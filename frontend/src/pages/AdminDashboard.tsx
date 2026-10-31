import { useCallback, useEffect, useRef, useState } from 'react'
import { AdminAccessError, adminRequest, deleteUser, type AdminUser, type Monitoring, type Staff, type UserPage } from '../admin'
import '../App.css'
import './dashboard.css'

export default function AdminDashboard() {
  const [staff, setStaff] = useState<Staff | null>(null)
  const [monitoring, setMonitoring] = useState<Monitoring | null>(null)
  const [users, setUsers] = useState<UserPage | null>(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [denied, setDenied] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<AdminUser | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [message, setMessage] = useState('')
  const pending = useRef(false)
  const generation = useRef(0)

  const load = useCallback((query = '', page = 1) => {
    const version = ++generation.current
    return adminRequest<Staff>('/me').then(async identity => {
      const [health, accounts] = await Promise.all([
        adminRequest<Monitoring>('/monitoring'),
        adminRequest<UserPage>(`/users?q=${encodeURIComponent(query)}&page=${page}`),
      ])
      if (version !== generation.current) return
      setStaff(identity); setMonitoring(health); setUsers(accounts); setDenied(false)
    }).catch(problem => {
      if (version !== generation.current) return
      setError(problem instanceof Error ? problem.message : 'Could not load the dashboard.')
      if (problem instanceof AdminAccessError) { setDenied(true); setStaff(null); setMonitoring(null); setUsers(null) }
    }).finally(() => { if (version === generation.current) setLoading(false) })
  }, [])

  function refresh(query = search, page = users?.page ?? 1) {
    setLoading(true); setError('')
    void load(query, page)
  }

  useEffect(() => {
    document.title = 'Admin dashboard | Taasheera'
    void load()
    return () => { generation.current += 1 }
  }, [load])

  return <main className="dashboard-page">
    <header className="dashboard-header"><a href="/">Taasheera</a><nav aria-label="Admin navigation"><a href="/account">Your account</a><a href="/sign-in">Sign in</a></nav></header>
    <div className="dashboard-content">
      <p className="eyebrow">OPERATIONS</p><h1>Admin dashboard</h1>
      <p>Application status, recent errors, and account management.</p>
      {staff && <p>Signed in as {staff.name}</p>}
      {loading && <p role="status">Loading dashboard…</p>}
      {error && <p role="alert" className="auth-error">{error}</p>}
      {!denied && <button type="button" disabled={loading || busy} onClick={() => refresh()}>Refresh dashboard</button>}
      {message && <p role="status">{message}</p>}
      {monitoring && <>
        <section aria-labelledby="application-monitor-heading"><h2 id="application-monitor-heading">Applications by status</h2>
          <p>{monitoring.total_applications} total applications</p>
          <div className="status-grid">{Object.entries(monitoring.applications_by_status).map(([status, count]) =>
            <div className="status-card" key={status}><span>{status.replaceAll('_', ' ')}</span><strong>{count}</strong></div>)}</div>
          {monitoring.total_applications === 0 && <p>No applications have been started yet.</p>}
        </section>
        <section aria-labelledby="recent-errors-heading"><h2 id="recent-errors-heading">Recent errors</h2>
          <p>Newest backend activity failures. Request bodies and document contents are excluded.</p>
          {monitoring.recent_errors.length === 0 ? <p>No errors recorded.</p> : <div className="table-scroll"><table>
            <thead><tr><th>Time</th><th>Source</th><th>Outcome</th></tr></thead><tbody>
              {monitoring.recent_errors.map(event => <tr key={event.id}><td>{new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(event.occurred_at) ? event.occurred_at : `${event.occurred_at}Z`).toLocaleString()}</td><td>{event.source}</td><td>{event.outcome}</td></tr>)}
            </tbody></table></div>}
          {!monitoring.agent_failures_available && <p>Agent failure monitoring will appear when the agent workflow is connected.</p>}
          {monitoring.pending_erasures > 0 && <p role="status">{monitoring.pending_erasures} account erasure(s) awaiting cleanup. Follow the monitoring runbook.</p>}
        </section>
      </>}
      {users && <section aria-labelledby="admin-users-heading"><h2 id="admin-users-heading">Users</h2>
        <form className="search-form" onSubmit={event => { event.preventDefault(); setSelected(null); refresh(search, 1) }}>
          <label htmlFor="admin-search">Search name or email</label><input id="admin-search" maxLength={100} value={search} onChange={event => setSearch(event.target.value)} />
          <button type="submit" disabled={loading || busy}>Search</button>
        </form>
        <p>{users.total} users</p>
        {users.items.length === 0 ? <p>No users match your search.</p> : <div className="table-scroll"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Action</th></tr></thead><tbody>
          {users.items.map(user => <tr key={user.id}><td>{user.name}</td><td>{user.email}</td><td>{user.role}</td><td>{user.status}</td><td>
            <button type="button" className="danger-button" aria-label={`Delete ${user.name}`} disabled={busy || loading || user.id === staff?.id || user.role === 'admin'}
              onClick={() => { setSelected(user); setConfirmation(''); setError(''); setMessage('') }}>Delete user</button>
          </td></tr>)}
        </tbody></table></div>}
        {selected && <form className="deletion-confirm" aria-label="Confirm user deletion" onSubmit={async event => {
          event.preventDefault()
          if (pending.current || confirmation !== 'DELETE') return
          pending.current = true; setBusy(true); setError('')
          try {
            const result = await deleteUser(selected.id)
            setSelected(null); setConfirmation('')
            setMessage(result.pending ? 'Account disabled. Data erasure is queued for retry.' : 'User and associated data deleted.')
            await load(search)
          } catch (problem) { setError(problem instanceof Error ? problem.message : 'Could not delete user.') }
          finally { pending.current = false; setBusy(false) }
        }}>
          <h3>Permanently delete {selected.name}?</h3><p>This removes their profile, passports, applications, sessions, and activity.</p>
          <label htmlFor="admin-delete-confirmation">Type DELETE to confirm</label><input id="admin-delete-confirmation" value={confirmation} disabled={busy} onChange={event => setConfirmation(event.target.value)} />
          <button className="danger-button" type="submit" disabled={busy || confirmation !== 'DELETE'}>{busy ? 'Deleting…' : 'Confirm permanent deletion'}</button>{' '}
          <button type="button" disabled={busy} onClick={() => setSelected(null)}>Cancel</button>
        </form>}
        <div className="pagination"><button disabled={loading || busy || users.page === 1} onClick={() => { setSelected(null); refresh(search, users.page - 1) }}>Previous users</button>
          <span>Page {users.page}</span><button disabled={loading || busy || users.page * users.page_size >= users.total} onClick={() => { setSelected(null); refresh(search, users.page + 1) }}>Next users</button></div>
      </section>}
    </div>
  </main>
}
