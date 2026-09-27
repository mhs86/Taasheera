import assert from 'node:assert/strict'
import { test } from 'node:test'

// Exercise the real session module without persisting tokens or requiring a DOM.
let queue = Promise.resolve()
Object.defineProperty(navigator, 'locks', { value: {
  request(_name, action) {
    const result = queue.then(action)
    queue = result.catch(() => {})
    return result
  },
} })
const traveler = { id: 1, name: 'Maya Haddad', email: 'maya@example.com' }
let calls = []
let responses = []
globalThis.fetch = async (url, options) => {
  calls.push({ url, ...options })
  assert.equal(options.credentials, 'same-origin')
  assert.equal(options.cache, 'no-store')
  const next = responses.shift()
  assert.ok(next, `Unexpected request: ${url}`)
  return new Response(next.status === 204 ? null : JSON.stringify(next.body), { status: next.status })
}
const auth = await import('../src/auth.ts')
function arrange(...next) { calls = []; responses = next }

test('correct password loads the name from protected /me using a bearer token', async () => {
  arrange({ status: 200, body: { access_token: 'test-access' } }, { status: 200, body: traveler })
  assert.deepEqual(await auth.signIn(' maya@example.com ', 'correct-password'), traveler)
  assert.deepEqual(calls.map(c => c.url), ['/auth/login', '/auth/me'])
  assert.deepEqual(JSON.parse(calls[0].body), { email: 'maya@example.com', password: 'correct-password' })
  assert.equal(calls[1].headers.Authorization, 'Bearer test-access')
})

test('wrong password reports a generic error and never requests protected profile', async () => {
  arrange({ status: 401, body: { detail: 'Invalid email or password.' } })
  await assert.rejects(auth.signIn(traveler.email, 'wrong'), /Invalid email or password/)
  assert.equal(calls.length, 1)
})

test('reload restores from the cookie and concurrent mounts share one refresh', async () => {
  arrange({ status: 200, body: { access_token: 'restored-access' } }, { status: 200, body: traveler })
  const first = auth.restoreSession()
  const second = auth.restoreSession()
  assert.equal(first, second)
  assert.deepEqual(await first, traveler)
  assert.deepEqual(calls.map(c => c.url), ['/auth/refresh', '/auth/me'])
  assert.equal(calls[0].headers, undefined)
  assert.equal(calls[1].headers.Authorization, 'Bearer restored-access')
})

test('missing or expired cookie returns signed-out state without protected access', async () => {
  arrange({ status: 401, body: {} })
  assert.equal(await auth.restoreSession(), null)
  assert.equal(calls.length, 1)
})

test('profile failure never produces a signed-in traveler', async () => {
  arrange({ status: 200, body: { access_token: 'revoked' } }, { status: 401, body: {} })
  await assert.rejects(auth.signIn(traveler.email, 'correct-password'), /Could not load/)
})

test('logout waits for backend revocation; reload stays signed out', async () => {
  arrange({ status: 204 }, { status: 401, body: {} })
  await auth.signOut()
  assert.equal(await auth.restoreSession(), null)
  assert.deepEqual(calls.map(c => c.url), ['/auth/logout', '/auth/refresh'])
})

test('logout failure is retryable and does not report success', async () => {
  arrange({ status: 503, body: {} }, { status: 204 })
  await assert.rejects(auth.signOut(), /Could not log out/)
  await auth.signOut()
})

test('restore service failure is distinct from an absent session and is retryable', async () => {
  arrange({ status: 503, body: {} }, { status: 401, body: {} })
  await assert.rejects(auth.restoreSession(), /Could not restore/)
  assert.equal(await auth.restoreSession(), null)
})
