import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import { afterEach, beforeEach, test } from 'node:test'
import { dom } from './dom-setup.mjs'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'

for (const name of ['Node', 'Element', 'HTMLAnchorElement', 'HTMLTextAreaElement', 'HTMLSelectElement',
  'MutationObserver', 'getComputedStyle', 'File', 'Event']) {
  globalThis[name] ??= dom.window[name]
}
window.matchMedia ??= () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
window.scrollTo = () => {}
URL.createObjectURL = () => 'blob:passport-photo'
URL.revokeObjectURL = () => {}

// Vite turns image imports into URLs; the shared test loader only stubs CSS.
registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('.svg')) return { format: 'module', source: `export default ${JSON.stringify(url)}`, shortCircuit: true }
    return nextLoad(url, context)
  },
})

const { routes } = await import('../src/routes.tsx')
const { checkFile } = await import('../src/passport/upload.ts')
const { fieldTrust, normalizeValue, validateFields, blankFields } = await import('../src/passport/fields.ts')

// ICAO 9303 specimen passport ("Utopia"). Never use real passport data in tests.
const SPECIMEN = {
  surname: 'ERIKSSON', given_names: 'ANNA MARIA', document_number: 'L898902C3', nationality: 'UTO',
  issuing_country: 'UTO', birth_date: '1974-08-12', sex: 'F', expiry_date: '2028-04-15', personal_number: 'ZE184226B',
}
const UPLOAD = 'a'.repeat(32)
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

// A fake backend: each test lists the responses it expects, keyed by "METHOD path".
let handlers
let calls
globalThis.fetch = async (url, options = {}) => {
  const key = `${options.method ?? 'GET'} ${url}`
  calls.push({ key, body: options.body })
  const handler = handlers[key]
  assert.ok(handler, `Unexpected request: ${key}`)
  return handler(options)
}

function signedIn(extra) {
  return {
    'POST /auth/refresh': () => json({ access_token: 'token' }),
    'GET /auth/me': () => json({ id: 1, name: 'Anna', email: 'anna@example.com' }),
    'POST /activity/events': () => new Response(null, { status: 204 }),
    [`GET /passports/${UPLOAD}/image`]: () => new Response(new Blob(['jpeg'], { type: 'image/jpeg' })),
    ...extra,
  }
}

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

async function type(element, value) {
  const prototype = element instanceof window.HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
  await act(async () => element.dispatchEvent(new window.Event('input', { bubbles: true })))
}
async function click(element) {
  await act(async () => element.click())
  await settle()
}
const button = label => [...container.querySelectorAll('button')].find(b => b.textContent.trim() === label)
const chip = key => $(`#passport-${key}-trust`)?.firstChild?.textContent

beforeEach(() => { calls = []; handlers = {} })
afterEach(() => {
  if (root) act(() => root.unmount())
  container?.remove()
  root = container = undefined
  document.body.replaceChildren()
})

// --- Pure rules --------------------------------------------------------------

test('the browser rejects files the server would reject', () => {
  assert.equal(checkFile(new File(['x'], 'p.jpg', { type: 'image/jpeg' })), null)
  assert.match(checkFile(new File(['x'], 'p.pdf', { type: 'application/pdf' })), /isn't a JPEG, PNG or WebP/)
  assert.match(checkFile(new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'big.jpg', { type: 'image/jpeg' })), /larger than 10 MB/)
})

test('trust follows the strongest signal, and an edit overrides the machine', () => {
  const extraction = {
    status: 'needs_review', fields: SPECIMEN, suspect_fields: ['document_number'], corrected_fields: ['personal_number'],
    unverifiable_fields: ['surname'], checks: { document_number: false, birth_date: true, personal_number: true },
  }
  assert.equal(fieldTrust('document_number', extraction, new Set()), 'failed')
  assert.equal(fieldTrust('personal_number', extraction, new Set()), 'corrected')
  assert.equal(fieldTrust('birth_date', extraction, new Set()), 'verified')
  assert.equal(fieldTrust('surname', extraction, new Set()), 'confirm')
  assert.equal(fieldTrust('document_number', extraction, new Set(['document_number'])), 'edited')
  assert.equal(fieldTrust('surname', { ...extraction, status: 'unreadable', fields: null }, new Set()), null)
})

test('validation mirrors the API and catches impossible dates', () => {
  assert.deepEqual(validateFields(SPECIMEN, new Date('2026-10-05')), {})
  const errors = validateFields({ ...blankFields, birth_date: '2030-01-01', expiry_date: '2020-01-01' }, new Date('2026-10-05'))
  assert.deepEqual(Object.keys(errors).sort(), ['birth_date', 'document_number', 'expiry_date', 'issuing_country', 'nationality', 'surname'])
  assert.equal(normalizeValue('document_number', 'l898 902c3'), 'L898902C3')
  assert.equal(normalizeValue('surname', 'Eriksson'), 'Eriksson')
})

// --- The page ----------------------------------------------------------------

