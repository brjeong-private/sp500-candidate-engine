targetScope = 'resourceGroup'

@description('Azure region that supports Linux Flex Consumption.')
param location string = resourceGroup().location

@minLength(3)
@maxLength(20)
@description('Lowercase prefix used for orchestrator resource names.')
param namePrefix string = 'sp500-orch'

@description('Candidate Engine HTTPS base URL.')
param candidateApiUrl string

@description('Candidate Engine App Service full ARM resource ID.')
param candidateResourceId string

@description('Portal HTTPS base URL.')
param portalApiUrl string

@description('Portal App Service full ARM resource ID.')
param portalResourceId string

@minLength(9)
@description('Required TradingAgents HTTPS base URL. Production preflight requires /readyz to report ready.')
param tradingAgentsApiUrl string

@description('Existing Action Group resource ID. Notification addresses remain outside this template.')
param alertActionGroupResourceId string

@description('Key Vault secret name populated after deployment with the Candidate API key.')
param candidateApiKeySecretName string = 'candidate-api-key'

@description('Key Vault secret name populated after deployment with the portal automation API key.')
param portalApiKeySecretName string = 'portal-automation-api-key'

@description('Key Vault secret name populated after deployment with the ACS sender address.')
param emailSenderSecretName string = 'orchestrator-email-sender'

@description('Key Vault secret name populated after deployment with comma-separated recipient addresses.')
param emailRecipientsSecretName string = 'orchestrator-email-recipients'

param exchangeMic string = 'XNYS'

@minValue(1)
@maxValue(1440)
param candidateTimeoutMinutes int = 120

@minValue(1)
@maxValue(1440)
param portalTimeoutMinutes int = 360

@minValue(15)
@maxValue(900)
param pollSeconds int = 60

var suffix = uniqueString(resourceGroup().id, namePrefix)
var compactPrefix = toLower(replace(namePrefix, '-', ''))
var storageName = take('${compactPrefix}${suffix}', 24)
var functionAppName = take('${namePrefix}-${suffix}', 60)
var planName = take('${namePrefix}-fc1-${suffix}', 60)
var workspaceName = take('${namePrefix}-law-${suffix}', 63)
var appInsightsName = take('${namePrefix}-appi-${suffix}', 63)
var vaultName = take('${compactPrefix}kv${suffix}', 24)
var communicationName = take('${namePrefix}-acs-${suffix}', 63)
var emailServiceName = take('${namePrefix}-email-${suffix}', 63)
var schedulerName = take('${namePrefix}-dts-${suffix}', 64)
var taskHubName = 'CandidateDailyOrchestrator'
var deploymentContainerName = 'function-releases'
var keyVaultReferencePrefix = '@Microsoft.KeyVault(VaultName=${vaultName};SecretName='
var tags = {
  workload: 'sp500-candidate-orchestrator'
  component: 'durable-functions'
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  tags: tags
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: deploymentContainerName
  properties: {
    publicAccess: 'None'
    immutableStorageWithVersioning: {
      enabled: false
    }
  }
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: true
    IngestionMode: 'LogAnalytics'
    RetentionInDays: 30
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: vaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
    sku: {
      family: 'A'
      name: 'standard'
    }
  }
}

resource emailService 'Microsoft.Communication/emailServices@2023-03-31' = {
  name: emailServiceName
  location: 'global'
  tags: tags
  properties: {
    dataLocation: 'United States'
  }
}

resource managedDomain 'Microsoft.Communication/emailServices/domains@2023-03-31' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource communicationService 'Microsoft.Communication/communicationServices@2023-03-31' = {
  name: communicationName
  location: 'global'
  tags: tags
  properties: {
    dataLocation: 'United States'
    linkedDomains: [
      managedDomain.id
    ]
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  kind: 'linux'
  tags: tags
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource durableTaskScheduler 'Microsoft.DurableTask/schedulers@2025-11-01' = {
  name: schedulerName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'Consumption'
    }
    ipAllowlist: [
      '0.0.0.0/0'
    ]
  }
}

