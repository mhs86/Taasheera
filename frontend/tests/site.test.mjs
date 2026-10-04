import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
import { afterEach, test } from 'node:test'
import { dom } from './dom-setup.mjs'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'

// Vite turns image imports into URLs; the shared test loader only stubs CSS.
registerHooks({
  load(url, context, nextLoad) {
    if (url.endsWith('.svg')) return { format: 'module', source: `export default ${JSON.stringify(url)}`, shortCircuit: true }
    return nextLoad(url, context)
  },
})

// Render the real route table in jsdom, plus one page that crashes on purpose.
const { routes } = await import('../src/routes.tsx')
const { apiFetch } = await import('../src/api.ts')
function Crash() { throw new Error('boom') }
routes[0].children[0].children.unshift({ path: 'crash', element: createElement(Crash) })

for (const name of ['Node', 'Element', 'HTMLAnchorElement', 'MutationObserver', 'getComputedStyle']) {
  globalThis[name] ??= dom.window[name]
}
window.matchMedia ??= () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
window.scrollTo = () => {}

let root
let container
async function render(path) {
  container = document.createElement('div')
  document.body.append(container)
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  root = createRoot(container)
  await act(async () => root.render(createElement(RouterProvider, { router })))
  return router
}
const settle = () => act(() => new Promise(resolve => setTimeout(resolve, 20)))

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

test('homepage explains the service and links every call to action to sign-up', async () => {
  await render('/')
  assert.match(container.querySelector('h1').textContent, /Prepare your visa application with AI/)
  for (const id of ['how-it-works', 'documents', 'destinations', 'privacy']) {
    assert.ok(container.querySelector(`#${id}`), `missing #${id}`)
  }
  const ctas = [...container.querySelectorAll('a')].filter(a => a.textContent.trim() === 'Get started')
  assert.equal(ctas.length, 3)
  for (const cta of ctas) assert.equal(cta.getAttribute('href'), '/sign-in#create-account')
  assert.equal(document.title, 'Taasheera | Your AI visa agent')
})

test('Get started opens the merged account page through the site router', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 401 }))
  window.history.replaceState(null, '', '/sign-in#create-account')
  await render('/sign-in#create-account')
  await settle()
  assert.equal(container.querySelector('h1')?.textContent, 'Create account')
  assert.equal(container.querySelector('form input[name="email"]')?.type, 'email')
  window.history.replaceState(null, '', '/')
})

test('mobile menu opens with every nav link and closes on a link or Escape', async () => {
  await render('/')
  const button = container.querySelector('.menu-button')
  const click = el => act(async () => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, button: 0 })))
  assert.equal(button.getAttribute('aria-expanded'), 'false')
  assert.equal(container.querySelector('#mobile-menu'), null)

  await click(button)
  assert.equal(button.getAttribute('aria-expanded'), 'true')
  const labels = [...container.querySelectorAll('#mobile-menu a')].map(a => a.textContent.trim())
  assert.deepEqual(labels, ['How it works', 'Destinations', 'Privacy', 'FAQ', 'Log in', 'Get started'])

  await click(container.querySelector('#mobile-menu a[href="/faq"]'))
  assert.equal(container.querySelector('#mobile-menu'), null)
  assert.equal(container.querySelector('h1').textContent, 'Frequently asked questions')

  await click(button)
  await act(async () => button.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  assert.equal(container.querySelector('#mobile-menu'), null)
})

test('homepage shows no pricing or payment content', async () => {
  await render('/')
  assert.doesNotMatch(container.textContent, /pric|payment|subscri|\$|€\d|EGP/i)
})

test('FAQ page lists every question in an accordion', async () => {
  await render('/faq')
  const items = container.querySelectorAll('details.faq-item')
  assert.equal(items.length, 10)
  for (const item of items) {
    assert.ok(item.querySelector('summary').textContent.trim())
    assert.equal(item.open, false)
  }
  assert.equal(document.title, 'FAQ | Taasheera')
})

test('unknown routes show the 404 page inside the site layout', async () => {
  await render('/no/such/page')
  assert.equal(container.querySelector('h1').textContent, 'Page not found')
  assert.ok(container.querySelector('.navbar'))
  assert.equal(document.title, 'Page not found | Taasheera')
})

test('passport page asks signed-out travelers to sign in', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 401 }))
  await render('/passport')
  await settle()
  assert.match(container.querySelector('h1').textContent, /Upload and review your passport/)
  assert.equal(container.querySelector('.passport-page a[href="/sign-in"]')?.textContent, 'sign in')
  assert.equal(container.querySelector('input[type="file"]'), null)
})

test('a crashing page shows the 500 page instead of a blank screen', async (t) => {
  t.mock.method(console, 'error', () => {})
  await render('/crash')
  assert.equal(container.querySelector('h1').textContent, 'Something went wrong')
  assert.ok(container.querySelector('.navbar'), 'layout should survive a page crash')
  assert.ok([...container.querySelectorAll('button')].some(b => b.textContent === 'Reload page'))
})

test('failed API calls raise a toast; client errors and silent calls do not', async (t) => {
  await render('/')
  const toasts = () => document.body.querySelectorAll('[data-sonner-toast]')

  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(apiFetch('/auth/me'), { name: 'ApiError', status: null })
  await settle()
  assert.match(toasts()[0]?.textContent ?? '', /could not reach Taasheera/)

  t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 503 }))
  await assert.rejects(apiFetch('/auth/me'), { status: 503 })
  await settle()
  // One shared id, so repeated failures replace the toast instead of stacking.
  assert.equal(toasts().length, 1)
  assert.match(toasts()[0].textContent, /went wrong on our side/)

  t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 401 }))
  assert.equal((await apiFetch('/auth/me')).status, 401)

  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    assert.equal(options.credentials, 'same-origin')
    return new Response(null, { status: 500 })
  })
  await assert.rejects(apiFetch('/auth/me', { silent: true }), { status: 500 })
})
