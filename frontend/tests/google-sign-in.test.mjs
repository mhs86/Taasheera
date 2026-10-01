import './dom-setup.mjs'
import assert from 'node:assert/strict'
import { afterEach, beforeEach, test } from 'node:test'
import { act, createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

const { default: App } = await import('../src/App.tsx')
let root, callback, buttonOptions, calls, replies, initialized, disabledAutoSelect
const traveler = { id: 7, name: 'Google Traveler', email: 'traveler@example.com' }
const response = ({ status, body }) => new Response(status === 204 ? null : JSON.stringify(body ?? {}), { status })
beforeEach(() => {
  calls = []; replies = []; initialized = []; disabledAutoSelect = 0
  window.history.replaceState(null, '', '/')
  window.google = { accounts: { id: {
    initialize(options) { initialized.push(options); callback = options.callback },
    renderButton(host, options) {
      buttonOptions = options
      const button = document.createElement('button')
      button.textContent = 'Mock official Google button'
      button.onclick = options.click_listener
      host.append(button)
    },
    disableAutoSelect() { disabledAutoSelect++ },
  } } }
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options })
    assert.equal(options.credentials, 'same-origin')
    assert.equal(options.cache, 'no-store')
    const next = replies.shift()
    assert.ok(next, `Unexpected request: ${url}`)
    return typeof next === 'function' ? next() : response(next)
  }
})
afterEach(async () => {
  if (root) await act(async () => root.unmount())
  root = null
  assert.equal(replies.length, 0)
})
async function mount(clientId = 'public-test-client') {
  root = createRoot(document.getElementById('root'))
  await act(async () => root.render(createElement(StrictMode, null,
    createElement(App, { initialNavigation: { page: 'sign-in', resetToken: null }, googleClientId: clientId }))))
}
async function signedOut(clientId) { replies.push({ status: 401 }); await mount(clientId) }
async function click(label) {
  const button = [...document.querySelectorAll('button')].find(item => item.textContent === label)
  assert.ok(button, label)
  await act(async () => button.click())
}
async function credential(state = buttonOptions.state, value = 'mock-id-credential') {
  await act(async () => callback({ credential: value, state }))
}
const text = () => document.body.textContent

test('Google callback signs in through protected profile; reload and logout use existing sessions', async () => {
  await signedOut()
  assert.equal(initialized.length, 1)
  assert.equal(initialized[0].client_id, 'public-test-client')
  assert.equal(initialized[0].auto_select, false)
  assert.equal(initialized[0].ux_mode, 'popup')
  assert.equal(buttonOptions.type, 'standard')
  await click('Mock official Google button')
  replies.push({ status: 200, body: { access_token: 'mock-access' } }, { status: 200, body: traveler })
  await credential()
  assert.match(text(), /Welcome, Google Traveler/)
  assert.deepEqual(JSON.parse(calls[1].body), { id_token: 'mock-id-credential' })
  assert.equal(calls[1].url, '/auth/google')
  assert.equal(calls[1].method, 'POST')
  assert.equal(calls[2].headers.Authorization, 'Bearer mock-access')
  assert.equal(window.location.href, 'http://127.0.0.1:5173/')
  await act(async () => root.unmount()); root = null
  replies.push({ status: 200, body: { access_token: 'refreshed-access' } }, { status: 200, body: traveler })
  await mount()
  assert.deepEqual(calls.slice(-2).map(call => call.url), ['/auth/refresh', '/auth/me'])
  assert.equal(calls.at(-1).headers.Authorization, 'Bearer refreshed-access')
  assert.match(text(), /Welcome, Google Traveler/)
  replies.push({ status: 204 })
  await click('Log out')
  assert.equal(calls.at(-1).url, '/auth/logout')
  assert.equal(disabledAutoSelect, 1)
  assert.match(text(), /Welcome back/)
  await act(async () => root.unmount()); root = null
  replies.push({ status: 401 }); await mount()
  assert.match(text(), /Welcome back/)
})

for (const [status, pattern] of [[409, /Use your existing sign-in method\. Accounts have not been linked/], [401, /could not be verified/], [422, /could not be verified/], [503, /temporarily unavailable/], [500, /temporarily unavailable/]]) {
  test(`Google HTTP ${status} gives a safe message and permits retry`, async () => {
    await signedOut(); await click('Mock official Google button')
    replies.push({ status, body: { detail: { code: 'google_link_required', message: 'Private backend detail' } } })
    await credential()
    assert.match(text(), pattern)
    assert.doesNotMatch(text(), /Private backend detail/)
    assert.equal(document.querySelector('input').disabled, false)
    assert.equal(calls.length, 2)
  })
}
test('network failure permits retry without displaying raw error details', async () => {
  await signedOut(); await click('Mock official Google button')
  replies.push(() => { throw new TypeError('Private network details') })
  await credential()
  assert.match(text(), /Check your connection/)
  assert.doesNotMatch(text(), /Private network details/)
  await click('Mock official Google button')
  replies.push({ status: 200, body: { access_token: 'mock-access' } }, { status: 200, body: traveler })
  await credential()
  assert.match(text(), /Welcome, Google Traveler/)
})
test('duplicate callbacks and email submissions cannot overlap a Google exchange', async () => {
  await signedOut(); await click('Mock official Google button')
  let resolve
  replies.push(() => new Promise(done => { resolve = done }))
  await credential(); await credential()
  await act(async () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
  assert.equal(calls.length, 2)
  assert.ok(document.querySelector('.google-button-host').hasAttribute('inert'))
  assert.equal(document.querySelector('input').disabled, true)
  await act(async () => resolve(response({ status: 401 })))
})
test('cancel ignores late credentials, keeps email usable, and allows a new attempt', async () => {
  await signedOut(); await click('Mock official Google button')
  const oldState = buttonOptions.state
  assert.equal(document.querySelector('input').disabled, false)
  assert.match(text(), /If you close or cancel/)
  await click('Cancel Google sign-in')
  await click('Mock official Google button')
  await credential(oldState)
  assert.equal(calls.length, 1)
  replies.push({ status: 401 }); await credential()
  assert.equal(calls.length, 2)
})
test('empty callback and callbacks after unmount do not send credentials', async () => {
  await signedOut(); await click('Mock official Google button')
  await credential(buttonOptions.state, '')
  assert.match(text(), /did not complete/)
  await click('Mock official Google button')
  await act(async () => root.unmount()); root = null
  await credential()
  assert.equal(calls.length, 1)
})
test('missing configuration loads no SDK and email sign-in still succeeds', async () => {
  delete window.google
  await signedOut('')
  assert.equal(document.querySelector('script[src*="accounts.google.com"]'), null)
  assert.match(text(), /Google sign-in is unavailable/)
  document.querySelector('[name=email]').value = 'traveler@example.com'
  document.querySelector('[name=password]').value = 'test-password'
  replies.push({ status: 200, body: { access_token: 'email-access' } }, { status: 200, body: traveler })
  await act(async () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
  assert.equal(calls[1].url, '/auth/login')
  assert.match(text(), /Welcome, Google Traveler/)
})
test('SDK render failure leaves password sign-in usable with retry', async () => {
  window.google.accounts.id.renderButton = () => { throw new Error('SDK failed') }
  await signedOut()
  assert.match(text(), /Google sign-in could not load/)
  assert.equal(document.querySelector('input').disabled, false)
  assert.ok([...document.querySelectorAll('button')].some(button => button.textContent === 'Retry Google sign-in'))
})
