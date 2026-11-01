import { dom } from './dom-setup.mjs'
import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { toast } from 'sonner'

for (const name of ['Node', 'Element', 'HTMLAnchorElement', 'MutationObserver', 'getComputedStyle']) {
  globalThis[name] ??= dom.window[name]
}
window.matchMedia ??= () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
window.scrollTo = () => {}
// sonner animates a dismissed toast away; this jsdom has no animation frames.
globalThis.requestAnimationFrame ??= callback => setTimeout(() => callback(Date.now()), 0)

const auth = await import('../src/auth.ts')
const { default: IdleGuard } = await import('../src/IdleGuard.tsx')
const { default: AuthRoute } = await import('../src/AuthRoute.tsx')

const MINUTE = 60_000
const START = Date.UTC(2026, 10, 1, 9, 0, 0)
const traveler = { id: 1, name: 'Maya Haddad', email: 'maya@example.com' }

// The guard compares timestamps, so the tests own the clock and the 15-second interval.
const realNow = Date.now
const realSetInterval = globalThis.setInterval
const realClearInterval = globalThis.clearInterval
let clock
let intervals
let nextInterval
let trail
let live
let restoreListeners
let root
let container

function takeOverTime() {
  clock = START
  Date.now = () => clock
  intervals = new Map()
  nextInterval = 0
  globalThis.setInterval = (fn, ms, ...args) => {
    if (ms !== 15_000) return realSetInterval(fn, ms, ...args)
    intervals.set(++nextInterval, fn)
    return nextInterval
  }
  globalThis.clearInterval = id => { if (!intervals.delete(id)) realClearInterval(id) }
}
const tick = () => act(async () => { for (const fn of [...intervals.values()]) fn() })
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
const at = minutes => { clock = START + minutes * MINUTE }

// Records which of the guard's listeners are attached to window and document right now.
const WATCHED = ['pointerdown', 'keydown', 'wheel', 'scroll', 'touchstart', 'visibilitychange', 'taasheera-auth-changed']
function watchListeners() {
  live = []
  const undo = []
  for (const target of [window, document]) {
    const add = target.addEventListener
    const remove = target.removeEventListener
    target.addEventListener = function (type, listener, options) {
      if (WATCHED.includes(type)) live.push({ target, type, listener })
      return add.call(this, type, listener, options)
    }
    target.removeEventListener = function (type, listener, options) {
      const index = live.findIndex(entry => entry.target === this && entry.type === type && entry.listener === listener)
      if (index >= 0) live.splice(index, 1)
      return remove.call(this, type, listener, options)
    }
    undo.push(() => { delete target.addEventListener; delete target.removeEventListener })
  }
  restoreListeners = () => undo.forEach(fn => fn())
}
const activityListeners = () => live.filter(entry => entry.type !== 'taasheera-auth-changed')

function arrangeFetch({ logout = 204, refresh = 200 } = {}) {
  globalThis.fetch = async (url) => {
    trail.push(`${url === '/auth/me' ? 'GET' : 'POST'} ${url}`)
    if (url === '/auth/login') return Response.json({ access_token: 'login-token' })
    if (url === '/auth/me') return Response.json(traveler)
    if (url === '/auth/refresh') {
      return refresh === 200 ? Response.json({ access_token: 'renewed-token' }) : new Response('{}', { status: refresh })
    }
    if (url === '/auth/logout') return new Response(null, { status: logout })
    if (url === '/auth/config') return Response.json({ google_client_id: null })
    assert.fail(`Unexpected request: ${url}`)
  }
}

async function signIn() {
  await act(async () => { await auth.signIn(traveler.email, 'correct-password') })
  trail.length = 0  // Only what the guard does is under test.
}

async function mount(props = {}) {
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  await act(async () => root.render(createElement(IdleGuard, {
    navigateAway: url => trail.push(`navigate ${url}`), ...props,
  })))
}

