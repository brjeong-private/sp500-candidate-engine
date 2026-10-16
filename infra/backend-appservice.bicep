targetScope = 'resourceGroup'

param location string = 'koreacentral'
param appName string = 'web-sp500-candidate-8d0218f4'
param appServicePlanName string = 'asp-sp500-candidate'
param postgresHost string
param postgresDatabase string = 'candidate_engine'
param tenantId string = subscription().tenantId
param portalOrigin string = 'https://web-jongmok-portal-8d0218f4.azurewebsites.net'
param httpUserAgent string
param candidateShortManifestSha256 string
param candidateMediumManifestSha256 string
param vnetIntegrationSubnetId string
param appServicePlanSkuName string = 'P3v3'
param appServicePlanSkuTier string = 'PremiumV3'
param azureOpenAIAccountName string = ''
param azureOpenAIEndpoint string = ''
param azureOpenAIDeployment string = ''
param azureOpenAIApiVersion string = ''
param llmPreselectionEnabled bool = false
@minValue(1)
param appServicePlanCapacity int = 1

@secure()
param apiKey string

@secure()
param massiveApiKey string

@secure()
param alphaVantageApiKey string

resource plan 'Microsoft.Web/serverfarms@2026-08-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: appServicePlanSkuName
    tier: appServicePlanSkuTier
    capacity: appServicePlanCapacity
  }
  properties: {
    reserved: true
  }
}

resource app 'Microsoft.Web/sites@2026-08-01' = {
  name: appName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  tags: {
    workload: 'sp500-candidate-api'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    virtualNetworkSubnetId: vnetIntegrationSubnetId
    vnetRouteAllEnabled: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'python -m uvicorn backend.app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1'
      alwaysOn: true
      healthCheckPath: '/health/ready'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      ftpsState: 'Disabled'
      http20Enabled: true
      // FastAPI owns CORS so error responses and API key preflights use one policy.
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'ENABLE_ORYX_BUILD', value: 'true' }
        { name: 'PYTHONPATH', value: '/home/site/wwwroot/src:/home/site/wwwroot' }
        { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
        { name: 'AZURE_TENANT_ID', value: tenantId }
        { name: 'AZURE_CREDENTIAL_MODE', value: 'default' }
        { name: 'PGHOST', value: postgresHost }
        { name: 'PGPORT', value: '5432' }
        { name: 'PGDATABASE', value: postgresDatabase }
        { name: 'PGUSER', value: appName }
        { name: 'PGSSLMODE', value: 'require' }
        { name: 'PGCONNECT_TIMEOUT', value: '30' }
        { name: 'BACKEND_API_KEY', value: apiKey }
        { name: 'BACKEND_CORS_ORIGINS', value: portalOrigin }
        { name: 'MASSIVE_API_KEY', value: massiveApiKey }
        { name: 'ALPHA_VANTAGE_API_KEY', value: alphaVantageApiKey }
        { name: 'RAW_DATA_DIR', value: '/home/candidate-engine/data/raw' }
        { name: 'LOG_DIR', value: '/home/candidate-engine/logs' }
        { name: 'BACKEND_WORKSPACE_DIR', value: '/home/candidate-engine' }
        { name: 'BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHORT_5D', value: 'models/short_5d/manifest.json' }
        { name: 'BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256_SHORT_5D', value: candidateShortManifestSha256 }
        { name: 'BACKEND_CANDIDATE_ARTIFACT_MANIFEST_MEDIUM_20D', value: 'models/medium_20d/manifest.json' }
        { name: 'BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256_MEDIUM_20D', value: candidateMediumManifestSha256 }
        { name: 'HTTP_USER_AGENT', value: httpUserAgent }
        { name: 'LLM_PRESELECTION_ENABLED', value: string(llmPreselectionEnabled) }
        { name: 'AZURE_OPENAI_ENDPOINT', value: azureOpenAIEndpoint }
        { name: 'AZURE_OPENAI_DEPLOYMENT', value: azureOpenAIDeployment }
        { name: 'AZURE_OPENAI_API_VERSION', value: azureOpenAIApiVersion }
        { name: 'AZURE_OPENAI_LLM_PROMPT_VERSION', value: 'llm-preselection-v1' }
        { name: 'AZURE_OPENAI_TIMEOUT_SECONDS', value: '60' }
      ]
    }

  }
}

resource azureOpenAI 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = if (!empty(azureOpenAIAccountName)) {
  name: azureOpenAIAccountName
}

var cognitiveServicesOpenAIUserRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
)

resource azureOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(azureOpenAIAccountName)) {
  name: guid(azureOpenAI.id, app.id, cognitiveServicesOpenAIUserRoleId)
  scope: azureOpenAI
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: cognitiveServicesOpenAIUserRoleId
  }
}

output appId string = app.id
output principalId string = app.identity.principalId
output endpoint string = 'https://${app.properties.defaultHostName}'
