import { useEffect, useState } from 'react'
import { Link, useOutletContext, useParams } from 'react-router'
import { toast } from 'sonner'
import {
  AdminRequestError, changeRole, getUser, reactivateUser, roles, suspendUser,
  type AdminUserDetail, type Role,
} from './api'
import type { AdminContext } from './AdminLayout'
import { readableDate, roleLabels, signInMethod, statusLabels } from './format'

type Pending = { kind: 'suspend' } | { kind: 'reactivate' } | { kind: 'role'; role: Role }

function question(user: AdminUserDetail, pending: Pending): string {
  if (pending.kind === 'suspend') {
    return `Suspend ${user.name}? They will be signed out on every device and cannot sign in until an admin reactivates the account.`
  }
  if (pending.kind === 'reactivate') return `Reactivate ${user.name}? They will be able to sign in again.`
  return `Change ${user.name}'s role from ${roleLabels[user.role]} to ${roleLabels[pending.role]}?`
}

function done(user: AdminUserDetail, pending: Pending): string {
  if (pending.kind === 'suspend') return `${user.name} is suspended and signed out everywhere.`
  if (pending.kind === 'reactivate') return `${user.name} is active again.`
  return `${user.name} is now ${rolePhrases[pending.role]}.`
}

const rolePhrases: Record<Role, string> = { traveler: 'a traveler', support: 'support staff', admin: 'an admin' }

// Keyed on the id, so moving to another user starts from a clean page.
export default function AdminUser() {
  const { userId } = useParams()
  return <AdminUserPage key={userId} userId={userId ?? ''} />
}

