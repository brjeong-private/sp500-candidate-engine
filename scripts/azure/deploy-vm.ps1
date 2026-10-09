param(
    [Parameter(Mandatory = $true)]
    [string]$PasswordFile,
    [string]$SubscriptionId = "8d0218f4-f340-446d-b76a-3ff419b03e77",
    [string]$ResourceGroup = "rg-ai-project",
    [string]$Location = "westus3",
    [string]$VnetName = "vnet-sp500-backfill-wus3",
    [string]$VnetPrefix = "10.83.0.0/16",
    [string]$SubnetName = "snet-sp500-backfill",
    [string]$SubnetPrefix = "10.83.5.0/24",
    [string]$NsgName = "nsg-sp500-backfill-wus3",
    [string]$PublicIpName = "pip-sp500-backfill-wus3",
    [string]$NicName = "nic-sp500-backfill-wus3",
    [string]$VmName = "vm-sp500-backfill-wus3",
    [string]$AdminUsername = "azurebackfill",
    [string]$VmSize = "Standard_D4as_v5",
    [string]$OutputFile = ".azure/vm-deployment-output.tmp.json"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PasswordFile -PathType Leaf)) {
    throw "Password file not found: $PasswordFile"
}

$password = (Get-Content -LiteralPath $PasswordFile -Raw).Trim()
if ($password.Length -lt 16) {
    throw "VM password must be at least 16 characters"
}

az account set --subscription $SubscriptionId

if (-not (az network nsg show -g $ResourceGroup -n $NsgName 2>$null)) {
    az network nsg create `
        --resource-group $ResourceGroup `
        --name $NsgName `
        --location $Location `
        --tags workload=sp500-backfill environment=development | Out-Null
}

if (-not (az network nsg rule show -g $ResourceGroup --nsg-name $NsgName -n AllowSshInternet 2>$null)) {
    az network nsg rule create `
        --resource-group $ResourceGroup `
        --nsg-name $NsgName `
        --name AllowSshInternet `
        --priority 1000 `
        --access Allow `
        --protocol Tcp `
        --direction Inbound `
        --source-address-prefixes Internet `
        --source-port-ranges "*" `
        --destination-address-prefixes "*" `
        --destination-port-ranges 22 | Out-Null
}

if (-not (az network vnet show -g $ResourceGroup -n $VnetName 2>$null)) {
    az network vnet create `
        --resource-group $ResourceGroup `
        --name $VnetName `
        --location $Location `
        --address-prefixes $VnetPrefix `
        --tags workload=sp500-backfill environment=development | Out-Null
}

if (-not (az network vnet subnet show -g $ResourceGroup --vnet-name $VnetName -n $SubnetName 2>$null)) {
    az network vnet subnet create `
        --resource-group $ResourceGroup `
        --vnet-name $VnetName `
        --name $SubnetName `
        --address-prefixes $SubnetPrefix `
        --network-security-group $NsgName | Out-Null
}

if (-not (az network public-ip show -g $ResourceGroup -n $PublicIpName 2>$null)) {
    az network public-ip create `
        --resource-group $ResourceGroup `
        --name $PublicIpName `
        --location $Location `
        --sku Standard `
        --allocation-method Static `
        --version IPv4 `
        --tags workload=sp500-backfill environment=development | Out-Null
}

$subnetId = az network vnet subnet show `
    --resource-group $ResourceGroup `
    --vnet-name $VnetName `
    --name $SubnetName `
    --query id -o tsv

if (-not (az network nic show -g $ResourceGroup -n $NicName 2>$null)) {
    az network nic create `
        --resource-group $ResourceGroup `
        --name $NicName `
        --location $Location `
        --subnet $subnetId `
        --network-security-group $NsgName `
        --public-ip-address $PublicIpName `
        --tags workload=sp500-backfill environment=development | Out-Null
}

if (-not (az vm show -g $ResourceGroup -n $VmName 2>$null)) {
    az vm create `
        --resource-group $ResourceGroup `
        --name $VmName `
        --location $Location `
        --nics $NicName `
        --image Ubuntu2404 `
        --size $VmSize `
        --admin-username $AdminUsername `
        --admin-password $password `
        --authentication-type password `
        --assign-identity `
        --os-disk-size-gb 64 `
        --storage-sku StandardSSD_LRS `
        --tags workload=sp500-backfill environment=development autoShutdown=disabled | Out-Null
}

$vm = az vm show `
    --resource-group $ResourceGroup `
    --name $VmName `
    --show-details `
    --query "{id:id,principalId:identity.principalId,publicIps:publicIps,privateIps:privateIps,powerState:powerState,location:location}" `
    --output json | ConvertFrom-Json

$schedules = az resource list `
    --resource-group $ResourceGroup `
    --resource-type Microsoft.DevTestLab/schedules `
    --query "[?contains(name, '$VmName')].{name:name,id:id}" `
    --output json | ConvertFrom-Json

if ($schedules.Count -gt 0) {
    throw "Unexpected auto-shutdown schedule detected for $VmName"
}

$output = @{
    vmName = $VmName
    adminUsername = $AdminUsername
    id = $vm.id
    principalId = $vm.principalId
    publicIp = $vm.publicIps
    privateIp = $vm.privateIps
    powerState = $vm.powerState
    location = $vm.location
    autoShutdownSchedules = 0
}

$output | ConvertTo-Json | Set-Content -LiteralPath $OutputFile -Encoding utf8
$output | ConvertTo-Json
