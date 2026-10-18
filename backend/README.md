# Candidate Engine API

FastAPI exposes the existing Candidate Engine PostgreSQL data and collection
workflows. It does not execute TradingAgents, place trades, or produce investment
recommendations.

## Local development

Use Python 3.11 for the Qlib analytics dependency:

```powershell
python -m pip install -e '.[backend,analytics,dev]'
Copy-Item backend\.env.example backend\.env
# Set a randomly generated BACKEND_API_KEY in the ignored backend\.env.
python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Connection and provider settings follow the root [.env.example](../.env.example).
Local identity uses Azure CLI; Azure uses the App Service system-assigned managed
identity. No PostgreSQL password or `.env` is deployed.

`backend/.env` can supply API settings locally. Process environment/App Settings
take precedence. The backend key must contain at least 32 characters.

## API

OpenAPI and Swagger UI are available at `/openapi.json` and `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health/live` | Process liveness |
| GET | `/health/ready` | Database and backend migration readiness |
| POST | `/api/v1/pipeline-runs` | Accept DAILY, RANGE, or BACKFILL; requires `X-API-Key` and `Idempotency-Key` |
| GET | `/api/v1/pipeline-runs` | Filtered, paginated execution history |
| GET | `/api/v1/pipeline-runs/{process_run_id}` | Execution status |
| GET | `/api/v1/pipeline-runs/{process_run_id}/dates` | Date/attempt details |
| GET | `/api/v1/pipeline-runs/weekly/eligibility` | Check weekly input eligibility; requires `X-API-Key` |
| POST | `/api/v1/pipeline-runs/weekly` | Accept an idempotent weekly training request; requires `X-API-Key` and `Idempotency-Key` |
| GET | `/api/v1/pipeline-runs/weekly/{weekly_run_id}` | Read allowlisted weekly run state; requires `X-API-Key` |
| POST | `/api/v1/pipeline-runs/weekly/{weekly_run_id}/execution` | Bind the allowlisted Container Apps execution name from the trusted orchestrator; requires `X-API-Key` |
| POST | `/api/v1/pipeline-runs/weekly/{weekly_run_id}/activation-smoke` | Smoke-check a promoted active assignment; requires `X-API-Key` |
| GET | `/api/v1/candidates` | Latest successful selection per date or explicit selection run |
| GET | `/api/v1/llm-preselections` | Latest successful manifest-fenced LLM Top 20 per date |
| GET | `/api/v1/llm-preselections/{run_id}` | Inspect one LLM run, including failed/shortfall |
| GET | `/api/v1/fusion-selections` | Latest successful Fusion per date, optionally pinned to Quant run and policy/hash |
| GET | `/api/v1/fusion-selections/{run_id}` | Inspect one Fusion run, including failed/shortfall |
| GET | `/api/v1/fusion-selections/{run_id}/handoff` | Strict versioned envelope for a successful final Top 20 |
| GET | `/api/v2/fusion-selections` | Local development: Fusion results with reasons from pinned Quant/LLM sources |
| GET | `/api/v2/fusion-selections/{run_id}` | Local development: exact Fusion result and source reasons, including legacy runs |
| GET | `/api/v2/fusion-selections/{run_id}/explanations` | Immutable typed Quant/LLM/RRF explanations for the exact Fusion run; legacy `NOT_RECORDED` |
| POST | `/api/v1/candidate-stage-runs` | Run exactly one Quant, LLM or Fusion stage from a frozen context; API key + Idempotency-Key |
| GET | `/api/v1/candidate-stage-runs/{stage_run_id}` | Authenticated stage status, contract/input hashes, result IDs and failure code |
| POST | `/api/v1/candidate-stage-runs/{stage_run_id}/retry` | Explicitly retry a failed/shortfall stage with preserved input and contract; new Idempotency-Key |
| GET | `/api/v1/collection-data/{dataset}` | Normalized dataset records |

The collection dataset allowlist is `daily-bars`, `corporate-actions`, `news`,
`sec-filings`, `sec-facts`, `earnings`, `universe-members`, and `exchange-sessions`.
Both range endpoints are required; the range includes both endpoints and must not
exceed **10 calendar days**. Default page size is 100; maximum is 500. Cursors must
be reused with unchanged filters. Collection endpoints show stored observations,
not a manifest-constrained analytical input contract or historical trading replay.

### Read semantics and pagination

The v2 routes describe local changes, not deployed production endpoints. Production v1 remains
unchanged. Source reasons can exist in PostgreSQL even when an older Fusion snapshot is absent;
see [candidate tables and ER diagrams](../SELECTION-DATABASE-ER.md).
Combined result/source-reason reads use the exact pinned source IDs and do not create snapshots.

Quantitative result deletion is recorded by run in
`selection.quant_result_deletion` (migration 025). All public candidate reads,
including explicit run IDs, exclude deleted results. There is no public
`include_deleted` parameter. Fusion source-reason reads still resolve the exact
pinned quantitative source internally, preserving its scores, candidates and
integrity checks. This is logical deletion of the independent result, not
physical erasure of evidence required by a retained Fusion result.

The v2 explanation endpoint is a single-run response, not a paginated list.
It returns `schema_version`, Fusion/context/session/cutoff identity, `selection_status`,
`failure_code`, recording `status`, and candidate identity/position/status/explanation.
Old runs return `NOT_RECORDED` with null explanations; reads never regenerate snapshots,
call an LLM, fetch current sources, or resubmit a handoff. Missing runs return 404;
corrupt/missing new-contract snapshots return a logged 500 rather than a legacy fallback.
Existing v1 reads/handoffs explicitly allowlist their original candidate fields.
The new endpoint and cutoff harness require code deployment, but no new DDL.

Historical LLM evaluation is fenced by the frozen run `cutoff_at`, not the retry's wall clock
or session-day midnight. Fresh inputs, screening lineage, cached packets and pre-model
inputs must pass `llm-cutoff-v1`; Fusion also revalidates pinned source packets/citations.
Reconstruction permits later collection of already-public information, never later
publication. Operational replay additionally requires observation by cutoff.
An earnings schedule known by cutoff may be in the future; a future published result may not.
The harness and `scored-citations-ko-v1` summary identity are pinned in new stage contracts.
No additional summary LLM request or update of historical results is performed.
The event prompt is `llm-event-preselection-v3-ko`: instructions and repair requests are Korean.
Natural-language summaries, citation reasons and non-null missing reasons must contain Korean;
English-only responses fail semantic validation and use the existing bounded repair budget.
JSON keys/enums/UUIDs and supplied source text remain unchanged. The prompt/config hash prevents
reuse of older English response caches. This local code change is not an operational deployment.

Optional native-search v4 uses `llm-event-preselection-v7-ko-search` / evidence schema 4.
Select `config/llm_preselection/policy_event_search_v4.yaml` explicitly. Server SEC downloading
and parsing enrichment was removed. Provider-hosted Responses `web_search` receives only public
company/archive metadata, never the complete DB packet or internal IDs.
The full search trace is quarantined. Every consulted source/open/find URL must be a pinned
pre-cutoff original version; one unsafe source rejects the whole response. Ordinary dated news
pages are not historical revision proof. Missing body content is not successful enrichment.
Only admitted cited passages enter a new, tool-free scoring conversation. No search conversation,
reasoning or previous_response_id crosses this boundary. Admission depends on source publication
and original-version proof, not model names/versions. Model metadata is nullable audit information;
aliases, missing snapshot dates and model changes do not reject otherwise admissible news.
Raw tool evidence is content-addressed outside PostgreSQL; bounded admitted evidence goes into
existing input JSONB. No new source tables or DDL are required. Replay reruns the admission gate.
Fusion search snapshots use `candidate-explanation-v3`; old v1 snapshots/handoff remain unchanged.
The mandatory source/time contract is [LLM-HARNESS.md](../src/sp500_candidate_engine/llm_preselection/LLM-HARNESS.md).

For tool-level historical date filtering select
`config/llm_preselection/policy_event_period_v5.yaml` and configure
`BING_GROUNDING_PROJECT_ENDPOINT` plus `BING_GROUNDING_CONNECTION_ID`.
The provider sends `freshness=YYYY-MM-DD..YYYY-MM-DD` in the actual `bing_grounding` tool
configuration. This is Bing discovery-date filtering, not historical source-version proof.
The original-version gate remains mandatory; unavailable provenance fails closed.

LLM publication/version checks use NY calendar dates: prior days need no creation timestamp;
same-day sources require a trusted timezone-aware time strictly before 05:30 New York.
An earlier explicit context cutoff remains stricter. Collection/Quant fences are unchanged.
DAY precision is recorded with its conservative day-end bound, not as an invented publication time.

Responses use `{ "items": [...], "next_cursor": null }`. When `next_cursor` is
non-null, resend it with the same dataset and filters; page size may change.
Cursors are authenticated, versioned, and bound to the request filters. They
expire when the single API worker restarts. They are not durable bookmarks.

Candidates without date filters cover **all dates**, newest first, selecting the
latest `SUCCEEDED` selection run separately for each date and model purpose.
The default `model_purpose` is `MEDIUM_20D`, so calls without the option return
the 20-session return model. Use `model_purpose=SHORT_5D` to retrieve the
preserved five-session model. A missing `MEDIUM_20D` result returns an empty page;
the API never silently falls back to `SHORT_5D`. `date` cannot be combined with
`start_date/end_date`; both range endpoints must be supplied.
`selection_run_id` explicitly inspects a run, including non-successful runs and
ignores the default purpose filter.
Ticker/company/sector come from that scoring run's universe version. The first
page fixes a run-creation watermark so a subsequent rerun cannot replace a run
mid-pagination. Candidate reason codes, priority and event revision IDs are
public; arbitrary reason-detail JSON is not.

The scheduled `MEDIUM_20D` policy returns exactly 20 quantitative analysis
candidates. The preserved `SHORT_5D` policy remains a 5–10 candidate legacy
path. LLM results are not mixed into this response: `/api/v1/llm-preselections`
returns a separate 20-item run with its execution context, cutoff,
prompt/deployment/evidence-schema versions, bounded reason codes, and selected
source-evidence lineage. Its score semantics are `LLM_EVIDENCE_SCORE`, not
predicted return, probability, confidence, or investment advice.

Fusion and its external handoff adapter are implemented but default off. With Fusion
disabled, MEDIUM still stops at `parallel_preselection` with zero submissions.
The separate `fusion-top20-v1` handoff sends all **20** final candidates and ends at
receipt acknowledgement, not external analysis completion. SHORT legacy execution
remains unchanged. Implementation does not imply production migration or deployment.

`LLM_PRESELECTION_ENABLED=false` is the safe deployment default. When enabled
for a MEDIUM daily run, the backend starts the LLM branch after the shared
cutoff-fixed input manifest is prepared, before any Qlib export or model
validation. The daily control plane runs quantitative inference and
`src/sp500_candidate_engine/llm_preselection/pipeline.py` independently in
parallel; quantitative inference never starts or waits for an LLM call.
LLM configuration lives in `config/llm_preselection/`, with dedicated tests in
`tests/llm_preselection/`. The execution result exposes sibling `candidate_run`
and `llm_preselection_run` objects, plus `preselection_failures`. One successful
Top 20 and one failed/shortfall branch yields partial success; neither successful
Top 20 yields failure. No branch falls back to an older run or the other list.

The LLM pipeline can also run alone with a supplied frozen context:

Local Azure OpenAI credentials belong in the ignored repository-root `.env`,
not inside the Python package. `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and
`AZURE_CLIENT_SECRET` support local service-principal authentication through
`DefaultAzureCredential`; Azure deployments continue to use managed identity.
The client leaves temperature at the deployment default so deployments that
reject custom temperature values remain compatible. Strict JSON output is still
required; identical completed inputs are reused rather than assuming sampling
is deterministic.

