import { useEffect } from 'react'
import { isRouteErrorResponse, useRouteError } from 'react-router'
import NotFound from './NotFound'

// Rendered by the router's error boundaries. `standalone` is used when the
// layout itself failed, so it avoids every shared component.
export default function ServerError({ standalone = false }: { standalone?: boolean }) {
  const error = useRouteError()

  useEffect(() => {
    document.title = 'Something went wrong | Taasheera'
    console.error(error)
  }, [error])

  if (!standalone && isRouteErrorResponse(error) && error.status === 404) return <NotFound />

  const content = (
    <section className="section page status" aria-labelledby="server-error-heading">
      <div className="container narrow">
        <p className="status-code" aria-hidden="true">500</p>
        <h1 id="server-error-heading">Something went wrong</h1>
        <p>This page hit an unexpected error. Your applications and documents have not been lost.</p>
        <div className="status-actions">
          <button type="button" className="pill-button pill-primary" onClick={() => window.location.reload()}>
            <span className="pill-label">Reload page</span>
          </button>
          {/* A full page load, so a broken client state is not carried over. */}
          <a href="/" className="pill-button pill-secondary"><span className="pill-label">Back to home</span></a>
        </div>
      </div>
    </section>
  )

  return standalone ? <main className="site">{content}</main> : content
}
