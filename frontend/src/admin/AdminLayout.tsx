import { useCallback, useEffect, useState } from 'react'
import { Link, Outlet, useNavigate } from 'react-router'
import { Toaster } from 'sonner'
import { restoreSession } from '../auth'
import { signInPath } from '../paths'
import { ADMIN_REQUIRED, AdminRequestError, getAdminMe, type AdminProfile } from './api'
import '../site.css'
import '../ui.css'
import './admin.css'

export type AdminContext = { admin: AdminProfile; leave: () => void }

// The page check only decides what to show: the backend refuses every /admin request from
// anyone who is not an active admin, whatever this page does.
export default function AdminLayout() {
  const navigate = useNavigate()
  const [admin, setAdmin] = useState<AdminProfile | null>(null)
  const [problem, setProblem] = useState('')
  const [attempt, setAttempt] = useState(0)

  // Sends a non-admin home; the site layout shows the notice there.
  const leave = useCallback(() => {
    navigate('/', { replace: true, state: { notice: ADMIN_REQUIRED } })
  }, [navigate])

  useEffect(() => {
    document.title = 'Admin | Taasheera'
    let active = true
    restoreSession().then(async traveler => {
      if (!active) return
      if (!traveler) {
        navigate(signInPath, { replace: true })
        return
      }
      const profile = await getAdminMe()
      if (active) setAdmin(profile)
    }).catch(error => {
      if (!active) return
      if (error instanceof AdminRequestError && error.status === 403) leave()
      else setProblem(error instanceof Error ? error.message : 'Could not check your access.')
    })
    return () => { active = false }
  }, [attempt, leave, navigate])

  return <div className="admin-shell">
    <a className="skip-link" href="#admin-main">Skip to content</a>
    <header className="admin-header">
      <div className="admin-header-inner">
        <Link to="/" className="logo" aria-label="Taasheera home">
          <span className="logo-mark" aria-hidden="true">T</span>Taasheera
        </Link>
        <span className="admin-badge">Admin</span>
        {admin && <nav className="admin-nav" aria-label="Admin">
          <Link to="/admin">Users</Link>
          <Link to="/backoffice">Monitoring</Link>
          <span className="admin-signed-in">Signed in as {admin.name}</span>
        </nav>}
      </div>
    </header>
    <main id="admin-main" className="admin-main">
      {admin ? <Outlet context={{ admin, leave } satisfies AdminContext} />
        : problem ? <div className="admin-panel" role="alert">
          <p>{problem}</p>
          <div className="admin-actions">
            <button type="button" className="button button-primary" onClick={() => {
              setProblem(''); setAttempt(value => value + 1)
            }}>Try again</button>
            <Link to={signInPath} className="button button-secondary">Sign in</Link>
          </div>
        </div>
          : <p role="status" className="admin-muted">Checking your access…</p>}
    </main>
    <Toaster position="top-center" richColors closeButton />
  </div>
}
