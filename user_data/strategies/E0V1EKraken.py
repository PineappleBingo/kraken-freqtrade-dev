"""E0V1EKraken — Kraken-fee-aware adaptation of the community 'E0V1E' scalper.

Origin: ssssi/freqtrade_strs "E0V1E" (one of the most-copied community
strategies). Core idea kept: buy sharp short-term RSI dips while the slower
RSI is falling and price sits below its short SMA band; exit into strength
(stochastic %K spike).

Kraken adaptations (the original targets Binance ~0.2% round-trip fees on 5m):
  - 15m timeframe instead of 5m (fewer, larger moves; less fee churn)
  - long-term uptrend filter (close > EMA200) — dips are only bought in
    healthy markets
  - profit floor tuned for Kraken's ~0.5-0.8% round trip: the ROI ladder
    never accepts less than 1.7% gross (~1%+ net), and the strength-exit
    only fires above the same floor
  - limit entry orders (maker fee) via config order_types

Entry/exit thresholds are hyperoptable -> tune with `scripts/lab.sh hyperopt`.
Risk knobs (stoploss, trailing, max_open_trades, protections) come from
config/risk_settings.json, same as KrakenSpotStrategy.
"""

from datetime import datetime

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame

# Gross profit floor ≈ 1%+ net after Kraken round-trip fees.
MIN_GROSS_PROFIT = 0.017


class E0V1EKraken(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 210

    # Fallbacks — overridden by config/risk_settings.json.
    stoploss = -0.08
    minimal_roi = {"0": 0.03, "120": 0.025, "300": 0.02, "600": MIN_GROSS_PROFIT}
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False

    # ── hyperoptable attributes (lab.sh hyperopt --spaces buy sell) ────────
    buy_rsi_fast = IntParameter(20, 45, default=35, space="buy", optimize=True)
    buy_rsi = IntParameter(15, 35, default=24, space="buy", optimize=True)
    buy_sma_offset = DecimalParameter(0.940, 0.990, default=0.970, decimals=3,
                                      space="buy", optimize=True)
    sell_fastk = IntParameter(60, 90, default=75, space="sell", optimize=True)

    @property
    def protections(self):
        return self.config.get("companion", {}).get("protections", [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,
                "trade_limit": 4,
                "stop_duration_candles": 48,
                "only_per_pair": False,
            },
        ])

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma_15"] = ta.SMA(dataframe, timeperiod=15)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=4)
        dataframe["rsi_slow"] = ta.RSI(dataframe, timeperiod=20)
        stoch = ta.STOCHF(dataframe, fastk_period=5, fastd_period=3)
        dataframe["fastk"] = stoch["fastk"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["close"] > dataframe["ema200"])
                & (dataframe["rsi_slow"] < dataframe["rsi_slow"].shift(1))
                & (dataframe["rsi_fast"] < self.buy_rsi_fast.value)
                & (dataframe["rsi"] > self.buy_rsi.value)
                & (dataframe["close"] < dataframe["sma_15"]
                   * self.buy_sma_offset.value)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exits are handled by custom_exit / ROI / trailing / stoploss.
        return dataframe

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        """Exit into strength — but never below the fee-aware profit floor."""
        if current_profit < MIN_GROSS_PROFIT:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None
        last = dataframe.iloc[-1]
        if last["fastk"] > self.sell_fastk.value:
            return "fastk_strength"
        return None
