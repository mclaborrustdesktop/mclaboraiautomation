// Monthly budget for the MC Labor subscription with alerts at 50 / 75 / 90 / 100 % of the amount (actual spend)
// and at 100 % of the forecast. Deployed at subscription scope:
//   az deployment sub create --location eastus --template-file budget.bicep --parameters amount=200 contactEmails="['owner@mclabor.com']"
targetScope = 'subscription'

@description('Monthly budget in USD')
param amount int = 200
@description('E-mail addresses that receive the alerts')
param contactEmails array
@description('First day of the first month to budget, yyyy-MM-01')
param startDate string = '2026-12-01'
@description('Resource groups the budget applies to (empty = the whole subscription)')
param resourceGroups array = []
@description('Budget name (one per environment)')
param budgetName string = 'mclabor-monthly'

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
      endDate: '2036-12-01'
    }
    filter: empty(resourceGroups) ? null : {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: resourceGroups
      }
    }
    notifications: {
      actual50: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 50, thresholdType: 'Actual', contactEmails: contactEmails }
      actual75: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 75, thresholdType: 'Actual', contactEmails: contactEmails }
      actual90: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 90, thresholdType: 'Actual', contactEmails: contactEmails }
      actual100: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Actual', contactEmails: contactEmails }
      forecast100: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Forecasted', contactEmails: contactEmails }
    }
  }
}
