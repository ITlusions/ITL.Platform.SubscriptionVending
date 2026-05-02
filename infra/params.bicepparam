using './main.bicep'

param location = 'westeurope'
param namePrefix = 'itl-vending'
param rootManagementGroup = 'ITL'
param keycloakUrl = 'https://keycloak.itlusions.com'
// eventGridSasKey should be supplied via --parameters or Key Vault reference