```powershell
python -m sp500_candidate_engine.llm_preselection --date 2026-10-14 --execution-context-id <context-uuid>
```

This entry point does not load Qlib exports, Alpha158 features, or LightGBM
artifacts. The existing `candidate-engine rank-llm-candidates` command remains
compatible and delegates to the same independent pipeline.

### Independent candidate stages

Apply [migration 024](../sql/024_candidate_stage_runs.sql) and grant the backend
SELECT/INSERT/UPDATE on `ops.candidate_stage_run` before deploying the independent-stage
code. Terminal stage identity/history is protected by a DB trigger; do not grant DELETE.
Result schemas, model parameters, ranking policies and existing daily scheduling are unchanged.

Each request needs `stage`, `target_session`, `execution_context_id`.
Stages are `QUANTITATIVE`, `LLM_PRESELECTION`, `FUSION`.
Quant defaults to MEDIUM and accepts explicit SHORT. LLM does not take a Quant purpose.
Fusion requires both source selection IDs and only supports MEDIUM.
Unknown context, non-session, wrong cutoff, empty universe and broken manifest fail closed.

Example authenticated POST body for independent Fusion:

```json
{
  "stage": "FUSION",
  "target_session": "2026-10-15",
  "execution_context_id": "525d8b80-2415-5e82-b47e-9298e2424bf5",
  "quant_selection_run_id": "832664a9-6e9a-5b7c-914f-ce94131174f3",
  "llm_preselection_run_id": "11524530-0f59-49cd-9264-c88d7e63ec29"
}
```

