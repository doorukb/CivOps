import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import type { DispatchDecision, ExtractionResult, Incident } from './api'
import LiveCall from './LiveCall'

vi.mock('./api', async (original) => ({
  ...(await original<typeof api>()),
  evaluateCall: vi.fn(),
  extractCall: vi.fn(),
  screenTranscript: vi.fn(),
  fetchReviews: vi.fn(),
  recordReview: vi.fn(),
  listScenarios: vi.fn(),
  playScenario: vi.fn(),
  startCallRecording: vi.fn(),
  stopCallRecording: vi.fn(),
}))

const mocked = vi.mocked(api)

class FakeSocket {
  static last: FakeSocket
  onopen: (() => void) | null = null
  onmessage: ((message: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null

  constructor() {
    FakeSocket.last = this
    queueMicrotask(() => this.onopen?.())
  }

  close() {}

  send(event: unknown) {
    act(() => this.onmessage?.({ data: typeof event === 'string' ? event : JSON.stringify(event) }))
  }
}

const decision = (patch: Partial<DispatchDecision>): DispatchDecision => ({
  destination: 'human_review',
  rule_id: 'SCREEN-INCOMPLETE',
  reason: 'Safety screening is incomplete.',
  missing_information: [],
  eligible: null,
  on_duty: null,
  source: 'Illustrative safety screening',
  rulebook_version: '0.2',
  provisional: false,
  needs_confirmation: [],
  ...patch,
})

const allClear: ExtractionResult = {
  call_type: 'wellbeing_check',
  weapon_present: false,
  violence: false,
  injury: false,
  immediate_danger: false,
  caller_requests_cress: true,
  timestamp: null,
  location: null,
  evidence: { injury: 'nobody is injured' },
  provenance: {
    weapon_present: 'model', violence: 'model', injury: 'model', immediate_danger: 'model',
  },
  downgraded: {},
  warnings: [],
  model: 'claude-haiku-4-5',
}

/** The rule engine in miniature, so the page gets realistic answers. */
function fakeEvaluate(incident: Incident): Promise<DispatchDecision> {
  const fields = api.SAFETY_FIELDS
  if (fields.some((f) => incident[f] === null)) return Promise.resolve(decision({}))
  const modelOnly = fields.filter((f) => incident[f] === false && incident.provenance?.[f] === 'model')
  return Promise.resolve(
    decision({
      destination: 'cress',
      rule_id: 'CRESS-001',
      reason: 'Eligible incident during CRESS operating hours.',
      provisional: modelOnly.length > 0,
      needs_confirmation: modelOnly,
    })
  )
}

const transcriptBox = () => screen.getByLabelText('Call Transcript') as HTMLTextAreaElement

beforeEach(() => {
  vi.stubGlobal('WebSocket', FakeSocket)
  mocked.screenTranscript.mockResolvedValue({})
  mocked.fetchReviews.mockResolvedValue([])
  mocked.listScenarios.mockResolvedValue([
    { id: 'hidden_knife', title: 'Noise complaint, then a hidden emergency', segments: 5 },
  ])
  mocked.evaluateCall.mockImplementation(fakeEvaluate)
  mocked.playScenario.mockResolvedValue()
})

describe('LiveCall', () => {
  it('evaluates a fresh page as all-unknown: unknown is never "no"', async () => {
    const user = userEvent.setup()
    render(<LiveCall />)

    await user.click(screen.getByRole('button', { name: 'Evaluate Incident' }))

    const [incident] = mocked.evaluateCall.mock.calls[0]
    for (const field of api.SAFETY_FIELDS) expect(incident[field]).toBeNull()
    expect(incident.call_type).toBeNull()
    expect(await screen.findByText('HUMAN REVIEW')).toBeInTheDocument()
    expect(screen.getAllByText('still open')).toHaveLength(4)
  })

  it('shows the tripwire banner as soon as the transcript has a safety word', async () => {
    const user = userEvent.setup()
    mocked.screenTranscript.mockResolvedValue({ weapon: ['knife'] })
    mocked.evaluateCall.mockResolvedValue(
      decision({ rule_id: 'TRANSCRIPT-TRIPWIRE', reason: 'Transcript contains potential safety signals: weapon' })
    )
    render(<LiveCall />)

    await user.type(transcriptBox(), 'he has a knife')

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('knife (weapon)')
    expect(banner).toHaveTextContent('the AI cannot clear this flag')
    expect(await screen.findByText(/TRANSCRIPT-TRIPWIRE/)).toBeInTheDocument()
  })

  it('discards an extraction that comes back after the transcript changed', async () => {
    const user = userEvent.setup()
    let finish: (value: ExtractionResult) => void = () => {}
    mocked.extractCall.mockReturnValue(new Promise((resolve) => (finish = resolve)))
    render(<LiveCall />)

    await user.type(transcriptBox(), 'first version')
    await user.click(screen.getByRole('button', { name: /Extract with Claude/ }))
    await user.type(transcriptBox(), ' and now it changed')
    await act(async () => finish(allClear))

    expect(await screen.findByText(/that result was discarded/)).toBeInTheDocument()
    expect(screen.getAllByText('still open')).toHaveLength(4) // the stale answers were not applied
  })

  it('keeps a CRESS recommendation provisional until a person confirms the AI-proposed "no" answers', async () => {
    const user = userEvent.setup()
    mocked.extractCall.mockResolvedValue(allClear)
    render(<LiveCall />)

    await user.type(transcriptBox(), 'Caller: nobody is injured')
    await user.click(screen.getByRole('button', { name: /Extract with Claude/ }))

    expect(await screen.findByText(/PROVISIONAL RECOMMENDATION/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Confirm recommendation/ })).toBeDisabled()
    expect(screen.getAllByText('AI-proposed: confirm').length).toBeGreaterThanOrEqual(4)

    await user.click(screen.getByRole('button', { name: /Confirm screening answers/ }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Confirm recommendation/ })).toBeEnabled()
    )
    const [confirmed] = mocked.evaluateCall.mock.calls.at(-1)!
    expect(Object.values(confirmed.provenance ?? {})).toEqual(['human', 'human', 'human', 'human'])
    expect(screen.queryByText(/PROVISIONAL RECOMMENDATION/)).not.toBeInTheDocument()
    expect(screen.getByText('RULE-BASED RECOMMENDATION')).toBeInTheDocument()
  })

