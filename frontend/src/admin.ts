import { protectedFetch } from './auth'

export type Staff = { id: number; name: string; email: string; role: 'admin' }
export type AdminUser = { id: number; name: string; email: string; role: string; status: string }
export type UserPage = { items: AdminUser[]; total: number; page: number; page_size: number }
export type Monitoring = {
  applications_by_status: Record<string, number>; total_applications: number
  recent_errors: { id: number; occurred_at: string; event_type: string; source: string; outcome: string }[]
  agent_failures_available: boolean; pending_erasures: number
}

export class AdminAccessError extends Error {}

export async function adminRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await protectedFetch(`/admin${path}`, { ...options, cache: 'no-store', silent: true })
  if ([401, 403].includes(response.status)) throw new AdminAccessError('An active admin account is required. Sign in with an authorized account.')
  if (!response.ok) {
    const messages: Record<number, string> = { 404: 'This user no longer exists. Refresh the list.',
      409: 'This action is unavailable. Admin accounts must transfer their role before deletion, and pending erasures cannot be changed.' }
    throw new Error(messages[response.status] ?? 'Could not complete the admin request. Please try again.')
  }
  if ([202, 204].includes(response.status)) return { pending: response.status === 202 } as T
  return response.json()
}

export function deleteUser(id: number): Promise<{ pending: boolean }> {
  return adminRequest(`/users/${id}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmation: 'DELETE', expected_user_id: id }) })
}
