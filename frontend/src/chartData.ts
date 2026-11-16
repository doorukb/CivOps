// Shaping API results for the charts. Pure functions, unit-tested.

import type { AuditResult, ComparisonResult, MetricBand } from './api'

/** 16 -> "4 PM", 24 -> "12 AM", 26 -> "2 AM" (the next day). */
export function clockLabel(hour: number): string {
  const h = ((hour % 24) + 24) % 24
  return `${h % 12 || 12} ${h < 12 ? 'AM' : 'PM'}`
}

export interface ComparisonBar {
  metric: string
  today: number
  proposed: number
  /** [distance below the mean, distance above it], as Recharts expects. */
  todaySpread: [number, number]
  proposedSpread: [number, number]
}

/** Handled and missed calls, all in calls per week so they share one axis. */
export function comparisonBars(result: ComparisonResult): ComparisonBar[] {
  const perWeek = (band: MetricBand, divisor: number) => ({
    mean: band.mean / divisor,
    spread: [
      Math.max(0, (band.mean - band.p10) / divisor),
      Math.max(0, (band.p90 - band.mean) / divisor),
    ] as [number, number],
  })

  const rows: [string, keyof ComparisonResult['baseline'], number][] = [
    ['Handled by CRESS', 'calls_per_week', 1],
    ['Missed: off duty', 'missed_off_duty', result.horizon_weeks],
    ['Missed: every team busy', 'missed_busy', result.horizon_weeks],
  ]

  return rows.map(([metric, key, divisor]) => {
    const today = perWeek(result.baseline[key], divisor)
    const proposed = perWeek(result.scenario[key], divisor)
    return {
      metric,
      today: today.mean,
      proposed: proposed.mean,
      todaySpread: today.spread,
      proposedSpread: proposed.spread,
    }
  })
}

export function auditGroupCounts(results: AuditResult[], windowLabel: string) {
  const count = (flag: keyof AuditResult) =>
    results.filter((record) => record[flag] === true).length

  return [
    { group: 'Sent to CRESS appropriately', calls: count('sent_to_cress_appropriately') },
    { group: 'Could have gone to CRESS', calls: count('could_have_gone_to_cress') },
    { group: 'Should not have gone to CRESS', calls: count('should_not_have_gone_to_cress') },
    { group: `Eligible, off duty, ${windowLabel}`, calls: count('eligible_after_hours') },
  ]
}

export const AUDIT_SERIES = [
  { key: 'appropriate', label: 'Sent to CRESS appropriately' },
  { key: 'couldHave', label: 'Could have gone to CRESS' },
  { key: 'shouldNot', label: 'Should not have gone to CRESS' },
  { key: 'other', label: 'No flag' },
] as const

export type AuditSeriesKey = (typeof AUDIT_SERIES)[number]['key']

/** The three routing groups cannot overlap; everything else is "no flag". */
export function auditSeriesOf(record: AuditResult): AuditSeriesKey {
  if (record.sent_to_cress_appropriately) return 'appropriate'
  if (record.could_have_gone_to_cress) return 'couldHave'
  if (record.should_not_have_gone_to_cress) return 'shouldNot'
  return 'other'
}

export function callsByHour(results: AuditResult[]) {
  const hours = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    appropriate: 0,
    couldHave: 0,
    shouldNot: 0,
    other: 0,
  }))

  for (const record of results) {
    if (record.local_hour === null || record.local_hour === undefined) continue
    hours[record.local_hour][auditSeriesOf(record)] += 1
  }

  return hours
}