  it('reports why the AI answer was not kept', async () => {
    const user = userEvent.setup()
    mocked.extractCall.mockResolvedValue({
      ...allClear,
      weapon_present: null,
      provenance: { violence: 'model', injury: 'model', immediate_danger: 'model' },
      downgraded: { weapon_present: 'The denial is hedged ("think"), so it stays unknown.' },
    })
    render(<LiveCall />)

    await user.type(transcriptBox(), "Caller: I don't think so")
    await user.click(screen.getByRole('button', { name: /Extract with Claude/ }))

    expect(
      await screen.findByText(/Weapon Present: the AI's answer was not kept\. The denial is hedged/)
    ).toBeInTheDocument()
  })

  it('an override needs a destination and a reason, and records what was chosen', async () => {
    const user = userEvent.setup()
    mocked.recordReview.mockResolvedValue({} as api.ReviewRecord)
    render(<LiveCall />)

    await user.click(screen.getByRole('button', { name: 'Evaluate Incident' }))
    const override = await screen.findByRole('button', { name: 'Override' })
    expect(override).toBeDisabled()

    await user.selectOptions(screen.getByLabelText('Override to'), 'police')
    expect(override).toBeDisabled() // still no reason
    await user.type(screen.getByLabelText('Reason'), 'Caller rang back in distress')
    expect(override).toBeEnabled()
    await user.click(override)

    expect(mocked.recordReview).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'overridden',
        chosen_destination: 'police',
        reason: 'Caller rang back in distress',
        call_id: null, // a typed transcript is not a recorded call
      })
    )
    // The recommended destination is not offered as an override target.
    const options = [...(screen.getByLabelText('Override to') as HTMLSelectElement).options].map((o) => o.value)
    expect(options).not.toContain('human_review')
  })

  it('tells the dispatcher when the server refuses to confirm a provisional recommendation', async () => {
    const user = userEvent.setup()
    mocked.recordReview.mockRejectedValue(new api.ApiError('provisional', 409, {}))
    render(<LiveCall />)

    await user.click(screen.getByRole('button', { name: 'Evaluate Incident' }))
    await user.click(await screen.findByRole('button', { name: /Confirm recommendation/ }))

    expect(await screen.findByText(/confirm the AI-proposed "no" answers first/)).toBeInTheDocument()
  })

  it('will not start the microphone without consent', async () => {
    const user = userEvent.setup()
    render(<LiveCall />)

    const start = await screen.findByRole('button', { name: /Start Call/ })
    await waitFor(() => expect(screen.getByText(/Transcript Stream Connected/)).toBeInTheDocument())
    expect(start).toBeDisabled()
    expect(screen.getByText(/sends the audio to Deepgram/)).toBeInTheDocument()

    await user.click(screen.getByLabelText(/Everyone present agrees/))
    expect(start).toBeEnabled()
  })

  it('accepts only the events of its own call and survives a malformed frame', async () => {
    const user = userEvent.setup()
    render(<LiveCall />)

    await user.click(await screen.findByRole('button', { name: /hidden emergency/ }))
    const callId = mocked.playScenario.mock.calls[0][1]
    const socket = FakeSocket.last

    socket.send({ speaker: 'system', text: api.CALL_STARTED, is_final: true, t: 0, call_id: callId })
    socket.send({ speaker: 'caller', text: 'late words from the previous call', is_final: true, t: 1, call_id: 'other-call-0001' })
    socket.send('{not json')
    socket.send({ speaker: 'caller', text: 'My neighbors are loud.', is_final: true, t: 2, call_id: callId })

    expect(transcriptBox().value).toBe('Caller: My neighbors are loud.')
    expect(screen.getByText('● CALL IN PROGRESS')).toBeInTheDocument()

    // Another call's end marker does not close this one.
    socket.send({ speaker: 'system', text: api.CALL_ENDED, is_final: true, t: 0, call_id: 'other-call-0001' })
    expect(screen.getByText('● CALL IN PROGRESS')).toBeInTheDocument()
  })

  it('shows a call that was started from a terminal', async () => {
    render(<LiveCall />)
    await screen.findByText(/Transcript Stream Connected/)
    const socket = FakeSocket.last

    socket.send({ speaker: 'system', text: api.CALL_STARTED, is_final: true, t: 0, call_id: 'curl-call-0001' })
    socket.send({ speaker: 'dispatcher', text: 'How can I help?', is_final: true, t: 1, call_id: 'curl-call-0001' })

    expect(transcriptBox().value).toBe('Dispatcher: How can I help?')
  })
})
