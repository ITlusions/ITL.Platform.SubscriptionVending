targetScope = 'managementGroup'

@description('Principal ID of the Function App managed identity.')
param principalId string

@description('Name prefix used to make role definition name unique per MG.')
param namePrefix string = 'itl-vending'

// Custom role — exact permissions the workflow needs, nothing more
var customRoleId = guid(managementGroup().id, namePrefix, 'subscription-vending-operator')

resource vendingRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: customRoleId
  properties: {
    roleName: '${namePrefix} Subscription Vending Operator'
    description: 'Grants the Subscription Vending service the minimum permissions required to onboard new subscriptions: MG placement, RBAC assignments, policy assignments, and budget creation.'
    type: 'CustomRole'
    assignableScopes: [
      managementGroup().id
    ]
    permissions: [
      {
        actions: [
          // Step 0 — read subscription tags
          'Microsoft.Resources/subscriptions/read'
          'Microsoft.Resources/subscriptions/tagNames/read'
          'Microsoft.Resources/subscriptions/tagNames/tagValues/read'

          // Step 1 — move subscription into management group
          'Microsoft.Management/managementGroups/subscriptions/write'
          'Microsoft.Management/managementGroups/subscriptions/delete'
          'Microsoft.Management/managementGroups/read'

          // Step 3 — RBAC role assignments on new subscriptions
          'Microsoft.Authorization/roleAssignments/write'
          'Microsoft.Authorization/roleAssignments/read'
          'Microsoft.Authorization/roleAssignments/delete'

          // Step 4 — policy assignments on new subscriptions
          'Microsoft.Authorization/policyAssignments/write'
          'Microsoft.Authorization/policyAssignments/read'
          'Microsoft.Authorization/policyAssignments/delete'

          // Step 5 — cost budget alerts on new subscriptions
          'Microsoft.Consumption/budgets/write'
          'Microsoft.Consumption/budgets/read'
          'Microsoft.Consumption/budgets/delete'
        ]
        notActions: []
      }
    ]
  }
}

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managementGroup().id, principalId, vendingRole.id)
  properties: {
    roleDefinitionId: vendingRole.id
    principalId: principalId
    principalType: 'ServicePrincipal'
    description: 'ITL Subscription Vending — Function App Managed Identity'
  }
}

output roleDefinitionId string = vendingRole.id
output roleAssignmentId string = roleAssignment.id
