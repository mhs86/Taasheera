import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { protectedFetch, restoreSession, type Traveler } from '../auth'
import AssistantPanel from '../assistant/AssistantPanel'
import Dropzone from '../passport/Dropzone'
import ReviewForm from '../passport/ReviewForm'
import {
  blankFields, normalizeValue, validateFields,
  type Extraction, type FieldKey, type PassportFields,
} from '../passport/fields'
import { signInPath } from '../paths'
import '../ui.css'
import './passport.css'

const steps = ['Add a photo', 'Check the details', 'Confirmed']

async function problemText(response: Response, fallback: string) {
  const problem = await response.json().catch(() => null) as { detail?: unknown } | null
  return typeof problem?.detail === 'string' ? problem.detail : fallback
}

// Each upload gets a fresh page state: keying on the id resets everything when it changes.
export default function Passport() {
  const { uploadId } = useParams()
  return <PassportPage key={uploadId ?? 'new'} uploadId={uploadId} />
}

function PassportPage({ uploadId }: { uploadId?: string }) {
  const navigate = useNavigate()
  const [traveler, setTraveler] = useState<Traveler | null | undefined>()
  const [phase, setPhase] = useState<'idle' | 'uploading' | 'reading' | 'ready'>(uploadId ? 'reading' : 'idle')
  const [imageUrl, setImageUrl] = useState('')
  const [extraction, setExtraction] = useState<Extraction | null>(null)
  const [fields, setFields] = useState<PassportFields | null>(null)
  const [edited, setEdited] = useState<ReadonlySet<FieldKey>>(new Set())
  const [errors, setErrors] = useState<Partial<Record<FieldKey, string>>>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    document.title = 'Your passport | Taasheera'
    let active = true
    restoreSession().then(profile => { if (active) setTraveler(profile) })
      .catch(() => { if (active) { setTraveler(null); setMessage('Could not restore your session. Please reload and try again.') } })
    return () => { active = false }
  }, [])

  // Show the stored photo, then the confirmed review if there is one, otherwise read the passport.
  useEffect(() => {
    if (!traveler || !uploadId) return
    let active = true
    let objectUrl = ''
    Promise.all([
      protectedFetch(`/passports/${uploadId}/image`),
      protectedFetch(`/passports/${uploadId}/review`),
    ]).then(async ([image, review]) => {
      if (!image.ok) throw new Error('This passport photo could not be found in your account.')
      objectUrl = URL.createObjectURL(await image.blob())
      if (!active) return URL.revokeObjectURL(objectUrl)
      setImageUrl(objectUrl)
      if (review.ok) {
        const confirmed = await review.json() as PassportFields
        if (active) { setFields(confirmed); setSaved(true) }
      } else if (review.status === 404) {
        const result = await protectedFetch(`/passports/${uploadId}/extract`, { method: 'POST' })
        if (!result.ok) throw new Error('We could not read this photo. Try uploading it again.')
        const extracted = await result.json() as Extraction
        if (active) { setExtraction(extracted); setFields(extracted.fields ?? { ...blankFields }) }
      } else {
        throw new Error('Could not load your passport review.')
      }
    }).catch(error => {
      if (active) setMessage(error instanceof Error ? error.message : 'Could not load the passport.')
    }).finally(() => { if (active) setPhase('ready') })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [traveler, uploadId])

  async function upload(file: File) {
    setPhase('uploading')
    setMessage('')
    try {
      const body = new FormData()
      body.append('file', file)
      const response = await protectedFetch('/passports', { method: 'POST', body })
      if (!response.ok) throw new Error(await problemText(response, 'Could not upload the photo. Please try again.'))
      const { id } = await response.json() as { id: string }
      navigate(`/passport/${id}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not upload the photo.')
      setPhase(uploadId ? 'ready' : 'idle')
    }
  }

  function change(key: FieldKey, value: string) {
    setFields(current => current && {
      ...current,
      [key]: key.endsWith('_date') ? (value || null) : normalizeValue(key, value),
    })
    setEdited(current => new Set(current).add(key))
    setErrors(current => ({ ...current, [key]: undefined }))
    setSaved(false)
  }

  async function save() {
    if (!uploadId || !fields) return
    const found = validateFields(fields)
    setErrors(found)
    const firstInvalid = Object.keys(found)[0]
    if (firstInvalid) {
      document.getElementById(`passport-${firstInvalid}`)?.focus()
      return
    }
    setSaving(true)
    setMessage('')
    try {
      const response = await protectedFetch(`/passports/${uploadId}/review`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields),
      })
      if (!response.ok) throw new Error('Could not save your details. Check every field and try again.')
      setSaved(true)
      setEdited(new Set())
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save your details.')
    } finally {
      setSaving(false)
    }
  }

  const current = !uploadId ? 0 : saved ? 2 : 1
  const busyLabel = phase === 'uploading' ? 'Uploading your photo…' : null

  return <section className="passport-page container" aria-labelledby="passport-heading">
    <header className="passport-intro">
      <p className="badge">Your first step</p>
      <h1 id="passport-heading">Upload and review your passport</h1>
      <p>We read the two machine-readable lines on your passport's photo page, check them, and show you what we found. Nothing is saved until you confirm it.</p>
    </header>

    {traveler === undefined && !message && <p className="passport-status" role="status">Checking your session…</p>}
    {traveler === null && <p className="passport-signin">Please <Link to={signInPath}>sign in</Link> before uploading a passport.</p>}

    {traveler && <>
      <ol className="stepper" aria-label="Progress">
        {steps.map((label, index) => {
          const done = index < current || (saved && index === current)
          return <li key={label} className={done ? 'is-done' : index === current ? 'is-current' : undefined}
            aria-current={index === current ? 'step' : undefined}>
            <span className="stepper-mark" aria-hidden="true">{done ? '✓' : index + 1}</span>
            <span>{label}</span>
          </li>
        })}
      </ol>

      <div className={`workbench${uploadId ? ' has-upload' : ''}`}>
        <div className="workbench-photo">
          {uploadId
            ? <>
                <figure className="photo-frame">
                  {imageUrl
                    ? <img src={imageUrl} alt="The passport photo you uploaded" />
                    : <div className="photo-placeholder" aria-hidden="true" />}
                  <figcaption>Stored privately in your account, with location data removed.</figcaption>
                </figure>
                <Dropzone compact busyLabel={busyLabel} onFile={upload} />
              </>
            : <Dropzone busyLabel={busyLabel} onFile={upload} />}
        </div>

        {uploadId && <div className="workbench-review">
          {phase === 'reading' && !fields && <div className="review-loading" role="status">
            <span className="loading-bar" aria-hidden="true" />
            Reading your passport…
          </div>}
          {fields && <ReviewForm fields={fields} extraction={extraction} edited={edited} errors={errors}
            saving={saving} saved={saved} onChange={change} onSubmit={save} />}
          {saved && <p className="passport-saved" role="status">
            Your details are confirmed. The assistant can now answer questions about them.
          </p>}
        </div>}
      </div>

      {message && <p className="passport-message" role="alert">{message}</p>}
      <AssistantPanel step={uploadId ? 'passport_review' : 'passport_upload'} />
    </>}

    <p className="passport-disclaimer">Taasheera helps prepare applications and does not give legal or immigration advice. Nothing is submitted to an embassy from this page.</p>
  </section>
}
