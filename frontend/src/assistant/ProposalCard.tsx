import { useState } from 'react'
import type { Proposal } from './api'

type Props = {
  proposal: Proposal
  // Saves through the normal answer endpoint, which checks the value again.
  onConfirm: () => Promise<void>
  onGoTo: (questionId: string) => void
}

// What the assistant offers to do (US 110). Nothing changes until the traveler presses Confirm:
// the model only proposed it, and the server already checked it against the question's rules.
export default function ProposalCard({ proposal, onConfirm, onGoTo }: Props) {
  const [state, setState] = useState<'open' | 'saving' | 'saved' | 'dismissed'>('open')
  const [error, setError] = useState('')

  async function confirm() {
    setState('saving')
    setError('')
    try {
      await onConfirm()
      setState('saved')
    } catch (failure) {
      setState('open')
      setError(failure instanceof Error ? failure.message : 'Could not save that change.')
    }
  }

  if (proposal.action === 'go_to_question' && proposal.question_id) {
    const questionId = proposal.question_id
    return <div className="proposal">
      <p className="proposal-text">{proposal.question}</p>
      <button type="button" className="button button-secondary" onClick={() => onGoTo(questionId)}
        data-activity-id="assistant-proposal-go">Go to this question</button>
    </div>
  }

  if (proposal.action === 'check' && proposal.report) {
    const { report } = proposal
    return <div className="proposal" role="status">
      <p className="proposal-text">
        {report.ready ? 'Nothing is missing.' : `${report.issues.filter(i => i.severity === 'blocking').length} to fix before you can submit.`}
      </p>
      {report.issues.length > 0 && <ul className="completeness-issues">
        {report.issues.map((issue, index) => <li key={`${issue.question_id}-${index}`} className={`completeness-issue is-${issue.severity}`}>
          <span className="completeness-tag">{issue.severity === 'blocking' ? 'Must fix' : 'Check'}</span> {issue.message}
        </li>)}
      </ul>}
    </div>
  }

  if (proposal.action !== 'change_answer' || !proposal.question_id) return null
  return <div className="proposal" aria-label="Proposed change">
    <p className="proposal-text">Change your answer to “{proposal.question}”</p>
    <p className="proposal-diff">
      {proposal.current_display && <><s>{proposal.current_display}</s> → </>}<strong>{proposal.display}</strong>
    </p>
    {state === 'saved' ? <p className="proposal-done" role="status">Saved.</p>
      : state === 'dismissed' ? <p className="proposal-done" role="status">Left as it was.</p>
      : <div className="proposal-actions">
          <button type="button" className="button" onClick={confirm} disabled={state === 'saving'}
            aria-busy={state === 'saving' || undefined} data-activity-id="assistant-proposal-confirm">
            {state === 'saving' ? 'Saving…' : 'Confirm change'}
          </button>
          <button type="button" className="button button-secondary" onClick={() => setState('dismissed')}
            disabled={state === 'saving'} data-activity-id="assistant-proposal-dismiss">Not now</button>
        </div>}
    {error && <p className="answer-error" role="alert">{error}</p>}
  </div>
}
