import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { askAssistant, type AssistantStep, type ChatTurn } from './api'
import '../ui.css'
import './assistant.css'

const suggestions: Record<AssistantStep, string[]> = {
  passport_upload: ['What kind of photo works best?', 'Which page should I photograph?', 'Is my passport kept private?'],
  passport_review: ['When does my passport expire?', 'What is a check digit?', 'Why is a field marked Confirm?'],
}
const MAX_LENGTH = 1000

// The chat lives only in this page: closing the tab forgets it (no history between visits in Sprint 1).
type Props = {
  step: AssistantStep
  // Controlled by the page, so other parts of it (e.g. the confirmation message) can open the chat.
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function AssistantPanel({ step, open, onOpenChange }: Props) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const panelId = useId()
  const launcher = useRef<HTMLButtonElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const log = useRef<HTMLDivElement>(null)

  useEffect(() => { if (open) input.current?.focus() }, [open])
  // Escape closes from anywhere: clicking a suggestion removes it, so focus may have left the panel.
  useEffect(() => {
    if (!open) return
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { onOpenChange(false); launcher.current?.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])
  useEffect(() => { log.current?.scrollTo?.({ top: log.current.scrollHeight }) }, [turns, pending])

  function close() {
    onOpenChange(false)
    launcher.current?.focus()
  }

  async function send(text: string) {
    const message = text.trim()
    if (!message || pending) return
    const history = turns
    setDraft('')
    setError('')
    setPending(true)
    setTurns(current => [...current, { role: 'user', content: message }])
    try {
      const answer = await askAssistant(message, step, history)
      setTurns(current => [...current, { role: 'assistant', content: answer.reply }])
    } catch (problem) {
      // Undo the unsent question and give it back, so retrying is one keypress.
      setTurns(current => current.slice(0, -1))
      setDraft(message)
      setError(problem instanceof Error ? problem.message : 'The assistant could not answer. Please try again.')
    } finally {
      setPending(false)
      input.current?.focus()
    }
  }

  const submit = (event: FormEvent) => { event.preventDefault(); void send(draft) }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void send(draft)
    }
  }

  return <div className="assistant">
    {open && <section id={panelId} className="assistant-panel" aria-labelledby={`${panelId}-title`}>
      <header className="assistant-header">
        <div>
          <h2 id={`${panelId}-title`}>Passport assistant</h2>
          <p>Answers use the details you confirmed. Not legal or immigration advice.</p>
        </div>
        <button type="button" className="assistant-close" onClick={close} aria-label="Close assistant"
          data-activity-id="assistant-close">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9" /></svg>
        </button>
      </header>

      <div className="assistant-log" ref={log} aria-live="polite">
        {turns.length === 0 && <div className="assistant-empty">
          <p>Ask about your passport or this step. For example:</p>
          <ul>
            {suggestions[step].map(question => <li key={question}>
              <button type="button" className="assistant-suggestion" onClick={() => void send(question)}
                disabled={pending} data-activity-id="assistant-suggestion">{question}</button>
            </li>)}
          </ul>
        </div>}
        {turns.map((turn, index) => <div key={index} className={`bubble bubble-${turn.role}`}>
          <span className="visually-hidden">{turn.role === 'user' ? 'You said' : 'Assistant said'}: </span>
          {turn.content}
        </div>)}
        {pending && <div className="bubble bubble-assistant bubble-pending" role="status">
          <span className="typing-dots" aria-hidden="true"><i /><i /><i /></span>
          <span className="visually-hidden">The assistant is answering</span>
        </div>}
      </div>

      <form className="assistant-form" onSubmit={submit}>
        {error && <p className="assistant-error" role="alert">{error}</p>}
        <label htmlFor={`${panelId}-input`} className="visually-hidden">Your question</label>
        <textarea id={`${panelId}-input`} ref={input} rows={2} maxLength={MAX_LENGTH} value={draft}
          placeholder="Ask a question…" onChange={event => setDraft(event.target.value)} onKeyDown={onKeyDown} />
        <button type="submit" className="button button-primary" disabled={pending || !draft.trim()}
          data-activity-id="assistant-send">Send</button>
      </form>
    </section>}

    <button ref={launcher} type="button" className={`assistant-launcher${open ? ' is-open' : ''}`}
      aria-expanded={open} aria-controls={open ? panelId : undefined}
      onClick={() => (open ? close() : onOpenChange(true))} data-activity-id="assistant-open">
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 4.5h12v8H9l-3.5 3v-3H4z" /></svg>
      {open ? 'Close assistant' : 'Ask about your passport'}
    </button>
  </div>
}
