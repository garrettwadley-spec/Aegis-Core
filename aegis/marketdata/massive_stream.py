"""Bounded Massive U.S. equities WebSocket market-data adapter."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from math import ceil, isfinite
import os
from typing import Any

from websockets.asyncio.client import connect

from aegis.clock import system_clock

from .live_models import LiveQuote, LiveTrade


MASSIVE_API_KEY = "MASSIVE_API_KEY"
MASSIVE_WS_URL = "MASSIVE_WS_URL"
DEFAULT_MASSIVE_WS_URL = "wss://socket.massive.com/stocks"
DEFAULT_MASSIVE_SYMBOLS = ("SPY", "QQQ", "NVDA", "AAPL", "TSLA")
MAX_MASSIVE_SYMBOLS = 20


class MissingMassiveCredentialError(RuntimeError):
    pass


@dataclass(frozen=True)
class MassiveStreamStatus:
    connected: bool
    authenticated: bool
    subscribed: bool
    requested_symbols: tuple[str, ...]
    requested_subscriptions: tuple[str, ...]
    accepted_subscriptions: tuple[str, ...]
    rejected_subscriptions: tuple[str, ...]
    messages_received: int
    trades_received: int
    quotes_received: int
    control_messages_received: int
    malformed_messages: int
    reconnect_count: int
    dropped_messages: int
    endpoint: str
    last_error: str | None = None


@dataclass(frozen=True)
class LatencyStatistics:
    count: int
    minimum_ms: float | None
    mean_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    maximum_ms: float | None
    invalid_samples: int


@dataclass(frozen=True)
class CapacityStatistics:
    messages_per_second: tuple[tuple[str, int], ...]
    peak_messages_per_second: int
    handler_count: int
    mean_handler_processing_ms: float | None
    maximum_handler_processing_ms: float | None
    queue_depth: int
    dropped_messages: int
    malformed_messages: int


def massive_credential_present(
    environment: Mapping[str, str] | None = None,
) -> bool:
    source = os.environ if environment is None else environment
    return bool(source.get(MASSIVE_API_KEY, "").strip())


def parse_massive_sip_timestamp(value: object) -> datetime:
    """Convert Massive's Unix-millisecond SIP timestamp to UTC."""

    if isinstance(value, bool):
        raise ValueError("Massive SIP timestamp must be Unix milliseconds")
    try:
        milliseconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Massive SIP timestamp must be Unix milliseconds") from exc
    if not isfinite(milliseconds) or milliseconds <= 0:
        raise ValueError("Massive SIP timestamp must be positive and finite")
    try:
        return datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("Massive SIP timestamp is outside the supported range") from exc


def _event_type(message: Mapping[str, Any]) -> str:
    return str(message.get("ev", message.get("T", ""))).strip()


def normalize_massive_message(
    message: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
) -> LiveTrade | LiveQuote | None:
    """Normalize Massive T/Q messages and leave status messages separate."""

    event_type = _event_type(message)
    if event_type not in ("T", "Q"):
        return None
    observed_at = system_clock.now() if received_at is None else received_at
    source_timestamp = parse_massive_sip_timestamp(message.get("t"))
    if event_type == "T":
        conditions = tuple(str(item) for item in (message.get("c") or ()))
        return LiveTrade(
            symbol=message.get("sym", ""),
            price=message.get("p"),
            size=message.get("s"),
            exchange=message.get("x"),
            trade_id=message.get("i"),
            conditions=conditions,
            source_timestamp=source_timestamp,
            received_at=observed_at,
            source="massive",
            created_at=observed_at,
            _metadata={
                "provider_message_type": "trade",
                "provider_sequence": message.get("q"),
                "participant_timestamp": message.get("pt"),
                "tape": message.get("z"),
                "conditions": conditions,
            },
        )
    quote_condition = message.get("c")
    indicators = tuple(str(item) for item in (message.get("i") or ()))
    return LiveQuote(
        symbol=message.get("sym", ""),
        bid_price=message.get("bp"),
        bid_size=message.get("bs"),
        bid_exchange=message.get("bx"),
        ask_price=message.get("ap"),
        ask_size=message.get("as"),
        ask_exchange=message.get("ax"),
        source_timestamp=source_timestamp,
        received_at=observed_at,
        source="massive",
        created_at=observed_at,
        _metadata={
            "provider_message_type": "quote",
            "provider_sequence": message.get("q"),
            "tape": message.get("z"),
            "condition": quote_condition,
            "indicators": indicators,
        },
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, ceil(percentile * len(ordered)))
    return ordered[rank - 1]


