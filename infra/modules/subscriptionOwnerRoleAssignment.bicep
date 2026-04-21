targetScope = 'subscription'

@description('Resource ID of the Function App.')
param functionAppId string

@description('Principal ID of the Function App managed identity.')
param principalId string

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, functionAppId, 'Owner')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'
    )
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
