import { useState } from 'react'
import { Link } from 'react-router'
import type { ApplicationSummary, Status } from './api'
import { destinationFlag } from './flags'
import { formatShortDate } from './format'

const statusCopy: Record<Status, string> = {
  DRAFT: 'In progress',
  INELIGIBLE: 'Needs a change',
  ANSWERS_COMPLETE: 'Answers complete',
}

type Props = {
  // null while loading.
  applications: ApplicationSummary[] | null
  currentId?: string
}

// Every application the traveler has started, newest activity first (US 12). Each one is
// named by its own answers ("France", arriving 10 Jan), so several trips are easy to tell apart.
export default function ApplicationsSidebar({ applications, currentId }: Props) {
  // Below 900px the list folds away behind a button, so the chat comes first on a phone.
  const [open, setOpen] = useState(false)
  const active = applications?.filter(application => application.status !== 'ANSWERS_COMPLETE') ?? []
  const complete = applications?.filter(application => application.status === 'ANSWERS_COMPLETE') ?? []

  const item = (application: ApplicationSummary) => {
    const flag = destinationFlag(application.destination)
    const when = application.trip_date
      ? `Arriving ${formatShortDate(application.trip_date)}`
      : `Started ${formatShortDate(application.created_at)}`
    return <li key={application.id}>
      <Link to={`/apply/${application.id}`} className="apps-item" onClick={() => setOpen(false)}
        aria-current={application.id === currentId ? 'page' : undefined} data-activity-id="application-resume">
        {flag ? <img src={flag} alt="" className="apps-flag" /> : <span className="apps-flag" aria-hidden="true" />}
        <span className="apps-text">
          <span className="apps-name">{application.place ?? application.destination_label}</span>
          <span className="apps-meta">{when}</span>
          <span className={`apps-status apps-status-${application.status.toLowerCase()}`}>
            {statusCopy[application.status]}
            {application.status === 'DRAFT' && ` · ${application.answered} of ${application.total}`}
          </span>
        </span>
      </Link>
    </li>
  }

  return <aside className={`apps-sidebar${open ? ' is-open' : ''}`} aria-label="Your applications">
    <button type="button" className="apps-toggle" aria-expanded={open} aria-controls="apps-panel"
      onClick={() => setOpen(value => !value)} data-activity-id="applications-toggle">
      Your applications{applications ? ` (${applications.length})` : ''}
    </button>
    <div id="apps-panel" className="apps-panel">
      <Link to="/apply" className="apps-new" onClick={() => setOpen(false)}
        aria-current={currentId ? undefined : 'page'} data-activity-id="application-new">
        <span aria-hidden="true">+</span> New application
      </Link>
      <Link to="/dashboard" className="apps-all" onClick={() => setOpen(false)} data-activity-id="dashboard-link">
        All applications and history
      </Link>
      {applications === null && <p className="apps-empty" role="status">Loading…</p>}
      {applications?.length === 0 && <p className="apps-empty">Applications you start appear here, so you can pick up where you left off. Archived ones are on your dashboard.</p>}
      {active.length > 0 && <>
        <h2 className="apps-heading">In progress</h2>
        <ul className="apps-list">{active.map(item)}</ul>
      </>}
      {complete.length > 0 && <>
        <h2 className="apps-heading">Answers complete</h2>
        <ul className="apps-list">{complete.map(item)}</ul>
      </>}
    </div>
  </aside>
}
