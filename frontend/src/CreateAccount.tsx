import { useRef, useState } from 'react'

function CreateAccount() {
  const [message, setMessage] = useState('')
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

      <p className="availability-note" id="registration-note">
        Preview only. Registration is not connected yet.
      </p>

      <form
        aria-describedby="registration-note"
        onSubmit={(event) => {
          event.preventDefault()
          // Recheck in case a password manager filled either password field.
          validatePasswords()
          if (!event.currentTarget.reportValidity()) return

          event.currentTarget.reset()
          setMessage('Registration is not available yet. No account was created and your details have not been sent or saved.')
        }}
      >
        <label htmlFor="name">Name</label>
        <input
          id="name"
          name="name"
          type="text"
          autoComplete="name"
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

        <button className="primary-button" type="submit">Create account</button>
      </form>

      <p className="create-account">
        Already have an account? <a href="#sign-in">Sign in</a>
      </p>

      <p className="auth-status" role="status">{message}</p>
    </section>
  )
}

export default CreateAccount
