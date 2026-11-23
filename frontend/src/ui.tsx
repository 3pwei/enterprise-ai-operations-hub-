import { useEffect, useState } from 'react'
import { Activity, Bot, Database, Factory, LockKeyhole, Send, ShieldCheck, TrendingUp } from 'lucide-react'

type Result = { source: string; data: Record<string, unknown> }
type Trace = { tool: string; input: Record<string, unknown>; source: string; output: Record<string, unknown> }
type Chat = { mode: 'mock' | 'llm'; answer: string; trace: Trace[] }
type Dashboard = { kpi: Result; issues: Result; sales: Result }
type WorkflowEvent = { id: number; agent: string; step: string; outcome: string; detail: Record<string, unknown> }
type Workflow = { id: string; owner_id: number; sku: string; status: string; inventory: number | null; reorder_point: number | null; open_sales: number | null; inbound: number | null; quantity: number | null; error: string | null; purchase_id: number | null; approval_id: number | null; rule_id: number | null; product_revision: number | null; stale: boolean; events: WorkflowEvent[] }
type Product = { sku: string; name: string; inventory: number; reorder_point: number; revision: number }
type Rule = { id: number; formula: 'standard' | 'safety_stock'; safety_stock: number; expression: string; author_id: number }
type Preview = { sku: string; inventory: number; reorder_point: number; open_sales: number; inbound: number; quantity: number }
type CatalogChange = { id: number; actor_id: number; action: string; target: string; before: Record<string, unknown>; after: Record<string, unknown>; created_at: string }

async function request<T>(path: string, token: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(`HTTP ${response.status}: ${response.status === 401 ? '登入憑證不正確' : body.detail ?? '服務暫時無法回應'}`)
  }
  return response.json() as Promise<T>
}

