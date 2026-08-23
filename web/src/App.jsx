import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import Setup from './components/Setup'
import Strategy from './components/Strategy'
import Signals from './components/Signals'
import Orders from './components/Orders'

const TABS = [
  ['setup', 'Setup'],
  ['strategy', 'Strategy'],
  ['signals', 'Signals'],
  ['orders', 'Orders'],
]

export default function App() {
  const [tab, setTab] = useState('setup')
  const [config, setConfig] = useState(null)
  const [spec, setSpec] = useState(null)
  const [specSummary, setSpecSummary] = useState('')
  const [scan, setScan] = useState(null)
  const [bootError, setBootError] = useState('')

  const refreshConfig = useCallback(async () => {
    try {
      setConfig(await api.config())
      setBootError('')
    } catch (e) {
      setBootError(e.message)
    }
  }, [])

  useEffect(() => {
    refreshConfig()
    api.defaultStrategy()
      .then(d => { setSpec(d.spec); setSpecSummary(d.summary) })
      .catch(() => {})
  }, [refreshConfig])

  const kiteLive = config?.kite?.authenticated
  const tradingOn = config?.trading_enabled

  return (
    <div className="wrap">
      <header>
        <div className="brand">
          <h1>varsity-algo</h1>
          <span className="tagline">
            Nifty crossover scanner &middot; describe it in English, review every order
          </span>
        </div>
        <nav>
          {TABS.map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} aria-current={tab === id}>
              {label}
              {id === 'signals' && scan?.signals?.length
                ? ` (${scan.signals.length})` : ''}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <span className={`pill ${kiteLive ? 'ok' : 'warn'}`}
                style={{ alignSelf: 'center' }}>
            <i className="dot" />
            {kiteLive ? `Kite: ${config.kite.profile?.user_id || 'connected'}`
                      : 'Kite: not connected'}
          </span>
          {tradingOn && (
            <span className="pill no" style={{ alignSelf: 'center' }}>
              <i className="dot" />live orders armed
            </span>
          )}
        </nav>
      </header>

      {bootError && (
        <div className="msg err"><strong>Backend unreachable.</strong> {bootError}</div>
      )}

      {tab === 'setup' && (
        <Setup config={config} onChange={refreshConfig} />
      )}
      {tab === 'strategy' && (
        <Strategy
          config={config}
          spec={spec}
          summary={specSummary}
          onSpec={(s, sum) => { setSpec(s); setSpecSummary(sum); setScan(null) }}
          goToSignals={() => setTab('signals')}
        />
      )}
      {tab === 'signals' && (
        <Signals
          spec={spec}
          summary={specSummary}
          scan={scan}
          onScan={setScan}
          goToOrders={() => setTab('orders')}
        />
      )}
      {tab === 'orders' && (
        <Orders config={config} scan={scan} onConfigChange={refreshConfig} />
      )}
    </div>
  )
}
