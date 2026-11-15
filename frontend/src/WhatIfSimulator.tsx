import { useState } from 'react'
import { runSimulation } from './api'
import type {
  SimulationConfig,
  SimulationResult,
  SimulationIncident,
} from './api'

const demoIncidents: SimulationIncident[] = [
  10, 10, 11, 12, 14, 15, 17, 18, 19
].map((hour, index) => ({
  call_type: 'wellbeing_check',
  weapon_present: false,
  violence: false,
  injury: false,
  immediate_danger: false,
  timestamp: `2026-11-16T${String(hour).padStart(2, '0')}:${index % 2 === 0 ? '00' : '15'}:00-05:00`,
}))

export default function WhatIfSimulator() {
  const [config, setConfig] = useState<SimulationConfig>({
    start_hour: 8,
    end_hour: 16,
    teams: 2,
    average_duration_minutes: 60,
    include_weekends: false,
  })

  const [baseline, setBaseline] = useState<SimulationResult | null>(null)
  const [scenario, setScenario] = useState<SimulationResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function simulate() {
  setLoading(true)
  setError(null)
  setBaseline(null)
  setScenario(null)

  try {
    const baselineConfig: SimulationConfig = {
      start_hour: 8,
      end_hour: 16,
      teams: 2,
      average_duration_minutes: 60,
      include_weekends: false,
    }

    const [baselineData, scenarioData] = await Promise.all([
      runSimulation(baselineConfig, demoIncidents),
      runSimulation(config, demoIncidents),
    ])

    setBaseline(baselineData)
    setScenario(scenarioData)
  } catch (err) {
    setError(err instanceof Error ? err.message : 'Unknown error')
  } finally {
    setLoading(false)
  }
}

  return (
    <div className="panel">
      <h3>Operational Scenario Modeling</h3>
      <p>
        Adjust staffing and operating hours to see how CRESS
        might handle a synthetic set of incoming calls.
      </p>

      <p className="disclaimer">
        Illustrative scenario only. Not a forecast of actual demand.
      </p>

      <div className="form-grid">
        <label>
          Start Hour
          <input
            type="number"
            min={0}
            max={23}
            value={config.start_hour}
            onChange={(e) =>
              setConfig({ ...config, start_hour: Number(e.target.value) })
            }
          />
        </label>

        <label>
          End Hour
          <input
            type="number"
            min={1}
            max={24}
            value={config.end_hour}
            onChange={(e) =>
              setConfig({ ...config, end_hour: Number(e.target.value) })
            }
          />
        </label>

        <label>
          Responder Teams
          <input
            type="number"
            min={1}
            max={20}
            value={config.teams}
            onChange={(e) =>
              setConfig({ ...config, teams: Number(e.target.value) })
            }
          />
        </label>

        <label>
          Average Response Duration (min)
          <input
            type="number"
            min={5}
            max={240}
            value={config.average_duration_minutes}
            onChange={(e) =>
              setConfig({
                ...config,
                average_duration_minutes: Number(e.target.value),
              })
            }
          />
        </label>

        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={config.include_weekends}
            onChange={(e) =>
              setConfig({ ...config, include_weekends: e.target.checked })
            }
          />
          Include Weekends
        </label>
      </div>

      <button
        className="primary-button"
        onClick={simulate}
        disabled={loading || config.end_hour <= config.start_hour}
      >
        {loading ? 'Simulating...' : 'Run Scenario'}
      </button>

      {error && <p className="error">{error}</p>}

      {baseline && scenario && (
  <>
    <div className="comparison-grid">
      <div className="comparison-card">
        <h3>Baseline</h3>
        <p>8 AM–4 PM · 2 Teams</p>

        <div className="comparison-value">
          {baseline.handled_calls}
        </div>

        <span>Calls Handled</span>

        <p>
          Off duty: {baseline.missed_off_duty}
          <br />
          Busy: {baseline.missed_busy}
          <br />
          Utilization: {(baseline.utilization * 100).toFixed(1)}%
        </p>
      </div>

      <div className="comparison-card highlighted">
        <h3>Proposed Scenario</h3>
        <p>
          {config.start_hour}:00–{config.end_hour}:00 · {config.teams} Teams
        </p>

        <div className="comparison-value">
          {scenario.handled_calls}
        </div>

        <span>Calls Handled</span>

        <p>
          Off duty: {scenario.missed_off_duty}
          <br />
          Busy: {scenario.missed_busy}
          <br />
          Utilization: {(scenario.utilization * 100).toFixed(1)}%
        </p>
      </div>
    </div>

    <div className="impact-summary">
      <h3>Scenario Impact</h3>
      <strong>
        {scenario.handled_calls - baseline.handled_calls >= 0 ? '+' : ''}
        {scenario.handled_calls - baseline.handled_calls}
      </strong>
      <span>Change in calls handled</span>
    </div>
  </>
)}
    </div>
  )
}