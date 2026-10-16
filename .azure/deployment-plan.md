# Azure Deployment Plan

Status: Deployed

## Candidate Top 20 contract and rollout boundary (2026-10-16)

The deployed records below are dated evidence, not proof that the new Top 20
policy, migration 022, independent LLM branch or MEDIUM dispatch gate are deployed.
The code contract is daily MEDIUM quantitative Top 20 plus an optional independent
LLM Top 20 (`LLM_PRESELECTION_ENABLED=false` by default). RRF final Top 20 remains
future work. The final Portal/TradingAgents handoff target changes from 5–10 to
20 with no secondary trim; current MEDIUM code stops at `parallel_preselection`
with zero submissions. Roll out schema, policy, backend and orchestrator validation
together, then separately validate fusion and external 20-item acceptance before
enabling handoff. Explicit SHORT legacy behavior remains unchanged.

## Scheduled daily MEDIUM_20D only (2026-10-16)

- The 05:30 ET daily gate now starts `daily_orchestrator` directly with
  `model_purpose=MEDIUM_20D` and ID `candidate-daily-YYYY-MM-DD-medium_20d`.
  Active MEDIUM instances and active legacy dual parents prevent duplicate starts.
- SHORT_5D, explicit API/manual model selection and the legacy dual workflow remain
  available. Weekly retraining still processes both model purposes independently.
- Flex deployment `9571a8d3-4f18-4e9b-84b4-8e9fcc1f40ec` is successful and
  active. The host is Running with all 22 functions indexed.
- All 101 orchestrator tests, 12 candidate API tests, Ruff and diff checks passed.
  The next scheduled 05:30 ET end-to-end run remains to be observed; validation did
  not start an additional production analysis.
- Email remains disabled and TradingAgents remains Running with min/max replicas 1.

## TradingAgents single replica and guardian floor (2026-10-16)

- User-approved scaling sets TradingAgents `minReplicas=1`, `maxReplicas=1`.
  Revision `ca-jongmok-tradingagents--single1-1016` is Healthy, receives 100%
  of traffic, and has one Running replica. The old `steady5fix` revision is
  deactivated. `ANALYSIS_WORKER_COUNT=3` is unchanged.
- Guardian treats `TRADINGAGENTS_MIN_REPLICAS=1` as a floor, not an exact
  replica target. It raises a lower minimum but never reduces a higher minimum.
- Flex deployment `763c9cbd-7a0d-43cf-98a3-e4b47cf6f90c` is active and
  successful; all 98 orchestrator tests and Ruff passed.
- Function host remains Running and `ORCHESTRATOR_EMAIL_ENABLED=false` remains
  applied. Both the new revision and production `/readyz` returned `ready`.
- A manually triggered guardian completed `SUCCEEDED` at 07:54:27 UTC, checking
  Candidate, PostgreSQL, Portal, MySQL, private Storage and TradingAgents without
  remediation.

## Email notifications disabled (2026-10-16)

- Flex OneDeploy `6522a353-64f9-4f84-8316-d0eb8735a1bf` completed successfully
  with remote build; the authenticated SCM deployment path handled the private
  deployment Storage without enabling its public endpoint or shared keys.
- `ORCHESTRATOR_EMAIL_ENABLED=false` is applied to the running Function App.
  Daily start/terminal messages and guardian alerts skip ACS calls; intentionally
  disabled notifications are recorded as `SKIPPED`, not delivery failures.
- Live host status is `Running`; all 22 indexed functions remain enabled,
  including daily/weekly timers, orchestrations and resource guardian.
- All 92 orchestrator tests and Ruff passed. ACS resources remain provisioned.

## Active preparation update: private FC1 storage network (2026-10-13)

- Use the standard Durable Functions Azure Storage backend through identity-based
  `AzureWebJobsStorage`; do not configure Durable Task Scheduler.
- Keep FC1 Storage `publicNetworkAccess=Disabled`, `defaultAction=Deny`,
  `allowSharedKeyAccess=false`, `allowBlobPublicAccess=false`, HTTPS-only and TLS 1.2.
