import canadaFlag from 'flag-icons/flags/4x3/ca.svg'
import euFlag from 'flag-icons/flags/4x3/eu.svg'
import ukFlag from 'flag-icons/flags/4x3/gb.svg'
import usFlag from 'flag-icons/flags/4x3/us.svg'

// Homepage and FAQ copy lives here so the pages stay about layout.
// Flags are bundled SVGs because Windows has no flag emoji.

export const destinations = [
  { id: 'schengen', flag: euFlag, name: 'Schengen area', visa: 'Short-stay tourist visa' },
  { id: 'uk', flag: ukFlag, name: 'United Kingdom', visa: 'Standard Visitor visa' },
  { id: 'us', flag: usFlag, name: 'United States', visa: 'B-2 tourist visa' },
  { id: 'canada', flag: canadaFlag, name: 'Canada', visa: 'Visitor visa' },
]

export const trustBadges = [
  'You approve before anything is submitted',
  'Passport data stays private',
  'Not affiliated with any embassy',
]

export const steps = [
  { title: 'Pick your destination', body: 'Choose the country and visa type. We load that embassy\'s requirements.' },
  { title: 'Upload your passport', body: 'We read your details from the passport. You check and confirm them.' },
  { title: 'Answer a few questions', body: 'Tell us about your trip and upload the documents on your checklist.' },
  { title: 'Review and submit', body: 'Check the prepared application, then submit it when you are ready.' },
]

export const whatWeDo = [
  'Fill in the embassy\'s application form from your passport and answers',
  'Write a cover letter for your trip',
  'Give you a document checklist for your destination',
  'Check that your documents match each other before you submit',
  'Tell you exactly how and where to submit',
]

export const requiredDocuments = [
  'A passport valid for at least 3 to 6 months after your trip',
  'A recent passport photo',
  'Your last 3 to 6 months of bank statements',
  'Flight and hotel reservations',
  'A letter from your employer or university',
  'Travel insurance (for Schengen visas)',
]

export const privacyPoints = [
  { title: 'Private storage', body: 'Your passport and documents are stored privately. Only your account can open them.' },
  { title: 'Location data removed', body: 'Photos are cleaned when you upload them, so hidden location data is removed.' },
  { title: 'You stay in control', body: 'Nothing is sent to an embassy until you review it and confirm.' },
]

export const faqs = [
  {
    question: 'What does Taasheera do?',
    answer: 'Taasheera is an AI visa agent. It reads your passport, works out what your embassy needs, asks you the right questions, checks your documents against each other, and prepares the official application and a cover letter. You review everything and decide when it is submitted.',
  },
  {
    question: 'Will anything be submitted without my approval?',
    answer: 'No. The agent stops before every submission and shows you the application field by field. Nothing is sent to an embassy until you explicitly confirm it.',
  },
  {
    question: 'Which destinations can I apply for?',
    answer: 'We are adding embassies one at a time, starting with common tourist visas such as Schengen, the UK, the US and Canada. When you choose a destination, we tell you exactly how much of the application we can complete for you.',
  },
  {
    question: 'How does the agent submit my application?',
    answer: 'It depends on the embassy. For PDF forms we fill the official form and build a print-ready packet. For online portals we fill the portal and stop at its review page. If a portal has a CAPTCHA, we fill up to it and hand it over to you. If an embassy cannot be automated, we give you a field-by-field guide instead.',
  },
  {
    question: 'How do you read my passport?',
    answer: 'We read the machine-readable zone, the two lines of text at the bottom of your passport\'s photo page, and verify it with its built-in check digits. Some mistakes can still slip through, so we always ask you to confirm each field.',
  },
  {
    question: 'What if my passport photo can\'t be read?',
    answer: 'We tell you what went wrong, for example glare or a cropped page, so you can retake it. You can also type your details in by hand and carry on.',
  },
  {
    question: 'Is my passport data safe?',
    answer: 'Your passport and documents are stored privately and are only ever available to your account. Photos are re-encoded when you upload them, which removes hidden location data. Sign-in tokens are never kept in your browser\'s storage.',
  },
  {
    question: 'Do I still need to go to the embassy?',
    answer: 'Often, yes. Many visas require you to give fingerprints or attend an interview in person. Taasheera prepares everything you need to bring and tells you what to expect.',
  },
  {
    question: 'Does Taasheera guarantee my visa?',
    answer: 'No. Only the embassy or consulate decides whether to issue a visa. We make sure your application is complete and consistent, which removes the most common avoidable reasons for refusal.',
  },
  {
    question: 'Is this legal or immigration advice?',
    answer: 'No. Taasheera is a preparation tool, not a lawyer or an immigration adviser. For complex cases, such as a previous refusal or overstay, speak to a qualified adviser or the embassy directly.',
  },
]
