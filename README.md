# cbBTC trend bot — 120-min momentum, trailing stop

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/gita-baru/btc-race-24h-20261118-1444/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/gita-baru/btc-race-24h-20261118-1444/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

A Python 3.13 bot that trades Coinbase Wrapped BTC (cbBTC) on 1-minute on-chain bars with $1,000 of paper money, for make.fun's "Race a BTC trading bot live for 24 hours" bounty. Long-only, one position at a time, full cash in and full position out.

## Strategy (v2, hybrid)

- **Trend:** enter when the 120-minute return first crosses above +0.4% (edge-triggered); exit on a 0.8% trailing stop from the peak, or as a dead trade if it has not gained +0.3% after 300 bars.
- **Bounce:** buy the recovery from a sharp washout — the 30-minute return below −1.5% and the close recovered 0.3% above the lowest close of the last 15 bars; exit at +0.8%, a 0.5% trailing stop, or 60 bars held.

## Dev-window result

Net PnL **+$13.41** on the frozen 24-hour dev window (1,440 bars), 6 trades, max drawdown 1.49%, still +$9.78 at 2× fees. Deterministic: two runs produce byte-identical action logs.

## Run it

The bot speaks the `agent-fun/bars-replay/v1` protocol on stdin/stdout (hello → one batch per bar → done). Standard library only; the vendored `vendor/makefun_bars.py` is the kit's SDK, copied byte-for-byte.

```sh
python3 main.py < bars.ndjson
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=bhtec78s&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards</sub>