- Add a West US 3 `10.203.0.0/16` VNet with non-overlapping `/24` subnets for
  FC1 integration and private endpoints. Delegate only the integration subnet to
  `Microsoft.App/environments`.
- Add Blob, Queue and Table storage private endpoints, matching private DNS zones,
  zone groups and VNet links. Route Function outbound traffic through the VNet.
- Keep system-assigned identity Blob, Queue and Table data roles for host, deployment
  and Durable state access; use identity-based service URIs for all three services.
- Remove scheduler/task hub resources, DTS app settings, outputs and scheduler RBAC
  from the template.
- Organization policy requires the Storage public endpoint to remain disabled.
  Preflight may restore only the private-only contract and must never enable public
  access. It verifies Blob, Queue and Table data-plane access before pipeline start.
- Before STARTED email, remediate stopped Candidate/Portal App Services,
  PostgreSQL/MySQL and TradingAgents replica state. Temporarily remove only blocking
  resource-level ReadOnly locks and restore identical locks in `finally`.
- Do not change SKU, broaden database firewall rules, rotate secrets or modify
  business data during automatic remediation.
- Existing deployed DTS resources remain unused and are retained until post-run
  decommission.

### Validation proof

- Bicep CLI build for `infra/orchestrator.bicep`: passed.
- Focused orchestrator tests: 30 passed.
- Ruff for `orchestrator` and `tests/orchestrator`: passed.
- Static tests confirm the template contains no `Microsoft.DurableTask` resources,
  DTS connection setting or scheduler-scoped RBAC.
- Expanded preflight suite: 37 passed; Ruff passed.
- ARM group validation with explicit Candidate/PostgreSQL/Portal/MySQL/
  TradingAgents resource IDs: succeeded.
- ResourceIdOnly what-if: one custom role definition and one assignment Create,
  existing orchestrator resources Deploy, all unrelated resources Ignore, no Delete.
- Private-network update validation: Bicep build passed without warnings, 38 focused
  orchestrator tests passed, and Ruff passed.
- Azure Resource Graph confirmed the selected subscription currently uses
  `10.20.0.0/16` and `10.82.0.0/16`; the new `10.203.0.0/16` does not overlap.
- Deployment/package implication: a runner outside the VNet cannot upload directly
  to the deployment Blob container. Use authenticated Flex OneDeploy with remote
  build (verified 2026-10-16), or a VNet-connected private-DNS-capable runner for
  direct Blob upload. Keep Storage public access disabled in either case.

### Deployment verification

- Function App: `https://sp500-orch-f4djpkceudqgy.azurewebsites.net`, Running,
  11 indexed functions.
- Storage public network, shared key and anonymous Blob access are Disabled.
  Blob/Queue/Table private endpoints are Approved and private DNS links Completed.
- Candidate deployment `cf6145f7-14fd-4b6d-8b73-a565ad776ba8` completed and
  `/health/ready` returned `ready`.
- Migration `020_backend_pipeline_idempotency` was applied while the original
  PostgreSQL ReadOnly lock was restored.
- Durable instance `candidate-daily-2026-10-09-short_5d` completed `SUCCEEDED`.
- Candidate process `f52dcc13-3d5f-4dc6-a2d8-35d0ad5e846b` completed one date
  with no failed dates.
- Existing market/event/filing/fact revisions produced zero new persisted rows;
  the versioned universe contract returned 503 members.
- SHORT_5D selection `639490fb-67cd-566a-aa3d-5bce2ade1015` returned ten
  five-session candidates.
- Portal `DailyAnalysis #10` is terminal with ten completed jobs, ten reports and
  zero failed jobs.
- ACS Email activities for the successful run completed at
  2026-10-12T19:01:31Z and 2026-10-12T19:22:00Z with no failures.

## Active deployment update: MEDIUM_20D backend (2026-10-11)

Deploy the existing backend App Service source with the additive multi-model API and
MEDIUM_20D candidate contract. Do not provision or modify infrastructure.

