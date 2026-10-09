targetScope = 'resourceGroup'

@description('Azure region for the backfill VM.')
param location string = resourceGroup().location

@description('Existing virtual network name.')
param virtualNetworkName string = 'vnet-jongmok-prd'

@description('Subnet name created for the backfill VM.')
param subnetName string = 'sp500-backfill'

@description('Subnet address prefix.')
param subnetAddressPrefix string = '10.82.5.0/24'

@description('Network security group name.')
param networkSecurityGroupName string = 'nsg-sp500-backfill'

@description('Virtual machine name.')
param virtualMachineName string = 'vm-sp500-backfill'

@description('Virtual machine size.')
param virtualMachineSize string = 'Standard_B4ms'

@description('Local administrator username.')
param adminUsername string = 'azurebackfill'

@secure()
@description('Local administrator password. Supply only through an ignored temporary parameter file.')
param adminPassword string

var tags = {
  workload: 'sp500-backfill'
  environment: 'development'
  autoShutdown: 'disabled'
}

module networkSecurityGroup 'br/public:avm/res/network/network-security-group:0.5.0' = {
  name: 'deploy-${networkSecurityGroupName}'
  params: {
    name: networkSecurityGroupName
    location: location
    securityRules: [
      {
        name: 'AllowSshInternet'
        properties: {
          access: 'Allow'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
          direction: 'Inbound'
          priority: 1000
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
        }
      }
    ]
    tags: tags
  }
}

module subnet 'br/public:avm/res/network/virtual-network/subnet:0.2.0' = {
  name: 'deploy-${subnetName}'
  params: {
    name: subnetName
    virtualNetworkName: virtualNetworkName
    addressPrefix: subnetAddressPrefix
    networkSecurityGroupResourceId: networkSecurityGroup.outputs.resourceId
  }
}

module virtualMachine 'br/public:avm/res/compute/virtual-machine:0.22.0' = {
  name: 'deploy-${virtualMachineName}'
  params: {
    availabilityZone: -1
    name: virtualMachineName
    nicConfigurations: [
      {
        deleteOption: 'Delete'
        ipConfigurations: [
          {
            name: 'ipconfig01'
            pipConfiguration: {
              publicIpNameSuffix: '-pip'
              publicIPAllocationMethod: 'Static'
              skuName: 'Standard'
            }
            subnetResourceId: subnet.outputs.resourceId
          }
        ]
        nicSuffix: '-nic'
      }
    ]
    osDisk: {
      caching: 'ReadWrite'
      diskSizeGB: 64
      managedDisk: {
        storageAccountType: 'StandardSSD_LRS'
      }
    }
    osType: 'Linux'
    vmSize: virtualMachineSize
    adminUsername: adminUsername
    adminPassword: adminPassword
    disablePasswordAuthentication: false
    imageReference: {
      offer: 'ubuntu-24_04-lts'
      publisher: 'Canonical'
      sku: 'server'
      version: 'latest'
    }
    location: location
    managedIdentities: {
      systemAssigned: true
    }
    patchMode: 'AutomaticByPlatform'
    rebootSetting: 'IfRequired'
    secureBootEnabled: true
    securityType: 'TrustedLaunch'
    tags: tags
    vTpmEnabled: true
  }
}

output virtualMachineId string = virtualMachine.outputs.resourceId
output principalId string = virtualMachine.outputs.systemAssignedMIPrincipalId!
