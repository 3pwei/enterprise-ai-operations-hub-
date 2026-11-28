import { expect, test } from '@playwright/test'
test.beforeEach(async ({ page }) => {
  await page.route('**/api/products', route => route.fulfill({ json: [{ sku: 'P-300', name: 'Demo', inventory: 4, reorder_point: 20, revision: 0 }] }))
  await page.route('**/api/rules', route => route.fulfill({ json: { active: { id: 1, formula: 'standard', safety_stock: 0, expression: 'max(0, reorder_point + open_sales - inventory - inbound)', author_id: 2 } } }))
  await page.route('**/api/catalog/changes', route => route.fulfill({ json: [] }))
})
test('login and traced mock chat', async ({ page }) => {
  await page.route('**/api/me', route => route.fulfill({ json: { id: 1, role: 'analyst', name: 'Alice' } }))
  await page.route('**/api/dashboard', route => route.fulfill({ json: { kpi: { source: 'data.batches', data: { yield_pct: 96.67 } }, issues: { source: 'data.quality_issues', data: { items: [{}] } }, sales: { source: 'data.sales_orders', data: { revenue: 4500 } } } }))
  await page.route('**/api/chat', route => route.fulfill({ json: { mode: 'mock', answer: 'Mock Mode：P-100 庫存 25', trace: [{ tool: 'inventory', input: { sku: 'P-100' }, source: 'erp.products', output: { inventory: 25 } }] } }))
  await page.route('**/api/workflows', route => route.fulfill({ json: [] }))
  await page.goto('/')
  await page.getByLabel('Demo bearer token').fill('example-token')
  await page.getByText('開啟工作台').click()
  await expect(page.getByText('96.67%')).toBeVisible()
  await page.getByLabel('提問').fill('查詢 P-100 庫存')
  await page.getByLabel('送出').click()
  await expect(page.getByText('MOCK MODE · 非真實 LLM')).toBeVisible()
  await expect(page.getByText('工具 1: inventory · erp.products')).toBeVisible()
})

test('procurement draft requires manager confirmation and shows EIP status', async ({ page }) => {
  let flow: Record<string, unknown> | null = null
  let submits = 0
  await page.route('**/api/me', route => route.fulfill({ json: { id: 2, role: 'manager', name: 'Ming' } }))
  await page.route('**/api/dashboard', route => route.fulfill({ json: { kpi: { source: 'data.batches', data: { yield_pct: 96.67 } }, issues: { source: 'data.quality_issues', data: { items: [] } }, sales: { source: 'data.sales_orders', data: { revenue: 4500 } } } }))
  await page.route('**/api/workflows', route => {
    if (route.request().method() === 'POST') {
      flow = { id: 'demo-task', owner_id: 2, sku: 'P-300', status: 'awaiting_confirmation', inventory: 4, reorder_point: 20, open_sales: 0, inbound: 0, quantity: 16, error: null, purchase_id: null, approval_id: null, events: [{ id: 1, agent: 'data_agent', step: 'inventory', outcome: 'ok', detail: { source: 'erp.products' } }] }
      return route.fulfill({ json: flow })
    }
    return route.fulfill({ json: flow ? [flow] : [] })
  })
  await page.route('**/api/workflows/demo-task/submit', route => {
    submits += 1
    flow = { ...flow, status: 'submitted', purchase_id: 3, approval_id: 2 }
    return route.fulfill({ json: flow })
  })
  await page.route('**/api/workflows/demo-task/approval', route => route.fulfill({ json: { source: 'eip.approvals', data: { status: 'pending' } } }))
  await page.goto('/')
  await page.getByLabel('Demo bearer token').fill('demo-manager-token')
  await page.getByRole('button', { name: '開啟工作台' }).click()
  await page.getByLabel('採購需求').fill('請評估採購 P-300')
  await page.getByRole('button', { name: '建立採購草稿' }).click()
  await expect(page.getByText('P-300 · awaiting_confirmation')).toBeVisible()
  await expect(page.getByText(/採購缺口：16/)).toBeVisible()
  await page.getByText('Agent / MCP 執行歷程（1）').click()
  await expect(page.getByText('data_agent · inventory · ok')).toBeVisible()
  expect(submits).toBe(0)
  await page.getByRole('button', { name: '人工確認並提交' }).click()
  expect(submits).toBe(1)
  await expect(page.getByText('採購單 #3')).toBeVisible()
  await page.getByRole('button', { name: '查詢 EIP 簽核' }).click()
  await expect(page.getByText(/EIP 簽核 #2 · pending/)).toBeVisible()
})

test('LLM procurement shows authorized draft, citations and sanitized execution', async ({ page }) => {
  await page.route('**/api/demo/config', route => route.fulfill({ json: { public_demo_mode: false, agent_mode: 'llm' } }))
  await page.route('**/api/me', route => route.fulfill({ json: { id: 1, role: 'analyst' } }))
  const metric = { source: 'data.batches', data: {} }
  await page.route('**/api/dashboard', route => route.fulfill({ json: { kpi: metric, issues: metric, sales: metric } }))
  let created = false
  const draft = { id: 'agent-draft', sku: 'P-300', status: 'awaiting_confirmation', quantity: 16,
    inventory: 4, reorder_point: 20, open_sales: 0, inbound: 0, rule_id: 1, events: [] }
  await page.route('**/api/workflows', route => route.fulfill({ json: created ? [draft] : [] }))
  await page.route('**/api/chat', route => {
    const body = route.request().postDataJSON()
    expect(body.message).toContain('P-300')
    expect(body.draft_sku).toBe('P-300')
    created = true
    return route.fulfill({ json: {
      agent: 'operations', mode: 'llm', answer: 'SOP 要求查核庫存與未交採購量。', draft,
      citations: [{ document_id: 'purchase-sop', title: '採購 SOP', version: 1, paragraph: '1',
        section: '請購前置檢查', excerpt: '查核庫存與未交採購量。', updated_at: '2026-11-28' }],
      execution: { id: 'agent-run', status: 'completed', elapsed_ms: 310, error: null,
        tokens: { input: 100, output: 20, total: 120 },
        trace: [{ tool: 'knowledge_search', source: 'knowledge.documents', outcome: 'ok', elapsed_ms: 80, matches: 1 }] },
    } })
  })
  await page.goto('/')
  await page.getByLabel('Demo bearer token').fill('demo-analyst-token')
  await page.getByRole('button', { name: '開啟工作台' }).click()
  await page.getByRole('button', { name: '填入 P-300 採購範例' }).click()
  const authorization = page.getByLabel('允許建立此 SKU 的採購草稿')
  await expect(authorization).not.toBeChecked()
  await authorization.check()
  await page.getByLabel('送出').click()
  await expect(page.getByText('LLM Agent · completed')).toBeVisible()
  await expect(page.getByText('採購 SOP · v1', { exact: false })).toBeVisible()
  await page.getByText('Agent 執行追蹤 · 310 ms').click()
  await expect(page.getByText('Token 共 120', { exact: false })).toBeVisible()
  await expect(page.getByText('knowledge_search · knowledge.documents · ok', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: '前往 Workflow Console' }).click()
  await expect(page.getByRole('heading', { name: 'P-300 · awaiting_confirmation' })).toBeVisible()
  await expect(page.getByRole('button', { name: '人工確認並提交' })).toHaveCount(0)
})
