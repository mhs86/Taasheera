import { useEffect, useState } from 'react'
import { endOtherSessions, endSession, getSessions, type TravelerSession } from './auth'

function readableDate(value: string | null) {
  if (!value) return 'Unknown'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Unknown' : new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(date)
}

function SessionTime({ value }: { value: string | null }) {
  return value && !Number.isNaN(new Date(value).getTime())
    ? <time dateTime={value}>{readableDate(value)}</time>
    : <>Unknown</>
}

export default function Sessions() {
  const [sessions, setSessions] = useState<TravelerSession[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [success, setSuccess] = useState('')
  const [confirm, setConfirm] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let active = true
    getSessions().then(items => {
      if (active) { setSessions(items); setLoadError('') }
    }).catch(() => {
      if (active) setLoadError('Could not load your sessions. Please try again.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [retry])

  async function finish() {
    if (!confirm || busy) return
    setBusy(true)
    setActionError('')
    setSuccess('')
    let ended = false
    try {
      if (confirm === 'others') await endOtherSessions()
      else await endSession(confirm)
      ended = true
      const updated = await getSessions()
      setSessions(updated)
      setConfirm(null)
      setSuccess(confirm === 'others' ? 'Other devices have been signed out.' : 'Session ended.')
    } catch {
      if (ended) {
        setConfirm(null)
        setActionError('Session ended, but the list could not refresh. Reload this page to see the latest sessions.')
      } else {
        setActionError(confirm === 'others'
          ? 'Could not sign out other devices. Please try again.'
          : 'Could not end this session. Please try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  const otherSessions = sessions?.filter(item => !item.current) ?? []
  return <section className="sessions-section" aria-labelledby="sessions-heading">
    <h2 id="sessions-heading">Sessions</h2>
    <p className="profile-help">See where you are signed in and end sessions you do not recognize.</p>
    {loading ? <p role="status">Loading your sessions…</p> : loadError ? <div>
      <p className="auth-status auth-error" role="alert">{loadError}</p>
      <button type="button" className="google-retry" onClick={() => {
        setLoading(true); setLoadError(''); setRetry(value => value + 1)
      }}>Try again</button>
    </div> : <>
      {sessions?.length === 0 ? <p className="availability-note">No active sessions found.</p> : <>
        <ul className="sessions-list">
          {sessions?.map(item => <li key={item.id}>
            <div className="session-details">
              <strong>{item.device_label}</strong>
              {item.current && <span className="session-current">This device</span>}
              <span>Signed in: <SessionTime value={item.created_at} /></span>
              <span>Last active: <SessionTime value={item.last_active_at} /></span>
            </div>
            {!item.current && <button type="button" className="google-retry session-end" disabled={busy}
              onClick={() => { setConfirm(item.id); setActionError(''); setSuccess('') }}>End session</button>}
          </li>)}
        </ul>
        {otherSessions.length === 0 && <p className="availability-note">Only this device is signed in.</p>}
        {otherSessions.length > 0 && <button type="button" className="google-retry" disabled={busy}
          onClick={() => { setConfirm('others'); setActionError(''); setSuccess('') }}>
          Sign out all other devices
        </button>}
      </>}
      {confirm && <div className="session-confirm" role="group" aria-label="Confirm ending sessions">
        <p>{confirm === 'others' ? 'Sign out every other device?' : 'End this session?'}</p>
        <div className="session-confirm-actions">
          <button type="button" className="primary-button" disabled={busy} onClick={() => void finish()}>
            {busy ? 'Ending…' : 'Yes, sign out'}
          </button>
          <button type="button" className="google-retry" disabled={busy} onClick={() => setConfirm(null)}>Cancel</button>
        </div>
      </div>}
      {actionError && <p className="auth-status auth-error" role="alert">{actionError}</p>}
      {success && <p className="auth-status" role="status">{success}</p>}
    </>}
  </section>
}
