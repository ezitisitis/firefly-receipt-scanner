# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Receipt Scanner for Firefly III — a FastAPI web app that scans receipts using any OpenAI-compatible LLM (Gemini by default) and creates transactions in Firefly III. Mobile-friendly with PWA support and camera capture.

## Commands

```bash
docker-compose up -d             # build and run on port 8000
docker-compose up -d --build     # rebuild after code changes
uv sync --frozen                 # install deps locally (incl. dev deps)
uv run pytest                    # run the test suite
uv run pytest --cov              # with coverage (fails below 90%)
uv run pytest tests/test_firefly.py::test_attach_image   # single test
```

Tests live in `tests/` and mock Firefly III (`requests`) and the LLM client, so they need no network or `.env`; `tests/conftest.py` sets dummy settings env vars. `tests/test_app.py` patches `requests.get` while importing `app.app`, because the module checks the Firefly III connection at import time. No linter is configured.

CI (`.github/workflows/ci.yml`) runs the tests and a Docker build on every PR; the `CI success` job aggregates both and is the check to require in branch protection. The Docker image installs with `--no-dev`, so pytest isn't shipped. `.github/workflows/publish.yml` pushes multi-arch images to Docker Hub and `ghcr.io`: `nightly` on every push to `main`, `X.Y.Z`/`X.Y`/`latest` on a published (non-prerelease) release; it needs the `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` secrets.

A "Branch naming" ruleset rejects branches unless they are `main` or start with `feature/`, `fix/`, `chore/`, `docs/` or `dependabot/`; see `CONTRIBUTING.md`.

## Architecture

Three-tier FastAPI application with Jinja2 server-side rendering:

```
User → FastAPI (app.py) → OpenAI-compatible LLM (receipt_processing.py)
                        → Firefly III API (firefly.py)
                        → Image preprocessing (image_utils.py)
```

### Request Flow
1. `GET /` — upload form, fetches asset accounts from Firefly III
2. `POST /extract` — receives one or more images + source account (+ optional `match_existing`/`window_days`), processes each image (resize/compress via `image_utils.py`), sends it to the LLM with categories/budgets from Firefly III, converts a foreign-currency amount to the account currency, optionally looks up matching existing withdrawals (`matching.py`); returns `review.html` for one image or `review_bulk.html` (fields prefixed `r0_`, `r1_`, ...) for several. Both render fields through the `receipt_fields` macro in `_receipt.html`
3. `POST /create-transaction` — single receipt; `match` is `new` or `<group_id>:<journal_id>`. New: creates withdrawal in Firefly III with `#automated` tag, 3 retries with exponential backoff. Match: `update_transaction_from_data` adds the tag, overwrites only the fields ticked in `overwrite_<journal_id>`, attaches the image
4. `POST /create-transactions` — bulk submit of the same per row (`r{i}_match` may also be `skip`), renders a summary

### Key Modules
- **app.py** — FastAPI routes, middleware (ProxyHeaders, TrustedHost), static file mounting, startup validation of Firefly III connection
- **receipt_processing.py** — LLM integration via the `openai` SDK (`LLM_BASE_URL`/`LLM_MODEL`, defaults to Gemini `gemini-2.5-flash`), dynamic prompt construction with Firefly categories/budgets, JSON response parsed into `ReceiptModel` by `parse_receipt`
- **firefly.py** — Firefly III REST API client (accounts, categories, budgets, transaction creation/update, account withdrawals), 30s timeout, comprehensive HTTP error handling
- **matching.py** — finds existing withdrawals within ±N days whose amount matches (exact, tolerance, recorded foreign amount, or converted via `FX_RATES_URL`); `assign_matches` preselects one-to-one
- **image_utils.py** — PIL image processing: RGB conversion, resize to max 768×768 with aspect ratio preservation, returns base64 JPEG
- **models.py** — `ReceiptModel` Pydantic model (date, amount, store_name, description, category, budget, currency)
- **templates/** — Jinja2 templates: `base.html` (layout + PWA meta), `upload.html`, `review.html`, `error.html`

### Configuration
Environment variables loaded via `pydantic-settings` (`app/config.py`) (see `.env.example`):
- `FIREFLY_III_URL` — Firefly III instance base URL
- `FIREFLY_III_TOKEN` — Firefly III personal access token
- `LLM_BASE_URL` — OpenAI-compatible endpoint (defaults to Gemini's)
- `LLM_API_KEY` — LLM provider API key (falls back to `GOOGLE_AI_API_KEY`)
- `LLM_MODEL` — model name, defaults to `gemini-2.5-flash` (falls back to `GEMINI_MODEL`)
- `IMAGE_QUALITY` — JPEG quality (1-100) of the image sent to the LLM, defaults to `85`
- `ATTACH_RECEIPT_DEFAULT` — initial state of the attach-receipt checkbox on the review page, defaults to `true`
- `MATCH_EXISTING_DEFAULT` — initial state of the "Match with existing transactions" checkbox, defaults to `false`
- `MATCH_DATE_WINDOW_DAYS` — default ± days searched around the receipt date, defaults to `3`
- `MATCH_AMOUNT_TOLERANCE` — absolute amount tolerance for same-currency matches, defaults to `0`
- `MATCH_FX_TOLERANCE_PERCENT` — % tolerance for converted amounts, defaults to `5`
- `FX_RATES_URL` — exchange-rate endpoint (`{base}` placeholder, returns `{"rates": {...}}`), defaults to open.er-api.com; empty disables conversion

### Tech Stack
Python 3.13, FastAPI, Uvicorn, Jinja2, Pydantic, Pillow, openai, uv (package manager), Docker, pytest
