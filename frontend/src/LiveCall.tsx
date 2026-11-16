import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  CALL_ENDED,
  CALL_ERROR,
  CALL_STARTED,
  DESTINATION_LABELS,
  REVIEWS_CSV_URL,
  SAFETY_FIELDS,
  evaluateCall,
  extractCall,
  fetchReviews,
  listScenarios,
  newCallId,
  playScenario,
  recordReview,
  screenTranscript,
  startCallRecording,
  stopCallRecording,
} from './api'
import type {
  DispatchDecision,
  Incident,
  ReviewRecord,
  SafetyField,
  Scenario,
  TranscriptEvent,
} from './api'
import {
  BLANK_INCIDENT,
  FIELD_LABELS,
  appendFinalLine,
  classifyEvent,
  confirmNegatives,
  fromExtraction,
  overrideChoices,
  parseEvent,
  speakerLabel,
  unconfirmedNegatives,
  withManualAnswer,
} from './liveCallLogic'

type CallState = 'idle' | 'connecting' | 'live' | 'ending'

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

const SAFETY_QUESTIONS: Record<SafetyField, string> = {
  weapon_present: 'Is a weapon involved?',
  violence: 'Is there violence or a threat?',
  injury: 'Is anyone injured?',
  immediate_danger: 'Is anyone in immediate danger?',
}

const CALL_STATUS: Record<CallState, [className: string, text: string]> = {
  idle: ['call-idle', '○ NO ACTIVE CALL'],
  connecting: ['call-pending', '◌ CONNECTING…'],
  live: ['call-live', '● CALL IN PROGRESS'],
  ending: ['call-pending', '◌ ENDING, WAITING FOR THE LAST WORDS…'],
}

// If __call_ended__ never arrives, stop waiting so the button can't stick
const END_TIMEOUT_MS = 10_000

function screeningStatus(value: boolean | null): [string, string] {
  if (value === null) return ['open', 'still open']
  return value ? ['yes', 'reported: yes'] : ['no', 'answered: no']
}

function yesNoUnknown(value: boolean | null): string {
  if (value === null) return 'unknown'
  return value ? 'yes' : 'no'
}

function destinationLabel(destination: string): string {
  return DESTINATION_LABELS[destination] ?? destination.replaceAll('_', ' ')
}

function fieldList(fields: string[]): string {
  return fields
    .map((field) => FIELD_LABELS[field as SafetyField]?.toLowerCase() ?? field)
    .join(', ')
}

