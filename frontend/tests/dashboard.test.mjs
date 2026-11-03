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

registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('.svg')) return { format: 'module', source: `export default ${JSON.stringify(url)}`, shortCircuit: true }
    return nextLoad(url, context)
  },
})

const { routes } = await import('../src/routes.tsx')
const { safePage } = await import('../src/activityPage.ts')

const APP = 'b'.repeat(32)
const OTHER = 'c'.repeat(32)
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const summary = (extra = {}) => ({
  id: APP, title: 'Schengen short-stay visa (type C)', destination: 'SCHENGEN', visa_type: 'short_stay',
  destination_label: 'Schengen area', visa_label: 'Short stay (type C)', status: 'DRAFT', group_size: 1,
  place: 'France', trip_date: '2027-01-10', answered: 5, total: 18,
  created_at: '2026-10-18T09:00:00Z', updated_at: '2026-10-18T10:00:00Z', archived_at: null, ...extra,
})
const question = (id, step_id, prompt, extra = {}) => ({
  id, step_id, type: 'text', prompt, help: null, required: true, options: null, max_length: 200,
  date_min: null, date_max: null, suggestion: null, ...extra,
})
const detail = (extra = {}) => ({
  ...summary(), steps: [{ id: 'eligibility', title: 'Eligibility' }, { id: 'about', title: 'About you' }],
  progress: { step_number: 2, step_count: 2, step_title: 'About you', answered: 2, total: 4 },
  answers: [
    { question: question('purpose', 'eligibility', 'Purpose of the trip?', { type: 'choice', options: [{ value: 'tourism', label: 'Tourism' }] }), value: 'tourism', source: 'traveler' },
    { question: question('place_of_birth', 'about', 'Where were you born?'), value: 'Zenith', source: 'profile' },
  ],
  current: question('occupation', 'about', 'What do you do?'), stopped: null, cleared: [], ...extra,
})
const timeline = (extra = {}) => ({
  id: APP, archived_at: null,
  events: [
    { kind: 'started', at: '2026-10-18T09:00:00Z', text: 'Started the Schengen short-stay visa (type C) application', question_id: null, step_title: null },
    { kind: 'answered', at: '2026-10-18T09:01:00Z', text: 'Purpose of the trip?', question_id: 'purpose', step_title: 'Eligibility' },
    { kind: 'answered', at: '2026-10-18T09:02:00Z', text: 'Where were you born?', question_id: 'place_of_birth', step_title: 'About you' },
  ],
  next: { kind: 'answer', text: 'Next question (step 2 of 2, About you): What do you do?' }, ...extra,
})

