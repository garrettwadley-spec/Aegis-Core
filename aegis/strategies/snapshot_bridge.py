"""Connect canonical market snapshots to the existing strategy interface."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aegis.eventbus import Event, Subscriber
from aegis.marketdata import OpeningRangeFactors
from aegis.snapshot import MarketSnapshot
from aegis.strategies.signal import MarketSignal
from aegis.strategies.strategy_base import StrategyBase


class SnapshotStrategyBridge(Subscriber):
    """Evaluate current snapshot records through an unchanged StrategyBase."""

    def __init__(
        self,
        strategy: StrategyBase,
        configuration: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        opening_range_factors: Mapping[str, OpeningRangeFactors] | None = None,
    ) -> None:
        self._strategy = strategy
        self._configuration = {
            symbol.strip().upper(): dict(values)
            for symbol, values in (configuration or {}).items()
            if symbol.strip()
        }
        self._opening_range_factors = {
            symbol.strip().upper(): factors
            for symbol, factors in (opening_range_factors or {}).items()
            if symbol.strip()
        }
        self._last_evaluated_symbols: tuple[str, ...] = ()
        self._last_signals: tuple[MarketSignal, ...] = ()

    @property
    def strategy_name(self) -> str:
        return self._strategy.name

    @property
    def last_evaluated_symbols(self) -> tuple[str, ...]:
        return self._last_evaluated_symbols

    @property
    def last_signals(self) -> tuple[MarketSignal, ...]:
        return self._last_signals

    def receive(self, event: Event) -> None:
        self.evaluate(event.payload)

    def evaluate(self, snapshot: MarketSnapshot) -> tuple[MarketSignal, ...]:
        evaluated_symbols: list[str] = []
        signals: list[MarketSignal] = []

        for market_data, source_sequence in zip(
            snapshot.market_data,
            snapshot.source_event_sequences,
        ):
            factors = self._opening_range_factors.get(market_data.symbol)
            configured_inputs = self._configuration.get(market_data.symbol)
            if factors is None and configured_inputs is None:
                continue

            if factors is not None:
                if factors.current_price != market_data.last:
                    raise ValueError(
                        "derived factors do not match snapshot current price"
                    )
                if source_sequence not in factors.source_event_sequences:
                    raise ValueError(
                        "derived factors do not include snapshot event provenance"
                    )
                strategy_input = dict(factors.strategy_values())
                strategy_input["opening_range_factors_id"] = factors.object_id
                strategy_input["input_origin"] = factors.input_origin
            else:
                strategy_input = dict(configured_inputs or {})
            strategy_input.update(
                {
                    "symbol": market_data.symbol,
                    "exchange": market_data.exchange,
                    "bid": market_data.bid,
                    "ask": market_data.ask,
                    "last": market_data.last,
                    "volume": market_data.volume,
                    "source": market_data.source,
                    "source_timestamp": market_data.source_timestamp,
                    "received_at": market_data.received_at,
                    "snapshot_as_of": snapshot.as_of,
                    "source_event_sequence": source_sequence,
                }
            )
            evaluated_symbols.append(market_data.symbol)
            signal = self._strategy.evaluate(strategy_input)
            if signal is not None:
                signals.append(signal)

        self._last_evaluated_symbols = tuple(evaluated_symbols)
        self._last_signals = tuple(signals)
        return self._last_signals
