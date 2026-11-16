// Pure helpers for the Monthly Audit screen: filtering, paging, CSV in and out.

import { SAFETY_FIELDS } from './api'
import type { AuditGroup, AuditRecordInput, AuditResult } from './api'

export const MAX_UPLOAD_RECORDS = 5000 // the backend's limit for /audit/run
export const PAGE_SIZE = 25

export const GROUP_LABELS: Record<AuditGroup, string> = {
  sent_to_cress_appropriately: 'Sent to CRESS appropriately',
  could_have_gone_to_cress: 'Could have gone to CRESS',
  should_not_have_gone_to_cress: 'Should not have gone to CRESS',
  eligible_after_hours: 'Eligible, off duty, after hours',
}

export const GROUPS = Object.keys(GROUP_LABELS) as AuditGroup[]

export function groupsOf(record: AuditResult): AuditGroup[] {
  return GROUPS.filter((group) => record[group] === true)
}

/** Records in one group (or all). Flagged records first; the sort is stable,
 * so call-ID order is kept within each half. */
export function visibleRecords(
  results: AuditResult[],
  group: AuditGroup | null
): AuditResult[] {
  const chosen = group ? results.filter((record) => record[group]) : results
  return [...chosen].sort(
    (a, b) => Number(groupsOf(b).length > 0) - Number(groupsOf(a).length > 0)
  )
}

export function pageCount(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_SIZE))
}

export function pageOf<T>(items: T[], page: number): T[] {
  return items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
}

/** A call's own clock time, exactly as recorded ("2026-11-30T12:35:00-05:00"
 * -> "2026-11-30 12:35 (UTC-05:00)"). Converting to the browser's time zone
 * would show an on-duty call at an off-duty hour. */
export function recordedTime(timestamp: string | null): string {
  if (!timestamp) return 'no timestamp'
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::[\d.]+)?(Z|[+-]\d{2}:\d{2})?$/.exec(timestamp)
  if (!match) return timestamp
  const [, date, time, offset] = match
  return `${date} ${time}${offset ? ` (UTC${offset === 'Z' ? '' : offset})` : ' (no time zone)'}`
}

// ------------------------------------------------------------------ CSV out

/** Free text must not run as a formula when the file is opened in a spreadsheet. */
function cell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value)
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

const EXPORT_COLUMNS = [
  'call_id', 'timestamp', 'call_type', 'source_line', 'actual_destination',
  'recommended_destination', 'rule_id', 'reason', 'source', 'eligible', 'on_duty',
  ...GROUPS,
] as const

export function toCsv(results: AuditResult[]): string {
  const rows = results.map((record) =>
    EXPORT_COLUMNS.map((column) => cell(record[column])).join(',')
  )
  return [EXPORT_COLUMNS.join(','), ...rows].join('\n') + '\n'
}

// ------------------------------------------------------------------- CSV in

/** Minimal RFC 4180 reader: quoted fields, doubled quotes, CRLF or LF. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false

  for (let i = 0; i < text.length; i++) {
    const char = text[i]

    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"'
        i++
      } else if (char === '"') {
        quoted = false
      } else {
        field += char
      }
    } else if (char === '"') {
      quoted = true
    } else if (char === ',') {
      row.push(field)
      field = ''
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[i + 1] === '\n') i++
      row.push(field)
      field = ''
      if (row.some((value) => value !== '')) rows.push(row)
      row = []
    } else {
      field += char
    }
  }

  row.push(field)
  if (row.some((value) => value !== '')) rows.push(row)
  return rows
}

/** "true"/"yes"/"1" -> true, "false"/"no"/"0" -> false, anything else -> null.
 * Unknown is never "no": a blank or unreadable answer stays unknown. */
export function answer(value: string | undefined): boolean | null {
  const text = (value ?? '').trim().toLowerCase()
  if (['true', 'yes', 'y', '1'].includes(text)) return true
  if (['false', 'no', 'n', '0'].includes(text)) return false
  return null
}

function recordsFromCsv(text: string): AuditRecordInput[] {
  const [header, ...rows] = parseCsv(text)
  if (!header) throw new Error('The file is empty.')

  const columns = header.map((name) => name.trim().toLowerCase())
  for (const required of ['call_id', 'actual_destination']) {
    if (!columns.includes(required)) {
      throw new Error(`The CSV needs a "${required}" column.`)
    }
  }

  return rows.map((row) => {
    const get = (name: string) => row[columns.indexOf(name)]?.trim() || undefined
    return {
      call_id: get('call_id') ?? '',
      actual_destination: get('actual_destination') ?? '',
      transcript: get('transcript') ?? null,
      incident: {
        call_type: get('call_type') ?? null,
        timestamp: get('timestamp') ?? null,
        ...Object.fromEntries(SAFETY_FIELDS.map((field) => [field, answer(get(field))])),
      },
    }
  })
}

function recordsFromJson(text: string): AuditRecordInput[] {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    throw new Error('The file is not valid JSON.')
  }

  const records =
    value && typeof value === 'object' && 'records' in value
      ? (value as { records: unknown }).records
      : value
  if (!Array.isArray(records)) {
    throw new Error('Expected a JSON array of records, or {"records": [...]}.')
  }
  return records as AuditRecordInput[]
}

/** Read an uploaded file into audit records. The backend validates each one;
 * this only checks shape and size so the error arrives before the upload. */
export function parseRecords(text: string, filename: string): AuditRecordInput[] {
  const looksLikeJson = /\.json$/i.test(filename) || /^\s*[[{]/.test(text)
  const records = looksLikeJson ? recordsFromJson(text) : recordsFromCsv(text)

  if (records.length === 0) throw new Error('The file has no records.')
  if (records.length > MAX_UPLOAD_RECORDS) {
    throw new Error(
      `The file has ${records.length} records; the limit is ${MAX_UPLOAD_RECORDS}.`
    )
  }
  return records
}
