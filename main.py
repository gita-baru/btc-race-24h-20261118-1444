"""cbBTC trend bot for make.fun btc-race-24h-20261118-1444.

Strategy (long only, one asset, $1,000 paper):
  * Enter when the 120-minute return first crosses above +0.4% (a fresh,
    edge-triggered momentum signal, not a level that re-fires every bar).
  * Exit on a 0.8% trailing stop from the highest close since entry, or,
    if the trade has not gained at least +0.3% after 300 bars, exit it as a
    dead trade. Both exits keep the bot out of slow chop, where a round
    trip costs ~26 bps in fees, slippage and price impact.
  * No trade until 241 closes of history are seen, so the 120-minute
    return is meaningful. Full cash on entry, full position on exit.

Why this shape: on the 24-hour dev window BTC drifts down -2.8% with one
sustained +1.9% rally and only small (+0.3-0.5%) bounces afterwards. Fast
signals (EMA 8/21, RSI, 60-minute returns) churn 20-80 trades and lose
$20-150 to fees and whipsaws; the slow 120-minute signal with a wide
trailing stop catches the one real leg and sits out the rest.

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
# Bars of history required before any trade: one full lookback window plus
# one bar, so the 120-minute return is computed on real closes.
WARMUP_BARS = 121
# Max slippage allowed from the latest close (5%): far above any normal
# 1-minute move plus impact, tight enough to refuse a dislocation.
MAX_SLIPPAGE_BPS = 500
# Minimum buy notional, 1 USDC in raw units.
MIN_NOTIONAL = 1_000_000


class Bot:
    def __init__(self):
        self.closes = []  # closes in raw price units, oldest first
        self.prev_cond = False  # entry condition on the previous batch
        self.entry = 0  # close at which the current position was decided
        self.peak = 0  # highest close since entry
        self.held = 0  # bars held in the current position
        self.pending_entry = None  # close of a buy sent but not yet filled

    def _cond(self):
        """True when the 120-minute return exceeds +0.4%."""
        if len(self.closes) <= LOOKBACK:
            return False
        return self.closes[-1] * ENTRY_DEN > self.closes[-1 - LOOKBACK] * ENTRY_NUM

    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []
        close = int(bar["c"])
        self.closes.append(close)
        if len(self.closes) <= WARMUP_BARS:
            self.prev_cond = self._cond()
            return []

        cond = self._cond()
        holding = state.positions.get(SYMBOL)
        qty = holding.qty if holding is not None else 0
        orders = []

        if qty <= 0:
            if self.pending_entry is not None:
                # The buy sent last batch never filled (rejected): forget it
                # and let the edge re-trigger if the signal is still fresh.
                self.pending_entry = None
                self.prev_cond = False
            elif cond and not self.prev_cond:
                cash = state.cash
                if cash >= MIN_NOTIONAL:
                    orders.append(
                        {
                            "side": "buy",
                            "symbol": SYMBOL,
                            "notional_quote_units": cash,
                            "max_slippage_bps": MAX_SLIPPAGE_BPS,
                        }
                    )
                    self.pending_entry = close
        else:
            if self.pending_entry is not None:
                # The position just appeared: anchor the trade on the close
                # the buy was decided at.
                self.entry = self.pending_entry
                self.peak = max(self.entry, close)
                self.held = 0
                self.pending_entry = None
            self.held += 1
            if close > self.peak:
                self.peak = close
            trail = (self.peak - close) * TRAIL_DEN > self.peak * TRAIL_NUM
            dead = (
                self.held >= TIME_EXIT_BARS
                and close * TIME_EXIT_DEN < self.entry * TIME_EXIT_NUM
            )
            if trail or dead:
                orders.append(
                    {
                        "side": "sell",
                        "symbol": SYMBOL,
                        "qty": qty,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                )
                self.entry = 0
                self.peak = 0
                self.held = 0

        self.prev_cond = cond
        return orders


makefun_bars.run(Bot().on_batch)
