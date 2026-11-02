import { useCallback, useRef, useState } from 'react'
import type { Traveler } from './auth'
import { deleteAccount } from './privacy'
import GoogleSignIn from './GoogleSignIn'

export default function DeleteAccount({ traveler, clientId, onDeleted }: {
  traveler: Traveler; clientId: string; onDeleted: (complete: boolean) => void
}) {
  const [opened, setOpened] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [password, setPassword] = useState('')
  const [googleToken, setGoogleToken] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const receiveCredential = useCallback((credential: string) => { setGoogleToken(credential); setMessage('Google identity received. Confirm deletion below.') }, [])
  const googleMessage = useCallback((value: string) => setMessage(value), [])
  return <section className="profile-section danger-zone" aria-labelledby="delete-account-heading">
    <h2 id="delete-account-heading">Delete account and all data</h2>
    <p>This permanently removes your profile, passport files, applications, sessions, and activity history.</p>
    {!opened ? <button type="button" className="danger-button" onClick={() => setOpened(true)}>Delete my account</button> :
      <form aria-busy={busy} onSubmit={async event => {
        event.preventDefault()
        if (pending.current || confirmation !== 'DELETE') return
        pending.current = true; setBusy(true); setMessage('')
        try { onDeleted(await deleteAccount(traveler.id, password, googleToken)) }
        catch (error) { setMessage(error instanceof Error ? error.message : 'Could not delete your account.') }
        finally { setPassword(''); setGoogleToken(''); pending.current = false; setBusy(false) }
      }}>
        {traveler.password_enabled !== false ? <label htmlFor="delete-current-password">Current password
          <input id="delete-current-password" type="password" autoComplete="current-password" required disabled={busy}
            value={password} onChange={event => setPassword(event.target.value)} />
        </label> : <GoogleSignIn clientId={clientId} disabled={busy} onCredential={receiveCredential} onMessage={googleMessage} />}
        <label htmlFor="delete-confirmation">Type DELETE to confirm permanent deletion
          <input id="delete-confirmation" required value={confirmation} disabled={busy} autoComplete="off"
            onChange={event => setConfirmation(event.target.value)} />
        </label>
        <button type="submit" className="danger-button" disabled={busy || confirmation !== 'DELETE' ||
          (traveler.password_enabled === false ? !googleToken : !password)}>{busy ? 'Deleting…' : 'Permanently delete account'}</button>{' '}
        <button type="button" disabled={busy} onClick={() => { setOpened(false); setConfirmation(''); setPassword(''); setGoogleToken(''); setMessage('') }}>Cancel</button>
        {message && <p role="alert">{message}</p>}
      </form>}
  </section>
}
