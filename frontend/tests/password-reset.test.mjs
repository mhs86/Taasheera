import './dom-setup.mjs'
import assert from 'node:assert/strict'
import { afterEach, beforeEach, test } from 'node:test'
import { act, createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

const { default: App } = await import('../src/App.tsx')
const { readNavigation } = await import('../src/navigation.ts')
const { passwordValidation } = await import('../src/passwordReset.ts')
const TOKEN = 'a'.repeat(43)
const GENERIC = 'If an account exists for that email, a password reset email will be sent.'
let root
let calls
let replies

beforeEach(() => {
  calls = []
  replies = []
  window.history.replaceState(null, '', '/')
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options })
    if (url !== '/auth/register') {
      assert.equal(options.credentials, 'same-origin')
      assert.equal(options.cache, 'no-store')
    }
    assert.ok(options.signal)
    const reply = replies.shift()
    assert.ok(reply, `Unexpected request to ${url}`)
    if (typeof reply === 'function') return reply()
    return response(reply)
  }
})
afterEach(async () => {
  if (root) await act(async () => root.unmount())
  root = null
  assert.equal(replies.length, 0, 'Every expected response should be consumed')
})
function response({ status, body }) {
  return new Response(status === 204 ? null : JSON.stringify(body ?? {}), { status })
}
async function mount(url) {
  window.history.replaceState(null, '', url)
  const initialNavigation = readNavigation(window)
  root = createRoot(document.getElementById('root'))
  await act(async () => root.render(createElement(StrictMode, null, createElement(App, { initialNavigation }))))
}
function fill(name, value) {
  const input = document.querySelector(`[name="${name}"]`)
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
  act(() => input.dispatchEvent(new window.Event('input', { bubbles: true })))
}
function passwords(password = 'New-password-123', confirmation = password) {
  fill('password', password)
  fill('confirmPassword', confirmation)
}
async function submit(times = 1) {
  await act(async () => {
    for (let index = 0; index < times; index++) {
      document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }))
    }
  })
}
async function navigate(hash) {
  await act(async () => {
    window.history.pushState(null, '', hash)
    window.dispatchEvent(new window.HashChangeEvent('hashchange'))
  })
}
const text = () => document.body.textContent

test('known and unknown emails display the same backend confirmation and exact request shape', async () => {
  await mount('/#forgot-password')
  for (const email of ['known@example.com', 'unknown@example.com']) {
    replies.push({ status: 202, body: { detail: GENERIC } })
    fill('email', email)
    await submit()
    assert.equal(document.querySelector('[role="status"]').textContent, GENERIC)
    assert.deepEqual(JSON.parse(calls.at(-1).body), { email })
    assert.equal(calls.at(-1).url, '/auth/forgot-password')
  }
})

test('forgot-password blocks repeated submissions while sending and permits retry after failure', async () => {
  await mount('/#forgot-password')
  let resolve
  replies.push(() => new Promise(done => { resolve = done }))
  fill('email', 'known@example.com')
  await submit(2)
  assert.equal(calls.length, 1)
  assert.equal(document.querySelector('button').disabled, true)
  assert.match(text(), /Sending/)
  await act(async () => resolve(response({ status: 503 })))
  assert.match(text(), /temporarily unavailable/)
  assert.equal(document.querySelector('button').disabled, false)
  replies.push({ status: 202, body: { detail: GENERIC } })
  await submit()
  assert.match(text(), /If an account exists/)
})

for (const status of [422, 429, 500]) {
  test(`forgot-password handles HTTP ${status} without showing server response details`, async () => {
    await mount('/#forgot-password')
    replies.push({ status, body: { detail: 'sensitive server diagnostic' } })
    fill('email', 'known@example.com')
    await submit()
    assert.ok(document.querySelector('[role="alert"]').textContent)
    assert.doesNotMatch(text(), /sensitive server diagnostic/)
  })
}

test('forgot-password handles network failure without claiming email was sent', async () => {
  await mount('/#forgot-password')
  replies.push(() => { throw new TypeError('network failure') })
  fill('email', 'known@example.com')
  await submit()
  assert.match(text(), /Check your connection/)
  assert.doesNotMatch(text(), /If an account exists/)
})

test('emailed link opens reset form and scrubs token even under StrictMode', async () => {
  await mount(`/reset-password#token=${TOKEN}`)
  assert.match(text(), /Set new password/)
  assert.ok(document.querySelector('form'))
  assert.equal(window.location.hash, '#set-new-password')
  assert.equal(window.history.state, null)
  assert.doesNotMatch(document.documentElement.outerHTML, new RegExp(TOKEN))
  assert.equal(calls.length, 0, 'No session restoration is required to reset a password')
})

for (const url of ['/reset-password', '/#set-new-password', '/reset-password#token=', '/reset-password#token=bad', `/reset-password#token=${TOKEN}&token=${TOKEN}`]) {
  test(`missing/malformed link has a recovery route (${url.includes('token') ? 'fragment' + url.length : url})`, async () => {
    await mount(url)
    assert.match(text(), /missing or invalid/)
    assert.equal(document.querySelector('form'), null)
    assert.ok(document.querySelector('a[href="#forgot-password"]'))
    assert.equal(calls.length, 0)
    await navigate('#forgot-password')
    assert.match(text(), /Forgot password\?/)
  })
}

