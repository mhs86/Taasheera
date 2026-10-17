import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import { afterEach, beforeEach, test } from 'node:test'
import { dom } from './dom-setup.mjs'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'

for (const name of ['Node', 'Element', 'HTMLAnchorElement', 'HTMLTextAreaElement', 'HTMLSelectElement',
  'MutationObserver', 'getComputedStyle', 'File', 'Event', 'KeyboardEvent']) {
  globalThis[name] ??= dom.window[name]
}
window.matchMedia ??= () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
window.scrollTo = () => {}
URL.createObjectURL = () => 'blob:passport-photo'
URL.revokeObjectURL = () => {}

registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('.svg')) return { format: 'module', source: `export default ${JSON.stringify(url)}`, shortCircuit: true }
    return nextLoad(url, context)
  },
})

const { routes } = await import('../src/routes.tsx')
const { formatAnswer, formatDate, safeReturnPath, returnedPassport } = await import('../src/application/format.ts')
const { safePage } = await import('../src/activityPage.ts')

// ICAO 9303 specimen passport ("Utopia"). Never use real passport data in tests.
const SPECIMEN = {
  surname: 'ERIKSSON', given_names: 'ANNA MARIA', document_number: 'L898902C3', nationality: 'UTO',
  issuing_country: 'UTO', birth_date: '1974-08-12', sex: 'F', expiry_date: '2030-04-15', personal_number: 'ZE184226B',
}
const APP = 'b'.repeat(32)
const UPLOAD = 'a'.repeat(32)
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const question = (id, type, prompt, extra = {}) => ({
  id, step_id: 'eligibility', type, prompt, help: null, required: true, options: null, max_length: 200,
  date_min: null, date_max: null, ...extra,
})
const PURPOSE = question('purpose', 'choice', "What's the main purpose of your trip?", {
  options: [{ value: 'tourism', label: 'Tourism' }, { value: 'business', label: 'Business' }],
})
const LONG_STAY = question('stay_over_90_days', 'yes_no', 'Will you stay more than 90 days?')
const PASSPORT = question('passport', 'passport', "Let's add your passport.", { step_id: 'passport' })
const ARRIVAL = question('arrival_date', 'date', 'When do you plan to arrive?',
  { step_id: 'trip', date_min: '2026-10-19', date_max: '2027-04-18' })

function state(answers, current, extra = {}) {
  return {
    id: APP, title: 'Schengen short-stay visa (type C)', status: current ? 'DRAFT' : 'ANSWERS_COMPLETE',
    updated_at: '2026-10-18T10:00:00Z', destination: 'SCHENGEN', visa_type: 'short_stay',
    steps: [{ id: 'eligibility', title: 'Eligibility' }, { id: 'passport', title: 'Passport' }],
    progress: { step_number: 1, step_count: 2, step_title: 'Eligibility', answered: answers.length, total: 4 },
    answers: answers.map(([q, value, source = 'traveler']) => ({ question: q, value, source })),
    current, stopped: null, cleared: [], ...extra,
  }
}

let handlers
let calls
globalThis.fetch = async (url, options = {}) => {
  const key = `${options.method ?? 'GET'} ${url}`
  calls.push({ key, body: options.body })
  const handler = handlers[key]
  assert.ok(handler, `Unexpected request: ${key}`)
  return handler(options)
}
const signedIn = extra => ({
  'POST /auth/refresh': () => json({ access_token: 'token' }),
  'GET /auth/me': () => json({ id: 1, name: 'Anna', email: 'anna@example.com' }),
  'POST /activity/events': () => new Response(null, { status: 204 }),
  ...extra,
})
const bodyOf = key => JSON.parse(calls.filter(call => call.key === key).at(-1).body)

