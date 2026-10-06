import type { FormEvent } from 'react'
import {
  fieldSpecs, fieldTrust, trustCopy,
  type Extraction, type FieldKey, type PassportFields,
} from './fields'

const statusCopy: Record<Extraction['status'], { title: string; body: string; tone: string }> = {
  verified: {
    title: 'Every check digit passed',
    body: "Check digits catch most misreads, not all of them. Compare each field with your passport, especially the ones marked Confirm.",
    tone: 'ok',
  },
  needs_review: {
    title: 'Some fields need a closer look',
    body: 'A check digit did not match. Correct the fields marked Check failed before you confirm.',
    tone: 'warn',
  },
  unreadable: {
    title: "We couldn't read this photo",
    body: 'Type the details from your passport below, or try a flatter, sharper photo without glare.',
    tone: 'danger',
  },
}

type Props = {
  fields: PassportFields
  extraction: Extraction | null
  edited: ReadonlySet<FieldKey>
  errors: Partial<Record<FieldKey, string>>
  saving: boolean
  saved: boolean
  onChange: (key: FieldKey, value: string) => void
  onSubmit: () => void
}

export default function ReviewForm({ fields, extraction, edited, errors, saving, saved, onChange, onSubmit }: Props) {
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit() }
  const status = extraction ? statusCopy[extraction.status] : null

  return <form className="review" onSubmit={submit} noValidate aria-labelledby="review-heading">
    <div className="review-head">
      <h2 id="review-heading">Check your details</h2>
      {saved && <span className="trust trust-ok">Confirmed</span>}
    </div>

    {status && !saved && <div className={`notice notice-${status.tone}`} role="status">
      <p className="notice-title">{status.title}</p>
      <p>{status.body}</p>
    </div>}

    <div className="review-grid">
      {fieldSpecs.map(spec => {
        const trust = saved ? null : fieldTrust(spec.key, extraction, edited)
        const error = errors[spec.key]
        const id = `passport-${spec.key}`
        const describedBy = [trust && `${id}-trust`, spec.help && `${id}-help`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
        const value = fields[spec.key] ?? ''

        return <div key={spec.key} className={`field${spec.wide ? ' field-wide' : ''}${trust ? ` field-${trust}` : ''}${error ? ' field-invalid' : ''}`}>
          <div className="field-label-row">
            <label htmlFor={id}>{spec.label}</label>
            {trust && <span id={`${id}-trust`} className={`trust trust-${trust}`} title={trustCopy[trust].detail}>
              {trustCopy[trust].label}<span className="visually-hidden">: {trustCopy[trust].detail}</span>
            </span>}
          </div>
          {spec.kind === 'sex'
            ? <select id={id} value={value} onChange={event => onChange(spec.key, event.target.value)} aria-describedby={describedBy}>
                <option value="F">F (female)</option>
                <option value="M">M (male)</option>
                <option value="X">X (unspecified)</option>
              </select>
            : <input
                id={id}
                type={spec.kind === 'date' ? 'date' : 'text'}
                className={spec.kind === 'code' ? 'is-code' : undefined}
                value={value}
                maxLength={spec.maxLength}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy}
                onChange={event => onChange(spec.key, event.target.value)}
              />}
          {spec.help && <p id={`${id}-help`} className="field-help">{spec.help}</p>}
          {error && <p id={`${id}-error`} className="field-error">{error}</p>}
        </div>
      })}
    </div>

    <div className="review-actions">
      <button type="submit" className="button button-primary" disabled={saving} data-activity-id="passport-confirm">
        {saving ? 'Saving…' : saved ? 'Save changes' : 'Confirm these details'}
      </button>
      <p className="review-note">Only details you confirm are saved to your account.</p>
    </div>
  </form>
}