### Scope

- Target existing app `web-sp500-candidate-8d0218f4` in `rg-ai-project`.
- Keep existing dedicated Linux B3 plan, Python 3.11, one worker and Managed Identity.
- Package source only; never include `.env`, model outputs, raw data or credentials.
- Database migrations `018_multi_model_support` and
  `019_advanced_feature_availability` are already applied by the Entra administrator.
- Default `GET /api/v1/candidates` must return `MEDIUM_20D`.
- Explicit `model_purpose=SHORT_5D` must preserve the existing five-session model.
- Missing MEDIUM_20D results must not silently fallback to SHORT_5D.
- Azure OpenAI news classification remains optional and is not required for API startup.
- No portal deployment or infrastructure change.

### Update checklist

- [x] MEDIUM_20D model trained and 2026-10-09 candidates persisted
- [x] Additive database migrations applied and existing SHORT_5D models preserved
- [x] Full application tests, Ruff, compile and package exclusion checks
- [x] Local API default/explicit-purpose functional verification
- [x] Source ZIP generation and secret scan
- [x] Azure validation handoff complete
- [x] Existing App Service ZIP deployment complete
- [x] Live readiness, default MEDIUM_20D, SHORT_5D and portal CORS verified

### Update functional verification

- Full Python suite: 214 passed using `.venv-alpha158`.
- Ruff `src backend tests scripts`: passed.
- `compileall src backend`: passed.
- Local `/health/ready`: 200/ready.
- Local candidate GET without `model_purpose`: 10 `MEDIUM_20D`, horizon 20.
- Local explicit `model_purpose=SHORT_5D`: 10 `SHORT_5D`, horizon 5.
- No Azure OpenAI configuration is required for backend startup or candidate reads.

### Update validation proof

- Azure CLI context: subscription `8d0218f4-f340-446d-b76a-3ff419b03e77`.
- Deployment ZIP: 124 entries, forbidden secret/raw/output paths 0.
- Bicep build: passed; only BCP081 type-availability warnings for the selected API version.
- ARM group validate: passed.
- ResourceIdOnly what-if: existing `asp-sp500-candidate` and
  `web-sp500-candidate-8d0218f4` Deploy, portal and unrelated resources Ignore,
  no Delete.
- The installed azure-validate `references/scripts` directory was empty. The official
  `microsoft/azure-skills` workflow helper was fetched from the trusted upstream
  repository and completed after the equivalent checks above.

### Update deployment verification

- OneDeploy ID: `22c85d46-51e4-4b65-b2c7-0c4206df6ec6`
- Runtime status: successful, one instance succeeded, zero failed.
- Kudu deployment status 4, complete/active, errors 0, warnings 0.
- App Service: Running in Korea Central on existing `asp-sp500-candidate`.
- `GET /health/ready`: 200, `ready`.
- Candidate GET without model option: 10 `MEDIUM_20D`, horizon 20.
- Explicit `model_purpose=SHORT_5D`: 10 `SHORT_5D`, horizon 5.
- Portal-origin browser fetch: 200, 10 `MEDIUM_20D`, horizon 20.
- Managed identity Azure RBAC assignments at app scope: none, as designed.
- PostgreSQL data-plane access: verified through live readiness and candidate reads.
- AppServiceConsoleLogs table was not yet available in Log Analytics; Kudu deployment
  logs and live endpoint verification provide deployment/runtime evidence.

### All update validation checks pass

- [x] Application tests, lint, compile and editor diagnostics
- [x] Deployment package content and secret exclusion
- [x] Bicep build and ARM group validate
- [x] ResourceIdOnly what-if with no deletes or portal changes
- [x] Static Managed Identity and least-privilege data-plane grant review
- [x] Local runtime readiness and MEDIUM_20D/SHORT_5D endpoint verification

## Active deployment: Backend API (2026-10-11)

