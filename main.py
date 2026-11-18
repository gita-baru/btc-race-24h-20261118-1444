"""cbBTC hybrid bot for make.fun btc-race-24h-20261118-1444 (v2).

Strategy (long only, one asset, $1,000 paper): two independent entries,
both full cash in and full position out, never overlapping.

TREND (carried over from v1, unchanged):
  * Enter when the 120-minute return first crosses above +0.4% (a fresh,
    edge-triggered momentum signal, not a level that re-fires every bar).
  * Exit on a 0.8% trailing stop from the highest close since entry, or,
    if the trade has not gained at least +0.3% after 300 bars, exit it as a
    dead trade. Both exits keep the bot out of slow chop, where a round
    trip costs ~26 bps in fees, slippage and price impact.
  * No trend trade until 122 closes of history are seen, so the 120-minute
    return is meaningful.

BOUNCE (new in v2): buy the recovery from a sharp intraday washout.
  * Trigger: the 30-minute return is below -1.5% (a capitulation drop)
    AND the close has recovered 0.3% above the lowest close of the last
    15 bars (the turn is confirmed, not guessed at the low).
  * Exit on the first of: +0.8% profit from the decision close, a 0.5%
    trailing stop from the highest close since entry, or 60 bars held.
  * Active from 32 closes of history, so it can catch a washout early in
    the window; the trend leg still needs its full 120-bar lookback.

Why this shape: on the 24-hour dev window BTC drifts down -2.8% with one
sustained +1.9% rally and one sharp early washout (-2.4% in 30 minutes,
then a +1.4% bounce in 10 bars). Fast signals (EMA 8/21, RSI, 60-minute
returns) churn 20-80 trades and lose $20-150 to fees and whipsaws; SMA-dip
and washout dip-buy rules lose too, because dips keep dipping in the
downtrend and the 1-bar fill lag eats the capture. The slow 120-minute
trend leg catches the rally; the bounce leg catches the one washout
recovery. The bounce parameters are not knife-edge: drop thresholds
-1.0% to -2.0%, recovery 0.2% to 0.5% and low lookbacks 5 to 30 bars all
produce the same trade on the dev window; only the +0.8% profit target
matters (a +1.2% target is never reached before the bounce fades).

Dev-window validation (local simulator, exact against the official
grade-local baselines buy-and-hold -$31.63 and ema-cross -$148.17):
  v2 hybrid  +$13.41  (6 trades, max drawdown 1.49%)
  v1 trend   +$7.59   (4 trades, max drawdown 1.45%)
  First half +$14.80, second half -$1.34, PnL at 2x fees +$9.78.
  A 240-minute trend filter was tried and rejected: it delays the rally
  entry and moves the second-half loss to -$6.30.

All comparisons are integer arithmetic on the harness's raw price units,
so two runs on the same data produce byte-identical action logs. No wall
clock, no network, no files, no randomness; the only state is the close
history and the position tracking below.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
# --- Trend leg (v1) ---
# Enter when close * 1000 > close_120_bars_ago * 1004  (120-min return > +0.4%).
LOOKBACK = 120
ENTRY_NUM = 1004
ENTRY_DEN = 1000
# Trailing stop: exit when (peak - close) * 1000 > peak * 8  (0.8% below peak).
TRAIL_NUM = 8
TRAIL_DEN = 1000
# Dead-trade exit: after 300 bars, exit if close * 1000 < entry * 1003
# (unrealised return below +0.3%).
TIME_EXIT_BARS = 300
TIME_EXIT_NUM = 1003
TIME_EXIT_DEN = 1000
# Bars of history required before any trend trade: one full lookback window
# plus one bar, so the 120-minute return is computed on real closes.
WARMUP_BARS = 121
# --- Bounce leg (v2) ---
# Trigger: 30-minute return below -1.5% (close * 1000 < close_30_ago * 985)
# and close 0.3% above the lowest close of the previous 15 bars
# (close * 1000 > low15 * 1003).
BOUNCE_DROP_N = 30
BOUNCE_DROP_NUM = 985
BOUNCE_DROP_DEN = 1000
BOUNCE_LOW_N = 15
BOUNCE_REC_NUM = 1003
BOUNCE_REC_DEN = 1000
# Bounce exit: +0.8% profit (close * 1000 >= entry * 1008), 0.5% trailing
# stop ((peak - close) * 1000 > peak * 5), or 60 bars held.
BOUNCE_TP_NUM = 1008
BOUNCE_TP_DEN = 1000
BOUNCE_TRAIL_NUM = 5
BOUNCE_TRAIL_DEN = 1000
BOUNCE_MAX_HOLD = 60
# Closes of history required before any bounce trade: 30 for the drop plus
# one bar for the current close and one for the low window.
BOUNCE_WARMUP = 32
# Max slippage allowed from the latest close (5%): far above any normal
# 1-minute move plus impact, tight enough to refuse a dislocation.
MAX_SLIPPAGE_BPS = 500
# Minimum buy notional, 1 USDC in raw units.
MIN_NOTIONAL = 1_000_000


class Bot:
    def __init__(self):
        self.closes = []  # closes in raw price units, oldest first
        self.prev_cond = False  # trend entry condition on the previous batch
        self.entry = 0  # close at which the current position was decided
        self.peak = 0  # highest close since entry
        self.held = 0  # bars held in the current position
        self.mode = None  # "trend" or "bounce" for the open position
        self.pending_entry = None  # close of a buy sent but not yet filled
        self.pending_mode = None  # mode of the pending buy

    def _trend_cond(self):
        """True when the 120-minute return exceeds +0.4%."""
        if len(self.closes) <= LOOKBACK:
            return False
        return self.closes[-1] * ENTRY_DEN > self.closes[-1 - LOOKBACK] * ENTRY_NUM

    def _bounce_cond(self):
        """True after a sharp 30-minute drop once the close has recovered
        0.3% above the lowest close of the previous 15 bars."""
        if len(self.closes) < BOUNCE_WARMUP:
            return False
        close = self.closes[-1]
        if close * BOUNCE_DROP_DEN >= self.closes[-1 - BOUNCE_DROP_N] * BOUNCE_DROP_NUM:
            return False
        low = min(self.closes[-1 - BOUNCE_LOW_N:-1])
        return close * BOUNCE_REC_DEN > low * BOUNCE_REC_NUM

    def _buy(self, state, close, mode):
        cash = state.cash
        if cash < MIN_NOTIONAL:
            return []
        self.pending_entry = close
        self.pending_mode = mode
        return [
            {
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": cash,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        ]

    def _sell(self, qty):
        self.entry = 0
        self.peak = 0
        self.held = 0
        self.mode = None
        return [
            {
                "side": "sell",
                "symbol": SYMBOL,
                "qty": qty,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        ]

    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []
        close = int(bar["c"])
        self.closes.append(close)
        if len(self.closes) < BOUNCE_WARMUP:
            return []

        # The trend leg only becomes meaningful once a full lookback plus
        # one bar of history is present; before that its condition is False
        # and the edge can never fire early.
        trend_ok = len(self.closes) > WARMUP_BARS
        cond = self._trend_cond() if trend_ok else False
        holding = state.positions.get(SYMBOL)
        qty = holding.qty if holding is not None else 0
        orders = []

        if qty <= 0:
            if self.pending_entry is not None:
                # The buy sent last batch never filled (rejected): forget it
                # and let the edge re-trigger if the signal is still fresh.
                self.pending_entry = None
                self.pending_mode = None
                self.prev_cond = False
            elif trend_ok and cond and not self.prev_cond:
                orders = self._buy(state, close, "trend")
            elif self._bounce_cond():
                orders = self._buy(state, close, "bounce")
        else:
            if self.pending_entry is not None:
                # The position just appeared: anchor the trade on the close
                # the buy was decided at.
                self.entry = self.pending_entry
                self.peak = max(self.entry, close)
                self.held = 0
                self.mode = self.pending_mode
                self.pending_entry = None
                self.pending_mode = None
            self.held += 1
            if close > self.peak:
                self.peak = close
            if self.mode == "trend":
                trail = (self.peak - close) * TRAIL_DEN > self.peak * TRAIL_NUM
                dead = (
                    self.held >= TIME_EXIT_BARS
                    and close * TIME_EXIT_DEN < self.entry * TIME_EXIT_NUM
                )
                if trail or dead:
                    orders = self._sell(qty)
            else:  # bounce: profit target, trailing stop, or max hold
                target = close * BOUNCE_TP_DEN >= self.entry * BOUNCE_TP_NUM
                trail = (self.peak - close) * BOUNCE_TRAIL_DEN > self.peak * BOUNCE_TRAIL_NUM
                stale = self.held >= BOUNCE_MAX_HOLD
                if target or trail or stale:
                    orders = self._sell(qty)

        self.prev_cond = cond
        return orders


makefun_bars.run(Bot().on_batch)
