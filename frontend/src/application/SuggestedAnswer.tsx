import { useState } from 'react'
import type { AnswerInput as Answer, Question, Suggestion } from './api'
import AnswerInput from './AnswerInput'
import { formatAnswer, sourceLabel } from './format'

type Props = {
  question: Question & { suggestion: Suggestion }
  applicationId: string
  onAnswer: (answer: Answer) => Promise<void>
}

// US 10: a question the saved passport or profile already answers is shown pre-filled, to confirm
// or change, instead of asked again. Changing it here changes this application only.
export default function SuggestedAnswer({ question, applicationId, onAnswer }: Props) {
  const [changing, setChanging] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const { suggestion } = question
  const from = suggestion.source === 'passport' ? 'your saved passport' : 'your profile'

  if (changing) {
    return <div className="answer">
      <p className="chat-note">Changing it here only changes this application, not {from}.</p>
      <AnswerInput question={question} applicationId={applicationId} initial={suggestion.value}
        onAnswer={onAnswer} onCancel={() => setChanging(false)} cancelLabel="Go back" />
    </div>
  }

  async function confirm() {
    setSaving(true)
    setError('')
    try {
      await onAnswer({ use_suggestion: true })
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Could not save your answer.')
      setSaving(false)
    }
  }

  return <div className="answer suggestion">
    <p className="suggestion-label">{sourceLabel(suggestion.source)}</p>
    <p className="suggestion-value">{formatAnswer(question, suggestion.value)}</p>
    <p className="suggestion-ask">Is this still correct?</p>
    <div className="answer-choices">
      <button type="button" className="button button-primary" disabled={saving} aria-busy={saving || undefined}
        onClick={() => void confirm()} data-activity-id="application-use-suggestion">
        {saving ? 'Saving…' : "Yes, that's right"}
      </button>
      <button type="button" className="button button-secondary" disabled={saving} onClick={() => setChanging(true)}
        data-activity-id="application-change-suggestion">Change it</button>
    </div>
    {error && <p className="answer-error" role="alert">{error}</p>}
  </div>
}
