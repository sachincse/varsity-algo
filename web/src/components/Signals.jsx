import { useState } from 'react'
import { api } from '../api'

export default function Signals({ spec, summary, scan, onScan, goToOrders }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [refresh, setRefresh] = useState(false)

  async function run() {
    if (!spec) { setErr('Pick a strategy on the Strategy tab first.'); return }
    setBusy(true); setErr('')
    try {
      onScan(await api.scan(spec, { refresh }))
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="panel">
        <h2>Scan</h2>
        <p className="sub">
          {summary
            ? summary.split('\n')[0]
            : 'No strategy selected yet.'}
        </p>
        <div className="row">
          <button className="btn" onClick={run} disabled={busy || !spec}>
            {busy ? 'Scanning…' : 'Run scan'}
          </button>
          <label style={{ display: 'flex', alignItems: 'center', gap: 7,
                          textTransform: 'none', letterSpacing: 0, fontWeight: 400,
                          fontSize: 13.5, color: 'var(--ink-2)', marginBottom: 0 }}>
            <input type="checkbox" checked={refresh} style={{ width: 'auto' }}
                   onChange={e => setRefresh(e.target.checked)} />
            re-download prices (slower)
          </label>
        </div>
        {busy && (
          <p className="muted" style={{ marginTop: 12 }}>
            First run downloads a few hundred symbols and takes a couple of
            minutes. Afterwards it is cached and near-instant.
          </p>
        )}
        {err && <div className="msg err" style={{ marginTop: 14 }}>{err}</div>}
      </div>

      {scan && (
        <div className="panel">
          <div className="stat" style={{ marginBottom: 18 }}>
            <div><span>As of</span><b style={{ fontSize: 16 }}>{scan.asof}</b></div>
            <div><span>Entries</span><b style={{ color: 'var(--buy)' }}>{scan.counts.entry}</b></div>
            <div><span>Exits</span><b style={{ color: 'var(--sell)' }}>{scan.counts.exit}</b></div>
            <div><span>Universe</span><b>{scan.universe_size}</b></div>
            <div><span>Bars</span><b>{scan.bars}</b></div>
            <div><span>Source</span><b style={{ fontSize: 15 }}>{scan.source}</b></div>
          </div>

          {scan.missing_symbols?.length > 0 && (
            <div className="msg warn">
              No price data for {scan.missing_symbols.length} symbol
              {scan.missing_symbols.length > 1 ? 's' : ''}:{' '}
              <span className="mono">{scan.missing_symbols.slice(0, 12).join(', ')}</span>
              {scan.missing_symbols.length > 12 && ' …'}
              {' '}— usually recent listings or renamed tickers.
            </div>
          )}

          {scan.signals.length === 0 ? (
            <p className="muted">
              No signals in the lookback window. That is a normal result, not a
              failure — widen <code>lookback_bars</code> or wait for the market
              to do something.
            </p>
          ) : (
            <>
              <div className="tw">
                <table>
                  <thead>
                    <tr>
                      <th>Symbol</th><th>Signal</th><th>Fired</th>
                      <th className="n">Bars ago</th><th className="n">Price</th>
                      <th>Price date</th><th className="n">Median turnover</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scan.signals.map(s => (
                      <tr key={`${s.symbol}-${s.side}`}
                          className={s.bars_since === 0 ? 'fresh' : ''}>
                        <td><strong>{s.symbol}</strong></td>
                        <td>
                          <span className={`tag ${s.side === 'ENTRY' ? 'entry' : 'exit'}`}>
                            {s.side}
                          </span>
                        </td>
                        <td className="mono">{s.signal_date}</td>
                        <td className="n">{s.bars_since}</td>
                        <td className="n">{s.price.toLocaleString('en-IN',
                          { minimumFractionDigits: 2 })}</td>
                        <td className="mono" style={{ color: s.price_date !== scan.asof
                          ? 'var(--warn)' : 'inherit' }}>{s.price_date}</td>
                        <td className="n">{s.median_turnover_cr.toFixed(1)} cr</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="msg warn" style={{ marginTop: 18 }}>
                <strong>An EXIT is a sell signal for something you already own.</strong>{' '}
                It is not a short. A retail account cannot hold a short equity
                position overnight in India, so half of a crossover scanner's
                output is only actionable if you are already holding the stock.
              </div>

              <button className="btn" style={{ marginTop: 4 }} onClick={goToOrders}>
                Build an order sheet →
              </button>
            </>
          )}
        </div>
      )}
    </>
  )
}
