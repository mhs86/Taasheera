import type { Role, Status } from './api'

export const roleLabels: Record<Role, string> = { traveler: 'Traveler', support: 'Support', admin: 'Admin' }
export const statusLabels: Record<Status, string> = { active: 'Active', suspended: 'Suspended' }

export function readableDate(value: string | null, withTime = true): string {
  if (!value) return 'Unknown'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown'
  return new Intl.DateTimeFormat(undefined, withTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' })
    .format(date)
}

export function signInMethod(value: string | null): string {
  return value === 'google' ? 'Google' : value === 'email_password' ? 'Email and password' : 'Unknown'
}
