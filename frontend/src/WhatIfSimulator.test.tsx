import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import WhatIfSimulator from './WhatIfSimulator'

vi.mock('./api', async (original) => ({
  ...(await original<typeof api>()),
  fetchBaseline: vi.fn(),
  fetchCoverage: vi.fn(),
  compareScenarios: vi.fn(),
}))

// Recharts needs a measured container; the charts are covered by chartData tests.
vi.mock('./charts', () => ({
  ComparisonChart: () => <div data-testid="comparison-chart" />,
  CoverageChart: () => <div data-testid="coverage-chart" />,
}))

const mocked = vi.mocked(api)
const band = (mean: number) => ({ mean, p10: mean - 1, p90: mean + 1 })
const metrics = {
  calls_per_week: band(8), share_handled: band(0.22), missed_off_duty: band(100),
  missed_busy: band(0), utilization: band(0.1),
}
const baseline = {
  start_hour: 8, end_hour: 16, teams: 3, average_duration_minutes: 60,
  include_weekends: false, include_noise_complaints: false,
}
const leap = { ...baseline, start_hour: 9, end_hour: 26, include_weekends: true }

beforeEach(() => {
  mocked.fetchBaseline.mockResolvedValue({
    baseline,
    calls_per_week: 47,
    calibrated_to_leap: false,
    presets: [{
      id: 'leap_recommended', label: 'LEAP recommended: every day, 9 AM to 2 AM',
      note: 'The schedule LEAP recommends.', config: leap, schedule_coverage: 0.87,
    }],
  })
  mocked.fetchCoverage.mockResolvedValue([{ end_hour: 9, coverage: 0.03 }, { end_hour: 10, coverage: 0.07 }])
  mocked.compareScenarios.mockResolvedValue({
    replications: 50, horizon_weeks: 4, baseline: metrics, scenario: metrics,
    difference: { ...metrics, calls_per_week: band(5) },
    assumptions: ['Synthetic calls.'], calibrated_to_leap: false,
  })
})

describe('WhatIfSimulator', () => {
  it('blocks an impossible schedule and says why', async () => {
    render(<WhatIfSimulator />)

    fireEvent.change(screen.getByLabelText('End Hour', { exact: false }), { target: { value: '7' } })

    expect(screen.getByRole('alert')).toHaveTextContent('End hour must be after start hour.')
    expect(screen.getByRole('button', { name: 'Run Scenario' })).toBeDisabled()
    expect(mocked.compareScenarios).not.toHaveBeenCalled()
  })

  it('accepts 26 (2 AM) but not 27, and no overlap with the next shift', () => {
    render(<WhatIfSimulator />)
    const end = screen.getByLabelText('End Hour', { exact: false })
    const start = screen.getByLabelText('Start Hour')

    fireEvent.change(end, { target: { value: '26' } })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run Scenario' })).toBeEnabled()

    fireEvent.change(start, { target: { value: '1' } }) // 1 AM to 2 AM the next day: 25 hours
    expect(screen.getByRole('alert')).toHaveTextContent('must end before the next one starts')

    fireEvent.change(start, { target: { value: '9' } })
    fireEvent.change(end, { target: { value: '27' } })
    expect(screen.getByRole('alert')).toHaveTextContent('up to 26')
  })

  it("runs the LEAP preset against today's schedule from the rulebook", async () => {
    const user = userEvent.setup()
    render(<WhatIfSimulator />)

    await user.click(await screen.findByRole('button', { name: /LEAP recommended/ }))

    expect(mocked.compareScenarios).toHaveBeenCalledWith(baseline, leap)
    expect(await screen.findByText(/\+5\.0 more/)).toBeInTheDocument()
    expect(screen.getByLabelText('End Hour', { exact: false })).toHaveValue(26)
    expect(screen.getByTestId('comparison-chart')).toBeInTheDocument()
    // The numbers are also available as a table.
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('shows the backend error instead of a blank screen', async () => {
    const user = userEvent.setup()
    mocked.compareScenarios.mockRejectedValue(new Error('Simulation failed (500)'))
    render(<WhatIfSimulator />)

    await user.click(screen.getByRole('button', { name: 'Run Scenario' }))

    expect(await screen.findByText('Simulation failed (500)')).toBeInTheDocument()
  })
})
