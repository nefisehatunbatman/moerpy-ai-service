# MOERPY AI Service — Enterprise Pilot Review
Date: 2026-09-17. Scope: changes ONLY inside `ai-service/`.
Verdict: **NO-GO for the complete enterprise demo**. Service hardening and a live-generated
control card are demonstrated; operational decision readiness and the existing UI chain are not.

## 1. AI Service mevcut mimari özeti

CONFIRMED: Python/FastAPI standalone service; synchronous SQLAlchemy repositories; read-only
ERP adapters; separate AI state; deterministic analytics; local hash embeddings or live embeddings;
OpenAI-compatible live LLM provider. Local configuration selects Gemini. Secrets remain in environment.
The two supplied screenshots were visually inspected. They show a summary card and a detail view:
priority/severity, ID/status, title, finding, problem signal, proposed decision, expected impact,
department/support, confidence number/band, evidence list and rationale. Risk and success metric
are product requirements in this review, but are not dedicated sections in the supplied screenshots.

Existing backend/frontend are external systems. Their source was read to establish the actual
boundary; no files outside AI Service were edited during this review.
The repository already had unrelated uncommitted/untracked work at the start.

## 2. Decision pipeline

```mermaid
flowchart LR
    A[Business CSV or canonical ERP] --> B[Provider / validation]
    B --> C[Deterministic KPI]
    C --> D[Threshold / anomaly snapshot]
    D --> E[Financial context / evidence selection]
    E --> F[Permitted pilot control]
    F --> G[Live LLM candidate]
    G --> H[Schema / quantity / action validation]
    H --> I[Deterministic card projection]
    I --> J[Confidence / persistence / API]
    J -. signed context missing in caller .-> K[Existing backend]
    K -. incomplete field adapter .-> L[Existing decision UI]
```

| Layer / responsible files | Input → output | Failure / missing data / propagation |
|---|---|---|
| `app/data/business.py` | manifest + CSV → versioned business SQLite | SHA256/header/row count/company/tenant checks; existing DB never overwritten; a failed build is not published |
| `app/data/providers/*` | scoped period → canonical facts | Business adapter enforces availability as of period end; fixture refuses splitting monthly totals; Postgres read-only transaction and statement timeout |
| `app/data/models.py` | fact fields → dataclasses | Tenant required; period ordering; cost effective range; waste/return enum; some parsing errors still reach generic request 500 |
| `app/kpi/calculation.py` | facts → values/status/formula/source digests | duplicate IDs, negative/nonfinite/nonnumeric required values, unresolved references rejected; missing cost does not become zero |
| `app/thresholds/engine.py` | value + threshold → comparison | undefined percentage baseline not evaluated; no inferred baseline |
| `app/anomaly/detector.py` | scoped KPIs + thresholds → persisted anomaly inputs | mixed scope and duplicate KPIs rejected; absent threshold skipped; non-ok KPI not actionable |
| `app/financial_impact/analyzer.py` | anomaly + snapshot → financial domain + observed/scenario amount | mapped context or logged generic context; no invented saving |
| `app/evidence/builder.py`, `selection.py`, `policies.py` | scoped snapshot → bounded evidence | primary identity/value must agree; invalid units, duplicates, stale context removed; missing required companion becomes review_required |
| `app/decisions/executive.py` | evidence → permitted control + card fields | known complete context with threshold → control-plan assignment; unknown/incomplete → blocked |
| `app/rag/*` | evidence labels → similar records | tenant/company filter; similarity is not causal proof; vector mismatch rejects request; startup index validation may stop startup |
| `app/llm/*` | compact evidence + permitted action → candidate | actual live API in acceptance; malformed JSON, truncated response, numeric prose and unsupported action rejected |
| `app/confidence/engine.py` | evidence + retrieval → heuristic score | approval is not measured success; unknown/incomplete evidence capped below medium |
| `app/decisions/service.py` | validated narrative + saved evidence → card + lifecycle | commit before response; failed generation leaves anomaly retryable; blocked/legacy cards cannot be approved |
| `app/core/runtime.py` | signed HTTP request → safe response | request IDs, bounded concurrency/body, safe errors; probes bypass saturation; provider failures do not stop service |
| Existing backend/UI | service response → rendered card | static inspection finds authentication and projection blockers; actual end-to-end integration not passed |

A component exception fails the current request. It does not silently substitute invented analytics
or a fake successful recommendation. Anomaly records survive failed generation.

## 3. Decision card field mapping

