import { expect, test } from '@playwright/test'
test('login and traced mock chat', async ({ page }) => {
  await page.route('**/api/me', route => route.fulfill({ json: { id: 1, role: 'analyst', name: 'Alice' } }))
  await page.route('**/api/dashboard', route => route.fulfill({ json: { kpi: { source: 'data.batches', data: { yield_pct: 96.67 } }, issues: { source: 'data.quality_issues', data: { items: [{}] } }, sales: { source: 'data.sales_orders', data: { revenue: 4500 } } } }))
  await page.route('**/api/chat', route => route.fulfill({ json: { mode: 'mock', answer: 'Mock Mode：P-100 庫存 25', trace: [{ tool: 'inventory', input: { sku: 'P-100' }, source: 'erp.products', output: { inventory: 25 } }] } }))
  await page.goto('/')
  await page.getByLabel('Demo bearer token').fill('example-token')
  await page.getByText('開啟工作台').click()
  await expect(page.getByText('96.67%')).toBeVisible()
  await page.getByLabel('提問').fill('查詢 P-100 庫存')
  await page.getByLabel('送出').click()
  await expect(page.getByText('MOCK MODE · 非真實 LLM')).toBeVisible()
  await expect(page.getByText('工具 1: inventory · erp.products')).toBeVisible()
})
