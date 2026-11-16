import { describe, expect, it } from 'vitest'
import type { AuditResult, ComparisonResult, SimulationConfig } from './api'
import {
  PAGE_SIZE,
  answer,
  groupsOf,
  pageCount,
  pageOf,
  parseCsv,
  parseRecords,
  recordedTime,
  toCsv,
  visibleRecords,
} from './auditLogic'
import { auditGroupCounts, callsByHour, clockLabel, comparisonBars } from './chartData'
import { FALLBACK_BASELINE, scenarioProblem } from './simulatorLogic'

const record = (patch: Partial<AuditResult>): AuditResult => ({
  call_id: 'SYN-0001',
  call_type: 'wellbeing_check',
  source_line: 'non_emergency',
  actual_destination: 'police',
  recommended_destination: 'cress',
  rule_id: 'CRESS-001',
  reason: 'Eligible incident during CRESS operating hours.',
  source: 'Illustrative eligibility assumption',
  eligible: true,
  on_duty: true,
  timestamp: '2026-11-16T10:00:00-05:00',
  local_hour: 10,
  sent_to_cress_appropriately: false,
  could_have_gone_to_cress: false,
  should_not_have_gone_to_cress: false,
  eligible_after_hours: false,
  ...patch,
})

describe('scenarioProblem', () => {
  const config = (patch: Partial<SimulationConfig>) => ({ ...FALLBACK_BASELINE, ...patch })

  it('accepts today and the LEAP schedule (9 AM to 2 AM)', () => {
    expect(scenarioProblem(FALLBACK_BASELINE)).toBeNull()
    expect(scenarioProblem(config({ start_hour: 9, end_hour: 26, include_weekends: true }))).toBeNull()
  })

  it.each([
    [{ start_hour: 20, end_hour: 8 }, /after start hour/],
    [{ end_hour: 27 }, /up to 26/],
    [{ start_hour: 0, end_hour: 26 }, /before the next one starts/],
    [{ end_hour: 16.5 }, /whole number/],
    [{ teams: 0 }, /1 to 20/],
    [{ teams: 21 }, /1 to 20/],
    [{ average_duration_minutes: 4 }, /5 to 240/],
    [{ start_hour: Number.NaN }, /0 to 23/],
  ])('rejects %j', (patch, problem) => {
    expect(scenarioProblem(config(patch))).toMatch(problem)
  })
})

describe('clockLabel', () => {
  it.each([[0, '12 AM'], [9, '9 AM'], [12, '12 PM'], [16, '4 PM'], [24, '12 AM'], [26, '2 AM']])(
    '%i -> %s',
    (hour, label) => expect(clockLabel(hour)).toBe(label)
  )
})

describe('comparisonBars', () => {
  const band = (mean: number, p10: number, p90: number) => ({ mean, p10, p90 })
  const result = {
    replications: 50,
    horizon_weeks: 4,
    baseline: {
      calls_per_week: band(8, 6, 10),
      missed_off_duty: band(100, 90, 112),
      missed_busy: band(0, 0, 0),
    },
    scenario: {
      calls_per_week: band(13, 11, 15),
      missed_off_duty: band(80, 72, 90),
      missed_busy: band(2, 0, 4),
    },
  } as unknown as ComparisonResult

  it('puts handled and missed calls on one per-week axis', () => {
    const [handled, offDuty, busy] = comparisonBars(result)
    expect(handled).toMatchObject({ today: 8, proposed: 13, todaySpread: [2, 2] })
    expect(offDuty).toMatchObject({ today: 25, proposed: 20, todaySpread: [2.5, 3] })
    expect(busy).toMatchObject({ today: 0, proposed: 0.5, proposedSpread: [0.5, 0.5] })
  })
})

