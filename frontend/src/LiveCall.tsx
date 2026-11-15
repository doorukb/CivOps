import { useEffect, useRef, useState } from 'react'
import {
  CALL_ENDED,
  CALL_ERROR,
  CALL_STARTED,
  evaluateCall,
  extractCall,
  listScenarios,
  playScenario,
  screenTranscript,
  startCallRecording,
  stopCallRecording,
} from './api'
import type {
  DispatchDecision,
  Incident,
  Scenario,
  TranscriptEvent,
} from './api'

type CallState = 'idle' | 'connecting' | 'live' | 'ending'

// Unknown is never "no": every field starts unknown, so Evaluate on a fresh
// page returns SCREEN-INCOMPLETE instead of a CRESS referral.
const BLANK_INCIDENT: Incident = {
  call_type: null,
  weapon_present: null,
  violence: null,
  injury: null,
  immediate_danger: null,
  caller_requests_cress: null,
  timestamp: null,
  evidence: {},
}

// Fictional call times the rulebook evaluates (America/New_York, EST).
const SIM_TIMES = {
  mon_2pm: {
    label: 'Monday 2 PM (on duty)',
    iso: '2026-11-16T14:00:00-05:00',
  },
  mon_730pm: {
    label: 'Monday 7:30 PM (after hours)',
    iso: '2026-11-16T19:30:00-05:00',
  },
  sat_11am: {
    label: 'Saturday 11 AM (weekend)',
    iso: '2026-11-21T11:00:00-05:00',
  },
} as const
type SimTime = keyof typeof SIM_TIMES

const SAFETY_QUESTIONS = [
  ['weapon_present', 'Weapon Present', 'Is a weapon involved?'],
  ['violence', 'Violence', 'Is there violence or a threat?'],
  ['injury', 'Injury', 'Is anyone injured?'],
  ['immediate_danger', 'Immediate Danger', 'Is anyone in immediate danger?'],
] as const

const CALL_STATUS: Record<CallState, [className: string, text: string]> = {
  idle: ['call-idle', '○ NO ACTIVE CALL'],
  connecting: ['call-pending', '◌ CONNECTING…'],
  live: ['call-live', '● CALL IN PROGRESS'],
  ending: ['call-pending', '◌ ENDING, WAITING FOR THE LAST WORDS…'],
}

// If __call_ended__ never arrives, stop waiting so the button can't stick
const END_TIMEOUT_MS = 10_000

function speakerLabel(speaker: string): string {
  switch (speaker.toLowerCase()) {
    case 'dispatcher':
      return 'Dispatcher: '
    case 'caller':
      return 'Caller: '
    default:
      return '' // microphone events ("unknown") stay unlabeled
  }
}

function screeningStatus(value: boolean | null): [string, string] {
  if (value === null) return ['open', 'still open']
  return value ? ['yes', 'reported: yes'] : ['no', 'answered: no']
}

function yesNoUnknown(value: boolean | null): string {
  if (value === null) return 'unknown'
  return value ? 'yes' : 'no'
}

interface ReviewEntry {
  time: string
  action: 'Confirmed' | 'Overridden'
  destination: string
  rule_id: string
  reason: string
}

