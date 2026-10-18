import { useState } from 'react'
import { changePassword } from './auth'
import { passwordValidation } from './passwordReset'

export default function ChangePassword() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState(false)

  return <section className="change-password" aria-labelledby="change-password-heading">
    <h2 id="change-password-heading">Change password</h2>
    <form aria-busy={busy} onSubmit={async event => {
      event.preventDefault()
      if (busy) return
      const validation = passwordValidation(newPassword, confirmation)
      if (validation) { setError(true); setMessage(validation); return }
      if (newPassword === currentPassword) {
        setError(true); setMessage('Choose a different new password.'); return
      }
      setBusy(true)
      setMessage('')
      try {
        await changePassword(currentPassword, newPassword)
        setCurrentPassword('')
        setNewPassword('')
        setConfirmation('')
        setError(false)
        setMessage('Password changed. Your other sessions have been signed out.')
      } catch (cause) {
        setError(true)
        setMessage(cause instanceof Error ? cause.message : 'Could not change your password. Please try again.')
      } finally {
        setBusy(false)
      }
    }}>
      <label htmlFor="current-password">Current password</label>
      <input id="current-password" type="password" autoComplete="current-password" required
        value={currentPassword} disabled={busy} onChange={event => setCurrentPassword(event.target.value)} />
      <label htmlFor="new-password">New password</label>
      <input id="new-password" type="password" autoComplete="new-password" required
        value={newPassword} disabled={busy} onChange={event => setNewPassword(event.target.value)} />
      <label htmlFor="confirm-new-password">Confirm new password</label>
      <input id="confirm-new-password" type="password" autoComplete="new-password" required
        value={confirmation} disabled={busy} onChange={event => setConfirmation(event.target.value)} />
      <button className="primary-button" type="submit" disabled={busy}>{busy ? 'Changing password…' : 'Change password'}</button>
      <p className={`auth-status${error ? ' auth-error' : ''}`} role={error ? 'alert' : 'status'}>{message}</p>
    </form>
  </section>
}
