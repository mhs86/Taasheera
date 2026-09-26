import { useRef, useState } from 'react'

function SetNewPassword() {
  const [message, setMessage] = useState('')
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmPasswordRef = useRef<HTMLInputElement>(null)

  // Keep password values in the form only and use browser validation messages.
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
    <section className="sign-in-card" aria-labelledby="new-password-heading">
      <p className="eyebrow">YOUR JOURNEY STARTS HERE</p>
      <h1 id="new-password-heading">Set new password</h1>
      <p className="intro">Enter and confirm your new password.</p>

      <p className="availability-note" id="new-password-note">
        Preview only. Password changes are not connected yet.
      </p>

      <form
        aria-describedby="new-password-note"
        onSubmit={(event) => {
          event.preventDefault()
          // Recheck in case a password manager filled either field.
          validatePasswords()
          if (!event.currentTarget.reportValidity()) return

          event.currentTarget.reset()
          setMessage('Setting a new password is not available yet. Your password has not been changed, sent, or saved.')
        }}
      >
        <label htmlFor="password">New password</label>
        <input
          ref={passwordRef}
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
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
          onChange={validatePasswords}
          required
        />

        <button className="primary-button" type="submit">Set new password</button>
      </form>

      <p className="auth-status" role="status">{message}</p>
      <p className="create-account"><a href="#sign-in">Back to sign-in</a></p>
    </section>
  )
}

export default SetNewPassword
