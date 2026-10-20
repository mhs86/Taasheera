import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import { afterEach, test } from 'node:test'
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

registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('.svg')) return { format: 'module', source: `export default ${JSON.stringify(url)}`, shortCircuit: true }
    return nextLoad(url, context)
  },
})

const { routes } = await import('../src/routes.tsx')

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const ADMIN = { id: 1, name: 'Adam Admin', email: 'adam@example.com', role: 'admin' }
const MAYA = {
  id: 7, name: 'Maya Haddad', email: 'maya@example.com', auth_type: 'email_password', role: 'traveler', status: 'active',
  created_at: '2026-10-01T08:30:00Z', last_sign_in_at: '2026-10-17T09:00:00Z',
}
const MAYA_DETAIL = {
  ...MAYA, sso_email: null, password_enabled: true, google_linked: false, last_sign_in_method: 'email_password',
  counts: { active_sessions: 2, sign_ins: 5, failed_sign_ins: 1, passport_uploads: 1 },
}
const OVERVIEW = { total_users: 12, new_last_7_days: 3, suspended: 1, applications_started: 4 }

// A fake backend: each test lists the responses it expects, keyed by "METHOD path".
let handlers
let calls
globalThis.fetch = async (url, options = {}) => {
  const key = `${options.method ?? 'GET'} ${url}`
  calls.push({ key, body: options.body, headers: options.headers })
  const handler = handlers[key]
  assert.ok(handler, `Unexpected request: ${key}`)
  return handler(options)
}

function backend(extra) {
  calls = []
  handlers = {
    'POST /auth/refresh': () => json({ access_token: 'token' }),
    'GET /auth/me': () => json({ id: ADMIN.id, name: ADMIN.name, email: ADMIN.email }),
    'GET /auth/config': () => json({ google_client_id: null }),
    'POST /activity/events': () => new Response(null, { status: 204 }),
    'GET /admin-api/me': () => json(ADMIN),
    'GET /admin-api/overview': () => json(OVERVIEW),
    'GET /admin-api/users?page=1&page_size=20': () => json({ items: [MAYA], total: 1, page: 1, page_size: 20 }),
    'GET /admin-api/users/7': () => json(MAYA_DETAIL),
    ...extra,
  }
}

let root
let container
let router
async function render(path) {
  container = document.createElement('div')
  document.body.append(container)
  router = createMemoryRouter(routes, { initialEntries: [path] })
  root = createRoot(container)
  await act(async () => root.render(createElement(RouterProvider, { router })))
  await settle()
}
const settle = () => act(() => new Promise(resolve => setTimeout(resolve, 30)))
const $ = selector => container.querySelector(selector)
const page = () => document.body.textContent
const button = label => [...container.querySelectorAll('button')].find(item => item.textContent === label)
const requested = prefix => calls.filter(call => call.key.startsWith(prefix))

async function click(element) {
  assert.ok(element, 'Missing element to click')
  await act(async () => element.dispatchEvent(new window.MouseEvent('click', { bubbles: true })))
  await settle()
}

async function choose(element, value) {
  await act(async () => {
    element.value = value
    element.dispatchEvent(new window.Event('change', { bubbles: true }))
  })
  await settle()
}

async function type(element, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(element, value)
    element.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
}

afterEach(async () => {
  await act(async () => root?.unmount())
  container?.remove()
  document.body.querySelectorAll('[data-sonner-toaster]').forEach(node => node.remove())
})

test('signed-out visitors are sent to sign-in before any admin request', async () => {
  backend({ 'POST /auth/refresh': () => json({ detail: 'Invalid or expired refresh token.' }, 401) })
  await render('/admin')
  assert.equal(router.state.location.pathname, '/sign-in')
  assert.deepEqual(requested('GET /admin-api'), [])
})

for (const path of ['/admin', '/admin/users/7', '/admin/anything']) {
  test(`a traveler is sent home from ${path} with a notice`, async () => {
    backend({ 'GET /admin-api/me': () => json({ detail: 'Admin access required.' }, 403) })
    await render(path)
    assert.equal(router.state.location.pathname, '/')
    assert.match(page(), /Admin access required\./)
    // Only the access check ran: no user data was requested.
    assert.deepEqual(requested('GET /admin-api').map(call => call.key), ['GET /admin-api/me'])
  })
}

test('the overview cards and users table load, with every request carrying the bearer token', async () => {
  backend()
  await render('/admin')
  assert.equal(router.state.location.pathname, '/admin')
  for (const value of ['Total users12', 'New in the last 7 days3', 'Suspended1', 'Applications started4']) {
    assert.ok(page().replace(/\s+/g, '').includes(value.replace(/\s+/g, '')), value)
  }
  assert.ok($('a[href="/admin/users/7"]'))
  assert.match(page(), /maya@example\.com/)
  assert.match(page(), /1 user found/)
  for (const call of requested('GET /admin-api')) assert.equal(call.headers.Authorization, 'Bearer token')
})

