import { useState, type KeyboardEvent, type MouseEvent } from 'react'
import { Link, NavLink, Outlet, ScrollRestoration } from 'react-router'
import { Toaster } from 'sonner'
import { ArrowIcon, MenuIcon } from './icons'
import ActivityTracker from './ActivityTracker'
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

export default function Layout() {
  // Below 1000px the nav links collapse into this menu (see site.css).
  const [menuOpen, setMenuOpen] = useState(false)
  const closeOnLink = (event: MouseEvent) => {
    if ((event.target as Element).closest('a')) setMenuOpen(false)
  }
  const closeOnEscape = (event: KeyboardEvent) => {
    if (event.key === 'Escape') setMenuOpen(false)
  }

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
            <Link to={signInPath} className="login-link" data-activity-id="login-link">Log in</Link>
            <Link to={createAccountPath} className="header-cta" data-activity-id="get-started-link">
              <span className="mini-circle"><ArrowIcon /></span>Get started
            </Link>
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
            <Link to={signInPath} data-activity-id="login-link">Log in</Link>
            <Link to={createAccountPath} className="header-cta" data-activity-id="get-started-link">
              <span className="mini-circle"><ArrowIcon /></span>Get started
            </Link>
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
              <Link to={signInPath} data-activity-id="login-link">Log in</Link>
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
