targetScope = 'resourceGroup'

param location string = 'koreacentral'
param appName string = 'web-sp500-candidate-8d0218f4'
param appServicePlanName string = 'asp-sp500-candidate'
param postgresHost string
param postgresDatabase string = 'candidate_engine'
param tenantId string = subscription().tenantId
param portalOrigin string = 'https://web-jongmok-portal-8d0218f4.azurewebsites.net'
param httpUserAgent string
param candidateManifestSha256 string

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
    name: 'B3'
    tier: 'Basic'
    capacity: 1
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
        { name: 'BACKEND_CANDIDATE_ARTIFACT_MANIFEST', value: 'models/manifest.json' }
        { name: 'BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256', value: candidateManifestSha256 }
        { name: 'HTTP_USER_AGENT', value: httpUserAgent }
      ]
    }
  }
}

output appId string = app.id
output principalId string = app.identity.principalId
output endpoint string = 'https://${app.properties.defaultHostName}'
