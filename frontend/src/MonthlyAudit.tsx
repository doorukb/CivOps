import { useState } from 'react'
import { fetchDemoAudit } from './api'
import type { AuditResponse } from './api'

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
            historical LEAP call distributions.
          </p>

          <div className="metric-grid">
            <div className="metric">
              <span>Total Calls</span>
              <strong>{data.summary.total_calls}</strong>
            </div>

            <div className="metric">
              <span>Potential CRESS Referrals</span>
              <strong>{data.summary.could_have_gone_to_cress}</strong>
            </div>

            <div className="metric">
              <span>Appropriate CRESS Referrals</span>
              <strong>{data.summary.sent_to_cress_appropriately}</strong>
            </div>

            <div className="metric">
              <span>After-Hours Opportunities</span>
              <strong>{data.summary.eligible_after_hours}</strong>
            </div>
          </div>

          <h3>Sample Dispatch Records</h3>

          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Call ID</th>
                  <th>Actual</th>
                  <th>Recommended</th>
                  <th>Rule</th>
                </tr>
              </thead>

              <tbody>
                {data.results.slice(0, 15).map((record) => (
                  <tr key={record.call_id}>
                    <td>{record.call_id}</td>
                    <td>{record.actual_destination}</td>
                    <td>{record.recommended_destination}</td>
                    <td>{record.rule_id}</td>
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