test('reload of scrubbed URL requires reopening the email or requesting a new link', async () => {
  await mount(`/reset-password#token=${TOKEN}`)
  const scrubbed = window.location.href
  await act(async () => root.unmount())
  root = null
  await mount(scrubbed)
  assert.match(text(), /missing or invalid/)
})

test('password confirmation and UTF-8 byte limits block submission', async () => {
  await mount(`/reset-password#token=${TOKEN}`)
  for (const [password, confirmation] of [['New-password-123', 'different'], ['short', 'short'], ['é'.repeat(37), 'é'.repeat(37)]]) {
    passwords(password, confirmation)
    await submit()
    assert.equal(calls.length, 0)
    assert.ok(document.querySelector('[name="confirmPassword"]').validationMessage)
  }
  assert.equal(passwordValidation('é'.repeat(36), 'é'.repeat(36)), '')
  assert.equal(passwordValidation('  spaced password  ', '  spaced password  '), '')
})

test('successful reset sends only token/password, blocks duplicates, clears form, and leads to sign-in', async () => {
  await mount(`/reset-password#token=${TOKEN}`)
  let resolve
  replies.push(() => new Promise(done => { resolve = done }))
  passwords()
  await submit(2)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/auth/reset-password')
  assert.deepEqual(JSON.parse(calls[0].body), { token: TOKEN, password: 'New-password-123' })
  assert.equal(document.querySelector('button').disabled, true)
  await act(async () => resolve(response({ status: 204 })))
  assert.match(text(), /password has been changed/)
  assert.equal(document.querySelector('form'), null)
  assert.ok(document.querySelector('a[href="#sign-in"]'))
  replies.push({ status: 401 })
  await navigate('#sign-in')
  assert.match(text(), /Welcome back/)
  assert.ok(document.querySelector('[autocomplete="current-password"]'))
})

test('expired or reused token removes the form and offers a fresh link', async () => {
  await mount(`/reset-password#token=${TOKEN}`)
  replies.push({ status: 400 })
  passwords()
  await submit()
  assert.match(text(), /invalid, expired, or already used/)
  assert.equal(document.querySelector('form'), null)
  assert.ok(document.querySelector('a[href="#forgot-password"]'))
})

for (const status of [422, 429, 500]) {
  test(`reset HTTP ${status} clears passwords but preserves the link for retry`, async () => {
    await mount(`/reset-password#token=${TOKEN}`)
    replies.push({ status, body: { detail: 'sensitive diagnostic' } })
    passwords()
    await submit()
    assert.ok(document.querySelector('[role="alert"]').textContent)
    assert.doesNotMatch(text(), /sensitive diagnostic/)
    assert.equal(document.querySelector('[name="password"]').value, '')
    assert.equal(document.querySelector('[name="confirmPassword"]').value, '')
    replies.push({ status: 204 })
    passwords()
    await submit()
    assert.match(text(), /password has been changed/)
  })
}

test('network/timeout failures are recoverable and warn that reset might have succeeded', async () => {
  await mount(`/reset-password#token=${TOKEN}`)
  replies.push(() => { throw new DOMException('timeout', 'TimeoutError') })
  passwords()
  await submit()
  assert.match(text(), /Check your connection/)
  assert.match(text(), /If it already succeeded/)
  assert.equal(document.querySelector('[name="password"]').value, '')
})

test('reset link remains accessible from a signed-in view and success discards the old profile', async () => {
  replies.push({ status: 200, body: { access_token: 'test-access' } },
    { status: 200, body: { id: 1, name: 'Maya', email: 'maya@example.com' } })
  await mount('/')
  assert.match(text(), /Welcome, Maya/)
  await navigate(`#token=${TOKEN}`)
  assert.match(text(), /Set new password/)
  replies.push({ status: 204 })
  passwords()
  await submit()
  replies.push({ status: 401 })
  await navigate('#sign-in')
  assert.match(text(), /Welcome back/)
  assert.doesNotMatch(text(), /Welcome, Maya/)
})

test('registration and sign-in hash routes still render their existing forms', async () => {
  replies.push({ status: 401 })
  await mount('/#create-account')
  assert.ok(document.querySelector('[name="name"]'))
  await navigate('#sign-in')
  assert.ok(document.querySelector('[autocomplete="current-password"]'))
})

test('registration from the site path shows the password toggle and returns to sign-in', async () => {
  replies.push({ status: 401 })
  await mount('/sign-in#create-account')
  assert.equal(document.querySelector('h1').textContent, 'Create account')

  const toggle = document.querySelector('[aria-label="Show password"]')
  assert.ok(toggle)
  await act(async () => toggle.click())
  assert.equal(document.querySelector('[name="password"]').type, 'text')
  assert.equal(document.querySelector('[aria-label="Hide password"]')?.getAttribute('aria-pressed'), 'true')

  fill('name', 'Maya Traveler')
  fill('email', 'maya@example.com')
  fill('password', 'Travel-test-123')
  fill('confirmPassword', 'Travel-test-123')
  replies.push({ status: 201 })
  await submit()
  await act(async () => window.dispatchEvent(new window.HashChangeEvent('hashchange')))

  assert.equal(calls.at(-1).url, '/auth/register')
  assert.deepEqual(JSON.parse(calls.at(-1).body), {
    name: 'Maya Traveler', email: 'maya@example.com', password: 'Travel-test-123',
  })
  assert.equal(window.location.pathname, '/sign-in')
  assert.equal(window.location.hash, '#sign-in')
  assert.equal(document.querySelector('h1').textContent, 'Welcome back')
  assert.match(text(), /Your traveler account has been created/)
})
