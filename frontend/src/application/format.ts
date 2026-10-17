// How answers read back in the chat, and the passport-page round trip.
// Kept free of React so the logic is easy to test and to explain.
import { countries } from '../countries'
import type { PassportFields } from '../passport/fields'
import type { Address, AnswerValue, Question } from './api'

export function countryName(code: string): string {
  return countries.find(country => country.code === code)?.name ?? code
}

export function formatDate(iso: string): string {
  // Parsed and printed in UTC so the day never shifts with the traveler's time zone.
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
    .format(new Date(`${iso}T00:00:00Z`))
}

export function formatAnswer(question: Question, value: AnswerValue): string {
  switch (question.type) {
    case 'choice':
      return question.options?.find(option => option.value === value)?.label ?? String(value)
    case 'yes_no':
      return value ? 'Yes' : 'No'
    case 'date':
      return formatDate(String(value))
    case 'country':
      return countryName(String(value))
    case 'address': {
      const address = value as Address
      return [address.line1, address.line2, address.city, address.region, address.postal_code, countryName(address.country)]
        .filter(Boolean).join(', ')
    }
    case 'passport': {
      const passport = value as PassportFields
      const name = [passport.surname, passport.given_names].filter(Boolean).join(', ')
      const expiry = passport.expiry_date ? ` · expires ${formatDate(passport.expiry_date)}` : ''
      return `${name} · passport ${passport.document_number}${expiry}`
    }
    default:
      return String(value) || 'Nothing to add'
  }
}

const APPLICATION_PATH = /^\/apply\/[0-9a-f]{32}$/
const UPLOAD_ID = /^[0-9a-f]{32}$/

// The passport page links back only to an application page on this site, never to
// whatever a crafted link puts in ?return= (an open redirect).
export function safeReturnPath(search: string): string | null {
  const target = new URLSearchParams(search).get('return')
  return target && APPLICATION_PATH.test(target) ? target : null
}

export function returnedPassport(search: string): string | null {
  const upload = new URLSearchParams(search).get('passport')
  return upload && UPLOAD_ID.test(upload) ? upload : null
}
