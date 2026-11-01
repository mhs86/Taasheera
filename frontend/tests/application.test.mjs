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

const OPTION = {
  destination: 'SCHENGEN', visa_type: 'short_stay', title: 'Schengen short-stay visa (type C)',
  destination_label: 'Schengen area', destination_description: '29 European countries',
  visa_label: 'Short stay (type C)', visa_description: 'Up to 90 days in any 180-day period.',
}
const summary = (extra = {}) => ({
  id: APP, title: OPTION.title, destination: 'SCHENGEN', visa_type: 'short_stay',
  destination_label: 'Schengen area', visa_label: 'Short stay (type C)', status: 'DRAFT', group_size: 1,
  place: null, trip_date: null, answered: 0, total: 18,
  created_at: '2026-10-18T09:00:00Z', updated_at: '2026-10-18T10:00:00Z', ...extra,
})

function state(answers, current, extra = {}) {
  return {
    ...summary(), status: current ? 'DRAFT' : 'ANSWERS_COMPLETE', answered: answers.length, total: 4,
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
  'GET /applications': () => json([]),
  [`GET /assistant/history?application_id=${APP}`]: () => json([]),
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

// --- Starting (US 4) -------------------------------------------------------

test('the opening steps pick the visa and record who is travelling', async () => {
  handlers = signedIn({
    'GET /applications/options': () => json([OPTION]),
    'POST /applications': () => json(state([], PURPOSE, { group_size: 3 }), 201),
    [`GET /applications/${APP}`]: () => json(state([], PURPOSE, { group_size: 3 })),
  })
  const router = await render('/apply')
  assert.match(text(), /Where are you travelling to\?/)
  await click([...container.querySelectorAll('.choice-card')].find(card => card.textContent.includes('Schengen area')))
  assert.match(text(), /Which visa do you need\?/)
  await click([...container.querySelectorAll('.choice-card')].find(card => card.textContent.includes('Short stay (type C)')))
  assert.match(text(), /just for yourself, or travelling with family or a group\?/)
  await click(button('Family or group'))
  assert.match(text(), /How many people are travelling, including you\?/)
  await click(button('3'))
  assert.deepEqual(bodyOf('POST /applications'), { destination: 'SCHENGEN', visa_type: 'short_stay', group_size: 3 })
  assert.equal(router.state.location.pathname, `/apply/${APP}`)
  // The chat repeats the opening answers, then asks the destination's first question.
  assert.match(text(), /Schengen area.*Short stay \(type C\).*Family or group of 3/)
  assert.match(text(), /What's the main purpose of your trip\?/)
  assert.match(text(), /Step 1 of 2/)
  // The new application appears in the sidebar straight away.
  assert.equal($('.apps-item[aria-current="page"]').getAttribute('href'), `/apply/${APP}`)
})

test('travelling alone starts the application in one click', async () => {
  handlers = signedIn({
    'GET /applications/options': () => json([OPTION]),
    'POST /applications': () => json(state([], PURPOSE), 201),
    [`GET /applications/${APP}`]: () => json(state([], PURPOSE)),
  })
  await render('/apply')
  await click($('.choice-card'))
  await click($('.choice-card'))
  await click(button('Just me'))
  assert.deepEqual(bodyOf('POST /applications'), { destination: 'SCHENGEN', visa_type: 'short_stay', group_size: 1 })
  assert.match(text(), /Just me/)
})

test('changing the destination clears the steps after it', async () => {
  handlers = signedIn({ 'GET /applications/options': () => json([OPTION]) })
  await render('/apply')
  await click($('.choice-card'))
  await click($('.choice-card'))
  assert.match(text(), /just for yourself/)
  await click($('[aria-label="Change your answer to: Where are you travelling to?"]'))
  assert.doesNotMatch(text(), /Which visa do you need\?/)
  assert.ok($('.choice-card'))
})

test('signed-out visitors are asked to sign in', async () => {
  handlers = { 'POST /auth/refresh': () => json({ detail: 'No session' }, 401) }
  await render('/apply')
  assert.match(text(), /Please sign in to start an application/)
})

// --- Sidebar (US 12) ---------------------------------------------------------

test('the sidebar lists applications by where and when, newest first', async () => {
  const other = 'c'.repeat(32)
  handlers = signedIn({
    'GET /applications': () => json([
      summary({ place: 'France', trip_date: '2027-01-10', answered: 13, total: 18 }),
      summary({ id: other, status: 'ANSWERS_COMPLETE', place: 'Germany', updated_at: '2026-10-17T10:00:00Z' }),
    ]),
    [`GET /applications/${APP}`]: () => json(state([[PURPOSE, 'tourism']], LONG_STAY, {
      place: 'France', trip_date: '2027-01-10' })),
  })
  await render(`/apply/${APP}`)
  const items = [...container.querySelectorAll('.apps-item')]
  assert.deepEqual(items.map(item => item.querySelector('.apps-name').textContent), ['France', 'Germany'])
  assert.match(items[0].textContent, /Arriving 10 Jan 2027/)
  assert.match(items[0].textContent, /In progress · 1 of 4/)
  assert.match(items[1].textContent, /Answers complete/)
  assert.equal(items[0].getAttribute('aria-current'), 'page')
  assert.equal(items[1].getAttribute('href'), `/apply/${other}`)
  assert.match($('.chat-header').textContent, /France · arriving 10 January 2027/)
})

test('answering updates the sidebar without reloading the list', async () => {
  handlers = signedIn({
    'GET /applications': () => json([summary({ total: 4 })]),
    [`GET /applications/${APP}`]: () => json(state([], PURPOSE)),
    [`PUT /applications/${APP}/answers/purpose`]: () => json(state([[PURPOSE, 'business']], LONG_STAY)),
  })
  await render(`/apply/${APP}`)
  assert.match($('.apps-item').textContent, /0 of 4/)
  await click(button('Business'))
  assert.match($('.apps-item').textContent, /1 of 4/)
  assert.equal(calls.filter(call => call.key === 'GET /applications').length, 1)
})

test('with no applications yet, the sidebar explains itself', async () => {
  handlers = signedIn({ 'GET /applications/options': () => json([OPTION]) })
  await render('/apply')
  assert.match($('.apps-sidebar').textContent, /Applications you start appear here/)
  assert.equal($('.apps-new').getAttribute('aria-current'), 'page')
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
  assert.ok($('.chat-reply:not(.chat-fixed)').textContent.startsWith('Business'))
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

// --- Pre-fill (US 10) ----------------------------------------------------------

const PHONE = question('phone', 'phone', 'What phone number can the embassy reach you on?', {
  step_id: 'personal', suggestion: { value: '+96171123456', source: 'profile' },
})

test('a known answer is shown to confirm instead of asked again', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([], PHONE)),
    [`PUT /applications/${APP}/answers/phone`]: () => json(state([[PHONE, '+96171123456', 'profile']], ARRIVAL)),
  })
  await render(`/apply/${APP}`)
  assert.equal($('.suggestion-label').textContent, 'From your profile')
  assert.equal($('.suggestion-value').textContent, '+96171123456')
  assert.equal($('#current-question input'), null, 'no empty field to retype it into')
  await click(button("Yes, that's right"))
  assert.deepEqual(bodyOf(`PUT /applications/${APP}/answers/phone`), { use_suggestion: true })
  assert.match($('.chat-reply:not(.chat-fixed)').textContent, /\+96171123456From your profile/)
})

test('changing a known answer starts from it and says what it changes', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([], PHONE)),
    [`PUT /applications/${APP}/answers/phone`]: () => json(state([[PHONE, '+33123456789']], ARRIVAL)),
  })
  await render(`/apply/${APP}`)
  await click(button('Change it'))
  assert.match(text(), /only changes this application, not your profile/)
  await click(button('Go back'))
  assert.ok(button("Yes, that's right"), 'back to the saved answer')
  await click(button('Change it'))
  const input = $('#current-question input[type="tel"]')
  assert.equal(input.value, '+96171123456')
  await type(input, '+33 1 23 45 67 89')
  await submit(input.form)
  assert.deepEqual(bodyOf(`PUT /applications/${APP}/answers/phone`), { value: '+33 1 23 45 67 89' })
})

