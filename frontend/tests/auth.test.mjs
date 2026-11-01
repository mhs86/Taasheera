import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

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

test('a suspended account is told so by either sign-in method, and an origin refusal is not mistaken for it', async () => {
  const suspended = { status: 403, body: { detail: { code: 'account_suspended', message: 'This account is suspended.' } } }
  arrange(suspended)
  await assert.rejects(auth.signIn(traveler.email, 'correct-password'), /This account is suspended/)
  arrange(suspended)
  await assert.rejects(auth.signInWithGoogle('google-id-token'), /This account is suspended/)
  assert.deepEqual(calls.map(c => c.url), ['/auth/google'])
  arrange({ status: 403, body: { detail: 'Origin is not allowed.' } })
  await assert.rejects(auth.signIn(traveler.email, 'correct-password'), /temporarily unavailable/)
  assert.equal(auth.hasAccessToken(), false)
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

test('activity requests use the in-memory bearer token and contain only event identifiers', async () => {
  arrange({ status: 200, body: { access_token: 'activity-token' } },
    { status: 200, body: traveler }, { status: 204 })
  await auth.signIn(traveler.email, 'correct-password')
  assert.equal(await auth.postActivity({ event_type: 'click', page: 'faq',
    control: 'faq-question', outcome: 'initiated' }), true)
  const call = calls.at(-1)
  assert.equal(call.url, '/activity/events')
  assert.equal(call.headers.Authorization, 'Bearer activity-token')
  assert.deepEqual(JSON.parse(call.body), { event_type: 'click', page: 'faq',
    control: 'faq-question', outcome: 'initiated' })
  assert.equal(call.body.includes('correct-password'), false)
  assert.equal(call.body.includes('activity-token'), false)

  arrange({ status: 204 })
  await auth.signOut()
  assert.equal(await auth.postActivity({ event_type: 'page_visit', page: 'home', outcome: 'visited' }), false)
  assert.deepEqual(calls.map(c => c.url), ['/auth/logout'])
})

// touchSession compares against Date.now(), so these tests run on a clock they control.
const realNow = Date.now
let clock = 0
afterEach(() => { Date.now = realNow })
async function signedInAtNineOClock() {
  clock = Date.UTC(2026, 10, 1, 9, 0, 0)
  Date.now = () => clock
  arrange({ status: 200, body: { access_token: 'first-token' } }, { status: 200, body: traveler })
  await auth.signIn(traveler.email, 'correct-password')
}

test('touchSession makes no request until the last refresh is 10 minutes old', async () => {
  await signedInAtNineOClock()
  arrange()
  clock += 9 * 60_000
  assert.equal(await auth.touchSession(), true)
  assert.equal(calls.length, 0)
  assert.equal(auth.hasAccessToken(), true)
})

test('touchSession makes exactly one refresh once it is due, then waits another 10 minutes', async () => {
  await signedInAtNineOClock()
  arrange({ status: 200, body: { access_token: 'renewed-token' } })
  clock += 10 * 60_000
  assert.equal(await auth.touchSession(), true)
  assert.deepEqual(calls.map(c => c.url), ['/auth/refresh'])
  assert.equal(calls[0].method, 'POST')
  assert.equal(auth.hasAccessToken(), true)
  arrange()
  clock += 9 * 60_000
  assert.equal(await auth.touchSession(), true)
  assert.equal(calls.length, 0)
})

test('two simultaneous touchSession calls make only one refresh', async () => {
  await signedInAtNineOClock()
  arrange({ status: 200, body: { access_token: 'renewed-token' } })
  clock += 15 * 60_000
  const first = auth.touchSession()
  const second = auth.touchSession()
  assert.equal(first, second)
  assert.deepEqual(await Promise.all([first, second]), [true, true])
  assert.equal(calls.length, 1)
})

test('touchSession does not repeat a refresh that restoreSession is already making', async () => {
  await signedInAtNineOClock()
  arrange({ status: 200, body: { access_token: 'restored-token' } }, { status: 200, body: traveler })
  clock += 15 * 60_000
  const restoring = auth.restoreSession()
  const touching = auth.touchSession()
  assert.deepEqual(await restoring, traveler)
  assert.equal(await touching, true)
  assert.deepEqual(calls.map(c => c.url), ['/auth/refresh', '/auth/me'])
})

test('touchSession returns false, without throwing, when the server no longer accepts the session', async () => {
  await signedInAtNineOClock()
  arrange({ status: 401, body: {} })
  clock += 31 * 60_000
  assert.equal(await auth.touchSession(), false)
  assert.equal(calls.length, 1)
  assert.equal(auth.hasAccessToken(), false)
})

test('after signOut, touchSession asks the server again and reports an ended session as false', async () => {
  await signedInAtNineOClock()
  arrange({ status: 204 })
  await auth.signOut()
  arrange({ status: 401, body: {} })
  clock += 60_000  // Far less than 10 minutes: the old timestamp must not be trusted.
  assert.equal(await auth.touchSession(), false)
  assert.deepEqual(calls.map(c => c.url), ['/auth/refresh'])
})

test('after a failed logout, touchSession asks the server again instead of trusting the old timestamp', async () => {
  await signedInAtNineOClock()
  arrange({ status: 503, body: {} })
  await assert.rejects(auth.signOut(), /Could not log out/)
  arrange({ status: 200, body: { access_token: 'after-failed-logout' } })
  clock += 60_000
  assert.equal(await auth.touchSession(), true)
  assert.deepEqual(calls.map(c => c.url), ['/auth/refresh'])
})
