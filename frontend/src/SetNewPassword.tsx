import { useRef, useState } from 'react'
import { resetPassword } from './auth'
import { passwordValidation, ResetError } from './passwordReset'

type Props = { token: string | null; onTokenCleared: () => void; onSuccess: () => void }

function SetNewPassword({ token, onTokenCleared, onSuccess }: Props) {
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [succeeded, setSucceeded] = useState(false)
  const inProgress = useRef(false)
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmPasswordRef = useRef<HTMLInputElement>(null)

  function validatePasswords() {
    const password = passwordRef.current
    const confirmation = confirmPasswordRef.current
    if (!password || !confirmation) return
    confirmation.setCustomValidity(passwordValidation(password.value, confirmation.value))
    setMessage('')
  }

  return (
    <section className="sign-in-card" aria-labelledby="new-password-heading">
      <p className="eyebrow">YOUR JOURNEY STARTS HERE</p>
      <h1 id="new-password-heading">Set new password</h1>

      {succeeded ? <>
        <p className="auth-status" role="status">Your password has been changed. Sign in again with your new password.</p>
        <p className="create-account"><a href="#sign-in" data-activity-id="sign-in-link">Sign in</a></p>
      </> : !token ? <>
        <p className="auth-status auth-error" role="alert">
          {message || 'This reset link is missing or invalid. Open the link from your email, or request a new one.'}
        </p>
        <p className="create-account"><a href="#forgot-password" data-activity-id="reset-link">Request a new reset link</a></p>
        <p className="create-account"><a href="#sign-in" data-activity-id="sign-in-link">Back to sign-in</a></p>
      </> : <>
        <p className="intro">Enter and confirm your new password.</p>
        <form
          aria-busy={submitting}
          onSubmit={async (event) => {
            event.preventDefault()
            if (inProgress.current) return
            const form = event.currentTarget
            validatePasswords()
            if (!form.reportValidity()) return
            const password = passwordRef.current?.value ?? ''
            inProgress.current = true
            setSubmitting(true)
            setMessage('')
            try {
              await resetPassword(token, password)
              setSucceeded(true)
              onSuccess()
            } catch (error) {
              setMessage(error instanceof ResetError ? error.message : 'Could not change your password. Please try again.')
              if (error instanceof ResetError && error.invalidLink) onTokenCleared()
            } finally {
              form.reset()
              confirmPasswordRef.current?.setCustomValidity('')
              inProgress.current = false
              setSubmitting(false)
            }
          }}
        >
          <label htmlFor="password">New password</label>
          <input ref={passwordRef} id="password" name="password" type="password"
            autoComplete="new-password" onChange={validatePasswords} disabled={submitting}
            minLength={8} aria-describedby="password-help" required />

          <label htmlFor="confirm-password">Confirm password</label>
          <input ref={confirmPasswordRef} id="confirm-password" name="confirmPassword" type="password"
            autoComplete="new-password" onChange={validatePasswords} disabled={submitting} required />

          <p className="password-help" id="password-help">Use at least 8 characters and at most 72 UTF-8 bytes.</p>
          <button className="primary-button" data-activity-id="reset-submit" type="submit" disabled={submitting}>
            {submitting ? 'Changing password…' : 'Set new password'}
          </button>
        </form>
        <p className="auth-status auth-error" role="alert">{message}</p>
        <p className="create-account"><a href="#forgot-password" data-activity-id="reset-link">Request a new reset link</a></p>
        <p className="create-account"><a href="#sign-in" data-activity-id="sign-in-link">Back to sign-in</a></p>
      </>}
    </section>
  )
}

export default SetNewPassword
