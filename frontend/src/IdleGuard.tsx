import { useEffect, useRef, useState } from 'react'
import { hasAccessToken, signOut, touchSession } from './auth'
import { disableGoogleAutoSelect } from './googleIdentity'
import { ACTIVITY_EVENTS, idleState } from './idleTimeout'
import './idleGuard.css'

// How often the clock is looked at. A timer only decides when to check; the verdict always comes
// from comparing timestamps, so a throttled background tab or a sleeping laptop is still caught.
const CHECK_EVERY_MS = 15_000
// AuthRoute reads this notice code on the sign-in page.
const SIGNED_OUT_URL = '/sign-in?notice=idle'

// Tabs of one browser share an idle clock: input in any of them counts for all. Messages are the
// time of the last input (a number) or SIGNED_OUT; anything else is ignored.
const CHANNEL_NAME = 'taasheera-idle'
const SIGNED_OUT = 'signed-out'
const BROADCAST_EVERY_MS = 10_000

function goToSignIn(url: string) { window.location.assign(url) }

// Signs the traveler out after 30 minutes without input, warning them at 28. Renders nothing
// while signed out. `navigateAway` is replaceable so tests need not leave the page.
export default function IdleGuard({ navigateAway = goToSignIn }: { navigateAway?: (url: string) => void }) {
  // Set from sign-in/sign-out events, not read on every render: the token is briefly null while a
  // refresh is running, and that must not look like a sign-out.
  const [signedIn, setSignedIn] = useState(hasAccessToken)
  const [warning, setWarning] = useState(false)
  const lastActivity = useRef(0)
  const navigate = useRef(navigateAway)
  const stay = useRef<() => void>(() => {})

  useEffect(() => { navigate.current = navigateAway }, [navigateAway])

  useEffect(() => {
    const changed = () => {
      setSignedIn(hasAccessToken())
      setWarning(false)
    }
    window.addEventListener('taasheera-auth-changed', changed)
    return () => window.removeEventListener('taasheera-auth-changed', changed)
  }, [])

  useEffect(() => {
    if (!signedIn) return
    lastActivity.current = Date.now()
    let ended = false
    let lastBroadcast = -Infinity
    const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CHANNEL_NAME)

    const broadcast = (message: number | typeof SIGNED_OUT) => {
      try { channel?.postMessage(message) } catch { /* Other tabs fall back to their own clock. */ }
    }

    // The session is over for the traveler whether or not the server heard about it: if the
    // request fails, the server ends the session itself at the next refresh, and reloading
    // the sign-in page drops everything held in memory.
    const leave = async () => {
      if (ended) return
      ended = true
      setWarning(false)
      // Before signOut: signing out closes this channel, and the other tabs must not repeat the request.
      broadcast(SIGNED_OUT)
      try { await signOut() } catch { /* Navigate regardless. */ }
      disableGoogleAutoSelect()
      navigate.current(SIGNED_OUT_URL)
    }

    const check = () => {
      if (ended) return
      const state = idleState(lastActivity.current, Date.now())
      if (state === 'logout') void leave()
      else setWarning(state === 'warn')
    }

    const onActivity = () => {
      if (ended) return
      // Too late to rescue: the server would refuse the refresh anyway.
      if (idleState(lastActivity.current, Date.now()) === 'logout') { void leave(); return }
      lastActivity.current = Date.now()
      setWarning(false)
      if (lastActivity.current - lastBroadcast >= BROADCAST_EVERY_MS) {
        lastBroadcast = lastActivity.current
        broadcast(lastActivity.current)
      }
      // Throttled inside touchSession. False means the server no longer accepts the session.
      touchSession().then(accepted => { if (!accepted) void leave() }, () => { /* Retry on the next activity. */ })
    }

    const onVisible = () => { if (document.visibilityState === 'visible') check() }

    if (channel) {
      channel.onmessage = ({ data }) => {
        if (ended) return
        if (data === SIGNED_OUT) {
          // Another tab already ended the session on the server: just leave, quietly.
          ended = true
          setWarning(false)
          disableGoogleAutoSelect()
          navigate.current(SIGNED_OUT_URL)
          return
        }
        const now = Date.now()
        if (typeof data !== 'number' || !Number.isFinite(data) || data > now) return
        // No touchSession: the tab that saw the input already refreshed the server's clock.
        lastActivity.current = Math.max(lastActivity.current, data)
        if (idleState(lastActivity.current, now) === 'active') setWarning(false)
      }
    }

    for (const name of ACTIVITY_EVENTS) window.addEventListener(name, onActivity, { capture: true, passive: true })
    document.addEventListener('visibilitychange', onVisible)
    const timer = setInterval(check, CHECK_EVERY_MS)
    stay.current = onActivity
    return () => {
      for (const name of ACTIVITY_EVENTS) window.removeEventListener(name, onActivity, { capture: true })
      document.removeEventListener('visibilitychange', onVisible)
      clearInterval(timer)
      channel?.close()
      stay.current = () => {}
    }
  }, [signedIn])

  if (!signedIn || !warning) return null
  // Deliberately not modal and never focused: the traveler may be typing in a field behind it.
  return (
    <div className="idle-warning" role="alertdialog" aria-labelledby="idle-warning-title" aria-describedby="idle-warning-text">
      <p className="idle-warning-title" id="idle-warning-title">You'll be signed out in 2 minutes</p>
      <p className="idle-warning-text" id="idle-warning-text">
        For your security, Taasheera signs you out after 30 minutes of inactivity.
      </p>
      <button type="button" className="idle-warning-button" onClick={() => stay.current()}>Stay signed in</button>
    </div>
  )
}
