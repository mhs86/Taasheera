import { useEffect, useState, type FormEvent } from 'react'
import { Link, useOutletContext, useSearchParams } from 'react-router'
import {
  AdminRequestError, getOverview, PAGE_SIZE, roles, searchUsers, statuses,
  type AdminOverview, type AdminUserPage, type Role, type Status,
} from './api'
import type { AdminContext } from './AdminLayout'
import { readableDate, roleLabels, statusLabels } from './format'

function Overview() {
  const { leave } = useOutletContext<AdminContext>()
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    getOverview().then(result => { if (active) setOverview(result) }).catch(error => {
      if (!active) return
      if (error instanceof AdminRequestError && error.status === 403) leave()
      else setFailed(true)
    })
    return () => { active = false }
  }, [leave])

  const cards: [string, number | undefined][] = [
    ['Total users', overview?.total_users],
    ['New in the last 7 days', overview?.new_last_7_days],
    ['Suspended', overview?.suspended],
    ['Applications started', overview?.applications_started],
  ]
  return <section aria-labelledby="overview-heading">
    <h2 id="overview-heading" className="visually-hidden">Overview</h2>
    {failed ? <p className="admin-muted" role="status">The overview numbers could not load.</p>
      : <dl className="admin-cards">
        {cards.map(([label, value]) => <div key={label} className="admin-card">
          <dt>{label}</dt>
          <dd>{value ?? '…'}</dd>
        </div>)}
      </dl>}
  </section>
}

function oneOf<T extends string>(value: string | null, options: readonly T[]): T | '' {
  return options.includes(value as T) ? value as T : ''
}

export default function AdminUsers() {
  const { leave } = useOutletContext<AdminContext>()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const role = oneOf<Role>(params.get('role'), roles)
  const status = oneOf<Status>(params.get('status'), statuses)
  const page = Math.max(1, Number.parseInt(params.get('page') ?? '1', 10) || 1)
  const [draft, setDraft] = useState(q)
  const [result, setResult] = useState<AdminUserPage | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  // The search whose answer is on screen; any other means a newer one is loading.
  const query = JSON.stringify([q, role, status, page, retry])
  const [loaded, setLoaded] = useState('')
  const loading = loaded !== query

  useEffect(() => {
    let active = true
    searchUsers({ q, role, status, page }).then(found => {
      if (active) { setResult(found); setError('') }
    }).catch(failure => {
      if (!active) return
      if (failure instanceof AdminRequestError && failure.status === 403) leave()
      else setError(failure instanceof Error ? failure.message : 'Could not load users.')
    }).finally(() => { if (active) setLoaded(query) })
    return () => { active = false }
  }, [q, role, status, page, retry, query, leave])

  function update(changes: Record<string, string>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next)
  }

  function search(event: FormEvent) {
    event.preventDefault()
    update({ q: draft.trim(), page: '' })
  }

  const pages = result ? Math.max(1, Math.ceil(result.total / PAGE_SIZE)) : 1
  return <div className="admin-page">
    <h1>Users</h1>
    <Overview />
    <section className="admin-panel" aria-labelledby="users-heading">
      <h2 id="users-heading">Find a user</h2>
      <form className="admin-filters" role="search" onSubmit={search}>
        <label className="admin-field admin-field-wide">
          <span>Name or email</span>
          <input id="admin-search" type="search" value={draft} maxLength={254}
            onChange={event => setDraft(event.target.value)} placeholder="maya@example.com" />
        </label>
        <label className="admin-field">
          <span>Role</span>
          <select id="admin-role" value={role} onChange={event => update({ role: event.target.value, page: '' })}>
            <option value="">Any role</option>
            {roles.map(option => <option key={option} value={option}>{roleLabels[option]}</option>)}
          </select>
        </label>
        <label className="admin-field">
          <span>Status</span>
          <select id="admin-status" value={status} onChange={event => update({ status: event.target.value, page: '' })}>
            <option value="">Any status</option>
            {statuses.map(option => <option key={option} value={option}>{statusLabels[option]}</option>)}
          </select>
        </label>
        <button type="submit" className="button button-primary">Search</button>
      </form>

      {error ? <div role="alert">
        <p className="admin-error">{error}</p>
        <button type="button" className="button button-secondary" onClick={() => {
          setError(''); setRetry(value => value + 1)
        }}>Try again</button>
      </div> : result && <>
        <p className="admin-muted" role="status" aria-live="polite">
          {loading ? 'Loading…' : `${result.total} ${result.total === 1 ? 'user' : 'users'} found`}
        </p>
        {result.items.length > 0 && <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr>
              <th scope="col">Name</th><th scope="col">Email</th><th scope="col">Role</th>
              <th scope="col">Status</th><th scope="col">Joined</th><th scope="col">Last sign-in</th>
            </tr></thead>
            <tbody>
              {result.items.map(user => <tr key={user.id}>
                <td><Link to={`/admin/users/${user.id}`}>{user.name}</Link></td>
                <td>{user.email}</td>
                <td>{roleLabels[user.role]}</td>
                <td><span className={`admin-status admin-status-${user.status}`}>{statusLabels[user.status]}</span></td>
                <td>{readableDate(user.created_at, false)}</td>
                <td>{readableDate(user.last_sign_in_at)}</td>
              </tr>)}
            </tbody>
          </table>
        </div>}
        {result.total > PAGE_SIZE && <nav className="admin-pagination" aria-label="Pages">
          <button type="button" className="button button-secondary" disabled={page <= 1 || loading}
            onClick={() => update({ page: String(page - 1) })}>Previous</button>
          <span>Page {page} of {pages}</span>
          <button type="button" className="button button-secondary" disabled={page >= pages || loading}
            onClick={() => update({ page: String(page + 1) })}>Next</button>
        </nav>}
      </>}
      {!result && !error && <p className="admin-muted" role="status">Loading users…</p>}
    </section>
  </div>
}
