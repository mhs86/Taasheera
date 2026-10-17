import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { countries } from '../countries'
import ReviewForm from '../passport/ReviewForm'
import {
  blankFields, normalizeValue, validateFields, type FieldKey, type PassportFields,
} from '../passport/fields'
import type { Address, AnswerInput as Answer, AnswerValue, Question } from './api'

type Props = {
  question: Question
  applicationId: string
  // The saved answer when the traveler is changing it.
  initial?: AnswerValue
  // Rejects with the server's message when the answer breaks a rule.
  onAnswer: (answer: Answer) => Promise<void>
  onCancel?: () => void
}

const blankAddress: Address = { line1: '', line2: '', city: '', region: '', postal_code: '', country: '' }
// Up to this many options show as buttons; longer lists (29 Schengen countries) become a menu.
const MAX_BUTTONS = 10

// One input per answer type. The server checks every answer again, so these are
// conveniences (date ranges, phone keyboards), not the rules themselves.
export default function AnswerInput({ question, applicationId, initial, onAnswer, onCancel }: Props) {
  const id = useId()
  const [text, setText] = useState(typeof initial === 'string' ? initial : '')
  const [address, setAddress] = useState<Address>(isAddress(initial) ? initial : blankAddress)
  const [passport, setPassport] = useState<PassportFields | null>(isPassport(initial) ? initial : null)
  const [passportErrors, setPassportErrors] = useState<Partial<Record<FieldKey, string>>>({})
  const [edited, setEdited] = useState<ReadonlySet<FieldKey>>(new Set())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function send(answer: Answer) {
    setSaving(true)
    setError('')
    try {
      await onAnswer(answer)
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Could not save your answer.')
    } finally {
      setSaving(false)
    }
  }
  const submit = (value: AnswerValue) => (event: FormEvent) => { event.preventDefault(); void send({ value }) }
  const errorId = `${id}-error`
  const described = error ? errorId : undefined
  const cancel = onCancel && <button type="button" className="button button-secondary" onClick={onCancel}
    disabled={saving} data-activity-id="application-cancel-change">Keep my answer</button>
  const continueButton = (label = 'Continue', disabled = false) =>
    <button type="submit" className="button button-primary" disabled={saving || disabled}
      aria-busy={saving || undefined} data-activity-id="application-answer">{saving ? 'Saving…' : label}</button>
  const errorLine = error && <p id={errorId} className="answer-error" role="alert">{error}</p>

  if (question.type === 'yes_no' || (question.type === 'choice' && (question.options?.length ?? 0) <= MAX_BUTTONS)) {
    const choices = question.type === 'yes_no'
      ? [{ value: true, label: 'Yes' }, { value: false, label: 'No' }]
      : question.options!.map(option => ({ value: option.value as string | boolean, label: option.label }))
    return <div className="answer">
      <div className="answer-choices" role="group" aria-label={question.prompt} aria-describedby={described}>
        {choices.map(choice => <button key={String(choice.value)} type="button"
          className={`choice${initial === choice.value ? ' is-selected' : ''}`} disabled={saving}
          aria-pressed={initial === undefined ? undefined : initial === choice.value}
          onClick={() => void send({ value: choice.value })} data-activity-id="application-answer">
          {choice.label}
        </button>)}
        {cancel}
      </div>
      {errorLine}
    </div>
  }

  if (question.type === 'choice' || question.type === 'country') {
    const options = question.type === 'choice'
      ? question.options!
      : countries.map(country => ({ value: country.code, label: country.name }))
    return <form className="answer" onSubmit={submit(text)} noValidate>
      <label htmlFor={`${id}-select`} className="visually-hidden">{question.prompt}</label>
      <div className="answer-row">
        <select id={`${id}-select`} value={text} onChange={event => setText(event.target.value)}
          aria-describedby={described} aria-invalid={error ? true : undefined}>
          <option value="" disabled>Choose…</option>
          {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        {continueButton('Continue', !text)}
        {cancel}
      </div>
      {errorLine}
    </form>
  }

  if (question.type === 'address') {
    const field = (key: keyof Address, label: string, autoComplete: string, optional = false) =>
      <div className={`field${key === 'line1' || key === 'line2' ? ' field-wide' : ''}`}>
        <label htmlFor={`${id}-${key}`}>{label}{optional && <span className="field-optional"> (optional)</span>}</label>
        <input id={`${id}-${key}`} value={address[key]} autoComplete={autoComplete}
          onChange={event => setAddress(current => ({ ...current, [key]: event.target.value }))} />
      </div>
    return <form className="answer answer-form" onSubmit={submit(address)} aria-describedby={described} noValidate>
      <div className="review-grid">
        {field('line1', 'Street address', 'address-line1')}
        {field('line2', 'Apartment, building, floor', 'address-line2', true)}
        {field('city', 'City', 'address-level2')}
        {field('region', 'Region or state', 'address-level1', true)}
        {field('postal_code', 'Postal code', 'postal-code', true)}
        <div className="field">
          <label htmlFor={`${id}-country`}>Country</label>
          <select id={`${id}-country`} value={address.country}
            onChange={event => setAddress(current => ({ ...current, country: event.target.value }))}>
            <option value="" disabled>Choose…</option>
            {countries.map(country => <option key={country.code} value={country.code}>{country.name}</option>)}
          </select>
        </div>
      </div>
      <div className="answer-row">{continueButton()}{cancel}</div>
      {errorLine}
    </form>
  }

  if (question.type === 'passport') {
    if (!passport) {
      return <div className="answer">
        <div className="answer-choices">
          <Link className="button button-primary" to={`/passport?return=${encodeURIComponent(`/apply/${applicationId}`)}`}
            data-activity-id="application-passport-upload">Upload a photo</Link>
          <button type="button" className="button button-secondary" onClick={() => setPassport({ ...blankFields })}
            data-activity-id="application-passport-manual">Type the details</button>
          {cancel}
        </div>
        {errorLine}
      </div>
    }
    const confirm = () => {
      const found = validateFields(passport)
      setPassportErrors(found)
      const firstInvalid = Object.keys(found)[0]
      if (firstInvalid) return document.getElementById(`passport-${firstInvalid}`)?.focus()
      void send({ value: passport })
    }
    return <div className="answer answer-form">
      <ReviewForm fields={passport} extraction={null} edited={edited} errors={passportErrors} saving={saving}
        saved={false} onSubmit={confirm} onChange={(key, value) => {
          setPassport(current => current && { ...current, [key]: key.endsWith('_date') ? (value || null) : normalizeValue(key, value) })
          setEdited(current => new Set(current).add(key))
          setPassportErrors(current => ({ ...current, [key]: undefined }))
        }} />
      {cancel && <div className="answer-row">{cancel}</div>}
      {errorLine}
    </div>
  }

  // Text, phone and date: one field and a button.
  const inputType = question.type === 'date' ? 'date' : question.type === 'phone' ? 'tel' : 'text'
  return <form className="answer" onSubmit={submit(text)} noValidate>
    <label htmlFor={`${id}-input`} className="visually-hidden">{question.prompt}</label>
    <div className="answer-row">
      <input id={`${id}-input`} type={inputType} value={text} onChange={event => setText(event.target.value)}
        maxLength={question.type === 'text' ? question.max_length : undefined}
        min={question.date_min ?? undefined} max={question.date_max ?? undefined}
        autoComplete={question.type === 'phone' ? 'tel' : 'off'} placeholder={question.type === 'phone' ? '+961 71 123 456' : undefined}
        aria-describedby={described} aria-invalid={error ? true : undefined} />
      {continueButton(question.required || text.trim() ? 'Continue' : 'Skip', question.required && !text.trim())}
      {cancel}
    </div>
    {errorLine}
  </form>
}

function isAddress(value: AnswerValue | undefined): value is Address {
  return typeof value === 'object' && value !== null && 'line1' in value
}

function isPassport(value: AnswerValue | undefined): value is PassportFields {
  return typeof value === 'object' && value !== null && 'document_number' in value
}
