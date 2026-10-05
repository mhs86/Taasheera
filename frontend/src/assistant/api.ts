import { ApiError } from '../api'
import { protectedFetch } from '../auth'

export type AssistantStep = 'passport_upload' | 'passport_review'
export type ChatTurn = { role: 'user' | 'assistant'; content: string }
export type AssistantReply = { reply: string; used_passport: boolean }

// The server allows ten earlier turns; older ones are dropped, newest kept.
export const MAX_HISTORY = 10

export async function askAssistant(message: string, step: AssistantStep, history: ChatTurn[]): Promise<AssistantReply> {
  let response: Response
  try {
    response = await protectedFetch('/assistant/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, step, history: history.slice(-MAX_HISTORY) }),
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
