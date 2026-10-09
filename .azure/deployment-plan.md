# Azure Deployment Plan

Status: Cancelled - local backfill selected

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
