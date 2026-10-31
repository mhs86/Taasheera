// Small pieces the dashboard (US 19) and the application detail page (US 20) share.
import { Link } from 'react-router'
import type { ApplicationSummary } from '../application/api'
import { destinationFlag } from '../application/flags'
import { signInPath } from '../paths'
import { statusCopy } from './helpers'

export function SignedOut() {
  return <p className="dash-status">Please <Link to={signInPath}>sign in</Link> to see your applications.</p>
}

export function Flag({ destination }: { destination: string }) {
  const flag = destinationFlag(destination)
  return flag ? <img src={flag} alt="" className="dash-flag" /> : <span className="dash-flag" aria-hidden="true" />
}

export function StatusChip({ application }: { application: ApplicationSummary }) {
  return <span className={`dash-chip dash-chip-${application.status.toLowerCase()}`}>
    {statusCopy[application.status]}
    {application.status === 'DRAFT' && ` · ${application.answered} of ${application.total}`}
  </span>
}
