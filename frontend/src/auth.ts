import { submitPasswordReset } from './passwordReset.ts'

export type Traveler = { id: number; name: string; email: string }

// Access tokens live only in this module's memory. The browser manages the
// HttpOnly refresh cookie; no token is written to browser storage.
let accessToken: string | null = null
let restoring: Promise<Traveler | null> | null = null

export function hasAccessToken(): boolean { return accessToken !== null }

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

async function refresh(): Promise<boolean> {
  accessToken = null
  const response = await request('refresh', { method: 'POST' })
  if (response.status === 401) return false
  if (!response.ok) throw new Error('Could not restore your session. Please try again.')
  accessToken = (await response.json()).access_token
  return true
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
    if (!response.ok) throw new Error('Sign-in is temporarily unavailable. Please try again.')
    accessToken = (await response.json()).access_token
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
    if (!response.ok) throw new Error('Google sign-in is temporarily unavailable. Try again or use email sign-in.')
    accessToken = (await response.json()).access_token
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
