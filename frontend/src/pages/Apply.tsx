import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { restoreSession, type Traveler } from '../auth'
import { askAssistant, getHistory, type ChatTurn, type Proposal } from '../assistant/api'
import ProposalCard from '../assistant/ProposalCard'
import AnswerInput from '../application/AnswerInput'
import ApplicationsSidebar from '../application/ApplicationsSidebar'
import CompletenessCheck from '../application/CompletenessCheck'
import StartChat from '../application/StartChat'
import SuggestedAnswer from '../application/SuggestedAnswer'
import {
  getApplication, listApplications, saveAnswer,
  type AnswerInput as Answer, type ApplicationState, type ApplicationSummary,
} from '../application/api'
import { formatAnswer, formatDate, returnedPassport, sourceLabel, travellers } from '../application/format'
import { signInPath } from '../paths'
import '../ui.css'
import '../assistant/assistant.css'
import './passport.css'
import './apply.css'

const DISCLAIMER = 'Taasheera helps prepare applications and does not give legal or immigration advice. Nothing is submitted to an embassy from this page.'

function useTraveler() {
  const [traveler, setTraveler] = useState<Traveler | null | undefined>()
  useEffect(() => {
    let active = true
    restoreSession().then(profile => { if (active) setTraveler(profile) })
      .catch(() => { if (active) setTraveler(null) })
    return () => { active = false }
  }, [])
  return traveler
}

// The application workspace: every application in a sidebar (US 12), and beside it either the
// opening questions for a new one (/apply, US 4) or the guided chat for one application (/apply/:id).
export default function Apply() {
  const { applicationId } = useParams()
  const traveler = useTraveler()
  const [applications, setApplications] = useState<ApplicationSummary[] | null>(null)

  useEffect(() => {
    if (!traveler) return
    let active = true
    // The chat may have loaded its application first; keep that fresher copy.
    listApplications().then(found => { if (active) setApplications(current => merge(found, current ?? [])) })
      .catch(() => { if (active) setApplications(current => current ?? []) })
    return () => { active = false }
  }, [traveler])

  // Every answer returns the application's new state, which includes its summary, so the
  // sidebar updates from that instead of asking the server for the whole list again.
  const update = useCallback((state: ApplicationState) => {
    setApplications(current => merge(current ?? [], [state]))
  }, [])

  if (traveler === undefined) return <section className="apply-page container"><p className="apply-status" role="status">Checking your session…</p></section>
  if (traveler === null) return <section className="apply-page container"><SignedOut /></section>
  return <div className="workspace container">
    <ApplicationsSidebar applications={applications} currentId={applicationId} />
    <div className="workspace-main">
      {applicationId
        ? <ApplicationChat key={applicationId} applicationId={applicationId} onChange={update} />
        : <StartChat onStarted={update} />}
      <p className="passport-disclaimer">{DISCLAIMER}</p>
    </div>
  </div>
}