| Reference card | AI Service response | Existing UI mapping / gap |
|---|---|---|
| Title | title | adapter discards title; current tile uses problem text as heading |
| Finding | summary | summary becomes expected-impact fallback when impact list is empty |
| Problem | problem_signal | carried through |
| Decision | recommended_decision | carried through |
| Evidence | signals; traceability.signals | signal list discarded by financial adapter |
| Rationale | reasoning | discarded by financial adapter |
| Expected impact | expected_impact; impact_assessment | empty list currently shows summary; unavailable reason ignored |
| Department/support | department/support_departments | main department carried; supports discarded |
| Confidence | confidence.score/band/factors/reasons/interpretation | score carried, reasons discarded; band reduced to high/limited |
| Risk/contraindication | risks/do_not_apply_when | no mapping |
| Success | success_metric | no mapping; target/deadline null when company rule missing |
| Trace | id; traceability | source batch list reset to empty; entity key becomes card ID |
| Readiness | decision_readiness/blockers | adapter always sets eligibility=eligible |

Backward compatibility: original service response fields and routes retained; new fields additive.
This does **not** make a caller consume fields it currently ignores.

## 4. Bulunan kritik problemler

| Priority | Finding | State |
|---|---|---|
| Critical | Backend sends shared token but not signed company/tenant/actor context | External blocker |
| Critical | Frontend marks all financial cards eligible and loses grounding/blocks | External blocker |
| Critical | Valid model category could still be semantically unrelated to evidence | Fixed via permitted control and deterministic projection |
| High | Missing required evidence could remain context_available | Fixed |
| High | Unknown review cards could be approved as actionable | Fixed; blocked readiness + approval gate |
| High | Narrative with no digits could invent causes or actions | Visible critical claims now deterministically projected |
| High | Percentage deviation with negative baseline could become negative | Fixed using baseline magnitude |
| High | Inventory/revenue monthly threshold could be applied to partial periods | Nonmonthly ratio marked degraded, excluded from anomalies |
| High | Approval counted as historical outcome support | Removed |
| High | Live smoke silently forced offline and asserted fake provider | Fixed; live is default and asserted |
| High | Old Docker image test results were attributed to changed source | Rebuilt images for verification |
| High | Live provider rate/availability/incomplete output | Safe failures; provider quota remains external constraint |
| High | No approved company action policy, duration, savings model or goals | Data/product blocker |
| Medium | All-KB in-memory search/startup; process-local metrics/concurrency | Remains; suitable only for bounded single-worker pilot |
| Medium | Numeric check cannot prove arbitrary natural-language semantics | Critical visible prose no longer trusts arbitrary model wording |
| Medium | No durable paid-generation lease for simultaneous identical requests | Remains; idempotent records prevent duplicate storage, not duplicate API charges |
| Medium | GET thresholds seeds DB; threshold approval provenance absent | Remains; explicitly not an approved company action rule |

## 5. Düzeltilen problemler

- Evidence mismatch between anomaly and financial context rejected.
- Unknown anomaly emits safe structured log and generic evidence.
- Missing required companions mark context insufficient.
- Empty entity scopes and nonfinite anomaly numbers rejected at schema boundary.
- Duplicate/mixed-scope KPI snapshots rejected before anomaly persistence.
- Required null/nonnumeric/bool/negative source values fail with a controlled data error.
- Nonmonthly inventory-to-revenue ratio cannot silently use a monthly threshold.
- Numeric prose rejection expanded to compatibility Unicode numbers and additional written quantities.
- Invalid or unsupported live action IDs cannot reach visible decision fields.
- Card title, problem, rationale, numbers, action and trace derive from one evidence snapshot.
- Risk, applicability conditions, nonfinancial completion criterion, unavailable-impact explanation added.
- Approval blocked for unsupported/legacy evidence.
- Evidence/RAG endpoint response models prevent new arbitrary top-level snapshot fields leaking.
- Historical approval no longer increases measured-outcome support.
- Provider quota and timeout distinguishable as 503/provider_rate_limited and 504/provider_timeout.
- Retry-After respected when it fits within provider budget; long delays stop the attempt.
- Live smoke stops the batch after provider rate limiting and reports remaining anomalies not evaluated.

## 6. builder.py / analyzer.py değişiklikleri

The existing mapping/selection design was retained; no large strategy framework was introduced.
Analyzer maps known metrics to financial domains, otherwise logs unknown_anomaly_context and
returns an unmapped financial signal. Builder now rejects mismatched financial context and
marks incomplete required evidence review_required. Optional companion amounts must survive
the same selection checks as visible signals. The policy registry remains in evidence/policies.py;
pilot control registry is separate in decisions/executive.py.

