import { useState } from 'react'
import { evaluateCall, extractCall } from './api'
import type { DispatchDecision, Incident } from './api'

const defaultIncident: Incident = {
  call_type: 'wellbeing_check',
  weapon_present: false,
  violence: false,
  injury: false,
  immediate_danger: false,
  caller_requests_cress: true,
  timestamp: '2026-11-16T10:00:00-05:00',
}

export default function LiveCall() {
  const [incident, setIncident] = useState<Incident>(defaultIncident)
  const [extracting, setExtracting] = useState(false)
  const [extractionError, setExtractionError] = useState<string | null>(null)
  const [transcript, setTranscript] = useState(
    'A resident is concerned about their neighbor, who seems distressed. No weapons or injuries reported.'
  )

  const [decision, setDecision] = useState<DispatchDecision | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

async function extract() {
  setExtracting(true)
  setExtractionError(null)
  setDecision(null)

  try {
    const extracted = await extractCall(transcript)

    setIncident({
      ...extracted,
      timestamp: incident.timestamp,
    })
  } catch (err) {
    setExtractionError(
      err instanceof Error ? err.message : 'Extraction failed'
    )
  } finally {
    setExtracting(false)
  }
}

  async function evaluate() {
    setLoading(true)
    setError(null)
    setDecision(null)

    try {
      const result = await evaluateCall(incident, transcript)
      setDecision(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="panel">
      <h3>Live Dispatch Assistant</h3>

      <p>
        Evaluate a fictional incident against the CivOps
        illustrative routing rules.
      </p>

      <p className="disclaimer">
        Demonstration only. Not a real emergency dispatch system.
        Human review is required for operational decisions.
      </p>

      <div className="call-form">
  <label>
    Call Transcript
    <textarea
        value={transcript}
        onChange={(e) => {
            setTranscript(e.target.value)
            setDecision(null)
            setExtractionError(null)

            setIncident((previous) => ({
            ...previous,
            call_type: null,
            weapon_present: null,
            violence: null,
            injury: null,
            immediate_danger: null,
            caller_requests_cress: null,
            evidence: {},
            }))
        }}
        rows={6}
    />
  </label>

    {/* NEW: Claude extraction button */}
    <div className="extraction-actions">
        <button
        className="primary-button"
        onClick={extract}
        disabled={extracting || !transcript.trim()}
        >
        {extracting ? 'Extracting...' : '✦ Extract with Claude'}
        </button>

        {extractionError && (
        <p className="error">{extractionError}</p>
        )}
    </div>

    <label>
        Call Type
          <select
            value={incident.call_type ?? ''}
            onChange={(e) => {
                setIncident((previous) => ({
                    ...previous,
                    call_type: e.target.value || null,
                }))

                setDecision(null)
            }}
          >
            <option value="">Unknown</option>
            <option value="wellbeing_check">Wellbeing Check</option>
            <option value="disturbance">Disturbance</option>
            <option value="suspicious">Suspicious Activity</option>
            <option value="noise_complaint">Noise Complaint</option>
            <option value="other">Other</option>
          </select>
        </label>

        <div className="safety-grid">
          {(
            [
              ['weapon_present', 'Weapon Present'],
              ['violence', 'Violence'],
              ['injury', 'Injury'],
              ['immediate_danger', 'Immediate Danger'],
            ] as const
          ).map(([field, label]) => (
            <label key={field}>
              {label}
              <select
                value={
                  incident[field] === null
                    ? 'unknown'
                    : String(incident[field])
                }
                onChange={(e) => {
                    const newValue =
                        e.target.value === 'unknown'
                        ? null
                        : e.target.value === 'true'

                    setIncident((previous) => {
                        const updatedEvidence = { ...previous.evidence }
                        delete updatedEvidence[field]

                        return {
                        ...previous,
                        [field]: newValue,
                        evidence: updatedEvidence,
                        }
                    })

                    // Invalidate the previous dispatch recommendation
                    setDecision(null)
                }}
              >
                <option value="unknown">Unknown</option>
                <option value="false">No</option>
                <option value="true">Yes</option>
              </select>
              {incident.evidence?.[field] && (
                <span className="evidence-quote">
                    Evidence: "{incident.evidence[field]}"
                </span>
              )}
            </label>
          ))}
        </div>
      </div>

      <button
        className="primary-button"
        onClick={evaluate}
        disabled={loading}
      >
        {loading ? 'Evaluating...' : 'Evaluate Incident'}
      </button>

      {error && <p className="error">{error}</p>}

      {decision && (
        <div className="decision-card">
          <span>RULE-BASED RECOMMENDATION</span>

          <h3>{decision.destination.replaceAll('_', ' ').toUpperCase()}</h3>

          <p>{decision.reason}</p>

          <p>Triggered Rule: {decision.rule_id}</p>

          {decision.missing_information.length > 0 && (
            <p>
              Missing information: {decision.missing_information.join(', ')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}