import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { getApplication, getTimeline, type ApplicationState, type Timeline, type TimelineEvent } from '../application/api'
import { formatAnswer, formatShortDate, sourceLabel, travellers } from '../application/format'
import ApplicationActions from './ApplicationActions'
import { applicationName, DISCLAIMER, formatDateTime, useTraveler } from './helpers'
import { Flag, SignedOut, StatusChip } from './shared'
import '../ui.css'
import './dashboard.css'

type Loaded = { application: ApplicationState; timeline: Timeline }

// One application: where it stands, what comes next, the answers so far and when things happened (US 20).
// Keyed by id, so moving to another application starts from a blank page instead of the old one.
export default function ApplicationDetail() {
  const { applicationId = '' } = useParams()
  return <Detail key={applicationId} applicationId={applicationId} />
}

function Detail({ applicationId }: { applicationId: string }) {
  const navigate = useNavigate()
  const traveler = useTraveler()
  // null while loading, 'missing' for an id that isn't the traveler's, an Error when loading failed.
  const [loaded, setLoaded] = useState<Loaded | 'missing' | Error | null>(null)
  const [attempt, setAttempt] = useState(0)

  const name = loaded && typeof loaded === 'object' && !(loaded instanceof Error) ? applicationName(loaded.application) : null
  useEffect(() => { document.title = `${name ?? 'Your application'} | Taasheera` }, [name])

  useEffect(() => {
    if (!traveler) return
    let active = true
    // The application first: reading it re-checks the answers, so the timeline then matches it.
    getApplication(applicationId)
      .then(async application => {
        const timeline = application ? await getTimeline(applicationId) : null
        if (active) setLoaded(application && timeline ? { application, timeline } : 'missing')
      })
      .catch(() => { if (active) setLoaded(new Error('Could not load this application.')) })
    return () => { active = false }
  }, [traveler, applicationId, attempt])

  if (traveler === undefined) return <section className="dash-page container"><p className="dash-status" role="status">Checking your session…</p></section>
  if (traveler === null) return <section className="dash-page container"><SignedOut /></section>

  const back = <Link to="/dashboard" className="dash-back" data-activity-id="dashboard-link">← All applications</Link>
  if (loaded === null) return <section className="dash-page container">{back}<p className="dash-status" role="status">Loading the application…</p></section>
  if (loaded === 'missing') return <section className="dash-page container">{back}
    <h1>Application not found</h1>
    <p className="dash-status">It may have been deleted, or the link is for another account.</p>
  </section>
  if (loaded instanceof Error) return <section className="dash-page container">{back}
    <div className="dash-status" role="alert">
      <p>{loaded.message}</p>
      <button type="button" className="button button-secondary dash-small" onClick={() => { setLoaded(null); setAttempt(count => count + 1) }}>Try again</button>
    </div>
  </section>

  const { application, timeline } = loaded
  const archived = application.archived_at !== null
  const byStep = application.steps
    .map(step => ({ step, answers: application.answers.filter(answer => answer.question.step_id === step.id) }))
    .filter(group => group.answers.length > 0)

  return <section className="dash-page container" aria-labelledby="detail-title">
    {back}
    <div className="dash-detail-head">
      <Flag destination={application.destination} />
      <div>
        <h1 id="detail-title">{applicationName(application)}</h1>
        <p className="dash-meta">
          {application.title} · {travellers(application.group_size)}
          {application.trip_date && <> · Arriving {formatShortDate(application.trip_date)}</>}
        </p>
        <p className="dash-meta">
          <StatusChip application={application} />
          {archived && <span className="dash-chip dash-chip-archived">Archived</span>}
        </p>
      </div>
    </div>

    <div className={`dash-next dash-next-${timeline.next.kind}`}>
      <h2>What happens next</h2>
      <p>{timeline.next.text}</p>
      <div className="dash-next-actions">
        {!archived && <Link to={`/apply/${application.id}`} className="button button-primary dash-small" data-activity-id="application-resume">
          {timeline.next.kind === 'complete' ? 'Review answers' : timeline.next.kind === 'change' ? 'Change an answer' : 'Resume'}
        </Link>}
        <ApplicationActions application={application}
          // The timeline gains or loses its "Archived" entry, so load both again.
          onArchiveChange={() => setAttempt(count => count + 1)}
          onDeleted={() => navigate('/dashboard', { replace: true })} />
      </div>
    </div>

    <div className="dash-detail-grid">
      <section aria-labelledby="answers-title">
        <h2 id="answers-title">Your answers</h2>
        {byStep.length === 0 && <p className="dash-status">No answers yet.</p>}
        {byStep.map(({ step, answers }) => <div key={step.id} className="dash-step">
          <h3>{step.title}</h3>
          <dl className="dash-answers">
            {answers.map(answer => <div key={answer.question.id}>
              <dt>{answer.question.prompt}</dt>
              <dd>
                {formatAnswer(answer.question, answer.value)}
                {sourceLabel(answer.source) && <span className="dash-source">{sourceLabel(answer.source)}</span>}
              </dd>
            </div>)}
          </dl>
        </div>)}
      </section>

      <section aria-labelledby="timeline-title">
        <h2 id="timeline-title">Timeline</h2>
        <ol className="dash-timeline">
          {group(timeline.events).map(item => <li key={item.key} className={`dash-event dash-event-${item.kind}`}>
            <time dateTime={item.at}>{formatDateTime(item.at)}</time>
            {item.kind === 'answered'
              ? <details>
                  <summary>Answered {item.prompts.length === 1 ? '1 question' : `${item.prompts.length} questions`}
                    {item.step && <> · {item.step}</>}</summary>
                  <ul>{item.prompts.map(prompt => <li key={prompt}>{prompt}</li>)}</ul>
                </details>
              : <span>{item.text}</span>}
          </li>)}
        </ol>
        <p className="dash-note">A changed answer shows at the time it was last saved.</p>
      </section>
    </div>
    <p className="dash-disclaimer">{DISCLAIMER}</p>
  </section>
}

type Item =
  | { key: string; kind: 'answered'; at: string; step: string | null; prompts: string[] }
  | { key: string; kind: Exclude<TimelineEvent['kind'], 'answered'>; at: string; text: string }

// Answers given one after another in the same step read as one entry, timed at the latest of them.
function group(events: TimelineEvent[]): Item[] {
  const items: Item[] = []
  events.forEach((event, index) => {
    const last = items.at(-1)
    if (event.kind === 'answered' && last?.kind === 'answered' && last.step === event.step_title) {
      last.prompts.push(event.text)
      last.at = event.at
    } else if (event.kind === 'answered') {
      items.push({ key: `answered-${index}`, kind: 'answered', at: event.at, step: event.step_title, prompts: [event.text] })
    } else {
      items.push({ key: `${event.kind}-${index}`, kind: event.kind, at: event.at, text: event.text })
    }
  })
  return items
}