Implement `backend/plan.md` and deploy a separate Linux App Service with Python 3.11,
single Uvicorn worker, Always On, Managed Identity PostgreSQL access, and exact
TradingAgents portal Origin CORS. Use Bicep and Azure CLI zip deployment.
Existing portal must not be redeployed.

### Confirmed execution context

- Subscription: ME-MngEnvMCAP572020-annajeong-1 (`8d0218f4-f340-446d-b76a-3ff419b03e77`).
- Resource group: existing `rg-ai-project` (RG metadata location West US 3).
- App and PostgreSQL region: **Korea Central**, explicitly set regardless of RG metadata.
- App: `web-sp500-candidate-8d0218f4`; dedicated Linux B3 `asp-sp500-candidate`.
- No change to the existing portal container, configuration, or plan size.
- One single-worker API app; no scale-out and no durable queue promise.
- PostgreSQL: `pg-jongmok-candidate-8d0218f4`, Entra-only, TLS, database `candidate_engine`.
- Secrets: secure Bicep parameters into encrypted App Settings, never ZIP contents.
- API key generated locally into ignored `backend/.env`; parameter file removed after deployment.
- User requested implementation/deployment; context confirmation tool returned user unavailable.
  Proceed with the existing subscription and same-region separate app, without deleting resources.

### Provisioning limits and policy evidence

| Resource | New | Total after | Evidence |
|---|---:|---:|---|
| Microsoft.Web/sites | 1 | 2 | API isolated from portal |
| Microsoft.Web/serverfarms | 1 | 2 | Dedicated B3 capacity 1 |
| Regional Web VMs | 1 | Within quota | `az quota list` limit 11; Web usage API current 0 |

2026-10-11: registered Microsoft.Quota and checked Microsoft.Web quota.
`isQuotaApplicable=false` means the quota response is informational, not unlimited.
Dedicated backend requests one regional compute instance.
Effective policy assignments queried; final ARM validate/what-if required.
Owner role inherited from tenant management group verified for deployment principal.
No new VM, public IP, storage account, or Key Vault. Additional App Service compute
charge applies for dedicated B3; portal and API do not share plan memory/CPU.

### Active execution checklist

- [x] Backend implementation and Python 3.11 targeted API/regression tests
- [x] Bicep build, ARM validate/what-if, source ZIP/secret exclusion
- [x] azure-validate status and validation proof
- [x] Separate API deployment and PostgreSQL managed identity grants
- [x] Live reads, invalid/authenticated execution tests, exact-origin CORS and browser fetch

### Final Backend Deployment Verification

2026-10-11: source deployment `a802183f-8d82-4e7c-b57c-816be39a9b3c`
completed at 08:07:33 UTC (Kudu status 4, complete/active, build errors/warnings 0).
Endpoint: https://web-sp500-candidate-8d0218f4.azurewebsites.net

Production DAILY `d58b5e37-0964-40fe-ba0e-11517566902d` completed SUCCEEDED
at 08:16:08 UTC. Read-only PostgreSQL lineage verification confirmed scoring
`b07f33a8-de06-52cb-b0bd-ef06c9ceba11` and selection
`3a46dac1-fc6b-5c18-a482-67d31539aa36` SUCCEEDED, ten distinct candidates,
session 2026-10-09, cutoff 2026-10-10 09:30 UTC and the pinned SHADOW model.
Exact-selection GET and real portal browser readiness/candidate/daily-bar fetches
returned 200 with CORS. No portal deployment. Final regressions: 146 passed; Ruff passed.
Live ARM role-assignment query for the app identity returned no assignments;
PostgreSQL data-plane access and successful execution were independently verified.

Operational caveat: App Service diagnosed 44 historical BACKFILL poll failures
as 502.0 invalid gateway upstream responses, with no 502.3 or container recycle
in the 05:05-05:35 UTC window. Final DAILY observed two transient 502s and recovered.
The exact lower-level connection cause remains unconfirmed; this deployment does
not claim to eliminate gateway errors. See [backend runbook](../backend/README.md).
Generated secret parameters and source ZIP are removed after final verification;
ignored local environment and persistent model artifacts are retained.