The response is HTTP202 with `stage_run_id`, the actual stored status, and `status_url`.
The stage ID is **not** the Quant/LLM/Fusion selection ID. GET returns the result's
actual selection/scoring/ranking/Fusion IDs, candidate count and reuse flag separately.
The immutable contract itself (including artifact location) is not exposed in this
status response; only contract/input hashes are public to authenticated operators.

Same key+same request returns the original stage, including its terminal status.
A different payload/retry source with the same key is HTTP409. Simultaneous active
identical inputs are rejected. Collection/daily requests and independent stages use
a common acceptance lock to prevent incompatible overlapping collection; separate
Quant and LLM stage inputs can execute concurrently. Same-context Quant exports are
serialized so SHORT/MEDIUM do not write the same Qlib files concurrently.

Quant pins its active assignment or explicitly provisioned manifest at acceptance;
execution never changes to a newer model assignment. It performs inference only,
not training or processor fitting. A matching successful MEDIUM result may be reused.
LLM pins its selected policy/hash and deployment/API and never initializes Quant/Qlib.
Standalone legacy LLM can run even when Fusion is enabled; the daily Fusion flow still
requires the explicitly selected event policy. Fusion validates and combines only
the explicit existing sources; it never invokes Quant, LLM or external handoff.

State is `PENDING → RUNNING → SUCCEEDED|SHORTFALL|FAILED`. API startup marks lost API
requests `FAILED/INTERRUPTED`; it does not mark separately owned CLI requests.
BackgroundTasks is not a durable queue. CLI cancellation is recorded when catchable;
an uncatchable OS/process kill requires operator recovery, not an assumed success.
Retry creates a new stage with `retry_of_run_id`; the previous terminal run is preserved.
Only failed/shortfall runs can retry. Policy/deployment/context changes require a new
request; a retry cannot silently switch the pinned contract.