function AdminUserPage({ userId }: { userId: string }) {
  const { admin, leave } = useOutletContext<AdminContext>()
  const id = /^[1-9][0-9]{0,9}$/.test(userId) ? Number(userId) : null
  const [user, setUser] = useState<AdminUserDetail | null>(null)
  const [problem, setProblem] = useState(id === null ? 'User not found.' : '')
  const [retry, setRetry] = useState(0)
  const [pending, setPending] = useState<Pending | null>(null)
  const [selectedRole, setSelectedRole] = useState<Role | ''>('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (id === null) return
    let active = true
    getUser(id).then(found => {
      if (active) { setUser(found); setSelectedRole(found.role); setProblem('') }
    }).catch(error => {
      if (!active) return
      if (error instanceof AdminRequestError && error.status === 403) leave()
      else setProblem(error instanceof Error ? error.message : 'Could not load this user.')
    })
    return () => { active = false }
  }, [id, retry, leave])

  async function confirm() {
    if (!user || !pending || busy) return
    setBusy(true)
    try {
      const updated = pending.kind === 'suspend' ? await suspendUser(user.id)
        : pending.kind === 'reactivate' ? await reactivateUser(user.id)
          : await changeRole(user.id, pending.role)
      toast.success(done(user, pending))
      setUser(updated)
      setSelectedRole(updated.role)
      setPending(null)
    } catch (error) {
      if (error instanceof AdminRequestError && error.status === 403) {
        leave()
        return
      }
      toast.error(error instanceof Error ? error.message : 'Something went wrong. Please try again.')
      setPending(null)
    } finally {
      setBusy(false)
    }
  }

  const back = <Link to="/admin" className="admin-back">← All users</Link>
  if (problem) {
    return <div className="admin-page">{back}
      <div className="admin-panel" role="alert">
        <p className="admin-error">{problem}</p>
        {problem !== 'User not found.' && <button type="button" className="button button-secondary"
          onClick={() => { setProblem(''); setRetry(value => value + 1) }}>Try again</button>}
      </div>
    </div>
  }
  if (!user) return <div className="admin-page">{back}<p role="status" className="admin-muted">Loading user…</p></div>

  const self = user.id === admin.id
  const methods = [user.password_enabled && 'Email and password', user.google_linked && 'Google'].filter(Boolean).join(', ')
  return <div className="admin-page">
    {back}
    <div className="admin-user-heading">
      <h1>{user.name}</h1>
      <span className={`admin-status admin-status-${user.status}`}>{statusLabels[user.status]}</span>
      <span className="admin-role">{roleLabels[user.role]}</span>
    </div>

    <section className="admin-panel" aria-labelledby="account-heading">
      <h2 id="account-heading">Account</h2>
      <dl className="admin-details">
        <div><dt>Email</dt><dd>{user.email}</dd></div>
        <div><dt>Sign-in methods</dt><dd>{methods || 'None'}</dd></div>
        {user.sso_email && <div><dt>Google email</dt><dd>{user.sso_email}</dd></div>}
        <div><dt>Joined</dt><dd>{readableDate(user.created_at)}</dd></div>
        <div><dt>Last sign-in</dt><dd>{user.last_sign_in_at
          ? `${readableDate(user.last_sign_in_at)} (${signInMethod(user.last_sign_in_method)})` : 'Never'}</dd></div>
        <div><dt>User ID</dt><dd>{user.id}</dd></div>
      </dl>
    </section>

    <section className="admin-panel" aria-labelledby="activity-heading">
      <h2 id="activity-heading">Activity</h2>
      <dl className="admin-cards admin-cards-small">
        <div className="admin-card"><dt>Active sessions</dt><dd>{user.counts.active_sessions}</dd></div>
        <div className="admin-card"><dt>Sign-ins</dt><dd>{user.counts.sign_ins}</dd></div>
        <div className="admin-card"><dt>Failed sign-ins</dt><dd>{user.counts.failed_sign_ins}</dd></div>
        <div className="admin-card"><dt>Passport uploads</dt><dd>{user.counts.passport_uploads}</dd></div>
      </dl>
      <p className="admin-muted">Passport images and details are never shown here.</p>
    </section>

    <section className="admin-panel" aria-labelledby="manage-heading">
      <h2 id="manage-heading">Manage</h2>
      {self ? <p className="admin-muted">This is your account. You can't suspend it or change its role; another admin can.</p> : <>
        <div className="admin-manage">
          <div>
            <h3>{user.status === 'active' ? 'Suspend account' : 'Reactivate account'}</h3>
            <p className="admin-muted">{user.status === 'active'
              ? 'Signs the user out everywhere and blocks sign-in.' : 'Lets the user sign in again.'}</p>
            <button type="button" className={`button ${user.status === 'active' ? 'admin-danger' : 'button-primary'}`}
              disabled={busy || pending !== null}
              onClick={() => setPending({ kind: user.status === 'active' ? 'suspend' : 'reactivate' })}>
              {user.status === 'active' ? 'Suspend' : 'Reactivate'}
            </button>
          </div>
          <div>
            <h3>Role</h3>
            <label className="admin-field">
              <span>New role</span>
              <select id="admin-new-role" value={selectedRole} disabled={busy || pending !== null}
                onChange={event => setSelectedRole(event.target.value as Role)}>
                {roles.map(option => <option key={option} value={option}>{roleLabels[option]}</option>)}
              </select>
            </label>
            <button type="button" className="button button-secondary"
              disabled={busy || pending !== null || !selectedRole || selectedRole === user.role}
              onClick={() => selectedRole && setPending({ kind: 'role', role: selectedRole })}>Change role</button>
          </div>
        </div>
        {pending && <div className="admin-confirm" role="alertdialog" aria-labelledby="admin-confirm-text">
          <p id="admin-confirm-text">{question(user, pending)}</p>
          <div className="admin-actions">
            <button type="button" className={`button ${pending.kind === 'suspend' ? 'admin-danger' : 'button-primary'}`}
              disabled={busy} aria-busy={busy} onClick={() => void confirm()}>
              {busy ? 'Saving…' : pending.kind === 'suspend' ? 'Yes, suspend' : pending.kind === 'reactivate' ? 'Yes, reactivate' : 'Yes, change role'}
            </button>
            <button type="button" className="button button-secondary" disabled={busy}
              onClick={() => { setPending(null); setSelectedRole(user.role) }}>Cancel</button>
          </div>
        </div>}
      </>}
    </section>
  </div>
}
