import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { protectedFetch, restoreSession, type Traveler } from '../auth'
import { signInPath } from '../paths'
import './passport.css'

type PassportFields = {
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
type Extraction = {
  status: 'verified' | 'needs_review' | 'unreadable'
  fields: PassportFields | null
  suspect_fields: string[]
  corrected_fields: string[]
}
const blank: PassportFields = {
  surname: '', given_names: '', document_number: '', nationality: '', issuing_country: '',
  birth_date: null, sex: 'X', expiry_date: null, personal_number: '',
}
const labels: Record<keyof PassportFields, string> = {
  surname: 'Surname', given_names: 'Given names', document_number: 'Passport number',
  nationality: 'Nationality code', issuing_country: 'Issuing country code',
  birth_date: 'Date of birth', sex: 'Sex', expiry_date: 'Expiry date',
  personal_number: 'Personal number',
}
const keys = Object.keys(labels) as (keyof PassportFields)[]

export default function Passport() {
  const { uploadId } = useParams()
  const navigate = useNavigate()
  const [traveler, setTraveler] = useState<Traveler | null | undefined>()
  const [fields, setFields] = useState<PassportFields | null>(null)
  const [extraction, setExtraction] = useState<Extraction | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    document.title = 'Passport review | Taasheera'
    let active = true
    restoreSession().then(profile => { if (active) setTraveler(profile) })
      .catch(() => { if (active) setMessage('Could not restore your session. Please reload and try again.') })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!traveler || !uploadId) return
    let active = true
    let objectUrl = ''
    Promise.all([
      protectedFetch(`/passports/${uploadId}/image`),
      protectedFetch(`/passports/${uploadId}/review`),
    ]).then(async ([image, review]) => {
      if (!image.ok) throw new Error('This passport image could not be found in your account.')
      objectUrl = URL.createObjectURL(await image.blob())
      if (active) setImageUrl(objectUrl)
      else { URL.revokeObjectURL(objectUrl); return }
      if (review.ok) {
        const savedFields = await review.json() as PassportFields
        if (active) { setFields(savedFields); setSaved(true) }
      } else if (review.status === 404) {
        const result = await protectedFetch(`/passports/${uploadId}/extract`, { method: 'POST' })
        if (!result.ok) throw new Error('Could not read the passport. Please try uploading it again.')
        const extracted = await result.json() as Extraction
        if (active) { setExtraction(extracted); setFields(extracted.fields ?? { ...blank }) }
      } else {
        throw new Error('Could not load your passport review.')
      }
    }).catch(error => { if (active) setMessage(error instanceof Error ? error.message : 'Could not load the passport.') })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [traveler, uploadId])

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const input = event.currentTarget.elements.namedItem('passport') as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return
    if (file.size > 10 * 1024 * 1024) { setMessage('Choose an image 10 MB or smaller.'); return }
    setBusy(true)
    setMessage('')
    try {
      const body = new FormData()
      body.append('file', file)
      const response = await protectedFetch('/passports', { method: 'POST', body })
      if (!response.ok) {
        const problem = await response.json().catch(() => null) as { detail?: string } | null
        throw new Error(typeof problem?.detail === 'string' ? problem.detail : 'Could not upload the image.')
      }
      const result = await response.json() as { id: string }
      setFields(null)
      setExtraction(null)
      setSaved(false)
      setImageUrl('')
      navigate(`/passport/${result.id}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not upload the image.')
    } finally { setBusy(false) }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!uploadId || !fields) return
    setBusy(true)
    setMessage('')
    try {
      const response = await protectedFetch(`/passports/${uploadId}/review`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields),
      })
      if (!response.ok) throw new Error('Could not save your review. Check all fields and try again.')
      setSaved(true)
      setMessage('Passport details saved to your account.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save your review.')
    } finally { setBusy(false) }
  }

  return <section className="passport-page container narrow" aria-labelledby="passport-heading">
    <p className="badge">Your first step</p>
    <h1 id="passport-heading">Upload and review your passport</h1>
    <p>Use a clear photo of the details page with the two machine readable lines visible. JPEG, PNG and WebP images up to 10 MB are accepted.</p>
    {traveler === undefined && !message && <p role="status">Checking your session…</p>}
    {traveler === null && <p>Please <Link to={signInPath}>sign in</Link> before uploading a passport.</p>}
    {traveler && <>
      <form className="passport-upload" onSubmit={upload}>
        <label htmlFor="passport-file">Passport image</label>
        <input id="passport-file" name="passport" type="file" accept="image/jpeg,image/png,image/webp" required disabled={busy} />
        <button type="submit" disabled={busy}>{busy ? 'Working…' : uploadId ? 'Upload another passport' : 'Upload passport'}</button>
      </form>
      {imageUrl && <img className="passport-preview" src={imageUrl} alt="Your uploaded passport details page" />}
      {extraction && <p className="passport-note" role="status">{extraction.status === 'verified'
        ? 'The machine readable lines passed their checks. Confirm every field against your passport.'
        : extraction.status === 'needs_review'
          ? 'Some checks failed. Carefully correct the highlighted fields before saving.'
          : 'We could not read the machine readable lines. Enter the fields from your passport manually.'}</p>}
      {fields && <form className="passport-review" onSubmit={save}>
        <h2>Confirm passport details</h2>
        {keys.map(key => <label key={key} htmlFor={`passport-${key}`} className={extraction?.suspect_fields.includes(key) ? 'suspect' : ''}>
          <span>{labels[key]}{extraction?.suspect_fields.includes(key) && ' — check this field'}</span>
          {key === 'sex' ? <select id={`passport-${key}`} value={fields.sex} onChange={event => setFields({ ...fields, sex: event.target.value as PassportFields['sex'] })}>
            <option value="M">M</option><option value="F">F</option><option value="X">X / unspecified</option>
          </select> : <input id={`passport-${key}`} type={key.endsWith('_date') ? 'date' : 'text'}
            maxLength={key === 'nationality' || key === 'issuing_country' ? 3 : key === 'personal_number' || key === 'document_number' ? 30 : 100}
            required={!['birth_date', 'expiry_date', 'personal_number'].includes(key)}
            value={fields[key] ?? ''} onChange={event => setFields({ ...fields, [key]: event.target.value || (key.endsWith('_date') ? null : '') })} />}
        </label>)}
        <button type="submit" disabled={busy}>{busy ? 'Saving…' : saved ? 'Save changes' : 'Confirm and save details'}</button>
      </form>}
    </>}
    {message && <p className="passport-message" role="status">{message}</p>}
    <p className="passport-disclaimer">Taasheera helps prepare applications and does not give legal or immigration advice. Nothing is submitted to an embassy from this page.</p>
  </section>
}