## 7. Unknown anomaly davranışı

Unknown anomaly is not dropped. A verified primary KPI can appear in generic evidence and a
blocked card. Its context is explicitly unknown, confidence is low, no impact prediction is made,
and approval returns 409. Without a primary verified signal, generation returns a safe 422 before
calling the model. A genuine analyzer/builder programming failure produces a logged, request-scoped
500; it is not disguised as a normal unknown anomaly.

New KPI support still requires a reviewed evidence policy and semantic catalog entry. A specialized
executive control can be registered independently. Unknown metrics work without these entries but
do not automatically gain authority to prescribe business changes.

## 8. Decision generation değişiklikleri

The pilot now issues scoped management assignments: responsible team, reconciliation deliverable,
corrective plan and submission for approval. For waste, operations and finance receive the task
of reconciling waste by product/cause and preparing an owned corrective plan.

**Limit:** this is a control-plan decision, not a validated operational optimization such as freezing
orders or setting a price. decision_readiness=control_plan_only makes that distinction explicit.
The code does not claim to satisfy operational-action acceptance C in full.

Live LLM receives compact evidence, historical examples and one permitted pilot control. The action
identifier is checked. Critical displayed text is rendered by deterministic projection; arbitrary
LLM prose is not published as verified business reasoning. generator=live_llm proves an actual provider
call on this path, not that every displayed sentence was written freely by the model.
The role is intentionally narrower until approved action policies and outcome data exist.

## 9. Number grounding sonuçları

LLM free-text quantities are rejected, including Unicode numeric forms. Visible numeric claims
come from code, with source types and references in traceability.numeric_claims. Metric values carry
formula and source digest. Threshold values carry COMPANY_THRESHOLD with approval_status=not_established:
persisted seed thresholds are not silently called approved company rules.
Confidence carries calculation source and factors. IDs are identifiers, not financial claims.

No savings simulation is currently implemented. expected_impact remains empty for control plans;
impact_assessment.status=unavailable explains missing avoidable share, implementation cost and timing.
observed_impact retains observed exposure or explicitly marked scenario kind. Stock value is not
cash savings; branch-margin scenario is not an expected return.

Source IDs are sampled (up to twenty); the digest covers all contributing records, and
source_refs_are_sampled discloses truncation. This is reproducible against a retained immutable
dataset, not a full raw-row export. The dataset hash/retention process remains necessary.

## 10. Eksik veri alanları

Business adapter imports 8 tables / 1,050,029 rows from the synthetic corpus:
1 company, 12 locations, 220 products, 30,013 invoices, 52,873 invoice lines,
5,280 costs, 759,524 snapshots, 202,106 movements. Coverage 2024-09-01..2026-08-31.
Full source manifest counts 1,577,755 rows; unimported tables must not be treated as evidence.
Private/oracle labels are not used. This is not customer production ERP data.
More rows alone do not fill semantic/policy gaps.

### DATA GAP — approved action policy
Field: action_policy_id, approved_by, approved_at, valid_from/to, allowed_scope, action_parameters
Required for: enforceable order freeze, supplier limit, pricing rule
Why: anomaly thresholds authorize detection, not operational action
Current consequence: only control-plan assignments; no duration/quantity invented
Decision affected: all operational interventions
Recommended fake-data change: add versioned, explicitly DEMO policies separately from facts; require expert/company approval before treating them as real mandates

### DATA GAP — operational constraints
Field: open_order_qty/value, cancellation_terms, supplier_lead_time, safety_stock, service_level_min, demand_forecast
Required for: safe purchase delay/reduction
Why: branch inventory ratio cannot identify safe SKU-level intervention
Current consequence: no order freeze duration or avoidable cash figure
Decision affected: inventory / cash flow
Recommended fake-data change: add linked, as-of-available order and constraint tables with normal and stockout counterexamples

### DATA GAP — approved cost baseline
Field: approved_budget_unit_cost, approval provenance, scope and effective dates
Required for: unit-cost overrun
Why: business adapter cost_history is observed cost, is_budget=False
Current consequence: cost variance is not evaluated for this corpus without an approved baseline
Decision affected: procurement optimization
Recommended fake-data change: add separate budget facts with explicit approval, never relabel actual costs as budget