const dialog = () => container.querySelector('[role="alertdialog"]')
const press = (type = 'keydown') => act(async () => {
  window.dispatchEvent(new window.KeyboardEvent(type, { key: 'a', bubbles: true }))
})

afterEach(async () => {
  if (root) await act(async () => root.unmount())
  container?.remove()
  document.querySelectorAll('input').forEach(input => input.remove())
  root = null
  container = null
  // Leave the session module signed out for the next test.
  Date.now = realNow
  globalThis.setInterval = realSetInterval
  globalThis.clearInterval = realClearInterval
  restoreListeners?.()
  restoreListeners = null
  delete document.visibilityState
  trail = []
  arrangeFetch()
  await act(async () => { await auth.signOut() })
  dom.reconfigure({ url: 'http://127.0.0.1:5173/' })
})

function begin() {
  trail = []
  takeOverTime()
  watchListeners()
  arrangeFetch()
}

test('signed out, the guard renders nothing and listens for no activity', async () => {
  begin()
  await mount()
  assert.equal(container.innerHTML, '')
  assert.deepEqual(activityListeners(), [])
  assert.equal(intervals.size, 0)
  // Only the sign-in announcement is watched, so the guard can start when someone signs in.
  assert.deepEqual(live.map(entry => entry.type), ['taasheera-auth-changed'])
})

test('the guard starts watching when a traveler signs in and stops when they sign out', async () => {
  begin()
  await mount()
  await signIn()
  assert.deepEqual(activityListeners().map(entry => entry.type).sort(),
    ['keydown', 'pointerdown', 'scroll', 'touchstart', 'visibilitychange', 'wheel'])
  assert.equal(intervals.size, 1)
  arrangeFetch()
  await act(async () => { await auth.signOut() })
  assert.deepEqual(activityListeners(), [])
  assert.equal(intervals.size, 0)
})

