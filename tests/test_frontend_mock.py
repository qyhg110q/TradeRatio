import json
from pathlib import Path


def test_mock_data_schema():
    data = json.loads(Path("static/mock-data.json").read_text())
    assert "data" in data
    assert len(data["data"]) >= 1
    for entry in data["data"]:
        assert "symbol" in entry
        assert "longProfitRatio" in entry
        assert "shortProfitRatio" in entry
        assert isinstance(entry["symbol"], str)
        assert isinstance(entry["longProfitRatio"], (int, float))
        assert isinstance(entry["shortProfitRatio"], (int, float))
