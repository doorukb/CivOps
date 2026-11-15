import { useState } from 'react'
import './App.css'
import MonthlyAudit from './MonthlyAudit'
import WhatIfSimulator from './WhatIfSimulator'
import LiveCall from './LiveCall'

type Page = 'live' | 'audit' | 'simulation'

function App() {
  const [page, setPage] = useState<Page>('live')

  const titles = {
    live: 'Live Call Copilot',
    audit: 'Monthly Dispatch Audit',
    simulation: 'What-If Simulator',
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <h1>CivOps</h1>
          <p>Civic Response Intelligence</p>
        </div>

        <nav>
          <button
            className={page === 'live' ? 'active' : ''}
            onClick={() => setPage('live')}
          >
            Live Call
          </button>

          <button
            className={page === 'audit' ? 'active' : ''}
            onClick={() => setPage('audit')}
          >
            Monthly Audit
          </button>

          <button
            className={page === 'simulation' ? 'active' : ''}
            onClick={() => setPage('simulation')}
          >
            What-If Simulator
          </button>
        </nav>

        <div className="sidebar-footer">
          Synthetic demonstration only
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <span>CIVOPS / OPERATIONS</span>
          <span className="status">● Prototype Environment</span>
        </header>

        <section className="page-content">
          <h2>{titles[page]}</h2>

          {page === 'live' && <LiveCall />}

          {page === 'audit' && <MonthlyAudit />}

          {page === 'simulation' && <WhatIfSimulator />}
        </section>
      </main>
    </div>
  )
}

export default App