### DATA GAP — financial impact model
Field: avoidable_fraction, implementation_cost, realization_schedule, scenario_assumptions
Required for: expected savings / ROI / cash impact
Why: observed cost is not fully preventable or immediately collectible
Current consequence: financial impact unavailable
Decision affected: all expected-impact fields
Recommended fake-data change: add reviewed scenario inputs, formula/version and sensitivity bounds; never synthetic success guarantees

### DATA GAP — target and outcome
Field: success_target, target_source, deadline, implementation_date, measured_outcome
Required for: KPI success target and empirical confidence calibration
Why: alert boundary is not a business goal; approval does not prove success
Current consequence: target/deadline null; historical outcome factor zero
Decision affected: success metric and trust score
Recommended fake-data change: provide actual-looking but clearly synthetic completed/failed decisions with before/after windows and confounders

### DATA GAP — financial availability
Field: unit_cost/cogs_amount/inventory_value and available_at per row
Required for: reliable margin / stock value / waste exposure
Why: values may exist in later records but be unknown at reporting cutoff
Current consequence: unknown cost blocks affected derived KPIs; never silently zero
Decision affected: profitability, waste and inventory
Recommended fake-data change: retain both missing and known-zero cases, with delayed cost recognition scenarios

### DATA GAP — business semantics
Field: closed_period/status, promotion_id, stockout_duration, return/cancellation linkage, collection/payment facts, FX basis
Required for: period comparability, demand attribution, collected cash and real-value comparisons
Why: posted invoice revenue is not cash; nominal TRY changes may reflect FX; margins do not establish causes
Current consequence: no seasonal/trend/causal/cash forecast claims; closure_not_verified reported
Decision affected: demand, pricing, supplier attribution, forecasts
Recommended fake-data change: add dated semantic facts and counterexamples; only import/interpret them after a canonical contract exists

### DATA GAP — screenshot supplier claims
Field: supplier/category spend, contract coverage, indexed-price terms, payment schedule, verified readiness/negotiation assumptions
Required for: supplier consolidation, contractless buying share, extra payment days
Why: reference screenshot claims cannot be derived from current canonical KPI set
Current consequence: no 312 suppliers, 8 categories, 4.2% reduction or 52M TRY promise can be copied from the mockup
Decision affected: procurement screenshot scenario
Recommended fake-data change: version a traceable procurement scenario with the above sources and a reviewed calculation

## 11. Backend integration bulguları

### EXTERNAL CHANGE REQUIRED
- Dosya / component: supabase/functions/ai-financial-decisions/index.ts
- Problem: only X-Internal-Token sent; signed tenant/company/actor/roles context missing; fetch has no explicit timeout.
- AI Service içerisinden neden çözülemiyor: caller identity cannot safely be inferred from a shared secret. Accepting this request would weaken tenant isolation.
- Gerekli değişiklik: sign the server-authorized context, method, full path/query, body SHA256 and timestamp with HMAC; use a timeout covering bounded service processing; propagate structured error codes.
- Mevcut sistem üzerindeki etkisi: AI proxy boundary only; business facts and business logic need not change.

### EXTERNAL CHANGE REQUIRED
- Dosya / component: src/services/decision/financial-decision-adapter.ts; corresponding financial DTO
- Problem: title, signals, reasons, support departments, blockers and trace are lost; all cards eligible; empty impact uses summary.
- AI Service içerisinden neden çözülemiyor: adding fields cannot force existing TypeScript code to read them. Inventing a quantitative impact or abusing summary would misrepresent the data.
- Gerekli değişiklik: preserve evidence and readiness; map unavailable impact to its explanation; prevent operational approval for blocked cards; carry risk and success metadata.
- Mevcut sistem üzerindeki etkisi: additive client adapter mapping; existing components may be reused where their slots support the data.

### EXTERNAL CHANGE REQUIRED
- Dosya / component: CEOActionCardTile / DecisionDetailView and their data contract (exact changes require separate approval)
- Problem: inspected tile uses problem text as title and decision as subtitle; supplied references need independent title/finding; no dedicated new risk/success slots were verified.
- AI Service içerisinden neden çözülemiyor: unused output fields cannot create visual sections; screenshot layout is not identical to inspected component.
- Gerekli değişiklik: approve a mapping/render review; use existing sections if possible, otherwise minimal component extension.
- Mevcut sistem üzerindeki etkisi: UI display only. No UI file changed here.

No external changes are authorized or applied in this review.
Postgres integration tests use disposable test schema, not the deployed Moerpy backend/session.

## 12. Test edilen edge-case'ler

