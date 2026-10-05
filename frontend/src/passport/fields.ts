// Passport review data and the rules for how much to trust each field.
// Kept free of React so the logic is easy to test and to explain.

export type PassportFields = {
  surname: string
  given_names: string
  document_number: string
  nationality: string
  issuing_country: string
  birth_date: string | null
  sex: 'M' | 'F' | 'X'
  expiry_date: string | null
  personal_number: string
}
export type FieldKey = keyof PassportFields

export type Extraction = {
  status: 'verified' | 'needs_review' | 'unreadable'
  fields: PassportFields | null
  suspect_fields: string[]
  corrected_fields: string[]
  unverifiable_fields: string[]
  checks: Record<string, boolean>
}

export const blankFields: PassportFields = {
  surname: '', given_names: '', document_number: '', nationality: '', issuing_country: '',
  birth_date: null, sex: 'X', expiry_date: null, personal_number: '',
}

type FieldSpec = {
  key: FieldKey
  label: string
  kind: 'name' | 'code' | 'date' | 'sex'
  maxLength?: number
  wide?: boolean
  help?: string
}

export const fieldSpecs: FieldSpec[] = [
  { key: 'surname', label: 'Surname', kind: 'name', maxLength: 100, wide: true },
  { key: 'given_names', label: 'Given names', kind: 'name', maxLength: 100, wide: true,
    help: 'Leave empty if your passport shows no given names.' },
  { key: 'document_number', label: 'Passport number', kind: 'code', maxLength: 30 },
  { key: 'personal_number', label: 'Personal number', kind: 'code', maxLength: 30,
    help: 'Not every passport has one. Leave empty if yours does not.' },
  { key: 'nationality', label: 'Nationality code', kind: 'code', maxLength: 3, help: 'Three letters, e.g. LBN.' },
  { key: 'issuing_country', label: 'Issuing country code', kind: 'code', maxLength: 3 },
  { key: 'birth_date', label: 'Date of birth', kind: 'date' },
  { key: 'expiry_date', label: 'Expiry date', kind: 'date' },
  { key: 'sex', label: 'Sex', kind: 'sex' },
]

// How much a field can be trusted, strongest signal first. A value the traveler
// typed themselves is "edited": whatever the machine checked no longer applies.
export type Trust = 'edited' | 'failed' | 'corrected' | 'verified' | 'confirm'

export const trustCopy: Record<Trust, { label: string; detail: string }> = {
  failed: { label: 'Check failed', detail: 'The check digit for this field did not match. Compare it with your passport.' },
  corrected: { label: 'Auto-corrected', detail: 'A misread character was fixed using the check digit. Glance at it to be sure.' },
  verified: { label: 'Passed check', detail: 'This field passed its check digit.' },
  confirm: { label: 'Confirm', detail: "This field has no check digit, so it can't be verified automatically." },
  edited: { label: 'Edited', detail: 'You changed this value.' },
}

export function fieldTrust(key: FieldKey, extraction: Extraction | null, edited: ReadonlySet<FieldKey>): Trust | null {
  if (edited.has(key)) return 'edited'
  if (!extraction?.fields) return null
  if (extraction.suspect_fields.includes(key)) return 'failed'
  if (extraction.corrected_fields.includes(key)) return 'corrected'
  if (extraction.checks[key]) return 'verified'
  if (extraction.unverifiable_fields.includes(key)) return 'confirm'
  return null
}

const CODE = /^[A-Z<]{1,3}$/
const DOCUMENT = /^[A-Z0-9<]{1,30}$/

// The same limits the API enforces, checked first so mistakes show next to the field.
export function validateFields(fields: PassportFields, today = new Date()): Partial<Record<FieldKey, string>> {
  const errors: Partial<Record<FieldKey, string>> = {}
  const todayIso = today.toISOString().slice(0, 10)
  if (!fields.surname.trim()) errors.surname = 'Enter your surname as it appears on your passport.'
  if (!DOCUMENT.test(fields.document_number)) errors.document_number = 'Use only the letters and numbers of your passport number.'
  if (fields.personal_number && !DOCUMENT.test(fields.personal_number)) errors.personal_number = 'Use only letters and numbers.'
  if (!CODE.test(fields.nationality)) errors.nationality = 'Enter the country code of up to three letters, e.g. LBN.'
  if (!CODE.test(fields.issuing_country)) errors.issuing_country = 'Enter the country code of up to three letters, e.g. LBN.'
  if (fields.birth_date && fields.birth_date > todayIso) errors.birth_date = "Date of birth can't be in the future."
  if (fields.birth_date && fields.expiry_date && fields.expiry_date <= fields.birth_date) {
    errors.expiry_date = 'Expiry date must be after your date of birth.'
  }
  return errors
}

// Codes and numbers are stored the way the passport prints them: upper case, no spaces.
export function normalizeValue(key: FieldKey, value: string): string {
  const spec = fieldSpecs.find(field => field.key === key)
  return spec?.kind === 'code' ? value.toUpperCase().replace(/\s+/g, '') : value
}
