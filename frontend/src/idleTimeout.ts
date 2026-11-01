// These must match the server: LOGOUT_AFTER_MS is the default AUTH_IDLE_TIMEOUT_SECONDS (1800 s)
// in backend/app/config.py. The server ends a session whose last refresh is older than that, so
// the warning and the sign-out here have to happen before it does. Change them together.
export const WARN_AFTER_MS = 28 * 60_000
export const LOGOUT_AFTER_MS = 30 * 60_000
export const REFRESH_AFTER_MS = 10 * 60_000

export type IdleState = 'active' | 'warn' | 'logout'

// Only genuine input counts. mousemove is left out so a bumped mouse does not keep a session open.
export const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'scroll', 'touchstart'] as const

// Compares timestamps instead of counting timer ticks: background tabs throttle timers and a
// sleeping laptop stops them, but the clock still shows how long the traveler has been away.
export function idleState(lastActivity: number, now: number): IdleState {
  const quiet = now - lastActivity
  if (quiet >= LOGOUT_AFTER_MS) return 'logout'
  if (quiet >= WARN_AFTER_MS) return 'warn'
  return 'active'
}

// A traveler who is active but triggers no API call would otherwise let the server's idle clock,
// which only moves on refresh, run out. Refreshing quietly every 10 minutes keeps the two in step.
export function refreshDue(lastRefresh: number, now: number): boolean {
  return now - lastRefresh >= REFRESH_AFTER_MS
}
