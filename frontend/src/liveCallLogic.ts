// Pure logic behind the Live Call screen, kept out of the component so the
// safety-relevant rules can be unit-tested without a browser.

import { CALL_STARTED, DESTINATIONS, SAFETY_FIELDS } from './api'
import type {
  ExtractionResult,
  Incident,
  SafetyField,
  TranscriptEvent,
} from './api'

// Unknown is never "no": every field starts unknown, so Evaluate on a fresh
// page returns SCREEN-INCOMPLETE instead of a CRESS referral.
export const BLANK_INCIDENT: Incident = {
  call_type: null,
  weapon_present: null,
  violence: null,
  injury: null,
  immediate_danger: null,
  caller_requests_cress: null,
  timestamp: null,
  location: null,
  evidence: {},
  provenance: {},
}

export function speakerLabel(speaker: string): string {
  switch (speaker.toLowerCase()) {
    case 'dispatcher':
      return 'Dispatcher: '
    case 'caller':
      return 'Caller: '
    default:
      return '' // microphone events ("unknown") stay unlabeled
  }
}

/** The transcript after one more final line. Labelled speakers start a new
 * line; unlabelled microphone text continues the paragraph. */
export function appendFinalLine(transcript: string, event: TranscriptEvent): string {
  const label = speakerLabel(event.speaker)
  const previous = transcript.trim()
  const line = label + event.text
  return previous ? `${previous}${label ? '\n' : ' '}${line}` : line
}

/** A message from the transcript socket, or null if it is not one. A malformed
 * frame must never take the page down mid-call. */
export function parseEvent(raw: unknown): TranscriptEvent | null {
  if (typeof raw !== 'string') return null

  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }

  if (!value || typeof value !== 'object') return null
  const event = value as Record<string, unknown>

  if (
    typeof event.speaker !== 'string' ||
    typeof event.text !== 'string' ||
    typeof event.is_final !== 'boolean'
  ) {
    return null
  }

  return {
    speaker: event.speaker,
    text: event.text,
    is_final: event.is_final,
    t: typeof event.t === 'number' ? event.t : 0,
    call_id: typeof event.call_id === 'string' ? event.call_id : null,
  }
}

export type EventVerdict = 'accept' | 'adopt' | 'ignore'

/** Decide what to do with an event from the shared transcript stream.
 *
 * - While this page has a call open, only events of THAT call are accepted,
 *   so a late event from the previous call can never land in the next one.
 * - While idle, a call started elsewhere (a terminal, another tab) is adopted
 *   when its start marker arrives. Anything else is ignored.
 */
export function classifyEvent(
  event: TranscriptEvent,
  state: { accepting: boolean; activeCallId: string | null }
): EventVerdict {
  if (state.accepting) {
    // Events with no ID come only from the token-gated standalone script.
    if (!event.call_id || !state.activeCallId) return 'accept'
    return event.call_id === state.activeCallId ? 'accept' : 'ignore'
  }

  const startsACall =
    event.speaker === 'system' && event.text === CALL_STARTED && !!event.call_id
  return startsACall ? 'adopt' : 'ignore'
}

/** The fields the form keeps from an extraction. Everything the model
 * proposed is marked as model-proposed by the backend (`provenance`). */
export function fromExtraction(extracted: ExtractionResult): Incident {
  return {
    call_type: extracted.call_type,
    weapon_present: extracted.weapon_present,
    violence: extracted.violence,
    injury: extracted.injury,
    immediate_danger: extracted.immediate_danger,
    caller_requests_cress: extracted.caller_requests_cress,
    timestamp: null,
    location: extracted.location ?? null,
    evidence: { ...extracted.evidence },
    provenance: { ...extracted.provenance },
  }
}

/** A person set this answer: it is human-entered, and the model's quote no
 * longer describes it. Setting it back to unknown clears the provenance. */
export function withManualAnswer(
  incident: Incident,
  field: SafetyField,
  value: boolean | null
): Incident {
  const evidence = { ...incident.evidence }
  delete evidence[field]

  const provenance = { ...incident.provenance }
  if (value === null) delete provenance[field]
  else provenance[field] = 'human'

  return { ...incident, [field]: value, evidence, provenance }
}

/** Screening answers that are "no" only because the model said so. */
export function unconfirmedNegatives(incident: Incident): SafetyField[] {
  return SAFETY_FIELDS.filter(
    (field) => incident[field] === false && incident.provenance?.[field] === 'model'
  )
}

/** The dispatcher has read the model's "no" answers and stands behind them.
 * Only negatives need this: a model-proposed "yes" already escalates. */
export function confirmNegatives(incident: Incident): Incident {
  const provenance = { ...incident.provenance }
  for (const field of unconfirmedNegatives(incident)) provenance[field] = 'human'
  return { ...incident, provenance }
}

/** Where a dispatcher may send a call instead of the recommendation. */
export function overrideChoices(recommended: string): string[] {
  return DESTINATIONS.filter((destination) => destination !== recommended)
}

export const FIELD_LABELS: Record<SafetyField, string> = {
  weapon_present: 'Weapon Present',
  violence: 'Violence',
  injury: 'Injury',
  immediate_danger: 'Immediate Danger',
}
