import { useEffect } from 'react'
import { Link } from 'react-router'

export default function NotFound() {
  useEffect(() => {
    document.title = 'Page not found | Taasheera'
  }, [])

  return (
    <section className="section page status" aria-labelledby="not-found-heading">
      <div className="container narrow">
        <p className="status-code" aria-hidden="true">404</p>
        <h1 id="not-found-heading">Page not found</h1>
        <p>We couldn't find the page you were looking for. Your applications and documents are safe.</p>
        <div className="status-actions">
          <Link to="/" className="pill-button pill-primary"><span className="pill-label">Back to home</span></Link>
          <Link to="/faq" className="pill-button pill-secondary"><span className="pill-label">Read the FAQ</span></Link>
        </div>
      </div>
    </section>
  )
}
