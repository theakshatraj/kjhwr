"""Tests for the Elexon client's request shape and date chunking."""

from __future__ import annotations

from app.services.elexon_client import ElexonClient


def test_windfor_chunks_cover_the_whole_window_without_gaps_or_overlap():
    chunks = list(ElexonClient._chunks("2025-11-30T00:00:00Z", "2026-01-31T00:00:00Z"))

    assert chunks[0][0] == "2025-11-30T00:00:00Z"
    assert chunks[-1][1] == "2026-01-31T00:00:00Z"
    for (_, previous_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert previous_end == next_start


def test_windfor_chunks_respect_the_max_range():
    chunks = list(ElexonClient._chunks("2025-11-30T00:00:00Z", "2026-03-31T00:00:00Z", days=7))
    assert len(chunks) > 1
    assert chunks[0] == ("2025-11-30T00:00:00Z", "2025-12-07T00:00:00Z")


def test_date_chunks_are_inclusive_of_the_last_day():
    chunks = list(ElexonClient._date_chunks("2025-12-01", "2026-01-31", days=31))

    assert chunks == [("2025-12-01", "2025-12-31"), ("2026-01-01", "2026-01-31")]


def test_date_chunks_do_not_merge_days_when_aligned():
    chunks = list(ElexonClient._date_chunks("2026-01-01", "2026-01-07", days=7))
    assert chunks == [("2026-01-01", "2026-01-07")]


def test_forecast_request_uses_publish_parameters(monkeypatch):
    """The publish-time parameters are the whole basis of the analysis."""
    client = ElexonClient()
    seen: list[dict] = []

    def fake_get(path, params):
        seen.append({"path": path, "params": params})
        return [{"startTime": "2026-01-15T00:00:00Z", "publishTime": "2026-01-14T08:30:00Z", "generation": 1}]

    monkeypatch.setattr(client, "_get", fake_get)
    client.fetch_wind_forecasts("2026-01-14T00:00:00Z", "2026-01-15T00:00:00Z")

    assert len(seen) == 1
    assert seen[0]["path"] == "/datasets/WINDFOR/stream"
    assert set(seen[0]["params"]) == {"publishDateTimeFrom", "publishDateTimeTo"}
    assert "from" not in seen[0]["params"]


def test_actuals_request_filters_on_settlement_date_and_fuel(monkeypatch):
    client = ElexonClient()
    seen: list[dict] = []

    def fake_get(path, params):
        seen.append({"path": path, "params": params})
        return []

    monkeypatch.setattr(client, "_get", fake_get)
    client.fetch_wind_actuals("2025-12-01", "2026-01-31")

    assert all(entry["path"] == "/datasets/FUELHH/stream" for entry in seen)
    assert all(entry["params"]["fuelType"] == "WIND" for entry in seen)
    assert all("settlementDateFrom" in entry["params"] for entry in seen)
    assert seen[0]["params"]["settlementDateFrom"] == "2025-12-01"
    assert seen[-1]["params"]["settlementDateTo"] == "2026-01-31"
