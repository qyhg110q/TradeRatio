from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    import requests

BINANCE_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_SMART_MONEY_URL = (
    "https://www.binance.com/bapi/futures/v1/public/future/smart-money/signal/overview"
)
BINANCE_PRICE_URL = "https://fapi.binance.com/fapi/v1/ticker/price"
BINANCE_HEADERS = {"User-Agent": "Mozilla/5.0"}

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200
REQUEST_TIMEOUT = 6
FETCH_WORKERS = 24
CACHE_TTL_SECONDS = 60
SYMBOL_CACHE_TTL_SECONDS = 15
HISTORY_DB_PATH = os.environ.get("HISTORY_DB_PATH", "data/history.db")
DEFAULT_REFRESH_INTERVAL_SECONDS = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "30"))

_cache_lock = threading.Lock()
_cache_state: dict[str, Any] = {"timestamp": 0.0, "data": []}
_symbol_cache: dict[str, dict[str, Any]] = {}
_refresh_interval_lock = threading.Lock()
_refresh_interval_seconds = DEFAULT_REFRESH_INTERVAL_SECONDS
_refresh_thread_started = False
_refresh_stop_event = threading.Event()
_refresh_lock = threading.Lock()


@dataclass(frozen=True)
class ProfitRatio:
    symbol: str
    long_profit_ratio: float | None
    short_profit_ratio: float | None
    price: float | None


def safe_ratio(numerator: float | int, denominator: float | int) -> float | None:
    if not denominator:
        return None
    return float(numerator) / float(denominator)


def parse_profit_ratio(
    symbol: str, payload: dict[str, Any], price: float | None = None
) -> ProfitRatio:
    data = payload.get("data") or {}
    long_profit = safe_ratio(
        data.get("longProfitTraders", 0),
        data.get("longTraders", 0),
    )
    short_profit = safe_ratio(
        data.get("shortProfitTraders", 0),
        data.get("shortTraders", 0),
    )
    return ProfitRatio(
        symbol=symbol,
        long_profit_ratio=long_profit,
        short_profit_ratio=short_profit,
        price=price,
    )


def fetch_active_symbols(session: "requests.Session") -> list[str]:
    import requests

    response = session.get(
        BINANCE_EXCHANGE_INFO_URL, timeout=REQUEST_TIMEOUT, headers=BINANCE_HEADERS
    )
    response.raise_for_status()
    data = response.json()
    symbols = []
    for entry in data.get("symbols", []):
        if entry.get("status") != "TRADING":
            continue
        if entry.get("contractType") not in {"PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"}:
            continue
        symbol = entry.get("symbol")
        if symbol:
            symbols.append(symbol)
    return symbols


