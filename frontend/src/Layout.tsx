import { useEffect, useState, type KeyboardEvent, type MouseEvent } from 'react'
import { Link, NavLink, Outlet, ScrollRestoration, useNavigate } from 'react-router'
import { toast, Toaster } from 'sonner'
import { ArrowIcon, MenuIcon } from './icons'
import ActivityTracker from './ActivityTracker'
import { restoreSession, signOut, type Traveler } from './auth'
import { disableGoogleAutoSelect } from './googleIdentity'
import { createAccountPath, signInPath } from './paths'
import './site.css'

function MainLinks() {
  return (
    <>
      <Link to="/#how-it-works" data-activity-id="how-it-works-link">How it works</Link>
      <Link to="/#destinations" data-activity-id="destinations-link">Destinations</Link>
      <Link to="/#privacy" data-activity-id="privacy-link">Privacy</Link>
      <NavLink to="/faq" data-activity-id="faq-link">FAQ</NavLink>
    </>
  )
}

type AccountProps = { traveler: Traveler | null; loggingOut: boolean; onLogOut: () => void; inMenu?: boolean }

// Signed out: Log in / Get started. Signed in: Log out / Your passport.
function AccountLinks({ traveler, loggingOut, onLogOut, inMenu = false }: AccountProps) {
  const cta = traveler
    ? <Link to="/passport" className="header-cta" data-activity-id="passport-link">
        <span className="mini-circle"><ArrowIcon /></span>Your passport
      </Link>
    : <Link to={createAccountPath} reloadDocument className="header-cta" data-activity-id="get-started-link">
        <span className="mini-circle"><ArrowIcon /></span>Get started
      </Link>
  const account = traveler
    ? <button type="button" className={`logout-button${inMenu ? '' : ' login-link'}`} data-activity-id="logout-button"
        disabled={loggingOut} onClick={onLogOut}>{loggingOut ? 'Logging out…' : 'Log out'}</button>
    : <Link to={signInPath} className={inMenu ? undefined : 'login-link'} data-activity-id="login-link">Log in</Link>
  return <>{account}{cta}</>
}

export default function Layout() {
  const navigate = useNavigate()
  // Below 1000px the nav links collapse into this menu (see site.css).
  const [menuOpen, setMenuOpen] = useState(false)
  const [traveler, setTraveler] = useState<Traveler | null>(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const closeOnLink = (event: MouseEvent) => {
    if ((event.target as Element).closest('a')) setMenuOpen(false)
  }
  const closeOnEscape = (event: KeyboardEvent) => {
    if (event.key === 'Escape') setMenuOpen(false)
  }

  // Shares the session restore ActivityTracker already makes; a failure just leaves the header signed out.
  useEffect(() => {
    let active = true
    restoreSession().then(profile => { if (active) setTraveler(profile) }).catch(() => {})
    return () => { active = false }
  }, [])

  async function logOut() {
    setLoggingOut(true)
    try {
      await signOut()
      disableGoogleAutoSelect()
      setTraveler(null)
      setMenuOpen(false)
      // Leaving the page unmounts anything it showed, such as a passport under review.
      navigate('/')
    } catch {
      toast.error('Could not log out. Check your connection and try again.')
    } finally {
      setLoggingOut(false)
    }
  }
  const account = { traveler, loggingOut, onLogOut: logOut }

  return (
    <div className="site">
      <ActivityTracker />
      <ScrollRestoration />
      <a className="skip-link" href="#main" data-activity-id="skip-link">Skip to content</a>
      <header className="navbar-wrap" onKeyDown={closeOnEscape}>
        <div className="navbar">
          <Link to="/" className="logo" aria-label="Taasheera home" data-activity-id="home-link">
            <span className="logo-mark" aria-hidden="true">T</span>Taasheera
          </Link>
          <nav className="nav-links" aria-label="Main">
            <MainLinks />
          </nav>
          <div className="nav-right">
            <AccountLinks {...account} />
            <button
              type="button"
              className="menu-button"
              data-activity-id="menu-toggle"
              aria-expanded={menuOpen}
              aria-controls="mobile-menu"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              onClick={() => setMenuOpen(open => !open)}
            >
              <MenuIcon open={menuOpen} />
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav id="mobile-menu" className="mobile-menu" aria-label="Menu" onClick={closeOnLink}>
            <MainLinks />
            <AccountLinks {...account} inMenu />
          </nav>
        )}
      </header>

      <main id="main"><Outlet /></main>

      <footer className="site-footer">
        <div className="container">
          <div className="footer-top">
            <Link to="/" className="logo" data-activity-id="home-link">
              <span className="logo-mark" aria-hidden="true">T</span>Taasheera
            </Link>
            <nav className="footer-links" aria-label="Footer">
              <Link to="/#how-it-works" data-activity-id="how-it-works-link">How it works</Link>
              <Link to="/faq" data-activity-id="faq-link">FAQ</Link>
              {traveler
                ? <Link to="/passport" data-activity-id="passport-link">Your passport</Link>
                : <Link to={signInPath} data-activity-id="login-link">Log in</Link>}
            </nav>
          </div>
          <p className="footer-legal">
            Taasheera helps you prepare visa applications. We are not affiliated with any embassy or
            government authority, and we do not give legal or immigration advice. Only the embassy or
            consulate decides whether to issue a visa. Nothing is submitted without your confirmation.
          </p>
        </div>
      </footer>

      <Toaster position="top-center" richColors closeButton />
    </div>
  )
}