test('a saved passport is offered the same way', async () => {
  const offered = { ...PASSPORT, suggestion: { value: SPECIMEN, source: 'passport' } }
  handlers = signedIn({ [`GET /applications/${APP}`]: () => json(state([], offered)) })
  await render(`/apply/${APP}`)
  assert.equal($('.suggestion-label').textContent, 'From your confirmed passport')
  assert.match($('.suggestion-value').textContent, /ERIKSSON, ANNA MARIA · passport L898902C3/)
  await click(button('Change it'))
  assert.match(text(), /not your saved passport/)
  assert.equal($('#passport-surname').value, 'ERIKSSON')
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

// --- Completeness check (US 13) -----------------------------------------------

test('the completeness check shows what blocks submission and what to look at', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([[PURPOSE, 'tourism']], LONG_STAY)),
    [`GET /applications/${APP}/check`]: () => json({ ready: false, answered: 1, total: 4, issues: [
      { kind: 'missing', severity: 'blocking', message: 'Not answered yet: Will you stay more than 90 days?',
        question_id: 'stay_over_90_days', step_id: 'eligibility' },
      { kind: 'inconsistent', severity: 'warning', message: "The surname on your passport doesn't match your profile.",
        question_id: 'passport', step_id: 'passport' },
    ] }),
  })
  await render(`/apply/${APP}`)
  assert.ok(!text().includes('Must fix'))
  await click(button('Check my application'))
  assert.match(text(), /1 thing needs fixing before you can submit/)
  assert.match(text(), /Must fix Not answered yet: Will you stay more than 90 days\?/)
  assert.match(text(), /Check The surname on your passport/)
  assert.ok(button('Check again'))
})

