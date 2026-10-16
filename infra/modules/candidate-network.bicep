param location string
param vnetName string
param storageAccountId string
param containerRegistryId string
param postgresServerResourceId string
param postgresPrivateDnsZoneName string = 'privatelink.postgres.database.azure.com'

var blobPrivateDnsZoneName = 'privatelink.blob.${environment().suffixes.storage}'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.40.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'container-apps-infrastructure'
        properties: {
          addressPrefix: '10.40.0.0/23'
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: '10.40.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'backend-appservice'
        properties: {
          addressPrefix: '10.40.3.0/24'
          delegations: [
            {
              name: 'Microsoft.Web.serverFarms'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
        }
      }
    ]
  }
}

resource infrastructureSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: 'container-apps-infrastructure'
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: 'private-endpoints'
}

resource backendSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: 'backend-appservice'
}

resource blobPrivateDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: blobPrivateDnsZoneName
  location: 'global'
}

resource acrPrivateDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.azurecr.io'
  location: 'global'
}

resource postgresPrivateDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: postgresPrivateDnsZoneName
  location: 'global'
}

resource blobDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobPrivateDns
  name: '${vnetName}-blob'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource acrDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: acrPrivateDns
  name: '${vnetName}-acr'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource postgresDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: postgresPrivateDns
  name: '${vnetName}-postgres'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource blobPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${vnetName}-blob-pe'
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          privateLinkServiceId: storageAccountId
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource blobDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: blobPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: blobPrivateDns.id
        }
      }
    ]
  }
}

resource acrPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${vnetName}-acr-pe'
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'registry'
        properties: {
          privateLinkServiceId: containerRegistryId
          groupIds: [
            'registry'
          ]
        }
      }
    ]
  }
}

resource acrDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: acrPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'registry'
        properties: {
          privateDnsZoneId: acrPrivateDns.id
        }
      }
    ]
  }
}

resource postgresPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${vnetName}-postgres-pe'
  location: location
  properties: {
    subnet: {
      id: privateEndpointSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: 'postgresqlServer'
        properties: {
          privateLinkServiceId: postgresServerResourceId
          groupIds: [
            'postgresqlServer'
          ]
        }
      }
    ]
  }
}

resource postgresDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: postgresPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'postgresqlServer'
        properties: {
          privateDnsZoneId: postgresPrivateDns.id
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output infrastructureSubnetId string = infrastructureSubnet.id
output backendIntegrationSubnetId string = backendSubnet.id