```powershell
candidate-engine run-stage --stage QUANTITATIVE --date 2026-10-15 --execution-context-id <context-uuid> --model-purpose MEDIUM_20D --idempotency-key <unique-key>
candidate-engine run-stage --stage LLM_PRESELECTION --date 2026-10-15 --execution-context-id <context-uuid> --idempotency-key <unique-key>
candidate-engine run-stage --stage FUSION --date 2026-10-15 --execution-context-id <context-uuid> --quant-selection-run-id <quant-uuid> --llm-preselection-run-id <llm-uuid> --idempotency-key <unique-key>
candidate-engine show-stage --stage-run-id <stage-uuid>
candidate-engine retry-stage --stage-run-id <failed-stage-uuid> --idempotency-key <new-key>
```

These CLI commands require the existing backend/analytics extras, selected Azure identity,
database and stage-specific configuration. They share the API service rather than
duplicating selection algorithms. Existing `rank-llm-candidates` and legacy training
commands remain compatible. Independent completion does **not** submit external analysis.

### Event/Fusion operational activation

1. With explicit approval, apply migrations through
   [023_hybrid_fusion.sql](../sql/023_hybrid_fusion.sql) before deploying the new
   code. Migration 022 also replaces the old 5–10 success constraint while retaining
   selected-count bounds; replay is supported.
2. Keep `LLM_PRESELECTION_ENABLED=false` and `FUSION_ENABLED=false` by default.
   The default `LLM_PRESELECTION_POLICY_PATH` remains
   `config/llm_preselection/policy_v1.yaml`.
3. To test Fusion after approval, explicitly select
   `config/llm_preselection/policy_event_v2.yaml`, enable LLM and then Fusion.
   Do not select the legacy policy for Fusion. Invalid configuration is an explicit failure.
4. [fusion_v1.yaml](../config/analytics/fusion_v1.yaml) fixes MEDIUM-only Top 20,
   k=10 and sector caps 2/4. Environment overrides must agree with the policy.
   `RRF_K`, `FUSION_SECTOR_CAP`, `FUSION_RELAXED_SECTOR_CAP` and any Top-N
   settings are validated rather than silently changing the policy.
5. Configure the orchestrator's matching Fusion policy/version/hash and leave external
   delivery off until the receiver passes the contract checks in
   [the orchestrator guide](../orchestrator/README.md).

The event policy screens at most 90 EVENT and 10 CONTROL issuers, with no quota
transfer or forced padding. It excludes price context, uses at least three
evidence-backed rubric criteria, renormalizes their weights and records null/missing
criteria. The LLM API exposes group, criterion citations, supported count and weight
denominator; its run retains the complete screening audit. RPM/TPM limits, finite retry
budget, stored response hashes, source-call references and context-restricted successful
batch reuse bound retries without assuming model determinism. An advisory evaluation
lock prevents concurrent duplicate event runs.

Fusion pins both source selection IDs and validates context, manifest/universe,
session/cutoff, policy hashes, model purpose, scoring/artifact lineage and source
counts. Exact RRF only sums identical instruments; issuer deduplication never moves
another share class's return to the selected instrument. The candidate pool never
extends beyond the two Top 20 lists. A shortage is stored as `SHORTFALL` and cannot
produce a handoff. Run/candidates/audit are append-only and atomically stored with
payload-conflict detection. The API exposes exact RRF numerator/denominator and nullable
source values; it rejects SHORT Fusion requests and never reinterprets legacy scores.

Daily results preserve sibling `candidate_run`, `llm_preselection_run` and, when
requested, `fusion_run`. Pipeline status exposes pinned Fusion and source selection
IDs. A failed Fusion stage preserves both upstream results; a failed external handoff
does not alter an already successful Fusion run. A retry reuses a successful Quant
selection in the same context and successful LLM inputs/batches, then runs only the
remaining stages. No production DB or real Azure OpenAI/receiver call is required by
the mock unit/integration tests.

Collection date filters have dataset-specific meanings:

| Dataset | Inclusive filter date | Revision behavior |
|---|---|---|
| `daily-bars` | `session_date` | Latest revision per instrument/session/source |
| `corporate-actions` | `effective_date` | Latest revision per source/action identity |
| `news` | UTC date of `published_at` | Latest revision per event |
| `earnings` | UTC date of `scheduled_at` | Latest revision per event |
| `sec-filings` | `filed_date` | Normalized issuer/accession filing identity |
| `sec-facts` | UTC date of `source_available_at`, **not** fiscal `period_end` | Normalized fact identity |
| `universe-members` | Universe version `as_of_date` | Version members, not daily validity expansion |
| `exchange-sessions` | `session_date` | Versioned calendar records |

