import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { restoreSession, type Traveler } from '../auth'
import { askAssistant, type ChatTurn } from '../assistant/api'
import AnswerInput from '../application/AnswerInput'
import {
  getApplication, getVisaOptions, listApplications, saveAnswer, startApplication,
  type AnswerInput as Answer, type ApplicationState, type ApplicationSummary, type VisaOption,
} from '../application/api'
import { formatAnswer, returnedPassport } from '../application/format'
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

// /apply starts or resumes an application; /apply/:id is the guided chat for one application.
export default function Apply() {
  const { applicationId } = useParams()
  return applicationId ? <ApplicationChat key={applicationId} applicationId={applicationId} /> : <StartApplication />
}

function SignedOut() {
  return <p className="apply-status">Please <Link to={signInPath}>sign in</Link> to start an application.</p>
}

function StartApplication() {
  const navigate = useNavigate()
  const traveler = useTraveler()
  const [options, setOptions] = useState<VisaOption[] | null>(null)
  const [existing, setExisting] = useState<ApplicationSummary[]>([])
  const [starting, setStarting] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => { document.title = 'Start an application | Taasheera' }, [])
  useEffect(() => {
    if (!traveler) return
    let active = true
    Promise.all([getVisaOptions(), listApplications()]).then(([visas, mine]) => {
      if (active) { setOptions(visas); setExisting(mine) }
    }).catch(error => { if (active) setMessage(error instanceof Error ? error.message : 'Could not load this page.') })
    return () => { active = false }
  }, [traveler])

  async function start(option: VisaOption) {
    setStarting(true)
    setMessage('')
    try {
      const application = await startApplication(option)
      navigate(`/apply/${application.id}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not start the application.')
      setStarting(false)
    }
  }

  const drafts = existing.filter(application => application.status !== 'ANSWERS_COMPLETE')
  return <section className="apply-page container" aria-labelledby="apply-heading">
    <header className="passport-intro">
      <p className="badge">New application</p>
      <h1 id="apply-heading">Start a visa application</h1>
      <p>We'll ask the embassy's questions one at a time, in plain language. Every answer is saved as you go, so you can stop and come back.</p>
    </header>
    {traveler === undefined && <p className="apply-status" role="status">Checking your session…</p>}
    {traveler === null && <SignedOut />}
    {traveler && <>
      {drafts.length > 0 && <div className="apply-resume">
        <h2>Pick up where you left off</h2>
        <ul>
          {drafts.map(application => <li key={application.id}>
            <Link to={`/apply/${application.id}`} data-activity-id="application-resume">{application.title}</Link>
            <span>{application.status === 'INELIGIBLE' ? 'Needs a change' : 'In progress'}</span>
          </li>)}
        </ul>
      </div>}
      {options === null && !message && <p className="apply-status" role="status">Loading…</p>}
      {options && <ul className="visa-options">
        {options.map(option => <li key={`${option.destination}-${option.visa_type}`} className="visa-option">
          <h2>{option.title}</h2>
          <p>One application covers all 29 Schengen countries, for stays of up to 90 days.</p>
          <button type="button" className="button button-primary" disabled={starting} onClick={() => void start(option)}
            data-activity-id="application-start">{starting ? 'Starting…' : 'Start this application'}</button>
        </li>)}
      </ul>}
      {message && <p className="passport-message" role="alert">{message}</p>}
    </>}
    <p className="passport-disclaimer">{DISCLAIMER}</p>
  </section>
}

// A question typed to the assistant mid-flow. `at` is how many answers existed when it was
// asked, so it shows at that point in the conversation and the flow carries on below it.
type Aside = ChatTurn & { at: number }

function ApplicationChat({ applicationId }: { applicationId: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const traveler = useTraveler()
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
    if (!traveler) return
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
      if (upload) navigate(location.pathname, { replace: true })
    }).catch(error => {
      if (active) setMessage(error instanceof Error ? error.message : 'Could not load your application.')
    })
    return () => { active = false }
    // Runs once per sign-in: the upload id is consumed by the first load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [traveler, applicationId])

  const currentId = application?.current?.id
  useEffect(() => { current.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }) }, [currentId, asides.length])

  async function answer(questionId: string, input: Answer) {
    const state = await saveAnswer(applicationId, questionId, input)
    setApplication(state)
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
      setAsides(turns => [...turns, { role: 'assistant', content: reply.reply, at }])
    } catch (error) {
      setAsides(turns => turns.slice(0, -1))
      setDraft(question)
      setAskError(error instanceof Error ? error.message : 'The assistant could not answer. Please try again.')
    } finally {
      setAsking(false)
    }
  }
  const askOnEnter = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) void ask(event)
  }

  if (traveler === null) return <section className="apply-page container"><SignedOut /></section>
  if (application === null) {
    return <section className="apply-page container">
      <p className="apply-status">This application could not be found in your account. <Link to="/apply">Start a new one</Link>.</p>
    </section>
  }
  if (!application) {
    return <section className="apply-page container">
      {message ? <p className="passport-message" role="alert">{message}</p>
        : <p className="apply-status" role="status">Loading your application…</p>}
    </section>
  }

  const { progress } = application
  const done = application.status === 'ANSWERS_COMPLETE'
  const asidesAt = (index: number, last = false) => asides
    .filter(turn => last ? turn.at >= index : turn.at === index)
    .map((turn, n) => <li key={`aside-${index}-${n}`} className={`bubble bubble-${turn.role === 'user' ? 'user' : 'assistant'} bubble-aside`}>
      <span className="bubble-label">{turn.role === 'user' ? 'You asked' : 'Assistant'}</span>
      {turn.content}
    </li>)

  return <section className="apply-page container" aria-labelledby="chat-heading">
    <header className="chat-header">
      <p className="badge">{done ? 'All questions answered' : `Step ${progress.step_number} of ${progress.step_count}`}</p>
      <h1 id="chat-heading">{application.title}</h1>
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
      <li className="bubble bubble-assistant">Hi! I'll ask what the embassy needs to know, one question at a time. Your answers are saved as you go.</li>
      {application.answers.map((saved, index) => <li key={saved.question.id} className="chat-turn">
        <ol className="chat-turn-inner">
          {asidesAt(index)}
          <li className="bubble bubble-assistant">{saved.question.prompt}</li>
          {editing === saved.question.id
            ? <li className="chat-answer"><AnswerInput question={saved.question} applicationId={applicationId}
                initial={saved.value} onAnswer={input => answer(saved.question.id, input)} onCancel={() => setEditing(null)} /></li>
            : <li className="bubble bubble-user chat-reply">
                <span>{formatAnswer(saved.question, saved.value)}</span>
                {saved.source === 'passport_upload' && <span className="reply-source">From your confirmed passport</span>}
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
            <AnswerInput key={application.current.id} question={application.current} applicationId={applicationId}
              onAnswer={input => answer(application.current!.id, input)} />
          </li>
        </ol>
      </li>}
      {done && <li ref={current} className="bubble bubble-assistant bubble-done" role="status">
        That's every question for now. Your answers are saved, and you can still change any of them above.
        Next we'll check your documents against these answers.
      </li>}
    </ol>

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

    <p className="passport-disclaimer">{DISCLAIMER}</p>
  </section>
}
