export type Traveler = { id: number; name: string; email: string }

// Access tokens live only in this module's memory. The browser manages the
// HttpOnly refresh cookie; no token is written to browser storage.
let accessToken: string | null = null
let restoring: Promise<Traveler | null> | null = null

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
  return response.json()
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

export function signOut(): Promise<void> {
  return sessionOperation(async () => {
    const response = await request('logout', { method: 'POST' })
    if (!response.ok) throw new Error('Could not log out. Please try again.')
    accessToken = null
  })
}
