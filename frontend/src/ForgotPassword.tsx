import { useEffect, useRef, useState } from 'react'
import { requestPasswordReset, ResetError, verifyResetCode } from './passwordReset'
import SetNewPassword from './SetNewPassword'

function ForgotPassword() {
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [hasError, setHasError] = useState(false)
  const inProgress = useRef(false)
  const mounted = useRef(false)
  const [requestedEmail, setRequestedEmail] = useState('')
  const [resetToken, setResetToken] = useState<string | null>(null)
  const [codeMessage, setCodeMessage] = useState('')
  const [verifying, setVerifying] = useState(false)
  const verifyingRef = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  if (resetToken) return <SetNewPassword token={resetToken}
    onTokenCleared={() => { setResetToken(null); setRequestedEmail('') }}
    onSuccess={() => { /* SetNewPassword retains its success view and clears auth state. */ }} />

  return (
    <section className="sign-in-card" aria-labelledby="forgot-password-heading">
      <p className="eyebrow">YOUR JOURNEY STARTS HERE</p>
      <h1 id="forgot-password-heading">Forgot password?</h1>
      <p className="intro">Enter your email/password account email to receive a six-digit reset code. Google-only users recover access through Google.</p>

      <form
        aria-busy={submitting}
        onSubmit={async (event) => {
          event.preventDefault()
          if (inProgress.current || verifyingRef.current) return
          const form = event.currentTarget
          if (!form.reportValidity()) return
          const fields = new FormData(form)
          inProgress.current = true
          setSubmitting(true)
          setHasError(false)
          setMessage('')
          try {
            const email = String(fields.get('email') ?? '').trim().toLowerCase()
            const confirmation = await requestPasswordReset(email)
            if (mounted.current) {
              setMessage(confirmation)
              setRequestedEmail(email)
              setCodeMessage('')
            }
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

        <button className="primary-button" data-activity-id="reset-request" type="submit" disabled={submitting}>
          {submitting ? 'Sending…' : requestedEmail ? 'Resend reset code' : 'Request password reset'}
        </button>
      </form>

      <p className={`auth-status${hasError ? ' auth-error' : ''}`} role={hasError ? 'alert' : 'status'}>{message}</p>

      {requestedEmail && <form aria-label="Verify reset code" aria-busy={verifying}
        onSubmit={async event => {
          event.preventDefault()
          if (verifyingRef.current || inProgress.current) return
          const form = event.currentTarget
          if (!form.reportValidity()) return
          const code = String(new FormData(form).get('code') ?? '')
          verifyingRef.current = true
          setVerifying(true)
          setCodeMessage('')
          try {
            const token = await verifyResetCode(requestedEmail, code)
            if (mounted.current) setResetToken(token)
          } catch (error) {
            if (mounted.current) setCodeMessage(error instanceof ResetError ? error.message : 'Could not verify the code.')
          } finally {
            form.reset()
            verifyingRef.current = false
            if (mounted.current) setVerifying(false)
          }
        }}>
        <label htmlFor="reset-code">Code from your email</label>
        <input id="reset-code" name="code" type="text" inputMode="numeric"
          autoComplete="one-time-code" pattern="[0-9]{6}" minLength={6} maxLength={6}
          disabled={verifying || submitting} required />
        <p className="password-help">The code expires in 10 minutes. After five incorrect attempts, request a new code. Wait one minute between requests.</p>
        <button className="primary-button" type="submit" disabled={verifying || submitting}>
          {verifying ? 'Checking code…' : 'Verify code'}
        </button>
        <p className="auth-status auth-error" role="alert">{codeMessage}</p>
      </form>}

      <p className="create-account"><a href="#sign-in" data-activity-id="sign-in-link">Back to sign-in</a></p>
    </section>
  )
}

export default ForgotPassword
