import { useEffect, useState, type FormEvent } from 'react'
import { countries } from './countries'
import { getTravelerProfile, putTravelerProfile, ProfileValidationError,
  type ProfileField, type TravelerProfile } from './auth'

const emptyProfile: TravelerProfile = {
  surname: null, given_names: null, birth_date: null, nationality: null, phone: null,
  address_line1: null, address_line2: null, address_city: null, address_region: null,
  address_postal_code: null, address_country: null,
}

const textFields: Array<{ key: ProfileField; label: string; autoComplete?: string; maxLength?: number }> = [
  { key: 'surname', label: 'Surname', autoComplete: 'family-name', maxLength: 100 },
  { key: 'given_names', label: 'Given names', autoComplete: 'given-name', maxLength: 100 },
  { key: 'phone', label: 'Phone', autoComplete: 'tel' },
  { key: 'address_line1', label: 'Address line 1', autoComplete: 'address-line1' },
  { key: 'address_line2', label: 'Address line 2', autoComplete: 'address-line2' },
  { key: 'address_city', label: 'City', autoComplete: 'address-level2' },
  { key: 'address_region', label: 'Region or state', autoComplete: 'address-level1' },
  { key: 'address_postal_code', label: 'Postal code', autoComplete: 'postal-code' },
]

function todayIso() {
  const today = new Date()
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
}

function yesterdayIso() {
  const yesterday = new Date()
  yesterday.setDate(yesterday.getDate() - 1)
  return `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`
}

export default function ProfileForm() {
  const [fields, setFields] = useState<TravelerProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [generalError, setGeneralError] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<ProfileField, string>>>({})
  const [success, setSuccess] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let active = true
    getTravelerProfile().then(profile => {
      if (active) { setFields(profile); setLoadError('') }
    }).catch(cause => {
      if (active) setLoadError(cause instanceof Error ? cause.message : 'Could not load your profile. Please try again.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [retry])

  function update(key: ProfileField, value: string) {
    setFields(previous => ({ ...(previous ?? emptyProfile), [key]: value }))
    setFieldErrors(previous => ({ ...previous, [key]: undefined }))
    setGeneralError('')
    setSuccess('')
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!fields || saving) return
    if (fields.birth_date && fields.birth_date >= todayIso()) {
      setFieldErrors({ birth_date: 'Birth date must be in the past.' })
      setGeneralError('Please correct the highlighted fields.')
      return
    }
    const replacement: TravelerProfile = {
      ...fields,
      surname: fields.surname?.trim() || null,
      birth_date: fields.birth_date || null,
      nationality: fields.nationality || null,
      address_country: fields.address_country || null,
      phone: fields.phone?.trim() || null,
    }
    setSaving(true)
    setFieldErrors({})
    setGeneralError('')
    setSuccess('')
    try {
      const saved = await putTravelerProfile(replacement)
      setFields(saved)
      setSuccess('Profile saved.')
    } catch (cause) {
      if (cause instanceof ProfileValidationError) {
        setFieldErrors(cause.fields)
        setGeneralError(cause.message)
      } else {
        setGeneralError(cause instanceof Error ? cause.message : 'Could not save your profile. Please try again.')
      }
    } finally {
      setSaving(false)
    }
  }

  function fieldError(key: ProfileField) {
    return fieldErrors[key] && <p className="profile-field-error" id={`profile-${key}-error`} role="alert">{fieldErrors[key]}</p>
  }

  function countrySelect(key: 'nationality' | 'address_country', label: string) {
    const value = fields?.[key] ?? ''
    return <div className="profile-field" key={key}>
      <label htmlFor={`profile-${key}`}>{label}</label>
      <select id={`profile-${key}`} name={key} autoComplete={key === 'address_country' ? 'country' : undefined}
        value={value} disabled={saving} aria-invalid={Boolean(fieldErrors[key])}
        aria-describedby={fieldErrors[key] ? `profile-${key}-error` : undefined}
        onChange={event => update(key, event.target.value)}>
        <option value="">Select a country</option>
        {value && !countries.some(country => country.code === value) &&
          <option value={value}>Previously saved code ({value})</option>}
        {countries.map(country => <option key={country.code} value={country.code}>{country.name}</option>)}
      </select>
      {fieldError(key)}
    </div>
  }

  return <section className="profile-section" aria-labelledby="profile-heading">
    <h2 id="profile-heading">Traveler profile</h2>
    <p className="profile-help">All fields are optional. Use the details shown on your passport when you add them.</p>
    {loading ? <p role="status">Loading your profile…</p> : loadError ? <div>
      <p className="auth-status auth-error" role="alert">{loadError}</p>
      <button type="button" className="google-retry" onClick={() => { setLoading(true); setRetry(value => value + 1) }}>Try again</button>
    </div> : fields && <>
      {Object.values(fields).every(value => value === null || value === '') &&
        <p className="availability-note">No profile details saved yet. Add any details you want to keep for later.</p>}
      <form aria-busy={saving} noValidate onSubmit={save}>
        <div className="profile-grid">
          {textFields.slice(0, 2).map(({ key, label, autoComplete, maxLength }) => <div className="profile-field" key={key}>
            <label htmlFor={`profile-${key}`}>{label}</label>
            <input id={`profile-${key}`} name={key} value={fields[key] ?? ''} maxLength={maxLength}
              autoComplete={autoComplete} disabled={saving} aria-invalid={Boolean(fieldErrors[key])}
              aria-describedby={fieldErrors[key] ? `profile-${key}-error` : undefined}
              onChange={event => update(key, event.target.value)} />
            {fieldError(key)}
          </div>)}
          <div className="profile-field">
            <label htmlFor="profile-birth_date">Birth date</label>
            <input id="profile-birth_date" name="birth_date" type="date" value={fields.birth_date ?? ''}
              max={yesterdayIso()} disabled={saving} aria-invalid={Boolean(fieldErrors.birth_date)}
              aria-describedby={fieldErrors.birth_date ? 'profile-birth_date-error' : undefined}
              onChange={event => update('birth_date', event.target.value)} />
            {fieldError('birth_date')}
          </div>
          {countrySelect('nationality', 'Nationality')}
          {textFields.slice(2).map(({ key, label, autoComplete }) => <div className="profile-field" key={key}>
            <label htmlFor={`profile-${key}`}>{label}</label>
            <input id={`profile-${key}`} name={key} type={key === 'phone' ? 'tel' : 'text'}
              inputMode={key === 'phone' ? 'tel' : undefined} placeholder={key === 'phone' ? '+96171123456' : undefined}
              value={fields[key] ?? ''} autoComplete={autoComplete} disabled={saving}
              aria-invalid={Boolean(fieldErrors[key])}
              aria-describedby={fieldErrors[key] ? `profile-${key}-error` : undefined}
              onChange={event => update(key, event.target.value)} />
            {fieldError(key)}
          </div>)}
          {countrySelect('address_country', 'Address country')}
        </div>
        <button type="submit" className="primary-button" disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>
        {generalError && <p className="auth-status auth-error" role="alert">{generalError}</p>}
        {success && <p className="auth-status" role="status">{success}</p>}
      </form>
    </>}
  </section>
}
