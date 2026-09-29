import { useEffect } from 'react'
import { faqs } from '../content'
import FaqList from './FaqList'

export default function Faq() {
  useEffect(() => {
    document.title = 'FAQ | Taasheera'
  }, [])

  return (
    <section className="section page" aria-labelledby="faq-page-heading">
      <div className="container narrow">
        <header className="section-header">
          <p className="badge">Help center</p>
          <h1 id="faq-page-heading">Frequently asked questions</h1>
          <p>Everything you need to know about preparing your visa application with Taasheera.</p>
        </header>
        <FaqList items={faqs} />
      </div>
    </section>
  )
}
