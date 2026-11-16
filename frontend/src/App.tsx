import { Suspense, lazy, useState } from 'react'
import './App.css'
import LiveCall from './LiveCall'

// The two screens with charts load on demand, so the Live Call screen (the
// one a demo opens on) does not wait for the charting library.
const MonthlyAudit = lazy(() => import('./MonthlyAudit'))
const WhatIfSimulator = lazy(() => import('./WhatIfSimulator'))

type Page = 'live' | 'audit' | 'simulation'

const PAGES: { id: Page; nav: string; title: string }[] = [
  { id: 'live', nav: 'Live Call', title: 'Live Call Copilot' },
  { id: 'audit', nav: 'Monthly Audit', title: 'Monthly Dispatch Audit' },
  { id: 'simulation', nav: 'What-If Simulator', title: 'What-If Simulator' },
]

function App() {
  const [page, setPage] = useState<Page>('live')
  const current = PAGES.find((entry) => entry.id === page) ?? PAGES[0]

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <aside className="sidebar">
        <div className="brand">
          <h1>CivOps</h1>
          <p>Civic Response Intelligence</p>
        </div>

        <nav aria-label="Screens">
          {PAGES.map((entry) => (
            <button
              key={entry.id}
              className={page === entry.id ? 'active' : ''}
              aria-current={page === entry.id ? 'page' : undefined}
              onClick={() => setPage(entry.id)}
            >
              {entry.nav}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          Synthetic demonstration only. Not a 911 system and not an official
          Amherst or CRESS tool.
        </div>
      </aside>

      <main className="main-content" id="main">
        <header className="topbar">
          <span>CIVOPS / OPERATIONS</span>
          <span className="status">● Prototype Environment</span>
        </header>

        <section className="page-content" aria-labelledby="page-title">
          <h2 id="page-title">{current.title}</h2>

          {page === 'live' && <LiveCall />}

          <Suspense fallback={<p role="status">Loading…</p>}>
            {page === 'audit' && <MonthlyAudit />}

            {page === 'simulation' && <WhatIfSimulator />}
          </Suspense>
        </section>
      </main>
    </div>
  )
}

export default App
