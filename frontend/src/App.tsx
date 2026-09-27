import { useCallback, useEffect, useRef, useState } from 'react'
import { restoreSession, signIn, signInWithGoogle, signOut, type Traveler } from './auth'
import GoogleSignIn from './GoogleSignIn'
import { disableGoogleAutoSelect } from './googleIdentity'
import './App.css'
import CreateAccount from './CreateAccount'
import ForgotPassword from './ForgotPassword'
import SetNewPassword from './SetNewPassword'
import { readNavigation, type Navigation } from './navigation'

const pageTitles = {
  'sign-in': 'Sign in',
  'create-account': 'Create account',
  'forgot-password': 'Forgot password',
  'set-new-password': 'Set new password',
}

function App({ initialNavigation, googleClientId = import.meta.env?.VITE_GOOGLE_CLIENT_ID?.trim() ?? '' }: {
  initialNavigation: Navigation; googleClientId?: string
}) {
  const [route, setRoute] = useState({ ...initialNavigation, version: 0 })
  const page = route.page
  const isResetPage = page === 'set-new-password'
  const isRecoveryPage = isResetPage || page === 'forgot-password'
  const [traveler, setTraveler] = useState<Traveler | null>(null)
  const [checking, setChecking] = useState(true)
  const [sessionError, setSessionError] = useState('')
  const [loggingOut, setLoggingOut] = useState(false)

  useEffect(() => {
    if (isRecoveryPage) return
    let active = true
    restoreSession().then((profile) => {
      if (active) setTraveler(profile)
    }).catch(() => {
      if (active) setSessionError('Could not restore your session. Check your connection and try reloading, or sign in again.')
    }).finally(() => {
      if (active) setChecking(false)
    })
    return () => { active = false }
  }, [isRecoveryPage])

  useEffect(() => {
    const updatePage = () => {
      const next = readNavigation(window)
      setRoute(previous => ({ ...next, version: previous.version + 1 }))
    }
    window.addEventListener('hashchange', updatePage)
    return () => window.removeEventListener('hashchange', updatePage)
  }, [])

  useEffect(() => {
    document.title = `${traveler && !isRecoveryPage ? 'Signed in' : pageTitles[page]} | Taasheera`
  }, [page, traveler, isRecoveryPage])

  return (
    <main className="sign-in-page">
      <header className="brand">
        <span className="brand-mark" aria-hidden="true">T</span>
        Taasheera
      </header>

      {isResetPage ? <SetNewPassword
        key={route.version}
        token={route.resetToken}
        onTokenCleared={() => setRoute(previous => ({ ...previous, resetToken: null }))}
        onSuccess={() => {
          setTraveler(null)
          setSessionError('')
          setChecking(false)
          setRoute(previous => ({ ...previous, resetToken: null }))
        }}
      /> : page === 'forgot-password' ? <ForgotPassword /> : checking ? <p role="status">Restoring your session…</p> : traveler ? (
        <section className="sign-in-card" aria-labelledby="signed-in-heading">
          <p className="eyebrow">YOUR TRAVELER ACCOUNT</p>
          <h1 id="signed-in-heading">Welcome, {traveler.name}</h1>
          <p className="intro">You are signed in.</p>
          <button className="primary-button" disabled={loggingOut} onClick={async () => {
            setLoggingOut(true)
            setSessionError('')
            try {
              await signOut()
              disableGoogleAutoSelect()
              setTraveler(null)
              window.location.hash = 'sign-in'
            } catch {
              setSessionError('Could not confirm logout. Check your connection and try again.')
            } finally {
              setLoggingOut(false)
            }
          }}>{loggingOut ? 'Logging out…' : 'Log out'}</button>
        </section>
      ) : <>
        {page === 'sign-in' && <SignIn googleClientId={googleClientId} onSignedIn={(profile) => {
          setSessionError('')
          setTraveler(profile)
        }} />}
        {page === 'create-account' && <CreateAccount />}
      </>}
      {sessionError && !isRecoveryPage && <p className="auth-status auth-error" role="alert">{sessionError}</p>}

      <footer>Your next chapter starts with a journey.</footer>
    </main>
  )
}

function SignIn({ onSignedIn, googleClientId }: { onSignedIn: (traveler: Traveler) => void; googleClientId: string }) {
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const inProgress = useRef(false)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const googleCredential = useCallback(async (credential: string) => {
    if (inProgress.current || !mounted.current) return
    inProgress.current = true
    setSubmitting(true)
    setMessage('Signing in with Google…')
    try {
      const profile = await signInWithGoogle(credential)
      if (mounted.current) onSignedIn(profile)
    } catch (error) {
      if (mounted.current) setMessage(error instanceof Error && error.name === 'Error'
        ? error.message : 'Could not complete Google sign-in. Please try again.')
    } finally {
      inProgress.current = false
      if (mounted.current) setSubmitting(false)
    }
  }, [onSignedIn])

  return (
    <section className="sign-in-card" aria-labelledby="sign-in-heading">
      <p className="eyebrow">YOUR JOURNEY STARTS HERE</p>
      <h1 id="sign-in-heading">Welcome back</h1>
      <p className="intro">Sign in to your traveler account.</p>

      <form
        aria-busy={submitting}
        onSubmit={async (event) => {
          event.preventDefault()
          if (inProgress.current) return
          const form = event.currentTarget
          const fields = new FormData(form)
          inProgress.current = true
          setSubmitting(true)
          setMessage('')
          try {
            const profile = await signIn(String(fields.get('email') ?? ''), String(fields.get('password') ?? ''))
            onSignedIn(profile)
          } catch (error) {
            setMessage(error instanceof Error && error.name === 'Error'
              ? error.message : 'Could not sign in. Check your connection and try again.')
          } finally {
            const password = form.elements.namedItem('password')
            if (password instanceof HTMLInputElement) password.value = ''
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
          placeholder="you@example.com"
          required
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          disabled={submitting}
          required
        />

        <a
          className="forgot-password"
          href="#forgot-password"
        >
          Forgot your password?
        </a>

        <button className="primary-button" type="submit" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}</button>
      </form>

      <div className="divider"><span>or</span></div>

      <GoogleSignIn clientId={googleClientId} disabled={submitting}
        onCredential={googleCredential} onMessage={setMessage} />

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

