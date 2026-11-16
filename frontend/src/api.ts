export interface AuditSummary {
  total_calls: number
  sent_to_cress_appropriately: number
  could_have_gone_to_cress: number
  should_not_have_gone_to_cress: number
  eligible_after_hours: number
}

export interface AuditResult {
  call_id: string
  actual_destination: string
  recommended_destination: string
  rule_id: string
  reason: string
  eligible: boolean | null
  on_duty: boolean | null
  timestamp: string | null
  sent_to_cress_appropriately: boolean
  could_have_gone_to_cress: boolean
  should_not_have_gone_to_cress: boolean
  eligible_after_hours: boolean
}

export interface AuditResponse {
  dataset: {
    name: string
    year: number
    month: number
    synthetic: boolean
    calibrated_to_leap: boolean
    arrival_pattern: string
    count: number
  }
  summary: AuditSummary
  results: AuditResult[]
}

export async function fetchDemoAudit(): Promise<AuditResponse> {
  const response = await fetch('/api/audit/demo')

  if (!response.ok) {
    throw new Error(`Audit API returned ${response.status}`)
  }

  return response.json()
}

export interface SimulationConfig {
  start_hour: number
  end_hour: number
  teams: number
  average_duration_minutes: number
  include_weekends: boolean
  include_noise_complaints?: boolean
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
}

export async function compareScenarios(
  baseline: SimulationConfig,
  scenario: SimulationConfig,
  replications = 50
): Promise<ComparisonResult> {
  const response = await fetch('/api/simulation/compare', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ baseline, scenario, replications }),
  })

  if (!response.ok) {
    throw new Error(`Simulation API returned ${response.status}`)
  }

  return response.json()
}

export interface Incident {
  call_type: string | null
  weapon_present: boolean | null
  violence: boolean | null
  injury: boolean | null
  immediate_danger: boolean | null
  caller_requests_cress: boolean | null
  timestamp: string | null
  evidence?: Record<string, string>
}

export interface DispatchDecision {
  destination: string
  rule_id: string
  reason: string
  missing_information: string[]
  eligible: boolean | null
  on_duty: boolean | null
  source: string | null
}

export async function evaluateCall(
  incident: Incident,
  transcript: string
): Promise<DispatchDecision> {
  const response = await fetch('/api/calls/evaluate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ incident, transcript }),
  })

  if (!response.ok) {
    throw new Error(`Call evaluation failed: ${response.status}`)
  }

  return response.json()
}

export async function extractCall(
  transcript: string
): Promise<Incident> {
  const response = await fetch('/api/calls/extract', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ transcript }),
  })

  if (!response.ok) {
    throw new Error(`Claude extraction failed: ${response.status}`)
  }

  return response.json()
}

export interface TranscriptEvent {
  speaker: string
  text: string
  is_final: boolean
  t: number
}

export async function startCallRecording(): Promise<void> {
  const response = await fetch('/api/calls/start', {
    method: 'POST',
  })

  if (!response.ok) {
    throw new Error(`Failed to start recording: ${response.status}`)
  }

  const result = await response.json()

  if (result.status === 'already_running') {
    throw new Error('A microphone session is already running')
  }

  if (result.status !== 'starting') {
    throw new Error(`Unexpected start status: ${result.status}`)
  }
}

export async function stopCallRecording(): Promise<string> {
  const response = await fetch('/api/calls/end', {
    method: 'POST',
  })

  if (!response.ok) {
    throw new Error(`Failed to stop recording: ${response.status}`)
  }

  const result = await response.json()

  if (!['stopping', 'not_running'].includes(result.status)) {
    throw new Error(`Unexpected stop status: ${result.status}`)
  }

  return result.status
}

// System events the backend sends in the transcript stream (speaker "system")
export const CALL_STARTED = '__call_started__'
export const CALL_ENDED = '__call_ended__'
export const CALL_ERROR = '__call_error__'

export interface Scenario {
  id: string
  title: string
  segments: number
}

export async function listScenarios(): Promise<Scenario[]> {
  const response = await fetch('/api/scenarios')

  if (!response.ok) {
    throw new Error(`Failed to list scenarios: ${response.status}`)
  }

  return response.json()
}

export async function playScenario(id: string): Promise<void> {
  const response = await fetch(
    `/api/scenarios/${encodeURIComponent(id)}/play`,
    { method: 'POST' }
  )

  if (!response.ok) {
    throw new Error(`Failed to play scenario: ${response.status}`)
  }

  const result = await response.json()

  if (result.status === 'already_running') {
    throw new Error('A call or scripted scenario is already running')
  }

  if (result.status !== 'started') {
    throw new Error(`Unexpected play status: ${result.status}`)
  }
}

export async function screenTranscript(
  text: string
): Promise<Record<string, string[]>> {
  const response = await fetch('/api/calls/screen', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ transcript: text }),
  })

  if (!response.ok) {
    throw new Error(`Transcript screening failed: ${response.status}`)
  }

  const result = await response.json()

  return result.tripwire_flags
}