Latest rebuilt image: **232 passed, 3 skipped**; the three PostgreSQL cases separately ran:
**3 passed** against disposable PostgreSQL 16. One AnyIO deprecation warning remains.

Covered: normal fixture; 24-month business monthly reconciliation; empty data; missing/null costs;
known zero cost; zero revenue; duplicate IDs; negative/nonfinite/nonnumeric source fields;
invalid periods/effective ranges; unresolved products/stores; unknown metric; absent threshold;
missing primary/companion; foreign financial context; cross-company/tenant records;
percentage baseline zero/negative; partial month; stale/future stock; malformed JSON;
schema failure; unsupported action; numeric hallucination variants; model timeout/rate limit;
analyzer/builder failures; retries; health under saturation; approval races; learning retry;
one hundred concurrent independent unknown contexts.

Limitations: concurrency test is bounded component concurrency, not production distributed load.
DB adapter/lifecycle tested in PostgreSQL; live deployed Supabase session/proxy not tested.
A multi-pod soak test, full outage recovery and empirical decision-outcome evaluation remain pending.

## 13. Gerçek API test sonuçları

Artifacts: [latest run](../pilot-results/live.json), [partial live run](../pilot-results/live-partial.json),
[initial failures](../pilot-results/live-initial-failure.json).

Configured Gemini endpoint/key actually called; no secret in artifacts. First run had incomplete JSON
and provider errors. Compact prompt and larger bounded output budget subsequently produced a real
card for SP-IST-02, but other calls were rate limited. Latest final-source run:
six anomalies calculated; first provider call exhausted rate-limit retries; safe 503/provider_rate_limited;
five anomalies not evaluated; health 200; passed=false. No offline fallback marked as live success.
Provider error response does not prove its exact quota subtype; account quota must be inspected.

The partial live card came from the intermediate review revision; final additive trace/title/error
changes passed local tests, but a fresh final-version card is blocked by provider rate limiting.

## 14. Örnek final decision card JSON

A successful final-version live card is **not claimed**. See
[live-example.json](../pilot-results/live-example.json) for the exact real card captured during review.
It contains SP-IST-02, waste ratio 10.95%, observed waste cost 18,927.27 TRY,
revenue 172,879.01 TRY, confidence 73/high **evidence sufficiency**, not success probability.
Its recommendation assigns operations/finance a scoped corrective-plan task.
expected_impact=[], target/deadline=null. No fabricated forecast.

## 15. Kalan riskler

| Acceptance | Assessment |
|---|---|
| A/B unknown anomaly + analyzer/builder | Passed bounded tests; genuine bugs fail current request visibly |
| C executable executive decision | Partial: executable control assignment; operational change requires approved company rules |
| D no invented missing values | Passed projection tests |
| E numeric grounding | Passed critical visible projection tests; arbitrary LLM prose not published |
| F traceable relation | Implemented; sampled raw refs, full digest; full raw export not available |
| G card internal consistency | Service projection verified; external UI mapping not accepted |
| H confidence | Explainable heuristic; uncalibrated, cannot mean decision success probability |
| I impact | Observed/scenario exposure verifiable; expected savings unavailable |
| J provider failure | Service survives, safe error; continuous card availability not guaranteed |
| K integration stability | Service response stable; existing caller authentication mismatch blocks full integration |
| L unchanged frontend correctly renders all fields | Blocked by existing adapter/component |
| M reference screens + real API | NOT passed |
| N executive questions | Finding/evidence/control/risk available; verified cause, financial outcome, timed operational target absent |

The safest product outcome is to disclose missing authority/data, not to decorate a demo with plausible
but unsupported actions. This revision intentionally does not claim to solve missing company policy.

## 16. Büyük şirket demosu öncesi yapılması gerekenler

1. Resolve provider quota/capacity and repeat compose.pilot.yaml with all anomalies; require actual live cards.
2. Obtain expert/company-approved action policies with permitted scope, preconditions and parameters.
3. Add scenario/impact assumptions and success targets through reviewed deterministic models.
4. Approve external signed-context and display-mapping fixes; perform a real authenticated backend/UI run.
5. Confirm period closure and source snapshot immutability/retention.
6. Run single-worker load rehearsal with expected volume; establish request timeouts and operational monitoring.
7. Treat control-plan approval as approval of that task only; no automatic purchase/price changes.
8. Calibrate confidence from measured outcomes before showing it as an action-success score.

Until 1–4 are satisfied, the complete enterprise pilot remains NO-GO.