def fetch_profit_ratios(session: "requests.Session", symbols: Iterable[str]) -> list[ProfitRatio]:
    import requests

    def fetch_symbol(symbol: str) -> ProfitRatio:
        try:
            response = session.get(
                BINANCE_SMART_MONEY_URL,
                params={"symbol": symbol},
                timeout=REQUEST_TIMEOUT,
                headers=BINANCE_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return ProfitRatio(
                symbol=symbol, long_profit_ratio=None, short_profit_ratio=None, price=None
            )
        return parse_profit_ratio(symbol, payload)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        return list(executor.map(fetch_symbol, symbols))


def fetch_prices(session: "requests.Session") -> dict[str, float]:
    response = session.get(BINANCE_PRICE_URL, timeout=REQUEST_TIMEOUT, headers=BINANCE_HEADERS)
    response.raise_for_status()
    data = response.json()
    prices: dict[str, float] = {}
    for item in data:
        symbol = item.get("symbol")
        price_str = item.get("price")
        if symbol and price_str is not None:
            try:
                prices[symbol] = float(price_str)
            except (TypeError, ValueError):
                continue
    return prices


def init_history_db() -> None:
    os.makedirs(os.path.dirname(HISTORY_DB_PATH), exist_ok=True)
    with sqlite3.connect(HISTORY_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                symbol TEXT NOT NULL,
                ts INTEGER NOT NULL,
                price REAL,
                long_ratio REAL,
                short_ratio REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_symbol_ts ON history(symbol, ts)")


def record_ratios(ratios: Iterable[ProfitRatio], timestamp: int) -> None:
    rows = [
        (
            ratio.symbol,
            timestamp,
            ratio.price,
            ratio.long_profit_ratio,
            ratio.short_profit_ratio,
        )
        for ratio in ratios
    ]
    if not rows:
        return
    with sqlite3.connect(HISTORY_DB_PATH) as conn:
        conn.executemany(
            """
            INSERT INTO history (symbol, ts, price, long_ratio, short_ratio)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )


def get_symbol_history(symbol: str, limit: int = 500) -> list[dict[str, Any]]:
    with sqlite3.connect(HISTORY_DB_PATH) as conn:
        cursor = conn.execute(
            """
            SELECT ts, price, long_ratio, short_ratio
            FROM history
            WHERE symbol = ?
            ORDER BY ts ASC
            LIMIT ?
            """,
            (symbol, limit),
        )
        rows = cursor.fetchall()
    return [
        {
            "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "price": price,
            "longProfitRatio": long_ratio,
            "shortProfitRatio": short_ratio,
        }
        for ts, price, long_ratio, short_ratio in rows
    ]


def get_cached_ratios() -> list[ProfitRatio]:
    with _cache_lock:
        return list(_cache_state["data"])


def set_cached_ratios(ratios: list[ProfitRatio]) -> None:
    with _cache_lock:
        _cache_state["data"] = list(ratios)
        _cache_state["timestamp"] = time.time()


def cache_is_fresh() -> bool:
    with _cache_lock:
        timestamp = _cache_state["timestamp"]
    return (time.time() - timestamp) < CACHE_TTL_SECONDS


def get_cached_symbol(symbol: str) -> ProfitRatio | None:
    with _cache_lock:
        entry = _symbol_cache.get(symbol)
        if not entry:
            return None
        timestamp = entry.get("timestamp", 0.0)
        if (time.time() - timestamp) >= SYMBOL_CACHE_TTL_SECONDS:
            return None
        return entry.get("data")


def set_cached_symbol(symbol: str, ratio: ProfitRatio) -> None:
    with _cache_lock:
        _symbol_cache[symbol] = {"timestamp": time.time(), "data": ratio}


def get_refresh_interval_seconds() -> int:
    with _refresh_interval_lock:
        return _refresh_interval_seconds


def set_refresh_interval_seconds(value: int) -> int:
    sanitized = max(1, min(int(value), 3600))
    with _refresh_interval_lock:
        global _refresh_interval_seconds
        _refresh_interval_seconds = sanitized
    return sanitized


def _merge_with_cached_ratios(
    new_ratios: list[ProfitRatio], cached_ratios: list[ProfitRatio]
) -> list[ProfitRatio]:
    if not cached_ratios:
        return new_ratios
    cached_by_symbol = {ratio.symbol: ratio for ratio in cached_ratios}
    merged: list[ProfitRatio] = []
    for ratio in new_ratios:
        cached = cached_by_symbol.get(ratio.symbol)
        if not cached:
            merged.append(ratio)
            continue
        merged.append(
            ProfitRatio(
                symbol=ratio.symbol,
                long_profit_ratio=ratio.long_profit_ratio
                if ratio.long_profit_ratio is not None
                else cached.long_profit_ratio,
                short_profit_ratio=ratio.short_profit_ratio
                if ratio.short_profit_ratio is not None
                else cached.short_profit_ratio,
                price=ratio.price if ratio.price is not None else cached.price,
            )
        )
    return merged


def refresh_all_ratios(session: "requests.Session") -> list[ProfitRatio]:
    with _refresh_lock:
        symbols = fetch_active_symbols(session)
        ratios = fetch_profit_ratios(session, symbols)
        try:
            prices = fetch_prices(session)
        except (requests.RequestException, ValueError):
            prices = {}
        ratios = [
            ProfitRatio(
                symbol=ratio.symbol,
                long_profit_ratio=ratio.long_profit_ratio,
                short_profit_ratio=ratio.short_profit_ratio,
                price=prices.get(ratio.symbol),
            )
            for ratio in ratios
        ]
        if ratios and all(
            ratio.long_profit_ratio is None and ratio.short_profit_ratio is None
            for ratio in ratios
        ):
            raise ValueError("Smart money data unavailable.")
        cached_ratios = get_cached_ratios()
        ratios = _merge_with_cached_ratios(ratios, cached_ratios)
        set_cached_ratios(ratios)
        record_ratios(ratios, int(time.time()))
        return ratios


def background_refresh_loop() -> None:
    import requests

    with requests.Session() as session:
        while not _refresh_stop_event.is_set():
            start_time = time.time()
            try:
                refresh_all_ratios(session)
            except (requests.RequestException, ValueError) as exc:
                print(f"[refresh] failed to update ratios: {exc}")

            elapsed = time.time() - start_time
            interval = get_refresh_interval_seconds()
            sleep_for = max(1.0, interval - elapsed)
            _refresh_stop_event.wait(sleep_for)


def ensure_background_refresh_started() -> None:
    global _refresh_thread_started
    if _refresh_thread_started:
        return
    _refresh_thread_started = True
    thread = threading.Thread(target=background_refresh_loop, daemon=True)
    thread.start()


def sort_profit_ratios(
    ratios: list[ProfitRatio],
    sort_key: str,
    order: str,
) -> list[ProfitRatio]:
    if sort_key == "symbol":
        return sorted(ratios, key=lambda item: item.symbol, reverse=order == "desc")

    def ratio_key(value: float | None) -> tuple[bool, float]:
        is_none = value is None
        if is_none:
            return True, 0.0
        numeric = float(value)
        return False, -numeric if order == "desc" else numeric

    if sort_key == "long":
        return sorted(ratios, key=lambda item: ratio_key(item.long_profit_ratio))
    if sort_key == "short":
        return sorted(ratios, key=lambda item: ratio_key(item.short_profit_ratio))
    return sorted(ratios, key=lambda item: item.symbol)


def paginate(items: list[ProfitRatio], page: int, per_page: int) -> tuple[list[ProfitRatio], int]:
    total = len(items)
    if total == 0:
        return [], 0
    start = (page - 1) * per_page
    end = start + per_page
    if start >= total:
        return [], total
    return items[start:end], total


def serialize_ratios(ratios: Iterable[ProfitRatio]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": ratio.symbol,
            "longProfitRatio": ratio.long_profit_ratio,
            "shortProfitRatio": ratio.short_profit_ratio,
            "price": ratio.price,
        }
        for ratio in ratios
    ]


def serialize_ratio(ratio: ProfitRatio, stale: bool = False) -> dict[str, Any]:
    return {
        "symbol": ratio.symbol,
        "longProfitRatio": ratio.long_profit_ratio,
        "shortProfitRatio": ratio.short_profit_ratio,
        "price": ratio.price,
        "stale": stale,
    }


def create_app() -> "Flask":
    import requests
    from flask import Flask, jsonify, render_template, request

    app = Flask(__name__, static_folder="static", template_folder="templates")
    init_history_db()
    ensure_background_refresh_started()

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.route("/history")
    def history_view() -> str:
        return render_template("history.html")

    @app.route("/api/profit-ratios")
    def profit_ratios() -> Any:
        try:
            page = max(int(request.args.get("page", 1)), 1)
        except ValueError:
            page = 1
        try:
            per_page = int(request.args.get("per_page", DEFAULT_PER_PAGE))
        except ValueError:
            per_page = DEFAULT_PER_PAGE

        per_page = max(1, min(per_page, MAX_PER_PAGE))
        sort_key = request.args.get("sort", "symbol").lower()
        order = request.args.get("order", "asc").lower()
        if order not in {"asc", "desc"}:
            order = "asc"
        refresh = request.args.get("refresh") == "1"

        ratios = get_cached_ratios()
        if refresh:
            with requests.Session() as session:
                try:
                    ratios = refresh_all_ratios(session)
                except (requests.RequestException, ValueError) as exc:
                    if not ratios:
                        return (
                            jsonify({"error": "Failed to refresh ratios.", "details": str(exc)}),
                            502,
                        )
        elif not ratios:
            return jsonify({"error": "No cached data yet. Try again soon."}), 503

        ratios = sort_profit_ratios(ratios, sort_key, order)
        page_items, total = paginate(ratios, page, per_page)
        total_pages = math.ceil(total / per_page) if per_page else 0

        return jsonify(
            {
                "page": page,
                "perPage": per_page,
                "total": total,
                "totalPages": total_pages,
                "sort": sort_key,
                "order": order,
                "data": serialize_ratios(page_items),
            }
        )

    @app.route("/api/profit-ratio")
    def profit_ratio() -> Any:
        symbol = request.args.get("symbol", "").strip().upper()
        if not symbol:
            return jsonify({"error": "Symbol is required."}), 400

        cached_ratio = get_cached_symbol(symbol)
        if cached_ratio:
            return jsonify(serialize_ratio(cached_ratio))

        with requests.Session() as session:
            try:
                payload_response = session.get(
                    BINANCE_SMART_MONEY_URL,
                    params={"symbol": symbol},
                    timeout=REQUEST_TIMEOUT,
                    headers=BINANCE_HEADERS,
                )
                payload_response.raise_for_status()
                payload = payload_response.json()
            except (requests.RequestException, ValueError) as exc:
                fallback_ratio = get_cached_symbol(symbol)
                if fallback_ratio:
                    return jsonify(serialize_ratio(fallback_ratio, stale=True))
                return (
                    jsonify({"error": "Failed to fetch symbol profit ratio.", "details": str(exc)}),
                    502,
                )

            try:
                price_response = session.get(
                    BINANCE_PRICE_URL,
                    params={"symbol": symbol},
                    timeout=REQUEST_TIMEOUT,
                    headers=BINANCE_HEADERS,
                )
                price_response.raise_for_status()
                price_payload = price_response.json()
                price_value = float(price_payload.get("price"))
            except (requests.RequestException, ValueError, TypeError):
                price_value = None

        ratio = parse_profit_ratio(symbol, payload, price_value)
        set_cached_symbol(symbol, ratio)
        record_ratios([ratio], int(time.time()))
        return jsonify(serialize_ratio(ratio))

    @app.route("/api/history")
    def history() -> Any:
        symbol = request.args.get("symbol", "").strip().upper()
        if not symbol:
            return jsonify({"error": "Symbol is required."}), 400
        try:
            limit = int(request.args.get("limit", 500))
        except ValueError:
            limit = 500
        limit = max(1, min(limit, 2000))
        return jsonify({"symbol": symbol, "data": get_symbol_history(symbol, limit)})

    @app.route("/api/refresh-interval", methods=["GET", "POST"])
    def refresh_interval() -> Any:
        if request.method == "GET":
            return jsonify({"seconds": get_refresh_interval_seconds()})
        payload = request.get_json(silent=True) or {}
        value = payload.get("seconds", request.form.get("seconds", DEFAULT_REFRESH_INTERVAL_SECONDS))
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid seconds value."}), 400
        seconds = set_refresh_interval_seconds(seconds)
        return jsonify({"seconds": seconds})

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    create_app().run(host="0.0.0.0", port=port, debug=True)
