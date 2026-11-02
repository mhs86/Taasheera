import './dom-setup.mjs'
import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
const { restoreSession, signIn } = await import('../src/auth.ts')
const { deleteAccount } = await import('../src/privacy.ts')
const { default: DeleteAccount } = await import('../src/DeleteAccount.tsx')
const { default: DocumentHistory } = await import('../src/DocumentHistory.tsx')
const { default: AdminDashboard } = await import('../src/pages/AdminDashboard.tsx')
const { scrubBrowserEvent } = await import('../src/monitoring.ts')

const traveler = { id: 7, name: 'Synthetic Traveler', email: 'test@example.com', password_enabled: true }
let root
afterEach(async () => { if (root) await act(async () => root.unmount()); root = null })

function input(id, value) {
  const element = document.getElementById(id)
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(element, value)
    element.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
}

function button(text) {
  const found = [...document.querySelectorAll('button')].find(element => element.textContent === text)
  assert.ok(found, `Missing ${text}`); return found
}

function apiMock(handler) {
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, ...options })
    if (url === '/auth/refresh') return Response.json({ access_token: 'synthetic-access' })
    if (url === '/auth/me') return Response.json(traveler)
    return handler(url, options)
  }
  return calls
}

async function mount(component, props = {}) {
  root = createRoot(document.getElementById('root'))
  await act(async () => { await restoreSession(); root.render(createElement(component, props)) })
}

test('account deletion requires confirmation, can cancel, and clears password after rejection', async () => {
  const calls = apiMock(url => {
    assert.equal(url, '/auth/account'); return Response.json({ detail: 'private diagnostics' }, { status: 403 })
  })
  let deleted = false
  await mount(DeleteAccount, { traveler, clientId: '', onDeleted: () => { deleted = true } })
  await act(async () => button('Delete my account').click())
  assert.equal(button('Permanently delete account').disabled, true)
  await act(async () => button('Cancel').click())
  assert.equal(calls.some(call => call.method === 'DELETE'), false)
  await act(async () => button('Delete my account').click())
  input('delete-current-password', 'test-password'); input('delete-confirmation', 'DELETE')
  await act(async () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
  assert.equal(deleted, false)
  assert.equal(document.getElementById('delete-current-password').value, '')
  assert.match(document.querySelector('[role="alert"]').textContent, /Confirm your current password/)
  assert.equal(document.body.textContent.includes('private diagnostics'), false)
  const sent = calls.find(call => call.method === 'DELETE')
  assert.equal(sent.headers.Authorization, 'Bearer synthetic-access')
  assert.deepEqual(JSON.parse(sent.body), { confirmation: 'DELETE', expected_traveler_id: 7, password: 'test-password' })
})

test('successful account deletion and queued cleanup have distinct outcomes and prevent duplicate submits', async () => {
  for (const status of [204, 202]) {
    let finish
    const calls = apiMock(() => new Promise(resolve => { finish = resolve }))
    let outcome
    await mount(DeleteAccount, { traveler, clientId: '', onDeleted: complete => { outcome = complete } })
    await act(async () => button('Delete my account').click())
    input('delete-current-password', 'test-password'); input('delete-confirmation', 'DELETE')
    await act(async () => {
      const form = document.querySelector('form')
      form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }))
      form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }))
    })
    assert.equal(calls.filter(call => call.method === 'DELETE').length, 1)
    assert.equal(button('Deleting…').disabled, true)
    await act(async () => finish(new Response(null, { status })))
    assert.equal(outcome, status === 204)
    await act(async () => root.unmount()); root = null
  }
})

test('deletion serializes with sign-in so a late deletion cannot clear a new session', async () => {
  let finish
  const calls = apiMock(url => {
    if (url === '/auth/account') return new Promise(resolve => { finish = resolve })
    if (url === '/auth/login') return Response.json({ access_token: 'new-session' })
    assert.fail(`Unexpected request ${url}`)
  })
  await restoreSession()
  const deleting = deleteAccount(7, 'test-password', '')
  await new Promise(resolve => setTimeout(resolve, 0))
  const signingIn = signIn('new@example.com', 'test-password')
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(calls.some(call => call.url === '/auth/login'), false)
  finish(new Response(null, { status: 204 }))
  assert.equal(await deleting, true)
  assert.equal((await signingIn).id, 7)
  assert.equal(calls.at(-1).url, '/auth/me')
  assert.equal(calls.at(-1).headers.Authorization, 'Bearer new-session')
})

