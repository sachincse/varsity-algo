import { useEffect, useState } from 'react'
import { api } from '../api'

// The login page from the video: API key, API secret, request token.
//
// Typing the secret into a browser form is not how you would build a hosted
// product, but this runs on your own laptop against your own backend, and it
// is what the video does. Credentials entered here are held in memory for the
// life of the server process and never written to disk — .env is offered
// alongside for anyone who would rather not retype them each morning.

export default function Connect({ config, onChange }) {
  const kite = config?.kite
  const fromEnv = kite?.credentials_from_env

  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [token, setToken] = useState('')
  const [showSecret, setShowSecret] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [caught, setCaught] = useState(false)

  // Zerodha sends the browser back to the redirect URL with the token in the
  // query string. That path falls through to this SPA, so rather than telling
  // people to copy it out of the address bar by hand, take it from the URL and
  // clean the bar afterwards — a token left in history is a token that leaks.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    const rt = q.get('request_token')
    if (!rt) return
    setToken(rt)
    setCaught(true)
    if (q.get('status') === 'error' || q.get('status') === 'cancelled') {
      setErr(`Zerodha reported "${q.get('status')}". Try the login link again.`)
    }
    window.history.replaceState({}, '', window.location.pathname === '/kite-redirect'
      ? '/' : window.location.pathname)
  }, [])

  const loginUrl = kite?.login_url
    || (apiKey.trim() ? `https://kite.zerodha.com/connect/login?v=3&api_key=${apiKey.trim()}` : '')

  async function login(e) {
    e.preventDefault()
    setBusy(true); setErr(''); setOk('')
    try {
      const r = await api.kiteLogin(token, apiKey, apiSecret)
      setOk(`Connected as ${r.profile.user_name} (${r.profile.user_id}).`)
      setToken(''); setApiSecret('')
      onChange()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function logout() {
    setBusy(true); setErr(''); setOk('')
    try { await api.kiteLogout(); onChange() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  if (kite?.authenticated) {
    const p = kite.profile
    return (
      <div className="panel">
        <h2>Zerodha Kite</h2>
        <p className="sub">Connected. Prices now come from your broker.</p>
        <div className="stat">
          <div><span>User ID</span><b>{p.user_id}</b></div>
          <div><span>Name</span><b style={{ fontSize: 15 }}>{p.user_name}</b></div>
          <div><span>Broker</span><b style={{ fontSize: 15 }}>{p.broker}</b></div>
        </div>
        <p className="muted" style={{ marginTop: 12 }}>
          Session expires {new Date(p.expires_at).toLocaleString()} — Kite tokens
          always die at 6&nbsp;AM IST, then you log in again.
        </p>
        <button className="btn ghost" onClick={logout} disabled={busy}
                style={{ marginTop: 12 }}>Disconnect</button>
        {err && <div className="msg err" style={{ marginTop: 14 }}>{err}</div>}
      </div>
    )
  }

  return (
    <div className="panel">
      <h2>Zerodha Kite</h2>
      <p className="sub">
        Connects the app to your broker, exactly as in the video — historical
        candles, live prices, holdings and order placement. The scanner works
        without it on free end-of-day data.
      </p>

      <div className="msg info">
        <strong>You need a Kite Connect app.</strong> Create one at{' '}
        <a href="https://developers.kite.trade" target="_blank" rel="noreferrer">
          developers.kite.trade</a> — type <strong>Connect</strong>, and set the
        redirect URL to <code>http://127.0.0.1:8000/kite-redirect</code>. It
        costs ₹500/month and includes historical data.
      </div>

      <form onSubmit={login}>
        <div className="row">
          <div className="grow">
            <label htmlFor="ak">API key</label>
            <input id="ak" value={fromEnv ? '•••••• (from .env)' : apiKey}
                   disabled={fromEnv} autoComplete="off" spellCheck="false"
                   placeholder="from your Kite app"
                   onChange={e => setApiKey(e.target.value)} />
          </div>
          <div className="grow">
            <label htmlFor="as">API secret</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input id="as" type={showSecret ? 'text' : 'password'}
                     value={fromEnv ? '••••••••••' : apiSecret}
                     disabled={fromEnv} autoComplete="off" spellCheck="false"
                     placeholder="kept in memory only"
                     onChange={e => setApiSecret(e.target.value)} />
              {!fromEnv && (
                <button type="button" className="btn ghost"
                        style={{ padding: '9px 12px', fontWeight: 400 }}
                        onClick={() => setShowSecret(v => !v)}>
                  {showSecret ? 'hide' : 'show'}
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="msg info" style={{ marginTop: 16 }}>
          <strong>Then get a request token.</strong>{' '}
          {loginUrl ? (
            <>
              <a href={loginUrl} target="_blank" rel="noreferrer">
                Open the Kite login page</a> and sign in. Zerodha sends you
              back here with the token already filled in — nothing to copy.
              If you landed here some other way, paste the address bar below.
            </>
          ) : (
            <>Enter your API key above and a login link will appear here.</>
          )}
          <br />
          <span className="muted">
            The token is single-use and dies after a couple of minutes. If login
            fails, that is almost always why — get a fresh one.
          </span>
        </div>

        {caught && (
          <div className="msg info" style={{ marginTop: 14 }}>
            <strong>Got your request token from the address bar.</strong>{' '}
            {fromEnv
              ? 'Press Login.'
              : 'Fill in your API key and secret above, then press Login.'}{' '}
            It expires in a couple of minutes, so do it now.
          </div>
        )}

        <div className="row" style={{ marginTop: 14 }}>
          <div className="grow">
            <label htmlFor="rt">Request token</label>
            <input id="rt" value={token} autoComplete="off" spellCheck="false"
                   placeholder="paste the token, or the whole redirected URL"
                   onChange={e => setToken(e.target.value)} />
          </div>
          <button className="btn"
                  disabled={busy || !token.trim() || (!fromEnv && (!apiKey.trim() || !apiSecret.trim()))}>
            {busy ? 'Connecting…' : 'Login'}
          </button>
        </div>
      </form>

      {!fromEnv && (
        <p className="muted" style={{ marginTop: 14 }}>
          Tired of retyping? Put <code>KITE_API_KEY</code> and{' '}
          <code>KITE_API_SECRET</code> in <code>.env</code> and restart — then
          only the request token is needed each morning.
        </p>
      )}

      {err && <div className="msg err" style={{ marginTop: 14 }}>{err}</div>}
      {ok && <div className="msg info" style={{ marginTop: 14 }}>{ok}</div>}
    </div>
  )
}