resource durableTaskHub 'Microsoft.DurableTask/schedulers/taskHubs@2025-11-01' = {
  parent: durableTaskScheduler
  name: taskHubName
  properties: {}
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentContainerName}'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 10
        instanceMemoryMB: 2048
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      ftpsState: 'Disabled'
      http20Enabled: true
      appSettings: [
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storage.name
        }
        {
          name: 'AzureWebJobsStorage__credential'
          value: 'managedidentity'
        }
        {
          name: 'DURABLE_TASK_SCHEDULER_CONNECTION_STRING'
          value: 'Endpoint=${durableTaskScheduler.properties.endpoint};TaskHub=${durableTaskHub.name};Authentication=ManagedIdentity'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING'
          value: 'Authorization=AAD'
        }
        {
          name: 'CANDIDATE_API_URL'
          value: candidateApiUrl
        }
        {
          name: 'CANDIDATE_API_KEY'
          value: '${keyVaultReferencePrefix}${candidateApiKeySecretName})'
        }
        {
          name: 'CANDIDATE_RESOURCE_ID'
          value: candidateResourceId
        }
        {
          name: 'PORTAL_API_URL'
          value: portalApiUrl
        }
        {
          name: 'PORTAL_AUTOMATION_API_KEY'
          value: '${keyVaultReferencePrefix}${portalApiKeySecretName})'
        }
        {
          name: 'PORTAL_RESOURCE_ID'
          value: portalResourceId
        }
        {
          name: 'TRADINGAGENTS_API_URL'
          value: tradingAgentsApiUrl
        }
        {
          name: 'ACS_EMAIL_ENDPOINT'
          value: 'https://${communicationService.name}.communication.azure.com'
        }
        {
          name: 'ORCHESTRATOR_EMAIL_SENDER'
          value: '${keyVaultReferencePrefix}${emailSenderSecretName})'
        }
        {
          name: 'ORCHESTRATOR_EMAIL_RECIPIENTS'
          value: '${keyVaultReferencePrefix}${emailRecipientsSecretName})'
        }
        {
          name: 'ORCHESTRATOR_EXCHANGE_MIC'
          value: exchangeMic
        }
        {
          name: 'ORCHESTRATOR_CANDIDATE_TIMEOUT_MINUTES'
          value: string(candidateTimeoutMinutes)
        }
        {
          name: 'ORCHESTRATOR_PORTAL_TIMEOUT_MINUTES'
          value: string(portalTimeoutMinutes)
        }
        {
          name: 'ORCHESTRATOR_POLL_SECONDS'
          value: string(pollSeconds)
        }
      ]
    }
  }
}

var storageBlobDataOwnerRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
)
var storageQueueDataContributorRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
)
var storageTableDataContributorRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
)
var keyVaultSecretsUserRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)
var monitoringMetricsPublisherRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '3913510d-42f4-4e42-8a64-420c390055eb'
)
var communicationEmailSenderRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '3a69bfc6-0483-44e7-9176-0054a05ed4d0'
)
var durableTaskDataContributorRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '0ad04412-c4d5-4796-b79c-f76d14c8d402'
)

resource storageBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, storageBlobDataOwnerRole)
  scope: storage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataOwnerRole
  }
}

resource storageQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, storageQueueDataContributorRole)
  scope: storage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageQueueDataContributorRole
  }
}

resource storageTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, storageTableDataContributorRole)
  scope: storage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageTableDataContributorRole
  }
}

resource vaultSecretsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, functionApp.id, keyVaultSecretsUserRole)
  scope: vault
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: keyVaultSecretsUserRole
  }
}

resource appInsightsPublisherRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appInsights.id, functionApp.id, monitoringMetricsPublisherRole)
  scope: appInsights
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: monitoringMetricsPublisherRole
  }
}

resource emailSenderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(communicationService.id, functionApp.id, communicationEmailSenderRole)
  scope: communicationService
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: communicationEmailSenderRole
  }
}

resource durableTaskDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(durableTaskScheduler.id, functionApp.id, durableTaskDataContributorRole)
  scope: durableTaskScheduler
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: durableTaskDataContributorRole
  }
}

resource exceptionAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${functionAppName}-exceptions'
  location: 'global'
  tags: tags
  properties: {
    description: 'Durable orchestrator exceptions were recorded.'
    severity: 1
    enabled: true
    scopes: [
      appInsights.id
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    autoMitigate: true
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'ExceptionCount'
          metricNamespace: 'microsoft.insights/components'
          metricName: 'exceptions/count'
          operator: 'GreaterThan'
          threshold: 0
          timeAggregation: 'Count'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: alertActionGroupResourceId
      }
    ]
  }
}

resource failedRequestAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${functionAppName}-failed-requests'
  location: 'global'
  tags: tags
  properties: {
    description: 'Durable orchestrator failed requests were recorded.'
    severity: 2
    enabled: true
    scopes: [
      appInsights.id
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    autoMitigate: true
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'FailedRequestCount'
          metricNamespace: 'microsoft.insights/components'
          metricName: 'requests/failed'
          operator: 'GreaterThan'
          threshold: 0
          timeAggregation: 'Count'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: alertActionGroupResourceId
      }
    ]
  }
}

output functionAppName string = functionApp.name
output functionAppPrincipalId string = functionApp.identity.principalId
output functionAppEndpoint string = 'https://${functionApp.properties.defaultHostName}'
output deploymentContainerUri string = '${storage.properties.primaryEndpoints.blob}${deploymentContainerName}'
output keyVaultName string = vault.name
output communicationServiceName string = communicationService.name
output managedDomainResourceId string = managedDomain.id
output durableTaskSchedulerEndpoint string = durableTaskScheduler.properties.endpoint
output durableTaskHubName string = durableTaskHub.name