News/earnings with null semantic timestamps are excluded. Entity filters
`ticker`, `instrument_id`, and `issuer_id` are combined with AND. Filings/facts
remain issuer-level records; associated-instrument filters use existence checks,
not a join that duplicates facts for share classes. Events return an association
per instrument, including null identities for unassociated events. Sessions have
no entity association and reject these filters. Symbols use identifier validity
at the semantic date; universe symbols use the selected universe version.
Provenance describes the normalized revision's origin snapshot and observation,
not every later re-observation of the same logical revision.

History date filters match overlapping execution ranges. API-owned status
overrides collection-only engine status, so later scoring/candidate failures
remain visible. RANGE `/dates` includes child attempts; each item's
`process_run_id` identifies its actual child run. Count keys are explicitly
allowlisted and engine `bars/actions/filings/facts` map to their public dataset
names. Public records exclude raw metadata, request payloads, storage URLs and
filesystem log paths; failures expose only safe summaries.

All timestamps retain provenance and are serialized as ISO 8601. Predicted return
is a raw return estimate for the declared horizon (20 sessions by default,
5 for explicit SHORT), **not** a confidence/probability.

```javascript
// Run on the TradingAgents portal Origin. Reads require no API key.
const response = await fetch(
  "https://web-sp500-candidate-8d0218f4.azurewebsites.net/api/v1/candidates?model_purpose=MEDIUM_20D&limit=20"
);
if (!response.ok) throw new Error(`Candidate API: ${response.status}`);
const candidates = await response.json();
```

The response includes `model_purpose`, `prediction_horizon_sessions`,
`score_semantics`, `return_policy`, and `promotion_status`. The default response
currently uses `MEDIUM_20D` with `PREDICTED_20D_RETURN`; this is a raw predicted
20-session return, not a probability or confidence.

Execution keys are server-side credentials: do not embed them in browser bundles.
The in-repository orchestrator or another trusted server sends `X-API-Key` and an
`Idempotency-Key` with each POST request. The idempotency key must be 1–128 ASCII
letters, digits, `.`, `_`, `:`, or `-`, starting with a letter or digit. Reusing
the same key and canonical request returns the original `process_run_id` and
status URL without scheduling duplicate work. Reusing a key with a different
request returns `409`.

### Weekly training and DAILY assignment pinning

The weekly API is a control surface, not an in-process trainer. Eligibility returns
`READY`, `NO_COMPLETE_MANIFEST`, or `ALREADY_ACCEPTED`. Acceptance persists a
`PENDING` `analytics.weekly_training_run` for `SHORT_5D` or `MEDIUM_20D`; a trusted
orchestrator must start the manual Container Apps Job and persist its execution
name. Status responses expose only allowlisted identifiers, lifecycle state, and
safe error codes. Activation smoke requires both `PROMOTED` state and that run's
model to be the current `analytics.active_model_assignment`.

At the start of a DAILY run, the backend reads the active assignment for the
requested purpose under the process transaction. It stores the model version,
artifact URI/hash, Blob ETag or version ID, generation, and weekly run ID in
`ops.process_run.metadata.model_bindings`. Retries for that process reuse this
binding even if a later promotion changes the active assignment. This prevents a
single DAILY run from changing models mid-execution. Until an active assignment
exists, the existing purpose-specific manifest path and SHA-256 App Settings remain
the explicit compatibility source; there is still no cross-purpose fallback.

## CORS

The exact allowed production Origin is:

```text
https://web-jongmok-portal-8d0218f4.azurewebsites.net
```

`BACKEND_CORS_ORIGINS` accepts comma-separated exact Origins without a trailing
slash. Wildcards are rejected. Only local `http://localhost`/`http://127.0.0.1`
Origins may use HTTP. Allowed methods are GET, POST, OPTIONS; allowed headers
include Content-Type, X-API-Key, and Idempotency-Key; credentials/cookies are not enabled.

CORS is a browser policy, **not authentication**: anonymous reads remain accessible
to non-browser clients. Admin history must therefore never include secrets, raw
exception traces, internal filesystem locations, or arbitrary provider payloads.
App Service platform CORS is left unconfigured; FastAPI is the single policy owner.

## Deployment

[infra/backend-appservice.bicep](../infra/backend-appservice.bicep) creates or updates
the separate Python App Service on the **existing** Linux plan `asp-sp500-candidate`.
It does not create or resize the plan. As of 2026-10-18, the user-approved SKU for
both `asp-sp500-candidate` and Portal's `asp-jongmok-prd` is **B2**; do not change
either to B1. Preserve each plan's SKU and instance count during deployment and
verify them before and after. Any later SKU change needs separate user approval.
Remove the obsolete `appServicePlanSkuName`, `appServicePlanSkuTier`, and
`appServicePlanCapacity` overrides from old parameter files.
`vnetIntegrationSubnetId` remains mandatory. Route-all VNet integration is configured so
the backend can resolve and reach private PostgreSQL, Blob, and ACR endpoints.
It does not redeploy the portal, alter its container image, or change the portal's
existing plan. The existing plans incur ongoing Azure cost. These SKU rules do
not change network settings; validate network feature compatibility separately.

