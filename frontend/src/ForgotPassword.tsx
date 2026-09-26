import { useState } from 'react'

function ForgotPassword() {
  const [message, setMessage] = useState('')

  return (
    <section className="sign-in-card" aria-labelledby="forgot-password-heading">
      <p className="eyebrow">YOUR JOURNEY STARTS HERE</p>
      <h1 id="forgot-password-heading">Forgot password?</h1>
      <p className="intro">Enter the email for your traveler account.</p>

      <p className="availability-note" id="reset-email-note">
        Preview only. Password reset and email sending are not connected yet.
      </p>

      <form
        aria-describedby="reset-email-note"
        onSubmit={(event) => {
          event.preventDefault()
          setMessage('Password reset is not available yet. No email has been sent.')
        }}
      >
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          onChange={() => setMessage('')}
          required
        />

        <button className="primary-button" type="submit">Request password reset</button>
      </form>

      <p className="auth-status" role="status">{message}</p>

      <p className="create-account"><a href="#sign-in">Back to sign-in</a></p>
      <p className="create-account">
        <a href="#set-new-password">Preview the Set new password page</a>
      </p>
    </section>
  )
}

export default ForgotPassword
