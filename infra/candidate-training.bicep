targetScope = 'resourceGroup'

param location string = 'koreacentral'
param namePrefix string = 'sp500-candidate'
param storageAccountName string = take(replace('${namePrefix}${uniqueString(resourceGroup().id)}', '-', ''), 24)
param containerRegistryName string = take(replace('${namePrefix}${uniqueString(subscription().id)}', '-', ''), 50)
param artifactContainerName string = 'candidate-training'
param postgresServerResourceId string
param postgresHost string
param postgresDatabase string = 'candidate_engine'
param postgresUser string = '${namePrefix}-training'
param postgresPrivateDnsZoneName string = 'privatelink.postgres.database.azure.com'
param trainingImageRepository string = 'candidate-training'
param trainingImageTag string = 'latest'
param deployTrainingJob bool = false
param orchestratorPrincipalId string = ''

resource trainingIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-training'
  location: location
}

resource readerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-reader'
  location: location
}

module artifacts 'modules/candidate-artifacts.bicep' = {
  name: 'candidate-artifacts'
  params: {
    location: location
    storageAccountName: storageAccountName
    containerName: artifactContainerName
    containerRegistryName: containerRegistryName
    trainingPrincipalId: trainingIdentity.properties.principalId
    readerPrincipalId: readerIdentity.properties.principalId
  }
}

module network 'modules/candidate-network.bicep' = {
  name: 'candidate-network'
  params: {
    location: location
    vnetName: '${namePrefix}-vnet'
    storageAccountId: artifacts.outputs.storageAccountId
    containerRegistryId: artifacts.outputs.containerRegistryId
    postgresServerResourceId: postgresServerResourceId
    postgresPrivateDnsZoneName: postgresPrivateDnsZoneName
  }
}

module observability 'modules/candidate-observability.bicep' = {
  name: 'candidate-observability'
  params: {
    location: location
    workspaceName: '${namePrefix}-logs'
    applicationInsightsName: '${namePrefix}-insights'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-environment'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: observability.outputs.logAnalyticsCustomerId
        sharedKey: observability.outputs.logAnalyticsSharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: network.outputs.infrastructureSubnetId
      internal: true
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

module trainingJob 'modules/candidate-training-job.bicep' = if (deployTrainingJob) {
  name: 'candidate-training-job'
  params: {
    location: location
    jobName: '${namePrefix}-training'
    environmentId: environment.id
    trainingIdentityId: trainingIdentity.id
    trainingIdentityClientId: trainingIdentity.properties.clientId
    azureSubscriptionId: subscription().subscriptionId
    azureTenantId: tenant().tenantId
    registryLoginServer: artifacts.outputs.containerRegistryLoginServer
    image: '${artifacts.outputs.containerRegistryLoginServer}/${trainingImageRepository}:${trainingImageTag}'
    storageBlobEndpoint: artifacts.outputs.storageBlobEndpoint
    storageContainerName: artifacts.outputs.containerName
    postgresHost: postgresHost
    postgresDatabase: postgresDatabase
    postgresUser: postgresUser
    applicationInsightsConnectionString: observability.outputs.applicationInsightsConnectionString
  }
}

var orchestratorJobOperatorRoleName = 'SP500 Candidate Training Job Operator'
resource orchestratorJobOperatorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, orchestratorJobOperatorRoleName)
  properties: {
    roleName: orchestratorJobOperatorRoleName
    description: 'Starts the candidate training job and reads its definition and executions.'
    type: 'CustomRole'
    assignableScopes: [
      resourceGroup().id
    ]
    permissions: [
      {
        actions: [
          'Microsoft.App/jobs/read'
          'Microsoft.App/jobs/start/action'
          'Microsoft.App/jobs/executions/read'
        ]
        notActions: []
        dataActions: []
        notDataActions: []
      }
    ]
  }
}

resource orchestratorJobOperatorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(orchestratorPrincipalId)) {
  name: guid(resourceGroup().id, orchestratorPrincipalId, orchestratorJobOperatorRole.id)
  properties: {
    principalId: orchestratorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: orchestratorJobOperatorRole.id
  }
}

output trainingIdentityId string = trainingIdentity.id
output trainingIdentityClientId string = trainingIdentity.properties.clientId
output readerIdentityId string = readerIdentity.id
output readerIdentityClientId string = readerIdentity.properties.clientId
output backendIntegrationSubnetId string = network.outputs.backendIntegrationSubnetId
output artifactStorageAccountId string = artifacts.outputs.storageAccountId
output artifactContainerName string = artifacts.outputs.containerName
output containerRegistryId string = artifacts.outputs.containerRegistryId
output containerAppsEnvironmentId string = environment.id
output trainingJobId string = deployTrainingJob ? trainingJob!.outputs.jobId : ''
output orchestratorJobOperatorRoleDefinitionId string = orchestratorJobOperatorRole.id
