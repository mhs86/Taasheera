import './dom-setup.mjs'
import assert from 'node:assert/strict'
import { test } from 'node:test'
const { loadGoogleIdentity } = await import('../src/googleIdentity.ts')

test('SDK loader deduplicates, handles script failure and missing API, then retries successfully', async () => {
  delete window.google
  const first = loadGoogleIdentity()
  assert.equal(loadGoogleIdentity(), first)
  const script = document.querySelector('script')
  assert.equal(script.src, 'https://accounts.google.com/gsi/client')
  assert.equal(script.async, true)
  const failure = assert.rejects(first, /could not load/)
  script.dispatchEvent(new window.Event('error'))
  await failure
  assert.equal(document.querySelector('script'), null)
  const missing = loadGoogleIdentity()
  const missingFailure = assert.rejects(missing, /could not load/)
  document.querySelector('script').dispatchEvent(new window.Event('load'))
  await missingFailure
  const retry = loadGoogleIdentity()
  const api = {}
  window.google = { accounts: { id: api } }
  document.querySelector('script').dispatchEvent(new window.Event('load'))
  assert.equal(await retry, api)
  assert.equal(await loadGoogleIdentity(), api)
  assert.equal(document.querySelectorAll('script').length, 1)
})
