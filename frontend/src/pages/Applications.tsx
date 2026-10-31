import { useCallback, useEffect, useRef, useState } from 'react'
import { protectedFetch } from '../auth'
import { countries } from '../countries'
import './dashboard.css'

type Application = { id: string; destination: string; visa_type: string; status: string }

export default function Applications() {
  const [items, setItems] = useState<Application[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const load = useCallback(() => {
    return protectedFetch('/applications?page_size=100', { silent: true, cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error('Could not load applications.')
      setItems(await response.json())
    }).catch(problem => { setError(problem instanceof Error ? problem.message : 'Could not load applications.') })
      .finally(() => { setLoading(false) })
  }, [])
  useEffect(() => { document.title = 'Your applications | Taasheera'; void load() }, [load])
  return <main className="dashboard-page">
    <header className="dashboard-header"><a href="/">Taasheera</a><a href="/account">Your account</a></header>
    <div className="dashboard-content"><h1>Your applications</h1>
      <p>Start a draft to track your application. Embassy submission and agent processing require their separate workflows.</p>
      {error && <p role="alert">{error} <a href="/sign-in">Sign in</a></p>}
      {loading && <p role="status">Loading applications…</p>}
      <section><h2>Start a draft</h2><form onSubmit={async event => {
        event.preventDefault()
        if (pending.current) return
        const form = event.currentTarget
        const fields = new FormData(form)
        pending.current = true; setBusy(true); setError('')
        try {
          const response = await protectedFetch('/applications', { method: 'POST', silent: true,
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(fields)) })
          if (!response.ok) throw new Error('Could not start the application. Check the fields and try again.')
          form.reset(); await load()
        } catch (problem) { setError(problem instanceof Error ? problem.message : 'Could not start application.') }
        finally { pending.current = false; setBusy(false) }
      }}>
        {(['destination', 'nationality'] as const).map(field => <div key={field}>
          <label htmlFor={`application-${field}`}>{field === 'destination' ? 'Destination' : 'Passport nationality'}</label>
          <select id={`application-${field}`} name={field} required disabled={busy} defaultValue=""><option value="" disabled>Select country</option>
            {countries.map(country => <option key={country.code} value={country.code}>{country.name}</option>)}
          </select></div>)}
        <label htmlFor="application-visa-type">Visa type<input id="application-visa-type" name="visa_type" maxLength={80} required disabled={busy} placeholder="Tourist" /></label>
        <button type="submit" disabled={busy}>{busy ? 'Starting…' : 'Start application'}</button>
      </form></section>
      <section><h2>Saved applications</h2>{!loading && items.length === 0 && <p>No applications yet.</p>}
        <ul>{items.map(item => <li key={item.id}>{countries.find(country => country.code === item.destination)?.name ?? item.destination} · {item.visa_type} · <strong>{item.status}</strong></li>)}</ul>
        <button type="button" disabled={loading || busy} onClick={() => { setLoading(true); setError(''); void load() }}>Refresh applications</button>
        {items.length === 100 && <p>Showing the latest 100 applications.</p>}
      </section>
    </div>
  </main>
}
