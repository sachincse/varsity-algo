import { useEffect, useState } from 'react'
import { api } from '../api'

// The "user tab" from the video: after login it calls the profile API and
// shows the username, user ID, the products enabled, and the exchanges
// available on the account. Holdings and margins are added because once you
// have a live session there is no reason not to show them.

export default function Profile({ config }) {
  const kite = config?.kite
  const live = kite?.authenticated
  const [holdings, setHoldings] = useState(null)
  const [margins, setMargins] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!live) return
    let cancelled = false
    setBusy(true)
    Promise.allSettled([api.holdings(), api.margins()])
      .then(([h, m]) => {
        if (cancelled) return
        if (h.status === 'fulfilled') setHoldings(h.value)
        if (m.status === 'fulfilled') setMargins(m.value)
        const bad = [h, m].find(r => r.status === 'rejected')
        if (bad) setErr(bad.reason.message)
      })
      .finally(() => !cancelled && setBusy(false))
    return () => { cancelled = true }
  }, [live])

  if (!live) {
    return (
      <div className="panel">
        <h2>Your account</h2>
        <p className="sub">Nothing to show until you connect Zerodha.</p>
        <div className="msg info">
          Go to <strong>Connect</strong> and log in. The scanner works without
          this — you just will not see holdings, live prices, or be able to
          place orders.
        </div>
      </div>
    )
  }

  const p = kite.profile
  return (
    <>
      <div className="panel">
        <h2>Your account</h2>
        <p className="sub">Straight from the Kite profile API.</p>
        <div className="stat">
          <div><span>User ID</span><b>{p.user_id}</b></div>
          <div><span>Name</span><b style={{ fontSize: 16 }}>{p.user_name}</b></div>
          <div><span>Broker</span><b style={{ fontSize: 16 }}>{p.broker}</b></div>
          {p.email && <div><span>Email</span><b style={{ fontSize: 14 }}>{p.email}</b></div>}
        </div>

        <div className="row" style={{ marginTop: 22, alignItems: 'flex-start' }}>
          <div className="grow">
            <label>Products enabled</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {(p.products || []).map(x => (
                <span key={x} className="pill ok" style={{ fontFamily: 'monospace' }}>{x}</span>
              ))}
            </div>
          </div>
          <div className="grow">
            <label>Exchanges available</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {(p.exchanges || []).map(x => (
                <span key={x} className="pill warn" style={{ fontFamily: 'monospace' }}>{x}</span>
              ))}
            </div>
          </div>
          <div className="grow">
            <label>Order types</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {(p.order_types || []).map(x => (
                <span key={x} className="pill" style={{
                  fontFamily: 'monospace', background: 'var(--sunk)',
                  color: 'var(--ink-2)' }}>{x}</span>
              ))}
            </div>
          </div>
        </div>

        <p className="muted" style={{ marginTop: 18 }}>
          Logged in {p.login_time || '—'} · session expires{' '}
          {new Date(p.expires_at).toLocaleString()}
        </p>
      </div>

      {margins && (
        <div className="panel">
          <h2>Funds</h2>
          <div className="stat">
            <div><span>Available cash</span>
              <b style={{ color: 'var(--buy)' }}>
                {margins.available_cash.toLocaleString('en-IN',
                  { maximumFractionDigits: 0 })}</b></div>
          </div>
        </div>
      )}

      <div className="panel">
        <h2>Holdings {holdings ? `(${holdings.count})` : ''}</h2>
        {busy && <p className="muted">Loading…</p>}
        {err && <div className="msg warn">{err}</div>}
        {holdings && holdings.count === 0 && (
          <p className="muted">No holdings in this account.</p>
        )}
        {holdings && holdings.count > 0 && (
          <>
            <div className="stat" style={{ marginBottom: 16 }}>
              <div><span>Invested</span><b>
                {holdings.invested.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</b></div>
              <div><span>P&amp;L</span><b style={{
                color: holdings.pnl >= 0 ? 'var(--buy)' : 'var(--sell)' }}>
                {holdings.pnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</b></div>
            </div>
            <div className="tw">
              <table>
                <thead>
                  <tr><th>Symbol</th><th className="n">Qty</th>
                    <th className="n">Avg</th><th className="n">Last</th>
                    <th className="n">P&amp;L</th></tr>
                </thead>
                <tbody>
                  {holdings.holdings.map(h => (
                    <tr key={h.tradingsymbol}>
                      <td><strong>{h.tradingsymbol}</strong></td>
                      <td className="n">{h.quantity}</td>
                      <td className="n">{Number(h.average_price).toFixed(2)}</td>
                      <td className="n">{Number(h.last_price).toFixed(2)}</td>
                      <td className="n" style={{
                        color: h.pnl >= 0 ? 'var(--buy)' : 'var(--sell)' }}>
                        {Number(h.pnl).toFixed(0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  )
}