let handlers
let calls
globalThis.fetch = async (url, options = {}) => {
  const key = `${options.method ?? 'GET'} ${url}`
  calls.push(key)
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
const text = () => container.textContent
const button = label => [...container.querySelectorAll('button, a')].find(b => b.textContent.trim() === label)
async function click(element) {
  await act(async () => element.click())
  await settle()
}

beforeEach(() => { calls = []; handlers = {} })
afterEach(() => {
  if (root) act(() => root.unmount())
  container?.remove()
  root = container = undefined
  document.body.replaceChildren()
})

test('dashboard pages have their own activity page id, without the id itself', () => {
  assert.equal(safePage('/dashboard', ''), 'dashboard')
  assert.equal(safePage(`/dashboard/${APP}`, ''), 'dashboard')
  assert.equal(safePage('/dashboard/not-an-id', ''), 'not-found')
})

test('the dashboard lists each application with its status, last update and a resume link', async () => {
  handlers = signedIn({
    'GET /applications': () => json([summary(), summary({ id: OTHER, place: null, status: 'ANSWERS_COMPLETE', trip_date: null })]),
  })
  await render('/dashboard')
  assert.match(text(), /Your applications/)
  const cards = [...container.querySelectorAll('.dash-card')]
  assert.equal(cards.length, 2)
  assert.match(cards[0].textContent, /France.*Short stay \(type C\).*Arriving 10 Jan 2027.*In progress · 5 of 18.*Last updated/)
  assert.equal(cards[0].querySelector('a[data-activity-id="application-resume"]').getAttribute('href'), `/apply/${APP}`)
  assert.equal(cards[0].querySelector('.dash-card-title a').getAttribute('href'), `/dashboard/${APP}`)
  // No country chosen yet: named by the destination. Complete: the button says what it does.
  assert.match(cards[1].textContent, /Schengen area.*Started 18 Oct 2026.*Answers complete/)
  assert.equal(document.title, 'Your applications | Taasheera')
  assert.ok([...cards[1].querySelectorAll('a')].some(link => link.textContent === 'Review answers'))
})

test('archived applications have their own tab, and archiving moves one there', async () => {
  handlers = signedIn({
    'GET /applications': () => json([summary()]),
    'GET /applications?archived=true': () => json([]),
    [`POST /applications/${APP}/archive`]: () => json(summary({ archived_at: '2026-10-31T10:00:00Z' })),
  })
  await render('/dashboard')
  await click(button('Archive'))
  assert.ok(calls.includes(`POST /applications/${APP}/archive`))
  assert.equal(container.querySelectorAll('.dash-card').length, 0)
  assert.match(text(), /no active applications/)

  handlers['GET /applications?archived=true'] = () => json([summary({ archived_at: '2026-10-31T10:00:00Z' })])
  await click(button('Archived'))
  assert.ok(calls.includes('GET /applications?archived=true'))
  const card = container.querySelector('.dash-card')
  assert.ok(card.textContent.includes('Restore'))
  // An archived application is restored before it is resumed.
  assert.equal(card.querySelector('a[data-activity-id="application-resume"]'), null)
})

test('delete asks first, and cancelling keeps the application', async () => {
  handlers = signedIn({
    'GET /applications': () => json([summary()]),
    [`DELETE /applications/${APP}`]: () => new Response(null, { status: 204 }),
  })
  await render('/dashboard')
  await click(button('Delete'))
  assert.match(container.querySelector('[role="alertdialog"]').textContent, /Delete France, arriving 10 Jan 2027 and all its answers\? This can't be undone\./)
  // The question takes the focus; Escape closes it like Cancel.
  assert.equal(document.activeElement, button('Cancel'))
  await act(async () => container.querySelector('[role="alertdialog"]')
    .dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  await settle()
  assert.equal(container.querySelector('[role="alertdialog"]'), null)
  assert.equal(document.activeElement, button('Delete'))
  assert.ok(!calls.includes(`DELETE /applications/${APP}`))

  await click(button('Delete'))
  await click(button('Yes, delete'))
  assert.ok(calls.includes(`DELETE /applications/${APP}`))
  assert.equal(container.querySelectorAll('.dash-card').length, 0)
  assert.equal(document.activeElement, container.querySelector('h1'))
})

test('a failed load says so and can be retried', async () => {
  let fail = true
  handlers = signedIn({ 'GET /applications': () => fail ? json({ detail: 'down' }, 500) : json([summary()]) })
  await render('/dashboard')
  assert.match(container.querySelector('[role="alert"]').textContent, /Could not load your applications/)
  fail = false
  await click(button('Try again'))
  assert.equal(container.querySelectorAll('.dash-card').length, 1)
})

test('the detail page shows the answers by step, what comes next, and the timeline', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(detail()),
    [`GET /applications/${APP}/timeline`]: () => json(timeline()),
  })
  await render(`/dashboard/${APP}`)
  assert.match(container.querySelector('h1').textContent, /France/)
  assert.match(text(), /What happens next.*What do you do\?/)
  assert.equal(button('Resume').getAttribute('href'), `/apply/${APP}`)
  assert.match(text(), /Eligibility.*Purpose of the trip\?.*Tourism.*About you.*Where were you born\?.*Zenith.*From your profile/)
  const events = [...container.querySelectorAll('.dash-event')].map(event => event.textContent)
  assert.equal(events.length, 3)
  assert.match(events[0], /Started the Schengen/)
  assert.match(events[1], /Answered 1 question · Eligibility/)
  assert.match(events[2], /Answered 1 question · About you/)
})

test('an archived application offers restore instead of resume', async () => {
  const archived = { archived_at: '2026-10-31T10:00:00Z' }
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(detail(archived)),
    [`GET /applications/${APP}/timeline`]: () => json(timeline({ ...archived, next: { kind: 'archived', text: 'This application is archived.' } })),
  })
  await render(`/dashboard/${APP}`)
  assert.match(text(), /Archived/)
  assert.equal(button('Resume'), undefined)
  assert.ok(button('Restore'))
})

test("another traveler's or a deleted application shows not found", async () => {
  handlers = signedIn({ [`GET /applications/${APP}`]: () => json({ detail: 'Application not found.' }, 404) })
  await render(`/dashboard/${APP}`)
  assert.match(text(), /Application not found/)
  assert.ok(!calls.includes(`GET /applications/${APP}/timeline`))
})

test('deleting from the detail page goes back to the dashboard', async () => {
  handlers = signedIn({
    [`GET /applications/${APP}`]: () => json(detail()),
    [`GET /applications/${APP}/timeline`]: () => json(timeline()),
    [`DELETE /applications/${APP}`]: () => new Response(null, { status: 204 }),
    'GET /applications': () => json([]),
  })
  const router = await render(`/dashboard/${APP}`)
  await click(button('Delete'))
  await click(button('Yes, delete'))
  assert.equal(router.state.location.pathname, '/dashboard')
})

test('signed out, the dashboard asks the traveler to sign in', async () => {
  handlers = {
    'POST /auth/refresh': () => json({ detail: 'Not signed in.' }, 401),
    'POST /activity/events': () => new Response(null, { status: 204 }),
  }
  await render('/dashboard')
  assert.match(text(), /Please sign in to see your applications/)
})

test('an archived application opened in the chat is read-only and stays off the sidebar', async () => {
  handlers = signedIn({
    'GET /applications': () => json([]),
    [`GET /applications/${APP}`]: () => json(detail({ archived_at: '2026-10-31T10:00:00Z' })),
  })
  await render(`/apply/${APP}`)
  assert.match(text(), /This application is archived, so its answers can't be changed\./)
  assert.equal(button('See it and restore it').getAttribute('href'), `/dashboard/${APP}`)
  assert.equal(container.querySelector('.apps-item'), null)
  assert.equal(container.querySelector('.chat-answer'), null)
})
