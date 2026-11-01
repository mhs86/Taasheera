import { captureMessage, init } from '@sentry/browser'

// A strict allowlist keeps passport data, URLs, tokens and form inputs out of Sentry.
export function scrubBrowserEvent(event: Record<string, unknown>) {
  return { ...(typeof event.event_id === 'string' ? { event_id: event.event_id } : {}),
    type: undefined, platform: 'javascript', level: 'error' as const, message: 'Taasheera page error',
    tags: { component: 'frontend' } }
}

export function configureBrowserMonitoring() {
  const dsn = import.meta.env?.VITE_SENTRY_DSN?.trim()
  if (!dsn) return
  init({ dsn, sendDefaultPii: false, defaultIntegrations: false,
    beforeSend: event => scrubBrowserEvent(event as unknown as Record<string, unknown>) })
  window.addEventListener('error', reportPageError)
  window.addEventListener('unhandledrejection', reportPageError)
}

export function reportPageError() {
  if (import.meta.env?.VITE_SENTRY_DSN) captureMessage('Taasheera page error', 'error')
}
