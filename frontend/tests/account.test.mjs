import './dom-setup.mjs'
import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import { afterEach, test } from 'node:test'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('.svg')) return { format: 'module', source: `export default ${JSON.stringify(url)}`, shortCircuit: true }
    return nextLoad(url, context)
  },
})

const { default: App } = await import('../src/App.tsx')
const { countries } = await import('../src/countries.ts')
const { routes } = await import('../src/routes.tsx')

const traveler = { id: 1, name: 'Traveler', email: 'traveler@example.com',
  sso_email: null, password_enabled: true }
const blank = { surname: null, given_names: null, birth_date: null, nationality: null,
  phone: null, address_line1: null, address_line2: null, address_city: null,
  address_region: null, address_postal_code: null, address_country: null }
const currentSession = { id: 'current', device_label: 'Chrome on Windows',
  created_at: '2026-10-16T10:00:00Z', last_active_at: '2026-10-16T11:00:00Z', current: true }
const otherSession = { id: 'other', device_label: 'Firefox on Android',
  created_at: null, last_active_at: null, current: false }
let root

function setInput(id, value) {
  const input = document.getElementById(id)
  assert.ok(input, `Missing ${id}`)
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
    input.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
}

function setSelect(id, value) {
  const select = document.getElementById(id)
  assert.ok(select, `Missing ${id}`)
  act(() => {
    select.value = value
    select.dispatchEvent(new window.Event('change', { bubbles: true }))
  })
}

async function mount(accountPage = true) {
  root = createRoot(document.getElementById('root'))
  await act(async () => root.render(createElement(App, {
    initialNavigation: { page: 'sign-in', resetToken: null }, accountPage, googleClientId: '',
  })))
}

function mockApi(profile = blank, saveReply, sessionsReply = () => Response.json([currentSession])) {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options })
    if (url === '/auth/refresh') return Response.json({ access_token: 'synthetic-access' })
    if (url === '/auth/me') return Response.json(traveler)
    if (url === '/profile' && options?.method === 'PUT') {
      return saveReply ? saveReply() : Response.json({ ...JSON.parse(options.body), phone: '+96171123456' })
    }
    if (url === '/profile') return Response.json(profile)
    if (url === '/sessions') return sessionsReply(options)
    assert.fail(`Unexpected request: ${url}`)
  }
  return calls
}

afterEach(async () => {
  if (root) await act(async () => root.unmount())
  root = null
})

test('country choices have unique passport codes and include Lebanon and Germany', () => {
  const codes = countries.map(country => country.code)
  assert.equal(new Set(codes).size, codes.length)
  assert.deepEqual(countries.find(country => country.code === 'LBN'), { name: 'Lebanon', code: 'LBN' })
  assert.deepEqual(countries.find(country => country.code === 'D'), { name: 'Germany', code: 'D' })
  assert.equal(codes.includes('DEU'), false)
})

test('/account is a page route and /profile is reserved for the API', () => {
  assert.ok(routes.some(route => route.path === 'account'))
  assert.equal(routes.some(route => route.path === 'profile'), false)
})

test('profile loading is visible until the protected request finishes', async () => {
  let finish
  globalThis.fetch = async url => {
    if (url === '/auth/refresh') return Response.json({ access_token: 'synthetic-access' })
    if (url === '/auth/me') return Response.json(traveler)
    if (url === '/profile') return new Promise(resolve => { finish = resolve })
    if (url === '/sessions') return Response.json([currentSession])
    assert.fail(`Unexpected request: ${url}`)
  }
  await mount()
  assert.match(document.querySelector('.profile-section [role="status"]').textContent, /Loading your profile/)
  assert.equal(document.querySelector('.profile-section form'), null)
  await act(async () => finish(Response.json(blank)))
  assert.ok(document.querySelector('.profile-section form'))
})

test('account form loads existing values and keeps methods and password sections together', async () => {
  const calls = mockApi({ ...blank, surname: 'Haddad', given_names: 'Maya', birth_date: '1998-04-03',
    nationality: 'LBN', phone: '+96171123456', address_line1: 'Example street', address_country: 'D' })
  await mount()
  assert.equal(document.getElementById('profile-surname').value, 'Haddad')
  assert.equal(document.getElementById('profile-birth_date').value, '1998-04-03')
  assert.equal(document.getElementById('profile-nationality').value, 'LBN')
  assert.equal(document.querySelector('#profile-nationality option:checked').textContent, 'Lebanon')
  assert.equal(document.querySelector('#profile-address_country option:checked').textContent, 'Germany')
  assert.ok(document.getElementById('sign-in-methods-heading'))
  assert.ok(document.getElementById('change-password-heading'))
  assert.ok(document.getElementById('sessions-heading'))
  assert.equal(document.querySelectorAll('#sign-in-methods-heading').length, 1)
  assert.equal(document.querySelector('a[href="/sign-in"]').textContent, 'Back to welcome')
  assert.equal(calls.find(call => call.url === '/profile').headers.Authorization, 'Bearer synthetic-access')
})

