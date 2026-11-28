import { useState } from 'react'
import { BookOpen, Send } from 'lucide-react'

type Department = '' | 'shared' | 'procurement' | 'operations' | 'quality'
type KnowledgeRequest = {
  message: string
  filters: { department?: Exclude<Department, ''> }
}
export type Citation = {
  document_id: string
  title: string
  version: number
  department: string
  updated_at: string
  section: string
  paragraph: string
  excerpt: string
}
export type KnowledgeAnswer = {
  agent: 'knowledge'
  mode: 'mock' | 'llm'
  status: 'answered' | 'no_evidence'
  answer: string
  citations: Citation[]
  inference: null
  model_fallback: boolean
  trace: {
    tool: string
    source: string
    request_id: string
    strategy: string
    matches: number
    filters: KnowledgeRequest['filters']
    outcome: 'matched' | 'no_evidence'
  }[]
}

export function KnowledgeResult({ result }: { result: KnowledgeAnswer }) {
  return <div className="space-y-3 text-sm">
    <p className="text-xs font-bold text-accent">
      {result.mode === 'llm' ? 'Knowledge Agent · AI 選取引用' : 'Mock Mode · 依文件摘錄'}
    </p>
    {result.model_fallback && <p className="text-xs text-slate-600">AI 選取暫時無法使用，顯示檢索到的文件段落。</p>}
    {result.status === 'answered' && <h4 className="font-semibold">文件規範</h4>}
    <p className="whitespace-pre-line break-words">{result.answer}</p>
    <Citations citations={result.citations}/>
    <details className="rounded-lg border bg-white p-3">
      <summary className="cursor-pointer">RAG / MCP 執行追蹤</summary>
      {result.trace.map(item => <div key={item.request_id} className="mt-2 space-y-1 text-xs text-slate-600 break-words">
        <p>{item.tool} · {item.source}</p>
        <p>{item.strategy} · {item.matches} 段授權且相符的文件</p>
        {item.filters.department && <p>部門篩選 {item.filters.department}</p>}
        <p>查詢識別碼 {item.request_id}</p>
      </div>)}
    </details>
  </div>
}

export function Citations({ citations }: { citations: Citation[] }) {
  return citations.length > 0 && <div>
      <h4 className="font-semibold mb-2">引用來源</h4>
      <ol className="list-decimal pl-5 space-y-2">
        {citations.map(citation => <li key={`${citation.document_id}@${citation.version}#${citation.paragraph}`}>
          <details className="rounded-lg border bg-white p-3">
            <summary className="cursor-pointer">
              {citation.title} · v{citation.version} · §{citation.paragraph} {citation.section}
            </summary>
            <blockquote className="mt-2 border-l-2 border-teal-200 pl-3 break-words">{citation.excerpt}</blockquote>
            <p className="mt-2 text-xs text-slate-600">更新日期 {citation.updated_at.slice(0, 10)}</p>
          </details>
        </li>)}
      </ol>
    </div>
}

const examples = ['請購單需要填哪些欄位？', 'A 類料的循環盤點頻率？', '不合格品如何隔離？']

export function KnowledgePanel({
  query, publicDemo,
}: {
  query: (input: KnowledgeRequest) => Promise<KnowledgeAnswer>
  publicDemo: boolean
}) {
  const [message, setMessage] = useState('')
  const [department, setDepartment] = useState<Department>('')
  const [result, setResult] = useState<KnowledgeAnswer | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function ask(question: string) {
    if (question.trim().length < 2 || loading) return
    setMessage(question)
    setResult(null)
    setError('')
    setLoading(true)
    try {
      setResult(await query({ message: question.trim(), filters: department ? { department } : {} }))
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  return <section id="knowledge" aria-labelledby="knowledge-heading" className="mt-8 scroll-mt-5 bg-white border rounded-2xl p-6 shadow-sm">
    <div className="flex items-center gap-2">
      <BookOpen size={20} className="text-accent" aria-hidden="true"/>
      <h2 id="knowledge-heading" className="text-xl font-bold">企業知識問答</h2>
    </div>
    <div className="mt-4 flex flex-wrap gap-2">
      {examples.map(example => <button key={example} type="button" disabled={loading} onClick={() => ask(example)}
        className="text-xs rounded-full bg-slate-100 hover:bg-teal-50 px-3 py-2 disabled:opacity-50">
        {example}
      </button>)}
    </div>
    <form className="mt-4 flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); void ask(message) }}>
      <input aria-label="知識問答問題" value={message} onChange={event => setMessage(event.target.value)}
        className="border rounded-lg p-3 text-sm flex-1 min-w-[min(100%,220px)]" maxLength={1000}
        placeholder="例如：採購簽核門檻是多少？"/>
      {!publicDemo && <select aria-label="文件部門" value={department} onChange={event => setDepartment(event.target.value as Department)}
        className="border rounded-lg px-3 text-sm">
        <option value="">所有可查閱部門</option>
        <option value="shared">共用文件</option>
        <option value="procurement">採購</option>
        <option value="operations">營運</option>
        <option value="quality">品質</option>
      </select>}
      <button type="submit" disabled={message.trim().length < 2 || loading}
        className="bg-accent text-white rounded-lg px-4 py-2.5 text-sm flex items-center gap-2 disabled:opacity-50">
        <Send aria-hidden="true" size={16}/>查詢文件
      </button>
    </form>
    <div aria-live="polite" aria-busy={loading}>
      {loading && <p className="mt-4 text-sm text-slate-600">正在搜尋文件…</p>}
      {result && <div className="mt-4 rounded-xl bg-slate-50 p-4"><KnowledgeResult result={result}/></div>}
    </div>
    {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
  </section>
}