test('a ready application says so, and a failed check is reported', async () => {
  let fail = false
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([[PURPOSE, 'tourism']], null)),
    [`GET /applications/${APP}/check`]: () => fail ? json({ detail: 'no' }, 500) : json({ ready: true, answered: 4, total: 4, issues: [] }),
  })
  await render(`/apply/${APP}`)
  await click(button('Check my application'))
  assert.match(text(), /Nothing is missing\. Your answers are ready for review\./)
  fail = true
  await click(button('Check again'))
  assert.ok($('.completeness [role="alert"]'))
  assert.ok(!text().includes('Nothing is missing'))
})

// --- Assistant actions (US 110) -------------------------------------------------

const CHANGE = {
  action: 'change_answer', question_id: 'purpose', question: "What's the main purpose of your trip?",
  value: 'business', display: 'Business', current_display: 'Tourism', report: null,
}

async function askFor(proposal, message = 'Change my purpose to business') {
  handlers[`GET /applications/${APP}`] ??= () => json(state([[PURPOSE, 'tourism']], LONG_STAY))
  handlers['POST /assistant/messages'] = () => json({ reply: "Here's the change. Confirm it below to save it.",
    used_passport: false, proposal })
  await render(`/apply/${APP}`)
  const box = $('#chat-ask-input')
  await type(box, message)
  await submit(box.form)
}

test('an assistant change is only saved when the traveler confirms it', async () => {
  handlers = signedIn({
    [`PUT /applications/${APP}/answers/purpose`]: () => json(state([[PURPOSE, 'business']], LONG_STAY)),
  })
  await askFor(CHANGE)
  assert.match($('[aria-label="Proposed change"]').textContent, /Tourism → Business/)
  assert.equal(calls.filter(call => call.key.startsWith('PUT')).length, 0)
  await click(button('Confirm change'))
  assert.deepEqual(bodyOf(`PUT /applications/${APP}/answers/purpose`), { value: 'business' })
  assert.match(text(), /Saved\./)
})

test('declining an assistant change saves nothing, and a refused save is shown', async () => {
  handlers = signedIn({
    [`PUT /applications/${APP}/answers/purpose`]: () => json({ detail: 'Choose one of the options.' }, 422),
  })
  await askFor(CHANGE)
  await click(button('Confirm change'))
  assert.match($('[aria-label="Proposed change"] [role="alert"]').textContent, /Choose one of the options\./)
  await click(button('Not now'))
  assert.match(text(), /Left as it was\./)
})

test('the assistant can open an answered question and show the completeness check', async () => {
  handlers = signedIn({})
  await askFor({ ...CHANGE, action: 'go_to_question', value: null, display: null, current_display: null })
  await click(button('Go to this question'))
  assert.ok(button('Keep my answer'), 'the answer opens for changing')
  afterEachCleanup()
  handlers = signedIn({})
  await askFor({ action: 'check', question_id: null, question: null, value: null, display: null, current_display: null,
    report: { ready: false, answered: 1, total: 4, issues: [{ kind: 'missing', severity: 'blocking',
      message: 'Not answered yet: Will you stay more than 90 days?', question_id: 'stay_over_90_days', step_id: 'eligibility' }] } },
  'Is anything missing?')
  assert.match(text(), /1 to fix before you can submit\.Must fix Not answered yet/)
})

function afterEachCleanup() {
  if (root) act(() => root.unmount())
  container?.remove()
  root = container = undefined
}

// --- Chat history (US 111) ------------------------------------------------------

test('the conversation from an earlier visit reloads', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(state([[PURPOSE, 'tourism']], LONG_STAY)),
    [`GET /assistant/history?application_id=${APP}`]: () => json([
      { role: 'user', content: 'Does the arrival day count?' }, { role: 'assistant', content: 'Yes, it counts.' }]),
  })
  await render(`/apply/${APP}`)
  const log = $('.chat-log').textContent
  assert.match(log, /You askedDoes the arrival day count\?AssistantYes, it counts\./)
  assert.ok(log.indexOf('Yes, it counts.') < log.indexOf('Will you stay more than 90 days?'))
})