export default function App() {
  const [token, setToken] = useState('')
  const [ready, setReady] = useState(false)
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [message, setMessage] = useState('')
  const [conversation, setConversation] = useState<{ question: string; result: Chat }[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [role, setRole] = useState('')
  const [workflowMessage, setWorkflowMessage] = useState('')
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [workflowLoading, setWorkflowLoading] = useState(false)
  const [approval, setApproval] = useState<Record<string, string>>({})
  const [products, setProducts] = useState<Product[]>([])
  const [activeRule, setActiveRule] = useState<Rule | null>(null)
  const [selectedSku, setSelectedSku] = useState('P-300')
  const [productName, setProductName] = useState('')
  const [inventory, setInventory] = useState(0)
  const [reorderPoint, setReorderPoint] = useState(0)
  const [orderKind, setOrderKind] = useState<'sale' | 'inbound'>('sale')
  const [orderQuantity, setOrderQuantity] = useState(1)
  const [formula, setFormula] = useState<'standard' | 'safety_stock'>('standard')
  const [safetyStock, setSafetyStock] = useState(0)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [catalogChanges, setCatalogChanges] = useState<CatalogChange[]>([])
  const [publicDemo, setPublicDemo] = useState(false)
  useEffect(() => { fetch('/api/demo/config').then(r => r.json()).then(
    data => setPublicDemo(Boolean(data.public_demo_mode))).catch(() => {}) }, [])

  async function refreshCatalog() {
    const [items, rules, changes] = await Promise.all([
      request<Product[]>('/api/products', token),
      request<{active: Rule}>('/api/rules', token),
      request<CatalogChange[]>('/api/catalog/changes', token),
    ])
    setProducts(items); setActiveRule(rules.active); setCatalogChanges(changes)
    if (!productName) {
      const selected = items.find(item => item.sku === selectedSku)
      if (selected) { setProductName(selected.name); setInventory(selected.inventory); setReorderPoint(selected.reorder_point) }
    }
  }

  async function changeCatalog(operation: () => Promise<unknown>) {
    setWorkflowLoading(true); setError('')
    try { await operation(); setPreview(null); await refreshCatalog(); await refreshWorkflows() }
    catch (err) { setError(String(err)) }
    finally { setWorkflowLoading(false) }
  }

  async function saveProduct() {
    const exists = products.some(p => p.sku === selectedSku)
    await changeCatalog(() => request(exists ? `/api/products/${selectedSku}` : '/api/products', token, {
      method: exists ? 'PUT' : 'POST',
      body: JSON.stringify({ ...(exists ? {} : { sku: selectedSku }), name: productName,
        inventory: Number(inventory), reorder_point: Number(reorderPoint) }),
    }))
  }

  async function saveOrder() {
    await changeCatalog(() => request('/api/orders', token, { method: 'POST',
      body: JSON.stringify({ sku: selectedSku, kind: orderKind, quantity: Number(orderQuantity) }) }))
  }

  async function previewRule() {
    setError(''); setWorkflowLoading(true)
    try { setPreview(await request<Preview>('/api/rules/preview', token, { method: 'POST',
      body: JSON.stringify({ sku: selectedSku, formula, safety_stock: Number(safetyStock) }) })) }
    catch (err) { setPreview(null); setError(String(err)) }
    finally { setWorkflowLoading(false) }
  }

  async function publishRule() {
    if (!activeRule || !preview || preview.sku !== selectedSku) return
    await changeCatalog(() => request('/api/rules', token, { method: 'POST',
      body: JSON.stringify({ formula, safety_stock: Number(safetyStock), expected_rule_id: activeRule.id }) }))
  }

  async function signIn() {
    setError(''); setLoading(true)
    try {
      if (publicDemo) await request('/api/demo/session', '', { method: 'POST' })
      const identity = await request<{role: string}>('/api/me', token)
      setRole(identity.role)
      if (!publicDemo) setDashboard(await request('/api/dashboard', token))
      setWorkflows(await request<Workflow[]>('/api/workflows', token))
      await refreshCatalog()
      setReady(true)
    } catch (err) { setError(String(err)) } finally { setLoading(false) }
  }

  async function switchRole() {
    if (!publicDemo) { setReady(false); setToken(''); setRole(''); setWorkflows([]); setConversation([]); setApproval({}); return }
    setError(''); setWorkflowLoading(true)
    try {
      const nextRole = role === 'analyst' ? 'manager' : 'analyst'
      await request('/api/demo/role', '', { method: 'POST', body: JSON.stringify({ role: nextRole }) })
      setRole(nextRole); await refreshWorkflows(); await refreshCatalog()
    } catch (err) { setError(String(err)) } finally { setWorkflowLoading(false) }
  }

  async function refreshWorkflows() {
    setWorkflows(await request<Workflow[]>('/api/workflows', token))
  }

  async function createWorkflow() {
    if (!workflowMessage.trim() || workflowLoading) return
    setWorkflowLoading(true); setError('')
    try {
      await request<Workflow>('/api/workflows', token, { method: 'POST', body: JSON.stringify({ message: workflowMessage }) })
      setWorkflowMessage(''); await refreshWorkflows()
    } catch (err) { setError(String(err)); await refreshWorkflows() } finally { setWorkflowLoading(false) }
  }

  async function action(id: string, name: 'submit' | 'retry' | 'cancel') {
    if (workflowLoading) return
    setWorkflowLoading(true); setError('')
    try {
      await request(`/api/workflows/${id}/${name}`, token, { method: 'POST' })
      await refreshWorkflows()
    } catch (err) { setError(String(err)); await refreshWorkflows() } finally { setWorkflowLoading(false) }
  }

  async function checkApproval(id: string) {
    setWorkflowLoading(true); setError('')
    try {
      const result = await request<{data: {status: string}}> (`/api/workflows/${id}/approval`, token)
      setApproval(previous => ({ ...previous, [id]: result.data.status }))
      await refreshWorkflows()
    } catch (err) { setError(String(err)) } finally { setWorkflowLoading(false) }
  }

  async function send(question = message) {
    if (!question.trim() || loading) return
    setError(''); setLoading(true); setMessage('')
    try {
      const result = await request<Chat>('/api/chat', token, { method: 'POST', body: JSON.stringify({ message: question }) })
      setConversation(previous => [...previous, { question, result }])
    } catch (err) { setError(String(err)); setMessage(question) } finally { setLoading(false) }
  }

  return <div className="min-h-screen">
    <header className="border-b bg-white"><div className="max-w-6xl mx-auto px-5 py-5 flex items-center gap-3"><div className="p-2 rounded-xl bg-ink text-white"><Factory size={22}/></div><div><h1 className="font-bold text-xl">Enterprise AI Operations Hub</h1><p className="text-xs text-slate-500">製造業營運情報 · ERP / EIP / Data MCP</p></div><span className="ml-auto text-xs rounded-full bg-teal-50 text-teal-800 px-3 py-1">模擬資料 Demo</span></div></header>
    <main className="max-w-6xl mx-auto px-5 py-8">
      {!ready ? <section className="max-w-md mx-auto mt-12 bg-white rounded-2xl border p-7 shadow-sm"><LockKeyhole className="text-accent mb-4"/><h2 className="text-xl font-semibold mb-2">{publicDemo ? '開始獨立模擬工作階段' : '輸入 Demo 憑證'}</h2><p className="text-sm text-slate-500 mb-5">{publicDemo ? '每位訪客使用隔離的模擬資料；角色切換僅為展示，沒有真實採購權限。工作階段 24 小時後到期。' : '請從本機 .env 取得 analyst 或 manager token；不會儲存在瀏覽器中。'}</p>{!publicDemo && <input aria-label="Demo bearer token" type="password" value={token} onChange={e => setToken(e.target.value)} onKeyDown={e => e.key === 'Enter' && signIn()} placeholder="Demo bearer token" className="border rounded-lg p-3 w-full mb-3"/>}<button onClick={signIn} disabled={loading} className="w-full bg-ink text-white p-3 rounded-lg disabled:opacity-50">{loading ? '連線中…' : publicDemo ? '開始模擬' : '開啟工作台'}</button></section> : <>
        <div className="mb-7 flex justify-between gap-4"><div><p className="uppercase tracking-widest text-accent font-semibold text-xs">Operations overview</p><h2 className="text-2xl font-bold mt-1">{publicDemo ? '採購模擬工作台' : '營運總覽'}</h2><p className="text-sm text-slate-500 mt-1">{publicDemo ? `展示身分：${role}；資料僅供模擬，不會送出真實訂單。` : '以下指標由資料庫計算，來源標示於卡片下方。'}</p></div><button className="self-start border rounded-lg px-3 py-2 text-sm" onClick={switchRole}>{publicDemo ? `切換為 ${role === 'analyst' ? 'manager' : 'analyst'}` : '切換身分'}</button></div>
        {!publicDemo && <><div className="grid sm:grid-cols-3 gap-4 mb-7">
          <Stat icon={<Activity size={19}/>} label="整體良率" value={`${dashboard?.kpi.data.yield_pct ?? '—'}%`} source={dashboard?.kpi.source}/>
          <Stat icon={<ShieldCheck size={19}/>} label="品質異常" value={String((dashboard?.issues.data.items as unknown[] | undefined)?.length ?? '—')} source={dashboard?.issues.source}/>
          <Stat icon={<TrendingUp size={19}/>} label="銷售營收" value={`NT$ ${Number(dashboard?.sales.data.revenue ?? 0).toLocaleString()}`} source={dashboard?.sales.source}/>
        </div>
        <section className="grid lg:grid-cols-[1.45fr_1fr] gap-6"><div className="bg-white border rounded-2xl overflow-hidden shadow-sm"><div className="px-5 py-4 border-b flex items-center gap-2"><Bot className="text-accent" size={20}/><h3 className="font-semibold">營運助理</h3></div><div className="px-5 py-5 space-y-5 min-h-[330px] max-h-[560px] overflow-auto" aria-live="polite">{conversation.length === 0 && <><p className="text-slate-600 text-sm">詢問生產良率、品質異常、銷售表現或指定的 ERP / EIP 資料。</p><div className="flex flex-wrap gap-2">{['本月生產良率與品質異常', '查詢 P-100 庫存', '銷售營收', '簽核規則'].map(q => <button key={q} onClick={() => send(q)} className="text-xs rounded-full bg-slate-100 hover:bg-teal-50 px-3 py-2">{q}</button>)}</div></>}{conversation.map((item, index) => <div key={index} className="space-y-3"><div className="ml-auto bg-ink text-white rounded-xl p-3 text-sm max-w-[85%] w-fit">{item.question}</div><div className="bg-slate-50 rounded-xl p-4 text-sm whitespace-pre-wrap break-words"><p className="text-xs font-bold text-accent mb-2">{item.result.mode === 'mock' ? 'MOCK MODE · 非真實 LLM' : 'AI AGENT'}</p>{item.result.answer}<div className="mt-4 space-y-2">{item.result.trace.map((t, i) => <details key={i} className="bg-white border rounded-lg p-2"><summary className="cursor-pointer text-xs font-medium">工具 {i + 1}: {t.tool} · {t.source}</summary><pre className="text-xs overflow-auto mt-2">{JSON.stringify({ input: t.input, output: t.output }, null, 2)}</pre></details>)}</div></div></div>)}</div><form onSubmit={e => { e.preventDefault(); send() }} className="border-t p-4 flex gap-2"><input aria-label="提問" className="border rounded-lg p-3 text-sm flex-1 min-w-0" placeholder="例如：P-100 庫存狀況？" value={message} onChange={e => setMessage(e.target.value)}/><button aria-label="送出" disabled={loading} className="bg-accent text-white rounded-lg px-4 disabled:opacity-50"><Send size={18}/></button></form></div><aside className="space-y-4"><div className="bg-ink text-white rounded-2xl p-6"><Database size={21} className="text-teal-300"/><h3 className="font-semibold mt-3 mb-2">資料流與權限</h3><p className="text-sm text-slate-300 leading-7">自然語言 → Function Calling → 獨立 MCP Server → 模擬企業資料庫。工具依角色授權，呼叫紀錄寫入稽核表。</p></div><div className="bg-white border rounded-2xl p-6"><h3 className="font-semibold mb-3">資料來源</h3><ul className="text-sm text-slate-600 space-y-2"><li>Data MCP · 生產、品質、銷售</li><li>ERP MCP · 庫存、訂單</li><li>EIP MCP · 簽核規則與狀態</li></ul></div></aside></section>
        </>}
        <section className="mt-8 bg-white border rounded-2xl p-6 shadow-sm" aria-label="Workflow Console">
          <div className="flex flex-wrap justify-between gap-3"><div><h2 className="text-xl font-bold">採購 Workflow Console</h2><p className="text-sm text-slate-500 mt-1">Mock Mode · 確定性規則；只有 manager 可人工提交，提交後仍須 EIP 簽核。</p></div><button onClick={() => refreshWorkflows().catch(err => setError(String(err)))} className="text-sm text-accent">重新整理</button></div>
          <form onSubmit={e => { e.preventDefault(); createWorkflow() }} className="flex flex-wrap gap-2 mt-5"><input aria-label="採購需求" value={workflowMessage} onChange={e => setWorkflowMessage(e.target.value)} placeholder="例如：請評估採購 P-300" className="border rounded-lg p-3 flex-1 min-w-[220px]"/><button disabled={workflowLoading} className="bg-accent text-white rounded-lg px-5 disabled:opacity-50">建立採購草稿</button></form>
          <div className="space-y-4 mt-6" aria-live="polite">{workflows.length === 0 && <p className="text-sm text-slate-500">目前沒有任務</p>}{workflows.map(flow => <article key={flow.id} className="rounded-xl border p-4 space-y-3"><div className="flex justify-between gap-3"><h3 className="font-semibold">{flow.sku} · {flow.status}</h3><span className="text-xs text-slate-500 break-all">{flow.id}</span></div><p className="text-sm">採購缺口：{flow.quantity ?? '計算中'}；庫存 {flow.inventory ?? '—'} + 待交採購 {flow.inbound ?? '—'}；補貨基準 {flow.reorder_point ?? '—'} + 未交銷售 {flow.open_sales ?? '—'}</p><p className="text-xs text-slate-500">規則版本 #{flow.rule_id ?? '—'} · 產品修訂 {flow.product_revision ?? '—'}</p>{flow.stale && <p role="status" className="text-amber-800">資料或規則已更新：請重新建立草稿，舊草稿不能提交。</p>}{flow.error && <p role="status" className="text-red-700 text-sm">{flow.error}</p>}{flow.purchase_id && <p className="text-sm">採購單 #{flow.purchase_id} · EIP 簽核 #{flow.approval_id} · {approval[flow.id] ?? '待查詢'}</p>}<div className="flex flex-wrap gap-2">{flow.status === 'awaiting_confirmation' && role === 'manager' && <button disabled={workflowLoading || flow.stale} onClick={() => action(flow.id, 'submit')} className="bg-ink text-white rounded-lg px-3 py-2 text-sm disabled:opacity-50">人工確認並提交</button>}{flow.status === 'failed' && <button disabled={workflowLoading} onClick={() => action(flow.id, 'retry')} className="border rounded-lg px-3 py-2 text-sm">重新執行</button>}{['running', 'failed', 'awaiting_confirmation'].includes(flow.status) && <button disabled={workflowLoading} onClick={() => action(flow.id, 'cancel')} className="border rounded-lg px-3 py-2 text-sm">取消</button>}{flow.status === 'submitted' && role === 'manager' && <button disabled={workflowLoading} onClick={() => checkApproval(flow.id)} className="border rounded-lg px-3 py-2 text-sm">查詢 EIP 簽核</button>}</div><details><summary className="text-sm cursor-pointer">Agent / MCP 執行歷程（{flow.events.length}）</summary><ol className="mt-2 space-y-2">{flow.events.map(evt => <li key={evt.id} className="text-xs border-l-2 pl-3 break-words">{evt.agent} · {evt.step} · {evt.outcome}<pre className="overflow-auto mt-1">{JSON.stringify(evt.detail, null, 2)}</pre></li>)}</ol></details></article>)}</div>
        </section>
        <section className="mt-8 bg-white border rounded-2xl p-6 shadow-sm" aria-label="模擬資料與規則">
          <h2 className="text-xl font-bold">模擬資料與採購規則</h2>
          <p className="text-sm text-slate-500">資料修改即刻影響新查詢；規則發布後新草稿才使用新版本。舊草稿過期須重新建立。</p>
          <p className="mt-3 text-sm">現行規則 #{activeRule?.id ?? '—'}：{activeRule?.expression ?? '載入中'}；安全庫存 {activeRule?.safety_stock ?? 0}</p>
          <ul className="mt-3 text-sm space-y-1">{products.map(p => <li key={p.sku}>{p.sku} · {p.name} · 庫存 {p.inventory} · 補貨基準 {p.reorder_point} · 修訂 {p.revision}</li>)}</ul>
          {role === 'manager' && <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <div className="space-y-2"><h3 className="font-semibold">產品與訂單</h3>
              <label className="block text-sm">SKU <input aria-label="編輯 SKU" className="border rounded p-2 w-full" value={selectedSku} onChange={e => { const sku = e.target.value.toUpperCase(); setSelectedSku(sku); setPreview(null); const p = products.find(item => item.sku === sku); if (p) { setProductName(p.name); setInventory(p.inventory); setReorderPoint(p.reorder_point) } }}/></label>
              <label className="block text-sm">名稱 <input aria-label="產品名稱" className="border rounded p-2 w-full" value={productName} onChange={e => setProductName(e.target.value)}/></label>
              <label className="block text-sm">庫存 <input aria-label="庫存數量" type="number" min="0" className="border rounded p-2 w-full" value={inventory} onChange={e => setInventory(Number(e.target.value))}/></label>
              <label className="block text-sm">補貨基準 <input aria-label="補貨基準" type="number" min="0" className="border rounded p-2 w-full" value={reorderPoint} onChange={e => setReorderPoint(Number(e.target.value))}/></label>
              <button disabled={workflowLoading} onClick={saveProduct} className="bg-accent text-white rounded px-4 py-2 disabled:opacity-50">新增或儲存產品</button>
              <div className="flex gap-2 items-center"><select aria-label="訂單類型" className="border rounded p-2" value={orderKind} onChange={e => setOrderKind(e.target.value as 'sale' | 'inbound')}><option value="sale">未交銷售</option><option value="inbound">待交採購</option></select><input aria-label="訂單數量" type="number" min="1" className="border rounded p-2 w-24" value={orderQuantity} onChange={e => setOrderQuantity(Number(e.target.value))}/><button disabled={workflowLoading} onClick={saveOrder} className="border rounded px-3 py-2">新增訂單</button></div>
            </div>
            <div className="space-y-2"><h3 className="font-semibold">新規則版本</h3>
              <label className="block text-sm">公式 <select aria-label="採購公式" className="border rounded p-2 w-full" value={formula} onChange={e => { const next = e.target.value as 'standard' | 'safety_stock'; setFormula(next); if (next === 'standard') setSafetyStock(0); setPreview(null) }}><option value="standard">標準缺口</option><option value="safety_stock">缺口加安全庫存</option></select></label>
              <label className="block text-sm">安全庫存 <input aria-label="安全庫存" type="number" min="0" disabled={formula === 'standard'} className="border rounded p-2 w-full" value={safetyStock} onChange={e => { setSafetyStock(Number(e.target.value)); setPreview(null) }}/></label>
              <button disabled={workflowLoading} onClick={previewRule} className="border rounded px-4 py-2">預覽 {selectedSku}</button>
              {preview && <div role="status" className="bg-teal-50 p-3 text-sm">預覽 {preview.sku}：{preview.reorder_point} + {formula === 'safety_stock' ? `${safetyStock} + ` : ''}{preview.open_sales} - {preview.inventory} - {preview.inbound} = {preview.quantity} <button disabled={workflowLoading} onClick={publishRule} className="ml-2 bg-ink text-white rounded px-3 py-2">發布規則</button></div>}
            </div>
          </div>}
          <details className="mt-5"><summary className="cursor-pointer text-sm">資料與規則異動歷程（{catalogChanges.length}）</summary><ol className="text-xs mt-2 space-y-2">{catalogChanges.map(item => <li key={item.id} className="border-l-2 pl-3">{item.action} · {item.target} · 操作者 #{item.actor_id} · {item.created_at}<pre className="overflow-auto">{JSON.stringify({ before: item.before, after: item.after }, null, 2)}</pre></li>)}</ol></details>
        </section>
      </>}{error && <p role="alert" className="mt-4 text-red-700 text-sm">{error}</p>}
    </main>
  </div>
}

function Stat({ icon, label, value, source }: { icon: React.ReactNode; label: string; value: string; source?: string }) {
  return <div className="bg-white border rounded-2xl p-5 shadow-sm"><div className="text-accent mb-5">{icon}</div><p className="text-sm text-slate-500">{label}</p><p className="text-3xl font-bold mt-1">{value}</p><p className="text-xs text-slate-400 mt-4">來源 · {source}</p></div>
}
