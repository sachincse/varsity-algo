import { useEffect, useState } from 'react'
import { api } from '../api'

// The signals tab from the video: short SMA, long SMA, lookback and max, a
// button, and a table ranked by how recently each crossover fired — showing
// the close alongside both moving averages so a signal can be checked by eye.
//
// The four controls edit the strategy spec directly. If the spec came from the
// language model and is not a plain moving-average crossover, the controls
// step aside rather than pretending to describe it.

const UNIVERSES = ['nifty50', 'nifty100', 'nifty200', 'nifty500']

function readCross(spec) {
  const e = spec?.entry
  if (e?.type !== 'crossover') return null
  const L = e.left, R = e.right
  if (L?.kind !== 'sma' || R?.kind !== 'sma') return null
  return { short: L.period, long: R.period }
}

export default function Signals({ spec, summary, scan, onScan, onSpec, goToOrders }) {
  const cross = readCross(spec)
  const [shortMa, setShortMa] = useState(cross?.short ?? 6)
  const [longMa, setLongMa] = useState(cross?.long ?? 30)
  const [lookback, setLookback] = useState(spec?.lookback_bars ?? 15)
  const [maxRows, setMaxRows] = useState(spec?.max_signals ?? 100)
  const [universe, setUniverse] = useState(spec?.universe ?? 'nifty100')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [refresh, setRefresh] = useState(false)
  const [prog, setProg] = useState(null)

  useEffect(() => {
    const c = readCross(spec)
    if (c) { setShortMa(c.short); setLongMa(c.long) }
    if (spec?.lookback_bars) setLookback(spec.lookback_bars)
    if (spec?.max_signals) setMaxRows(spec.max_signals)
    if (spec?.universe) setUniverse(spec.universe)
  }, [spec])

  function buildSpec() {
    if (!spec) return null
    const next = { ...spec, lookback_bars: Number(lookback),
                   max_signals: Number(maxRows), universe }
    if (cross) {
      const s = Number(shortMa), l = Number(longMa)
      next.entry = { type: 'crossover', direction: 'above',
                     left: { kind: 'sma', period: s },
                     right: { kind: 'sma', period: l } }
      next.exit = { type: 'crossover', direction: 'below',
                    left: { kind: 'sma', period: s },
                    right: { kind: 'sma', period: l } }
      next.name = `SMA ${s}/${l} crossover`
    }
    return next
  }

  async function run() {
    if (!spec) { setErr('Pick a strategy on the Strategy tab first.'); return }
    if (cross && Number(shortMa) >= Number(longMa)) {
      setErr('The short average must be shorter than the long one — otherwise '
             + 'it can never cross up through it.'); return
    }
    setBusy(true); setErr(''); setProg(null)
    const next = buildSpec()
    try {
      const result = await api.scanWithProgress(next, { refresh }, setProg)
      onScan(result)
      if (onSpec) onSpec(result.spec, result.summary)
    } catch (e) { setErr(e.message) } finally { setBusy(false); setProg(null) }
  }

  return (
    <>
      <div className="panel">
        <h2>Signals</h2>
        <p className="sub">
          {summary ? summary.split('\n')[0] : 'No strategy selected yet.'}
        </p>

        <div className="row">
          {cross && (
            <>
              <div style={{ minWidth: 118 }}>
                <label htmlFor="sm">Short SMA</label>
                <input id="sm" type="number" min="1" max="400" value={shortMa}
                       onChange={e => setShortMa(e.target.value)} />
              </div>
              <div style={{ minWidth: 118 }}>
                <label htmlFor="lm">Long SMA</label>
                <input id="lm" type="number" min="2" max="400" value={longMa}
                       onChange={e => setLongMa(e.target.value)} />
              </div>
            </>
          )}
          <div style={{ minWidth: 118 }}>
            <label htmlFor="lb">Lookback</label>
            <input id="lb" type="number" min="1" max="250" value={lookback}
                   onChange={e => setLookback(e.target.value)} />
          </div>
          <div style={{ minWidth: 110 }}>
            <label htmlFor="mx">Max rows</label>
            <input id="mx" type="number" min="1" max="500" value={maxRows}
                   onChange={e => setMaxRows(e.target.value)} />
          </div>
          <div style={{ minWidth: 130 }}>
            <label htmlFor="uv">Universe</label>
            <select id="uv" value={universe} onChange={e => setUniverse(e.target.value)}>
              {UNIVERSES.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <button className="btn" onClick={run} disabled={busy || !spec}>
            {busy ? 'Scanning…' : 'Generate signals'}
          </button>
        </div>

        {!cross && spec && (
          <p className="muted" style={{ marginTop: 12 }}>
            This strategy is not a plain moving-average crossover, so the SMA
            boxes are hidden. Edit it on the Strategy tab.
          </p>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 7,
                        textTransform: 'none', letterSpacing: 0, fontWeight: 400,
                        fontSize: 13.5, color: 'var(--ink-2)', marginTop: 14 }}>
          <input type="checkbox" checked={refresh} style={{ width: 'auto' }}
                 onChange={e => setRefresh(e.target.checked)} />
          re-download prices (slower)
        </label>

        {busy && (
          <div style={{ marginTop: 16 }}>
            <div className="bar"><div className="bar-fill" style={{
              width: prog?.percent != null ? prog.percent + '%' : '100%',
              animation: prog?.percent == null ? 'pulse 1.2s ease-in-out infinite' : 'none',
            }} /></div>
            <p className="muted" style={{ marginTop: 8 }}>
              {prog?.message || 'starting…'}
              {prog?.percent != null ? ` — ${prog.percent}%` : ''}
              {prog?.elapsed != null ? ` · ${Math.round(prog.elapsed)}s` : ''}
            </p>
            <p className="muted" style={{ marginTop: 4, fontSize: 12.5 }}>
              The first run downloads every symbol in the universe and takes a
              few minutes. After that it is cached and near-instant.
            </p>
          </div>
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

          {scan.source === 'yfinance' && (
            <div className="msg info">
              Prices are from the free Yahoo end-of-day feed. Connect Zerodha and
              they come from Kite instead, matching your broker's own chart —
              which is what the video does.
            </div>
          )}

          {scan.dropped > 0 && (
            <div className="msg warn">
              <strong>Showing {scan.shown} of {scan.total} signals.</strong>{' '}
              {scan.dropped} more were found and are not listed, because Max rows
              is set to {scan.max_signals}. The Entries and Exits counts above
              are for all {scan.total}, and the order sheet only sees what is
              listed here.
            </div>
          )}

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
              failure — widen the lookback, or wait for the market to move.
            </p>
          ) : (
            <>
              <div className="tw">
                <table>
                  <thead>
                    <tr>
                      <th>Symbol</th><th>Signal</th><th>Crossover date</th>
                      <th className="n">Bars ago</th><th className="n">Close</th>
                      <th className="n">{scan.signals[0]?.left_label || 'fast'}</th>
                      <th className="n">{scan.signals[0]?.right_label || 'slow'}</th>
                      <th className="n">Turnover</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scan.signals.map(s => (
                      <tr key={`${s.symbol}-${s.side}`}
                          className={s.bars_since === 0 ? 'fresh' : ''}>
                        <td><strong>{s.symbol}</strong></td>
                        <td>
                          <span className={`tag ${s.side === 'ENTRY' ? 'entry' : 'exit'}`}>
                            {s.side === 'ENTRY' ? 'BULLISH' : 'BEARISH'}
                          </span>
                        </td>
                        <td className="mono">{s.signal_date}</td>
                        <td className="n">{s.bars_since}</td>
                        <td className="n">{s.price?.toLocaleString('en-IN',
                          { minimumFractionDigits: 2 })}</td>
                        <td className="n">{s.left_value?.toLocaleString('en-IN',
                          { minimumFractionDigits: 2 }) ?? '—'}</td>
                        <td className="n">{s.right_value?.toLocaleString('en-IN',
                          { minimumFractionDigits: 2 }) ?? '—'}</td>
                        <td className="n">{s.median_turnover_cr?.toFixed(1)} cr</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="msg warn" style={{ marginTop: 18 }}>
                <strong>A BEARISH row is a sell signal for something you already
                own.</strong> It is not a short. A retail account cannot hold a
                short equity position overnight in India, so half of a crossover
                scanner's output is only actionable if you hold the stock.
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