export default function LiveCall() {
  const [transcript, setTranscript] = useState('')
  const [incident, setIncident] = useState<Incident>(BLANK_INCIDENT)
  const [simTime, setSimTime] = useState<SimTime>('mon_2pm')
  const [decision, setDecision] = useState<DispatchDecision | null>(null)

  const [extracting, setExtracting] = useState(false)
  const [evaluating, setEvaluating] = useState(false)
  const [extractionError, setExtractionError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [staleNotice, setStaleNotice] = useState<string | null>(null)

  const [callState, setCallState] = useState<CallState>('idle')
  const [callError, setCallError] = useState<string | null>(null)
  const [speechConnected, setSpeechConnected] = useState(false)
  const [liveInterim, setLiveInterim] = useState('')
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [tripwireFlags, setTripwireFlags] =
    useState<Record<string, string[]> | null>(null)

  const [reviewReason, setReviewReason] = useState('')
  const [reviewLog, setReviewLog] = useState<ReviewEntry[]>([])

  // Refs are read by async code and the WebSocket handler, which can run
  // between renders (e.g. the last words and __call_ended__ back to back).
  const transcriptRef = useRef('')
  const acceptEventsRef = useRef(false)
  const versionRef = useRef(0) // bumped on every transcript or field edit
  const screenSeqRef = useRef(0) // guards the live tripwire chain
  const endTimerRef = useRef<number | undefined>(undefined)
  const handleEventRef = useRef<(event: TranscriptEvent) => void>(() => {})

  function invalidate() {
    versionRef.current += 1
    setDecision(null)
  }

  // Every transcript change goes through here. Extracted fields no longer
  // describe the new text, so they go back to unknown.
  function changeTranscript(next: string) {
    transcriptRef.current = next
    setTranscript(next)
    setIncident(BLANK_INCIDENT)
    setExtractionError(null)
    invalidate()
  }

  function updateField(patch: Partial<Incident>, staleEvidence?: string) {
    setIncident((previous) => {
      const evidence = { ...previous.evidence }
      if (staleEvidence) delete evidence[staleEvidence]
      return { ...previous, ...patch, evidence }
    })
    invalidate()
  }

  function closeCall() {
    acceptEventsRef.current = false
    window.clearTimeout(endTimerRef.current)
    setCallState('idle')
    setLiveInterim('')
  }

  function handleEvent(event: TranscriptEvent) {
    // Lifecycle markers come first; they are never speech.
    if (event.speaker === 'system') {
      if (!acceptEventsRef.current) return // not a session this page started

      if (event.text === CALL_STARTED) {
        setCallState((state) => (state === 'connecting' ? 'live' : state))
      } else if (event.text === CALL_ENDED || event.text === CALL_ERROR) {
        // ENDED always follows the last words, so the transcript is complete
        closeCall()

        if (event.text === CALL_ERROR) {
          setCallError('The call ended with an error (check the backend log).')
        } else if (transcriptRef.current.trim()) {
          void extract(transcriptRef.current)
        }
      }
      return
    }

    if (!acceptEventsRef.current) return

    const label = speakerLabel(event.speaker)

    if (event.is_final) {
      const previous = transcriptRef.current.trim()
      const line = label + event.text
      changeTranscript(
        previous ? `${previous}${label ? '\n' : ' '}${line}` : line
      )
      setLiveInterim('')
    } else {
      setLiveInterim(label + event.text)
    }
  }

  // The socket outlives renders; always dispatch to the latest handler
  useEffect(() => {
    handleEventRef.current = handleEvent
  })

  useEffect(() => {
    let cancelled = false // StrictMode mounts twice; only the live run acts
    let socket: WebSocket | null = null
    let retryTimer: number | undefined

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(
        `${protocol}//${window.location.host}/ws/transcript`
      )

      socket.onopen = () => {
        if (cancelled) return
        setSpeechConnected(true)
        listScenarios()
          .then((list) => {
            if (!cancelled) setScenarios(list)
          })
          .catch(() => {}) // scripted calls are optional
      }

      socket.onmessage = (message) => {
        if (!cancelled) handleEventRef.current(JSON.parse(message.data))
      }

      socket.onclose = () => {
        if (cancelled) return
        setSpeechConnected(false)
        setLiveInterim('')
        retryTimer = window.setTimeout(connect, 1000)
      }
    }

    connect()

    return () => {
      cancelled = true
      window.clearTimeout(retryTimer)
      socket?.close()
    }
  }, [])

  // Live tripwire: 250 ms after the transcript settles, screen it with no
  // AI. If flagged, evaluate a blank incident so TRANSCRIPT-TRIPWIRE shows
  // at once. The sequence number drops answers for older text.
  useEffect(() => {
    const seq = ++screenSeqRef.current
    const text = transcript

    const timer = window.setTimeout(async () => {
      if (!text.trim()) {
        setTripwireFlags(null)
        return
      }

      try {
        const flags = await screenTranscript(text)
        if (seq !== screenSeqRef.current) return

        const flagged = Object.keys(flags).length > 0
        setTripwireFlags(flagged ? flags : null)
        if (!flagged) return

        const result = await evaluateCall(BLANK_INCIDENT, text)
        if (seq !== screenSeqRef.current) return
        setDecision(result)
      } catch {
        // Best effort only: Evaluate runs the same tripwires on the server
      }
    }, 250)

    return () => window.clearTimeout(timer)
  }, [transcript])

  async function beginSession(start: () => Promise<void>) {
    setCallError(null)
    setStaleNotice(null)
    setError(null)
    changeTranscript('')
    setLiveInterim('')

    // Accept events before asking the backend, so no first word is dropped
    acceptEventsRef.current = true
    setCallState('connecting')

    try {
      await start()
    } catch (err) {
      closeCall()
      setCallError(
        err instanceof Error ? err.message : 'Could not start the call'
      )
    }
  }

  async function endCall() {
    // Keep accepting events: the last words arrive before __call_ended__
    setCallState('ending')
    setCallError(null)

    window.clearTimeout(endTimerRef.current)
    endTimerRef.current = window.setTimeout(() => {
      closeCall()
      setCallError(
        'No end signal from the backend after 10 seconds; closed the call here.'
      )
    }, END_TIMEOUT_MS)

    try {
      // Nothing was running, so no marker will come
      if ((await stopCallRecording()) === 'not_running') closeCall()
    } catch (err) {
      setCallError(err instanceof Error ? err.message : 'Could not end the call')
    }
  }

  async function extract(text: string) {
    const version = versionRef.current
    setExtracting(true)
    setExtractionError(null)
    setStaleNotice(null)

    try {
      const extracted = await extractCall(text)

      if (versionRef.current !== version) {
        setStaleNotice(
          'The transcript or fields changed while Claude was extracting, ' +
            'so that result was discarded. Extract again.'
        )
        return
      }

      const next = { ...extracted, timestamp: null }
      setIncident(next)
      versionRef.current += 1 // the fields just changed
      void evaluate(next, text) // auto-flow: extract, then evaluate
    } catch (err) {
      setExtractionError(
        err instanceof Error ? err.message : 'Extraction failed'
      )
    } finally {
      setExtracting(false)
    }
  }

  async function evaluate(current: Incident, text: string) {
    const version = versionRef.current
    setEvaluating(true)
    setError(null)
    setStaleNotice(null)

    try {
      const result = await evaluateCall(
        { ...current, timestamp: SIM_TIMES[simTime].iso },
        text
      )

      if (versionRef.current !== version) {
        setStaleNotice(
          'The transcript or fields changed while evaluating, ' +
            'so that recommendation was discarded. Evaluate again.'
        )
        return
      }

      setDecision(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setEvaluating(false)
    }
  }

  function review(action: ReviewEntry['action']) {
    if (!decision) return

    setReviewLog((log) => [
      {
        time: new Date().toLocaleTimeString(),
        action,
        destination: decision.destination,
        rule_id: decision.rule_id,
        reason: reviewReason.trim(),
      },
      ...log,
    ])
    setReviewReason('')
  }

  const [statusClass, statusText] = CALL_STATUS[callState]

  const tripwireSummary = tripwireFlags
    ? Object.entries(tripwireFlags).map(([category, words]) => {
        const unique = [...new Set(words.map((w) => w.toLowerCase()))]
        return `${unique.join(', ')} (${category.replaceAll('_', ' ')})`
      })
    : []

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
          {callState === 'idle' ? (
            <button
              type="button"
              className="start-call-button"
              onClick={() => beginSession(startCallRecording)}
              disabled={!speechConnected}
            >
              ☎ Start Call
            </button>
          ) : (
            <button
              type="button"
              className="end-call-button"
              onClick={endCall}
              disabled={callState === 'ending'}
            >
              {callState === 'ending' ? 'Ending…' : '■ End Call'}
            </button>
          )}

          <span className={statusClass}>{statusText}</span>
        </div>

        {callState === 'idle' && speechConnected && scenarios.length > 0 && (
          <div className="scenario-buttons">
            <span>Scripted calls:</span>
            {scenarios.map((scenario) => (
              <button
                key={scenario.id}
                type="button"
                className="secondary-button"
                onClick={() =>
                  beginSession(() => playScenario(scenario.id))
                }
              >
                ▶ {scenario.title}
              </button>
            ))}
          </div>
        )}

        {callError && <p className="error">{callError}</p>}

        <div className="speech-status">
          <span className={speechConnected ? 'speech-online' : 'speech-offline'}>
            ● {speechConnected
              ? 'Transcript Stream Connected'
              : 'Transcript Stream Disconnected (retrying)'}
          </span>
        </div>

        <label>
          Simulated call time
          <select
            value={simTime}
            onChange={(e) => {
              setSimTime(e.target.value as SimTime)
              invalidate()
            }}
          >
            {Object.entries(SIM_TIMES).map(([key, option]) => (
              <option key={key} value={key}>
                {option.label}
              </option>
            ))}
          </select>
          <span className="hint">
            The rulebook judges this time, not the real clock.
          </span>
        </label>

        {tripwireSummary.length > 0 && (
          <div className="tripwire-alert" role="alert">
            <strong>⚠ Safety words in the transcript:</strong>{' '}
            {tripwireSummary.join('; ')}. This call goes to a human
            dispatcher, and the AI cannot clear this flag.
          </div>
        )}

        <label>
          Call Transcript
          <textarea
            value={transcript}
            onChange={(e) => changeTranscript(e.target.value)}
            rows={6}
          />
        </label>

        {liveInterim && (
          <div className="live-interim">
            <strong>Listening:</strong> {liveInterim}
          </div>
        )}

        <div className="extraction-actions">
          <button
            className="primary-button"
            onClick={() => extract(transcript)}
            disabled={extracting || !transcript.trim()}
          >
            {extracting ? 'Extracting...' : '✦ Extract with Claude'}
          </button>

          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              changeTranscript('')
              setLiveInterim('')
              setStaleNotice(null)
            }}
          >
            Clear Transcript
          </button>

          {extractionError && <p className="error">{extractionError}</p>}
        </div>

        {staleNotice && <p className="notice">{staleNotice}</p>}

        <div className="screening-checklist">
          <span>SCREENING QUESTIONS</span>
          <ul>
            {SAFETY_QUESTIONS.map(([field, , question]) => {
              const [status, text] = screeningStatus(incident[field])
              return (
                <li key={field}>
                  {question}{' '}
                  <strong className={`screen-${status}`}>{text}</strong>
                </li>
              )
            })}
          </ul>
        </div>

        <label>
          Call Type
          <select
            value={incident.call_type ?? ''}
            onChange={(e) =>
              updateField({ call_type: e.target.value || null })
            }
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
          {SAFETY_QUESTIONS.map(([field, label]) => (
            <label key={field}>
              {label}
              <select
                value={
                  incident[field] === null ? 'unknown' : String(incident[field])
                }
                onChange={(e) =>
                  updateField(
                    {
                      [field]:
                        e.target.value === 'unknown'
                          ? null
                          : e.target.value === 'true',
                    },
                    field
                  )
                }
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

        <p className="read-only-line">
          Caller asked for CRESS:{' '}
          <strong>{yesNoUnknown(incident.caller_requests_cress)}</strong>{' '}
          (shown for context; the illustrative rules don't use it)
        </p>
      </div>

      <button
        className="primary-button"
        onClick={() => evaluate(incident, transcript)}
        disabled={evaluating || extracting}
      >
        {evaluating ? 'Evaluating...' : 'Evaluate Incident'}
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

          <div className="review-actions">
            <input
              type="text"
              placeholder="Reason (required to override)"
              value={reviewReason}
              onChange={(e) => setReviewReason(e.target.value)}
            />
            <button
              type="button"
              className="secondary-button"
              onClick={() => review('Confirmed')}
            >
              ✓ Confirm
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => review('Overridden')}
              disabled={!reviewReason.trim()}
            >
              Override
            </button>
          </div>
        </div>
      )}

      {reviewLog.length > 0 && (
        <div className="review-log">
          <span>DISPATCHER REVIEW LOG (this page only, not saved)</span>
          <ul>
            {reviewLog.map((entry, index) => (
              <li key={reviewLog.length - index}>
                {entry.time} · {entry.action}{' '}
                {entry.destination.replaceAll('_', ' ')} ({entry.rule_id})
                {entry.reason && <> · “{entry.reason}”</>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