test('no warning at 27 minutes; an alertdialog at 28', async () => {
  begin()
  await signIn()
  await mount()
  at(27)
  await tick()
  assert.equal(dialog(), null)

  at(28)
  await tick()
  const box = dialog()
  assert.ok(box)
  assert.equal(box.getAttribute('aria-modal'), null)
  assert.match(container.querySelector(`#${box.getAttribute('aria-labelledby')}`).textContent, /You'll be signed out in 2 minutes/)
  assert.ok(container.querySelector(`#${box.getAttribute('aria-describedby')}`).textContent.length > 0)
  assert.equal(box.querySelector('button').textContent, 'Stay signed in')
  assert.equal(box.querySelector('[autofocus], [tabindex]'), null)
})

test('the warning does not take focus from the field being typed in', async () => {
  begin()
  await signIn()
  await mount()
  const field = document.createElement('input')
  document.body.append(field)
  field.focus()
  assert.equal(document.activeElement, field)
  at(28)
  await tick()
  assert.ok(dialog())
  assert.equal(document.activeElement, field)
})

test('keydown dismisses the warning and refreshes quietly; mousemove does not', async () => {
  begin()
  await signIn()
  await mount()
  at(28)
  await tick()
  assert.ok(dialog())

  await act(async () => { window.dispatchEvent(new window.MouseEvent('mousemove', { bubbles: true })) })
  await settle()
  assert.ok(dialog(), 'a moved mouse is not activity')
  assert.deepEqual(trail, [])

  await press('keydown')
  await settle()
  assert.equal(dialog(), null)
  assert.deepEqual(trail, ['POST /auth/refresh'])  // Last refresh was 28 minutes ago, so one is due.

  at(29)  // One minute after the keystroke, not 29 minutes of quiet.
  await tick()
  assert.equal(dialog(), null)
})

test('Stay signed in resets the clock and refreshes the session', async () => {
  begin()
  await signIn()
  await mount()
  at(28)
  await tick()
  await act(async () => { dialog().querySelector('button').click() })
  await settle()
  assert.equal(dialog(), null)
  assert.deepEqual(trail, ['POST /auth/refresh'])

  at(29.5)  // 90 seconds after pressing the button.
  await tick()
  assert.equal(dialog(), null)
  assert.deepEqual(trail, ['POST /auth/refresh'])
})

test('at 30 minutes the guard signs out on the server and goes to the sign-in page', async () => {
  begin()
  await signIn()
  await mount()
  at(30)
  await tick()
  await settle()
  assert.deepEqual(trail, ['POST /auth/logout', 'navigate /sign-in?notice=idle'])
})

test('a long sleep is caught as soon as the tab is visible again, without waiting for a tick', async () => {
  begin()
  await signIn()
  await mount()
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
  clock = START + 8 * 60 * MINUTE  // The lid was closed; no interval ran.
  await act(async () => { document.dispatchEvent(new window.Event('visibilitychange')) })
  await settle()
  assert.deepEqual(trail, ['POST /auth/logout', 'navigate /sign-in?notice=idle'])
})

test('a failed logout request still navigates away', async () => {
  begin()
  await signIn()
  await mount()
  arrangeFetch({ logout: 503 })
  at(30)
  await tick()
  await settle()
  assert.deepEqual(trail, ['POST /auth/logout', 'navigate /sign-in?notice=idle'])
})

test('activity after 30 minutes signs out instead of rescuing the session', async () => {
  begin()
  await signIn()
  await mount()
  at(31)
  await press('keydown')
  await settle()
  assert.deepEqual(trail, ['POST /auth/logout', 'navigate /sign-in?notice=idle'])
})

test('a refresh the server refuses signs the traveler out', async () => {
  begin()
  await signIn()
  await mount()
  arrangeFetch({ refresh: 401 })
  at(5)
  await press('keydown')
  await settle()
  assert.deepEqual(trail, ['POST /auth/refresh', 'POST /auth/logout', 'navigate /sign-in?notice=idle'])
})

test('unmounting leaves no listeners and no interval behind', async () => {
  begin()
  await signIn()
  await mount()
  assert.ok(live.length > 0)
  assert.equal(intervals.size, 1)
  await act(async () => root.unmount())
  root = null
  assert.deepEqual(live, [])
  assert.equal(intervals.size, 0)
})

async function renderSignInRoute() {
  container = document.createElement('div')
  document.body.append(container)
  const router = createMemoryRouter([{
    path: '/sign-in', loader: () => ({ page: 'sign-in', resetToken: null }), element: createElement(AuthRoute),
  }], { initialEntries: ['/sign-in'] })
  root = createRoot(container)
  await act(async () => root.render(createElement(RouterProvider, { router })))
  await settle()
}
const toasts = () => document.body.querySelectorAll('[data-sonner-toast]')

test('the sign-in page shows the idle notice once and removes it from the address', async () => {
  begin()
  arrangeFetch({ refresh: 401 })
  dom.reconfigure({ url: 'http://127.0.0.1:5173/sign-in?notice=idle#sign-in' })
  await renderSignInRoute()
  assert.equal(toasts().length, 1)
  assert.match(toasts()[0].textContent, /You were signed out after 30 minutes of inactivity\./)
  assert.equal(window.location.search, '')
  assert.equal(window.location.pathname, '/sign-in')
  assert.equal(window.location.hash, '#sign-in')

  // sonner keeps toasts in a module-level store that outlives the Toaster; clear it for the next test.
  toast.dismiss()
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 100)) })
})

test('the sign-in page shows no notice for other addresses', async () => {
  begin()
  arrangeFetch({ refresh: 401 })
  dom.reconfigure({ url: 'http://127.0.0.1:5173/sign-in?notice=something-else' })
  await renderSignInRoute()
  assert.equal(toasts().length, 0)
  assert.equal(window.location.search, '?notice=something-else')
})
