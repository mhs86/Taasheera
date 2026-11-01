import { useState } from 'react'
import AssistantPanel from './AssistantPanel'

// The assistant button on every signed-in page (US 23). The passport and application pages
// have their own assistant with that page's context, so the layout leaves those out.
export default function GlobalAssistant() {
  const [open, setOpen] = useState(false)
  return <AssistantPanel step="general" open={open} onOpenChange={setOpen} />
}