let root
let container
async function render(path) {
  container = document.createElement('div')
  document.body.append(container)
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  root = createRoot(container)
  await act(async () => root.render(createElement(RouterProvider, { router })))
  await settle()
  return router
}
const settle = () => act(() => new Promise(resolve => setTimeout(resolve, 30)))
const $ = selector => container.querySelector(selector)
const text = () => container.textContent
const button = label => [...container.querySelectorAll('button, a')].find(b => b.textContent.trim() === label)
async function click(element) {
  await act(async () => element.click())
  await settle()
}
async function type(element, value) {
  const prototype = element instanceof window.HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
  await act(async () => element.dispatchEvent(new window.Event('input', { bubbles: true })))
}
async function submit(form) {
  await act(async () => form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
  await settle()
}

beforeEach(() => { calls = []; handlers = {} })
afterEach(() => {
  if (root) act(() => root.unmount())
  container?.remove()
  root = container = undefined
  document.body.replaceChildren()
})

// --- Pure helpers ------------------------------------------------------------

test('answers read back in plain language', () => {
  assert.equal(formatAnswer(PURPOSE, 'business'), 'Business')
  assert.equal(formatAnswer(LONG_STAY, false), 'No')
  assert.equal(formatAnswer(ARRIVAL, '2027-01-10'), '10 January 2027')
  assert.equal(formatAnswer(question('c', 'country', 'Country?'), 'D'), 'Germany')
  assert.equal(formatAnswer(question('a', 'address', 'Address?'),
    { line1: '1 Example Street', line2: '', city: 'Beirut', region: '', postal_code: '', country: 'LBN' }),
  '1 Example Street, Beirut, Lebanon')
  assert.equal(formatAnswer(PASSPORT, SPECIMEN), 'ERIKSSON, ANNA MARIA · passport L898902C3 · expires 15 April 2030')
  assert.equal(formatAnswer(question('t', 'text', 'Former surname?', { required: false }), ''), 'Nothing to add')
  assert.equal(formatDate('2028-02-29'), '29 February 2028')
})

test('the passport page only links back to an application on this site', () => {
  assert.equal(safeReturnPath(`?return=/apply/${APP}`), `/apply/${APP}`)
  assert.equal(safeReturnPath('?return=https://evil.example/apply'), null)
  assert.equal(safeReturnPath('?return=//evil.example'), null)
  assert.equal(safeReturnPath(`?return=/apply/${APP}/../../account`), null)
  assert.equal(safeReturnPath(''), null)
  assert.equal(returnedPassport(`?passport=${UPLOAD}`), UPLOAD)
  assert.equal(returnedPassport('?passport=../../x'), null)
})

test('application pages have their own activity page id, without the id itself', () => {
  assert.equal(safePage('/apply', ''), 'apply')
  assert.equal(safePage(`/apply/${APP}`, ''), 'apply')
  assert.equal(safePage('/apply/not-an-id', ''), 'not-found')
})

// --- Starting --------------------------------------------------------------

test('starting an application opens its chat at the first question', async () => {
  handlers = signedIn({
    'GET /applications/options': () => json([{ destination: 'SCHENGEN', visa_type: 'short_stay', title: 'Schengen short-stay visa (type C)' }]),
    'GET /applications': () => json([]),
    'POST /applications': () => json(state([], PURPOSE), 201),
    [`GET /applications/${APP}`]: () => json(state([], PURPOSE)),
  })
  const router = await render('/apply')
  assert.match(text(), /Schengen short-stay visa \(type C\)/)
  await click(button('Start this application'))
  assert.deepEqual(bodyOf('POST /applications'), { destination: 'SCHENGEN', visa_type: 'short_stay' })
  assert.equal(router.state.location.pathname, `/apply/${APP}`)
  assert.match(text(), /What's the main purpose of your trip\?/)
  assert.match(text(), /Step 1 of 2/)
  assert.match(text(), /0 of 4 questions answered/)
})

test('signed-out visitors are asked to sign in', async () => {
  handlers = { 'POST /auth/refresh': () => json({ detail: 'No session' }, 401) }
  await render('/apply')
  assert.match(text(), /Please sign in to start an application/)
})

// --- Answering -------------------------------------------------------------

test('a choice answer is saved at once and the next question follows', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([], PURPOSE)),
    [`PUT /applications/${APP}/answers/purpose`]: () => json(state([[PURPOSE, 'business']], LONG_STAY)),
  })
  await render(`/apply/${APP}`)
  await click(button('Business'))
  assert.deepEqual(bodyOf(`PUT /applications/${APP}/answers/purpose`), { value: 'business' })
  assert.match(text(), /Will you stay more than 90 days\?/)
  assert.ok($('.chat-reply').textContent.startsWith('Business'))
  assert.match(text(), /1 of 4 questions answered/)
})

test('yes or no answers send real booleans', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([], LONG_STAY)),
    [`PUT /applications/${APP}/answers/stay_over_90_days`]: () => json(state([[LONG_STAY, false]], PASSPORT)),
  })
  await render(`/apply/${APP}`)
  await click(button('No'))
  assert.deepEqual(bodyOf(`PUT /applications/${APP}/answers/stay_over_90_days`), { value: false })
})

test("the server's reason for rejecting an answer is shown next to it", async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([], ARRIVAL)),
    [`PUT /applications/${APP}/answers/arrival_date`]: () => json({ detail: 'Your arrival date needs to be in the future.' }, 422),
  })
  await render(`/apply/${APP}`)
  const input = $('input[type="date"]')
  assert.equal(input.min, '2026-10-19')
  assert.equal(input.max, '2027-04-18')
  await type(input, '2026-10-01')
  await submit(input.form)
  assert.deepEqual(bodyOf(`PUT /applications/${APP}/answers/arrival_date`), { value: '2026-10-01' })
  assert.equal($('[role="alert"]').textContent, 'Your arrival date needs to be in the future.')
  assert.equal(input.getAttribute('aria-invalid'), 'true')
})

