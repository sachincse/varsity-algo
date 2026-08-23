import { useState } from 'react'
import { api } from '../api'

export default function Setup({ config, onChange }) {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')

  if (!config) return <div className="panel"><p className="muted">Loading…</p></div>

  const kite = config.kite
  const llm = config.llm

  async function login(e) {
    e.preventDefault()
    setBusy(true); setErr(''); setOk('')
    try {
      const r = await api.kiteLogin(token)
      setOk(`Connected as ${r.profile.user_name} (${r.profile.user_id}).`)
      setToken('')
      onChange()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function logout() {
    setBusy(true); setErr(''); setOk('')
    try { await api.kiteLogout(); onChange() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="panel">
        <h2>Zerodha Kite</h2>
        <p className="sub">
          Needed for holdings, live prices and placing orders. Not needed just
          to scan — the scanner works on free end-of-day data.
        </p>

        {!kite.configured && (
          <div className="msg warn">
            <strong>No API credentials yet.</strong> Add <code>KITE_API_KEY</code> and{' '}
            <code>KITE_API_SECRET</code> to the <code>.env</code> file in the project
            root, then restart the backend. Step 4 of <code>docs/SETUP.md</code> walks
            through creating the app at developers.kite.trade.
          </div>
        )}

        {kite.configured && !kite.authenticated && (
          <>
            <div className="msg info">
              <strong>Step 1.</strong>{' '}
              <a href={kite.login_url} target="_blank" rel="noreferrer">
                Open the Kite login page
              </a>{' '}and sign in.
              <br />
              <strong>Step 2.</strong> You will land on your redirect URL. Copy the
              value of <code>request_token</code> from the address bar and paste it
              below. You can paste the whole URL — the token will be extracted.
              <br />
              <span className="muted">
                The token is single-use and dies after a couple of minutes. If it
                fails, just get a fresh one.
              </span>
            </div>
            <form onSubmit={login} className="row">
              <div className="grow">
                <label htmlFor="rt">request_token</label>
                <input id="rt" value={token} onChange={e => setToken(e.target.value)}
                       placeholder="paste the token, or the whole redirected URL"
                       autoComplete="off" spellCheck="false" />
              </div>
              <button className="btn" disabled={busy || !token.trim()}>
                {busy ? 'Connecting…' : 'Connect'}
              </button>
            </form>
          </>
        )}

        {kite.authenticated && (
          <>
            <div className="stat">
              <div><span>User</span><b>{kite.profile.user_id}</b></div>
              <div><span>Name</span><b style={{ fontSize: 15 }}>{kite.profile.user_name}</b></div>
              <div><span>Broker</span><b style={{ fontSize: 15 }}>{kite.profile.broker}</b></div>
              <div><span>Exchanges</span><b style={{ fontSize: 15 }}>
                {(kite.profile.exchanges || []).join(', ')}</b></div>
            </div>
            <p className="muted" style={{ marginTop: 12 }}>
              Session expires {new Date(kite.profile.expires_at).toLocaleString()} —
              Kite tokens always die at 6&nbsp;AM IST.
            </p>
            <button className="btn ghost" onClick={logout} disabled={busy}
                    style={{ marginTop: 12 }}>Disconnect</button>
          </>
        )}

        {err && <div className="msg err" style={{ marginTop: 14 }}>{err}</div>}
        {ok && <div className="msg info" style={{ marginTop: 14 }}>{ok}</div>}
      </div>

      <div className="panel">
        <h2>Language model</h2>
        <p className="sub">
          Used only to turn your English description into a strategy. The model
          never writes or runs code — it fills in a fixed schema that the server
          validates. Active provider: <strong>{llm.active_label}</strong>
          {' '}(<code className="mono">{llm.model}</code>). Change it with{' '}
          <code>LLM_PROVIDER</code> and <code>LLM_MODEL</code> in <code>.env</code>.
        </p>
        <div className="provider-grid">
          {llm.providers.map(p => (
            <div key={p.key} className={`provider ${p.configured ? 'on' : ''}`}>
              <div className="nm">
                <span>{p.label}</span>
                <span className={`pill ${p.configured ? 'ok' : 'no'}`}>
                  {p.configured ? 'ready' : p.local ? 'not running' : 'no key'}
                </span>
              </div>
              <div className="mdl">
                LLM_PROVIDER={p.key}
                {p.env_var ? ` · ${p.env_var}` : ' · no key needed'}
              </div>
              <div className="nt">{p.note}</div>
              {!p.configured && p.signup && (
                <div className="nt">
                  <a href={p.signup} target="_blank" rel="noreferrer">Get a key →</a>
                </div>
              )}
            </div>
          ))}
        </div>
        <p className="muted" style={{ marginTop: 14 }}>
          No key at all? The Strategy tab still works — it ships with the video's
          SMA 6/30 rule built in, and you can edit the numbers by hand.
        </p>
      </div>
    </>
  )
}