### Active Validation Proof

Final artifact/settings revalidation (2026-10-11): backend tests 81 passed,
Ruff passed; Bicep build and ARM validate passed. ARM what-if deploys only
`asp-sp500-candidate` and `web-sp500-candidate-8d0218f4`, ignores 34 resources
including portal. SHA-pinned manifest and selected model uploaded and checksum verified.
No infrastructure RBAC grants are added; existing PostgreSQL data-plane grants remain.

2026-10-11: integrated backend plus existing process/candidate/backfill/selection tests:
93 passed. Ruff backend/tests/modified engine modules: passed. compileall: passed.
Source-only wheel excludes .env and configured secret values. Packaging test passed.
Bicep build passed (latest ARM API schema unavailable in local Bicep warning only).
ARM validation passed. What-if: one API app Create, portal and all existing resources Ignore.
Quota and deployment Owner checked; local PostgreSQL data-plane connectivity passed after
starting the previously stopped database. PostgreSQL identity grants are handled by
administrator script after provisioning; app does not receive ARM Owner/Contributor.
Historical VM validation below is not evidence for this App Service deployment.

## 7. Backend Validation Proof

Final source-fix revalidation (2026-10-11): backend, process tracking, candidate,
backfill, selection and analytics pytest suites all passed; Ruff passed.
ARM group validate passed for unchanged dedicated B3 infrastructure/settings.
Source ZIP rebuilt after explicit decision-cutoff fix; packaging exclusion tests passed.
No active API or external process runs at predeployment check.

2026-10-11:
- Official `microsoft/azure-skills` pinned validation helper (local skill installation
  was missing scripts): CLI/auth/Bicep/ARM validate/what-if OVERALL PASS.
- ARM what-if scope reviewed: API site Create, no portal Modify/Delete.
- Python 3.11 pytest integrated run: 93 passed; Ruff and compileall passed.
- Local running API with real PostgreSQL: 18 smoke checks passed, including all eight
  collection datasets, candidate cursor, readiness, API-key rejection, 10-day limit,
  allowed portal preflight and rejected unrelated Origin.
- `sql/017_backend_requests.sql` applied by Entra administrator.
- Wheel/source packaging tests passed; generated `.env` and deployment parameters ignored.
- Static identity: system-assigned App Service identity; PostgreSQL data permissions
  provisioned with `grant_database_access.py`. No Azure ARM permission assigned to app.
- Public PostgreSQL firewall remains restricted to explicit client/app outbound addresses.
- No unresolved application/infrastructure validation failure.

### All validation checks pass
- [x] CLI/auth/Bicep build and ARM validation
- [x] What-if scope reviewed; no portal modifications or deletion
- [x] Policy validation through ARM validation
- [x] Application tests, compile and lint
- [x] Static identity/data permission script reviewed
- [x] Official azure-validate workflow and proof finalization

### Backend compute isolation update

The initial separate API site was provisioned on the existing B1 plan, but candidate
inference and Oryx build memory are unsuitable for sharing 1.75 GB with the portal.
Keep portal and existing plan unchanged; move API only to dedicated
`asp-sp500-candidate`, Linux B3, 7 GB, one instance. Additional ongoing compute cost
applies. Asked for confirmation; user unavailable, selecting isolation to fulfill
full candidate execution verification without risking portal availability.
Regional Web usage 0 / limit 11 previously checked; request one new plan instance.
Rerun ARM validate and what-if before this compute deployment.
Validation rerun: official core helper OVERALL PASS; filtered ARM what-if shows
only new `asp-sp500-candidate` Create and API site Modify. Portal is Ignore.
Application code and static data permissions unchanged; prior 93 tests and 18
database-backed smoke checks remain applicable. Official validation workflow repeated.

The cancelled VM plan below is retained as historical context, not authorization
to provision a VM.

## Objective

