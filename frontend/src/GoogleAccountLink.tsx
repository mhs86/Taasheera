import { useEffect, useRef, useState } from 'react'
import { linkGoogleAndSignIn, type Traveler } from './auth'

export default function GoogleAccountLink({ credential, onSignedIn, onCancel }: {
  credential: string; onSignedIn: (traveler: Traveler) => void; onCancel: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const pending = useRef(false)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  return <section className="sign-in-card" aria-labelledby="google-link-heading">
    <h1 id="google-link-heading">Connect Google to your account</h1>
    <p>You already have an account with this Google email. Confirm your existing Taasheera password once
      to connect Google. Your account details, applications and permissions stay with this account.</p>
    <form aria-busy={busy} onSubmit={async event => {
      event.preventDefault()
      if (pending.current) return
      const form = event.currentTarget
      pending.current = true
      setBusy(true)
      setMessage('')
      try {
        const traveler = await linkGoogleAndSignIn(credential, String(new FormData(form).get('password') ?? ''))
        if (mounted.current) onSignedIn(traveler)
      } catch (error) {
        if (mounted.current) setMessage(error instanceof Error ? error.message : 'Could not connect Google.')
      } finally {
        const input = form.elements.namedItem('password')
        if (input instanceof HTMLInputElement) input.value = ''
        pending.current = false
        if (mounted.current) setBusy(false)
      }
    }}>
      <label htmlFor="google-link-password">Existing account password</label>
      <input id="google-link-password" name="password" type="password" autoComplete="current-password"
        required disabled={busy} />
      <button type="submit" className="primary-button" disabled={busy}>
        {busy ? 'Connecting Google…' : 'Link Google and sign in'}
      </button>
    </form>
    <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>Use another sign-in method</button>
    <a href="#forgot-password">Forgot your password?</a>
    <p role="status" className="auth-status">{message}</p>
  </section>
}
