import { useState } from 'react'
import { checkApplication, type CheckReport } from './api'

// The completeness check before submission (US 13). The server decides what is missing or
// inconsistent; this only shows it. Fix links from each issue are US 14 (next sprint).
// The page keys it by the application's last update, so an old report never sits next to new answers.
export default function CompletenessCheck({ applicationId }: { applicationId: string }) {
  const [report, setReport] = useState<CheckReport | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState('')

  async function run() {
    setChecking(true)
    setError('')
    try {
      setReport(await checkApplication(applicationId))
    } catch (failure) {
      setReport(null)
      setError(failure instanceof Error ? failure.message : 'Could not check your application.')
    } finally {
      setChecking(false)
    }
  }

  const blocking = report?.issues.filter(issue => issue.severity === 'blocking') ?? []
  const warnings = report?.issues.filter(issue => issue.severity === 'warning') ?? []
  return <section className="completeness" aria-labelledby="completeness-heading">
    <div className="completeness-head">
      <h2 id="completeness-heading">Check before you submit</h2>
      <button type="button" className="button button-secondary" onClick={run} disabled={checking}
        aria-busy={checking || undefined} data-activity-id="application-check">
        {checking ? 'Checking…' : report ? 'Check again' : 'Check my application'}
      </button>
    </div>
    {error && <p className="answer-error" role="alert">{error}</p>}
    {report && <div role="status">
      <p className={report.ready ? 'completeness-ok' : 'completeness-bad'}>
        {report.ready
          ? warnings.length ? 'Nothing is missing, but have a look at these first.' : 'Nothing is missing. Your answers are ready for review.'
          : `${blocking.length} ${blocking.length === 1 ? 'thing needs' : 'things need'} fixing before you can submit.`}
      </p>
      {report.issues.length > 0 && <ul className="completeness-issues">
        {report.issues.map((issue, index) => <li key={`${issue.question_id}-${index}`}
          className={`completeness-issue is-${issue.severity}`}>
          <span className="completeness-tag">{issue.severity === 'blocking' ? 'Must fix' : 'Check'}</span> {issue.message}
        </li>)}
      </ul>}
    </div>}
  </section>
}