- Complete and validate the maximum-data historical backfill implementation.
- Deploy the repository to one Ubuntu Azure VM in the current Azure subscription.
- Use password authentication as explicitly requested.
- Store the generated VM password only in an ignored temporary local file.
- Ensure no Azure auto-shutdown schedule is configured for the VM.
- Run the recent three-month backfill only after implementation, validation, and deployment checks pass.

## Final Outcome

- The user cancelled VM deployment and selected local execution on 2026-10-10.
- No West US 3 VM was deployed.
- Local process `9d333911-64e9-4f81-bd88-5cfc60f86bef` completed 65 of 65 sessions successfully.
- Azure deployment validation stopped after live capacity checks; this plan must be prepared and validated again before any future deployment.

## Current Assumptions

- Subscription: ME-MngEnvMCAP572020-annajeong-1, `8d0218f4-f340-446d-b76a-3ff419b03e77`.
- Region: West US 3.
- Resource group: existing `rg-ai-project`.
- VM OS: Ubuntu 24.04 LTS.
- VM size: Standard_D4as_v5, 4 vCPU and 16 GB; same-region D-series fallback is allowed if live capacity rejects it.
- Database: existing Azure Database for PostgreSQL Flexible Server `candidate_engine`.
- Authentication to PostgreSQL: Microsoft Entra through Azure CLI locally and managed identity or equivalent non-secret Azure credential on the VM.
- VM login: generated strong password stored locally outside Git.

## Planned Work

1. Finish backfill implementation:
   - Range-based Massive dividends, splits, and chunked news.
   - SEC bulk ZIP normalization and filing/fact persistence.
   - Parent raw snapshots and per-date derived snapshots.
   - Daily 05:30 ET historical cutoffs.
   - Staging/COPY or equivalent set-based persistence.
   - Checkpoints, stale-run recovery, retry queue, and process logs.
2. Add tests:
   - Duplicate logical rows and revisions.
   - Future-data leakage.
   - Retry ordering after initial batch completion.
   - Resume after interruption.
   - Per-run and per-date live logs.
3. Update architecture and pipeline documentation.
4. Validate locally without running the three-month collection.
5. Prepare Azure VM deployment artifacts.
6. Validate Azure context, region, quota, policy, network, and VM cost assumptions.
7. Obtain user approval for this completed plan.
8. Invoke `azure-validate`.
9. Invoke `azure-deploy`.
10. Create and configure the VM:
    - Ubuntu 24.04 LTS.
    - Password login.
    - System-assigned managed identity.
    - Repository checkout and Python environment.
    - `.env` created on the VM without committing secrets.
    - No `Microsoft.DevTestLab/schedules` auto-shutdown resource.
    - Verify OS has no shutdown timer.
11. Run the three-month backfill.
12. Verify database counts, future-row count, retries, logs, and process completion.

## Requirements

- Classification: Development internal batch.
- Scale: one VM, one backfill process, 65 XNYS sessions.
- Budget: cost-optimized burstable VM selected by user.
- Compliance: no additional regional or organizational requirements beyond the active Azure policies.
- Availability: single VM; this is an auxiliary backfill path, not a highly available service.

## Recipe

- Recipe: Azure CLI.
- Rationale: one existing repository, one existing resource group/PostgreSQL server, and one explicitly requested VM with custom password/SFTP bootstrap.
- No `azd init` or template conversion is required.

## Azure Context

- Subscription: `ME-MngEnvMCAP572020-annajeong-1`.
- Subscription ID: `8d0218f4-f340-446d-b76a-3ff419b03e77`.
- Region: `westus3`.
- Resource group: `rg-ai-project`.

## Planned Azure Resources

| Resource | Name | Configuration |
|---|---|---|
| VNet | `vnet-sp500-backfill-wus3` | `10.83.0.0/16` in West US 3 |
| Subnet | `snet-sp500-backfill` | `10.83.5.0/24` |
| NSG | `nsg-sp500-backfill-wus3` | SSH 22 from Internet, explicitly approved by user |
| Public IP | `vm-sp500-backfill-wus3-pip` | Standard, static IPv4 |
| NIC | `vm-sp500-backfill-wus3-nic` | VM subnet, public IP, NSG |
| VM | `vm-sp500-backfill-wus3` | Ubuntu 24.04, Standard_D4as_v5, 64 GB Standard SSD |
| Managed identity | system-assigned | PostgreSQL Entra authentication target |

