import { useState } from 'react'
import { Activity, Bot, Database, Factory, LockKeyhole, Send, ShieldCheck, TrendingUp } from 'lucide-react'

type Result = { source: string; data: Record<string, unknown> }
type Trace = { tool: string; input: Record<string, unknown>; source: string; output: Record<string, unknown> }
type Chat = { mode: 'mock' | 'llm'; answer: string; trace: Trace[] }
type Dashboard = { kpi: Result; issues: Result; sales: Result }
type WorkflowEvent = { id: number; agent: string; step: string; outcome: string; detail: Record<string, unknown> }
type Workflow = { id: string; owner_id: number; sku: string; status: string; inventory: number | null; reorder_point: number | null; open_sales: number | null; inbound: number | null; quantity: number | null; error: string | null; purchase_id: number | null; approval_id: number | null; events: WorkflowEvent[] }

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

  async function signIn() {
    setError(''); setLoading(true)
    try {
      const identity = await request<{role: string}>('/api/me', token)
      setRole(identity.role)
      setDashboard(await request('/api/dashboard', token))
      setWorkflows(await request<Workflow[]>('/api/workflows', token))
      setReady(true)
    } catch (err) { setError(String(err)) } finally { setLoading(false) }
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
      {!ready ? <section className="max-w-md mx-auto mt-12 bg-white rounded-2xl border p-7 shadow-sm"><LockKeyhole className="text-accent mb-4"/><h2 className="text-xl font-semibold mb-2">輸入 Demo 憑證</h2><p className="text-sm text-slate-500 mb-5">請從本機 .env 取得 analyst 或 manager token；不會儲存在瀏覽器中。</p><input aria-label="Demo bearer token" type="password" value={token} onChange={e => setToken(e.target.value)} onKeyDown={e => e.key === 'Enter' && signIn()} placeholder="Demo bearer token" className="border rounded-lg p-3 w-full mb-3"/><button onClick={signIn} disabled={loading} className="w-full bg-ink text-white p-3 rounded-lg disabled:opacity-50">{loading ? '連線中…' : '開啟工作台'}</button></section> : <>
        <div className="mb-7"><p className="uppercase tracking-widest text-accent font-semibold text-xs">Operations overview</p><h2 className="text-2xl font-bold mt-1">營運總覽</h2><p className="text-sm text-slate-500 mt-1">以下指標由資料庫計算，來源標示於卡片下方。</p></div>
        <div className="grid sm:grid-cols-3 gap-4 mb-7">
          <Stat icon={<Activity size={19}/>} label="整體良率" value={`${dashboard?.kpi.data.yield_pct ?? '—'}%`} source={dashboard?.kpi.source}/>
          <Stat icon={<ShieldCheck size={19}/>} label="品質異常" value={String((dashboard?.issues.data.items as unknown[] | undefined)?.length ?? '—')} source={dashboard?.issues.source}/>
          <Stat icon={<TrendingUp size={19}/>} label="銷售營收" value={`NT$ ${Number(dashboard?.sales.data.revenue ?? 0).toLocaleString()}`} source={dashboard?.sales.source}/>
        </div>
        <section className="grid lg:grid-cols-[1.45fr_1fr] gap-6"><div className="bg-white border rounded-2xl overflow-hidden shadow-sm"><div className="px-5 py-4 border-b flex items-center gap-2"><Bot className="text-accent" size={20}/><h3 className="font-semibold">營運助理</h3></div><div className="px-5 py-5 space-y-5 min-h-[330px] max-h-[560px] overflow-auto" aria-live="polite">{conversation.length === 0 && <><p className="text-slate-600 text-sm">詢問生產良率、品質異常、銷售表現或指定的 ERP / EIP 資料。</p><div className="flex flex-wrap gap-2">{['本月生產良率與品質異常', '查詢 P-100 庫存', '銷售營收', '簽核規則'].map(q => <button key={q} onClick={() => send(q)} className="text-xs rounded-full bg-slate-100 hover:bg-teal-50 px-3 py-2">{q}</button>)}</div></>}{conversation.map((item, index) => <div key={index} className="space-y-3"><div className="ml-auto bg-ink text-white rounded-xl p-3 text-sm max-w-[85%] w-fit">{item.question}</div><div className="bg-slate-50 rounded-xl p-4 text-sm whitespace-pre-wrap break-words"><p className="text-xs font-bold text-accent mb-2">{item.result.mode === 'mock' ? 'MOCK MODE · 非真實 LLM' : 'AI AGENT'}</p>{item.result.answer}<div className="mt-4 space-y-2">{item.result.trace.map((t, i) => <details key={i} className="bg-white border rounded-lg p-2"><summary className="cursor-pointer text-xs font-medium">工具 {i + 1}: {t.tool} · {t.source}</summary><pre className="text-xs overflow-auto mt-2">{JSON.stringify({ input: t.input, output: t.output }, null, 2)}</pre></details>)}</div></div></div>)}</div><form onSubmit={e => { e.preventDefault(); send() }} className="border-t p-4 flex gap-2"><input aria-label="提問" className="border rounded-lg p-3 text-sm flex-1 min-w-0" placeholder="例如：P-100 庫存狀況？" value={message} onChange={e => setMessage(e.target.value)}/><button aria-label="送出" disabled={loading} className="bg-accent text-white rounded-lg px-4 disabled:opacity-50"><Send size={18}/></button></form></div><aside className="space-y-4"><div className="bg-ink text-white rounded-2xl p-6"><Database size={21} className="text-teal-300"/><h3 className="font-semibold mt-3 mb-2">資料流與權限</h3><p className="text-sm text-slate-300 leading-7">自然語言 → Function Calling → 獨立 MCP Server → 模擬企業資料庫。工具依角色授權，呼叫紀錄寫入稽核表。</p></div><div className="bg-white border rounded-2xl p-6"><h3 className="font-semibold mb-3">資料來源</h3><ul className="text-sm text-slate-600 space-y-2"><li>Data MCP · 生產、品質、銷售</li><li>ERP MCP · 庫存、訂單</li><li>EIP MCP · 簽核規則與狀態</li></ul></div></aside></section>
        <section className="mt-8 bg-white border rounded-2xl p-6 shadow-sm" aria-label="Workflow Console">
          <div className="flex flex-wrap justify-between gap-3"><div><h2 className="text-xl font-bold">採購 Workflow Console</h2><p className="text-sm text-slate-500 mt-1">Mock Mode · 確定性規則；只有 manager 可人工提交，提交後仍須 EIP 簽核。</p></div><button onClick={() => refreshWorkflows().catch(err => setError(String(err)))} className="text-sm text-accent">重新整理</button></div>
          <form onSubmit={e => { e.preventDefault(); createWorkflow() }} className="flex flex-wrap gap-2 mt-5"><input aria-label="採購需求" value={workflowMessage} onChange={e => setWorkflowMessage(e.target.value)} placeholder="例如：請評估採購 P-300" className="border rounded-lg p-3 flex-1 min-w-[220px]"/><button disabled={workflowLoading} className="bg-accent text-white rounded-lg px-5 disabled:opacity-50">建立採購草稿</button></form>
          <div className="space-y-4 mt-6" aria-live="polite">{workflows.length === 0 && <p className="text-sm text-slate-500">目前沒有任務</p>}{workflows.map(flow => <article key={flow.id} className="rounded-xl border p-4 space-y-3"><div className="flex justify-between gap-3"><h3 className="font-semibold">{flow.sku} · {flow.status}</h3><span className="text-xs text-slate-500 break-all">{flow.id}</span></div><p className="text-sm">採購缺口：{flow.quantity ?? '計算中'}；庫存 {flow.inventory ?? '—'} + 待交採購 {flow.inbound ?? '—'}；補貨基準 {flow.reorder_point ?? '—'} + 未交銷售 {flow.open_sales ?? '—'}</p>{flow.error && <p role="status" className="text-red-700 text-sm">{flow.error}</p>}{flow.purchase_id && <p className="text-sm">採購單 #{flow.purchase_id} · EIP 簽核 #{flow.approval_id} · {approval[flow.id] ?? '待查詢'}</p>}<div className="flex flex-wrap gap-2">{flow.status === 'awaiting_confirmation' && role === 'manager' && <button disabled={workflowLoading} onClick={() => action(flow.id, 'submit')} className="bg-ink text-white rounded-lg px-3 py-2 text-sm">人工確認並提交</button>}{flow.status === 'failed' && <button disabled={workflowLoading} onClick={() => action(flow.id, 'retry')} className="border rounded-lg px-3 py-2 text-sm">重新執行</button>}{['running', 'failed', 'awaiting_confirmation'].includes(flow.status) && <button disabled={workflowLoading} onClick={() => action(flow.id, 'cancel')} className="border rounded-lg px-3 py-2 text-sm">取消</button>}{flow.status === 'submitted' && role === 'manager' && <button disabled={workflowLoading} onClick={() => checkApproval(flow.id)} className="border rounded-lg px-3 py-2 text-sm">查詢 EIP 簽核</button>}</div><details><summary className="text-sm cursor-pointer">Agent / MCP 執行歷程（{flow.events.length}）</summary><ol className="mt-2 space-y-2">{flow.events.map(evt => <li key={evt.id} className="text-xs border-l-2 pl-3 break-words">{evt.agent} · {evt.step} · {evt.outcome}<pre className="overflow-auto mt-1">{JSON.stringify(evt.detail, null, 2)}</pre></li>)}</ol></details></article>)}</div>
        </section>
      </>}{error && <p role="alert" className="mt-4 text-red-700 text-sm">{error}</p>}
    </main>
  </div>
}

function Stat({ icon, label, value, source }: { icon: React.ReactNode; label: string; value: string; source?: string }) {
  return <div className="bg-white border rounded-2xl p-5 shadow-sm"><div className="text-accent mb-5">{icon}</div><p className="text-sm text-slate-500">{label}</p><p className="text-3xl font-bold mt-1">{value}</p><p className="text-xs text-slate-400 mt-4">來源 · {source}</p></div>
}
