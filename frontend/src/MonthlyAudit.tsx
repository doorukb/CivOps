import { useState } from 'react'
import { fetchDemoAudit } from './api'
import type { AuditResponse, AuditResult } from './api'

// The town's four review groups, as flags on each audit result
const GROUPS: { flag: keyof AuditResult; label: string }[] = [
  { flag: 'sent_to_cress_appropriately', label: 'Sent to CRESS appropriately' },
  { flag: 'could_have_gone_to_cress', label: 'Could have gone to CRESS' },
  { flag: 'should_not_have_gone_to_cress', label: 'Should not have gone to CRESS' },
  { flag: 'eligible_after_hours', label: 'Eligible 4 to 8 PM' },
]

function groupsOf(record: AuditResult): string[] {
  return GROUPS.filter((g) => record[g.flag] === true).map((g) => g.label)
}

// Flagged records first; the sort is stable, so call-ID order is kept within each half
function flaggedFirst(results: AuditResult[]): AuditResult[] {
  return [...results].sort(
    (a, b) => Number(groupsOf(b).length > 0) - Number(groupsOf(a).length > 0)
  )
}

export default function MonthlyAudit() {
  const [data, setData] = useState<AuditResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function runAudit() {
    setLoading(true)
    setError(null)

    try {
      const result = await fetchDemoAudit()
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="panel">
      <h3>Monthly Dispatch Review</h3>
      <p>
        Run an audit of 250 synthetic dispatch records using
        the CivOps eligibility rule engine.
      </p>

      <button
        className="primary-button"
        onClick={runAudit}
        disabled={loading}
      >
        {loading ? 'Running Audit...' : 'Run Synthetic Audit'}
      </button>

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <p className="disclaimer">
            Synthetic demonstration data. Not calibrated to
            historical LEAP call distributions.{' '}
            {data.dataset.arrival_pattern}{' '}
            The &ldquo;actual dispatch&rdquo; outcomes shown here are
            invented for the demonstration, not real dispatch records.
          </p>

          <div className="metric-grid">
            <div className="metric">
              <span>Total Calls</span>
              <strong>{data.summary.total_calls}</strong>
            </div>

            <div className="metric">
              <span>Model-flagged: could have gone to CRESS</span>
              <strong>{data.summary.could_have_gone_to_cress}</strong>
            </div>

            <div className="metric">
              <span>Model-flagged: should not have gone to CRESS</span>
              <strong>{data.summary.should_not_have_gone_to_cress}</strong>
            </div>

            <div className="metric">
              <span>Appropriate CRESS Referrals</span>
              <strong>{data.summary.sent_to_cress_appropriately}</strong>
            </div>

            <div className="metric">
              <span>Eligible calls 4 to 8 PM</span>
              <strong>{data.summary.eligible_after_hours}</strong>
            </div>
          </div>

          <h3>Sample Dispatch Records (flagged first)</h3>

          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Call ID</th>
                  <th>Actual</th>
                  <th>Recommended</th>
                  <th>Rule</th>
                  <th>Group</th>
                </tr>
              </thead>

              <tbody>
                {flaggedFirst(data.results).slice(0, 15).map((record) => (
                  <tr key={record.call_id}>
                    <td>{record.call_id}</td>
                    <td>{record.actual_destination}</td>
                    <td>{record.recommended_destination}</td>
                    <td>{record.rule_id}</td>
                    <td>{groupsOf(record).join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}