targetScope = 'subscription'

@description('Resource group scope where the orchestrator may remediate approved resource states.')
param assignableScope string

var roleName = 'SP500 Orchestrator Resource Remediator'
var roleDefinitionGuid = guid(subscription().id, roleName)

resource roleDefinition 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: roleDefinitionGuid
  properties: {
    roleName: roleName
    description: 'Starts approved application and database resources, restores Container Apps and Storage configuration, and temporarily manages resource locks.'
    type: 'CustomRole'
    assignableScopes: [
      assignableScope
    ]
    permissions: [
      {
        actions: [
          'Microsoft.Web/sites/read'
          'Microsoft.Web/sites/start/Action'
          'Microsoft.DBforPostgreSQL/flexibleServers/read'
          'Microsoft.DBforPostgreSQL/flexibleServers/start/action'
          'Microsoft.DBforMySQL/flexibleServers/read'
          'Microsoft.DBforMySQL/flexibleServers/start/action'
          'Microsoft.App/containerApps/read'
          'Microsoft.App/containerApps/write'
          'Microsoft.App/containerApps/start/action'
          'Microsoft.Storage/storageAccounts/read'
          'Microsoft.Storage/storageAccounts/write'
          'Microsoft.Authorization/locks/read'
          'Microsoft.Authorization/locks/write'
          'Microsoft.Authorization/locks/delete'
        ]
        notActions: []
        dataActions: []
        notDataActions: []
      }
    ]
  }
}

output roleDefinitionId string = roleDefinition.id
