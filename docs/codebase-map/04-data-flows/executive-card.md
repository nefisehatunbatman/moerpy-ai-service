# Flow 1 — Executive decision card

Archetype strategy: backend API plus data lineage. The service is FastAPI
(`app/core/runtime.py`), with deterministic facts/KPIs and SQLAlchemy state.
Diagram: [executive-card.mmd](executive-card.mmd).

```mermaid
sequenceDiagram
    participant Backend
    participant API as AI API
    participant KPI
    participant Evidence
    participant LLM
    participant DB
    Backend->>API: signed POST /analysis/run
    API->>KPI: compute scoped facts
    KPI-->>API: values / status / lineage
    API->>DB: anomaly + KPI + threshold snapshot
    Backend->>API: signed POST /anomalies/id/generate-decision
    API->>DB: load saved anomaly
    API->>Evidence: analyzer + selection + policy
    Evidence-->>API: bounded verified signals or review_required
    API->>LLM: evidence + permitted control
    LLM-->>API: candidate JSON or provider error
    API->>API: validate quantities / action; project card
    API->>DB: commit card + evidence + lifecycle
    API-->>Backend: stable card or safe error
```

## Trigger

Authorized backend analysis request, followed by per-anomaly decision generation.
Repeated requests retrieve the same saved card for the anomaly/language/prompt version.
The pilot script drives real localhost HTTP with signed context and a temporary AI database.
Unit tests call isolated services and fixtures; they are not live acceptance.

## Path — CONFIRMED

1. `app/api/security.py:authenticate` verifies HMAC context, timestamp, method/path/query and body hash.
   The default context age is 120 seconds. Shared token alone is insufficient.
2. `app/api/routes/v2.py:analysis` checks company/tenant and write role, validates dates,
   reads company thresholds and invokes KPI computation.
3. `app/kpi/calculation.py:compute_kpis` validates canonical references/values, resolves point-in-time costs,
   computes amounts/ratios and records formulas, raw reference sample and full source digest.
4. `app/anomaly/detector.py:detect_anomalies` rejects mixed scopes and duplicate KPIs. Only valid
   threshold-covered KPIs are compared; unavailable metrics do not become healthy observations.
5. `app/anomaly/repository.py` persists scoped evidence snapshots. Historical runs remain identifiable.
6. `app/decisions/service.py:generate_decision_for_anomaly` reloads the snapshot; it does not recalculate
   facts from a changed provider during generation.
7. `app/financial_impact/analyzer.py:analyze` uses a domain mapping or logged generic context.
   Observed cost/stock value is not relabeled as savings.
8. `app/evidence/selection.py:select_context` validates the primary signal, policy requirements and
   optional local/parent context. Default budget is eight signals.
9. `app/evidence/builder.py:build_evidence` rejects financial context from another anomaly,
   removes unsupported quantified context and marks incomplete evidence review_required.
10. `app/rag/retriever.py:retrieve` uses company/tenant-safe historical records; retrieval is not proof.
11. `app/llm/prompts.py:build_user_prompt` sends compact evidence plus a permitted control.
    The pilot uses `LLM_MODE=live`; JSON field validation and action-ID validation follow.
12. `app/decisions/executive.py:project` renders the visible important claims from saved evidence.
    Unsupported model narrative is not promoted to business facts. The permitted pilot action is a
    plan/reconciliation assignment, not an automatic operational change.
13. `app/confidence/engine.py:compute_confidence` produces a heuristic evidence score, not probability.
    No measured historical outcome exists; unknown/incomplete context is capped below medium.
14. `app/decisions/repository.py:add` commits before returning; `to_card` exposes trace and limitations.
15. `approve_decision` rejects blocked or legacy-unverified cards. Approval of a control-plan card
    approves that task only. Learning retries are separate from the action outcome.

## Data touched

| Value | Storage | Writer |
|---|---|---|
| Synthetic business facts | read-only business_24m.db | verified CSV ingestion |
| Canonical customer facts | external read-only PostgreSQL | outside this service |
| KPI/threshold snapshots | anomaly record JSON | analysis |
| Evidence and executive contract | decision evidence_snapshot | decision generation |
| Card/lifecycle | AI database | generation / approve / reject |
| Similar examples | AI knowledge base | seed / approved decision learning |
| Request slots/metrics | process memory | ASGI boundary |
| API credentials | environment/config only | operator; never included in artifacts |

## Failure modes — CONFIRMED from code, not all observed in production

| Failure | Behavior | Caller sees |
|---|---|---|
| unsigned/expired/tampered context | rejects before scoped work | 401 |
| foreign company/tenant record | authorization refuses | 404 |
| read-only actor tries paid generation | role rejects | 403 |
| invalid date/source | controlled validation failure | 422 with request ID |
| missing company threshold | metric not evaluated | no anomaly for that metric; KPI endpoint still available |
| incomplete evidence | review_required / blocked | card unapprovable |
| no verified primary | does not call model | safe 422 |
| analyzer/builder programming error | logs stack locations; fails current request | safe 500; health remains available |
| model malformed JSON/schema/quantity | no persisted successful decision | safe provider/validation error |
| provider quota | bounded retries then stop | 503/provider_rate_limited, Retry-After |
| provider timeout | bounded provider budget | 504/provider_timeout |
| DB commit fails | request cannot claim success | safe error |
| saturated slots | reject excess request | 429; probes exempt |
| blocked approval | transition rejected | 409 |
| existing index incompatible | startup validation refuses ready service | explicit operational repair required |

## What is NOT in this flow

No automatic ERP mutation. No approved purchase-freeze, pricing, supplier-limit or savings model.
No outcome-based confidence calibration. No success deadline invented from anomaly severity.
No live backend authentication/UI rendering test was passed. Initial template decisions are not
measured successful customer outcomes.

## Observations — INFERRED, not verified at runtime

Process-local slots and metrics require a single-worker interpretation. Scaling across workers
multiplies provider pressure. Idempotent DB records do not suppress concurrent paid calls before
the first commit. All-KB retrieval/startup may become expensive at enterprise scale.
The screenshot's expected-impact promise requires data/policies not present in the canonical flow.

## Where the trace stops

Existing backend proxy does not send signed context. The frontend financial adapter discards
several service fields and marks all cards eligible. Both require external approval before edits.
Google internals and account quota type cannot be inferred from HTTP 429 alone.
See the enterprise review for exact external-change requests and test artifacts.
