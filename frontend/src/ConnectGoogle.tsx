import { useCallback, useEffect, useRef, useState } from 'react'
import { connectGoogle, type Traveler } from './auth'
import GoogleSignIn from './GoogleSignIn'

type Props = {
  traveler: Traveler
  clientId: string
  configurationStatus: 'loading' | 'ready' | 'failed'
  onConfigurationRetry?: () => void
  onConnected: (traveler: Traveler) => void
}

export default function ConnectGoogle({ traveler, clientId, configurationStatus,
  onConfigurationRetry, onConnected }: Props) {
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const inProgress = useRef(false)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const credential = useCallback(async (idToken: string) => {
    if (inProgress.current || !password) return
    inProgress.current = true
    setBusy(true)
    setMessage('Connecting Google…')
    try {
      const profile = await connectGoogle(idToken, password, traveler.id)
      if (mounted.current) onConnected(profile)
    } catch (error) {
      if (mounted.current) setMessage(error instanceof Error && error.name === 'Error'
        ? error.message : 'Could not connect Google. Please try again.')
    } finally {
      if (mounted.current) { setPassword(''); setBusy(false) }
      inProgress.current = false
    }
  }, [password, onConnected, traveler.id])

  if (traveler.sso_email) return <p>Google connected: {traveler.sso_email}</p>
  return <section aria-labelledby="connect-google-heading">
    <h2 id="connect-google-heading">Connect Google</h2>
    <p>Confirm your current password, then choose your Google account to enable Google sign-in for this traveler account.</p>
    <label htmlFor="connect-google-password">Current password</label>
    <input id="connect-google-password" type="password" autoComplete="current-password"
      value={password} disabled={busy} onChange={event => setPassword(event.target.value)} />
    <GoogleSignIn clientId={clientId} disabled={busy || !password}
      configurationStatus={configurationStatus} onConfigurationRetry={onConfigurationRetry}
      onCredential={credential} onMessage={setMessage} />
    <p role="status">{message}</p>
  </section>
}
