from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    import requests

BINANCE_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_SMART_MONEY_URL = (
    "https://www.binance.com/bapi/futures/v1/public/future/smart-money/signal/overview"
)

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200
REQUEST_TIMEOUT = 10
FETCH_WORKERS = 12
CACHE_TTL_SECONDS = 60

_cache_lock = threading.Lock()
_cache_state: dict[str, Any] = {"timestamp": 0.0, "data": []}


@dataclass(frozen=True)
class ProfitRatio:
    symbol: str
    long_profit_ratio: float | None
    short_profit_ratio: float | None


def safe_ratio(numerator: float | int, denominator: float | int) -> float | None:
    if not denominator:
        return None
    return float(numerator) / float(denominator)


def parse_profit_ratio(symbol: str, payload: dict[str, Any]) -> ProfitRatio:
    data = payload.get("data") or {}
    long_profit = safe_ratio(
        data.get("longProfitTraders", 0),
        data.get("longTraders", 0),
    )
    short_profit = safe_ratio(
        data.get("shortProfitTraders", 0),
        data.get("shortTraders", 0),
    )
    return ProfitRatio(symbol=symbol, long_profit_ratio=long_profit, short_profit_ratio=short_profit)


def fetch_active_symbols(session: "requests.Session") -> list[str]:
    import requests

    response = session.get(BINANCE_EXCHANGE_INFO_URL, timeout=REQUEST_TIMEOUT)
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
            response = requests.get(
                BINANCE_SMART_MONEY_URL,
                params={"symbol": symbol},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return ProfitRatio(symbol=symbol, long_profit_ratio=None, short_profit_ratio=None)
        return parse_profit_ratio(symbol, payload)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        return list(executor.map(fetch_symbol, symbols))


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
        }
        for ratio in ratios
    ]


def create_app() -> "Flask":
    import requests
    from flask import Flask, jsonify, render_template, request

    app = Flask(__name__, static_folder="static", template_folder="templates")

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

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

        if not refresh and cache_is_fresh():
            ratios = get_cached_ratios()
        else:
            with requests.Session() as session:
                try:
                    symbols = fetch_active_symbols(session)
                except (requests.RequestException, ValueError) as exc:
                    return (
                        jsonify({"error": "Failed to fetch exchange info.", "details": str(exc)}),
                        502,
                    )

                ratios = fetch_profit_ratios(session, symbols)
            set_cached_ratios(ratios)

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

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    create_app().run(host="0.0.0.0", port=port, debug=True)
