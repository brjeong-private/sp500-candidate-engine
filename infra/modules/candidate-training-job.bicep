param location string
param jobName string
param environmentId string
param trainingIdentityId string
param trainingIdentityClientId string
param azureSubscriptionId string
param azureTenantId string
param registryLoginServer string
param image string
param storageBlobEndpoint string
param storageContainerName string
param postgresHost string
param postgresDatabase string = 'candidate_engine'
param postgresUser string
param applicationInsightsConnectionString string

resource trainingJob 'Microsoft.App/jobs@2024-03-01' = {
  name: jobName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${trainingIdentityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      registries: [
        {
          server: registryLoginServer
          identity: trainingIdentityId
        }
      ]
      replicaRetryLimit: 1
      replicaTimeout: 14400
      triggerType: 'Manual'
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
    }
    template: {
      containers: [
        {
          name: 'candidate-training'
          image: image
          resources: {
            cpu: json('2.0')
            memory: '4Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: trainingIdentityClientId
            }
            {
              name: 'AZURE_SUBSCRIPTION_ID'
              value: azureSubscriptionId
            }
            {
              name: 'AZURE_TENANT_ID'
              value: azureTenantId
            }
            {
              name: 'CANDIDATE_ARTIFACT_BLOB_ENDPOINT'
              value: storageBlobEndpoint
            }
            {
              name: 'CANDIDATE_ARTIFACT_CONTAINER'
              value: storageContainerName
            }
            {
              name: 'PGHOST'
              value: postgresHost
            }
            {
              name: 'PGPORT'
              value: '5432'
            }
            {
              name: 'PGDATABASE'
              value: postgresDatabase
            }
            {
              name: 'PGUSER'
              value: postgresUser
            }
            {
              name: 'PGSSLMODE'
              value: 'require'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: applicationInsightsConnectionString
            }
          ]
        }
      ]
    }
    workloadProfileName: 'Consumption'
  }
}

output jobId string = trainingJob.id
output jobName string = trainingJob.name
