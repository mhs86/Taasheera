import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router'
import { hasAccessToken, postActivity, restoreSession } from './auth'
import { safePage } from './activityPage'

const controls = new Set([
  'home-link', 'how-it-works-link', 'destinations-link', 'privacy-link', 'faq-link',
  'login-link', 'get-started-link', 'skip-link', 'menu-toggle', 'password-toggle',
  'forgot-password-link', 'create-account-link', 'sign-in-link', 'submit-login',
  'submit-registration', 'logout-button', 'google-retry', 'google-cancel',
  'faq-question', 'reset-request', 'reset-submit', 'reset-link',
  'passport-choose-file', 'passport-take-photo', 'passport-replace', 'passport-confirm',
  'assistant-open', 'assistant-close', 'assistant-send', 'assistant-suggestion', 'passport-link',
])

export default function ActivityTracker() {
  const location = useLocation()
  const lastVisit = useRef('')

  useEffect(() => {
    let active = true
    const visit = () => {
      const page = safePage(window.location.pathname, window.location.hash)
      if (lastVisit.current === page) return
      if (hasAccessToken()) {
        lastVisit.current = page
        void postActivity({ event_type: 'page_visit', page, outcome: 'visited' })
        return
      }
      void restoreSession().then(traveler => {
        if (!active || !traveler || lastVisit.current === page) return
        lastVisit.current = page
        void postActivity({ event_type: 'page_visit', page, outcome: 'visited' })
      }).catch(() => {})
    }
    const onAuth = () => {
      visit()
    }
    visit()
    window.addEventListener('hashchange', visit)
    window.addEventListener('taasheera-auth-changed', onAuth)
    return () => {
      active = false
      window.removeEventListener('hashchange', visit)
      window.removeEventListener('taasheera-auth-changed', onAuth)
    }
  }, [location.pathname])

  useEffect(() => {
    const click = (event: MouseEvent) => {
      if (!event.isTrusted) return
      const element = event.target instanceof Element ? event.target.closest<HTMLElement>('[data-activity-id]') : null
      const control = element?.dataset.activityId
      if (!control || !controls.has(control) || element?.matches(':disabled')) return
      const page = safePage(window.location.pathname, window.location.hash)
      void postActivity({ event_type: 'click', page, control, outcome: 'initiated' })
    }
    document.addEventListener('click', click, { capture: true })
    return () => document.removeEventListener('click', click, { capture: true })
  }, [])

  return null
}
