@description('Azure region')
param location string = resourceGroup().location

@description('Prefix for all resources')
@minLength(3)
param namePrefix string = 'itl-vending'

@description('Root management group name')
param rootManagementGroup string = 'ITL'

@description('SAS key for Event Grid delivery')
@secure()
param eventGridSasKey string

@description('Keycloak URL')
param keycloakUrl string

// Storage Account for Function App
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: '${replace(namePrefix, '-', '')}sa'
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
}

// App Service Plan (Consumption)
resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${namePrefix}-plan'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

// Function App
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: '${namePrefix}-func'
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.12'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'VENDING_ROOT_MANAGEMENT_GROUP'
          value: rootManagementGroup
        }
        {
          name: 'VENDING_KEYCLOAK_URL'
          value: keycloakUrl
        }
        {
          name: 'VENDING_EVENT_GRID_SAS_KEY'
          value: eventGridSasKey
        }
      ]
    }
  }
}

// Event Grid System Topic at subscription level
resource eventGridTopic 'Microsoft.EventGrid/systemTopics@2023-12-15-preview' = {
  name: '${namePrefix}-eg-topic'
  location: 'global'
  properties: {
    source: subscription().id
    topicType: 'Microsoft.Resources.Subscriptions'
  }
}

// Event Grid Subscription → Function App
resource eventGridSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2023-12-15-preview' = {
  parent: eventGridTopic
  name: '${namePrefix}-subscription'
  properties: {
    destination: {
      endpointType: 'WebHook'
      properties: {
        endpointUrl: 'https://${functionApp.properties.defaultHostName}/webhook/'
        deliveryAttributeMappings: [
          {
            name: 'aeg-sas-key'
            type: 'Static'
            properties: {
              value: eventGridSasKey
              isSecret: true
            }
          }
        ]
      }
    }
    filter: {
      includedEventTypes: [
        'Microsoft.Resources.ResourceActionSuccess'
      ]
      advancedFilters: [
        {
          operatorType: 'StringContains'
          key: 'data.operationName'
          values: [
            'Microsoft.Subscription/aliases/write'
          ]
        }
      ]
    }
  }
}

// RBAC: Owner role for Function App Managed Identity at subscription scope
module roleAssignment './modules/subscriptionOwnerRoleAssignment.bicep' = {
  name: '${namePrefix}-owner-assignment'
  scope: subscription()
  params: {
    functionAppId: functionApp.id
    principalId: functionApp.identity.principalId
  }
}

// Outputs
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output webhookEndpoint string = 'https://${functionApp.properties.defaultHostName}/webhook/'
output managedIdentityPrincipalId string = functionApp.identity.principalId
