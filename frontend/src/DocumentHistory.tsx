import { useRef, useState } from 'react'
import { loadDocumentAccess, type AccessPage } from './privacy'

const purposes: Record<string, string> = { image_view: 'Viewed passport image', extraction: 'Read for passport extraction',
  review_read: 'Read confirmed details', review_update: 'Read for review update', assistant_context: 'Read for assistant context' }

export default function DocumentHistory() {
  const [opened, setOpened] = useState(false)
  const [history, setHistory] = useState<AccessPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const pending = useRef(false)
  async function load(page = 1) {
    if (pending.current) return
    pending.current = true
    setOpened(true); setLoading(true); setError('')
    try { setHistory(await loadDocumentAccess(page)) }
    catch { setError('Could not load document access history. Please try again.') }
    finally { pending.current = false; setLoading(false) }
  }
  return <section className="profile-section" aria-labelledby="document-history-heading">
    <h2 id="document-history-heading">Document access history</h2>
    <p>See when your passport image or confirmed details were accessed. Only your records appear here.</p>
    <button type="button" className="google-retry" disabled={loading} onClick={() => void load()}>Refresh access history</button>
    {loading && <p role="status">Loading document access history…</p>}
    {error && <p role="alert">{error}</p>}
    {opened && !loading && history && <>
      {history.total === 0 ? <p>No document access recorded yet.</p> : <ul className="access-history">
        {history.items.map(item => <li key={item.id}>
          <strong>{item.accessor}</strong> · {purposes[item.purpose] ?? 'Passport access'}
          <br /><time dateTime={item.occurred_at}>{new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(item.occurred_at) ? item.occurred_at : `${item.occurred_at}Z`).toLocaleString()}</time>
          <br /><small>Passport {item.upload_id.slice(0, 8)}</small>
        </li>)}
      </ul>}
      <p>{history.total} recorded access{history.total === 1 ? '' : 'es'}</p>
      <button type="button" disabled={loading || history.page === 1} onClick={() => void load(history.page - 1)}>Previous</button>{' '}
      <button type="button" disabled={loading || history.page * history.page_size >= history.total}
        onClick={() => void load(history.page + 1)}>Next</button>
    </>}
  </section>
}
