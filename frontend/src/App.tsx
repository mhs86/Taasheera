import { useEffect, useState } from 'react'
import './App.css'
import CreateAccount from './CreateAccount'

function App() {
  const [isCreatingAccount, setIsCreatingAccount] = useState(
    () => window.location.hash === '#create-account',
  )

  useEffect(() => {
    const updatePage = () => setIsCreatingAccount(window.location.hash === '#create-account')
    window.addEventListener('hashchange', updatePage)
    return () => window.removeEventListener('hashchange', updatePage)
  }, [])

  useEffect(() => {
    document.title = `${isCreatingAccount ? 'Create account' : 'Sign in'} | Taasheera`
  }, [isCreatingAccount])

  return (
    <main className="sign-in-page">
      <header className="brand">
        <span className="brand-mark" aria-hidden="true">T</span>
        Taasheera
      </header>

      {isCreatingAccount ? <CreateAccount /> : <SignIn />}

      <footer>Your next chapter starts with a journey.</footer>
    </main>
  )
}

function SignIn() {
  const [message, setMessage] = useState('')

  return (
    <section className="sign-in-card" aria-labelledby="sign-in-heading">
      <p className="eyebrow">YOUR JOURNEY STARTS HERE</p>
      <h1 id="sign-in-heading">Welcome back</h1>
      <p className="intro">Sign in to your traveler account.</p>

      <p className="availability-note" id="availability-note">
        Preview only. Sign-in is not connected yet.
      </p>

      <form
        aria-describedby="availability-note"
        onSubmit={(event) => {
          event.preventDefault()
          // Connect real authentication here when the backend is ready.
          setMessage('Email sign-in is not available yet. Your details have not been sent or saved.')
        }}
      >
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
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />

        <a
          className="forgot-password"
          href="#auth-status"
          onClick={() => setMessage('Password reset is not available yet. Please check back later.')}
        >
          Forgot your password?
        </a>

        <button className="primary-button" type="submit">Sign in</button>
      </form>

      <div className="divider"><span>or</span></div>

      <button
        className="google-button"
        type="button"
        onClick={() => setMessage('Google sign-in is not connected yet. Please check back later.')}
      >
        Continue with Google
      </button>

      <p className="create-account">
        New to Taasheera?{' '}
        <a href="#create-account">
          Create an account
        </a>
      </p>

      <p className="auth-status" id="auth-status" role="status">{message}</p>
    </section>
  )
}

export default App

