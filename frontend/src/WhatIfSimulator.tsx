import { useEffect, useState } from 'react'
import { compareScenarios, fetchBaseline, fetchCoverage } from './api'
import type {
  ComparisonMetric,
  ComparisonResult,
  CoveragePoint,
  MetricBand,
  SimulationBaseline,
  SimulationConfig,
} from './api'
import { clockLabel } from './chartData'
import { ComparisonChart, CoverageChart } from './charts'
import {
  FALLBACK_BASELINE,
  MAX_END_HOUR,
  scenarioProblem,
} from './simulatorLogic'

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

function scheduleText(config: SimulationConfig): string {
  const days = config.include_weekends ? 'every day' : 'weekdays'
  const next = config.end_hour > 24 ? ' the next day' : ''
  return `${days}, ${clockLabel(config.start_hour)} to ${clockLabel(config.end_hour)}${next}`
}

export default function WhatIfSimulator() {
  // "Today's schedule" comes from the rulebook via the API, not from a copy here.
  const [reference, setReference] = useState<SimulationBaseline | null>(null)
  const baseline = reference?.baseline ?? FALLBACK_BASELINE

  const [config, setConfig] = useState<SimulationConfig>({
    ...FALLBACK_BASELINE,
    end_hour: 20,
  })
  const [result, setResult] = useState<ComparisonResult | null>(null)
  const [coverage, setCoverage] = useState<CoveragePoint[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchBaseline()
      .then((loaded) => {
        if (!cancelled) setReference(loaded)
      })
      .catch(() => {}) // keep the fallback; Run still reports a real error
    return () => {
      cancelled = true
    }
  }, [])

  const problem = scenarioProblem(config)
  const { start_hour: startHour, include_weekends: weekends } = config
  const startValid = Number.isInteger(startHour) && startHour >= 0 && startHour <= 23

  useEffect(() => {
    if (!startValid) return
    let cancelled = false
    fetchCoverage(startHour, weekends)
      .then((loaded) => {
        if (!cancelled) setCoverage(loaded)
      })
      .catch(() => {
        if (!cancelled) setCoverage([])
      })
    return () => {
      cancelled = true
    }
  }, [startHour, weekends, startValid])

  async function run(scenario: SimulationConfig) {
    setLoading(true)
    setError(null)

    try {
      setResult(await compareScenarios(baseline, scenario))
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  function apply(next: SimulationConfig) {
    setConfig(next)
    void run(next)
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
        schedule ({scheduleText(baseline)}, {baseline.teams} teams) is shown
        as a ceiling, not what dispatch sends today.
      </p>

      {reference && reference.presets.length > 0 && (
        <div className="scenario-buttons">
          <span>Scenarios:</span>
          {reference.presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className="secondary-button"
              title={`${preset.note} Covers about ${percent(preset.schedule_coverage)} of arrivals.`}
              onClick={() => apply({ ...baseline, ...preset.config })}
              disabled={loading}
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}

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
            max={MAX_END_HOUR}
            value={config.end_hour}
            onChange={(e) =>
              setConfig({ ...config, end_hour: Number(e.target.value) })
            }
            aria-describedby="end-hour-hint"
          />
          <span className="hint" id="end-hour-hint">
            Up to {MAX_END_HOUR}: 24 is midnight, 26 is 2 AM the next day.
          </span>
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
            checked={config.include_noise_complaints ?? false}
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
          disabled={loading || !!problem}
        >
          {loading ? 'Simulating...' : 'Run Scenario'}
        </button>

        <button
          className="secondary-button"
          onClick={() => apply({ ...config, ...STRESS_TEST })}
          disabled={loading || !!problem}
          title="Sets 1 team and 180 minutes per call"
        >
          Stress test: 1 team, 180 min
        </button>
      </div>

      {problem && (
        <p className="error" role="alert">
          {problem}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {coverage.length > 1 && (
        <CoverageChart
          points={coverage}
          todayEnd={baseline.end_hour}
          proposedEnd={config.end_hour}
        />
      )}

      {result && change && scenario && (
        <>
          <div className="impact-summary" role="status" aria-live="polite">
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

          <ComparisonChart result={result} />

          <div className="table-container">
            <table>
              <caption>
                Today's schedule against the proposed one. Each cell is the
                mean, with p10 to p90 in parentheses.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  <th scope="col">Today's schedule (ceiling)</th>
                  <th scope="col">Proposed</th>
                  <th scope="col">Change</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map(({ key, label, format }) => (
                  <tr key={key}>
                    <th scope="row">
                      {label}
                      {key.startsWith('missed') && ` (per ${weeks} weeks)`}
                    </th>
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
