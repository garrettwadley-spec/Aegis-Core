"""Canonical market-data ingestion for Aegis."""

from .bus import MARKET_DATA_RECEIVED, MarketDataBus
from .history import CanonicalMarketHistory, MarketHistoryObservation
from .models import MarketData, RawMarketData, normalize_market_data
from .orb_factors import (
    CANONICAL_FACTOR_ORIGIN,
    CANONICAL_REPLAY_STRATEGY_EVIDENCE,
    SYNTHETIC_FACTOR_ORIGIN,
    InsufficientHistoryError,
    InvalidMarketHistoryError,
    MACDCalculation,
    OpeningRangeCalculationConfig,
    OpeningRangeFactorCalculator,
    OpeningRangeFactors,
    calculate_macd,
    calculate_wilder_rsi,
)
from .replay import ReplaySource

__all__ = [
    "CANONICAL_FACTOR_ORIGIN",
    "CANONICAL_REPLAY_STRATEGY_EVIDENCE",
    "CanonicalMarketHistory",
    "InsufficientHistoryError",
    "InvalidMarketHistoryError",
    "MARKET_DATA_RECEIVED",
    "MACDCalculation",
    "MarketData",
    "MarketDataBus",
    "MarketHistoryObservation",
    "OpeningRangeCalculationConfig",
    "OpeningRangeFactorCalculator",
    "OpeningRangeFactors",
    "RawMarketData",
    "ReplaySource",
    "SYNTHETIC_FACTOR_ORIGIN",
    "calculate_macd",
    "calculate_wilder_rsi",
    "normalize_market_data",
]
