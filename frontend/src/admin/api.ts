import { protectedFetch } from '../auth'

// The dashboard's pages live at /admin, so the browser reaches the backend's /admin API under
// /admin-api (rewritten by Vite locally, and by nginx or Netlify when deployed).
const BASE = '/admin-api'

export const roles = ['traveler', 'support', 'admin'] as const
export const statuses = ['active', 'suspended'] as const
export type Role = typeof roles[number]
export type Status = typeof statuses[number]

export type AdminProfile = { id: number; name: string; email: string; role: Role }

export type AdminUserSummary = {
  id: number
  name: string
  email: string
  auth_type: 'email_password' | 'google'
  role: Role
  status: Status
  created_at: string | null
  last_sign_in_at: string | null
}

export type AdminUserDetail = AdminUserSummary & {
  sso_email: string | null
  password_enabled: boolean
  google_linked: boolean
  last_sign_in_method: string | null
  counts: { active_sessions: number; sign_ins: number; failed_sign_ins: number; passport_uploads: number }
}

export type AdminUserPage = { items: AdminUserSummary[]; total: number; page: number; page_size: number }

export type AdminOverview = {
  total_users: number
  new_last_7_days: number
  suspended: number
  applications_started: number | null
}

export type UserSearch = { q?: string; role?: Role | ''; status?: Status | ''; page?: number }

export const PAGE_SIZE = 20
export const ADMIN_REQUIRED = 'Admin access required.'

// `status` is null when the request never got an answer (offline, signed out, server error).
export class AdminRequestError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'AdminRequestError'
    this.status = status
  }
}

async function adminRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    // silent: each page shows its own message, so the shared error toast would repeat it.
    response = await protectedFetch(`${BASE}${path}`, { ...options, cache: 'no-store', silent: true })
  } catch (error) {
    throw new AdminRequestError(error instanceof Error ? error.message : 'Could not reach Taasheera.', null)
  }
  if (response.ok) return await response.json() as T
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null
  // The API's own wording for 404 and 409 ("You can't suspend your own account.") is written for people.
  const detail = typeof payload?.detail === 'string' ? payload.detail : null
  const fallback = response.status === 403 ? ADMIN_REQUIRED
    : response.status === 422 ? 'That request was not valid. Check the filters and try again.'
      : 'Something went wrong. Please try again.'
  throw new AdminRequestError(detail ?? fallback, response.status)
}

function json(method: string, body?: unknown): RequestInit {
  return body === undefined ? { method } : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }
}

export function getAdminMe() {
  return adminRequest<AdminProfile>('/me')
}

export function getOverview() {
  return adminRequest<AdminOverview>('/overview')
}

export function searchUsers({ q = '', role = '', status = '', page = 1 }: UserSearch) {
  const params = new URLSearchParams()
  if (q.trim()) params.set('q', q.trim())
  if (role) params.set('role', role)
  if (status) params.set('status', status)
  params.set('page', String(page))
  params.set('page_size', String(PAGE_SIZE))
  return adminRequest<AdminUserPage>(`/users?${params}`)
}

export function getUser(id: number) {
  return adminRequest<AdminUserDetail>(`/users/${id}`)
}

export function suspendUser(id: number) {
  return adminRequest<AdminUserDetail>(`/users/${id}/suspend`, json('POST'))
}

export function reactivateUser(id: number) {
  return adminRequest<AdminUserDetail>(`/users/${id}/reactivate`, json('POST'))
}

export function changeRole(id: number, role: Role) {
  return adminRequest<AdminUserDetail>(`/users/${id}/role`, json('PUT', { role }))
}
