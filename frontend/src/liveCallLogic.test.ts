import { describe, expect, it } from 'vitest'
import { CALL_ENDED, CALL_STARTED, SAFETY_FIELDS } from './api'
import type { ExtractionResult, Incident, TranscriptEvent } from './api'
import {
  BLANK_INCIDENT,
  appendFinalLine,
  classifyEvent,
  confirmNegatives,
  fromExtraction,
  overrideChoices,
  parseEvent,
  unconfirmedNegatives,
  withManualAnswer,
} from './liveCallLogic'

const event = (patch: Partial<TranscriptEvent>): TranscriptEvent => ({
  speaker: 'caller',
  text: 'hello',
  is_final: true,
  t: 0,
  call_id: 'call-aaaa',
  ...patch,
})

const allClearFromModel: Incident = {
  ...BLANK_INCIDENT,
  call_type: 'wellbeing_check',
  weapon_present: false,
  violence: false,
  injury: false,
  immediate_danger: false,
  evidence: { injury: 'nobody is injured' },
  provenance: {
    weapon_present: 'model',
    violence: 'model',
    injury: 'model',
    immediate_danger: 'model',
  },
}

describe('unknown is never no', () => {
  it('starts every screening answer as unknown', () => {
    for (const field of SAFETY_FIELDS) expect(BLANK_INCIDENT[field]).toBeNull()
    expect(BLANK_INCIDENT.call_type).toBeNull()
    expect(unconfirmedNegatives(BLANK_INCIDENT)).toEqual([])
  })
})

describe('parseEvent', () => {
  it('reads a transcript event', () => {
    expect(parseEvent(JSON.stringify(event({})))).toEqual(event({}))
  })

  it.each([
    ['not JSON', '{oops'],
    ['a number', '42'],
    ['null', 'null'],
    ['missing text', JSON.stringify({ speaker: 'caller', is_final: true })],
    ['wrong types', JSON.stringify({ speaker: 1, text: 'x', is_final: 'yes' })],
    ['binary frame', new ArrayBuffer(4)],
  ])('drops %s instead of throwing', (_name, raw) => {
    expect(parseEvent(raw)).toBeNull()
  })

  it('treats a missing call ID as none', () => {
    const { call_id: _omit, ...bare } = event({})
    void _omit
    expect(parseEvent(JSON.stringify(bare))?.call_id).toBeNull()
  })
})

describe('classifyEvent', () => {
  const open = { accepting: true, activeCallId: 'call-aaaa' }
  const idle = { accepting: false, activeCallId: null }

  it('accepts events of the open call', () => {
    expect(classifyEvent(event({}), open)).toBe('accept')
  })

  it('ignores a late event from another call', () => {
    expect(classifyEvent(event({ call_id: 'call-bbbb' }), open)).toBe('ignore')
    const ended = event({ speaker: 'system', text: CALL_ENDED, call_id: 'call-bbbb' })
    expect(classifyEvent(ended, open)).toBe('ignore')
  })

  it('ignores speech while no call is open', () => {
    expect(classifyEvent(event({}), idle)).toBe('ignore')
  })

  it('adopts a call started elsewhere when its start marker arrives', () => {
    const started = event({ speaker: 'system', text: CALL_STARTED, call_id: 'call-cccc' })
    expect(classifyEvent(started, idle)).toBe('adopt')
    // ...but not while another call is open
    expect(classifyEvent(started, open)).toBe('ignore')
  })

  it('does not adopt a start marker that carries no call ID', () => {
    const anonymous = event({ speaker: 'system', text: CALL_STARTED, call_id: null })
    expect(classifyEvent(anonymous, idle)).toBe('ignore')
  })
})

describe('appendFinalLine', () => {
  it('puts each labelled speaker on a new line', () => {
    const first = appendFinalLine('', event({ speaker: 'dispatcher', text: 'How can I help?' }))
    const second = appendFinalLine(first, event({ text: 'My neighbor is loud.' }))
    expect(second).toBe('Dispatcher: How can I help?\nCaller: My neighbor is loud.')
  })

  it('keeps unlabelled microphone text in one paragraph', () => {
    const first = appendFinalLine('', event({ speaker: 'unknown', text: 'hello there' }))
    expect(appendFinalLine(first, event({ speaker: 'unknown', text: 'are you ok' }))).toBe(
      'hello there are you ok'
    )
  })
})

describe('one-way autonomy in the form', () => {
  it('lists the "no" answers that only the model stands behind', () => {
    expect(unconfirmedNegatives(allClearFromModel)).toEqual([...SAFETY_FIELDS])
  })

  it('does not ask for confirmation of a model-proposed yes', () => {
    const escalating = { ...allClearFromModel, weapon_present: true }
    expect(unconfirmedNegatives(escalating)).not.toContain('weapon_present')
  })

  it('confirming marks exactly those answers as human', () => {
    const confirmed = confirmNegatives({ ...allClearFromModel, weapon_present: true })
    expect(unconfirmedNegatives(confirmed)).toEqual([])
    expect(confirmed.provenance?.injury).toBe('human')
    expect(confirmed.provenance?.weapon_present).toBe('model') // a yes needs no confirmation
    expect(confirmed.injury).toBe(false) // answers themselves are untouched
  })

  it('a manual answer is human-entered and drops the model quote', () => {
    const edited = withManualAnswer(allClearFromModel, 'injury', true)
    expect(edited.injury).toBe(true)
    expect(edited.provenance?.injury).toBe('human')
    expect(edited.evidence?.injury).toBeUndefined()
    expect(unconfirmedNegatives(edited)).not.toContain('injury')
  })

  it('setting an answer back to unknown clears its provenance', () => {
    const cleared = withManualAnswer(allClearFromModel, 'violence', null)
    expect(cleared.violence).toBeNull()
    expect(cleared.provenance?.violence).toBeUndefined()
  })

  it('keeps provenance when an extraction is loaded into the form', () => {
    const extracted: ExtractionResult = {
      ...allClearFromModel,
      timestamp: '2026-11-16T14:00:00-05:00',
      location: '14 Maple Court',
      downgraded: { violence: 'hedged' },
      warnings: [],
      model: 'claude-haiku-4-5',
    }
    const incident = fromExtraction(extracted)
    expect(incident.provenance).toEqual(allClearFromModel.provenance)
    expect(incident.location).toBe('14 Maple Court')
    expect(incident.timestamp).toBeNull() // the simulated time is chosen in the console
    expect(incident).not.toHaveProperty('downgraded')
  })
})

describe('overrideChoices', () => {
  it('offers every destination except the recommended one', () => {
    expect(overrideChoices('cress')).toEqual([
      'cress_followup', 'human_review', 'police', 'fire_ems', 'crisis',
    ])
    expect(overrideChoices('human_review')).not.toContain('human_review')
  })
})
