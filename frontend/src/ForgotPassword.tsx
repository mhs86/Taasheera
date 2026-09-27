import { useRef, useState } from 'react'
import { requestPasswordReset, ResetError } from './passwordReset'

function ForgotPassword() {
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [hasError, setHasError] = useState(false)
  const inProgress = useRef(false)

  return (
    <section className="sign-in-card" aria-labelledby="forgot-password-heading">
      <p className="eyebrow">YOUR JOURNEY STARTS HERE</p>
      <h1 id="forgot-password-heading">Forgot password?</h1>
      <p className="intro">Enter the email for your traveler account.</p>

      <form
        aria-busy={submitting}
        onSubmit={async (event) => {
          event.preventDefault()
          if (inProgress.current) return
          const form = event.currentTarget
          if (!form.reportValidity()) return
          const fields = new FormData(form)
          inProgress.current = true
          setSubmitting(true)
          setHasError(false)
          setMessage('')
          try {
            setMessage(await requestPasswordReset(String(fields.get('email') ?? '')))
          } catch (error) {
            setHasError(true)
            setMessage(error instanceof ResetError ? error.message : 'Could not request a reset email. Please try again.')
          } finally {
            inProgress.current = false
            setSubmitting(false)
          }
        }}
      >
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          disabled={submitting}
          maxLength={254}
          placeholder="you@example.com"
          onChange={() => setMessage('')}
          required
        />

        <button className="primary-button" type="submit" disabled={submitting}>
          {submitting ? 'Sending…' : 'Request password reset'}
        </button>
      </form>

      <p className={`auth-status${hasError ? ' auth-error' : ''}`} role={hasError ? 'alert' : 'status'}>{message}</p>

      <p className="create-account"><a href="#sign-in">Back to sign-in</a></p>
    </section>
  )
}

export default ForgotPassword