test('empty profile has a clear state and every optional field is editable', async () => {
  mockApi()
  await mount()
  assert.match(document.body.textContent, /No profile details saved yet/)
  for (const key of Object.keys(blank)) assert.ok(document.querySelector(`[name="${key}"]`), key)
  assert.equal(document.getElementById('profile-surname').value, '')
})

test('save sends every field and uses null for optional empty codes and date', async () => {
  const calls = mockApi({ ...blank, given_names: 'Maya', address_line2: 'Suite 2' })
  await mount()
  setInput('profile-surname', 'Haddad')
  setInput('profile-given_names', '')
  setInput('profile-phone', '+961 71 123 456')
  setInput('profile-address_line2', '')
  setSelect('profile-nationality', 'LBN')
  setSelect('profile-address_country', 'D')
  await act(async () => document.querySelector('.profile-section form').dispatchEvent(
    new window.Event('submit', { bubbles: true, cancelable: true })))
  const request = calls.find(call => call.url === '/profile' && call.method === 'PUT')
  assert.ok(request)
  assert.equal(request.headers.Authorization, 'Bearer synthetic-access')
  assert.deepEqual(JSON.parse(request.body), {
    ...blank, surname: 'Haddad', given_names: '', phone: '+961 71 123 456',
    nationality: 'LBN', address_line2: '', address_country: 'D',
  })
  assert.equal(document.getElementById('profile-phone').value, '+96171123456')
  assert.match(document.querySelector('.profile-section [role="status"]').textContent, /Profile saved/)
})

test('backend field errors appear beside the field and leave the form retryable', async () => {
  mockApi(blank, () => Response.json({ detail: [
    { loc: ['body', 'phone'], msg: 'Value error, Phone must be a valid international number.', type: 'value_error' },
  ] }, { status: 422 }))
  await mount()
  setInput('profile-phone', '+999123')
  await act(async () => document.querySelector('.profile-section form').dispatchEvent(
    new window.Event('submit', { bubbles: true, cancelable: true })))
  assert.match(document.getElementById('profile-phone-error').textContent, /Phone must be a valid international number/)
  assert.equal(document.getElementById('profile-phone').getAttribute('aria-invalid'), 'true')
  assert.match(document.querySelector('.profile-section form .auth-error').textContent, /correct the highlighted fields/)
  assert.equal(document.querySelector('.profile-section button[type="submit"]').disabled, false)
})

test('a server failure gives a general error without losing entered values', async () => {
  mockApi(blank, () => Response.json({}, { status: 500 }))
  await mount()
  setInput('profile-surname', 'Haddad')
  await act(async () => document.querySelector('.profile-section form').dispatchEvent(
    new window.Event('submit', { bubbles: true, cancelable: true })))
  assert.match(document.querySelector('.profile-section form .auth-error').textContent, /Something went wrong/)
  assert.equal(document.getElementById('profile-surname').value, 'Haddad')
})

test('welcome links to account and does not duplicate its sections', async () => {
  mockApi()
  await mount(false)
  assert.equal(document.querySelector('a[href="/account"]').textContent, 'Edit your account details')
  assert.equal(document.getElementById('profile-heading'), null)
  assert.equal(document.getElementById('sign-in-methods-heading'), null)
  assert.equal(document.getElementById('change-password-heading'), null)
  assert.equal(document.getElementById('sessions-heading'), null)
})

test('sessions list marks this device and shows Unknown for legacy dates', async () => {
  mockApi(blank, undefined, () => Response.json([currentSession, otherSession]))
  await mount()
  const rows = document.querySelectorAll('.sessions-list li')
  assert.equal(rows.length, 2)
  assert.match(rows[0].textContent, /Chrome on Windows.*This device.*Signed in:.*Last active:/)
  assert.equal(rows[0].querySelector('button'), null)
  assert.match(rows[1].textContent, /Firefox on Android.*Signed in: Unknown.*Last active: Unknown/)
  assert.equal(rows[1].querySelector('button').textContent, 'End session')
  assert.equal(document.querySelector('.sessions-section [role="alert"]'), null)
})

