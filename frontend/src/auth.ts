import { submitPasswordReset } from './passwordReset.ts'
import { apiFetch } from './api.ts'
import { refreshDue } from './idleTimeout.ts'

export type Traveler = { id: number; name: string; email: string; sso_email?: string | null
  auth_type?: 'email_password' | 'google'; password_enabled?: boolean; last_login_method?: string | null }

export type TravelerProfile = {
  surname: string | null
  given_names: string | null
  birth_date: string | null
  nationality: string | null
  phone: string | null
  address_line1: string | null
  address_line2: string | null
  address_city: string | null
  address_region: string | null
  address_postal_code: string | null
  address_country: string | null
}

export type ProfileField = keyof TravelerProfile

export type TravelerSession = {
  id: string
  device_label: string
  created_at: string | null
  last_active_at: string | null
  current: boolean
}

export async function getSessions(): Promise<TravelerSession[]> {
  const response = await protectedFetch('/sessions', { silent: true, cache: 'no-store' })
  if (!response.ok) throw new Error('Could not load your sessions. Please try again.')
  return response.json()
}

export async function endSession(id: string): Promise<void> {
  const response = await protectedFetch(`/sessions/${encodeURIComponent(id)}`, {
    method: 'DELETE', silent: true, cache: 'no-store',
  })
  if (response.status !== 204) throw new Error('Could not end this session. Please try again.')
}

export async function endOtherSessions(): Promise<number> {
  const response = await protectedFetch('/sessions/revoke-others', {
    method: 'POST', silent: true, cache: 'no-store',
  })
  if (!response.ok) throw new Error('Could not sign out other devices. Please try again.')
  const result = await response.json() as { ended: number }
  return result.ended
}

export class ProfileValidationError extends Error {
  readonly fields: Partial<Record<ProfileField, string>>

  constructor(message: string, fields: Partial<Record<ProfileField, string>>) {
    super(message)
    this.name = 'ProfileValidationError'
    this.fields = fields
  }
}

export async function getTravelerProfile(): Promise<TravelerProfile> {
  const response = await protectedFetch('/profile', { silent: true, cache: 'no-store' })
  if (!response.ok) throw new Error('Could not load your profile. Please try again.')
  return response.json()
}

export async function putTravelerProfile(fields: TravelerProfile): Promise<TravelerProfile> {
  const response = await protectedFetch('/profile', {
    method: 'PUT', silent: true, cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields),
  })
  if (response.status === 422) {
    const payload = await response.json().catch(() => ({}))
    const errors: Partial<Record<ProfileField, string>> = {}
    if (Array.isArray(payload.detail)) {
      for (const issue of payload.detail) {
        const field = issue.loc?.[1]
        if (typeof field === 'string' && field in fields && typeof issue.msg === 'string') {
          errors[field as ProfileField] = issue.msg.replace(/^Value error, /, '')
        }
      }
    }
    throw new ProfileValidationError('Please correct the highlighted fields.', errors)
  }
  if (!response.ok) throw new Error('Could not save your profile. Please try again.')
  return response.json()
}

let configurationRequest: Promise<string> | null = null

export function loadGoogleClientId(): Promise<string> {
  // Share StrictMode's simultaneous requests, but refresh on later route visits.
  if (!configurationRequest) configurationRequest = request('config').then(async response => {
    if (!response.ok) throw new Error('Google sign-in configuration could not load.')
    const config = await response.json()
    if (config.google_client_id === null) return ''
    if (typeof config.google_client_id !== 'string' ||
        !/^[A-Za-z0-9._-]+\.apps\.googleusercontent\.com$/.test(config.google_client_id)) {
      throw new Error('Google sign-in configuration could not load.')
    }
    return config.google_client_id
  }).finally(() => { configurationRequest = null })
  return configurationRequest
}

