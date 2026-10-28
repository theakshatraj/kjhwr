# Wind Forecast Decision Portal

A fixed historical analysis of UK national wind generation: the WINDFOR value that would have been visible at an **assumed, configurable** day-ahead cutoff, with an empirical conservative-wind band, scored against FUELHH actuals for January 2026 (December 2025 warm-up).

This is **not** a live trading system and **not** a procurement recommendation. Demand and other supply are out of scope.

**Live deployment:** [https://gridbricks-three.vercel.app](https://gridbricks-three.vercel.app)

OpenAPI UI: [https://gridbricks-three.vercel.app/api/docs](https://gridbricks-three.vercel.app/api/docs)

---

## 1. Summary

The portal answers three questions a day-ahead buyer might ask of **wind only**:

1. **Decision view.** For each settlement half-hour of a January 2026 delivery day, what forecast was already published by the assumed cutoff on D−1, what daily energy that implies, and what empirical lower/upper band sits around it.
2. **Accuracy.** Over January, what were the signed bias, MAE, RMSE and error percentiles of that decision-time selection, and did the lower bound cover actuals at about the nominal 90% out of sample.
3. **Lead time (separate analysis).** How do error metrics look across *all* WINDFOR vintages, grouped by forecast horizon — not mixed into the decision-time headline.

The snapshot was built from Elexon BMRS on **26 October 2026** (UTC). The same CSV/parquet files are served in Docker, locally, and on Vercel.

---

## 2. AI tools disclosure

Implementation across this repository was **agent-assisted**. The final deployment, smoke test, README and repository audit (Phases 7–8) were produced with the **OpenCode** coding agent running **DeepSeek V4.1 Flash Free**; earlier phases were completed in the same agent-assisted workflow. Agents proposed code, configuration and documentation; they did not run the live market.

Review and testing of that output (not a rubber stamp):

- Backend: `pytest` in `backend/` (101 tests at the time of writing), covering cutoff selection, the `E = F − A` sign convention, `max(0, F − P90(E))`, no-look-ahead calibration, the HTTP contract (camelCase JSON vs `frontend/src/types.ts`), and snapshot-backed API checks.
- Frontend: Vitest unit tests (33), ESLint, `tsc --noEmit` as part of `npm run build`.
- Data: `backend/scripts/validate_data.py` against the processed snapshot; provenance recorded in `backend/data/provenance.json`.
- Deployment: `python scripts/smoke_test.py <live-url>` against health, one January decision query, and the January accuracy summary. The live UI and `/api/docs` were then loaded in a fresh browser session with no authoring cookies, and the public repository was fetched through its unauthenticated URL.

Formulas, coverage percentages and row counts in this README are taken from that snapshot and from the running API, not invented in copy.

---

## 3. Directory and file tree

```
.
├── api/index.py                 # Vercel ASGI entry: puts backend/ on sys.path, re-exports app.main:app
├── backend/
│   ├── Dockerfile               # Python 3.12-slim image; bakes processed snapshot; uvicorn :8000
│   ├── .dockerignore            # Drops tests, scripts, raw JSON from the image context
│   ├── pytest.ini               # pythonpath=.; quiet pytest
│   ├── requirements.txt         # API + pipeline + test deps (includes pyarrow, pytest, uvicorn)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI factory: CORS, /api routers, /api/docs
│   │   ├── config.py            # Paths, London TZ, assumed 09:00 cutoff, windows, attribution
│   │   ├── schemas.py           # Pydantic models; snake_case in Python, camelCase on the wire
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── _helpers.py      # Cutoff parse, January window, 422/404, calibration payload
│   │   │   ├── meta.py          # GET /api/health, /api/meta
│   │   │   ├── forecast.py      # GET /api/forecast/decision, /api/forecast/vintages
│   │   │   └── accuracy.py      # Summary, daily, by-hour, distribution, by-horizon
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── data_store.py    # Clean, parquet+CSV IO via pathlib, provenance writer
│   │       ├── decision_forecast.py  # Latest publish_time <= cutoff per delivery half-hour
│   │       ├── calibration.py   # Pooled P90/P10 bounds, no-look-ahead, coverage checks
│   │       ├── metrics.py       # E=F−A, bias/MAE/RMSE, percentiles, horizon buckets
│   │       └── elexon_client.py # Chunked BMRS WINDFOR / FUELHH fetches (no API key)
│   ├── data/
│   │   ├── provenance.json      # Snapshot date, parameters, row counts, licence
│   │   ├── feasibility_report.txt   # Measured WINDFOR hourly vs FUELHH half-hourly
│   │   ├── processed/           # forecasts/actuals .parquet (local/CI) and .csv (Vercel)
│   │   └── raw/                 # Cached Elexon JSON + a copy of the feasibility report
│   ├── scripts/
│   │   ├── fetch_data.py        # Build/rebuild the offline snapshot
│   │   ├── validate_data.py     # Coverage, duplicates, missing days (never zero-fills)
│   │   └── feasibility_spike.py # Phase-1 diagnostic of native resolution (not request-path)
│   └── tests/                   # Unit + snapshot integration + OpenAPI/contract tests
├── frontend/
│   ├── Dockerfile               # Node 22 build → nginx:1.27 serving dist
│   ├── nginx.conf               # /api/ proxy to the api service; SPA fallback
│   ├── package.json             # Vite 6, React 18, TanStack Query, Recharts, Vitest
│   ├── vite.config.ts           # Dev proxy /api → :8000
│   ├── vitest.config.ts
│   ├── src/api/client.ts        # Typed fetch client; query keys snake_case, bodies camelCase
│   ├── src/types.ts             # Shared response types (read by backend contract tests)
│   ├── src/pages/               # Decision, Accuracy, Methodology
│   ├── src/components/          # Chart, table, KPI, notices, CSV download
│   ├── src/lib/                 # Energy totals, formatters, CSV helper, dict access
│   └── screenshots/             # Local UI captures (not served)
├── scripts/smoke_test.py        # Live health + decision + accuracy checks (stdlib only)
├── .github/workflows/ci.yml     # pytest (requires parquet) + frontend lint/test/build
├── docker-compose.yml           # api :8000 + web :8080
├── Makefile                     # up, down, dev, test, lint, fetch-data
├── requirements.txt             # Vercel function deps only (no pyarrow)
├── vercel.json                  # Vite dist as static site; /api/* → api/index.py; SPA fallback
├── .vercelignore                # Raw JSON, parquet, tests, screenshots stay out of the upload
└── .python-version              # 3.12 (Vercel / Docker / CI)
```

---

## 4. How to run

### Docker Compose

From the repository root (processed snapshot is copied into the API image; no Elexon call is required):

```bash
docker compose up --build
```

- UI: http://localhost:8080
- API / docs: http://localhost:8000/api/docs (also via the UI origin at `/api/docs` through nginx)

Stop with `docker compose down` or `make down`.

### Non-Docker backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Docs: http://localhost:8000/api/docs

The repo root also has a `.venv` used in local development. Paths are resolved from `backend/app/config.py` via `Path(__file__)`, so the working directory can be `backend/` or the repo root as long as `backend` is on `PYTHONPATH` (pytest.ini sets this).

### Non-Docker frontend

```bash
cd frontend
npm ci
npm run dev
```

Vite serves http://localhost:5173 and proxies `/api` to http://127.0.0.1:8000. `make dev` starts both processes.

### Refreshing data

```bash
cd backend
python scripts/fetch_data.py            # reuse backend/data/raw if present
python scripts/fetch_data.py --refresh  # re-download from Elexon
python scripts/validate_data.py
```

`make fetch-data` and `make fetch-data ARGS=--refresh` wrap the same commands. `write_processed` writes **both** parquet (local/CI/Docker) and CSV (Vercel bundle).

### Tests

```bash
cd backend && pytest

cd frontend
npm test
npm run lint
npm run typecheck   # also runs as part of npm run build
```

`make test` runs backend pytest then `npm test`. GitHub Actions (`.github/workflows/ci.yml`) fails if `forecasts.parquet` / `actuals.parquet` are missing so the snapshot-backed suite cannot skip green.

Live deployment:

```bash
python scripts/smoke_test.py https://gridbricks-three.vercel.app
```

---

## 5. Methodology

### Decision-time selection

For each settlement half-hour of delivery day **D** (Europe/London calendar day):

- Eligible vintages: `publish_time <= cutoff(D)`
- Selected: the eligible row with the **latest** `publish_time` (a publish exactly at the cutoff is included)
- The cutoff is on **D−1** at a local clock time

**Default cutoff: 09:00 Europe/London.** This is an **assumption**, not official gate closure. The UI and API label it “assumed decision cutoff”. It is configurable (`cutoff=HH:MM` on the API and in the Decision/Accuracy forms). Exchange gate times differ (for example N2EX documentation is often cited around 09:50 GMT); this project does not claim that 09:00 is the market deadline.

WINDFOR is **hourly** (24 values per normal day). FUELHH is **half-hourly** (48). Each hourly MW is applied to both constituent half-hours **without interpolation**. Metrics always report both half-hour rows and distinct forecast intervals so the same hourly value is not counted as two independent observations.

### Definitions

| Term | Definition |
| --- | --- |
| Error **E** | `E = F − A` in MW. Positive = over-forecast of wind. |
| Actual | `A = F − E` |
| Horizon | `startTime − publishTime` in hours (how far ahead the vintage looks) |
| Forecast age at decision | `cutoff − publishTime` in hours (how stale the selected vintage was when deciding). Not the same as horizon. |
| Energy | `MWh = MW × 0.5` per settlement half-hour. Daily wind energy = `Σ (F_t × 0.5)` over intervals that have a forecast. Partial days are flagged; missing slots are **never** treated as 0 MW. |

### Conservative-wind formula

From the pooled empirical distribution of decision-time errors:

```
lower bound = max(0, F − P90(E))   # conservative wind indicator (~90% one-sided)
upper bound = max(0, F − P10(E))
```

Because `A = F − E`, subtracting a *large positive* P90(E) produces a *lower* bound on actual wind. Worked check in code: `F = 4000`, `P90(E) = +800` → lower = 3200 (not 3400).

### Calibration modes

- **`decision_time` (default).** Strict no-look-ahead: only delivery days **≤ D−2** (actuals fully realised before the D−1 cutoff). December 2025 is the warm-up so early January is not starved. If fewer than 7 days / 336 intervals of history exist, bounds are omitted (`insufficient calibration history`) rather than filled from the future.
- **`retrospective`.** Uses the completed window; labelled as retrospective and **not** evidence of decision-time performance.

Percentiles are **pooled** over every eligible historical half-hour. They are **not** conditioned on horizon, hour of day, or wind level.

### Coverage validation

Coverage is out-of-sample: each day’s P90/P10 is estimated from prior eligible days, bounds are applied, **then** compared with that day’s actuals. Reported as the share of intervals where `actual ≥ lower bound` (nominal 90%) and where `lower ≤ actual ≤ upper`.

On this snapshot, January 2026 at 09:00, decision-time mode:

- Lower-bound coverage **90.1%** (1488 intervals, 31 days, 0 days excluded)
- Two-sided band coverage **85.4%**
- By horizon group (pooled bound, not horizon-conditioned): 0–24 h **87.3%**, 24–30 h **92.7%**, 30–36 h **90.6%**, 36–42 h **91.1%**. Spread **5.4 percentage points**, flagged as material (> 5 pp). Shorter-horizon slots under-cover relative to the nominal 90%.

---

## 6. Data provenance

| | |
| --- | --- |
| Snapshot generated | `2026-10-26T18:52:11Z` (`backend/data/provenance.json`) |
| Provider | Elexon Insights Solution (BMRS), `https://data.elexon.co.uk/bmrs/api/v1` |
| Forecasts | `GET /datasets/WINDFOR/stream` with `publishDateTimeFrom=2025-11-30T00:00:00Z`, `publishDateTimeTo=2026-01-31T00:00:00Z` (publish-time filter; Elexon’s `from`/`to` on this dataset is **not** used — it would silently return only the latest vintage) |
| Actuals | `GET /datasets/FUELHH/stream` with `settlementDateFrom=2025-12-01`, `settlementDateTo=2026-01-31`, `fuelType=WIND` |
| API key | None required |

**Row counts (raw = processed; nothing dropped):**

- Forecast records: **36,208**
- Actual records: **2,976**
- Actuals expected half-hours 2025-12-01 … 2026-01-31: **2,976**
- Missing actual intervals: **0**
- Forecast start times span 2025-11-29 21:00 UTC … 2026-02-01 21:00 UTC; publish times 2025-11-30 02:30 UTC … 2026-01-30 22:30 UTC

**December warm-up.** Actuals and forecasts from December 2025 seed calibration for January 2026. The Decision view still only *scores* January delivery days as the analysis month.

**Attribution / licence.** Contains data from Elexon Insights Solution / BMRS (https://bmrs.elexon.co.uk), licensed under the Elexon Open Data Licence. Reuse requires attribution; redistribution must keep the attribution and licence note. Data is used here for historical analysis only.

---

## 7. API reference

All JSON **response** keys are camelCase. Query parameters stay snake_case (`delivery_date`, `cutoff`, `mode`, `from`, `to`). Interactive docs: `/api/docs` (OpenAPI at `/api/openapi.json`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | `{ status, dataAvailable }` |
| GET | `/api/meta` | Delivery month, assumed cutoff note, warm-up, resolution, counts, provenance |
| GET | `/api/forecast/decision` | One row per half-hour for a delivery date, plus daily energy and calibration |
| GET | `/api/forecast/vintages` | Every WINDFOR vintage of each hour of a day; `selected` marks the cutoff vintage |
| GET | `/api/accuracy/summary` | Decision-time bias/MAE/RMSE/percentiles, native-hourly metrics, out-of-sample coverage |
| GET | `/api/accuracy/daily` | Per delivery-day error series |
| GET | `/api/accuracy/by-hour` | By London hour of day |
| GET | `/api/accuracy/distribution` | Signed-error histogram and absolute-error percentiles |
| GET | `/api/accuracy/by-horizon` | All-vintages lead-time comparison (separate from the decision-time headline) |

**Query defaults.** `delivery_date` defaults to 2026-01-31; `cutoff` to `09:00`; `mode` to `decision_time`. `from`/`to` default to 2026-01-01 … 2026-01-31. Dates outside January 2026 return **422**. A valid date with no intervals in the snapshot would return **404**.

Example:

```bash
curl "https://gridbricks-three.vercel.app/api/forecast/decision?delivery_date=2026-01-15&cutoff=09:00&mode=decision_time"
```

January 2026 decision-time accuracy on this snapshot (half-hour scoring, 09:00 cutoff): **bias +1,852 MW**, **MAE 2,145 MW**, **RMSE 2,616 MW**, **P90(E) +4,275 MW**, **P10(E) −544 MW**, mean actual **11,581 MW**, MAE **18.5%** of mean actual. Native hourly metrics (one observation per forecast hour) are in `nativeHourly` on the same response.

---

## 8. Design decisions and trade-offs

**Snapshot vs live.** The portal never calls Elexon on a user request. A dated snapshot is reproducible, reviewable, and deployable without credentials or rate limits. The cost is staleness: later revisions of FUELHH or new WINDFOR vintages after 26 October 2026 are invisible. A live system would need scheduled refresh, revision handling, and a different accuracy story.

**Deployment layout.** One Vercel project: Vite writes `frontend/dist` as the static site; `/api/*` rewrites to `api/index.py` (the same FastAPI app as Docker/local); unmatched routes fall back to `index.html` for the SPA. Docker Compose is the full-stack local analogue (nginx + uvicorn) and is what CI does not run — CI tests units and the frontend build.

**CSV vs parquet.** Parquet is smaller and typed (forecasts ~146 KB vs CSV ~2.3 MB) but needs pyarrow (~100 MB). The serverless `requirements.txt` omits pyarrow; `data_store.load_processed()` uses pathlib and **prefers parquet, falls back to CSV**. Vercel `includeFiles` ships only the CSV plus `backend/app` and `provenance.json`.

**Same-origin UI.** The browser only calls relative `/api/...`. Vite proxies in dev; nginx and Vercel rewrites in production. FastAPI CORS is localhost-only because the production UI does not cross origins.

**WINDFOR hourly.** The brief’s half-hourly forecast grid is wrong for this dataset. The code measures that fact (`feasibility_report.txt`) and maps 1:2 rather than interpolating.

---

## 9. Statistical limitations

1. **Empirical bounds, no guarantee.** P90 of past errors is not a probabilistic forecast and is not a regulatory or trading guarantee.
2. **Sample size.** One January (31 days, 1,488 scored half-hours / 744 hourly intervals) plus a December warm-up. Results can move with another month or another cutoff.
3. **Pooled, not horizon-conditioned calibration.** One error distribution is applied to every slot. Out-of-sample lower-bound coverage is **90.1%** overall, but **varies by horizon** (87.3% in 0–24 h vs 92.7% in 24–30 h). Do not read 90% as a per-horizon or per-interval promise.
4. **Missing intervals.** Gaps are flagged and energy totals marked partial. They are **never** zero-filled. This snapshot happens to have complete actuals (0 missing).
5. **Fixed snapshot (26 Oct 2026).** Not updated unless someone re-runs `fetch_data.py`.
6. **Not a procurement recommendation.** Wind only. No demand, no other generation, no prices, no balancing risk, no bid strategy.
7. **Half-hour rows are not independent.** Two settlement periods share one WINDFOR value; use `nForecastIntervals` / `nativeHourly` when comparing sample sizes.
8. **Cutoff is assumed.** Changing `cutoff` changes the selected vintage, the error distribution, and the buffer. 09:00 is not gate closure.

---

## 10. Future work

- Bring in **demand and other supply** so a residual (or stack) can sit next to the wind band.
- Other assumed cutoffs as first-class presets (and a comparison table), not only a free-text clock.
- True **probabilistic** forecasts (or horizon-conditioned error models) instead of a single pooled P90.
- **Scheduled refresh** of the Elexon snapshot, with provenance for each run.
- Horizon-conditioned calibration, now that coverage spread is known to be material.
- Broader delivery months and DST-transition days in the scored window (January 2026 is GMT throughout).

---

## 11. Repo audit (Phase 8)

Checked for dead request-path code, secrets, personal information in the tree, and oversized files.

| Finding | Severity | Notes |
| --- | --- | --- |
| No API keys, `.env` files, or credentials in source | — | Elexon client uses a public base URL only |
| No personal names/emails in tracked source files | — | The published repository uses a fresh single-commit history with a neutral author (`kjhwr <kjhwr@users.noreply.github.com>`); the earlier personal-author commit is not part of it |
| `backend/data/raw/windfor_raw.json` ~4.4 MB | Medium | Needed for offline `fetch_data.py` without `--refresh`; excluded from Vercel via `.vercelignore`. GitHub-safe (<50 MB) but large for a demo repo |
| `frontend/screenshots/*.png` ~1.2 MB total | Low | Not served; excluded from Vercel. Useful as UI evidence |
| Duplicate `feasibility_report.txt` under `data/` and `data/raw/` | Low | Same diagnostic, two paths |
| `backend/scripts/feasibility_spike.py` | Low | Phase-1 probe; not imported by the API |
| `frontend/src/lib/csv.ts` | Not dead | Used by the Decision table download |
| Local `.venv` on Python 3.10 vs `.python-version` 3.12 | Low | Docker/CI/Vercel are 3.12; tests pass on 3.10 here |

Nothing in the request path is an unused stub left over from the Phase 2 Vercel skeleton: `api/index.py` only re-exports `app.main:app`.