test('ending one session confirms, sends DELETE, refreshes the list, and reports success', async () => {
  let listed = [currentSession, otherSession]
  const calls = mockApi(blank, undefined, () => Response.json(listed))
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    if (url === '/sessions/other' && options?.method === 'DELETE') {
      calls.push({ url, ...options })
      listed = [currentSession]
      return new Response(null, { status: 204 })
    }
    return originalFetch(url, options)
  }
  await mount()
  await act(async () => document.querySelector('.session-end').click())
  assert.equal(calls.some(call => call.method === 'DELETE'), false)
  assert.match(document.querySelector('.session-confirm').textContent, /End this session/)
  await act(async () => document.querySelector('.session-confirm .primary-button').click())
  assert.equal(calls.find(call => call.method === 'DELETE').url, '/sessions/other')
  assert.equal(calls.filter(call => call.url === '/sessions').length, 2)
  assert.equal(document.querySelectorAll('.sessions-list li').length, 1)
  assert.match(document.querySelector('.sessions-section [role="status"]').textContent, /Session ended/)
})

test('sign out all other devices appears only when needed and can be cancelled', async () => {
  const calls = mockApi(blank, undefined, () => Response.json([currentSession, otherSession]))
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    if (url === '/sessions/revoke-others') {
      calls.push({ url, ...options })
      return Response.json({ ended: 1 })
    }
    return originalFetch(url, options)
  }
  await mount()
  const all = [...document.querySelectorAll('.sessions-section button')]
    .find(button => button.textContent.includes('Sign out all other devices'))
  assert.ok(all)
  await act(async () => all.click())
  await act(async () => document.querySelector('.session-confirm .google-retry').click())
  assert.equal(calls.some(call => call.url === '/sessions/revoke-others'), false)
})

test('signing out all other devices sends POST and reloads the list', async () => {
  let listed = [currentSession, otherSession]
  const calls = mockApi(blank, undefined, () => Response.json(listed))
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    if (url === '/sessions/revoke-others' && options?.method === 'POST') {
      calls.push({ url, ...options })
      listed = [currentSession]
      return Response.json({ ended: 1 })
    }
    return originalFetch(url, options)
  }
  await mount()
  const all = [...document.querySelectorAll('.sessions-section button')]
    .find(button => button.textContent.includes('Sign out all other devices'))
  await act(async () => all.click())
  await act(async () => document.querySelector('.session-confirm .primary-button').click())
  assert.equal(calls.find(call => call.url === '/sessions/revoke-others' && call.method === 'POST').url,
    '/sessions/revoke-others')
  assert.equal(calls.filter(call => call.url === '/sessions').length, 2)
  assert.equal(document.querySelectorAll('.sessions-list li').length, 1)
  assert.match(document.querySelector('.sessions-section [role="status"]').textContent, /Other devices have been signed out/)
})

test('an empty sessions list has a clear state', async () => {
  mockApi(blank, undefined, () => Response.json([]))
  await mount()
  assert.match(document.querySelector('.sessions-section').textContent, /No active sessions found/)
  assert.equal(document.querySelector('.sessions-section button'), null)
})

test('only this device has a clear state and no end-all button', async () => {
  mockApi()
  await mount()
  assert.match(document.querySelector('.sessions-section').textContent, /Only this device is signed in/)
  assert.equal(document.querySelector('.sessions-section').textContent.includes('Sign out all other devices'), false)
})

test('sessions load errors show retry; action errors remain retryable', async () => {
  let loads = 0
  const calls = mockApi(blank, undefined, () => {
    loads += 1
    return loads === 1 ? Response.json({}, { status: 500 }) : Response.json([currentSession, otherSession])
  })
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    if (url === '/sessions/other' && options?.method === 'DELETE') {
      calls.push({ url, ...options })
      return Response.json({}, { status: 500 })
    }
    return originalFetch(url, options)
  }
  await mount()
  assert.match(document.querySelector('.sessions-section [role="alert"]').textContent, /Could not load/)
  await act(async () => document.querySelector('.sessions-section .google-retry').click())
  assert.equal(document.querySelectorAll('.sessions-list li').length, 2)
  await act(async () => document.querySelector('.session-end').click())
  await act(async () => document.querySelector('.session-confirm .primary-button').click())
  assert.match(document.querySelector('.sessions-section [role="alert"]').textContent, /Could not end/)
  assert.equal(document.querySelector('.session-confirm .primary-button').disabled, false)
})