test('choosing a photo uploads it and opens its review page', async () => {
  handlers = signedIn({ 'POST /passports': () => json({ id: UPLOAD }, 201) })
  const router = await render('/passport')
  const input = $('input[type="file"]')
  Object.defineProperty(input, 'files', { value: [new File(['jpeg'], 'p.jpg', { type: 'image/jpeg' })] })

  handlers[`GET /passports/${UPLOAD}/review`] = () => json({ detail: 'Not found' }, 404)
  handlers[`POST /passports/${UPLOAD}/extract`] = () => json({
    status: 'verified', fields: SPECIMEN, suspect_fields: [], corrected_fields: [],
    unverifiable_fields: ['surname'], checks: { document_number: true },
  })
  await act(async () => input.dispatchEvent(new window.Event('change', { bubbles: true })))
  await settle()

  assert.equal(router.state.location.pathname, `/passport/${UPLOAD}`)
  assert.ok(calls.some(call => call.key === 'POST /passports' && call.body instanceof window.FormData))
  assert.match(text(), /Every check digit passed/)
})

test('a failed check is flagged, edits are marked, and only confirmed details are saved', async () => {
  let saved
  handlers = signedIn({
    [`GET /passports/${UPLOAD}/review`]: () => json({ detail: 'Not found' }, 404),
    [`POST /passports/${UPLOAD}/extract`]: () => json({
      status: 'needs_review', fields: { ...SPECIMEN, document_number: 'L8B8902C3' },
      suspect_fields: ['document_number'], corrected_fields: [],
      unverifiable_fields: ['surname', 'given_names', 'nationality', 'issuing_country', 'sex'],
      checks: { document_number: false, birth_date: true, expiry_date: true, personal_number: true, composite: false },
    }),
    [`PUT /passports/${UPLOAD}/review`]: options => { saved = JSON.parse(options.body); return json(saved) },
  })
  await render(`/passport/${UPLOAD}`)

  assert.match(text(), /Some fields need a closer look/)
  assert.equal(chip('document_number'), 'Check failed')
  assert.equal(chip('birth_date'), 'Passed check')
  assert.equal(chip('surname'), 'Confirm')
  assert.equal($('.photo-frame img').getAttribute('src'), 'blob:passport-photo')

  await type($('#passport-document_number'), 'l898902c3')
  assert.equal(chip('document_number'), 'Edited')

  await click(button('Confirm these details'))
  assert.equal(saved.document_number, 'L898902C3')
  assert.equal(saved.surname, 'ERIKSSON')
  assert.match(text(), /Your details are confirmed/)
  assert.equal($('.review-head .trust').textContent, 'Confirmed')
})

test('an unreadable photo becomes an empty form that will not save until it is valid', async () => {
  handlers = signedIn({
    [`GET /passports/${UPLOAD}/review`]: () => json({ detail: 'Not found' }, 404),
    [`POST /passports/${UPLOAD}/extract`]: () => json({
      status: 'unreadable', fields: null, suspect_fields: [], corrected_fields: [], unverifiable_fields: [], checks: {},
    }),
  })
  await render(`/passport/${UPLOAD}`)

  assert.match(text(), /couldn't read this photo/)
  await click(button('Confirm these details'))

  assert.ok(!calls.some(call => call.key.startsWith('PUT')), 'nothing is sent while fields are invalid')
  assert.match(text(), /Enter your surname/)
  assert.equal(document.activeElement, $('#passport-surname'))
})

test('a confirmed review loads as confirmed without reading the photo again', async () => {
  handlers = signedIn({ [`GET /passports/${UPLOAD}/review`]: () => json(SPECIMEN) })
  await render(`/passport/${UPLOAD}`)

  assert.equal($('#passport-surname').value, 'ERIKSSON')
  assert.equal($('.review-head .trust').textContent, 'Confirmed')
  assert.ok(!calls.some(call => call.key.endsWith('/extract')))
})

// --- The assistant -----------------------------------------------------------

test('the assistant answers from the server and keeps the chat in the page', async () => {
  let request
  handlers = signedIn({
    [`GET /passports/${UPLOAD}/review`]: () => json(SPECIMEN),
    'POST /assistant/messages': options => {
      request = JSON.parse(options.body)
      return json({ reply: 'Your passport expires on 15 April 2028.', used_passport: true })
    },
  })
  await render(`/passport/${UPLOAD}`)

  await click(button('Ask about your passport'))
  assert.match(text(), /Not legal or immigration advice/)
  await click(button('When does my passport expire?'))

  assert.deepEqual(request, { message: 'When does my passport expire?', step: 'passport_review', history: [] })
  assert.match($('.assistant-log').textContent, /expires on 15 April 2028/)
  assert.equal(document.activeElement, $('.assistant-form textarea'), 'focus returns to the question box')

  await act(async () => document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' })))
  assert.equal($('.assistant-panel'), null)
  assert.equal(document.activeElement, button('Ask about your passport'))
})

test('a failed answer shows inline, gives the question back, and raises no toast', async () => {
  handlers = signedIn({
    'POST /assistant/messages': () => json({ detail: "The assistant couldn't answer right now. Please try again in a moment." }, 503),
  })
  await render('/passport')

  await click(button('Ask about your passport'))
  const box = $('.assistant-form textarea')
  await type(box, 'Which page should I photograph?')
  await click(button('Send'))

  assert.match($('.assistant-error').textContent, /couldn't answer right now/)
  assert.equal(box.value, 'Which page should I photograph?')
  assert.equal($('.bubble-user'), null)
  assert.equal(document.body.querySelector('[data-sonner-toast]'), null)
  assert.equal(JSON.parse(calls.find(call => call.key === 'POST /assistant/messages').body).step, 'passport_upload')
})
