using './main.bicep'

param location = 'westeurope'
param baseName = 'itl-subvending'
param containerImage = 'myacr.azurecr.io/itl-subscription-vending:latest'
param azureTenantId = '<your-tenant-id>'
param rootManagementGroup = 'ITL'
param mockMode = false
// eventGridSasKey should be supplied via --parameters or Key Vault reference
