// Regenerates the screenshots in this folder from the running app.
//
//   make dev                     (backend on :8000, frontend on :5173)
//   EXTRACTION_FIXTURE=<json> node docs/img/capture-screenshots.cjs
//
// Needs Playwright with Chromium (npm i -D playwright && npx playwright install
// chromium); it is not a dependency of this project.
//
// IMPORTANT: the capture environment has no Anthropic API key, so the
// "Extract with Claude" request is answered from EXTRACTION_FIXTURE: the
// hand-written ideal extraction in backend/eval/fixtures/demo_scripts.json
// after it has passed through the real evidence and hedge checks. The
// transcript stream, the tripwire, the rulebook, the call log, the audit and
// the simulator in the screenshots are the real backend. Scripted calls are
// played 4x faster than normal.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const out = __dirname
const fixtures = JSON.parse(fs.readFileSync(process.env.EXTRACTION_FIXTURE, 'utf8'))

;(async () => {
  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width: 1280, height: 860 },
    deviceScaleFactor: 2,
  })
  const page = await context.newPage()

  let script = 'routine_wellbeing'
  await page.route('**/api/calls/extract', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify(fixtures[script]) })
  )
  await page.route('**/api/scenarios/*/play*', (route) => {
    const url = new URL(route.request().url())
    url.searchParams.set('speed', '4')
    route.continue({ url: url.toString() })
  })

  const shot = async (name) => {
    await page.waitForTimeout(600)
    await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true })
    console.log('saved', name)
  }
  const card = (text) => page.locator('.decision-card', { hasText: text })

  await page.goto('http://localhost:5173/')
  await page.getByRole('button', { name: /Routine wellbeing check/ }).waitFor()

  // Routine call: CRESS is provisional until a person confirms the "no" answers
  await page.getByRole('button', { name: /Routine wellbeing check/ }).click()
  await card('PROVISIONAL RECOMMENDATION').waitFor({ timeout: 60000 })
  await shot('live-call-provisional')
  await page.getByRole('button', { name: /Confirm screening answers/ }).click()
  await card('RULE-BASED RECOMMENDATION').waitFor()
  await page.getByRole('button', { name: /Confirm recommendation/ }).click()
  await page.getByText(/Confirmed CRESS/).waitFor()

  // Hidden knife: the tripwire sends it to a human; the dispatcher overrides
  script = 'hidden_knife'
  await page.getByRole('button', { name: /hidden emergency/ }).click()
  await page.getByText('Safety words in the transcript').waitFor({ timeout: 60000 })
  await page.getByText('NO ACTIVE CALL').waitFor({ timeout: 60000 })
  await card('TRANSCRIPT-TRIPWIRE').waitFor()
  await page.getByLabel('Override to').selectOption('police')
  await page.getByLabel('Reason').fill('Caller heard a man say he has a knife.')
  await page.getByRole('button', { name: 'Override', exact: true }).click()
  await page.getByText(/Overrode Human review/).waitFor()
  await shot('live-call-tripwire')

  await page.getByRole('button', { name: 'Monthly Audit' }).click()
  await page.getByRole('button', { name: 'Run Synthetic Audit' }).click()
  await page.getByText('The four review groups').waitFor()
  await page.getByRole('button', { name: /Could have gone to CRESS/ }).first().click()
  await page.locator('.row-toggle').first().click()
  await page.waitForTimeout(1200)
  await shot('monthly-audit')

  await page.getByRole('button', { name: 'What-If Simulator' }).click()
  await page.getByRole('button', { name: /LEAP recommended/ }).click()
  await page.getByText(/calls CRESS could take per week/).waitFor({ timeout: 60000 })
  await page.waitForTimeout(1200)
  await shot('what-if-simulator')

  await browser.close()
})().catch((error) => {
  console.error(error)
  process.exit(1)
})
