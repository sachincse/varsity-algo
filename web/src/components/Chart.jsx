import { useEffect, useRef, useState } from 'react'
import { createChart, CandlestickSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts'
import { api } from '../api'

// Candles for one signal, with the strategy's own two averages drawn over them.
//
// The table already prints close, short SMA and long SMA on every row so a
// crossover can be checked by eye. Reading three numbers and picturing the
// lines crossing is a poor substitute for watching them cross, and the whole
// point of the row is that the signal is verifiable rather than trusted.
//
// The series come from /api/bars, which recomputes them from the same panel
// the scan used. A chart drawn from a second, independent calculation could
// disagree with the row beside it, and then neither would be believable.

const UP = '#4cba8b'
const DOWN = '#e07a68'

export default function Chart({ symbol, short, long, signalDate, side, onClose }) {
  const holder = useRef(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(true)
  const [meta, setMeta] = useState(null)

  useEffect(() => {
    let chart = null
    let cancelled = false
    const ro = { current: null }

    async function draw() {
      setBusy(true); setErr(''); setMeta(null)
      try {
        const d = await api.bars(symbol, { count: 260, short, long })
        if (cancelled || !holder.current) return
        if (!d.bars?.length) { setErr(`No price history for ${symbol}.`); return }

        const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
        chart = createChart(holder.current, {
          autoSize: true,
          layout: {
            background: { color: 'transparent' },
            textColor: dark ? '#9fb0b5' : '#5b686c',
            attributionLogo: false,
          },
          grid: {
            vertLines: { color: dark ? '#222e32' : '#eaeff0' },
            horzLines: { color: dark ? '#222e32' : '#eaeff0' },
          },
          rightPriceScale: { borderVisible: false },
          timeScale: { borderVisible: false, rightOffset: 4 },
          crosshair: { mode: 0 },
        })

        const candles = chart.addSeries(CandlestickSeries, {
          upColor: UP, downColor: DOWN, borderVisible: false,
          wickUpColor: UP, wickDownColor: DOWN,
        })
        candles.setData(d.bars)

        if (d.short?.points?.length) {
          chart.addSeries(LineSeries, { color: '#5aa9dd', lineWidth: 2, priceLineVisible: false, lastValueVisible: false })
            .setData(d.short.points)
        }
        if (d.long?.points?.length) {
          chart.addSeries(LineSeries, { color: '#d0a24e', lineWidth: 2, priceLineVisible: false, lastValueVisible: false })
            .setData(d.long.points)
        }

        // Mark the bar the signal actually fired on, so the chart answers the
        // question the row raised rather than being decoration.
        if (signalDate && d.bars.some(b => b.time === signalDate)) {
          createSeriesMarkers(candles, [{
            time: signalDate,
            position: side === 'EXIT' ? 'aboveBar' : 'belowBar',
            color: side === 'EXIT' ? DOWN : UP,
            shape: side === 'EXIT' ? 'arrowDown' : 'arrowUp',
            text: side === 'EXIT' ? 'exit' : 'entry',
          }])
        }

        chart.timeScale().fitContent()
        setMeta({ source: d.source, bars: d.bars.length })
      } catch (e) {
        if (!cancelled) setErr(e.message)
      } finally {
        if (!cancelled) setBusy(false)
      }
    }

    draw()
    return () => {
      cancelled = true
      ro.current?.disconnect()
      chart?.remove()
    }
  }, [symbol, short, long, signalDate, side])

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>{symbol}</h2>
        <span className="muted" style={{ fontSize: 13 }}>
          <span style={{ color: '#5aa9dd' }}>&#9644;</span> SMA({short}){'  '}
          <span style={{ color: '#d0a24e' }}>&#9644;</span> SMA({long})
          {meta && <> &middot; {meta.bars} bars from {meta.source}</>}
        </span>
        <button className="btn ghost" style={{ marginLeft: 'auto' }} onClick={onClose}>
          Close
        </button>
      </div>

      {err && <div className="msg err" style={{ marginTop: 12 }}>{err}</div>}
      {busy && !err && <p className="muted" style={{ marginTop: 12 }}>Loading bars…</p>}

      <div ref={holder}
           style={{ height: 340, marginTop: 12, display: err ? 'none' : 'block' }} />

      {!err && !busy && (
        <p className="muted" style={{ marginTop: 10, marginBottom: 0, fontSize: 13 }}>
          The arrow marks the bar the crossover fired on. A real entry would
          have filled at the <em>next</em> session's open, never at this bar's
          close.
        </p>
      )}
    </div>
  )
}
