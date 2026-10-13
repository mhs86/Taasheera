import { useLoaderData } from 'react-router'
import App from './App'
import ActivityTracker from './ActivityTracker'
import type { Navigation } from './navigation'
import { useEffect, useState } from 'react'
import { loadGoogleClientId } from './auth'

export default function AuthRoute() {
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
  return <><ActivityTracker /><App initialNavigation={useLoaderData() as Navigation}
    googleClientId={clientId} googleConfigurationStatus={status}
    onGoogleConfigurationRetry={() => { setClientId(''); setStatus('loading'); setAttempt(value => value + 1) }} /></>
}
