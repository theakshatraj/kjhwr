"""Shared fixtures: tiny hand-written payloads shaped exactly like Elexon's."""

from __future__ import annotations

import pytest


@pytest.fixture
def raw_forecast_records() -> list[dict]:
    """Three published versions of one startTime, plus one version of another."""
    return [
        {
            "dataset": "WINDFOR",
            "publishTime": "2026-01-14T02:30:00Z",
            "startTime": "2026-01-15T00:00:00Z",
            "generation": 12000,
        },
        {
            "dataset": "WINDFOR",
            "publishTime": "2026-01-14T05:30:00Z",
            "startTime": "2026-01-15T00:00:00Z",
            "generation": 12500,
        },
        {
            "dataset": "WINDFOR",
            "publishTime": "2026-01-14T08:30:00Z",
            "startTime": "2026-01-15T00:00:00Z",
            "generation": 13100,
        },
        {
            "dataset": "WINDFOR",
            "publishTime": "2026-01-14T08:30:00Z",
            "startTime": "2026-01-15T01:00:00Z",
            "generation": 13400,
        },
    ]


@pytest.fixture
def raw_actual_records() -> list[dict]:
    """Two settlement periods; the first was published twice (a revision)."""
    return [
        {
            "dataset": "FUELHH",
            "publishTime": "2026-01-15T00:30:00Z",
            "startTime": "2026-01-15T00:00:00Z",
            "settlementDate": "2026-01-15",
            "settlementPeriod": 1,
            "fuelType": "WIND",
            "generation": 10000,
        },
        {
            "dataset": "FUELHH",
            "publishTime": "2026-01-15T01:00:00Z",
            "startTime": "2026-01-15T00:00:00Z",
            "settlementDate": "2026-01-15",
            "settlementPeriod": 1,
            "fuelType": "WIND",
            "generation": 10400,
        },
        {
            "dataset": "FUELHH",
            "publishTime": "2026-01-15T01:00:00Z",
            "startTime": "2026-01-15T00:30:00Z",
            "settlementDate": "2026-01-15",
            "settlementPeriod": 2,
            "fuelType": "WIND",
            "generation": 10600,
        },
    ]
