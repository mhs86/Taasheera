import { useEffect, useRef, useState } from 'react'
import { loadGoogleIdentity, renderGoogleButton } from './googleIdentity'

type Props = {
  clientId: string
  disabled: boolean
  onCredential: (credential: string) => void
  onMessage: (message: string) => void
}

export default function GoogleSignIn({ clientId, disabled, onCredential, onMessage }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const accepting = useRef(false)
  const [attempt, setAttempt] = useState(0)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [waiting, setWaiting] = useState(false)

  useEffect(() => {
    if (!clientId || !host.current) return
    const element = host.current
    let live = true
    let dispose: (() => void) | undefined
    loadGoogleIdentity().then(api => {
      if (!live) return
      dispose = renderGoogleButton(api, clientId, element, response => {
        if (!live || !accepting.current) return
        accepting.current = false
        setWaiting(false)
        if (!response.credential) {
          onMessage('Google sign-in did not complete. Try again or use email sign-in.')
          return
        }
        onCredential(response.credential)
      }, () => {
        if (!live) return
        accepting.current = true
        setWaiting(true)
        onMessage('Continue in the Google window. If you close or cancel it, retry or use email sign-in.')
      })
      setStatus('ready')
    }).catch(() => {
      if (live) setStatus('failed')
    })
    return () => {
      live = false
      accepting.current = false
      dispose?.()
    }
  }, [clientId, attempt, onCredential, onMessage])

  if (!clientId) return <p className="password-help">Google sign-in is unavailable. Use your email and password.</p>

  return <div className="google-sign-in">
    <div ref={host} className="google-button-host" inert={disabled} aria-busy={disabled} />
    {status === 'loading' && <p className="auth-status" role="status">Loading Google sign-in…</p>}
    {status === 'failed' && <>
      <p className="auth-status auth-error" role="alert">Google sign-in could not load. Retry or use email sign-in.</p>
      <button type="button" className="google-retry" disabled={disabled} onClick={() => {
        setStatus('loading')
        setAttempt(value => value + 1)
      }}>Retry Google sign-in</button>
    </>}
    {waiting && !disabled && <button type="button" className="google-retry" onClick={() => {
      accepting.current = false
      setWaiting(false)
      setAttempt(value => value + 1)
      onMessage('Google sign-in cancelled here. You can close the Google window, try again, or use email sign-in.')
    }}>Cancel Google sign-in</button>}
  </div>
}
