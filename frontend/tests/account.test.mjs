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

function mockApi(profile = blank, saveReply) {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options })
    if (url === '/auth/refresh') return Response.json({ access_token: 'synthetic-access' })
    if (url === '/auth/me') return Response.json(traveler)
    if (url === '/profile' && options?.method === 'PUT') {
      return saveReply ? saveReply() : Response.json({ ...JSON.parse(options.body), phone: '+96171123456' })
    }
    if (url === '/profile') return Response.json(profile)
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
})
