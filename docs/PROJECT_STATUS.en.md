# CiteFin Project Status

English | [简体中文](PROJECT_STATUS.zh-CN.md)

> Status as of September 8, 2026. This page is a GitHub-facing summary. The
> authoritative feature states are in [`FEATURES.json`](../FEATURES.json), and
> detailed verification evidence is in [`VALIDATION.md`](VALIDATION.md).

## Conclusion

The engineering implementation of the F001–F018 MVP and the complete annual-report research workbench is finished. The project has not yet passed formal production acceptance.

- All 18 features have engineering implementations; none are `not_started`.
- F001–F003 are `verified`.
- F004 is `provisional`.
- F005–F018 are `candidate_complete`.
- The complete automated gate passes: 137 pytest tests, 91.40% coverage, Ruff, formatting, strict mypy, 3/3 synthetic golden cases, and JavaScript syntax validation.
- The local `main` branch is synchronized with GitHub `origin/main`.

`candidate_complete` means that the implementation and current machine checks are complete. It does not mean formal external acceptance, and it must not be interpreted as validated accuracy on real Chinese annual reports.

## Implemented capabilities

| Scope | Status | Knowledge and capability delivered |
| --- | --- | --- |
| F001–F003 | `verified` | Engineering baseline, health checks, PDF upload and immutable storage, page text and table-candidate parsing |
| F004 | `provisional` | Consolidated balance-sheet, income-statement, and cash-flow-statement identification with ambiguity preservation and human-confirmation boundaries |
| F005–F007 | `candidate_complete` | Decimal financial-fact normalization, 15 deterministic metrics, and traceable Claim–Evidence relationships |
| F008–F010 | `candidate_complete` | Typed workflow state, evidence-backed financial claims, and deterministic risk detection |
| F011–F013 | `candidate_complete` | Structured reports, an independent Evaluator, and the sole Goal Gate with repair routing |
| F014–F015 | `candidate_complete` | Checkpoint save/restore, run progress, bounded SSE events, and cursor reconnection |
| F016–F018 | `candidate_complete` | Complete web workbench, page-level PDF evidence viewing, and synthetic success/failure end-to-end acceptance |

The workbench reads persisted backend entities and does not fabricate progress or completion state. It exposes staged operations for upload, parsing, statement identification, manual fact confirmation, metrics, financial analysis, risks, reports, evaluation, Goal Gate decisions, and Checkpoint recovery.

## Remaining production work

- Independent Reviewer A/B blind review, adjudication, and evidence sealing for F004 real annual reports.
- Real-data review and formal external Goal Gate acceptance for F005–F018.
- Automatic table-field extraction; some financial facts currently require human confirmation.
- A complete LangGraph executor and automatic Checkpoints after every required node.
- Production authentication; `X-User-ID` is only a development isolation boundary.
- Production long-lived event streaming, a multi-instance event bus, object storage, and database-level audit protection.
- Validation of real-report accuracy, evidence-location accuracy, and a production browser matrix.

## Validation boundary

The current end-to-end acceptance uses reproducible synthetic PDFs, contract data, and manually supplied facts submitted through the public API. Material-claim page-level evidence coverage is 100% within that synthetic flow only; it is not evidence of performance on real annual reports.

CiteFin does not execute trades, place orders, move funds, or operate accounts. It does not guarantee returns or provide unsupported personalized investment instructions.

## Run locally

```powershell
.\scripts\dev.ps1 setup
.\scripts\dev.ps1 migrate
.\scripts\dev.ps1 test
.\scripts\dev.ps1 run
```

Open `http://127.0.0.1:8000/` after startup to use the workbench.