class MassiveStockStreamAdapter:
    """Authenticate, subscribe, normalize, meter, and deliver Massive data."""

    def __init__(
        self,
        *,
        symbols: tuple[str, ...],
        observation_sink: Callable[[LiveTrade | LiveQuote], object],
        api_key: str,
        endpoint: str = DEFAULT_MASSIVE_WS_URL,
        max_attempts: int = 2,
        reconnect_delay_seconds: float = 1.0,
        connect_factory: Callable[..., Any] = connect,
    ) -> None:
        requested = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        if not requested:
            raise ValueError("Massive watchlist requires at least one symbol")
        if len(requested) > MAX_MASSIVE_SYMBOLS:
            raise ValueError(
                f"Massive watchlist cannot exceed {MAX_MASSIVE_SYMBOLS} symbols"
            )
        if any("*" in symbol for symbol in requested):
            raise ValueError("wildcard Massive subscriptions are prohibited")
        if not endpoint.strip().lower().startswith("wss://"):
            raise ValueError("Massive endpoint must use wss://")
        if max_attempts <= 0 or max_attempts > 3:
            raise ValueError("max_attempts must be between one and three")
        if reconnect_delay_seconds < 0 or reconnect_delay_seconds > 5:
            raise ValueError("reconnect delay must be between zero and five seconds")
        topics = tuple(
            [f"T.{symbol}" for symbol in requested]
            + [f"Q.{symbol}" for symbol in requested]
        )
        self._symbols = requested
        self._topics = topics
        self._observation_sink = observation_sink
        self._api_key = api_key
        self._endpoint = endpoint.strip()
        self._max_attempts = max_attempts
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._connect_factory = connect_factory
        self._latencies_ms: list[float] = []
        self._invalid_latency_samples = 0
        self._message_buckets: dict[str, int] = {}
        self._handler_times_ms: list[float] = []
        self._status = MassiveStreamStatus(
            connected=False,
            authenticated=False,
            subscribed=False,
            requested_symbols=requested,
            requested_subscriptions=topics,
            accepted_subscriptions=(),
            rejected_subscriptions=(),
            messages_received=0,
            trades_received=0,
            quotes_received=0,
            control_messages_received=0,
            malformed_messages=0,
            reconnect_count=0,
            dropped_messages=0,
            endpoint=self._endpoint,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        symbols: tuple[str, ...],
        observation_sink: Callable[[LiveTrade | LiveQuote], object],
        environment: Mapping[str, str] | None = None,
        max_attempts: int = 2,
        reconnect_delay_seconds: float = 1.0,
        connect_factory: Callable[..., Any] = connect,
    ) -> "MassiveStockStreamAdapter":
        source = os.environ if environment is None else environment
        if not massive_credential_present(source):
            raise MissingMassiveCredentialError("MASSIVE_API_KEY is required")
        return cls(
            symbols=symbols,
            observation_sink=observation_sink,
            api_key=source[MASSIVE_API_KEY],
            endpoint=source.get(MASSIVE_WS_URL, DEFAULT_MASSIVE_WS_URL)
            or DEFAULT_MASSIVE_WS_URL,
            max_attempts=max_attempts,
            reconnect_delay_seconds=reconnect_delay_seconds,
            connect_factory=connect_factory,
        )

    def __repr__(self) -> str:
        return (
            f"MassiveStockStreamAdapter(symbols={self._symbols!r}, "
            f"status={self._status!r})"
        )

    @property
    def status(self) -> MassiveStreamStatus:
        return self._status

    @property
    def latency_statistics(self) -> LatencyStatistics:
        values = self._latencies_ms
        return LatencyStatistics(
            count=len(values),
            minimum_ms=None if not values else min(values),
            mean_ms=None if not values else sum(values) / len(values),
            p50_ms=_percentile(values, 0.50),
            p95_ms=_percentile(values, 0.95),
            maximum_ms=None if not values else max(values),
            invalid_samples=self._invalid_latency_samples,
        )

    @property
    def capacity_statistics(self) -> CapacityStatistics:
        buckets = tuple(sorted(self._message_buckets.items()))
        timings = self._handler_times_ms
        return CapacityStatistics(
            messages_per_second=buckets,
            peak_messages_per_second=max((count for _, count in buckets), default=0),
            handler_count=len(timings),
            mean_handler_processing_ms=(
                None if not timings else sum(timings) / len(timings)
            ),
            maximum_handler_processing_ms=None if not timings else max(timings),
            queue_depth=0,
            dropped_messages=self._status.dropped_messages,
            malformed_messages=self._status.malformed_messages,
        )

    def _authentication_message(self) -> dict[str, str]:
        return {"action": "auth", "params": self._api_key}

    def subscription_message(self) -> dict[str, str]:
        return {"action": "subscribe", "params": ",".join(self._topics)}

    def handle_message(self, message: Mapping[str, Any]) -> LiveTrade | LiveQuote | None:
        """Separate controls, normalize market data, and record bounded metrics."""

        handler_start = system_clock.monotonic()
        received_at = system_clock.now()
        bucket = received_at.replace(microsecond=0).isoformat()
        self._message_buckets[bucket] = self._message_buckets.get(bucket, 0) + 1
        self._status = replace(
            self._status,
            messages_received=self._status.messages_received + 1,
        )
        try:
            event_type = _event_type(message)
            if event_type not in ("T", "Q"):
                if event_type.lower() == "status":
                    self._handle_control(message)
                else:
                    self._record_malformed(event_type)
                return None
            try:
                observation = normalize_massive_message(
                    message,
                    received_at=received_at,
                )
            except (TypeError, ValueError):
                self._record_malformed(event_type)
                return None
            if observation is None:
                self._record_malformed(event_type)
                return None
            self._record_latency(observation)
            if isinstance(observation, LiveTrade):
                self._status = replace(
                    self._status,
                    trades_received=self._status.trades_received + 1,
                )
            else:
                self._status = replace(
                    self._status,
                    quotes_received=self._status.quotes_received + 1,
                )
            try:
                self._observation_sink(observation)
            except Exception:
                self._status = replace(
                    self._status,
                    dropped_messages=self._status.dropped_messages + 1,
                    last_error="Normalized observation delivery failed",
                )
                raise
            return observation
        finally:
            elapsed_ms = max(0.0, (system_clock.monotonic() - handler_start) * 1000.0)
            self._handler_times_ms.append(elapsed_ms)

    def handle_payload(self, payload: str | bytes) -> tuple[LiveTrade | LiveQuote, ...]:
        try:
            decoded = json.loads(payload)
        except (TypeError, ValueError):
            self.handle_message({"ev": "invalid_payload"})
            return ()
        messages = decoded if isinstance(decoded, list) else [decoded]
        observations: list[LiveTrade | LiveQuote] = []
        for message in messages:
            if not isinstance(message, Mapping):
                self.handle_message({"ev": "invalid_payload_entry"})
                continue
            observation = self.handle_message(message)
            if observation is not None:
                observations.append(observation)
        return tuple(observations)

    async def run(self, *, max_seconds: float = 180.0) -> tuple[LiveTrade | LiveQuote, ...]:
        if not self._api_key.strip():
            raise MissingMassiveCredentialError("MASSIVE_API_KEY is required")
        if max_seconds <= 0 or max_seconds > 600:
            raise ValueError("max_seconds must be between zero and 600")
        observations: list[LiveTrade | LiveQuote] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_seconds
        for attempt in range(1, self._max_attempts + 1):
            self._status = replace(
                self._status,
                connected=False,
                authenticated=False,
                subscribed=False,
                reconnect_count=attempt - 1,
                last_error=None,
            )
            try:
                async with self._connect_factory(
                    self._endpoint,
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=20,
                    ping_timeout=10,
                ) as websocket:
                    self._status = replace(self._status, connected=True)
                    await websocket.send(json.dumps(self._authentication_message()))
                    await self._receive_until(
                        websocket,
                        deadline,
                        "authenticated",
                        observations,
                    )
                    await websocket.send(json.dumps(self.subscription_message()))
                    await self._receive_until(
                        websocket,
                        deadline,
                        "subscribed",
                        observations,
                    )
                    while loop.time() < deadline:
                        remaining = deadline - loop.time()
                        payload = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=remaining,
                        )
                        observations.extend(self.handle_payload(payload))
                    return tuple(observations)
            except asyncio.CancelledError:
                self._status = replace(
                    self._status,
                    last_error="CancelledError: stream cancelled",
                )
                raise
            except TimeoutError:
                if self._status.subscribed:
                    return tuple(observations)
                self._status = replace(
                    self._status,
                    last_error="TimeoutError: stream deadline reached",
                )
            except Exception as exc:
                self._status = replace(
                    self._status,
                    last_error=f"{type(exc).__name__}: connection attempt failed",
                )
            finally:
                self._status = replace(self._status, connected=False)
            if attempt < self._max_attempts and loop.time() < deadline:
                await asyncio.sleep(
                    min(
                        self._reconnect_delay_seconds,
                        max(0.0, deadline - loop.time()),
                    )
                )
        return tuple(observations)

    async def _receive_until(
        self,
        websocket: Any,
        deadline: float,
        status_field: str,
        observations: list[LiveTrade | LiveQuote],
    ) -> None:
        loop = asyncio.get_running_loop()
        while not getattr(self._status, status_field):
            remaining = min(10.0, deadline - loop.time())
            if remaining <= 0:
                raise TimeoutError
            payload = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            observations.extend(self.handle_payload(payload))
            if self._status.last_error is not None:
                raise RuntimeError("Massive rejected authentication or subscription")

    def _handle_control(self, message: Mapping[str, Any]) -> None:
        status = str(message.get("status", "")).strip().lower()
        text = str(message.get("message", "")).strip().lower()
        self._status = replace(
            self._status,
            control_messages_received=self._status.control_messages_received + 1,
        )
        if status in ("auth_success", "authenticated") or "authenticated" in text:
            self._status = replace(self._status, authenticated=True)
            return
        if status in ("success", "subscribed") and "subscrib" in text:
            mentioned = tuple(topic for topic in self._topics if topic.lower() in text)
            acknowledged = mentioned or self._topics
            accepted_set = set(self._status.accepted_subscriptions) | set(acknowledged)
            accepted = tuple(topic for topic in self._topics if topic in accepted_set)
            rejected = tuple(topic for topic in self._topics if topic not in accepted)
            self._status = replace(
                self._status,
                subscribed=set(accepted) == set(self._topics),
                accepted_subscriptions=accepted,
                rejected_subscriptions=rejected,
            )
            return
        if status in ("auth_failed", "error", "failed"):
            self._status = replace(
                self._status,
                rejected_subscriptions=tuple(
                    topic
                    for topic in self._topics
                    if topic not in self._status.accepted_subscriptions
                ),
                last_error=f"Massive status error: {status or 'unknown'}",
            )

    def _record_latency(self, observation: LiveTrade | LiveQuote) -> None:
        latency_ms = (
            observation.received_at - observation.source_timestamp
        ).total_seconds() * 1000.0
        if not isfinite(latency_ms) or latency_ms < 0:
            self._invalid_latency_samples += 1
            return
        self._latencies_ms.append(latency_ms)

    def _record_malformed(self, message_type: str) -> None:
        safe_type = message_type if message_type in ("T", "Q") else "unknown"
        self._status = replace(
            self._status,
            malformed_messages=self._status.malformed_messages + 1,
            last_error=f"Malformed Massive {safe_type} message",
        )