The resource group metadata location is West US 3, but the application explicitly
uses **Korea Central** to match the existing plan and database.

From the repository root:

```powershell
python backend\prepare_deployment.py
# Run Azure validation before deployment.
az deployment group create -g rg-ai-project --template-file infra\backend-appservice.bicep --parameters '@.azure\backend.parameters.tmp.json' --output none
```

The generated `.azure/backend.parameters.tmp.json` contains secrets and is ignored.
Never print it, include it in source ZIPs, or commit it. Delete it after deployment.
The source ZIP excludes `.env`, raw data, local environments and model outputs.

Grant the new managed identity database access using an Entra administrator:

```powershell
python backend\grant_database_access.py --principal-id <app-managed-identity-object-id>
az webapp deploy -g rg-ai-project -n web-sp500-candidate-8d0218f4 --src-path .azure\backend-source.tmp.zip --type zip --output none
```

Only the app's outbound IPv4 addresses should be added to PostgreSQL firewall rules;
do not enable the broad "Allow Azure services" rule. Database migrations run with
the administrator, not the app identity. App settings hold provider/API credentials;
rotate them through an encrypted settings update, not a new source ZIP.

### Candidate training infrastructure and bootstrap

[infra/candidate-training.bicep](../infra/candidate-training.bicep) and its modules
implement the candidate-only training foundation in **Korea Central**:

- an internal Container Apps managed environment and a manual Consumption Job
  sized at 2 CPU/4 GiB;
- a private Premium ACR and private Standard ZRS Blob account with versioning and
  the `candidate-training` container;
- separate Container Apps, private-endpoint, and backend App Service integration
  subnets, plus Blob, ACR, and PostgreSQL private endpoints/private DNS;
- separate training and reader user-assigned identities; and
- Blob Data Contributor for training, Blob Data Reader for readers, AcrPull for
  training, and a custom ARM role limited to reading/starting the Job.

Bootstrap is intentionally two-phase:

1. Deploy with `deployTrainingJob=false`. Wait for the deployment to reach
   `Succeeded`; capture `backendIntegrationSubnetId`, identity IDs, ACR, Blob, and
   environment outputs. Do not treat an `Accepted`, `Running`, or in-progress
   deployment as complete.
2. Build a training image that installs the analytics dependencies and repository
   configuration and whose entry point is
   `python -m sp500_candidate_engine.analytics.weekly_job`. Push it as
   `<acr-login-server>/candidate-training:latest`.
3. Provision the training identity in PostgreSQL, then validate its grants. The
   database role used as `PGUSER` must refer to that exact Entra identity.
4. Redeploy the same template with `deployTrainingJob=true`. Each Job start must
   supply `WEEKLY_RUN_ID` and `MODEL_PURPOSE`; the runtime must also receive the
   provisioned `PGUSER`. Only then configure the orchestrator with the resulting
   Job resource ID and grant its Job operator role.
5. Redeploy the backend with the bootstrap `backendIntegrationSubnetId` while
   preserving the existing plan, App Settings, and API keys. This does not
   authorize changing the current user-approved B2 SKU.

Create the least-privilege PostgreSQL identity with an Entra administrator:

```powershell
python -m backend.grant_weekly_training_access `
  --principal-id <trainingIdentityPrincipalId> `
  --role <training-database-role-used-as-PGUSER>
```

That role receives `CONNECT`; read-only access to source data in `ops`, `ref`,
`market`, `fundamental`, `event`, and `selection`; narrow `INSERT` access only to
`ops.input_manifest`, `ops.input_manifest_member`, and `ops.execution_context` for
cutoff-fixed derived export metadata; and `SELECT`, `INSERT`, and `UPDATE` plus
sequence usage in `analytics`. It does not receive schema ownership, DDL, DELETE,
broad database-owner rights, or backend API credentials. Migrations remain an
administrator responsibility.

**Deployment status (2026-10-16):** the private training environment, ACR, Blob,
manual Job, managed identities, least-privilege PostgreSQL grants, Durable weekly
functions, backend P3v3/capacity 1, and backend VNet integration are deployed.
Backend live/readiness and weekly eligibility/acceptance are runtime-verified.
The Job start contract preserves the deployed container definition and overrides
only `WEEKLY_RUN_ID` and `MODEL_PURPOSE`; the Job then creates a cutoff-fixed Qlib
export in ephemeral work storage before training.

## Operational limitations

- `BackgroundTasks` is not a durable queue. `202` means accepted, not completed.
  Poll the returned status URL.