No Key Vault or new storage account is planned. Provider secrets are copied over password-authenticated SFTP into `/opt/sp500-candidate-engine/.env` with mode 0600. This is a development-only deviation from the preferred Key Vault pattern.

## Network and Database Access

- Create a separate West US 3 VNet because Azure VNets and NSGs cannot change regions.
- New VNet: `vnet-sp500-backfill-wus3`, `10.83.0.0/16`.
- New VM subnet: `snet-sp500-backfill`, `10.83.5.0/24`.
- PostgreSQL `pg-jongmok-candidate-8d0218f4` currently has public network access enabled and Microsoft Entra-only authentication.
- Add one PostgreSQL firewall rule for the VM's static public IPv4 address after deployment.
- Do not enable the broad "Allow Azure services" firewall rule.
- Use the VM system-assigned managed identity and a PostgreSQL role created by the Entra administrator.

## Policy Constraints

- Azure Security Baseline assignment applies.
- MCAPSGov deny, audit, deploy/modify policy initiatives apply.
- Defender-related subscription policies apply.
- The current effective assignment summary contains Defender/OpenSourceRelationalDatabases policies; validation must still surface any inherited deny.

## Quota and Availability

- West US 3 compute quota check reports available VM quota.
- Planned vCPUs: 4.
- Standard_D4as_v5 is supported in West US 3 and is the first deployment choice.
- If live capacity rejects it, use Standard_D4s_v5, Standard_D2as_v5, then Standard_D2s_v5 without leaving West US 3.
- Prior Korea Central failures for B4ms, D4s_v5, and D4as_v5 were live capacity restrictions and do not apply to West US 3.
- Existing VMs in the resource group: 0.
- Existing public IPs in the resource group: 0.

## Cost Estimate

- Standard_D4as_v5 Linux consumption in West US 3: approximately USD 0.172/hour.
- 730-hour compute estimate: approximately USD 125.56/month.
- OS disk and public IP are additional.
- Auto-shutdown is intentionally disabled, so cost continues until the VM is manually stopped/deallocated or deleted.

## Security

- Never commit `.env`, provider keys, VM password, raw payloads, or runtime logs.
- Store the VM password in a local ignored temporary file with restricted ACL.
- Do not print passwords or API keys in command output or logs.
- Restrict SSH to the current client IP where possible.
- User explicitly selected Internet-wide SSH access; record this as a development risk and keep password complexity high.
- Prefer managed identity for Azure resource access from the VM.
- Use TLS for PostgreSQL.

## Auto-Shutdown Requirement

- Do not create an auto-shutdown schedule.
- Query `Microsoft.DevTestLab/schedules` after VM creation.
- Remove only a schedule created for this VM if one unexpectedly exists, after explicit destructive-action confirmation if required.
- Verify no guest OS shutdown timer is enabled.

Current resource-group check returned zero `Microsoft.DevTestLab/schedules`.

## Validation Gates

- Unit tests, lint, format, type diagnostics, and Mermaid validation pass.
- Backfill dry-run reports the expected XNYS sessions and provider budgets.
- No API or DB mutation occurs before the execution phase.
- Azure policy and quota checks pass.
- VM is reachable and remains running.
- Three-month backfill has zero future rows.
- Failed dates are retried only after the initial pass.
- Final process status and per-run log are available.
- Local test suite: 35 passed.
- Ruff lint and format: passed.
- Pylance and editor diagnostics: no errors.
- Mermaid validation: passed.
- No backfill API or DB execution was performed during local implementation.

## Role Assignment Verification

