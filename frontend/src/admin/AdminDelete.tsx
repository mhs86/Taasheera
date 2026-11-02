import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { AdminAccessError, deleteUser } from '../admin'

export default function AdminDelete({ id, name, disabled, onBusy, onForbidden }: {
  id: number; name: string; disabled: boolean; onBusy: (busy: boolean) => void; onForbidden: () => void
}) {
  const navigate = useNavigate()
  const [opened, setOpened] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const pending = useRef(false)
  return <section className="admin-panel" aria-labelledby="admin-delete-heading">
    <h2 id="admin-delete-heading">Delete account and all data</h2>
    <p>Removes this user's profile, passport files, applications and answers, sessions, recovery credentials and activity.</p>
    {!opened ? <button type="button" className="button admin-danger" disabled={disabled}
      onClick={() => setOpened(true)}>Delete user</button> : <form onSubmit={async event => {
        event.preventDefault()
        if (pending.current || confirmation !== 'DELETE') return
        pending.current = true; setBusy(true); onBusy(true); setProblem('')
        try {
          const result = await deleteUser(id)
          toast.success(result.pending ? 'Account disabled. Data erasure is queued for retry.' : 'User and associated data deleted.')
          navigate('/admin', { replace: true })
        } catch (error) {
          if (error instanceof AdminAccessError) onForbidden()
          else setProblem(error instanceof Error ? error.message : 'Could not delete user.')
        } finally { pending.current = false; setBusy(false); onBusy(false) }
      }}>
      <p>Permanently delete {name}?</p>
      <label className="admin-field" htmlFor="detail-delete-confirmation">Type DELETE to confirm
        <input id="detail-delete-confirmation" value={confirmation} disabled={busy}
          onChange={event => setConfirmation(event.target.value)} />
      </label>
      <div className="admin-actions">
        <button type="submit" className="button admin-danger" disabled={busy || confirmation !== 'DELETE'}>{busy ? 'Deleting…' : 'Confirm permanent deletion'}</button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => { setOpened(false); setConfirmation(''); setProblem('') }}>Cancel</button>
      </div>
      {problem && <p role="alert">{problem}</p>}
    </form>}
  </section>
}
