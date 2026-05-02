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

var webhookPath = '/webhook/'
var sanitizedPrefix = replace(toLower(namePrefix), '-', '')
var storageAccountPrefix = length(sanitizedPrefix) >= 1 ? sanitizedPrefix : 'sv'
var storageAccountName = take('${storageAccountPrefix}sa', 24)
var keyVaultName = take('${sanitizedPrefix}-kv', 24)

// Built-in role definition IDs
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
var eventGridDataSenderRoleId = 'd5a91429-5739-47e2-a06b-3470a27159e7'

// Storage Account for Function App
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
}

// Key Vault — stores secrets; uses RBAC authorization (no access policies)
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: tenant().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
  }
}

// Key Vault secret — Event Grid SAS key
resource eventGridSasKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'event-grid-sas-key'
  properties: {
    value: eventGridSasKey
  }
}

// Event Grid Custom Topic — outbound subscription-vended notifications
resource notificationTopic 'Microsoft.EventGrid/topics@2023-12-15-preview' = {
  name: '${namePrefix}-notifications'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    inputSchema: 'EventGridSchema'
    publicNetworkAccess: 'Enabled'
  }
}

// RBAC: Function App MI → EventGrid Data Sender on the notification topic
resource egDataSenderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(notificationTopic.id, functionApp.id, eventGridDataSenderRoleId)
  scope: notificationTopic
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventGridDataSenderRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
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
          // Managed-identity storage connection — no account key stored here
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccount.name
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
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
          // Key Vault reference — secret value never stored in App Settings
          name: 'VENDING_EVENT_GRID_SAS_KEY'
          value: '@Microsoft.KeyVault(SecretUri=https://${keyVault.name}.vault.azure.net/secrets/${eventGridSasKeySecret.name}/)'
        }
        {
          // Outbound notification topic endpoint — resolved via Managed Identity at runtime
          name: 'VENDING_EVENT_GRID_TOPIC_ENDPOINT'
          value: notificationTopic.properties.endpoint
        }
      ]
    }
  }
}

// RBAC: Function App MI → Key Vault Secrets User (allows KV reference resolution)
resource kvSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionApp.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// RBAC: Function App MI → Storage (managed-identity AzureWebJobsStorage)
resource storageBlobOwnerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, storageBlobDataOwnerRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageQueueContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, storageQueueDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageTableContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, storageTableDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributorRoleId)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
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
        endpointUrl: 'https://${functionApp.properties.defaultHostName}${webhookPath}'
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
output webhookEndpoint string = 'https://${functionApp.properties.defaultHostName}${webhookPath}'
output managedIdentityPrincipalId string = functionApp.identity.principalId
output keyVaultName string = keyVault.name
output notificationTopicEndpoint string = notificationTopic.properties.endpoint
