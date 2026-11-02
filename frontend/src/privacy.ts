import { protectedFetch, deleteAccountSession } from './auth'

export type AccessEntry = { id: number; upload_id: string; actor_id: number; accessor: string; purpose: string; occurred_at: string }
export type AccessPage = { items: AccessEntry[]; total: number; page: number; page_size: number }

export async function loadDocumentAccess(page = 1): Promise<AccessPage> {
  const response = await protectedFetch(`/activity/documents?page=${page}`, { silent: true, cache: 'no-store' })
  if (!response.ok) throw new Error('Could not load document access history. Please try again.')
  return response.json()
}

export async function deleteAccount(expectedTravelerId: number, password: string, googleIdToken: string): Promise<boolean> {
  const response = await deleteAccountSession({ confirmation: 'DELETE', expected_traveler_id: expectedTravelerId,
      ...(password ? { password } : {}), ...(googleIdToken ? { google_id_token: googleIdToken } : {}),
  })
  if (response.status === 403) throw new Error('Confirm your current password or connected Google identity.')
  if (response.status === 409) throw new Error('Your account changed or has an admin role. Reload and transfer any admin role before deleting.')
  if (response.status === 429) throw new Error('Too many attempts. Please wait 15 minutes before trying again.')
  if (![202, 204].includes(response.status)) throw new Error('Could not delete your account. Please try again.')
  return response.status === 204
}
