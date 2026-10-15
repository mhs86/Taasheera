import './dom-setup.mjs'
import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

const { default: App } = await import('../src/App.tsx')

let root
const profile = { id: 1, name: 'Traveler', email: 'traveler@example.com',
  password_enabled: true, sso_email: null }

async function showAccount(traveler = profile, changeStatus = 204) {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options })
    if (url === '/auth/refresh') return Response.json({ access_token: 'synthetic-access' })
    if (url === '/auth/me') return Response.json(traveler)
    if (url === '/auth/change-password') return new Response(
      changeStatus === 204 ? null : '{}', { status: changeStatus })
    assert.fail(`Unexpected request: ${url}`)
  }
  root = createRoot(document.getElementById('root'))
  await act(async () => root.render(createElement(App, {
    initialNavigation: { page: 'sign-in', resetToken: null }, googleClientId: '',
  })))
  return calls
}

function fill(id, value) {
  const input = document.getElementById(id)
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
    input.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
}

async function submit() {
  await act(async () => document.querySelector('.change-password form').dispatchEvent(
    new window.Event('submit', { bubbles: true, cancelable: true })))
}

afterEach(async () => {
  if (root) await act(async () => root.unmount())
  root = null
})

test('change password form shows for email accounts and hides for Google-only accounts', async () => {
  await showAccount()
  assert.ok(document.getElementById('change-password-heading'))
  assert.ok(document.getElementById('current-password'))
  await act(async () => root.unmount()); root = null
  await showAccount({ ...profile, password_enabled: false, sso_email: 'google@example.com' })
  assert.equal(document.getElementById('change-password-heading'), null)
})

test('successful change sends only the two passwords and clears the form', async () => {
  const calls = await showAccount()
  fill('current-password', 'Current-password-123')
  fill('new-password', 'Different-password-456')
  fill('confirm-new-password', 'Different-password-456')
  await submit()
  const request = calls.find(call => call.url === '/auth/change-password')
  assert.ok(request)
  assert.equal(request.headers.Authorization, 'Bearer synthetic-access')
  assert.deepEqual(JSON.parse(request.body), {
    current_password: 'Current-password-123', new_password: 'Different-password-456',
  })
  assert.match(document.querySelector('.change-password [role="status"]').textContent, /other sessions have been signed out/)
  for (const id of ['current-password', 'new-password', 'confirm-new-password']) {
    assert.equal(document.getElementById(id).value, '')
  }
})

test('wrong current password shows an error and leaves the form retryable', async () => {
  await showAccount(profile, 403)
  fill('current-password', 'Wrong-password-123')
  fill('new-password', 'Different-password-456')
  fill('confirm-new-password', 'Different-password-456')
  await submit()
  assert.match(document.querySelector('.change-password [role="alert"]').textContent, /Current password is incorrect/)
  assert.equal(document.querySelector('.change-password button').disabled, false)
})
