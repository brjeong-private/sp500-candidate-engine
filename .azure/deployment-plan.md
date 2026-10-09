# Azure Deployment Plan

Status: Ready for Validation

## Objective

- Complete and validate the maximum-data historical backfill implementation.
- Deploy the repository to one Ubuntu Azure VM in the current Azure subscription.
- Use password authentication as explicitly requested.
- Store the generated VM password only in an ignored temporary local file.
- Ensure no Azure auto-shutdown schedule is configured for the VM.
- Run the recent three-month backfill only after implementation, validation, and deployment checks pass.

## Current Assumptions

- Subscription: ME-MngEnvMCAP572020-annajeong-1, `8d0218f4-f340-446d-b76a-3ff419b03e77`.
- Region: Korea Central.
- Resource group: existing `rg-ai-project`.
- VM OS: Ubuntu 24.04 LTS.
- VM size: Standard_B4ms, 4 vCPU and 16 GB class.
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
- Compliance: Korea region only, no additional requirements.
- Availability: single VM; this is an auxiliary backfill path, not a highly available service.

## Recipe

- Recipe: Azure CLI.
- Rationale: one existing repository, one existing resource group/VNet/PostgreSQL server, and one explicitly requested VM with custom password/SFTP bootstrap.
- No `azd init` or template conversion is required.

## Azure Context

- Subscription: `ME-MngEnvMCAP572020-annajeong-1`.
- Subscription ID: `8d0218f4-f340-446d-b76a-3ff419b03e77`.
- Region: `koreacentral`.
- Resource group: `rg-ai-project`.

## Planned Azure Resources

| Resource | Name | Configuration |
|---|---|---|
| Subnet | `sp500-backfill` | `10.82.5.0/24` in existing `vnet-jongmok-prd` |
| NSG | `nsg-sp500-backfill` | SSH 22 from Internet, explicitly approved by user |
| Public IP | `pip-sp500-backfill` | Standard, static IPv4 |
| NIC | `nic-sp500-backfill` | VM subnet, public IP, NSG |
| VM | `vm-sp500-backfill` | Ubuntu 24.04, Standard_B4ms, 64 GB Standard SSD |
| Managed identity | system-assigned | PostgreSQL Entra authentication target |

No Key Vault or new storage account is planned. Provider secrets are copied over password-authenticated SFTP into `/opt/sp500-candidate-engine/.env` with mode 0600. This is a development-only deviation from the preferred Key Vault pattern.

## Existing Network

- VNet: `vnet-jongmok-prd`, `10.82.0.0/16`.
- Existing delegated subnets cannot host the VM.
- Existing private-endpoints subnet is reserved for private endpoints.
- New VM subnet uses unused `10.82.5.0/24`.
- PostgreSQL private DNS zone `privatelink.postgres.database.azure.com` is linked to the VNet.

## Policy Constraints

- Azure Security Baseline assignment applies.
- MCAPSGov deny, audit, deploy/modify policy initiatives apply.
- `Block Azure RM Resource Creation` assignment may deny VM or network creation; Azure validation must surface an explicit deny before deployment.
- Defender-related subscription policies apply.
- West Europe is blocked; selected Korea Central is unaffected by that region restriction.

## Quota and Availability

- Total Regional vCPUs: limit 100, usage 0.
- Standard BS Family vCPUs: limit 100, usage 0.
- Planned vCPUs: 4.
- Standard_B4ms appears in Korea Central VM size listing.
- Existing VMs in the resource group: 0.
- Existing public IPs in the resource group: 0.

## Cost Estimate

- Standard_B4ms Linux consumption: approximately USD 0.208/hour.
- 730-hour compute estimate: approximately USD 151.84/month.
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

## Open Decisions

- No blocking user decisions remain.
- Alpha historical earnings remain intentionally unavailable.
- Wikipedia universe history is accepted as reconstruction until licensed S&P history is available.

## Approval Record

- 2026-10-09: User explicitly requested completion of the maximum-data backfill implementation, tests, data architecture, documentation, and repository push before any Azure deployment.
- Azure VM provisioning and three-month execution remain pending after local implementation and validation.
- User selected current subscription, Korea Central, `rg-ai-project`, Development classification, Standard_B4ms, Internet-wide SSH, and no additional compliance constraints.
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
- [ ] Azure validation complete
- [ ] Azure deployment complete
- [ ] Three-month backfill complete
- [ ] Post-run verification complete
