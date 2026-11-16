// Every call to the backend lives here. Vite proxies /api/* to 127.0.0.1:8000.

/** Thrown for any non-2xx answer, carrying the backend's own explanation. */
export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function describe(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  // FastAPI validation errors: [{loc, msg, ...}]
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item.msg === 'string' ? item.msg : null))
      .filter(Boolean)
    return messages.length ? messages.join('; ') : null
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const message = (detail as { message: unknown }).message
    return typeof message === 'string' ? message : null
  }
  return null
}

async function request<T>(
  what: string,
  path: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`/api${path}`, init)

  if (!response.ok) {
    let detail: unknown = null
    try {
      detail = (await response.json()).detail
    } catch {
      // not JSON: keep the status only
    }
    throw new ApiError(
      `${what} failed (${response.status})${describe(detail) ? `: ${describe(detail)}` : ''}`,
      response.status,
      detail
    )
  }

  return response.json()
}

function post(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

// ---------------------------------------------------------------- incidents

export const SAFETY_FIELDS = [
  'weapon_present',
  'violence',
  'injury',
  'immediate_danger',
] as const
export type SafetyField = (typeof SAFETY_FIELDS)[number]

/** Who an answer comes from: the language model, or a person at the console. */
export type Provenance = 'model' | 'human'

export interface Incident {
  call_type: string | null
  weapon_present: boolean | null
  violence: boolean | null
  injury: boolean | null
  immediate_danger: boolean | null
  caller_requests_cress: boolean | null
  timestamp: string | null
  location?: string | null
  evidence?: Record<string, string>
  provenance?: Partial<Record<SafetyField, Provenance>>
}

export interface ExtractionResult extends Incident {
  /** Field -> why the checks reset the model's answer to unknown. */
  downgraded: Record<string, string>
  warnings: string[]
  model: string | null
}

export const DESTINATIONS = [
  'cress',
  'cress_followup',
  'human_review',
  'police',
  'fire_ems',
  'crisis',
] as const
export type Destination = (typeof DESTINATIONS)[number]

export const DESTINATION_LABELS: Record<string, string> = {
  cress: 'CRESS',
  cress_followup: 'CRESS follow-up',
  human_review: 'Human review',
  police: 'Police',
  fire_ems: 'Fire / EMS',
  crisis: '988 / mobile crisis',
}

export interface DispatchDecision {
  destination: string
  rule_id: string
  reason: string
  missing_information: string[]
  eligible: boolean | null
  on_duty: boolean | null
  source: string | null
  rulebook_version: string | null
  /** True while a "no" the recommendation rests on is model-only. */
  provisional: boolean
  needs_confirmation: string[]
}

export function evaluateCall(
  incident: Incident,
  transcript: string
): Promise<DispatchDecision> {
  return request('Call evaluation', '/calls/evaluate', post({ incident, transcript }))
}

export function extractCall(transcript: string): Promise<ExtractionResult> {
  return request('Claude extraction', '/calls/extract', post({ transcript }))
}

export async function screenTranscript(
  text: string
): Promise<Record<string, string[]>> {
  const result = await request<{ tripwire_flags: Record<string, string[]> }>(
    'Transcript screening',
    '/calls/screen',
    post({ transcript: text })
  )
  return result.tripwire_flags
}

// ------------------------------------------------------------- live session

export interface TranscriptEvent {
  speaker: string
  text: string
  is_final: boolean
  t: number
  call_id?: string | null
}

// System events the backend sends in the transcript stream (speaker "system")
export const CALL_STARTED = '__call_started__'
export const CALL_ENDED = '__call_ended__'
export const CALL_ERROR = '__call_error__'

/** The page picks the ID, so it knows its own events before the first arrives. */
export function newCallId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID().replaceAll('-', '')
  }
  return `call${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

export async function startCallRecording(callId: string): Promise<void> {
  const result = await request<{ status: string }>(
    'Starting the call',
    `/calls/start?call_id=${encodeURIComponent(callId)}`,
    { method: 'POST' }
  )

  if (result.status === 'already_running') {
    throw new Error('A microphone session is already running')
  }
  if (result.status !== 'starting') {
    throw new Error(`Unexpected start status: ${result.status}`)
  }
}

export async function stopCallRecording(): Promise<string> {
  const result = await request<{ status: string }>('Ending the call', '/calls/end', {
    method: 'POST',
  })

  if (!['stopping', 'not_running'].includes(result.status)) {
    throw new Error(`Unexpected stop status: ${result.status}`)
  }
  return result.status
}

export interface Scenario {
  id: string
  title: string
  summary?: string
  segments: number
}

export function listScenarios(): Promise<Scenario[]> {
  return request('Listing scripted calls', '/scenarios')
}

export async function playScenario(id: string, callId: string): Promise<void> {
  const result = await request<{ status: string }>(
    'Starting the scripted call',
    `/scenarios/${encodeURIComponent(id)}/play?call_id=${encodeURIComponent(callId)}`,
    { method: 'POST' }
  )

  if (result.status === 'already_running') {
    throw new Error('A call or scripted scenario is already running')
  }
  if (result.status !== 'started') {
    throw new Error(`Unexpected play status: ${result.status}`)
  }
}

// ------------------------------------------------------------------ call log

export interface ReviewRecord {
  id: number
  created_at: string
  call_id: string
  call_source: string
  action: 'confirmed' | 'overridden'
  rule_id: string
  recommended_destination: string
  chosen_destination: string
  reason: string
  rulebook_version: string | null
  simulated_time: string | null
}

export interface ReviewRequest {
  call_id: string | null
  incident: Incident
  transcript: string
  action: 'confirmed' | 'overridden'
  chosen_destination?: string
  reason?: string
}

/** The server re-evaluates the incident itself and stores what it finds. */
export function recordReview(review: ReviewRequest): Promise<ReviewRecord> {
  return request('Saving the review', '/reviews', post(review))
}

export function fetchReviews(limit = 10): Promise<ReviewRecord[]> {
  return request('Loading the review log', `/reviews?limit=${limit}`)
}

export const REVIEWS_CSV_URL = '/api/reviews.csv'

// --------------------------------------------------------------------- audit

export type AuditGroup =
  | 'sent_to_cress_appropriately'
  | 'could_have_gone_to_cress'
  | 'should_not_have_gone_to_cress'
  | 'eligible_after_hours'

export interface AuditSummary extends Record<AuditGroup, number> {
  total_calls: number
  review_window: { start_hour: number; end_hour: number; label: string; days: string }
  rulebook_version: string
  could_have_gone_by_line: Record<string, number>
  by_rule: Record<string, number>
}

export interface AuditResult extends Record<AuditGroup, boolean> {
  call_id: string
  call_type: string | null
  source_line: string | null
  actual_destination: string
  recommended_destination: string
  rule_id: string
  reason: string
  source: string | null
  eligible: boolean | null
  on_duty: boolean | null
  timestamp: string | null
  local_hour: number | null
}

export interface AuditDataset {
  name: string
  year: number
  month: number
  seed: number
  synthetic: boolean
  calibrated_to_leap: boolean
  arrival_pattern: string
  count: number
}

export interface AuditResponse {
  dataset?: AuditDataset
  summary: AuditSummary
  results: AuditResult[]
}

export function fetchDemoAudit(count = 250, seed = 42): Promise<AuditResponse> {
  return request('Audit', `/audit/demo?count=${count}&seed=${seed}`)
}

export interface AuditRecordInput {
  call_id: string
  incident: Partial<Incident>
  actual_destination: string
  transcript?: string | null
}

/** Replay your own records (at most 5,000) through the rulebook. */
export function runAudit(records: AuditRecordInput[]): Promise<AuditResponse> {
  return request('Audit', '/audit/run', post({ records }))
}

// ---------------------------------------------------------------- simulation

export interface SimulationConfig {
  start_hour: number
  /** Above 24 the shift runs past midnight: 26 means 2 AM the next day. */
  end_hour: number
  teams: number
  average_duration_minutes: number
  include_weekends: boolean
  include_noise_complaints?: boolean
}

export interface SimulationPreset {
  id: string
  label: string
  note: string
  config: SimulationConfig
  schedule_coverage: number
}

export interface SimulationBaseline {
  baseline: SimulationConfig
  calls_per_week: number
  calibrated_to_leap: boolean
  presets: SimulationPreset[]
}

export function fetchBaseline(): Promise<SimulationBaseline> {
  return request('Loading the baseline', '/simulation/baseline')
}

export interface CoveragePoint {
  end_hour: number
  coverage: number
}

export async function fetchCoverage(
  startHour: number,
  includeWeekends: boolean
): Promise<CoveragePoint[]> {
  const result = await request<{ points: CoveragePoint[] }>(
    'Loading schedule coverage',
    `/simulation/coverage?start_hour=${startHour}&include_weekends=${includeWeekends}`
  )
  return result.points
}

export interface MetricBand {
  mean: number
  p10: number
  p90: number
}

export type ComparisonMetric =
  | 'calls_per_week'
  | 'share_handled'
  | 'missed_off_duty'
  | 'missed_busy'
  | 'utilization'

export interface ComparisonResult {
  replications: number
  horizon_weeks: number
  baseline: Record<ComparisonMetric, MetricBand>
  scenario: Record<ComparisonMetric, MetricBand>
  difference: Record<ComparisonMetric, MetricBand>
  assumptions: string[]
  calibrated_to_leap: boolean
}

export function compareScenarios(
  baseline: SimulationConfig,
  scenario: SimulationConfig,
  replications = 50
): Promise<ComparisonResult> {
  return request(
    'Simulation',
    '/simulation/compare',
    post({ baseline, scenario, replications })
  )
}
