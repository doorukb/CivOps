import { describe, expect, it, vi } from 'vitest'
import { ApiError, evaluateCall, newCallId, playScenario, recordReview } from './api'
import { BLANK_INCIDENT } from './liveCallLogic'

function respond(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(typeof body === 'string' ? body : JSON.stringify(body), { status })
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('api error handling', () => {
  it('returns the parsed body on success', async () => {
    const fetchMock = respond(200, { destination: 'human_review' })
    await expect(evaluateCall(BLANK_INCIDENT, 'hi')).resolves.toEqual({ destination: 'human_review' })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/calls/evaluate',
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('carries the backend explanation for a plain detail', async () => {
    respond(502, { detail: 'AI extraction service unavailable' })
    await expect(evaluateCall(BLANK_INCIDENT, 'hi')).rejects.toThrow(
      'Call evaluation failed (502): AI extraction service unavailable'
    )
  })

  it('joins FastAPI validation messages', async () => {
    respond(422, { detail: [{ msg: 'An override must give a reason' }, { msg: 'second' }] })
    await expect(
      recordReview({ call_id: null, incident: BLANK_INCIDENT, transcript: '', action: 'overridden' })
    ).rejects.toThrow('An override must give a reason; second')
  })

  it('exposes the status and structured detail of a refused confirmation', async () => {
    respond(409, { detail: { message: 'This recommendation is provisional', needs_confirmation: ['injury'] } })
    const error = await recordReview({
      call_id: null, incident: BLANK_INCIDENT, transcript: '', action: 'confirmed',
    }).catch((e) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(409)
    expect(error.detail.needs_confirmation).toEqual(['injury'])
    expect(error.message).toContain('This recommendation is provisional')
  })

  it('still reports the status when the body is not JSON', async () => {
    respond(403, 'Forbidden origin')
    await expect(evaluateCall(BLANK_INCIDENT, 'hi')).rejects.toThrow('Call evaluation failed (403)')
  })

  it('turns "already running" into an error the page can show', async () => {
    respond(200, { status: 'already_running' })
    await expect(playScenario('hidden_knife', 'call-12345678')).rejects.toThrow(/already running/)
  })
})

describe('newCallId', () => {
  it('matches the pattern the backend accepts and does not repeat', () => {
    const ids = new Set(Array.from({ length: 50 }, newCallId))
    expect(ids.size).toBe(50)
    for (const id of ids) expect(id).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
  })
})