export async function connectGoogle(idToken: string, password: string, expectedTravelerId: number): Promise<Traveler> {
  const response = await protectedFetch('/auth/google/link', {
    method: 'POST', silent: true, cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id_token: idToken, password, expected_traveler_id: expectedTravelerId }),
  })
  if (response.status === 403) throw new Error('Check your current password and try again.')
  if (response.status === 409) {
    const detail = await response.json().catch(() => ({}))
    if (detail.detail?.code === 'account_changed') throw new Error('Your signed-in account changed. Reload before connecting Google.')
    throw new Error('That Google account is already connected to another account, or you have a different Google account connected.')
  }
  if (response.status === 401 || response.status === 422) throw new Error('Google sign-in could not be verified. Try again.')
  if (!response.ok) throw new Error('Could not connect Google. Please try again.')
  return response.json()
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const response = await protectedFetch('/auth/change-password', {
    method: 'POST', silent: true, cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  if (response.status === 204) return
  if (response.status === 403) throw new Error('Current password is incorrect.')
  if (response.status === 400) throw new Error('Choose a different new password.')
  if (response.status === 422) throw new Error('Use at least 8 characters and at most 72 UTF-8 bytes for your new password.')
  if (response.status === 429) throw new Error('Too many attempts. Please wait 15 minutes before trying again.')
  throw new Error('Could not change your password. Please try again.')
}

// Access tokens live only in this module's memory. The browser manages the
// HttpOnly refresh cookie; no token is written to browser storage.
let accessToken: string | null = null
let restoring: Promise<Traveler | null> | null = null

export function hasAccessToken(): boolean { return accessToken !== null }

// Options are apiFetch's, so a caller can pass `silent: true` and show its own error instead of a toast.
export async function protectedFetch(path: string, options: Parameters<typeof apiFetch>[1] = {}): Promise<Response> {
  if (!accessToken && !(await restoreSession())) throw new Error('Please sign in to continue.')
  const send = () => apiFetch(path, {
    ...options,
    headers: { ...Object.fromEntries(new Headers(options.headers)), Authorization: `Bearer ${accessToken}` },
  })
  let response = await send()
  if (response.status === 401) {
    const renewed = await sessionOperation(refresh)
    if (!renewed) throw new Error('Your session expired. Please sign in again.')
    response = await send()
  }
  return response
}

async function request(path: string, options: RequestInit = {}) {
  return fetch(`/auth/${path}`, {
    ...options,
    credentials: 'same-origin',
    cache: 'no-store',
    signal: AbortSignal.timeout(15000),
  })
}

// Rotation must be serialized across tabs as well as within this page.
function sessionOperation<T>(operation: () => Promise<T>): Promise<T> {
  return navigator.locks.request('taasheera-session', operation)
}

// When this page last got a fresh session from the server (sign-in or refresh), in ms.
let lastRefreshAt = 0
let touching: Promise<boolean> | null = null

async function refresh(): Promise<boolean> {
  accessToken = null
  const response = await request('refresh', { method: 'POST' })
  if (response.status === 401) return false
  if (!response.ok) throw new Error('Could not restore your session. Please try again.')
  accessToken = (await response.json()).access_token
  lastRefreshAt = Date.now()
  return true
}

// The server ends a session whose last refresh is too old, and an active traveler may trigger no
// API call. Called on real activity: refreshes quietly if the last refresh is old enough, else does
// nothing. True means the session is fine, false that the server no longer accepts it (401).
// It takes the same cross-tab lock as every other session change and checks again once it holds
// the lock, so a refresh or sign-in that finished while it waited is not repeated.
export function touchSession(): Promise<boolean> {
  const fresh = () => accessToken !== null && !refreshDue(lastRefreshAt, Date.now())
  if (fresh()) return Promise.resolve(true)
  touching ??= sessionOperation(async () => fresh() || refresh()).finally(() => { touching = null })
  return touching
}

const SUSPENDED = 'This account is suspended, so it cannot sign in.'

// Sign-in answers 403 to a disallowed origin too, so only the code identifies a suspension.
async function isSuspended(response: Response): Promise<boolean> {
  if (response.status !== 403) return false
  const payload = await response.json().catch(() => ({}))
  return payload?.detail?.code === 'account_suspended'
}

async function profile(): Promise<Traveler> {
  const response = await request('me', {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (!response.ok) {
    accessToken = null
    throw new Error('Could not load your traveler profile. Please sign in again.')
  }
  const traveler = await response.json()
  if (typeof window !== 'undefined') window.dispatchEvent(new window.Event('taasheera-auth-changed'))
  return traveler
}

export async function postActivity(event: { event_type: 'page_visit' | 'click'; page: string; control?: string; outcome: 'visited' | 'initiated' }): Promise<boolean> {
  if (!accessToken) return false
  try {
    const response = await fetch('/activity/events', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify(event), signal: AbortSignal.timeout(5000),
    })
    return response.status === 204
  } catch {
    // Activity collection must not interrupt the action the traveler selected.
    return false
  }
}

export function restoreSession(): Promise<Traveler | null> {
  // React StrictMode mounts effects twice; both callers share one rotation.
  if (!restoring) {
    restoring = sessionOperation(async () => (await refresh()) ? profile() : null)
      .finally(() => { restoring = null })
  }
  return restoring
}

export function signIn(email: string, password: string): Promise<Traveler> {
  return sessionOperation(async () => {
    accessToken = null
    const response = await request('login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim(), password }),
    })
    if (response.status === 401) throw new Error('Invalid email or password.')
    if (response.status === 422) throw new Error('Please check your email and password.')
    if (await isSuspended(response)) throw new Error(SUSPENDED)
    if (!response.ok) throw new Error('Sign-in is temporarily unavailable. Please try again.')
    accessToken = (await response.json()).access_token
    lastRefreshAt = Date.now()
    return profile()
  })
}

export function signInWithGoogle(idToken: string): Promise<Traveler> {
  return sessionOperation(async () => {
    accessToken = null
    let response: Response
    try {
      response = await request('google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_token: idToken }),
      })
    } catch {
      throw new Error('Could not complete Google sign-in. Check your connection and try again.')
    }
    if (response.status === 409) {
      throw new Error('This email already belongs to an account. Use your existing sign-in method. Accounts have not been linked.')
    }
    if (response.status === 401 || response.status === 422) {
      throw new Error('Google sign-in could not be verified. Please try again or use email sign-in.')
    }
    if (await isSuspended(response)) throw new Error(SUSPENDED)
    if (!response.ok) throw new Error('Google sign-in is temporarily unavailable. Try again or use email sign-in.')
    accessToken = (await response.json()).access_token
    lastRefreshAt = Date.now()
    return profile()
  })
}

export function signOut(): Promise<void> {
  return sessionOperation(async () => {
    const response = await request('logout', { method: 'POST' })
    if (!response.ok) throw new Error('Could not log out. Please try again.')
    accessToken = null
  })
}

export function resetPassword(token: string, password: string): Promise<void> {
  return sessionOperation(async () => {
    await submitPasswordReset(token, password)
    accessToken = null
  })
}
