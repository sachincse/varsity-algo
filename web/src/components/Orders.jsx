import { useState } from 'react'
import { api } from '../api'

export default function Orders({ config, scan, onConfigChange }) {
  const [capital, setCapital] = useState(1000000)
  const [maxPositions, setMaxPositions] = useState(10)
  const [maxBars, setMaxBars] = useState(3)
  const [sheet, setSheet] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [placing, setPlacing] = useState(null)
  const [results, setResults] = useState({})

  const tradingOn = config?.trading_enabled
  const kiteLive = config?.kite?.authenticated

  async function preview() {
    if (!scan?.signals?.length) { setErr('Run a scan first.'); return }
    setBusy(true); setErr(''); setResults({})
    try {
      setSheet(await api.preview({
        signals: scan.signals,
        capital: Number(capital),
        max_positions: Number(maxPositions),
        max_bars_since: Number(maxBars),
      }))
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function place(order) {
    const label = `${order.transaction_type} ${order.quantity} ${order.tradingsymbol}`
    if (!window.confirm(
      `Place a REAL order?\n\n${label}\nProduct ${order.product}, ${order.order_type}\n` +
      `Estimated value Rs ${order.est_value.toLocaleString('en-IN')}\n\n` +
      `This sends money to the market. There is no undo.`)) return

    setPlacing(order.confirm_token); setErr('')
    try {
      const r = await api.place({
        tradingsymbol: order.tradingsymbol,
        exchange: order.exchange,
        transaction_type: order.transaction_type,
        quantity: order.quantity,
        product: order.product,
        order_type: order.order_type,
        confirm_token: order.confirm_token,
        confirm: 'CONFIRM',
      })
      setResults(p => ({ ...p, [order.confirm_token]: r }))
      onConfigChange()
    } catch (e) {
      setResults(p => ({ ...p, [order.confirm_token]: { error: e.message } }))
    } finally { setPlacing(null) }
  }

  return (
    <>
      <div className="panel">
        <h2>Order sheet</h2>
        <p className="sub">
          Sized equally across open slots, from the signals on the Signals tab.
          Nothing is sent until you approve a specific row.
        </p>

        {!scan?.signals?.length && (
          <div className="msg info">Run a scan first — there is nothing to size yet.</div>
        )}

        <div className="row">
          <div style={{ minWidth: 170 }}>
            <label htmlFor="cap">Capital (Rs)</label>
            <input id="cap" type="number" value={capital} min="1000"
                   onChange={e => setCapital(e.target.value)} />
          </div>
          <div style={{ minWidth: 130 }}>
            <label htmlFor="mp">Max positions</label>
            <input id="mp" type="number" value={maxPositions} min="1" max="50"
                   onChange={e => setMaxPositions(e.target.value)} />
          </div>
          <div style={{ minWidth: 150 }}>
            <label htmlFor="mb">Max bars since signal</label>
            <input id="mb" type="number" value={maxBars} min="0" max="250"
                   onChange={e => setMaxBars(e.target.value)} />
          </div>
          <button className="btn" onClick={preview}
                  disabled={busy || !scan?.signals?.length}>
            {busy ? 'Building…' : 'Preview orders'}
          </button>
        </div>
        {kiteLive && (
          <p className="muted" style={{ marginTop: 10 }}>
            Connected to Kite — your real holdings and available cash will be
            used, overriding the capital figure above.
          </p>
        )}
        {err && <div className="msg err" style={{ marginTop: 14 }}>{err}</div>}
      </div>

      {sheet && (
        <div className="panel">
          <div className="stat" style={{ marginBottom: 16 }}>
            <div><span>Buy side</span><b style={{ color: 'var(--buy)' }}>
              {sheet.totals.buy.toLocaleString('en-IN')}</b></div>
            <div><span>Sell side</span><b style={{ color: 'var(--sell)' }}>
              {sheet.totals.sell.toLocaleString('en-IN')}</b></div>
            <div><span>Net</span><b>{sheet.totals.net.toLocaleString('en-IN')}</b></div>
            <div><span>Cash</span><b>{sheet.totals.cash.toLocaleString('en-IN')}</b></div>
          </div>

          {!tradingOn && (
            <div className="msg info">
              <strong>Order placement is off.</strong> This is preview-only. To
              arm it, set <code>ENABLE_TRADING=true</code> in <code>.env</code> and
              restart the backend. Leaving it off is the sensible default.
            </div>
          )}
          {tradingOn && !kiteLive && (
            <div className="msg warn">
              Trading is armed but you are not connected to Kite. Connect on the
              Setup tab.
            </div>
          )}
          {tradingOn && kiteLive && (
            <div className="msg err">
              <strong>Live orders are armed.</strong> Each button below sends a
              real market order to the exchange against account{' '}
              {config.kite.profile?.user_id}. Approvals expire after{' '}
              {Math.round(sheet.token_ttl_seconds / 60)} minutes.
            </div>
          )}

          {sheet.orders.length === 0 ? (
            <p className="muted">No orders — see the notes below for why.</p>
          ) : (
            <div className="tw">
              <table>
                <thead>
                  <tr>
                    <th>Side</th><th>Symbol</th><th className="n">Qty</th>
                    <th className="n">Est. price</th><th className="n">Est. value</th>
                    <th>Why</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {sheet.orders.map(o => {
                    const res = results[o.confirm_token]
                    return (
                      <tr key={o.confirm_token}>
                        <td>
                          <span className={`tag ${o.transaction_type === 'BUY' ? 'entry' : 'exit'}`}>
                            {o.transaction_type}
                          </span>
                        </td>
                        <td><strong>{o.tradingsymbol}</strong>
                          <div className="muted" style={{ fontSize: 11.5 }}>
                            {o.product} · {o.order_type}</div></td>
                        <td className="n">{o.quantity}</td>
                        <td className="n">{o.est_price.toLocaleString('en-IN',
                          { minimumFractionDigits: 2 })}</td>
                        <td className="n">{o.est_value.toLocaleString('en-IN',
                          { maximumFractionDigits: 0 })}</td>
                        <td className="muted" style={{ fontSize: 12.5 }}>{o.reason}</td>
                        <td>
                          {res ? (
                            res.error
                              ? <span className="pill no">{res.error.slice(0, 60)}</span>
                              : <span className="pill ok">
                                  {res.status} · {res.order_id}
                                </span>
                          ) : (
                            <button className="btn danger"
                                    style={{ fontSize: 12.5, padding: '6px 12px' }}
                                    disabled={!tradingOn || !kiteLive
                                              || placing === o.confirm_token}
                                    onClick={() => place(o)}>
                              {placing === o.confirm_token ? 'Sending…' : 'Place'}
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {sheet.notes?.length > 0 && (
            <ul className="notes">
              {sheet.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}

          <p className="muted" style={{ marginTop: 16 }}>{sheet.disclaimer}</p>
        </div>
      )}

      <div className="panel">
        <h2>Before you act on any of this</h2>
        <p className="sub" style={{ marginBottom: 0 }}>
          This exact rule — SMA 6/30 on the Nifty 100 — was backtested over
          2011&ndash;2026 with next-open fills, full Zerodha charges, 25 bps of
          slippage and a point-in-time universe. It returned <strong>1.9% a
          year against the index's 10.7%</strong>, lost to random entries of the
          same length in the same universe, and spent most of fifteen years
          under water. The scanner is a useful lens on what is moving. It is not
          a reason to trade.
        </p>
      </div>
    </>
  )
}
