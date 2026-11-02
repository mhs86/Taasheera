import { useLoaderData } from 'react-router'
import { toast, Toaster } from 'sonner'
import App from './App'
import ActivityTracker from './ActivityTracker'
import IdleGuard from './IdleGuard'
import type { Navigation } from './navigation'
import { useEffect, useState } from 'react'
import { loadGoogleClientId } from './auth'

export default function AuthRoute({ accountPage = false }: { accountPage?: boolean }) {
  const [clientId, setClientId] = useState('')
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    loadGoogleClientId().then(id => {
      if (active) { setClientId(id); setStatus('ready') }
    }).catch(() => { if (active) setStatus('failed') })
    return () => { active = false }
  }, [attempt])

  // IdleGuard sends travelers here as /sign-in?notice=idle after signing them out. Show the notice
  // once and remove it from the address so a reload does not repeat it.
  useEffect(() => {
    const url = new URL(window.location.href)
    if (url.searchParams.get('notice') !== 'idle') return
    toast('You were signed out after 30 minutes of inactivity.', { id: 'idle-notice' })
    url.searchParams.delete('notice')
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`)
  }, [])

  return <><ActivityTracker /><IdleGuard /><Toaster position="top-center" richColors closeButton />
    <App initialNavigation={useLoaderData() as Navigation} accountPage={accountPage}
    googleClientId={clientId} googleConfigurationStatus={status}
    onGoogleConfigurationRetry={() => { setClientId(''); setStatus('loading'); setAttempt(value => value + 1) }} /></>
}
