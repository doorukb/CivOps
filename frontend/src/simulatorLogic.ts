// Validation for the What-If inputs. Mirrors the backend's rules so the
// button is disabled with a clear reason instead of answering 422.

import type { SimulationConfig } from './api'

export const MAX_END_HOUR = 26 // 2 AM the next day

// Used until GET /simulation/baseline answers, or if it cannot be reached.
export const FALLBACK_BASELINE: SimulationConfig = {
  start_hour: 8,
  end_hour: 16,
  teams: 3,
  average_duration_minutes: 60,
  include_weekends: false,
  include_noise_complaints: false,
}

/** Why this scenario cannot run, or null if it can. */
export function scenarioProblem(config: SimulationConfig): string | null {
  const whole = (value: number) => Number.isInteger(value)

  if (!whole(config.start_hour) || config.start_hour < 0 || config.start_hour > 23) {
    return 'Start hour must be a whole number from 0 to 23.'
  }
  if (!whole(config.end_hour) || config.end_hour > MAX_END_HOUR) {
    return `End hour must be a whole number up to ${MAX_END_HOUR} (26 = 2 AM the next day).`
  }
  if (config.end_hour <= config.start_hour) {
    return 'End hour must be after start hour.'
  }
  if (config.end_hour > 24 && config.end_hour - 24 > config.start_hour) {
    return 'A shift that runs past midnight must end before the next one starts.'
  }
  if (!whole(config.teams) || config.teams < 1 || config.teams > 20) {
    return 'Responder teams must be a whole number from 1 to 20.'
  }
  if (
    !whole(config.average_duration_minutes) ||
    config.average_duration_minutes < 5 ||
    config.average_duration_minutes > 240
  ) {
    return 'Minutes per call must be a whole number from 5 to 240.'
  }
  return null
}