- Use **one Uvicorn worker and one plan instance**. No scale-out. Always On is enabled.
- App Service restarts/deployments may interrupt accepted work. API-owned interrupted
  requests must become failed, not silently stay running or automatically restart.
  Inspect status before manually resubmitting.
- Do not redeploy during active collection. The API remains separate from the
  portal. Both App Service plans must retain their user-approved B2 SKU;
  the 2026-10-16 P3v3 deployment below is historical, not a resize instruction.
  Analytics runs still
  require measured memory capacity and valid model/export prerequisites before
  increasing production workloads.
- PostgreSQL must be running. Readiness reports failure when database access fails.
- Per-process request IDs and structured request completion logs support diagnostics.

### Execution integration and candidate prerequisites

Apply migrations through `020_backend_pipeline_idempotency.sql` before starting
the API. Execution
ownership and full-stage status live in `ops.backend_pipeline_request`; existing
engine collection state remains in `ops.process_run`. RANGE children reference
their parent through `parent_process_run_id`. Main must initialize
`PipelineExecutionService(database, engine_settings)` and run
`reconcile_interrupted()` off the event loop during single-worker startup.
Readiness must check `ops.backend_pipeline_request`, not a differently named API
request table.

Migration 020 is an expand-compatible rollout: its idempotency columns remain
nullable as a pair so an old API instance can continue inserting rows while the
migration is applied. A partial unique index covers non-null keys. The new API
always writes both columns; a later contract migration may make them mandatory
only after all old instances are retired.

Acceptance uses a transaction advisory lock. An exact idempotent replay is
resolved before the active-run check; a new key still rejects any active API
request or conflicting external CLI run to protect shared provider quotas. DAILY keeps
its API request `RUNNING` after collection completes until scoring and candidate
generation finish. Internal engine results may include scoring/selection run IDs,
but their arbitrary metadata is not part of the public history response.

Candidate DAILY is **inference-only**: it never trains a model or fits processors.
Use the analytics extra on **Python 3.11 or 3.12**, explicitly provision the chosen
LightGBM model plus a manifest for each model purpose, and configure
`BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHORT_5D`,
`BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256_SHORT_5D`,
`BACKEND_CANDIDATE_ARTIFACT_MANIFEST_MEDIUM_20D`, and
`BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256_MEDIUM_20D`. Each hash pins that
purpose's manifest exact bytes. The legacy unsuffixed pair is accepted only as a
SHORT_5D compatibility setting; MEDIUM_20D never falls back to it or to another
purpose. Do not automatically bundle `data\output` or select whichever model
happens to exist on disk.

The manifest contains `schema_version=2`, `model_purpose`, `label_semantics`,
`prediction_semantics`, `horizon_sessions`, `model_version_id`, `model_file`,
`model_sha256`, ordered `feature_names` (158 strings), `feature_config_hash`, and
`model_config_hash` (the effective model-plus-label configuration hash). The API
validates these fields against the purpose-specific model and label configs and
against the registered model, plus artifact/manifest/config hashes, training cutoff,
and feature dimension/order. Current inference supports raw, unprocessed Alpha158.
Missing or invalid artifacts fail closed without cross-purpose fallback.

Provision the selected registered artifact before preparing the deployment ZIP:

```powershell
python -m backend.prepare_candidate_artifact --model-purpose SHORT_5D --model-version-id <short-model-id> --source-directory <short-source-directory> --output-directory data\backend-artifacts\models\short_5d
python -m backend.prepare_candidate_artifact --model-purpose MEDIUM_20D --model-version-id <medium-model-id> --source-directory <medium-source-directory> --output-directory data\backend-artifacts\models\medium_20d
python -m backend.upload_candidate_artifact
python -m backend.prepare_deployment
```

The upload uses your Azure CLI Entra identity, writes only the selected manifest/model
to persistent storage, and verifies both checksums. The deployment helper pins the
local manifest checksum in Bicep parameters. Model artifacts are ignored by Git and
excluded from the application source ZIP.

Prepopulate sufficient PostgreSQL history with RANGE/BACKFILL. Current inference
needs **61 sessions**: configured Alpha158 lookback 60 plus one session. Each
candidate DAILY creates a fresh manifest-constrained Qlib export under
`<BACKEND_WORKSPACE_DIR>\data\output\qlib` and JSON outputs under
`<BACKEND_WORKSPACE_DIR>\data\output\candidates`. Set `BACKEND_WORKSPACE_DIR` to
a persistent writable directory; relative artifact manifest paths resolve within
it. If unset, the workspace defaults to the repository root; installed code,
versioned configuration, and SQL stay at the repository root independently.
The deployed workspace is `/home/candidate-engine` and manifest setting is
`models/manifest.json` within that workspace. These output directories, raw-data
and log directories must be persistent
and writable. Missing history, artifacts, configuration or a
supported runtime produces a FAILED API request; no fallback or past candidate
reuse is presented as success. Existing CLI defaults remain unchanged; the
separate CLI training workflow is not invoked by the API.

