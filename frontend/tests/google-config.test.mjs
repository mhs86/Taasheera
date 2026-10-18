import './dom-setup.mjs'
import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { loadGoogleClientId } from '../src/auth.ts'

const original = globalThis.fetch
afterEach(() => { globalThis.fetch = original })

test('Google client ID comes from uncached AWS backend configuration and StrictMode shares the request', async () => {
  let resolve, calls = 0
  globalThis.fetch = async (url, options) => {
    calls++
    assert.equal(url, '/auth/config')
    assert.equal(options.credentials, 'same-origin')
    assert.equal(options.cache, 'no-store')
    return new Promise(done => { resolve = done })
  }
  const first = loadGoogleClientId(), second = loadGoogleClientId()
  assert.equal(calls, 1)
  resolve(new Response(JSON.stringify({ google_client_id: 'aws-runtime.apps.googleusercontent.com' }), { status: 200 }))
  assert.deepEqual(await Promise.all([first, second]), ['aws-runtime.apps.googleusercontent.com', 'aws-runtime.apps.googleusercontent.com'])
})

test('disabled Google configuration does not enable a stale compiled client ID', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ google_client_id: null }), { status: 200 })
  assert.equal(await loadGoogleClientId(), '')
})

test('configuration failure is retryable and malformed IDs are rejected', async () => {
  globalThis.fetch = async () => new Response('{}', { status: 503 })
  await assert.rejects(loadGoogleClientId(), /could not load/)
  globalThis.fetch = async () => new Response(JSON.stringify({ google_client_id: 'untrusted-config' }), { status: 200 })
  await assert.rejects(loadGoogleClientId(), /could not load/)
  globalThis.fetch = async () => new Response(JSON.stringify({ google_client_id: 'correct.apps.googleusercontent.com' }), { status: 200 })
  assert.equal(await loadGoogleClientId(), 'correct.apps.googleusercontent.com')
})