test('document history loads on request, exposes empty/error states and paginates', async () => {
  let loads = 0
  const calls = apiMock(url => {
    loads += 1
    if (loads === 1) return Response.json({}, { status: 500 })
    if (loads === 2) return Response.json({ items: [], total: 0, page: 1, page_size: 20 })
    assert.ok(url.startsWith('/activity/documents?page='))
    return Response.json({ items: [{ id: 1, upload_id: 'abc12345longid', actor_id: 7, accessor: 'You',
      purpose: 'assistant_context', occurred_at: '2026-10-31T08:00:00' }], total: 21, page: loads === 3 ? 1 : 2, page_size: 20 })
  })
  await mount(DocumentHistory)
  assert.equal(loads, 0)
  await act(async () => button('Refresh access history').click())
  assert.match(document.querySelector('[role="alert"]').textContent, /Could not load/)
  await act(async () => button('Refresh access history').click())
  assert.match(document.body.textContent, /No document access recorded/)
  await act(async () => button('Refresh access history').click())
  assert.match(document.querySelector('.access-history').textContent, /You.*Read for assistant context/)
  assert.match(document.querySelector('.access-history').textContent, /abc12345/)
  await act(async () => button('Next').click())
  assert.equal(calls.at(-1).url, '/activity/documents?page=2')
})

test('non-admin cannot load dashboard data even with a client-side route', async () => {
  const calls = apiMock(url => { assert.equal(url, '/admin-api/me'); return Response.json({}, { status: 403 }) })
  await mount(AdminDashboard)
  assert.match(document.querySelector('[role="alert"]').textContent, /active admin/)
  assert.equal(calls.some(call => call.url.includes('/users') || call.url.includes('/monitoring')), false)
  assert.equal(document.querySelector('table'), null)
})

test('admin sees genuine empty status counts, safe errors, and must confirm selected-user deletion', async () => {
  let users = [{ id: 9, name: 'Synthetic User', email: 'synthetic@example.com', role: 'traveler', status: 'active' }]
  const calls = apiMock((url, options) => {
    if (url === '/admin-api/me') return Response.json({ id: 7, name: 'Admin', role: 'admin' })
    if (url === '/admin-api/monitoring') return Response.json({ total_applications: 0,
      applications_by_status: { DRAFT: 0, FAILED: 0 }, recent_errors: [], agent_failures_available: false, pending_erasures: 0 })
    if (url.startsWith('/admin-api/users?')) return Response.json({ items: users, total: users.length, page: 1, page_size: 20 })
    if (url === '/admin-api/users/9' && options.method === 'DELETE') { users = []; return new Response(null, { status: 204 }) }
    assert.fail(`Unexpected request ${url}`)
  })
  await mount(AdminDashboard)
  assert.match(document.body.textContent, /No applications have been started/)
  assert.match(document.body.textContent, /No errors recorded/)
  await act(async () => button('Delete user').click())
  assert.equal(button('Confirm permanent deletion').disabled, true)
  await act(async () => button('Cancel').click())
  assert.equal(calls.some(call => call.method === 'DELETE'), false)
  await act(async () => button('Delete user').click())
  input('admin-delete-confirmation', 'DELETE')
  await act(async () => document.querySelector('.deletion-confirm').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
  const deleted = calls.find(call => call.method === 'DELETE')
  assert.deepEqual(JSON.parse(deleted.body), { confirmation: 'DELETE', expected_user_id: 9 })
  assert.match(document.body.textContent, /User and associated data deleted/)
  assert.match(document.body.textContent, /No users match your search/)
})

test('browser Sentry payload drops credentials, URLs, forms and exception messages', () => {
  const output = scrubBrowserEvent({ event_id: 'safe-id', message: 'private passport', request: { url: '/reset#secret' },
    user: { email: 'private@example.com' }, breadcrumbs: [{ password: 'secret' }], extra: { document: 'private' } })
  assert.equal(output.event_id, 'safe-id')
  assert.equal(output.message, 'Taasheera page error')
  assert.equal(/private|secret|password/.test(JSON.stringify(output)), false)
})