Shared B1 capacity (1.75 GB) is unsafe/unverified for this inference workload.
The 2026-10-11 live verification used the dedicated B3 host (7 GB); P3v3 was a later
historical target. The current user-approved SKU is B2 (2026-10-18), and the
deployment template preserves the existing plan instead of resizing it.
These SKUs are not a measured minimum. Full retraining belongs in the separate Container Apps Job, not
on App Service; its 2 CPU/4 GiB request also requires workload-specific measurement.

## Live verification (2026-10-11)

- Endpoint: `https://web-sp500-candidate-8d0218f4.azurewebsites.net`
- At this verification date, the live backend used dedicated Linux B3 plan
  `asp-sp500-candidate`, one instance, Korea Central. P3v3/VNet is a later target,
  not part of this 2026-10-11 verification.
- Readiness uses system-assigned identity access to PostgreSQL.
- Real database-backed API smoke checks passed for candidates, all dataset routes,
  history, allowed/disallowed Origins, API-key rejection and ten-day range validation.
- Authenticated one-day RANGE for `2026-10-09` returned 202 and completed SUCCEEDED.
- Real portal page browser `fetch()` returned 200 with response type `cors` for
  readiness, candidates and daily bars.
- SEC filings/facts and universe queries were additionally verified with populated
  `2026-10-08` data. The current exchange-session table contains no stored rows;
  the endpoint correctly returns an empty list rather than inventing calendar data.
- Cutoff-fixed source deployment `a802183f-8d82-4e7c-b57c-816be39a9b3c`
  completed at `2026-10-11T08:07:33Z`, with no Oryx errors or warnings.
- Production DAILY `d58b5e37-0964-40fe-ba0e-11517566902d` completed SUCCEEDED
  at `2026-10-11T08:16:08Z`. PostgreSQL execution metadata links it to successful
  scoring `b07f33a8-de06-52cb-b0bd-ef06c9ceba11` and selection
  `3a46dac1-fc6b-5c18-a482-67d31539aa36`: ten distinct stored candidates for
  `2026-10-09`, decision cutoff `2026-10-10T09:30:00Z`, pinned model
  `f75be739-4149-518f-8cbe-1cf6296e619a`. The model remains **SHADOW**;
  successful execution does not imply promotion or a passed promotion gate.
- Explicit `selection_run_id` candidate retrieval returned those ten rows.
  After redeployment, real portal browser fetches returned 200/type `cors` for
  readiness, that exact selection and daily bars. The portal was not redeployed.
- BACKFILL `9a8e9b0c-e2de-4eca-953b-140bcdc32675` completed SUCCEEDED
  at `2026-10-11T05:32:47Z`, despite intermittent status-poll gateway errors.

### Intermittent status-poll 502 diagnosis

For `2026-10-11T05:05:00Z` through `05:35:00Z`, App Service's
`httpservererrorslinux` detector recorded 44 **502.0** responses, all on the
BACKFILL run-status GET. It classifies these as an invalid upstream response at
the gateway/proxy. There were no 502.3 proxy-timeout errors; failed responses took
approximately 0.4 seconds, not the long-request timeout interval.
Application access logs contained 171 successful 200 responses on that path and
no application-generated 502. `LinuxContainerRecycle` found no recycle event in
the window. This confirms the platform gateway failure layer; it does **not**
prove a specific connection-reset, keep-alive, CPU or memory cause.

The final DAILY smoke run also observed two transient 502 responses and recovered
before successful completion. This is **not a verified infrastructure fix**.
The verifier records each poll's UTC timestamp, HTTP status, latency and available
request/server headers, retries only 502/503/504, and fails after five consecutive
gateway errors. Preserve those timestamps and App Service detector evidence for
Azure support if errors recur; AppLens diagnostic access returned 401.
Resume verification with `--existing-run-id` rather than resubmitting accepted work.
The date-based smoke candidate check alone can see an older successful selection;
prove new DAILY output using PostgreSQL execution metadata and then retrieve
candidates with its exact `selection_run_id`, as done above.

Deployment cleanup removes only the generated secret-parameter JSON and source ZIP.
Keep the ignored local environment and selected persistent model artifacts.

## Validation

```powershell
python -m pytest tests\backend
python -m pytest tests\test_process_tracking.py tests\test_candidate_pipeline.py tests\test_backfill.py tests\selection
python -m ruff check backend tests\backend
python -m backend.smoke_test --run-mode DAILY --expected-model-id f75be739-4149-518f-8cbe-1cf6296e619a --timeout-seconds 3600 --output <daily-verification.json>
python -m backend.smoke_test --run-mode BACKFILL --output <backfill-verification.json>
python -m backend.smoke_test --run-mode DAILY --existing-run-id d58b5e37-0964-40fe-ba0e-11517566902d --output <resumed-verification.json>
```

Final integrated backend/process/candidate/backfill/selection/analytics regression
run: **146 tests passed**, including bounded gateway-retry/report persistence tests.
Ruff and `git diff --check` passed. The existing Starlette/httpx deprecation warning
does not affect test success.
