type Faq = { question: string; answer: string }

// Native <details> gives keyboard and screen-reader support for the accordion.
export default function FaqList({ items }: { items: Faq[] }) {
  return (
    <div className="faq-list">
      {items.map(item => (
        <details key={item.question} className="faq-item">
          <summary data-activity-id="faq-question">
            {item.question}
            <span className="faq-icon" aria-hidden="true" />
          </summary>
          <p>{item.answer}</p>
        </details>
      ))}
    </div>
  )
}
