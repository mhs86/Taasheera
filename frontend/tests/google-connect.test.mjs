import './dom-setup.mjs'
import assert from 'node:assert/strict'
import { afterEach, beforeEach, test } from 'node:test'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
const { default: ConnectGoogle } = await import('../src/ConnectGoogle.tsx')
const { signIn } = await import('../src/auth.ts')

const owner = { id: 1, name: 'Owner', email: 'mhs86@mail.aub.edu', sso_email: null }
let root, callback, button, options, calls, replies, connected
beforeEach(async () => {
  calls = []; connected = []; replies = [
    { status: 200, body: { access_token: 'synthetic-owner-access' } },
    { status: 200, body: owner },
  ]
  globalThis.fetch = async (url, init) => {
    calls.push({ url, ...init })
    const next = replies.shift()
    assert.ok(next, `Unexpected request: ${url}`)
    return typeof next === 'function' ? next() : new Response(JSON.stringify(next.body ?? {}), { status: next.status })
  }
  window.google = { accounts: { id: {
    initialize(init) { callback = init.callback },
    renderButton(host, init) {
      options = init
      button = document.createElement('button'); button.textContent = 'Google popup'
      button.onclick = init.click_listener; host.append(button)
    },
    disableAutoSelect() {},
  } } }
  await signIn(owner.email, 'synthetic-current-password')
  root = createRoot(document.getElementById('root'))
  await act(async () => root.render(createElement(ConnectGoogle, {
    traveler: owner, clientId: 'runtime.apps.googleusercontent.com', configurationStatus: 'ready',
    onConnected: profile => connected.push(profile),
  })))
})
afterEach(async () => {
  if (root) await act(async () => root.unmount())
  root = null
  assert.equal(replies.length, 0)
})
async function enterPassword() {
  const input = document.getElementById('connect-google-password')
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'synthetic-current-password')
    input.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
}
async function selectGoogle() {
  await act(async () => button.click())
  await act(async () => callback({ credential: 'synthetic-google-credential', state: options.state }))
}

test('Connect Google requires current password and sends an owner-authenticated request', async () => {
  assert.equal(document.querySelector('.google-button-host').hasAttribute('inert'), true)
  await enterPassword()
  assert.equal(document.querySelector('.google-button-host').hasAttribute('inert'), false)
  const linked = { ...owner, sso_email: owner.email }
  replies.push({ status: 200, body: linked })
  await selectGoogle()
  assert.equal(calls.at(-1).url, '/auth/google/link')
  assert.equal(calls.at(-1).headers.Authorization, 'Bearer synthetic-owner-access')
  assert.deepEqual(JSON.parse(calls.at(-1).body), { id_token: 'synthetic-google-credential', password: 'synthetic-current-password', expected_traveler_id: 1 })
  assert.deepEqual(connected, [linked])
  assert.equal(document.getElementById('connect-google-password').value, '')
})

test('incorrect password leaves linking retryable and clears the secret input', async () => {
  await enterPassword()
  replies.push({ status: 403 })
  await selectGoogle()
  assert.match(document.body.textContent, /Check your current password/)
  assert.equal(document.getElementById('connect-google-password').value, '')
  assert.deepEqual(connected, [])
})

test('duplicate Google callback does not create a second linking request', async () => {
  await enterPassword()
  let resolve
  replies.push(() => new Promise(done => { resolve = done }))
  await selectGoogle()
  await act(async () => callback({ credential: 'synthetic-google-credential', state: options.state }))
  assert.equal(calls.filter(call => call.url === '/auth/google/link').length, 1)
  await act(async () => resolve(new Response(JSON.stringify({ ...owner, sso_email: owner.email }), { status: 200 })))
  assert.equal(connected.length, 1)
})

test('a late linking response cannot restore a view after unmount', async () => {
  await enterPassword()
  let resolve
  replies.push(() => new Promise(done => { resolve = done }))
  await selectGoogle()
  await act(async () => root.unmount()); root = null
  await act(async () => resolve(new Response(JSON.stringify({ ...owner, sso_email: owner.email }), { status: 200 })))
  assert.deepEqual(connected, [])
})
