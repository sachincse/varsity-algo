import { useState } from 'react'
import { api } from '../api'

const EXAMPLES = [
  'Scan the Nifty 100 for stocks where the 6 day moving average crosses over the 30 day, most recent first',
  'Golden cross on the Nifty 500, but only where RSI is under 70',
  'Stocks closing above their 20 day high, exit when they close below the 20 day average',
  'Nifty 50 stocks where RSI drops below 30, exit at RSI 65',
]

export default function Strategy({ config, spec, summary, onSpec, goToSignals }) {
  const [text, setText] = useState(EXAMPLES[0])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [warning, setWarning] = useState('')
  const [meta, setMeta] = useState(null)
  const [plain, setPlain] = useState('')
  const [notes, setNotes] = useState([])

  const llmReady = config?.llm?.providers?.some(p => p.key === config.llm.active && p.configured)

  async function describe(e) {
    e?.preventDefault()
    setBusy(true); setErr(''); setWarning(''); setMeta(null)
    try {
      const r = await api.strategyFromText(text)
      onSpec(r.spec, r.summary)
      setPlain(r.explanation || ''); setNotes(r.lint || [])
      setWarning(r.warning || '')
      setMeta(r.meta)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function useDefault() {
    setBusy(true); setErr(''); setWarning(''); setMeta(null)
    try {
      const r = await api.defaultStrategy()
      onSpec(r.spec, r.summary)
      setPlain(r.explanation || ''); setNotes(r.lint || [])
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="panel">
        <h2>Describe the strategy</h2>
        <p className="sub">
          Plain English. The model fills in a fixed schema — it never writes or
          runs code, and anything it produces that fails validation is rejected
          before it reaches the engine.
        </p>

        {!llmReady && (
          <div className="msg warn">
            <strong>No language model configured.</strong> You can still use the
            built-in SMA 6/30 rule below, or set up a provider on the Setup tab.
            The free options are Groq, OpenRouter and Google Gemini; Ollama runs
            locally with no key at all.
          </div>
        )}

        <form onSubmit={describe}>
          <label htmlFor="desc">Your rule</label>
          <textarea id="desc" value={text} onChange={e => setText(e.target.value)}
                    placeholder="e.g. buy when the 20 day average crosses above the 50 day on the Nifty 200" />
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={busy || !text.trim() || !llmReady}>
              {busy ? 'Thinking…' : 'Build strategy'}
            </button>
            <button type="button" className="btn ghost" onClick={useDefault} disabled={busy}>
              Use the video's SMA 6/30
            </button>
          </div>
        </form>

        <div style={{ marginTop: 16 }}>
          <label>Try one of these</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {EXAMPLES.map((ex, i) => (
              <button key={i} type="button" className="btn ghost"
                      style={{ fontSize: 12.5, fontWeight: 400, padding: '6px 11px' }}
                      onClick={() => setText(ex)}>
                {ex.length > 58 ? ex.slice(0, 55) + '…' : ex}
              </button>
            ))}
          </div>
        </div>

        {err && <div className="msg err" style={{ marginTop: 16 }}>{err}</div>}
        {warning && (
          <div className="msg warn" style={{ marginTop: 16 }}>
            <strong>Partly unsupported.</strong> {warning}
          </div>
        )}
      </div>

      {spec && (
        <div className="panel">
          <h2>Compiled strategy</h2>
          <p className="sub">
            This is what will actually run. Check it matches what you meant
            before scanning.
            {meta && (
              <> Built by <code className="mono">{meta.provider}/{meta.model}</code>
                {meta.repaired && ' (needed one correction round)'}.</>
            )}
          </p>
          {plain && (
            <div className="msg info" style={{ marginBottom: 14 }}>
              <strong>In plain English:</strong> {plain}
            </div>
          )}
          {notes.map((n, i) => (
            <div key={i} className={n.level === 'warn' ? 'msg err' : 'msg info'}
                 style={{ marginBottom: 10 }}>
              {n.message}
            </div>
          ))}
          <div className="spec">{summary}</div>
          <details style={{ marginTop: 14 }}>
            <summary className="muted" style={{ cursor: 'pointer' }}>
              Show the raw spec
            </summary>
            <div className="spec" style={{ marginTop: 10 }}>
              {JSON.stringify(spec, null, 2)}
            </div>
          </details>
          <button className="btn" style={{ marginTop: 16 }} onClick={goToSignals}>
            Scan for signals →
          </button>
        </div>
      )}
    </>
  )
}
