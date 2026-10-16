param location string
param storageAccountName string
param containerName string = 'candidate-training'
param containerRegistryName string
param trainingPrincipalId string
param readerPrincipalId string

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_ZRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: {
      enabled: true
      days: 30
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 30
    }
  }
}

resource artifactsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: containerRegistryName
  location: location
  sku: {
    name: 'Premium'
  }
  properties: {
    adminUserEnabled: false
    dataEndpointEnabled: false
    networkRuleBypassOptions: 'None'
    publicNetworkAccess: 'Disabled'
    zoneRedundancy: 'Enabled'
    policies: {
      retentionPolicy: {
        days: 30
        status: 'enabled'
      }
      trustPolicy: {
        type: 'Notary'
        status: 'disabled'
      }
    }
  }
}

var blobDataContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)
var blobDataReaderRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
)
var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource trainingBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, trainingPrincipalId, blobDataContributorRoleId)
  scope: storage
  properties: {
    principalId: trainingPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobDataContributorRoleId
  }
}

resource readerBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, readerPrincipalId, blobDataReaderRoleId)
  scope: storage
  properties: {
    principalId: readerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobDataReaderRoleId
  }
}

resource trainingAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, trainingPrincipalId, acrPullRoleId)
  scope: registry
  properties: {
    principalId: trainingPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

output storageAccountId string = storage.id
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output containerName string = artifactsContainer.name
output containerRegistryId string = registry.id
output containerRegistryLoginServer string = registry.properties.loginServer
