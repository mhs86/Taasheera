import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { ACCEPTED_TYPES, checkFile } from './upload'

// A camera button only helps where there is a camera to point: phones and tablets.
function hasTouchCamera() {
  return typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches
}

type Props = {
  busyLabel: string | null
  onFile: (file: File) => void
  compact?: boolean
}

export default function Dropzone({ busyLabel, onFile, compact = false }: Props) {
  const fileInput = useRef<HTMLInputElement>(null)
  const cameraInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [problem, setProblem] = useState('')
  const busy = busyLabel !== null

  function take(file: File | undefined) {
    if (!file || busy) return
    const error = checkFile(file)
    setProblem(error ?? '')
    if (!error) onFile(file)
  }

  const onChange = (event: ChangeEvent<HTMLInputElement>) => {
    take(event.target.files?.[0])
    event.target.value = '' // choosing the same file again still triggers a change
  }
  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    take(event.dataTransfer.files[0])
  }

  if (compact) {
    return <div className="dropzone-compact">
      <button type="button" className="button button-secondary" disabled={busy}
        onClick={() => fileInput.current?.click()} data-activity-id="passport-replace">
        {busyLabel ?? 'Use a different photo'}
      </button>
      <input ref={fileInput} type="file" accept={ACCEPTED_TYPES.join(',')} hidden onChange={onChange} />
      {problem && <p className="field-error" role="alert">{problem}</p>}
    </div>
  }

  return <div
    className={`dropzone${dragging ? ' is-dragging' : ''}${busy ? ' is-busy' : ''}`}
    onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true) }}
    onDragLeave={() => setDragging(false)}
    onDrop={onDrop}
  >
    <svg className="dropzone-glyph" viewBox="0 0 64 44" aria-hidden="true">
      <rect x="1.5" y="1.5" width="61" height="41" rx="4" />
      <rect className="glyph-photo" x="8" y="8" width="14" height="17" rx="2" />
      <path d="M28 10h26M28 16h20M28 22h23" />
      <path className="glyph-mrz" d="M8 31h48M8 36h48" />
    </svg>
    <p className="dropzone-title" aria-live="polite">{busyLabel ?? 'Drop a photo of your passport here'}</p>
    {!busy && <p className="dropzone-hint">
      Use the page with your photo. The two lines of <code>&lt;&lt;&lt;</code> text at the bottom need to be sharp and fully in the frame. JPEG, PNG or WebP, up to 10 MB.
    </p>}
    <div className="dropzone-actions">
      <button type="button" className="button button-primary" disabled={busy}
        onClick={() => fileInput.current?.click()} data-activity-id="passport-choose-file">
        Choose a photo
      </button>
      {hasTouchCamera() && <button type="button" className="button button-secondary" disabled={busy}
        onClick={() => cameraInput.current?.click()} data-activity-id="passport-take-photo">
        Take a photo
      </button>}
    </div>
    <input ref={fileInput} type="file" accept={ACCEPTED_TYPES.join(',')} hidden onChange={onChange} />
    <input ref={cameraInput} type="file" accept="image/*" capture="environment" hidden onChange={onChange} />
    {problem && <p className="field-error" role="alert">{problem}</p>}
  </div>
}
