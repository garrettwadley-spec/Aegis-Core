"""Canonical market-data ingestion for Aegis."""

from .bus import MARKET_DATA_RECEIVED, MarketDataBus
from .models import MarketData, RawMarketData, normalize_market_data
from .replay import ReplaySource

__all__ = [
    "MARKET_DATA_RECEIVED",
    "MarketData",
    "MarketDataBus",
    "RawMarketData",
    "ReplaySource",
    "normalize_market_data",
]
