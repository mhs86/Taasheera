import { useEffect, useRef, useState } from 'react'
import { addAdmin, AdminRequestError, findAdminCandidate, type AdminUserSummary } from './api'

export default function AddAdmin({ onAdded, leave }: { onAdded: () => void; leave: () => void }) {
  const [email, setEmail] = useState('')
  const [candidate, setCandidate] = useState<AdminUserSummary | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  async function run(grant: boolean) {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    setMessage('')
    try {
      if (grant && candidate) {
        const added = await addAdmin(email, candidate.id)
        if (mounted.current) {
          setCandidate(null)
          setEmail('')
          setMessage(`${added.name} is now an admin.`)
          onAdded()
        }
      } else {
        const found = await findAdminCandidate(email)
        if (mounted.current) setCandidate(found)
      }
    } catch (error) {
      if (!mounted.current) return
      if (error instanceof AdminRequestError && error.status === 403) leave()
      else {
        setCandidate(null)
        setMessage(error instanceof Error ? error.message : 'Could not add an admin.')
      }
    } finally {
      pending.current = false
      if (mounted.current) setBusy(false)
    }
  }
  return <section className="admin-panel" aria-labelledby="add-admin-heading">
    <h2 id="add-admin-heading">Add an admin</h2>
    <p>Enter the email of an existing account, created with Google or email and password.
      New users must register first. Admins can manage users and access monitoring.</p>
    <form className="admin-filters" onSubmit={event => { event.preventDefault(); void run(false) }} aria-busy={busy}>
      <label className="admin-field admin-field-wide">
        <span>New admin email</span>
        <input type="email" required maxLength={254} autoComplete="off" disabled={busy} value={email}
          onChange={event => { setEmail(event.target.value); setCandidate(null); setMessage('') }} />
      </label>
      <button type="submit" className="button button-primary" disabled={busy}>Find account</button>
    </form>
    {candidate && <div>
      <p><strong>{candidate.name}</strong> ({candidate.email}) — {candidate.auth_type === 'google' ? 'Google' : 'Email and password'};
        {' '}{candidate.role}, {candidate.status}.</p>
      {candidate.role === 'admin' ? <p>This account is already an admin.</p>
        : candidate.status !== 'active' ? <p>Reactivate this account before adding it as an admin.</p>
          : <button type="button" className="button button-primary" disabled={busy} onClick={() => { void run(true) }}>
            Confirm admin access for {candidate.email}
          </button>}
    </div>}
    <p role="status" aria-live="polite">{message}</p>
  </section>
}