describe('audit grouping and paging', () => {
  const results = [
    record({ call_id: 'A' }),
    record({ call_id: 'B', could_have_gone_to_cress: true }),
    record({ call_id: 'C', could_have_gone_to_cress: true, eligible_after_hours: true, local_hour: 17 }),
    record({ call_id: 'D', should_not_have_gone_to_cress: true, local_hour: null }),
  ]

  it('shows flagged records first and keeps their order', () => {
    expect(visibleRecords(results, null).map((r) => r.call_id)).toEqual(['B', 'C', 'D', 'A'])
  })

  it('filters by one group', () => {
    expect(visibleRecords(results, 'eligible_after_hours').map((r) => r.call_id)).toEqual(['C'])
    expect(groupsOf(results[2])).toEqual(['could_have_gone_to_cress', 'eligible_after_hours'])
  })

  it('pages through every record, not a fixed sample', () => {
    const many = Array.from({ length: 60 }, (_, i) => record({ call_id: `SYN-${i}` }))
    expect(pageCount(many.length)).toBe(3)
    expect(pageOf(many, 0)).toHaveLength(PAGE_SIZE)
    expect(pageOf(many, 2)).toHaveLength(10)
    expect(pageCount(0)).toBe(1)
  })

  it('counts each call once in the hour histogram and skips unknown hours', () => {
    const hours = callsByHour(results)
    expect(hours).toHaveLength(24)
    expect(hours[10]).toMatchObject({ couldHave: 1, other: 1 })
    expect(hours[17]).toMatchObject({ couldHave: 1 })
    const total = hours.reduce((sum, h) => sum + h.appropriate + h.couldHave + h.shouldNot + h.other, 0)
    expect(total).toBe(3)
  })

  it('labels the after-hours bar with the window from the rulebook', () => {
    const counts = auditGroupCounts(results, '4 PM to 8 PM')
    expect(counts.map((c) => c.calls)).toEqual([0, 2, 1, 1])
    expect(counts[3].group).toBe('Eligible, off duty, 4 PM to 8 PM')
  })
})

describe('recordedTime', () => {
  it("shows the call's own clock, not the browser's", () => {
    expect(recordedTime('2026-11-30T12:35:00-05:00')).toBe('2026-11-30 12:35 (UTC-05:00)')
    expect(recordedTime('2026-11-30T17:35:00Z')).toBe('2026-11-30 17:35 (UTC)')
    expect(recordedTime('2026-11-30T12:35:00')).toBe('2026-11-30 12:35 (no time zone)')
    expect(recordedTime(null)).toBe('no timestamp')
  })
})

describe('CSV export', () => {
  it('quotes commas and neutralises formulas', () => {
    const csv = toCsv([record({ reason: 'Reported safety concerns: injury, violence', source: '=HYPERLINK("x")' })])
    const [header, row] = csv.trim().split('\n')
    expect(header.startsWith('call_id,timestamp,call_type')).toBe(true)
    expect(row).toContain('"Reported safety concerns: injury, violence"')
    expect(row).toContain(`"'=HYPERLINK(""x"")"`)
  })
})

describe('reading an uploaded file', () => {
  it('parses quoted CSV fields and CRLF', () => {
    expect(parseCsv('a,b\r\n"x, y","say ""hi"""\r\n\r\n')).toEqual([
      ['a', 'b'],
      ['x, y', 'say "hi"'],
    ])
  })

  it('never turns a blank or unreadable answer into "no"', () => {
    expect(answer('no')).toBe(false)
    expect(answer('TRUE')).toBe(true)
    expect(answer('')).toBeNull()
    expect(answer(undefined)).toBeNull()
    expect(answer('n/a')).toBeNull()
  })

  it('builds records from CSV, leaving missing answers unknown', () => {
    const csv = [
      'call_id,actual_destination,call_type,timestamp,weapon_present,violence,injury',
      'C-1,police,wellbeing_check,2026-11-16T10:00:00-05:00,no,no,',
    ].join('\n')
    expect(parseRecords(csv, 'calls.csv')).toEqual([
      {
        call_id: 'C-1',
        actual_destination: 'police',
        transcript: null,
        incident: {
          call_type: 'wellbeing_check',
          timestamp: '2026-11-16T10:00:00-05:00',
          weapon_present: false,
          violence: false,
          injury: null,
          immediate_danger: null,
        },
      },
    ])
  })

  it('accepts a JSON array or {records: [...]}', () => {
    const records = [{ call_id: 'C-1', incident: {}, actual_destination: 'police' }]
    expect(parseRecords(JSON.stringify(records), 'x.json')).toEqual(records)
    expect(parseRecords(JSON.stringify({ records }), 'x.json')).toEqual(records)
  })

  it.each([
    ['{"a": 1}', 'x.json', /JSON array/],
    ['{oops', 'x.json', /not valid JSON/],
    ['[]', 'x.json', /no records/],
    ['name,value\n1,2', 'x.csv', /"call_id" column/],
    ['', 'x.csv', /empty/],
  ])('explains what is wrong with %j', (text, name, problem) => {
    expect(() => parseRecords(text, name)).toThrow(problem)
  })

  it('refuses more records than the backend accepts', () => {
    const many = Array.from({ length: 5001 }, (_, i) => ({
      call_id: `C-${i}`, incident: {}, actual_destination: 'police',
    }))
    expect(() => parseRecords(JSON.stringify(many), 'x.json')).toThrow(/limit is 5000/)
  })
})
