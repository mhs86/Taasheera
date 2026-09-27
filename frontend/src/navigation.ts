export type Page = 'sign-in' | 'create-account' | 'forgot-password' | 'set-new-password'
export type Navigation = { page: Page; resetToken: string | null }

// Called before React mounts and on navigation, never from a render initializer.
// The backend emails RESET_FRONTEND_URL + '#token=...'. Scrub the fragment
// immediately; retain the token only in the current page's React state.
export function readNavigation(browser: Pick<Window, 'location' | 'history'>): Navigation {
  const { location, history } = browser
  const params = new URLSearchParams(location.hash.slice(1))
  if (params.has('token')) {
    const tokens = params.getAll('token')
    const token = tokens.length === 1 && /^[A-Za-z0-9_-]{43}$/.test(tokens[0]) ? tokens[0] : null
    history.replaceState(null, '', `${location.pathname}${location.search}#set-new-password`)
    return { page: 'set-new-password', resetToken: token }
  }
  const hashPages: Record<string, Page> = {
    '#sign-in': 'sign-in',
    '#create-account': 'create-account',
    '#forgot-password': 'forgot-password',
    '#set-new-password': 'set-new-password',
  }
  return {
    page: hashPages[location.hash] ?? (location.pathname.replace(/\/$/, '') === '/reset-password' ? 'set-new-password' : 'sign-in'),
    resetToken: null,
  }
}
