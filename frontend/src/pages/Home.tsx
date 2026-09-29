import { useEffect } from 'react'
import { Link } from 'react-router'
import { destinations, faqs, privacyPoints, requiredDocuments, steps, trustBadges, whatWeDo } from '../content'
import { ArrowIcon, CheckIcon } from '../icons'
import { createAccountPath } from '../paths'
import FaqList from './FaqList'

export default function Home() {
  useEffect(() => {
    document.title = 'Taasheera | Your AI visa agent'
  }, [])

  return (
    <>
      <section className="hero dots" aria-labelledby="hero-heading">
        <div className="container hero-inner">
          <h1 id="hero-heading" className="hero-title">
            Prepare your visa application <span className="accent">with AI</span>
          </h1>
          <p className="hero-sub">
            Upload your passport and answer a few questions. We fill in the embassy form, write your
            cover letter and give you a document checklist, ready for you to review and submit.
          </p>
          <div className="hero-buttons">
            <Link to={createAccountPath} className="pill-button pill-primary">
              <span className="pill-icon"><ArrowIcon /></span>
              <span className="pill-label">Get started</span>
            </Link>
            <a href="#how-it-works" className="pill-button pill-secondary">
              <span className="pill-label">How it works</span>
            </a>
          </div>
          <ul className="trust-badges">
            {trustBadges.map(badge => (
              <li key={badge} className="trust-badge"><CheckIcon />{badge}</li>
            ))}
          </ul>
        </div>
      </section>

      <section id="how-it-works" className="section" aria-labelledby="how-heading">
        <div className="container">
          <header className="section-header">
            <p className="badge">How it works</p>
            <h2 id="how-heading">Four simple steps</h2>
          </header>
          <ol className="steps">
            {steps.map((step, index) => (
              <li key={step.title} className="card">
                <span className="step-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="section section-raised" aria-labelledby="what-heading">
        <div className="container two-lists">
          <div className="card list-card">
            <p className="badge">What we do</p>
            <h2 id="what-heading">We prepare your application</h2>
            <ul className="check-list">
              {whatWeDo.map(item => <li key={item}><CheckIcon />{item}</li>)}
            </ul>
          </div>
          <div id="documents" className="card list-card">
            <p className="badge">What you'll need</p>
            <h2>Have these ready</h2>
            <ul className="check-list">
              {requiredDocuments.map(item => <li key={item}><CheckIcon />{item}</li>)}
            </ul>
            <p className="list-note">Your exact checklist depends on your destination and nationality.</p>
          </div>
        </div>
      </section>

      <section id="destinations" className="section" aria-labelledby="destinations-heading">
        <div className="container">
          <header className="section-header">
            <p className="badge">Destinations</p>
            <h2 id="destinations-heading">Where do you want to go?</h2>
          </header>
          <ul className="destinations">
            {destinations.map(item => (
              <li key={item.id} className="card destination">
                <img src={item.flag} alt="" width="40" height="30" />
                <div>
                  <h3>{item.name}</h3>
                  <p>{item.visa}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section id="privacy" className="section section-dark dots" aria-labelledby="privacy-heading">
        <div className="container">
          <header className="section-header">
            <p className="badge">Privacy</p>
            <h2 id="privacy-heading">Your documents are safe with us</h2>
          </header>
          <ul className="privacy">
            {privacyPoints.map(point => (
              <li key={point.title} className="card">
                <h3>{point.title}</h3>
                <p>{point.body}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="section" aria-labelledby="faq-heading">
        <div className="container narrow">
          <header className="section-header">
            <p className="badge">FAQ</p>
            <h2 id="faq-heading">Frequently asked questions</h2>
          </header>
          <FaqList items={faqs.slice(0, 5)} />
          <p className="more-link"><Link to="/faq">See all questions</Link></p>
        </div>
      </section>

      <section className="section section-raised" aria-labelledby="cta-heading">
        <div className="container final-cta">
          <h2 id="cta-heading">Ready to start your visa application?</h2>
          <Link to={createAccountPath} className="pill-button pill-primary">
            <span className="pill-icon"><ArrowIcon /></span>
            <span className="pill-label">Get started</span>
          </Link>
        </div>
      </section>
    </>
  )
}
