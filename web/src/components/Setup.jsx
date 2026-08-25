

// Settings. The Kite login moved to its own Connect tab, mirroring the video.
export default function Setup({ config }) {
  if (!config) return <div className="panel"><p className="muted">Loading…</p></div>

  const llm = config.llm

  return (
    <>
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
          SMA 6/30 rule built in, and the Signals tab lets you change the
          numbers by hand.
        </p>
      </div>

      <div className="panel">
        <h2>Price data</h2>
        <p className="sub">
          Currently using <strong>{config.price_source || 'automatic'}</strong>.
        </p>
        <ul className="notes">
          <li>
            <strong>Kite</strong> — your broker's own candles, matching the chart
            you see in Kite, and the only source that supports intraday
            intervals. Used automatically once you connect. Needs the ₹500/month
            Kite Connect subscription.
          </li>
          <li>
            <strong>Yahoo</strong> — free, end-of-day, no subscription. Used when
            you are not connected, so the scanner works before you have paid for
            anything.
          </li>
        </ul>
        <p className="muted" style={{ marginTop: 14 }}>
          Force one with <code>PRICE_SOURCE=kite</code> or{' '}
          <code>PRICE_SOURCE=yfinance</code> in <code>.env</code>. Leave it blank
          to switch automatically.
        </p>
      </div>

      <div className="panel">
        <h2>Order placement</h2>
        <p className="sub">
          {config.trading_enabled
            ? 'ARMED — the Orders tab can send real orders to the exchange.'
            : 'Disabled. Preview works; nothing can be sent.'}
        </p>
        <p className="muted">
          Controlled by <code>ENABLE_TRADING</code> in <code>.env</code>. Even
          when armed, every order needs its own preview token and a typed
          confirmation, and orders go one at a time.
        </p>
      </div>
    </>
  )
}
