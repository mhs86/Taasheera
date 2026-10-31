// Helpers the dashboard (US 19) and the application detail page (US 20) share.
import { useEffect, useState } from 'react'
import { restoreSession, type Traveler } from '../auth'
import type { ApplicationSummary, Status } from '../application/api'
import { formatShortDate } from '../application/format'

export const DISCLAIMER = 'Taasheera helps prepare applications and does not give legal or immigration advice. Nothing is submitted to an embassy from this page.'

export const statusCopy: Record<Status, string> = {
  DRAFT: 'In progress',
  INELIGIBLE: 'Needs a change',
  ANSWERS_COMPLETE: 'Answers complete',
}

// undefined while the session is being checked, null when signed out.
export function useTraveler() {
  const [traveler, setTraveler] = useState<Traveler | null | undefined>()
  useEffect(() => {
    let active = true
    restoreSession().then(profile => { if (active) setTraveler(profile) })
      .catch(() => { if (active) setTraveler(null) })
    return () => { active = false }
  }, [])
  return traveler
}

// "France", or the destination's name until the traveler has said which country.
export function applicationName(application: ApplicationSummary): string {
  return application.place ?? application.destination_label
}

// Tells several trips to the same country apart, as the sidebar does: "France, arriving 10 Jan 2027".
export function applicationLabel(application: ApplicationSummary): string {
  const when = tripWhen(application)
  return `${applicationName(application)}, ${when[0].toLowerCase()}${when.slice(1)}`
}

export function tripWhen(application: ApplicationSummary): string {
  return application.trip_date
    ? `Arriving ${formatShortDate(application.trip_date)}`
    : `Started ${formatShortDate(application.created_at)}`
}

// A server timestamp in the traveler's own time zone: "31 Oct 2026, 14:05".
export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    .format(new Date(iso))
}
