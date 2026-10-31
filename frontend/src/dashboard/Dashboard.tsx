import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { listApplications, type ApplicationSummary } from '../application/api'
import { formatShortDate } from '../application/format'
import ApplicationActions from './ApplicationActions'
import { applicationName, DISCLAIMER, formatDateTime, useTraveler } from './helpers'
import { Flag, SignedOut, StatusChip } from './shared'
import '../ui.css'
import './dashboard.css'

type View = 'active' | 'archived'

// Every application the traveler has started, with where it stands (US 19). Archived ones sit
// behind their own tab until restored or deleted (US 79).
export default function Dashboard() {
  const traveler = useTraveler()
  const [view, setView] = useState<View>('active')
  // null while loading; an Error when the list could not be loaded.
  const [applications, setApplications] = useState<ApplicationSummary[] | Error | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!traveler) return
    let active = true
    listApplications(view === 'archived')
      .then(found => { if (active) setApplications(found) })
      .catch(() => { if (active) setApplications(new Error('Could not load your applications.')) })
    return () => { active = false }
  }, [traveler, view, attempt])

  // Read when a toast's Undo runs, which can be after the traveler switched tabs.
  const viewRef = useRef(view)
  useEffect(() => { viewRef.current = view }, [view])

  const drop = useCallback((id: string) => {
    setApplications(current => Array.isArray(current) ? current.filter(application => application.id !== id) : current)
  }, [])
  // Archiving moves an application to the other tab; Undo brings it back to this one.
  const place = useCallback((updated: ApplicationSummary) => {
    const belongsHere = (updated.archived_at !== null) === (viewRef.current === 'archived')
    setApplications(current => {
      if (!Array.isArray(current)) return current
      const others = current.filter(application => application.id !== updated.id)
      return belongsHere ? [...others, updated].sort((a, b) => b.updated_at.localeCompare(a.updated_at)) : others
    })
  }, [])

  if (traveler === undefined) return <section className="dash-page container"><p className="dash-status" role="status">Checking your session…</p></section>
  if (traveler === null) return <section className="dash-page container"><SignedOut /></section>

  return <section className="dash-page container" aria-labelledby="dash-title">
    <div className="dash-head">
      <div>
        <h1 id="dash-title">Your applications</h1>
        <p className="dash-lede">Where each visa application stands, and where to pick up.</p>
      </div>
      <Link to="/apply" className="button button-primary" data-activity-id="application-new">New application</Link>
    </div>

    <div className="dash-tabs" role="group" aria-label="Show">
      {(['active', 'archived'] as const).map(option =>
        <button key={option} type="button" className="dash-tab" aria-pressed={view === option}
          data-activity-id="dashboard-filter" onClick={() => { if (option !== view) { setApplications(null); setView(option) } }}>
          {option === 'active' ? 'Active' : 'Archived'}
        </button>)}
    </div>

    {applications === null && <p className="dash-status" role="status">Loading your applications…</p>}
    {applications instanceof Error && <div className="dash-status" role="alert">
      <p>{applications.message}</p>
      <button type="button" className="button button-secondary dash-small" onClick={() => { setApplications(null); setAttempt(count => count + 1) }}>Try again</button>
    </div>}
    {Array.isArray(applications) && applications.length === 0 && <div className="dash-empty">
      {view === 'active'
        ? <><p>You have no active applications.</p><Link to="/apply" data-activity-id="application-new">Start your first application</Link></>
        : <p>Nothing archived. Applications you archive wait here until you restore or delete them.</p>}
    </div>}
    {Array.isArray(applications) && applications.length > 0 && <ul className="dash-list">
      {applications.map(application => <li key={application.id} className="dash-card">
        <Flag destination={application.destination} />
        <div className="dash-card-body">
          <h2 className="dash-card-title">
            <Link to={`/dashboard/${application.id}`} data-activity-id="application-details">{applicationName(application)}</Link>
          </h2>
          <p className="dash-meta">
            {application.visa_label}
            {application.trip_date && <> · Arriving {formatShortDate(application.trip_date)}</>}
            {application.group_size > 1 && <> · Group of {application.group_size}</>}
          </p>
          <p className="dash-meta">
            <StatusChip application={application} />
            <span className="dash-updated">Last updated <time dateTime={application.updated_at}>{formatDateTime(application.updated_at)}</time></span>
          </p>
        </div>
        <div className="dash-card-side">
          {view === 'active' && <Link to={`/apply/${application.id}`} className="button button-primary dash-small"
            data-activity-id="application-resume" aria-label={`Resume ${applicationName(application)}`}>
            {application.status === 'ANSWERS_COMPLETE' ? 'Review answers' : 'Resume'}
          </Link>}
          <ApplicationActions application={application} onArchiveChange={place} onDeleted={drop} />
        </div>
      </li>)}
    </ul>}
    <p className="dash-disclaimer">{DISCLAIMER}</p>
  </section>
}
