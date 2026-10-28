"""FastAPI application for the Wind Forecast Decision Portal.

A fixed historical analysis over an Elexon BMRS snapshot - not a live trading
system, and not a procurement recommendation.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import SNAPSHOT_CAVEAT
from app.routers import accuracy, forecast, meta

#: The Vite dev server; production origins are added when the frontend is deployed.
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Wind Forecast Decision Portal",
        version="0.3.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        description=(
            "Decision-time UK national wind forecasts from Elexon BMRS (WINDFOR) with "
            "calibrated empirical uncertainty, and forecast-error analytics against "
            "FUELHH actuals. " + SNAPSHOT_CAVEAT
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(meta.router, prefix="/api")
    app.include_router(forecast.router, prefix="/api")
    app.include_router(accuracy.router, prefix="/api")

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "service": "wind-forecast-decision-portal",
            "docs": "/api/docs",
            "notice": SNAPSHOT_CAVEAT,
        }

    return app


app = create_app()