test('search and filters go to the API and stay in the URL', async () => {
  backend({
    'GET /admin-api/users?q=maya%40example.com&page=1&page_size=20': () => json({ items: [MAYA], total: 1, page: 1, page_size: 20 }),
    'GET /admin-api/users?q=maya%40example.com&status=suspended&page=1&page_size=20': () => json({ items: [], total: 0, page: 1, page_size: 20 }),
  })
  await render('/admin')
  await type($('#admin-search'), '  maya@example.com ')
  await act(async () => $('form[role="search"]').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
  await settle()
  assert.equal(router.state.location.search, '?q=maya%40example.com')
  await choose($('#admin-status'), 'suspended')
  assert.equal(router.state.location.search, '?q=maya%40example.com&status=suspended')
  assert.match(page(), /0 users found/)
})

test('pagination moves between pages', async () => {
  const many = { items: [MAYA], total: 45, page: 1, page_size: 20 }
  backend({
    'GET /admin-api/users?page=1&page_size=20': () => json(many),
    'GET /admin-api/users?page=2&page_size=20': () => json({ ...many, page: 2 }),
  })
  await render('/admin')
  assert.match(page(), /Page 1 of 3/)
  assert.equal(button('Previous').disabled, true)
  await click(button('Next'))
  assert.match(page(), /Page 2 of 3/)
  assert.equal(requested('GET /admin-api/users?page=2').length, 1)
})

test('the detail panel shows account information and counts, never passport data', async () => {
  backend()
  await render('/admin/users/7')
  for (const value of ['Maya Haddad', 'maya@example.com', 'Email and password', 'Traveler', 'Active',
    'Active sessions2', 'Sign-ins5', 'Failed sign-ins1', 'Passport uploads1']) {
    assert.ok(page().replace(/\s+/g, '').includes(value.replace(/\s+/g, '')), value)
  }
})

test('suspending asks for confirmation first, then shows a success toast', async () => {
  backend({ 'POST /admin-api/users/7/suspend': () => json({ ...MAYA_DETAIL, status: 'suspended', counts: { ...MAYA_DETAIL.counts, active_sessions: 0 } }) })
  await render('/admin/users/7')
  await click(button('Suspend'))
  assert.match(page(), /Suspend Maya Haddad\? They will be signed out on every device/)
  assert.deepEqual(requested('POST /admin-api'), [])
  await click(button('Yes, suspend'))
  assert.deepEqual(requested('POST /admin-api').map(call => call.key), ['POST /admin-api/users/7/suspend'])
  assert.match(page(), /Maya Haddad is suspended and signed out everywhere\./)
  assert.ok(button('Reactivate'))
  assert.match(page(), /Suspended/)
})

test('cancelling a confirmation sends nothing', async () => {
  backend()
  await render('/admin/users/7')
  await click(button('Suspend'))
  await click(button('Cancel'))
  assert.equal(button('Yes, suspend'), undefined)
  await choose($('#admin-new-role'), 'admin')
  await click(button('Change role'))
  assert.match(page(), /Change Maya Haddad's role from Traveler to Admin\?/)
  await click(button('Cancel'))
  assert.equal($('#admin-new-role').value, 'traveler')
  assert.deepEqual(requested('POST /admin-api').concat(requested('PUT /admin-api')), [])
})

test('a role change sends only the role and toasts the result', async () => {
  backend({ 'PUT /admin-api/users/7/role': () => json({ ...MAYA_DETAIL, role: 'support' }) })
  await render('/admin/users/7')
  assert.equal(button('Change role').disabled, true)  // Nothing to change yet.
  await choose($('#admin-new-role'), 'support')
  await click(button('Change role'))
  await click(button('Yes, change role'))
  assert.deepEqual(requested('PUT /admin-api').map(call => JSON.parse(call.body)), [{ role: 'support' }])
  assert.match(page(), /Maya Haddad is now support staff\./)
})

test('a refused action shows the server message as an error toast', async () => {
  backend({ 'POST /admin-api/users/7/suspend': () => json({ detail: 'This account is already suspended.' }, 409) })
  await render('/admin/users/7')
  await click(button('Suspend'))
  await click(button('Yes, suspend'))
  assert.match(page(), /This account is already suspended\./)
  assert.equal(button('Yes, suspend'), undefined)
})

test('losing admin access mid-session sends the admin away', async () => {
  backend({ 'POST /admin-api/users/7/suspend': () => json({ detail: 'Admin access required.' }, 403) })
  await render('/admin/users/7')
  await click(button('Suspend'))
  await click(button('Yes, suspend'))
  assert.equal(router.state.location.pathname, '/')
  assert.match(page(), /Admin access required\./)
})

test('admins cannot act on their own account from the dashboard', async () => {
  backend({ 'GET /admin-api/users/1': () => json({ ...MAYA_DETAIL, id: 1, name: 'Adam Admin', role: 'admin' }) })
  await render('/admin/users/1')
  assert.match(page(), /This is your account\. You can't suspend it or change its role/)
  assert.equal(button('Suspend'), undefined)
  assert.equal($('#admin-new-role'), null)
})

test('an unknown user shows not found', async () => {
  backend({ 'GET /admin-api/users/99': () => json({ detail: 'User not found.' }, 404) })
  await render('/admin/users/99')
  assert.match(page(), /User not found\./)
  await render('/admin/users/abc')
  assert.match(page(), /User not found\./)
  assert.equal(requested('GET /admin-api/users/abc').length, 0)
})