- Status: Verified with one post-deployment database action.
- Identity checked after deployment: system-assigned identity of `vm-sp500-backfill-wus3`.
- Azure RBAC roles: none required because the VM does not read Blob Storage or Key Vault and only requests an Entra token.
- PostgreSQL data-plane role: must be created after the VM principal ID exists, with least-privilege grants on `ops`, `ref`, `market`, `event`, and `fundamental`.
- Management-plane Contributor/Owner roles are not assigned to the VM.

### All validation checks pass

- [ ] 1. Core Validation: Azure CLI, authentication, Bicep build, group validation, and what-if
- [ ] 2. Linting: Bicep lint
- [ ] 3. Azure Policy Validation: active assignments reviewed and group validation/what-if reports no deny

- [x] 1. Core Validation: Azure CLI, authentication, Bicep build, group validation, and what-if
- [x] 2. Docker Build: not applicable because the VM runs the Python project directly
- [x] 3. Azure Policy Validation: policy assignments reviewed and group validate/what-if passed

## Previous Validation Proof

The following proof applies to the superseded Korea Central plan. West US 3 validation must replace it before deployment.

- Command: `python -m pytest`
  - Result: PASS, 35 tests.
- Command: `python -m ruff check src tests scripts/azure/upload_and_bootstrap.py`
  - Result: PASS.
- Command: `python -m ruff format --check src tests scripts/azure/upload_and_bootstrap.py`
  - Result: PASS.
- Command: `az bicep build --file infra/main.bicep`
  - Result: PASS.
- Command: `validate-deployment.ps1 -Scope group -ResourceGroup rg-ai-project -Template infra/main.bicep -Parameters .azure/validate.parameters.tmp.json`
  - Result: OVERALL PASS.
- Command: `az deployment group what-if`
  - Result: PASS, Create 2, Modify 0, Delete 0.
- Command after B4ms capacity fallback: `validate-deployment.ps1` with Standard_D4s_v5
  - Result: OVERALL PASS, Create 0, Modify 0, Delete 0 after partial resources from the failed B4ms attempt.
- Command: `pip wheel . --no-deps`
  - Result: PASS.
- Azure CLI installed: PASS
- Azure authentication: PASS
- Bicep compilation: PASS
- Resource-group deployment validation: PASS
- What-if: PASS, Create 2, Modify 0, Delete 0
- Policy validation: PASS through deployment validate/what-if; no deny surfaced
- Local tests: 35 passed
- Python wheel build: PASS, `sp500_candidate_engine-0.1.0-py3-none-any.whl`
- Ruff lint/format: PASS
- Pylance/editor diagnostics: PASS
- Mermaid validation: PASS

## Open Decisions

- No blocking user decisions remain.
- Alpha historical earnings remain intentionally unavailable.
- Wikipedia universe history is accepted as reconstruction until licensed S&P history is available.

## Approval Record

- 2026-10-09: User explicitly requested completion of the maximum-data backfill implementation, tests, data architecture, documentation, and repository push before any Azure deployment.
- Azure VM provisioning and three-month execution remain pending after local implementation and validation.
- User selected current subscription, Korea Central, `rg-ai-project`, Development classification, Standard_B4ms, Internet-wide SSH, and no additional compliance constraints.
- After Standard_B4ms returned `SkuNotAvailable`, user selected Standard_D4s_v5 in Korea Central.
- After Standard_D4s_v5 also returned `SkuNotAvailable`, user selected Standard_D4as_v5.
- 2026-10-10: User explicitly selected West US 3, any available D-series size, password authentication, pipeline deployment, and three-month backfill execution.
- User explicitly instructed the agent to execute Azure deployment and the three-month pipeline after implementation.

## Status Checklist

- [x] Workspace and backfill implementation analyzed
- [x] Azure requirements gathered
- [x] Azure policy, region, quota, and pricing checked
- [x] Deployment architecture finalized
- [x] User approved plan
- [x] Local implementation complete
- [x] Local validation complete
- [x] Status updated to Ready for Validation
- [ ] Azure validation complete for West US 3
- [ ] Azure deployment complete
- [x] Local three-month backfill complete
- [x] Post-run verification complete
