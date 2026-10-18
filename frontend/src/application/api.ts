import { protectedFetch } from '../auth'
import type { PassportFields } from '../passport/fields'

// Mirrors backend/app/applications/router.py. The server decides which question
// comes next and checks every answer; the page only shows what it is given.
export type AnswerType = 'choice' | 'yes_no' | 'text' | 'date' | 'country' | 'phone' | 'address' | 'passport'
export type Option = { value: string; label: string }
export type Address = { line1: string; line2: string; city: string; region: string; postal_code: string; country: string }
export type AnswerValue = string | boolean | Address | PassportFields

export type Question = {
  id: string
  step_id: string
  type: AnswerType
  prompt: string
  help: string | null
  required: boolean
  options: Option[] | null
  max_length: number
  date_min: string | null
  date_max: string | null
}

export type Answer = { question: Question; value: AnswerValue; source: 'traveler' | 'passport_upload' }
export type Status = 'DRAFT' | 'INELIGIBLE' | 'ANSWERS_COMPLETE'
export type Progress = { step_number: number; step_count: number; step_title: string; answered: number; total: number }

// What the applications sidebar shows (US 12).
export type ApplicationSummary = {
  id: string
  title: string
  destination: string
  visa_type: string
  destination_label: string
  visa_label: string
  status: Status
  group_size: number
  // From the answers that name the trip, once given: "France", "2027-01-10".
  place: string | null
  trip_date: string | null
  answered: number
  total: number
  created_at: string
  updated_at: string
}
export type ApplicationState = ApplicationSummary & {
  steps: { id: string; title: string }[]
  progress: Progress
  answers: Answer[]
  current: Question | null
  stopped: string | null
  cleared: string[]
}
export type VisaOption = {
  destination: string
  visa_type: string
  title: string
  destination_label: string
  destination_description: string
  visa_label: string
  visa_description: string
}

// A rejected answer: the server's message is written for the traveler, so show it as is.
export class AnswerError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'AnswerError'
  }
}

async function detail(response: Response, fallback: string) {
  const problem = await response.json().catch(() => null) as { detail?: unknown } | null
  return typeof problem?.detail === 'string' ? problem.detail : fallback
}

const json = { 'Content-Type': 'application/json' }

export async function getVisaOptions(): Promise<VisaOption[]> {
  const response = await protectedFetch('/applications/options', { cache: 'no-store' })
  if (!response.ok) throw new Error('Could not load the visas we can prepare.')
  return response.json()
}

export async function listApplications(): Promise<ApplicationSummary[]> {
  const response = await protectedFetch('/applications', { cache: 'no-store' })
  if (!response.ok) throw new Error('Could not load your applications.')
  return response.json()
}

export async function startApplication(option: VisaOption, groupSize: number): Promise<ApplicationState> {
  const response = await protectedFetch('/applications', {
    method: 'POST', headers: json, cache: 'no-store',
    body: JSON.stringify({ destination: option.destination, visa_type: option.visa_type, group_size: groupSize }),
  })
  if (!response.ok) throw new Error(await detail(response, 'Could not start the application. Please try again.'))
  return response.json()
}

export async function getApplication(id: string): Promise<ApplicationState | null> {
  const response = await protectedFetch(`/applications/${id}`, { cache: 'no-store' })
  if (response.status === 404) return null
  if (!response.ok) throw new Error('Could not load your application.')
  return response.json()
}

// Either a value, or the id of a passport upload the traveler confirmed on the passport page.
export type AnswerInput = { value: AnswerValue } | { passport_upload_id: string }

export async function saveAnswer(id: string, questionId: string, answer: AnswerInput): Promise<ApplicationState> {
  const response = await protectedFetch(`/applications/${id}/answers/${questionId}`, {
    method: 'PUT', headers: json, cache: 'no-store', silent: true, body: JSON.stringify(answer),
  })
  if (response.status === 422 || response.status === 404 || response.status === 409) {
    throw new AnswerError(await detail(response, 'Check your answer and try again.'))
  }
  if (!response.ok) throw new Error('Could not save your answer. Please try again.')
  return response.json()
}
