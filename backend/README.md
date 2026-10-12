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
| GET | `/api/v1/candidates` | Latest successful selection per date or explicit selection run |
| GET | `/api/v1/collection-data/{dataset}` | Normalized dataset records |

The collection dataset allowlist is `daily-bars`, `corporate-actions`, `news`,
`sec-filings`, `sec-facts`, `earnings`, `universe-members`, and `exchange-sessions`.
Both range endpoints are required; the range includes both endpoints and must not
exceed **10 calendar days**. Default page size is 100; maximum is 500. Cursors must
be reused with unchanged filters. Collection endpoints show stored observations,
not a manifest-constrained analytical input contract or historical trading replay.

### Read semantics and pagination

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
is a raw five-session return estimate, **not** a confidence/probability.

```javascript
// Run on the TradingAgents portal Origin. Reads require no API key.
const response = await fetch(
  "https://web-sp500-candidate-8d0218f4.azurewebsites.net/api/v1/candidates?limit=10"
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

[infra/backend-appservice.bicep](../infra/backend-appservice.bicep) creates a separate
Python App Service on the dedicated Linux B3 `asp-sp500-candidate` Plan (7 GB,
one instance). It does not redeploy the portal, alter its container image, or
change the portal's existing B1 plan. The dedicated plan incurs ongoing Azure cost.

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

## Operational limitations

- `BackgroundTasks` is not a durable queue. `202` means accepted, not completed.
  Poll the returned status URL.
- Use **one Uvicorn worker and one plan instance**. No scale-out. Always On is enabled.
- App Service restarts/deployments may interrupt accepted work. API-owned interrupted
  requests must become failed, not silently stay running or automatically restart.
  Inspect status before manually resubmitting.
- Do not redeploy during active collection. The API has a dedicated B3 plan, separate
  from the portal. Analytics runs still require measured memory capacity and valid
  model/export prerequisites before increasing production workloads.
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
LightGBM model plus a manifest, and configure deployment environment variables
`BACKEND_CANDIDATE_ARTIFACT_MANIFEST` and
`BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256`. The hash must pin the manifest's
exact bytes. `PipelineExecutionService(database, engine_settings)` reads these
settings; explicit keyword overrides are available for tests. Do not automatically
bundle `data\output` or select whichever model happens to exist on disk.

The manifest contains `schema_version=1`, `model_version_id`, `model_file`,
`model_sha256`, ordered `feature_names` (158 strings), `feature_config_hash`, and
`model_config_hash` (the effective model-plus-label configuration hash). Provision
only the selected model file, such as `lightgbm.txt`, and its manifest. The API
validates the registered model, artifact/manifest/config hashes, training cutoff,
and feature dimension/order. Current inference supports raw, unprocessed Alpha158
and reuses the pinned registered model.

Provision the selected registered artifact before preparing the deployment ZIP:

```powershell
python -m backend.prepare_candidate_artifact --model-version-id f75be739-4149-518f-8cbe-1cf6296e619a --source-directory data\output\phase45\e84b93ed6b6365fa23f92dfa --output-directory data\backend-artifacts\models
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
The deployed API therefore uses a dedicated B3 host (7 GB). Use
**at least 4 GB as a starting recommendation**,
not a measured minimum. Full retraining belongs on a separate host; **8 GB** is
a starting recommendation requiring workload-specific measurement.

## Live verification (2026-10-11)

- Endpoint: `https://web-sp500-candidate-8d0218f4.azurewebsites.net`
- Dedicated Linux B3 plan: `asp-sp500-candidate`, one instance, Korea Central.
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
