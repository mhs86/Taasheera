import assert from 'node:assert/strict'
import { test } from 'node:test'
import './dom-setup.mjs'
const { safePage } = await import('../src/activityPage.ts')

test('page identifiers never include reset tokens, arbitrary paths, or fragments', () => {
  assert.equal(safePage('/', '#privacy'), 'home')
  assert.equal(safePage('/faq', ''), 'faq')
  assert.equal(safePage('/sign-in', '#create-account'), 'create-account')
  assert.equal(safePage('/sign-in', '#forgot-password'), 'forgot-password')
  assert.equal(safePage('/sign-in', '#token=private-reset-token'), 'reset-password')
  assert.equal(safePage('/reset-password', '#token=private-reset-token'), 'reset-password')
  assert.equal(safePage('/private/passport-123', ''), 'not-found')
})
