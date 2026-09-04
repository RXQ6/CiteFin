# CiteFin

CiteFin is an evidence-driven financial analysis agent that turns annual reports into traceable financial facts, deterministic metrics, risk findings, and independently verified reports.

## MVP

The first release accepts a searchable Chinese annual-report PDF for a non-financial A-share listed company. It extracts core facts from the three primary financial statements, calculates 15 versioned metrics, maps material claims to page-level evidence, and requires an independent Goal Gate before a report can be marked complete.

The project does not execute trades, move funds, guarantee returns, or provide unsupported personalized investment instructions.

## Technology

- Python 3.12 and FastAPI
- LangChain and LangGraph
- PostgreSQL and Redis
- uv, pytest, Ruff, and mypy
- Docker Compose

## Quick start

POSIX or CI:

```sh
make setup
make test
make check
make run
```

Windows PowerShell without GNU Make:

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 test
.\scripts\dev.ps1 check
.\scripts\dev.ps1 run
```

The local API is available at `http://127.0.0.1:8000`, with interactive documentation at `/docs` and health endpoints at `/api/v1/health/live` and `/api/v1/health/ready`.

Apply database migrations before using analysis endpoints:

```powershell
.\scripts\dev.ps1 migrate
```

The internal run-initialization API creates an analysis run and its initial audit/checkpoint bundle:

```text
POST /api/v1/analysis-runs
X-User-ID: <user identifier>
Idempotency-Key: <stable request key>
```

F002 attaches a searchable annual-report PDF to an owned analysis run:

```text
POST /api/v1/analysis-runs/{run_id}/documents
X-User-ID: <same user that owns the run>
Content-Type: multipart/form-data
file: <annual-report.pdf>
```

The upload is limited to 50 MiB by default. Encrypted, malformed, image-only, and non-PDF
files are rejected with a stable error code. Repeated content reuses its SHA-256-addressed
immutable object instead of creating another physical copy.

## Project controls

- Read `AGENTS.md` before starting work.
- Use `FEATURES.json` as the source of task status and acceptance criteria.
- Record cross-session state in `docs/PROGRESS.md`, decisions in `docs/DECISIONS.md`, and verification evidence in `docs/VALIDATION.md`.
- A worker may propose `candidate_complete`; only an independent Goal Gate may set `verified`.

## Current status

F001 (project initialization and health checks) and F002 (annual-report upload and file storage) are independently verified. Work is intentionally stopped before F003.
