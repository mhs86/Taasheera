// Small inline icons; decorative, so hidden from screen readers.

export function ArrowIcon() {
  return (
    <svg className="icon" viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true">
      <path d="M4 10h12m-5-5 5 5-5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function MenuIcon({ open }: { open: boolean }) {
  return (
    <svg className="icon" viewBox="0 0 20 20" width="20" height="20" fill="none" aria-hidden="true">
      <path d={open ? 'm5 5 10 10M15 5 5 15' : 'M3 6h14M3 10h14M3 14h14'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function CheckIcon() {
  return (
    <svg className="icon" viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true">
      <path d="m5 10.5 3.2 3L15 6.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
