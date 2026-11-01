import assert from 'node:assert/strict'
import { test } from 'node:test'

const {
  ACTIVITY_EVENTS, LOGOUT_AFTER_MS, REFRESH_AFTER_MS, WARN_AFTER_MS, idleState, refreshDue,
} = await import('../src/idleTimeout.ts')

const MINUTE = 60_000
const START = Date.UTC(2026, 10, 1, 9, 0, 0)

test('the limits are 28, 30 and 10 minutes, matching the server default of 30', () => {
  assert.equal(WARN_AFTER_MS, 28 * MINUTE)
  assert.equal(LOGOUT_AFTER_MS, 30 * MINUTE)
  assert.equal(REFRESH_AFTER_MS, 10 * MINUTE)
})

test('a traveler is active until 28 minutes of quiet', () => {
  assert.equal(idleState(START, START), 'active')
  assert.equal(idleState(START, START + 5 * MINUTE), 'active')
  assert.equal(idleState(START, START + 28 * MINUTE - 1), 'active')
})

test('the warning shows from 28 minutes until 30', () => {
  assert.equal(idleState(START, START + 28 * MINUTE), 'warn')
  assert.equal(idleState(START, START + 29 * MINUTE), 'warn')
  assert.equal(idleState(START, START + 30 * MINUTE - 1), 'warn')
})

test('the traveler is signed out at 30 minutes and after', () => {
  assert.equal(idleState(START, START + 30 * MINUTE), 'logout')
  assert.equal(idleState(START, START + 31 * MINUTE), 'logout')
})

test('a long clock jump, such as a laptop waking from sleep, signs out at once', () => {
  // No timer ticked while the lid was closed; only the clock shows the gap.
  assert.equal(idleState(START, START + 8 * 60 * MINUTE), 'logout')
  assert.equal(idleState(START, START + 3 * 24 * 60 * MINUTE), 'logout')
})

test('activity moves the clock, so the same moment is quiet or not depending on the last activity', () => {
  const now = START + 29 * MINUTE
  assert.equal(idleState(START, now), 'warn')
  assert.equal(idleState(now - MINUTE, now), 'active')
})

test('a clock set backwards does not sign anyone out', () => {
  assert.equal(idleState(START, START - 5 * MINUTE), 'active')
})

test('a quiet refresh is not due before 10 minutes and is due from then on', () => {
  assert.equal(refreshDue(START, START), false)
  assert.equal(refreshDue(START, START + 9 * MINUTE), false)
  assert.equal(refreshDue(START, START + 10 * MINUTE - 1), false)
  assert.equal(refreshDue(START, START + 10 * MINUTE), true)
  assert.equal(refreshDue(START, START + 25 * MINUTE), true)
})

test('only deliberate input counts as activity, never mousemove', () => {
  assert.deepEqual([...ACTIVITY_EVENTS].sort(), ['keydown', 'pointerdown', 'scroll', 'touchstart', 'wheel'])
  assert.ok(!ACTIVITY_EVENTS.includes('mousemove'))
  assert.ok(!ACTIVITY_EVENTS.includes('pointermove'))
})
