// Charts for the What-If and Monthly Audit screens (Recharts).
//
// Colours are categorical slots checked for colour-blind separation and
// contrast on this app's dark surface. Text never takes a series colour, each
// chart has a legend when it has more than one series, and every chart sits
// next to a table of the same numbers.

import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { AuditResult, ComparisonResult, CoveragePoint } from './api'
import {
  AUDIT_SERIES,
  auditGroupCounts,
  callsByHour,
  clockLabel,
  comparisonBars,
} from './chartData'

const SERIES = { first: '#3987e5', second: '#d95926', third: '#199e70' }
const NEUTRAL = '#64748b'
const INK = '#94a3b8'
const GRID = '#263244'

const axis = { stroke: GRID, tick: { fill: INK, fontSize: 12 } }

// Legend text stays in ink; the swatch beside it carries the series colour.
// Series keep the order they are declared in, not alphabetical order.
const legend = {
  itemSorter: null,
  wrapperStyle: { fontSize: 13, paddingTop: 6 },
  formatter: (value: string) => <span style={{ color: '#cbd5e1' }}>{value}</span>,
}
const tooltip = {
  contentStyle: {
    background: '#0b1120',
    border: `1px solid ${GRID}`,
    borderRadius: 8,
    color: '#e2e8f0',
    fontSize: 13,
  },
  cursor: { fill: 'rgba(148, 163, 184, 0.08)' },
}

function Figure({
  title,
  note,
  children,
}: {
  title: string
  note: string
  children: React.ReactElement
}) {
  return (
    <figure className="chart">
      <figcaption>
        <strong>{title}</strong>
        <span>{note}</span>
      </figcaption>
      <div className="chart-plot">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </figure>
  )
}

/** Today's schedule vs the proposed one, in calls per week, with the p10 to
 * p90 spread across replications as whiskers. */
export function ComparisonChart({ result }: { result: ComparisonResult }) {
  const data = comparisonBars(result)
  const one = (value: unknown) => Number(value).toFixed(1)

  return (
    <Figure
      title="Eligible calls per week: where they go"
      note={`Synthetic calls. Bars are the mean of ${result.replications} simulated ${result.horizon_weeks}-week runs; whiskers are p10 to p90.`}
    >
      <BarChart data={data} barGap={2} margin={{ top: 12, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="metric" {...axis} tickLine={false} />
        <YAxis {...axis} tickLine={false} axisLine={false} width={36} />
        <Tooltip {...tooltip} formatter={(value) => `${one(value)} per week`} />
        <Legend {...legend} />
        <Bar dataKey="today" name="Today's schedule (ceiling)" fill={SERIES.first} radius={[4, 4, 0, 0]} maxBarSize={48}>
          <ErrorBar dataKey="todaySpread" width={6} stroke="#e2e8f0" strokeWidth={1.5} />
        </Bar>
        <Bar dataKey="proposed" name="Proposed" fill={SERIES.second} radius={[4, 4, 0, 0]} maxBarSize={48}>
          <ErrorBar dataKey="proposedSpread" width={6} stroke="#e2e8f0" strokeWidth={1.5} />
        </Bar>
      </BarChart>
    </Figure>
  )
}

/** Share of call arrivals inside the schedule as the end hour moves. Pure
 * arithmetic on the arrival model: no teams, no simulation. */
export function CoverageChart({
  points,
  todayEnd,
  proposedEnd,
}: {
  points: CoveragePoint[]
  todayEnd: number
  proposedEnd: number
}) {
  const data = points.map((point) => ({
    ...point,
    percent: Math.round(point.coverage * 1000) / 10,
  }))
  const marks = [
    { hour: todayEnd, label: 'today', colour: NEUTRAL },
    { hour: proposedEnd, label: 'proposed', colour: SERIES.second },
  ].filter(
    (mark, index, all) =>
      data.some((point) => point.end_hour === mark.hour) &&
      all.findIndex((other) => other.hour === mark.hour) === index
  )

  return (
    <Figure
      title="What each extra hour is worth"
      note="Share of synthetic call arrivals inside the schedule, by the hour the shift ends (start hour and days as set above). Before any team limits."
    >
      <LineChart data={data} margin={{ top: 22, right: 40, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis
          dataKey="end_hour"
          type="number"
          domain={['dataMin', 'dataMax']}
          tickCount={Math.min(data.length, 9)}
          tickFormatter={clockLabel}
          {...axis}
          tickLine={false}
        />
        <YAxis
          {...axis}
          tickLine={false}
          axisLine={false}
          width={44}
          domain={[0, 100]}
          tickFormatter={(value) => `${value}%`}
        />
        <Tooltip
          {...tooltip}
          cursor={{ stroke: INK, strokeDasharray: '3 3' }}
          labelFormatter={(hour) => `Shift ends at ${clockLabel(Number(hour))}`}
          formatter={(value) => [`${value}%`, 'Arrivals covered']}
        />
        {marks.map((mark) => (
          <ReferenceLine
            key={mark.label}
            x={mark.hour}
            stroke={mark.colour}
            strokeDasharray="4 4"
            label={{ value: mark.label, position: 'top', fill: '#e2e8f0', fontSize: 12 }}
          />
        ))}
        <Line
          dataKey="percent"
          name="Arrivals covered"
          stroke={SERIES.first}
          strokeWidth={2}
          dot={{ r: 3, fill: SERIES.first, strokeWidth: 0 }}
          activeDot={{ r: 5 }}
          isAnimationActive={false}
        />
      </LineChart>
    </Figure>
  )
}

/** The four review groups. One measure, so one colour; the axis names them. */
export function AuditGroupsChart({
  results,
  windowLabel,
}: {
  results: AuditResult[]
  windowLabel: string
}) {
  const data = auditGroupCounts(results, windowLabel)

  return (
    <Figure
      title="The four review groups"
      note="Synthetic records. A call can be in more than one group, and most are in none."
    >
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 36, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" allowDecimals={false} {...axis} tickLine={false} />
        <YAxis
          type="category"
          dataKey="group"
          width={150}
          stroke={GRID}
          tick={{ fill: INK, fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip {...tooltip} formatter={(value) => [`${value} calls`, 'In this group']} />
        <Bar
          dataKey="calls"
          fill={SERIES.first}
          radius={[0, 4, 4, 0]}
          maxBarSize={22}
          label={{ position: 'right', fill: '#e2e8f0', fontSize: 12 }}
        />
      </BarChart>
    </Figure>
  )
}

/** When calls arrived, split by what the audit found. */
export function CallsByHourChart({ results }: { results: AuditResult[] }) {
  const data = callsByHour(results)
  const colours = [SERIES.first, SERIES.second, SERIES.third, NEUTRAL]

  return (
    <Figure
      title="Calls by hour of day"
      note="Synthetic records, local time. Each call is counted once, under its first matching group."
    >
      <BarChart data={data} barCategoryGap={2} margin={{ top: 12, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="hour" interval={2} tickFormatter={clockLabel} {...axis} tickLine={false} />
        <YAxis allowDecimals={false} {...axis} tickLine={false} axisLine={false} width={32} />
        <Tooltip {...tooltip} labelFormatter={(hour) => `${clockLabel(Number(hour))} to ${clockLabel(Number(hour) + 1)}`} />
        <Legend {...legend} />
        {AUDIT_SERIES.map((series, index) => (
          <Bar
            key={series.key}
            dataKey={series.key}
            name={series.label}
            stackId="calls"
            fill={colours[index]}
            stroke="#111827"
            strokeWidth={1}
          />
        ))}
      </BarChart>
    </Figure>
  )
}
