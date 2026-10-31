import { useState } from 'react'
import { toast } from 'sonner'
import { deleteApplication, setArchived, type ApplicationSummary } from '../application/api'
import { applicationName } from './helpers'

type Props = {
  application: ApplicationSummary
  onArchiveChange: (application: ApplicationSummary) => void
  onDeleted: (id: string) => void
}

// Archive or restore (undoable, so no question first) and delete (asks first) for one application (US 79).
export default function ApplicationActions({ application, onArchiveChange, onDeleted }: Props) {
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const name = applicationName(application)
  const archived = application.archived_at !== null

  async function toggleArchive(archive: boolean, undo = false) {
    setBusy(true)
    try {
      const updated = await setArchived(application.id, archive)
      onArchiveChange(updated)
      if (undo) toast.success(archive ? `${name} archived again.` : `${name} is back on your dashboard.`)
      else toast.success(archive ? `${name} archived.` : `${name} restored.`, {
        action: { label: 'Undo', onClick: () => void toggleArchive(!archive, true) },
      })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    try {
      await deleteApplication(application.id)
      toast.success(`${name} deleted.`)
      onDeleted(application.id)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Something went wrong. Please try again.')
      setBusy(false)
    }
  }

  const confirmId = `dash-confirm-${application.id}`
  return <div className="dash-actions-wrap">
    <div className="dash-actions">
      <button type="button" className="button button-secondary dash-small" disabled={busy || confirming}
        data-activity-id={archived ? 'application-restore' : 'application-archive'}
        aria-label={`${archived ? 'Restore' : 'Archive'} ${name}`}
        onClick={() => void toggleArchive(!archived)}>{archived ? 'Restore' : 'Archive'}</button>
      <button type="button" className="button dash-small dash-delete" disabled={busy || confirming}
        data-activity-id="application-delete" aria-label={`Delete ${name}`}
        onClick={() => setConfirming(true)}>Delete</button>
    </div>
    {confirming && <div className="dash-confirm" role="alertdialog" aria-labelledby={confirmId}>
      <p id={confirmId}>Delete {name} and all its answers? This can't be undone.</p>
      <div className="dash-actions">
        <button type="button" className="button dash-small dash-danger" disabled={busy} aria-busy={busy}
          data-activity-id="application-delete-confirm" onClick={() => void remove()}>
          {busy ? 'Deleting…' : 'Yes, delete'}
        </button>
        <button type="button" className="button button-secondary dash-small" disabled={busy}
          data-activity-id="application-delete-cancel" onClick={() => setConfirming(false)}>Cancel</button>
      </div>
    </div>}
  </div>
}
