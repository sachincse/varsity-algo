// All calls are same-origin and relative. Vite proxies /api to FastAPI in dev;
// FastAPI serves this build and answers /api itself in production. Same URLs
// either way, so there is nothing to configure per environment.

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch (e) {
    throw new Error(
      'Could not reach the backend. Is it running? Start it with ' +
      '`python -m uvicorn server.main:app --reload --port 8000` from the ' +
      'project root.'
    )
  }

  const text = await res.text()
  let body
  try {
    body = text ? JSON.parse(text) : {}
  } catch {
    throw new Error(`Backend returned non-JSON (HTTP ${res.status}): ${text.slice(0, 300)}`)
  }

  if (!res.ok) {
    const detail = body.detail
    if (typeof detail === 'string') throw new Error(detail)
    if (Array.isArray(detail)) {
      throw new Error(detail.map(d => `${(d.loc || []).join('.')}: ${d.msg}`).join('; '))
    }
    throw new Error(`HTTP ${res.status}`)
  }
  return body
}

const post = (path, body) =>
  request(path, { method: 'POST', body: JSON.stringify(body ?? {}) })

export const api = {
  health: () => request('/api/health'),
  config: () => request('/api/config'),

  kiteStatus: () => request('/api/kite/status'),
  kiteLoginUrl: () => request('/api/kite/login-url'),
  kiteLogin: (request_token) => post('/api/kite/login', { request_token }),
  kiteLogout: () => post('/api/kite/logout'),
  holdings: () => request('/api/kite/holdings'),
  margins: () => request('/api/kite/margins'),

  providers: () => request('/api/llm/providers'),
  defaultStrategy: () => request('/api/llm/default'),
  strategyFromText: (text, provider, model) =>
    post('/api/llm/strategy', { text, provider, model }),

  scan: (spec, opts = {}) => post('/api/scan', { spec, ...opts }),
  scanStart: (spec, opts = {}) => post('/api/scan/start', { spec, ...opts }),
  scanStatus: (id) => request(`/api/scan/status/${id}`),

  // Kick off a scan and poll until it finishes, reporting progress as it goes.
  // A cold first run downloads hundreds of symbols; a spinner with no numbers
  // is indistinguishable from a hang.
  async scanWithProgress(spec, opts = {}, onProgress = () => {}) {
    const { job_id } = await this.scanStart(spec, opts)
    for (;;) {
      await new Promise(r => setTimeout(r, 700))
      const s = await this.scanStatus(job_id)
      onProgress(s)
      if (s.state === 'done') return s.result
      if (s.state === 'error') throw new Error(s.error)
    }
  },

  tradeStatus: () => request('/api/trade/status'),
  preview: (payload) => post('/api/trade/preview', payload),
  place: (payload) => post('/api/trade/place', payload),
  orderStatus: (id) => request(`/api/trade/order/${encodeURIComponent(id)}`),
}
