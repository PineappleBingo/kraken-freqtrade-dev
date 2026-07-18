"""Conservative Kraken spot strategy for small accounts.

Trend-following pullback system on 1h candles:
  - only trade while EMA50 > EMA200 and price is above EMA200 (uptrend)
  - enter on an RSI dip (oversold pullback inside the uptrend)
  - exit on RSI overbought, ROI ladder, trailing stop or stoploss

Risk knobs (stoploss, minimal_roi, trailing stop, max_open_trades,
available_capital, protections) are NOT hardcoded here — they come from
config/risk_settings.json, which freqtrade loads last and which the Telegram
settings bot edits at runtime. Values below are only fallbacks.
"""

from freqtrade.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta


class KrakenSpotStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 210

    # Fallbacks — overridden by config/risk_settings.json.
    stoploss = -0.08
    minimal_roi = {"0": 0.04, "240": 0.025, "720": 0.015, "1440": 0.01}
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    rsi_entry_threshold = 35
    rsi_exit_threshold = 70

    @property
    def protections(self):
        # Editable via risk_settings.json -> companion.protections
        return self.config.get("companion", {}).get("protections", [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 4,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 48,
                "trade_limit": 6,
                "max_allowed_drawdown": 0.1,
                "stop_duration_candles": 24,
            },
        ])

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema50"] > dataframe["ema200"])
                & (dataframe["close"] > dataframe["ema200"])
                & (dataframe["rsi"] < self.rsi_entry_threshold)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["rsi"] > self.rsi_exit_threshold)
                & (dataframe["volume"] > 0)
            ),
            "exit_long",
        ] = 1
        return dataframe
