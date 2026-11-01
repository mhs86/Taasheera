import { ApiError } from '../api'
import { protectedFetch } from '../auth'
import type { AnswerValue, CheckReport } from '../application/api'

export type AssistantStep = 'passport_upload' | 'passport_review' | 'application'
export type ChatTurn = { role: 'user' | 'assistant'; content: string }
// An action the traveler asked the assistant for (US 110), checked by the server but not saved.
// Mirrors backend/app/applications/actions.py.
export type Proposal = {
  action: 'change_answer' | 'go_to_question' | 'check'
  question_id: string | null
  question: string | null
  value: AnswerValue | null
  display: string | null
  current_display: string | null
  report: CheckReport | null
}
export type AssistantReply = { reply: string; used_passport: boolean; proposal?: Proposal | null }

// The server allows ten earlier turns; older ones are dropped, newest kept.
export const MAX_HISTORY = 10

// In the application chat, only the application's id is sent; the server loads its answers itself.
export async function askAssistant(message: string, step: AssistantStep, history: ChatTurn[],
  applicationId?: string): Promise<AssistantReply> {
  let response: Response
  try {
    response = await protectedFetch('/assistant/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message, step, history: history.slice(-MAX_HISTORY),
        ...(applicationId ? { application_id: applicationId } : {}),
      }),
      // The model can take several seconds; the server gives up well before this.
      signal: AbortSignal.timeout(45000),
      silent: true,
    })
  } catch (error) {
    // apiFetch reports any 5xx generically; the assistant explains its own outage.
    if (error instanceof ApiError && error.status !== null) {
      throw new Error("The assistant couldn't answer right now. Please try again in a moment.", { cause: error })
    }
    throw error
  }
  if (!response.ok) {
    const problem = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof problem?.detail === 'string' ? problem.detail : 'The assistant could not answer. Please try again.')
  }
  return await response.json() as AssistantReply
}

// Earlier turns kept by the server (US 111), oldest first. Per application, or outside one when omitted.
export async function getHistory(applicationId?: string): Promise<ChatTurn[]> {
  const query = applicationId ? `?application_id=${applicationId}` : ''
  const response = await protectedFetch(`/assistant/history${query}`, { cache: 'no-store', silent: true })
  if (!response.ok) return []
  return await response.json() as ChatTurn[]
}
