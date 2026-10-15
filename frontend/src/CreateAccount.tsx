import { useCallback, useEffect, useRef, useState } from 'react'
import GoogleSignIn from './GoogleSignIn'
import { signInWithGoogle, type Traveler } from './auth'

function validationMessage(body: unknown): string {
  const fallback = 'Please check your name, email, and password and try again.'
  if (!body || typeof body !== 'object' || !('detail' in body) || !Array.isArray(body.detail)) {
    return fallback
  }

  // Use our own messages, never submitted values from an error response.
  const messages = body.detail.map((issue: unknown) => {
    if (!issue || typeof issue !== 'object' || !('loc' in issue) || !Array.isArray(issue.loc)) return fallback
    switch (issue.loc[1]) {
      case 'name': return 'Name must contain 1–100 characters, not just spaces.'
      case 'email': return 'Enter a valid email address (at most 254 characters).'
      case 'password': return 'Password must contain at least 8 characters and at most 72 UTF-8 bytes.'
      default: return fallback
    }
  })
  return [...new Set(messages)].join(' ') || fallback
}

function CreateAccount({ onCreated, googleClientId = '', googleConfigurationStatus = 'ready',
  onGoogleConfigurationRetry, onSignedIn }: { onCreated: () => void; googleClientId?: string
  googleConfigurationStatus?: 'loading' | 'ready' | 'failed'; onGoogleConfigurationRetry?: () => void
  onSignedIn?: (traveler: Traveler) => void }) {
  const [message, setMessage] = useState('')
  const [hasError, setHasError] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const requestInProgress = useRef(false)
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmPasswordRef = useRef<HTMLInputElement>(null)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  const googleCredential = useCallback(async (credential: string) => {
    if (requestInProgress.current || !mounted.current) return
    requestInProgress.current = true
    setIsSubmitting(true)
    try {
      const profile = await signInWithGoogle(credential)
      if (mounted.current) onSignedIn?.(profile)
    } catch (error) {
      if (mounted.current) {
        setHasError(true)
        setMessage(error instanceof Error ? error.message : 'Could not continue with Google.')
      }
    } finally {
      requestInProgress.current = false
      if (mounted.current) setIsSubmitting(false)
    }
  }, [onSignedIn])

  // Use browser validation without keeping passwords in React state.
  function validatePasswords() {
    const password = passwordRef.current
    const confirmation = confirmPasswordRef.current
    if (!password || !confirmation) return

    confirmation.setCustomValidity(
      confirmation.value && confirmation.value !== password.value
        ? 'Passwords must match.'
        : '',
    )
    setMessage('')
  }

  return (
    <section className="sign-in-card" aria-labelledby="create-account-heading">
      <p className="eyebrow">YOUR JOURNEY STARTS HERE</p>
      <h1 id="create-account-heading">Create account</h1>
      <p className="intro">Start your journey with a traveler account.</p>

      <form
        aria-busy={isSubmitting}
        onSubmit={async (event) => {
          event.preventDefault()
          if (requestInProgress.current) return
          const form = event.currentTarget
          // Recheck in case a password manager filled either password field.
          validatePasswords()
          if (!form.reportValidity()) return

          const fields = new FormData(form)
          requestInProgress.current = true
          setIsSubmitting(true)
          setHasError(false)
          setMessage('')

          try {
            const response = await fetch('/auth/register', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                name: String(fields.get('name') ?? '').trim(),
                email: String(fields.get('email') ?? '').trim(),
                password: String(fields.get('password') ?? ''),
              }),
              signal: AbortSignal.timeout(15000),
            })

            if (response.status === 201) {
              form.reset()
              onCreated()
            } else {
              setHasError(true)
              if (response.status === 409) {
                setMessage('This email is already registered. Sign in or use a different email address.')
              } else if (response.status === 422) {
                const body: unknown = await response.json().catch(() => null)
                setMessage(validationMessage(body))
              } else if (response.status === 429) {
                setMessage('Too many registration attempts. Please wait 15 minutes before trying again.')
              } else {
                setMessage('Registration is temporarily unavailable. Check that the backend is running and try again.')
              }
            }
          } catch {
            setHasError(true)
            setMessage('Could not confirm registration. Check your connection and that the backend is running, then try again. If your email is already registered on retry, the earlier request may have succeeded.')
          } finally {
            // Do not retain passwords after a request, including failed requests.
            if (passwordRef.current) passwordRef.current.value = ''
            if (confirmPasswordRef.current) {
              confirmPasswordRef.current.value = ''
              confirmPasswordRef.current.setCustomValidity('')
            }
            requestInProgress.current = false
            setIsSubmitting(false)
          }
        }}
      >
        <label htmlFor="name">Name</label>
        <input
          id="name"
          name="name"
          type="text"
          autoComplete="name"
          disabled={isSubmitting}
          maxLength={100}
          pattern=".*\S.*"
          title="Enter your name, not just spaces."
          required
        />

        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          disabled={isSubmitting}
          maxLength={254}
          placeholder="you@example.com"
          required
        />

        <label htmlFor="password">Password</label>
        <div className="create-password-field">
          <input
            ref={passwordRef}
            id="password"
            name="password"
            type={showPassword ? 'text' : 'password'}
            autoComplete="new-password"
            disabled={isSubmitting}
            minLength={8}
            aria-describedby="password-help"
            onChange={validatePasswords}
            required
          />
          <button
            type="button"
            className="create-password-toggle"
            data-activity-id="password-toggle"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
            aria-pressed={showPassword}
            disabled={isSubmitting}
            onClick={() => setShowPassword(value => !value)}
          >
            <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
              <circle cx="12" cy="12" r="3" />
              {showPassword && <path d="M3 21 21 3" />}
            </svg>
          </button>
        </div>

        <label htmlFor="confirm-password">Confirm password</label>
        <input
          ref={confirmPasswordRef}
          id="confirm-password"
          name="confirmPassword"
          type="password"
          autoComplete="new-password"
          disabled={isSubmitting}
          onChange={validatePasswords}
          required
        />

        <p className="password-help" id="password-help">
          Use at least 8 characters and at most 72 UTF-8 bytes. Some characters use more than one byte.
        </p>
        <button className="primary-button" data-activity-id="submit-registration" type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Creating account…' : 'Create account'}
        </button>
      </form>

      {onSignedIn && <>
        <div className="divider"><span>or</span></div>
        <GoogleSignIn clientId={googleClientId} disabled={isSubmitting}
          configurationStatus={googleConfigurationStatus} onConfigurationRetry={onGoogleConfigurationRetry}
          onMessage={setMessage} onCredential={googleCredential} />
      </>}

      <p className="create-account">
        Already have an account? <a href="#sign-in" data-activity-id="sign-in-link">Sign in</a>
      </p>

      <p className={`auth-status${hasError ? ' auth-error' : ''}`} role="status">{message}</p>
    </section>
  )
}

export default CreateAccount
