// infra/main.bicep — Azure Container App + Event Grid subscription
// for ITL Subscription Vending service.

@description('Deployment location')
param location string = resourceGroup().location

@description('Base name used to derive all resource names')
param baseName string = 'itl-subvending'

@description('Container image to deploy (e.g. myacr.azurecr.io/itl-subscription-vending:latest)')
param containerImage string

@description('Azure tenant ID passed to the service as an environment variable')
param azureTenantId string

@description('Root management group name')
param rootManagementGroup string = 'ITL'

@description('Event Grid SAS key for webhook authentication')
@secure()
param eventGridSasKey string = ''

@description('Enable mock mode (POST /webhook/test endpoint)')
param mockMode bool = false

// ── Log Analytics workspace ───────────────────────────────────────────────────
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${baseName}-law'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ── Container Apps environment ────────────────────────────────────────────────
resource containerAppsEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: '${baseName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ── Container App ─────────────────────────────────────────────────────────────
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: baseName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
      }
      secrets: [
        {
          name: 'event-grid-sas-key'
          value: eventGridSasKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'subscription-vending'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'VENDING_AZURE_TENANT_ID'
              value: azureTenantId
            }
            {
              name: 'VENDING_ROOT_MANAGEMENT_GROUP'
              value: rootManagementGroup
            }
            {
              name: 'VENDING_MOCK_MODE'
              value: string(mockMode)
            }
            {
              name: 'VENDING_EVENT_GRID_SAS_KEY'
              secretRef: 'event-grid-sas-key'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

// ── Event Grid System Topic ───────────────────────────────────────────────────
resource eventGridTopic 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: '${baseName}-topic'
  location: 'global'
  properties: {
    source: subscription().id
    topicType: 'Microsoft.Resources.Subscriptions'
  }
}

// ── Event Grid Subscription ───────────────────────────────────────────────────
resource eventGridSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2022-06-15' = {
  parent: eventGridTopic
  name: '${baseName}-sub'
  properties: {
    destination: {
      endpointType: 'WebHook'
      properties: {
        endpointUrl: 'https://${containerApp.properties.configuration.ingress.fqdn}/webhook'
      }
    }
    filter: {
      includedEventTypes: [
        'Microsoft.Resources.SubscriptionCreationStarted'
      ]
    }
    eventDeliverySchema: 'EventGridSchema'
    retryPolicy: {
      maxDeliveryAttempts: 30
      eventTimeToLiveInMinutes: 1440
    }
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────
output webhookUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}/webhook'
output containerAppName string = containerApp.name
output principalId string = containerApp.identity.principalId
