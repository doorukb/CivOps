import { useState } from 'react'
import { compareScenarios } from './api'
import type {
  ComparisonMetric,
  ComparisonResult,
  SimulationConfig,
  MetricBand,
} from './api'

// "Today's schedule": a fixed reference, not an input.
const BASELINE: SimulationConfig = {
  start_hour: 8,
  end_hour: 16,
  teams: 3,
  average_duration_minutes: 60,
  include_weekends: false,
  include_noise_complaints: false,
}

const STRESS_TEST = { teams: 1, average_duration_minutes: 180 }

type Format = (value: number) => string

const count: Format = (v) => v.toFixed(1)
const percent: Format = (v) => `${(v * 100).toFixed(1)}%`

const ROWS: { key: ComparisonMetric; label: string; format: Format }[] = [
  { key: 'calls_per_week', label: 'Calls per week', format: count },
  { key: 'share_handled', label: 'Share of eligible calls CRESS could take', format: percent },
  { key: 'missed_off_duty', label: 'Missed: off duty', format: count },
  { key: 'missed_busy', label: 'Missed: every team busy', format: count },
  { key: 'utilization', label: 'Utilization', format: percent },
]

// Differences between percentages are percentage points, not percent.
const points: Format = (v) => `${(v * 100).toFixed(1)} pts`

function spreadText({ mean, p10, p90 }: MetricBand, format: Format, signed = false) {
  const shown = format(mean)
  const sign = signed && mean > 0 && parseFloat(shown) > 0 ? '+' : ''
  return `${sign}${shown} (${format(p10)} to ${format(p90)})`
}

export default function WhatIfSimulator() {
  const [config, setConfig] = useState<SimulationConfig>({
    ...BASELINE,
    end_hour: 20,
  })
  const [result, setResult] = useState<ComparisonResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid =
    Number.isInteger(config.start_hour) && config.start_hour >= 0 && config.start_hour <= 23 &&
    Number.isInteger(config.end_hour) && config.end_hour > config.start_hour && config.end_hour <= 24 &&
    Number.isInteger(config.teams) && config.teams >= 1 && config.teams <= 20 &&
    Number.isInteger(config.average_duration_minutes) &&
    config.average_duration_minutes >= 5 && config.average_duration_minutes <= 240

  async function run(scenario: SimulationConfig) {
    setLoading(true)
    setError(null)

    try {
      setResult(await compareScenarios(BASELINE, scenario))
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  function stressTest() {
    const stressed = { ...config, ...STRESS_TEST }
    setConfig(stressed)
    run(stressed)
  }

  const weeks = result?.horizon_weeks ?? 4
  const change = result?.difference.calls_per_week
  const scenario = result?.scenario

  return (
    <div className="panel">
      <h3>Operational Scenario Modeling</h3>
      <p>
        Change CRESS's hours or staffing to see how many more calls it could
        take in a model fed with synthetic calls.
      </p>

      <p className="disclaimer">
        Illustrative scenario only. Not a forecast of actual demand. Today's
        schedule is shown as a ceiling, not what dispatch sends today.
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
          Minutes per Call
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

        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={config.include_noise_complaints}
            onChange={(e) =>
              setConfig({
                ...config,
                include_noise_complaints: e.target.checked,
              })
            }
          />
          Add noise complaints
        </label>
      </div>

      <div className="extraction-actions">
        <button
          className="primary-button"
          onClick={() => run(config)}
          disabled={loading || !valid}
        >
          {loading ? 'Simulating...' : 'Run Scenario'}
        </button>

        <button
          className="secondary-button"
          onClick={stressTest}
          disabled={loading || !valid}
          title="Sets 1 team and 180 minutes per call"
        >
          Stress test: 1 team, 180 min
        </button>
      </div>

      {!valid && (
        <p className="error">
          Check the inputs: end hour must be after start hour, teams 1–20,
          minutes per call 5–240.
        </p>
      )}
      {error && <p className="error">{error}</p>}

      {result && change && scenario && (
        <>
          <div className="impact-summary">
            <strong>
              {change.mean >= 0
                ? `+${change.mean.toFixed(1)} more`
                : `${Math.abs(change.mean).toFixed(1)} fewer`}{' '}
              calls CRESS could take per week
            </strong>
            <span>
              Range {change.p10.toFixed(1)} to {change.p90.toFixed(1)} (p10 to
              p90 across {result.replications} simulated {weeks}-week runs)
            </span>
          </div>

          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Today's schedule (ceiling)</th>
                  <th>Proposed</th>
                  <th>Change</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map(({ key, label, format }) => (
                  <tr key={key}>
                    <td>
                      {label}
                      {key.startsWith('missed') && ` (per ${weeks} weeks)`}
                    </td>
                    <td>{spreadText(result.baseline[key], format)}</td>
                    <td>{spreadText(result.scenario[key], format)}</td>
                    <td>
                      {spreadText(
                        result.difference[key],
                        format === percent ? points : format,
                        true
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="disclaimer">
            Each cell is the mean, with p10 to p90 in parentheses.
          </p>

          <p>
            {scenario.missed_busy.mean >= 0.5
              ? `In this model, about ${scenario.missed_busy.mean.toFixed(1)} calls per ${weeks} weeks arrived while every team was busy. `
              : `In this model, teams were busy for only ${percent(scenario.utilization.mean)} of scheduled time, so few calls were missed for lack of a team. `}
            CRESS's other work is not included, so real availability would be
            lower.
          </p>

          <h3>Assumptions</h3>
          <ul className="assumptions">
            {result.assumptions.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
