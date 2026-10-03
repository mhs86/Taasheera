export function safePage(pathname: string, hash: string): string {
  if (pathname === '/') return 'home'
  if (pathname === '/faq') return 'faq'
  if (pathname === '/reset-password') return 'reset-password'
  if (pathname !== '/sign-in') return 'not-found'
  if (hash.startsWith('#create-account')) return 'create-account'
  if (hash.startsWith('#forgot-password')) return 'forgot-password'
  if (hash.startsWith('#set-new-password') || hash.startsWith('#token=')) return 'reset-password'
  return 'sign-in'
}
