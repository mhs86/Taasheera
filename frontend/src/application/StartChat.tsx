import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { getVisaOptions, startApplication, type ApplicationState, type VisaOption } from './api'
import { destinationFlag } from './flags'

const GROUP_SIZES = [2, 3, 4, 5, 6, 7, 8, 9, 10]

// The opening steps of every application (US 4): where to, which visa, and alone or with others.
// They pick the question file, so they come before the application exists. Answering the last
// one creates it and hands over to that destination's questions.
export default function StartChat({ onStarted }: { onStarted: (application: ApplicationState) => void }) {
  const navigate = useNavigate()
  const [options, setOptions] = useState<VisaOption[] | null>(null)
  const [destination, setDestination] = useState<string | null>(null)
  const [visa, setVisa] = useState<VisaOption | null>(null)
  const [withOthers, setWithOthers] = useState<boolean | null>(null)
  const [starting, setStarting] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    document.title = 'New application | Taasheera'
    let active = true
    getVisaOptions().then(found => { if (active) setOptions(found) })
      .catch(error => { if (active) setMessage(error instanceof Error ? error.message : 'Could not load the visas we can prepare.') })
    return () => { active = false }
  }, [])

  async function start(option: VisaOption, groupSize: number) {
    setStarting(true)
    setMessage('')
    try {
      const application = await startApplication(option, groupSize)
      onStarted(application)
      navigate(`/apply/${application.id}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not start the application.')
      setStarting(false)
    }
  }

  // Changing an earlier step clears the ones after it.
  const chooseDestination = (value: string | null) => { setDestination(value); setVisa(null); setWithOthers(null) }
  const chooseVisa = (value: VisaOption | null) => { setVisa(value); setWithOthers(null) }
  const destinations = [...new Map((options ?? []).map(option => [option.destination, option])).values()]
  const visas = (options ?? []).filter(option => option.destination === destination)
  const chosenDestination = destinations.find(option => option.destination === destination)

  const reply = (text: string, onChange: () => void, label: string) => <li className="bubble bubble-user chat-reply">
    <span>{text}</span>
    {!starting && <button type="button" className="reply-change" onClick={onChange} aria-label={`Change your answer to: ${label}`}
      data-activity-id="application-change">Change</button>}
  </li>

  return <section aria-labelledby="start-heading">
    <header className="chat-header">
      <p className="badge">New application</p>
      <h1 id="start-heading">Start a visa application</h1>
      <p className="chat-lede">A few questions to pick the right embassy form. Every answer after this is saved as you go.</p>
    </header>

    <ol className="chat-log" aria-live="polite">
      <li className="bubble bubble-assistant">Hi! Where are you travelling to?</li>
      {destination === null
        ? options && <li className="chat-answer">
            <div className="answer-choices answer-cards">
              {destinations.map(option => {
                const flag = destinationFlag(option.destination)
                return <button key={option.destination} type="button" className="choice choice-card"
                  onClick={() => chooseDestination(option.destination)} data-activity-id="application-answer">
                  {flag && <img src={flag} alt="" className="apps-flag" />}
                  <span><strong>{option.destination_label}</strong><span>{option.destination_description}</span></span>
                </button>
              })}
            </div>
            <p className="chat-note">More destinations are coming. We add each embassy only once we can prepare its form properly.</p>
          </li>
        : reply(chosenDestination?.destination_label ?? destination, () => chooseDestination(null), 'Where are you travelling to?')}

      {destination !== null && <li className="bubble bubble-assistant">Which visa do you need?</li>}
      {destination !== null && (visa === null
        ? <li className="chat-answer">
            <div className="answer-choices answer-cards">
              {visas.map(option => <button key={option.visa_type} type="button" className="choice choice-card"
                onClick={() => chooseVisa(option)} data-activity-id="application-answer">
                <span><strong>{option.visa_label}</strong><span>{option.visa_description}</span></span>
              </button>)}
            </div>
          </li>
        : reply(visa.visa_label, () => chooseVisa(null), 'Which visa do you need?'))}

      {visa && <li className="bubble bubble-assistant">Are you applying just for yourself, or travelling with family or a group?</li>}
      {visa && withOthers === null && <li className="chat-answer">
        <div className="answer-choices">
          <button type="button" className="choice" disabled={starting} onClick={() => void start(visa, 1)}
            data-activity-id="application-start">Just me</button>
          <button type="button" className="choice" disabled={starting} onClick={() => setWithOthers(true)}
            data-activity-id="application-answer">Family or group</button>
        </div>
      </li>}
      {visa && withOthers && <>
        {reply('Family or group', () => setWithOthers(null), 'Are you applying just for yourself?')}
        <li className="bubble bubble-assistant">
          How many people are travelling, including you?
          <span className="bubble-help">For now I'll prepare your own application. Applications for the others come in a later version.</span>
        </li>
        <li className="chat-answer">
          <div className="answer-choices" role="group" aria-label="How many people are travelling, including you?">
            {GROUP_SIZES.map(size => <button key={size} type="button" className="choice" disabled={starting}
              onClick={() => void start(visa, size)} data-activity-id="application-start">{size}</button>)}
          </div>
        </li>
      </>}
      {starting && <li className="bubble bubble-assistant" role="status">Setting up your application…</li>}
    </ol>
    {options === null && !message && <p className="apply-status" role="status">Loading…</p>}
    {message && <p className="passport-message" role="alert">{message}</p>}
  </section>
}