// Combine two lists of summaries; for the same application, the one in `newer` wins.
function merge(older: ApplicationSummary[], newer: ApplicationSummary[]): ApplicationSummary[] {
  const byId = new Map(older.map(application => [application.id, application]))
  for (const application of newer) byId.set(application.id, application)
  return [...byId.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

function SignedOut() {
  return <p className="apply-status">Please <Link to={signInPath}>sign in</Link> to start an application.</p>
}

// A question typed to the assistant mid-flow. `at` is how many answers existed when it was
// asked, so it shows at that point in the conversation and the flow carries on below it.
// An assistant reply may carry an action for the traveler to confirm (US 110).
type Aside = ChatTurn & { at: number; proposal?: Proposal | null }

type ChatProps = { applicationId: string; onChange: (state: ApplicationState) => void }

function ApplicationChat({ applicationId, onChange }: ChatProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const [application, setApplication] = useState<ApplicationState | null | undefined>()
  const [editing, setEditing] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [handoffError, setHandoffError] = useState('')
  const [message, setMessage] = useState('')
  const [asides, setAsides] = useState<Aside[]>([])
  const [draft, setDraft] = useState('')
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState('')
  const current = useRef<HTMLLIElement>(null)
  const upload = returnedPassport(location.search)

  useEffect(() => { document.title = 'Your application | Taasheera' }, [])

  // Load the application. Coming back from the passport page with ?passport=<upload>,
  // that confirmed passport answers the passport question, then the link is tidied away.
  useEffect(() => {
    let active = true
    getApplication(applicationId).then(async state => {
      if (!active) return
      if (state && upload && state.current?.type === 'passport') {
        try {
          state = await saveAnswer(applicationId, state.current.id, { passport_upload_id: upload })
        } catch (error) {
          if (active) setHandoffError(error instanceof Error ? error.message : 'Could not use that passport.')
        }
      }
      if (!active) return
      setApplication(state)
      if (state) {
        onChange(state)
        // The conversation from earlier visits (US 111) picks up where the traveler is now.
        const at = state.answers.length
        getHistory(applicationId).then(turns => {
          if (active && turns.length) setAsides(current => [...turns.map(turn => ({ ...turn, at })), ...current])
        }).catch(() => { /* No history is just a fresh chat. */ })
      }
      if (upload) navigate(location.pathname, { replace: true })
    }).catch(error => {
      if (active) setMessage(error instanceof Error ? error.message : 'Could not load your application.')
    })
    return () => { active = false }
    // Runs once per application: the upload id is consumed by the first load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId])

  const currentId = application?.current?.id
  useEffect(() => { current.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }) }, [currentId, asides.length])

  async function answer(questionId: string, input: Answer) {
    const state = await saveAnswer(applicationId, questionId, input)
    setApplication(state)
    onChange(state)
    setEditing(null)
    setHandoffError('')
    setNotice(state.cleared.length
      ? `Because of that change, ${state.cleared.length === 1 ? 'one later answer no longer fits' : `${state.cleared.length} later answers no longer fit`}. I'll ask again below.`
      : '')
  }

  async function ask(event?: { preventDefault(): void }) {
    event?.preventDefault()
    const question = draft.trim()
    if (!question || asking || !application) return
    const at = application.answers.length
    const history = asides.map(({ role, content }) => ({ role, content }))
    setDraft('')
    setAskError('')
    setAsking(true)
    setAsides(turns => [...turns, { role: 'user', content: question, at }])
    try {
      const reply = await askAssistant(question, 'application', history, applicationId)
      setAsides(turns => [...turns, { role: 'assistant', content: reply.reply, at, proposal: reply.proposal }])
    } catch (error) {
      setAsides(turns => turns.slice(0, -1))
      setDraft(question)
      setAskError(error instanceof Error ? error.message : 'The assistant could not answer. Please try again.')
    } finally {
      setAsking(false)
    }
  }
  // The assistant offered to take the traveler to a question: open an answered one for changing.
  function goTo(questionId: string) {
    if (questionId === application?.current?.id) {
      current.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
      return
    }
    setEditing(questionId)
    document.getElementById(`answer-${questionId}`)?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }
  const askOnEnter = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) void ask(event)
  }

  if (application === null) {
    return <p className="apply-status">This application could not be found in your account. <Link to="/apply">Start a new one</Link>.</p>
  }
  if (!application) {
    return message ? <p className="passport-message" role="alert">{message}</p>
      : <p className="apply-status" role="status">Loading your application…</p>
  }

  const { progress } = application
  const done = application.status === 'ANSWERS_COMPLETE'
  const asidesAt = (index: number, last = false) => asides
    .filter(turn => last ? turn.at >= index : turn.at === index)
    .map((turn, n) => <li key={`aside-${index}-${n}`} className={`bubble bubble-${turn.role === 'user' ? 'user' : 'assistant'} bubble-aside`}>
      <span className="bubble-label">{turn.role === 'user' ? 'You asked' : 'Assistant'}</span>
      {turn.content}
      {turn.proposal && <ProposalCard proposal={turn.proposal} onGoTo={goTo}
        onConfirm={() => answer(turn.proposal!.question_id!, { value: turn.proposal!.value! })} />}
    </li>)

  const trip = [application.place, application.trip_date && `arriving ${formatDate(application.trip_date)}`]
    .filter(Boolean).join(' · ')
  return <section aria-labelledby="chat-heading">
    <header className="chat-header">
      <p className="badge">{done ? 'All questions answered' : `Step ${progress.step_number} of ${progress.step_count}`}</p>
      <h1 id="chat-heading">{application.title}</h1>
      {trip && <p className="chat-lede">{trip}</p>}
      <ol className="chat-steps" aria-label="Steps">
        {application.steps.map((step, index) => {
          const state = done || index + 1 < progress.step_number ? 'is-done' : index + 1 === progress.step_number ? 'is-current' : ''
          return <li key={step.id} className={state || undefined} aria-current={state === 'is-current' ? 'step' : undefined}>
            {step.title}
          </li>
        })}
      </ol>
      <div className="chat-progress">
        <progress value={progress.answered} max={progress.total} aria-label="Questions answered" />
        <span>{progress.answered} of {progress.total} questions answered</span>
      </div>
    </header>

    <ol className="chat-log" aria-live="polite">
      {/* The opening steps (US 4) chose this question file, so they can't change here: a new
          destination or visa means a new application. */}
      <li className="bubble bubble-assistant">Where are you travelling to?</li>
      <li className="bubble bubble-user chat-reply chat-fixed">{application.destination_label}</li>
      <li className="bubble bubble-assistant">Which visa do you need?</li>
      <li className="bubble bubble-user chat-reply chat-fixed">{application.visa_label}</li>
      <li className="bubble bubble-assistant">Are you applying just for yourself, or travelling with family or a group?</li>
      <li className="bubble bubble-user chat-reply chat-fixed">{travellers(application.group_size)}</li>
      <li className="bubble bubble-assistant">Great. Now the embassy's questions, one at a time. Your answers are saved as you go.</li>
      {application.answers.map((saved, index) => <li key={saved.question.id} id={`answer-${saved.question.id}`} className="chat-turn">
        <ol className="chat-turn-inner">
          {asidesAt(index)}
          <li className="bubble bubble-assistant">{saved.question.prompt}</li>
          {editing === saved.question.id
            ? <li className="chat-answer"><AnswerInput question={saved.question} applicationId={applicationId}
                initial={saved.value} onAnswer={input => answer(saved.question.id, input)} onCancel={() => setEditing(null)} /></li>
            : <li className="bubble bubble-user chat-reply">
                <span>{formatAnswer(saved.question, saved.value)}</span>
                {sourceLabel(saved.source) && <span className="reply-source">{sourceLabel(saved.source)}</span>}
                <button type="button" className="reply-change" onClick={() => setEditing(saved.question.id)}
                  aria-label={`Change your answer to: ${saved.question.prompt}`} data-activity-id="application-change">Change</button>
              </li>}
        </ol>
      </li>)}
      {asidesAt(application.answers.length, true)}
      {notice && <li className="bubble bubble-assistant bubble-notice">{notice}</li>}
      {application.stopped && <li className="bubble bubble-assistant bubble-stop" role="status">
        {application.stopped} If that's not right, change your answer above.
      </li>}
      {application.current && <li ref={current} className="chat-turn" id="current-question">
        <ol className="chat-turn-inner">
          <li className="bubble bubble-assistant">
            {application.current.prompt}
            {application.current.help && <span className="bubble-help">{application.current.help}</span>}
          </li>
          <li className="chat-answer">
            {handoffError && <p className="answer-error" role="alert">{handoffError}</p>}
            {application.current.suggestion
              ? <SuggestedAnswer key={application.current.id}
                  question={{ ...application.current, suggestion: application.current.suggestion }}
                  applicationId={applicationId} onAnswer={input => answer(application.current!.id, input)} />
              : <AnswerInput key={application.current.id} question={application.current} applicationId={applicationId}
                  onAnswer={input => answer(application.current!.id, input)} />}
          </li>
        </ol>
      </li>}
      {done && <li ref={current} className="bubble bubble-assistant bubble-done" role="status">
        That's every question for now. Your answers are saved, and you can still change any of them above.
        Next we'll check your documents against these answers.
      </li>}
    </ol>

    {!application.stopped && <CompletenessCheck key={application.updated_at} applicationId={applicationId} />}

    <form className="chat-ask" onSubmit={ask}>
      <label htmlFor="chat-ask-input">Not sure about something? Ask the assistant. Your place in the questions is kept.</label>
      <div className="answer-row">
        <textarea id="chat-ask-input" rows={1} maxLength={1000} value={draft} placeholder="Ask a question…"
          onChange={event => setDraft(event.target.value)} onKeyDown={askOnEnter} />
        <button type="submit" className="button button-secondary" disabled={asking || !draft.trim()}
          aria-busy={asking || undefined} data-activity-id="application-ask">{asking ? 'Asking…' : 'Ask'}</button>
      </div>
      {askError && <p className="answer-error" role="alert">{askError}</p>}
    </form>
  </section>
}
