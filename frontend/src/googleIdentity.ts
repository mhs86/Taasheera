export type GoogleCredential = { credential?: string; state?: string }
export type GoogleIdentity = {
  initialize(options: { client_id: string; callback: (response: GoogleCredential) => void; ux_mode: 'popup'; auto_select: false }): void
  renderButton(element: HTMLElement, options: {
    type: 'standard'; theme: 'outline'; size: 'large'; text: 'signin_with'; width: number
    state: string; click_listener: () => void
  }): void
  disableAutoSelect(): void
}

declare global {
  interface Window { google?: { accounts: { id: GoogleIdentity } } }
}

const SCRIPT_URL = 'https://accounts.google.com/gsi/client'
let loading: Promise<GoogleIdentity> | null = null
let initialized: { api: GoogleIdentity; clientId: string } | null = null
let active: { state: string; receive: (response: GoogleCredential) => void } | null = null
let buttonSequence = 0

export function loadGoogleIdentity(): Promise<GoogleIdentity> {
  if (window.google?.accounts.id) return Promise.resolve(window.google.accounts.id)
  if (loading) return loading
  loading = new Promise<GoogleIdentity>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = SCRIPT_URL
    script.async = true
    script.defer = true
    const finish = (failed: boolean) => {
      clearTimeout(timeout)
      script.onload = null
      script.onerror = null
      const api = window.google?.accounts.id
      if (failed || !api) {
        script.remove()
        reject(new Error('Google sign-in could not load. Retry or use email sign-in.'))
      } else resolve(api)
    }
    const timeout = setTimeout(() => finish(true), 15000)
    script.onload = () => finish(false)
    script.onerror = () => finish(true)
    document.head.appendChild(script)
  }).catch(error => {
    loading = null
    throw error
  })
  return loading
}

export function renderGoogleButton(api: GoogleIdentity, clientId: string, element: HTMLElement,
  receive: (response: GoogleCredential) => void, clicked: () => void): () => void {
  if (!initialized || initialized.api !== api || initialized.clientId !== clientId) {
    api.initialize({
      client_id: clientId, ux_mode: 'popup', auto_select: false,
      callback: response => {
        if (active && response.state === active.state) active.receive(response)
      },
    })
    initialized = { api, clientId }
  }
  const state = `taasheera-google-${++buttonSequence}`
  active = { state, receive }
  const render = () => {
    element.replaceChildren()
    api.renderButton(element, {
      type: 'standard', theme: 'outline', size: 'large', text: 'signin_with',
      width: Math.min(400, Math.max(180, Math.floor(element.getBoundingClientRect().width || 240))),
      state, click_listener: clicked,
    })
  }
  try { render() } catch (error) {
    if (active?.state === state) active = null
    throw error
  }
  let width = element.getBoundingClientRect().width
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
    const next = element.getBoundingClientRect().width
    if (Math.abs(next - width) >= 1) { width = next; render() }
  })
  observer?.observe(element)
  return () => {
    observer?.disconnect()
    if (active?.state === state) active = null
    element.replaceChildren()
  }
}

export function disableGoogleAutoSelect() {
  // Logout must still succeed if the external SDK is unavailable or blocked.
  try { window.google?.accounts.id.disableAutoSelect() } catch { /* No credentials are logged. */ }
}
