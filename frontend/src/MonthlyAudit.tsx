import { Fragment, useState } from 'react'
import { fetchDemoAudit, runAudit } from './api'
import type { AuditGroup, AuditResponse, AuditResult } from './api'
import {
  GROUPS,
  GROUP_LABELS,
  MAX_UPLOAD_RECORDS,
  groupsOf,
  pageCount,
  pageOf,
  parseRecords,
  recordedTime,
  toCsv,
  visibleRecords,
} from './auditLogic'
import { AuditGroupsChart, CallsByHourChart } from './charts'

const LINE_LABELS: Record<string, string> = {
  '911': '911',
  non_emergency: 'non-emergency line',
  unknown: 'line not recorded',
}

function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export default function MonthlyAudit() {
  const [data, setData] = useState<AuditResponse | null>(null)
  const [origin, setOrigin] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [count, setCount] = useState(250)
  const [seed, setSeed] = useState(42)

  const [group, setGroup] = useState<AuditGroup | null>(null)
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<string | null>(null)

  const inputsValid =
    Number.isInteger(count) && count >= 1 && count <= 5000 &&
    Number.isInteger(seed) && seed >= 0

  async function load(what: string, job: () => Promise<AuditResponse>) {
    setLoading(true)
    setError(null)

    try {
      setData(await job())
      setOrigin(what)
      setGroup(null)
      setPage(0)
      setOpen(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  async function upload(file: File | undefined) {
    if (!file) return
    await load(`your file ${file.name}`, async () =>
      runAudit(parseRecords(await file.text(), file.name))
    )
  }

  function choose(next: AuditGroup | null) {
    setGroup(next)
    setPage(0)
    setOpen(null)
  }

  const summary = data?.summary
  const windowLabel = summary?.review_window.label ?? ''
  const records = data ? visibleRecords(data.results, group) : []
  const pages = pageCount(records.length)
  const shown = pageOf(records, page)

  const label = (g: AuditGroup) =>
    g === 'eligible_after_hours'
      ? `Eligible, off duty, ${windowLabel}`
      : GROUP_LABELS[g]

  return (
    <div className="panel">
      <h3>Monthly Dispatch Review</h3>
      <p>
        Replay a month of dispatch records through the Despatch rulebook and
        sort them into the four groups a monthly review looks at.
      </p>

      <div className="form-grid">
        <label>
          Synthetic calls
          <input
            type="number"
            min={1}
            max={5000}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
          />
        </label>

        <label>
          Seed
          <input
            type="number"
            min={0}
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
            aria-describedby="seed-hint"
          />
          <span className="hint" id="seed-hint">
            Same seed, same month.
          </span>
        </label>
      </div>

      <div className="extraction-actions">
        <button
          className="primary-button"
          onClick={() =>
            load('the synthetic month', () => fetchDemoAudit(count, seed))
          }
          disabled={loading || !inputsValid}
        >
          {loading ? 'Running Audit...' : 'Run Synthetic Audit'}
        </button>

        <label className="secondary-button file-button">
          Audit your own file (JSON or CSV)
          <input
            type="file"
            accept=".json,.csv,application/json,text/csv"
            disabled={loading}
            onChange={(e) => {
              void upload(e.target.files?.[0])
              e.target.value = '' // let the same file be chosen again
            }}
          />
        </label>
      </div>

      <p className="hint">
        Your own file: up to {MAX_UPLOAD_RECORDS.toLocaleString()} records with
        call_id, actual_destination, call_type, timestamp (with a UTC offset)
        and the four screening answers. Synthetic or de-identified data only.
        The file is replayed and not stored.
      </p>

      {!inputsValid && (
        <p className="error" role="alert">
          Calls must be 1 to 5,000 and the seed a whole number of 0 or more.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {data && summary && (
        <>
          <p className="disclaimer">
            {data.dataset ? (
              <>
                Synthetic demonstration data. {data.dataset.arrival_pattern}{' '}
                The &ldquo;actual dispatch&rdquo; outcomes shown here are
                invented for the demonstration, not real dispatch records.
              </>
            ) : (
              <>
                Showing {origin}. The recommendations come from an
                illustrative rulebook, not an official protocol.
              </>
            )}{' '}
            Rulebook v{summary.rulebook_version}.
          </p>

          <div
            className="metric-grid"
            role="group"
            aria-label="Filter the table by review group"
          >
            <button
              type="button"
              className={`metric ${group === null ? 'selected' : ''}`}
              aria-pressed={group === null}
              onClick={() => choose(null)}
            >
              <span>All calls</span>
              <strong>{summary.total_calls}</strong>
            </button>

            {GROUPS.map((g) => (
              <button
                key={g}
                type="button"
                className={`metric ${group === g ? 'selected' : ''}`}
                aria-pressed={group === g}
                onClick={() => choose(group === g ? null : g)}
              >
                <span>{label(g)}</span>
                <strong>{summary[g]}</strong>
              </button>
            ))}
          </div>

          <p className="read-only-line">
            The after-hours group covers {windowLabel},{' '}
            {summary.review_window.days}: the four hours after the rulebook's
            shift ends.
            {summary.could_have_gone_to_cress > 0 && (
              <>
                {' '}Of the {summary.could_have_gone_to_cress} calls that could
                have gone to CRESS:{' '}
                {Object.entries(summary.could_have_gone_by_line)
                  .map(([line, n]) => `${n} on ${LINE_LABELS[line] ?? line}`)
                  .join(', ')}
                {' '}(shown for context; no rule reads the line).
              </>
            )}
          </p>

          <div className="chart-row">
            <AuditGroupsChart results={data.results} windowLabel={windowLabel} />
            <CallsByHourChart results={data.results} />
          </div>

          <div className="table-heading">
            <h3>
              {group ? label(group) : 'All records'} ({records.length})
            </h3>
            <button
              type="button"
              className="secondary-button"
              onClick={() =>
                download(
                  `despatch-audit${group ? `-${group}` : ''}.csv`,
                  toCsv(records)
                )
              }
              disabled={records.length === 0}
            >
              Download CSV
            </button>
          </div>

          <div className="table-container">
            <table>
              <caption>
                {group ? label(group) : 'Every record, flagged first'}. Open a
                row to see why the rulebook recommended what it did.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Call ID</th>
                  <th scope="col">Actual</th>
                  <th scope="col">Recommended</th>
                  <th scope="col">Rule</th>
                  <th scope="col">Group</th>
                </tr>
              </thead>

              <tbody>
                {shown.map((record: AuditResult) => (
                  <Fragment key={record.call_id}>
                    <tr>
                      <td>
                        <button
                          type="button"
                          className="row-toggle"
                          aria-expanded={open === record.call_id}
                          onClick={() =>
                            setOpen(
                              open === record.call_id ? null : record.call_id
                            )
                          }
                        >
                          {open === record.call_id ? '▾' : '▸'} {record.call_id}
                        </button>
                      </td>
                      <td>{record.actual_destination}</td>
                      <td>{record.recommended_destination}</td>
                      <td>{record.rule_id}</td>
                      <td>
                        {groupsOf(record).map(label).join(', ') || '—'}
                      </td>
                    </tr>
                    {open === record.call_id && (
                      <tr className="row-detail">
                        <td colSpan={5}>
                          <strong>{record.reason}</strong>
                          <br />
                          Source: {record.source ?? 'not given'}
                          <br />
                          {recordedTime(record.timestamp)} ·{' '}
                          {record.call_type?.replaceAll('_', ' ') ??
                            'call type unknown'}{' '}
                          ·{' '}
                          {LINE_LABELS[record.source_line ?? 'unknown']}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
                {shown.length === 0 && (
                  <tr>
                    <td colSpan={5}>No records in this group.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {pages > 1 && (
            <nav className="pager" aria-label="Table pages">
              <button
                type="button"
                className="secondary-button"
                onClick={() => setPage(page - 1)}
                disabled={page === 0}
              >
                ← Previous
              </button>
              <span role="status" aria-live="polite">
                Page {page + 1} of {pages}
              </span>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setPage(page + 1)}
                disabled={page >= pages - 1}
              >
                Next →
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  )
}
