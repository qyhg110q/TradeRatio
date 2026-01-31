import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import ProfitRatio, paginate, parse_profit_ratio, safe_ratio, sort_profit_ratios


def test_safe_ratio_handles_zero():
    assert safe_ratio(1, 0) is None
    assert safe_ratio(0, 0) is None


def test_safe_ratio_returns_float():
    assert safe_ratio(5, 2) == 2.5


def test_parse_profit_ratio():
    payload = {
        "data": {
            "longProfitTraders": 12,
            "longTraders": 48,
            "shortProfitTraders": 21,
            "shortTraders": 70,
        }
    }
    ratio = parse_profit_ratio("TESTUSDT", payload)
    assert ratio.symbol == "TESTUSDT"
    assert ratio.long_profit_ratio == pytest.approx(0.25)
    assert ratio.short_profit_ratio == pytest.approx(0.3)


def test_sort_profit_ratios_by_long_desc():
    ratios = [
        ProfitRatio("AAA", long_profit_ratio=0.1, short_profit_ratio=0.2),
        ProfitRatio("BBB", long_profit_ratio=0.9, short_profit_ratio=0.3),
        ProfitRatio("CCC", long_profit_ratio=None, short_profit_ratio=0.4),
    ]
    sorted_ratios = sort_profit_ratios(ratios, "long", "desc")
    assert [ratio.symbol for ratio in sorted_ratios] == ["BBB", "AAA", "CCC"]


def test_sort_profit_ratios_by_short_asc():
    ratios = [
        ProfitRatio("AAA", long_profit_ratio=0.1, short_profit_ratio=0.2),
        ProfitRatio("BBB", long_profit_ratio=0.9, short_profit_ratio=None),
        ProfitRatio("CCC", long_profit_ratio=0.5, short_profit_ratio=0.1),
    ]
    sorted_ratios = sort_profit_ratios(ratios, "short", "asc")
    assert [ratio.symbol for ratio in sorted_ratios] == ["CCC", "AAA", "BBB"]


def test_paginate_returns_expected_slice():
    ratios = [ProfitRatio(f"SYM{i}", 0.1, 0.2) for i in range(10)]
    page_items, total = paginate(ratios, page=2, per_page=3)
    assert total == 10
    assert [ratio.symbol for ratio in page_items] == ["SYM3", "SYM4", "SYM5"]