export default function LiveCall() {
  const [transcript, setTranscript] = useState('')
  const [incident, setIncident] = useState<Incident>(BLANK_INCIDENT)
  const [simTime, setSimTime] = useState<SimTime>('mon_2pm')
  const [decision, setDecision] = useState<DispatchDecision | null>(null)

  const [extracting, setExtracting] = useState(false)
  const [evaluating, setEvaluating] = useState(false)
  const [extractionError, setExtractionError] = useState<string | null>(null)
  const [extractionNotes, setExtractionNotes] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [staleNotice, setStaleNotice] = useState<string | null>(null)

  const [callState, setCallState] = useState<CallState>('idle')
  const [callError, setCallError] = useState<string | null>(null)
  const [speechConnected, setSpeechConnected] = useState(false)
  const [liveInterim, setLiveInterim] = useState('')
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [tripwireFlags, setTripwireFlags] =
    useState<Record<string, string[]> | null>(null)
  const [micConsent, setMicConsent] = useState(false)

  const [reviewReason, setReviewReason] = useState('')
  const [overrideTo, setOverrideTo] = useState('')
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [reviewLog, setReviewLog] = useState<ReviewRecord[]>([])
  const [logError, setLogError] = useState<string | null>(null)

  // Refs are read by async code and the WebSocket handler, which can run
  // between renders (e.g. the last words and __call_ended__ back to back).
  const transcriptRef = useRef('')
  const acceptEventsRef = useRef(false)
  const callIdRef = useRef<string | null>(null) // the call this page is showing
  const versionRef = useRef(0) // bumped on every transcript or field edit
  const screenSeqRef = useRef(0) // guards the live tripwire chain
  const endTimerRef = useRef<number | undefined>(undefined)
  const handleEventRef = useRef<(event: TranscriptEvent) => void>(() => {})

  function invalidate() {
    versionRef.current += 1
    setDecision(null)
    setReviewError(null)
  }

  // Every transcript change goes through here. Extracted fields no longer
  // describe the new text, so they go back to unknown.
  function changeTranscript(next: string) {
    transcriptRef.current = next
    setTranscript(next)
    setIncident(BLANK_INCIDENT)
    setExtractionError(null)
    setExtractionNotes([])
    invalidate()
  }

  function closeCall() {
    acceptEventsRef.current = false
    window.clearTimeout(endTimerRef.current)
    setCallState('idle')
    setLiveInterim('')
  }

  function handleEvent(event: TranscriptEvent) {
    const verdict = classifyEvent(event, {
      accepting: acceptEventsRef.current,
      activeCallId: callIdRef.current,
    })

    if (verdict === 'ignore') return // another call's event, or nothing open

    if (verdict === 'adopt') {
      // A call started outside this page (a terminal, another tab)
      callIdRef.current = event.call_id ?? null
      acceptEventsRef.current = true
      setCallError(null)
      setStaleNotice(null)
      changeTranscript('')
      setCallState('live')
      return
    }

    // Lifecycle markers come first; they are never speech.
    if (event.speaker === 'system') {
      if (event.text === CALL_STARTED) {
        setCallState((state) => (state === 'connecting' ? 'live' : state))
      } else if (event.text === CALL_ENDED || event.text === CALL_ERROR) {
        // ENDED always follows the last words, so the transcript is complete
        closeCall()

        if (event.text === CALL_ERROR) {
          setCallError(
            'The call ended with an error (transcription stopped; check the backend log).'
          )
        } else if (transcriptRef.current.trim()) {
          void extract(transcriptRef.current)
        }
      }
      return
    }

    if (event.is_final) {
      changeTranscript(appendFinalLine(transcriptRef.current, event))
      setLiveInterim('')
    } else {
      setLiveInterim(speakerLabel(event.speaker) + event.text)
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
        if (cancelled) return
        // A malformed frame is dropped, never thrown
        const event = parseEvent(message.data)
        if (event) handleEventRef.current(event)
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

  async function refreshLog() {
    try {
      setReviewLog(await fetchReviews(8))
      setLogError(null)
    } catch {
      setLogError('The saved review log could not be loaded.')
    }
  }

  // Show what is already in the call log when the page opens
  useEffect(() => {
    let cancelled = false

    fetchReviews(8)
      .then((log) => {
        if (!cancelled) setReviewLog(log)
      })
      .catch(() => {
        if (!cancelled) setLogError('The saved review log could not be loaded.')
      })

    return () => {
      cancelled = true
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

  async function beginSession(start: (callId: string) => Promise<void>) {
    setCallError(null)
    setStaleNotice(null)
    setError(null)
    changeTranscript('')
    setLiveInterim('')

    // Choose the ID and accept its events before asking the backend, so no
    // first word is dropped and no other call's event is taken for ours
    const callId = newCallId()
    callIdRef.current = callId
    acceptEventsRef.current = true
    setCallState('connecting')

    try {
      await start(callId)
    } catch (err) {
      closeCall()
      callIdRef.current = null
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
    setExtractionNotes([])
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

      const next = fromExtraction(extracted)
      setIncident(next)
      setExtractionNotes([
        ...extracted.warnings,
        ...Object.entries(extracted.downgraded).map(
          ([field, why]) =>
            `${FIELD_LABELS[field as SafetyField] ?? field}: the AI's answer was not kept. ${why}`
        ),
      ])
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
      setOverrideTo('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setEvaluating(false)
    }
  }

  function setAnswer(field: SafetyField, value: boolean | null) {
    setIncident((previous) => withManualAnswer(previous, field, value))
    invalidate()
  }

  // The dispatcher stands behind the AI-proposed "no" answers. Re-evaluate at
  // once: the recommendation is no longer provisional.
  function confirmAnswers() {
    const next = confirmNegatives(incident)
    setIncident(next)
    invalidate()
    void evaluate(next, transcript)
  }

  async function review(action: 'confirmed' | 'overridden') {
    if (!decision) return

    setSaving(true)
    setReviewError(null)

    try {
      await recordReview({
        call_id: callIdRef.current,
        incident: { ...incident, timestamp: SIM_TIMES[simTime].iso },
        transcript,
        action,
        ...(action === 'overridden'
          ? { chosen_destination: overrideTo, reason: reviewReason.trim() }
          : { reason: reviewReason.trim() }),
      })
      setReviewReason('')
      setOverrideTo('')
      await refreshLog()
    } catch (err) {
      setReviewError(
        err instanceof ApiError && err.status === 409
          ? 'Not saved: confirm the AI-proposed "no" answers first.'
          : err instanceof Error
            ? err.message
            : 'The review could not be saved'
      )
    } finally {
      setSaving(false)
    }
  }

  const [statusClass, statusText] = CALL_STATUS[callState]

  const tripwireSummary = tripwireFlags
    ? Object.entries(tripwireFlags).map(([category, words]) => {
        const unique = [...new Set(words.map((w) => w.toLowerCase()))]
        return `${unique.join(', ')} (${category.replaceAll('_', ' ')})`
      })
    : []

  const toConfirm = unconfirmedNegatives(incident)
  const canOverride =
    !!decision && !!overrideTo && reviewReason.trim().length >= 3 && !saving

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
        {callState === 'idle' && (
          <div className="consent-notice">
            <p>
              <strong>Before you use the microphone.</strong> Start Call
              records the microphone of the computer running the backend and
              sends the audio to Deepgram for transcription. Only use it when
              everyone in the room has agreed. This is a synthetic
              demonstration: do not discuss real emergencies or real people.
              The microphone has one channel, so speakers are not told apart.
            </p>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={micConsent}
                onChange={(e) => setMicConsent(e.target.checked)}
              />
              Everyone present agrees to be recorded and transcribed.
            </label>
          </div>
        )}

        <div className="call-controls">
          {callState === 'idle' ? (
            <button
              type="button"
              className="start-call-button"
              onClick={() => beginSession(startCallRecording)}
              disabled={!speechConnected || !micConsent}
              title={
                micConsent
                  ? undefined
                  : 'Tick the consent box to use the microphone'
              }
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

          <span className={statusClass} role="status" aria-live="polite">
            {statusText}
          </span>
        </div>

        {callState === 'idle' && speechConnected && scenarios.length > 0 && (
          <div className="scenario-buttons">
            <span>Scripted calls (fictional, no microphone):</span>
            {scenarios.map((scenario) => (
              <button
                key={scenario.id}
                type="button"
                className="secondary-button"
                title={scenario.summary}
                onClick={() =>
                  beginSession((callId) => playScenario(scenario.id, callId))
                }
              >
                ▶ {scenario.title}
              </button>
            ))}
          </div>
        )}

        {callError && (
          <p className="error" role="alert">
            {callError}
          </p>
        )}

        <div className="speech-status" role="status" aria-live="polite">
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
            onChange={(e) => {
              // Typed or pasted text is not part of a recorded call
              if (!acceptEventsRef.current && !e.target.value.trim()) {
                callIdRef.current = null
              }
              changeTranscript(e.target.value)
            }}
            rows={6}
            maxLength={20000}
          />
        </label>

        {liveInterim && (
          <div className="live-interim" aria-live="off">
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
              callIdRef.current = null
              changeTranscript('')
              setLiveInterim('')
              setStaleNotice(null)
            }}
          >
            Clear Transcript
          </button>

          {extractionError && (
            <p className="error" role="alert">
              {extractionError}
            </p>
          )}
        </div>

        {staleNotice && <p className="notice">{staleNotice}</p>}

        {extractionNotes.length > 0 && (
          <ul className="notice extraction-notes">
            {extractionNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}

        <div className="screening-checklist">
          <span>SCREENING QUESTIONS</span>
          <ul>
            {SAFETY_FIELDS.map((field) => {
              const [status, text] = screeningStatus(incident[field])
              return (
                <li key={field}>
                  {SAFETY_QUESTIONS[field]}{' '}
                  <strong className={`screen-${status}`}>{text}</strong>
                  {incident[field] !== null &&
                    incident.provenance?.[field] === 'model' && (
                      <span className="provenance-tag">
                        {incident[field]
                          ? 'AI-proposed'
                          : 'AI-proposed: confirm'}
                      </span>
                    )}
                </li>
              )
            })}
          </ul>
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
              invalidate()
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
          {SAFETY_FIELDS.map((field) => {
            const needsConfirm = toConfirm.includes(field)
            return (
              <label
                key={field}
                className={needsConfirm ? 'needs-confirm' : undefined}
              >
                {FIELD_LABELS[field]}
                <select
                  value={
                    incident[field] === null
                      ? 'unknown'
                      : String(incident[field])
                  }
                  onChange={(e) =>
                    setAnswer(
                      field,
                      e.target.value === 'unknown'
                        ? null
                        : e.target.value === 'true'
                    )
                  }
                >
                  <option value="unknown">Unknown</option>
                  <option value="false">No</option>
                  <option value="true">Yes</option>
                </select>
                {needsConfirm && (
                  <span className="provenance-tag">AI-proposed: confirm</span>
                )}
                {incident.evidence?.[field] && (
                  <span className="evidence-quote">
                    Evidence: "{incident.evidence[field]}"
                  </span>
                )}
              </label>
            )
          })}
        </div>

        {toConfirm.length > 0 && (
          <div className="confirm-answers">
            <p>
              The AI proposed &ldquo;no&rdquo; for {fieldList(toConfirm)}.
              The system may raise urgency by itself, but only a person can
              lower it. Read the evidence quotes, correct any answer, then
              confirm.
            </p>
            <button
              type="button"
              className="primary-button"
              onClick={confirmAnswers}
              disabled={evaluating || extracting}
            >
              ✓ Confirm screening answers
            </button>
          </div>
        )}

        <p className="read-only-line">
          Caller asked for CRESS:{' '}
          <strong>{yesNoUnknown(incident.caller_requests_cress)}</strong>{' '}
          · Stated location:{' '}
          <strong>{incident.location || 'not stated'}</strong>{' '}
          (both shown for context; the illustrative rules use neither)
        </p>
      </div>

      <button
        className="primary-button"
        onClick={() => evaluate(incident, transcript)}
        disabled={evaluating || extracting}
      >
        {evaluating ? 'Evaluating...' : 'Evaluate Incident'}
      </button>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {decision && (
        <div
          className={[
            'decision-card',
            decision.destination === 'human_review' ? 'human-review' : '',
            decision.provisional ? 'provisional' : '',
          ].join(' ')}
          role="status"
          aria-live="polite"
        >
          <span>
            {decision.provisional
              ? 'PROVISIONAL RECOMMENDATION · NOT YET CONFIRMABLE'
              : 'RULE-BASED RECOMMENDATION'}
          </span>

          <h3>{destinationLabel(decision.destination).toUpperCase()}</h3>

          <p>{decision.reason}</p>

          <p>
            Triggered Rule: <strong>{decision.rule_id}</strong>
            {decision.rulebook_version &&
              ` · rulebook v${decision.rulebook_version}`}
          </p>

          {decision.source && (
            <p className="rule-source">Source: {decision.source}</p>
          )}

          {decision.missing_information.length > 0 && (
            <p>
              Missing information: {decision.missing_information.join(', ')}
            </p>
          )}

          {decision.provisional && (
            <p className="provisional-note">
              This rests on AI-proposed &ldquo;no&rdquo; answers (
              {fieldList(decision.needs_confirmation)}). A person must confirm
              them before the recommendation can be accepted.
            </p>
          )}

          <div className="review-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => review('confirmed')}
              disabled={saving || decision.provisional}
              title={
                decision.provisional
                  ? 'Confirm the screening answers first'
                  : undefined
              }
            >
              ✓ Confirm recommendation
            </button>

            <label className="override-field">
              Override to
              <select
                value={overrideTo}
                onChange={(e) => setOverrideTo(e.target.value)}
              >
                <option value="">Choose a destination…</option>
                {overrideChoices(decision.destination).map((destination) => (
                  <option key={destination} value={destination}>
                    {destinationLabel(destination)}
                  </option>
                ))}
              </select>
            </label>

            <label className="override-field grow">
              Reason
              <input
                type="text"
                placeholder="Required to override"
                value={reviewReason}
                maxLength={500}
                onChange={(e) => setReviewReason(e.target.value)}
              />
            </label>

            <button
              type="button"
              className="secondary-button"
              onClick={() => review('overridden')}
              disabled={!canOverride}
            >
              Override
            </button>
          </div>

          {reviewError && (
            <p className="error" role="alert">
              {reviewError}
            </p>
          )}
        </div>
      )}

      <div className="review-log">
        <span>
          DISPATCHER REVIEW LOG (saved in the local call log) ·{' '}
          <a href={REVIEWS_CSV_URL} download>
            Download CSV
          </a>
        </span>
        {logError && <p className="error">{logError}</p>}
        {reviewLog.length === 0 && !logError ? (
          <p className="hint">No reviews recorded yet.</p>
        ) : (
          <ul>
            {reviewLog.map((entry) => (
              <li key={entry.id}>
                {new Date(entry.created_at).toLocaleString()} ·{' '}
                {entry.action === 'confirmed' ? (
                  <>
                    Confirmed {destinationLabel(entry.recommended_destination)}
                  </>
                ) : (
                  <>
                    Overrode {destinationLabel(entry.recommended_destination)}{' '}
                    → {destinationLabel(entry.chosen_destination)}
                  </>
                )}{' '}
                ({entry.rule_id})
                {entry.reason && <> · “{entry.reason}”</>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