test('changing an earlier answer explains the answers it cleared', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([[PURPOSE, 'tourism'], [LONG_STAY, false]], PASSPORT)),
    [`PUT /applications/${APP}/answers/purpose`]: () => json(state([[PURPOSE, 'business']], LONG_STAY, { cleared: ['stay_over_90_days'] })),
  })
  await render(`/apply/${APP}`)
  await click($('[aria-label^="Change your answer to: What\'s the main purpose"]'))
  assert.equal(button('Tourism').getAttribute('aria-pressed'), 'true')
  await click(button('Business'))
  assert.match(text(), /one later answer no longer fits/)
  assert.match(text(), /Will you stay more than 90 days\?/)
})

test('a stopped application says why and asks no question', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([[LONG_STAY, true]], null, {
      status: 'INELIGIBLE', stopped: 'A short-stay visa covers at most 90 days in any 180-day period.',
    })),
  })
  await render(`/apply/${APP}`)
  assert.match($('.bubble-stop').textContent, /covers at most 90 days/)
  assert.equal($('#current-question'), null)
})

test('an application from another account is not found', async () => {
  handlers = signedIn({ [`GET /applications/${APP}`]: () => json({ detail: 'Application not found.' }, 404) })
  await render(`/apply/${APP}`)
  assert.match(text(), /could not be found in your account/)
})

// --- Passport ---------------------------------------------------------------

test('the passport question sends the traveler to the passport page and back', async () => {
  handlers = signedIn({ [`GET /applications/${APP}`]: () => json(state([], PASSPORT)) })
  await render(`/apply/${APP}`)
  assert.equal(button('Upload a photo').getAttribute('href'), `/passport?return=${encodeURIComponent(`/apply/${APP}`)}`)
})

test('coming back with a confirmed passport answers the passport question', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([], PASSPORT)),
    [`PUT /applications/${APP}/answers/passport`]: () => json(state([[PASSPORT, SPECIMEN, 'passport_upload']], ARRIVAL)),
  })
  const router = await render(`/apply/${APP}?passport=${UPLOAD}`)
  assert.deepEqual(bodyOf(`PUT /applications/${APP}/answers/passport`), { passport_upload_id: UPLOAD })
  assert.match(text(), /From your confirmed passport/)
  assert.equal(router.state.location.search, '')
})

test('the passport can be typed in instead, with the review form', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([], PASSPORT)),
    [`PUT /applications/${APP}/answers/passport`]: () => json(state([[PASSPORT, SPECIMEN]], ARRIVAL)),
  })
  await render(`/apply/${APP}`)
  await click(button('Type the details'))
  for (const [key, value] of Object.entries(SPECIMEN)) {
    const field = $(`#passport-${key}`)
    if (field instanceof window.HTMLSelectElement) {
      field.value = value
      await act(async () => field.dispatchEvent(new window.Event('change', { bubbles: true })))
    } else await type(field, value)
  }
  await click(button('Confirm these details'))
  assert.deepEqual(bodyOf(`PUT /applications/${APP}/answers/passport`), { value: SPECIMEN })
})

test('the passport page offers the way back once the details are confirmed', async () => {
  handlers = signedIn({
    [`GET /passports/${UPLOAD}/image`]: () => new Response(new Blob(['jpeg'], { type: 'image/jpeg' })),
    [`GET /passports/${UPLOAD}/review`]: () => json(SPECIMEN),
  })
  await render(`/passport/${UPLOAD}?return=${encodeURIComponent(`/apply/${APP}`)}`)
  assert.equal(button('Continue your application').getAttribute('href'), `/apply/${APP}?passport=${UPLOAD}`)
})

test('a crafted return link is ignored by the passport page', async () => {
  handlers = signedIn({
    [`GET /passports/${UPLOAD}/image`]: () => new Response(new Blob(['jpeg'], { type: 'image/jpeg' })),
    [`GET /passports/${UPLOAD}/review`]: () => json(SPECIMEN),
  })
  await render(`/passport/${UPLOAD}?return=https://evil.example`)
  assert.equal(button('Continue your application'), undefined)
})

// --- Assistant mid-flow -----------------------------------------------------

test('a question to the assistant keeps the traveler on the same step', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([[PURPOSE, 'tourism']], LONG_STAY)),
    'POST /assistant/messages': () => json({ reply: 'Count every day you are in the area.', used_passport: false }),
  })
  await render(`/apply/${APP}`)
  const box = $('#chat-ask-input')
  await type(box, 'Does the arrival day count?')
  await submit(box.form)
  assert.deepEqual(bodyOf('POST /assistant/messages'), {
    message: 'Does the arrival day count?', step: 'application', history: [], application_id: APP,
  })
  assert.match(text(), /Count every day you are in the area\./)
  // The aside sits before the current question, which is still waiting for its answer.
  const log = $('.chat-log').textContent
  assert.ok(log.indexOf('Count every day') < log.indexOf('Will you stay more than 90 days?'))
  assert.ok(button('Yes') && button('No'))
})

test('a completed application says so', async () => {
  handlers = signedIn({ [`GET /applications/${APP}`]: () => json(state([[PURPOSE, 'tourism']], null)) })
  await render(`/apply/${APP}`)
  assert.match($('.bubble-done').textContent, /That's every question for now/)
  assert.match(text(), /All questions answered/)
})
