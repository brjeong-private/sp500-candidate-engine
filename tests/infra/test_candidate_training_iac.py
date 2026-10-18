from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"


def _template(relative_path: str) -> str:
    return (INFRA / relative_path).read_text(encoding="utf-8")


def test_candidate_training_bootstraps_without_job_in_korea_central() -> None:
    template = _template("candidate-training.bicep")

    assert "param location string = 'koreacentral'" in template
    assert "param deployTrainingJob bool = false" in template
    assert "if (deployTrainingJob)" in template
    assert "internal: true" in template


def test_artifacts_are_private_premium_and_versioned() -> None:
    template = _template("modules/candidate-artifacts.bicep")

    assert "name: 'Standard_ZRS'" in template
    assert "isVersioningEnabled: true" in template
    assert template.count("publicNetworkAccess: 'Disabled'") == 2
    assert "name: 'Premium'" in template
    assert "allowSharedKeyAccess: false" in template
    assert "Blob Data Contributor" not in template
    assert "ba92f5b4-2d11-453d-a403-e96b0029c9fe" in template
    assert "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1" in template
    assert "7f951dda-4ed3-4680-a7ca-43fe172d538d" in template


def test_network_has_isolated_subnets_private_endpoints_and_dns() -> None:
    template = _template("modules/candidate-network.bicep")

    assert "Microsoft.App/environments" in template
    assert "Microsoft.Web/serverFarms" in template
    assert "privateEndpointNetworkPolicies: 'Disabled'" in template
    for zone in (
        "privatelink.blob.${environment().suffixes.storage}",
        "privatelink.azurecr.io",
        "privatelink.postgres.database.azure.com",
    ):
        assert zone in template
    for group_id in ("'blob'", "'registry'", "'postgresqlServer'"):
        assert group_id in template


def test_training_job_is_manual_consumption_with_required_resources() -> None:
    template = _template("modules/candidate-training-job.bicep")

    assert "triggerType: 'Manual'" in template
    assert "workloadProfileName: 'Consumption'" in template
    assert "cpu: json('2.0')" in template
    assert "memory: '4Gi'" in template
    assert "type: 'UserAssigned'" in template
    assert "name: 'AZURE_SUBSCRIPTION_ID'" in template
    assert "name: 'AZURE_TENANT_ID'" in template
    assert "name: 'PGUSER'" in template
    assert "value: postgresUser" in template


def test_backend_preserves_existing_plan_sku_and_integrates_with_vnet() -> None:
    template = _template("backend-appservice.bicep")

    assert "resource plan 'Microsoft.Web/serverfarms@2026-08-01' existing = {" in template
    assert "appServicePlanSkuName" not in template
    assert "appServicePlanSkuTier" not in template
    assert "appServicePlanCapacity" not in template
    assert "serverFarmId: plan.id" in template
    assert "virtualNetworkSubnetId: vnetIntegrationSubnetId" in template
    assert "vnetRouteAllEnabled: true" in template


def test_orchestrator_job_role_can_only_read_and_start_jobs() -> None:
    template = _template("candidate-training.bicep")

    assert "'Microsoft.App/jobs/read'" in template
    assert "'Microsoft.App/jobs/start/action'" in template
    assert "'Microsoft.App/jobs/executions/read'" in template
