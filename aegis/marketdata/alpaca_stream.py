"""Minimal Alpaca stock WebSocket market-data adapter."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
import json
import os
from typing import Any

from websockets.asyncio.client import connect

from aegis.clock import system_clock

from .live_models import LiveQuote, LiveTrade, parse_source_timestamp


ALPACA_API_KEY = "ALPACA_API_KEY"
ALPACA_API_SECRET = "ALPACA_API_SECRET"
ALPACA_DATA_FEED = "ALPACA_DATA_FEED"
ALPACA_CREDENTIAL_VARIABLES = (
    ALPACA_API_KEY,
    ALPACA_API_SECRET,
    ALPACA_DATA_FEED,
)
ALPACA_STREAM_ROOT = "wss://stream.data.alpaca.markets/v2"
MAX_LIVE_SYMBOLS = 20


class AlpacaStreamMode(str, Enum):
    TEST = "test"
    LIVE_IEX = "iex"
    LIVE_SIP = "sip"


class MissingAlpacaCredentialsError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlpacaSubscriptionStatus:
    connected: bool
    authenticated: bool
    subscribed: bool
    requested_symbols: tuple[str, ...]
    accepted_symbols: tuple[str, ...]
    rejected_symbols: tuple[str, ...]
    selected_feed: str
    coverage_classification: str
    connection_attempts: int = 0
    last_error: str | None = None


def credential_variables_present(
    environment: Mapping[str, str] | None = None,
) -> bool:
    source = os.environ if environment is None else environment
    return all(bool(source.get(name, "").strip()) for name in ALPACA_CREDENTIAL_VARIABLES)


def _message_type(message: Mapping[str, Any]) -> str:
    return str(message.get("T", "")).strip().lower()


def normalize_alpaca_message(
    message: Mapping[str, Any],
) -> LiveTrade | LiveQuote | None:
    """Normalize an Alpaca trade or quote and ignore control messages."""

    message_type = _message_type(message)
    received_at = system_clock.now()
    if message_type == "t":
        return LiveTrade(
            symbol=message.get("S", ""),
            price=message.get("p"),
            size=message.get("s"),
            exchange=message.get("x"),
            source_timestamp=parse_source_timestamp(message.get("t")),
            received_at=received_at,
            source="alpaca",
            trade_id=message.get("i"),
            conditions=tuple(message.get("c") or ()),
            created_at=received_at,
            _metadata={"provider_message_type": "trade"},
        )
    if message_type == "q":
        return LiveQuote(
            symbol=message.get("S", ""),
            bid_price=message.get("bp"),
            bid_size=message.get("bs"),
            ask_price=message.get("ap"),
            ask_size=message.get("as"),
            bid_exchange=message.get("bx"),
            ask_exchange=message.get("ax"),
            source_timestamp=parse_source_timestamp(message.get("t")),
            received_at=received_at,
            source="alpaca",
            created_at=received_at,
            _metadata={"provider_message_type": "quote"},
        )
    return None


class AlpacaStockStreamAdapter:
    """Authenticate, subscribe, normalize, and deliver Alpaca observations."""

    def __init__(
        self,
        *,
        mode: AlpacaStreamMode,
        symbols: tuple[str, ...],
        observation_sink: Callable[[LiveTrade | LiveQuote], object],
        api_key: str,
        api_secret: str,
        max_attempts: int = 2,
    ) -> None:
        requested = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
        if mode == AlpacaStreamMode.TEST:
            if requested not in ((), ("FAKEPACA",)):
                raise ValueError("TEST mode supports FAKEPACA only")
            requested = ("FAKEPACA",)
        elif not requested:
            raise ValueError("live modes require at least one symbol")
        if mode != AlpacaStreamMode.TEST and len(requested) > MAX_LIVE_SYMBOLS:
            raise ValueError(f"live watchlist cannot exceed {MAX_LIVE_SYMBOLS} symbols")
        if max_attempts <= 0 or max_attempts > 3:
            raise ValueError("max_attempts must be between one and three")
        self._mode = mode
        self._symbols = requested
        self._observation_sink = observation_sink
        self._api_key = api_key
        self._api_secret = api_secret
        self._max_attempts = max_attempts
        self._status = AlpacaSubscriptionStatus(
            connected=False,
            authenticated=False,
            subscribed=False,
            requested_symbols=requested,
            accepted_symbols=(),
            rejected_symbols=(),
            selected_feed=mode.value,
            coverage_classification=(
                "TEST_FEED"
                if mode == AlpacaStreamMode.TEST
                else "IEX_ONLY"
                if mode == AlpacaStreamMode.LIVE_IEX
                else "CONSOLIDATED_SIP"
            ),
        )

    @classmethod
    def from_environment(
        cls,
        *,
        mode: AlpacaStreamMode,
        symbols: tuple[str, ...],
        observation_sink: Callable[[LiveTrade | LiveQuote], object],
        environment: Mapping[str, str] | None = None,
        max_attempts: int = 2,
    ) -> "AlpacaStockStreamAdapter":
        source = os.environ if environment is None else environment
        if not credential_variables_present(source):
            raise MissingAlpacaCredentialsError(
                "ALPACA_API_KEY, ALPACA_API_SECRET, and ALPACA_DATA_FEED are required"
            )
        configured_feed = source[ALPACA_DATA_FEED].strip().lower()
        if (
            mode != AlpacaStreamMode.TEST
            and configured_feed
            and configured_feed != mode.value
        ):
            raise ValueError("ALPACA_DATA_FEED does not match the selected stream mode")
        return cls(
            mode=mode,
            symbols=symbols,
            observation_sink=observation_sink,
            api_key=source[ALPACA_API_KEY],
            api_secret=source[ALPACA_API_SECRET],
            max_attempts=max_attempts,
        )

    def __repr__(self) -> str:
        return (
            f"AlpacaStockStreamAdapter(mode={self._mode.name}, "
            f"symbols={self._symbols!r}, status={self._status!r})"
        )

    @property
    def endpoint(self) -> str:
        return f"{ALPACA_STREAM_ROOT}/{self._mode.value}"

    @property
    def status(self) -> AlpacaSubscriptionStatus:
        return self._status

    def handle_message(self, message: Mapping[str, Any]) -> LiveTrade | LiveQuote | None:
        """Normalize before any message is delivered beyond the adapter."""

        observation = normalize_alpaca_message(message)
        if observation is not None:
            self._observation_sink(observation)
            return observation
        self._handle_control(message)
        return None

    def handle_payload(self, payload: str | bytes) -> tuple[LiveTrade | LiveQuote, ...]:
        decoded = json.loads(payload)
        messages = decoded if isinstance(decoded, list) else [decoded]
        observations: list[LiveTrade | LiveQuote] = []
        for message in messages:
            if not isinstance(message, Mapping):
                raise ValueError("Alpaca payload entries must be objects")
            observation = self.handle_message(message)
            if observation is not None:
                observations.append(observation)
        return tuple(observations)

    async def run(self, *, max_seconds: float = 90.0) -> tuple[LiveTrade | LiveQuote, ...]:
        if not self._api_key.strip() or not self._api_secret.strip():
            raise MissingAlpacaCredentialsError("Alpaca credential variables are required")
        if max_seconds <= 0 or max_seconds > 90:
            raise ValueError("max_seconds must be between zero and 90")
        observations: list[LiveTrade | LiveQuote] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_seconds
        for attempt in range(1, self._max_attempts + 1):
            self._status = replace(
                self._status,
                connected=False,
                authenticated=False,
                subscribed=False,
                connection_attempts=attempt,
                last_error=None,
            )
            try:
                async with connect(
                    self.endpoint,
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=20,
                    ping_timeout=10,
                ) as websocket:
                    self._status = replace(self._status, connected=True)
                    await websocket.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": self._api_key,
                                "secret": self._api_secret,
                            }
                        )
                    )
                    await self._receive_until(websocket, deadline, "authenticated", observations)
                    await websocket.send(
                        json.dumps(
                            {
                                "action": "subscribe",
                                "trades": list(self._symbols),
                                "quotes": list(self._symbols),
                            }
                        )
                    )
                    await self._receive_until(websocket, deadline, "subscribed", observations)
                    while loop.time() < deadline:
                        remaining = deadline - loop.time()
                        payload = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                        observations.extend(self.handle_payload(payload))
                    return tuple(observations)
            except TimeoutError:
                if self._status.subscribed:
                    return tuple(observations)
                self._status = replace(self._status, last_error="TimeoutError: stream deadline reached")
            except Exception as exc:
                self._status = replace(
                    self._status,
                    last_error=f"{type(exc).__name__}: connection attempt failed",
                )
            finally:
                self._status = replace(self._status, connected=False)
            if attempt < self._max_attempts and loop.time() < deadline:
                await asyncio.sleep(min(float(attempt), max(0.0, deadline - loop.time())))
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
                raise RuntimeError("Alpaca stream rejected authentication or subscription")

    def _handle_control(self, message: Mapping[str, Any]) -> None:
        message_type = _message_type(message)
        text = str(message.get("msg", "")).lower()
        if message_type == "success" and text == "authenticated":
            self._status = replace(self._status, authenticated=True)
            return
        if message_type == "subscription":
            trades = {str(item).upper() for item in message.get("trades", ())}
            quotes = {str(item).upper() for item in message.get("quotes", ())}
            accepted = tuple(symbol for symbol in self._symbols if symbol in trades and symbol in quotes)
            rejected = tuple(symbol for symbol in self._symbols if symbol not in accepted)
            self._status = replace(
                self._status,
                subscribed=bool(accepted),
                accepted_symbols=accepted,
                rejected_symbols=rejected,
            )
            return
        if message_type == "error":
            self._status = replace(
                self._status,
                last_error=f"Alpaca stream error code {message.get('code', 'unknown')}",
            )
