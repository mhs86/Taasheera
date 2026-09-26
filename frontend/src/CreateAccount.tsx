import { useRef, useState } from 'react'

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

function CreateAccount() {
  const [message, setMessage] = useState('')
  const [hasError, setHasError] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const requestInProgress = useRef(false)
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmPasswordRef = useRef<HTMLInputElement>(null)

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
              setMessage('Your traveler account has been created. Sign-in is not available yet.')
            } else {
              setHasError(true)
              if (response.status === 409) {
                setMessage('This email is already registered. Use a different email address. Sign-in is not available yet.')
              } else if (response.status === 422) {
                const body: unknown = await response.json().catch(() => null)
                setMessage(validationMessage(body))
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
        <input
          ref={passwordRef}
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          disabled={isSubmitting}
          minLength={8}
          aria-describedby="password-help"
          onChange={validatePasswords}
          required
        />

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
        <button className="primary-button" type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Creating account…' : 'Create account'}
        </button>
      </form>

      <p className="create-account">
        Already have an account? <a href="#sign-in">Sign in</a>
      </p>

      <p className={`auth-status${hasError ? ' auth-error' : ''}`} role="status">{message}</p>
    </section>
  )
}

export default CreateAccount
