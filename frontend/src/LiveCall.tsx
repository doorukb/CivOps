import { useEffect, useRef, useState } from 'react'
import type { TranscriptEvent } from './api'
import {
  evaluateCall,
  extractCall,
  startCallRecording,
  stopCallRecording,
} from './api'
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
  const [transcript, setTranscript] = useState('')

  const [decision, setDecision] = useState<DispatchDecision | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [liveInterim, setLiveInterim] = useState('')
  const [speechConnected, setSpeechConnected] = useState(false)
  const [callActive, setCallActive] = useState(false)
  const callActiveRef = useRef(false)
  const [callError, setCallError] = useState<string | null>(null)
  const [callBusy, setCallBusy] = useState(false)
    useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(
        `${protocol}//${window.location.host}/ws/transcript`
    )

    socket.onopen = () => {
        setSpeechConnected(true)
    }

    socket.onmessage = (message) => {
        const event: TranscriptEvent = JSON.parse(message.data)
        if (!callActiveRef.current) {
            return
        }
        if (event.is_final) {
        setTranscript((previous) =>
            previous.trim()
            ? `${previous.trim()} ${event.text}`
            : event.text
        )

        setLiveInterim('')
        setDecision(null)

        // Previous incident fields no longer describe the full transcript
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
        } else {
        setLiveInterim(event.text)
        }
    }

    socket.onclose = () => {
        setSpeechConnected(false)
        setLiveInterim('')
    }

    socket.onerror = () => {
        setSpeechConnected(false)
    }

    return () => {
        socket.close()
    }
    }, [])

    async function startCall() {
        setCallBusy(true)
        setCallError(null)

        try {
            await startCallRecording()

            setTranscript('')
            setLiveInterim('')
            setDecision(null)
            setExtractionError(null)

            setIncident({
            ...defaultIncident,
            call_type: null,
            weapon_present: null,
            violence: null,
            injury: null,
            immediate_danger: null,
            caller_requests_cress: null,
            evidence: {},
            })

            callActiveRef.current = true
            setCallActive(true)
        } catch (err) {
            setCallError(
            err instanceof Error ? err.message : 'Could not start call'
            )
        } finally {
            setCallBusy(false)
        }
        }

async function endCall() {
    setCallBusy(true)
  setCallError(null)

  try {
    await stopCallRecording()

    callActiveRef.current = false
    setCallActive(false)
    setLiveInterim('')
  } catch (err) {
    setCallError(
      err instanceof Error ? err.message : 'Could not end call'
    )
  }finally {
    setCallBusy(false)
  }
}

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
        <div className="call-controls">
    {!callActive ? (
        <button
        type="button"
        className="start-call-button"
        onClick={startCall}
        disabled={!speechConnected || callBusy}
        >
        ☎ Start Call
        </button>
    ) : (
        <button
        type="button"
        className="end-call-button"
        onClick={endCall}
        disabled={callBusy}
        >
        ■ End Call
        </button>
    )}
    {callError && <p className="error">{callError}</p>}

    <span className={callActive ? 'call-live' : 'call-idle'}>
        {callActive ? '● CALL IN PROGRESS' : '○ NO ACTIVE CALL'}
    </span>
    </div>
    <div className="speech-status">
    <span className={speechConnected ? 'speech-online' : 'speech-offline'}>
        ● {speechConnected ? 'Transcript Stream Connected' : 'Transcript Stream Disconnected'}
    </span>
    </div>
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
    {liveInterim && (
    <div className="live-interim">
        <strong>Listening:</strong> {liveInterim}
    </div>
    )}

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
    <button
        type="button"
        className="secondary-button"
        onClick={() => {
            setTranscript('')
            setLiveInterim('')
            setDecision(null)
            setExtractionError(null)

            setIncident({
            ...defaultIncident,
            call_type: null,
            weapon_present: null,
            violence: null,
            injury: null,
            immediate_danger: null,
            caller_requests_cress: null,
            evidence: {},
            })
        }}
        >
        Clear Transcript
    </button>

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