import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { readNavigation } from './navigation'

const initialNavigation = readNavigation(window)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App initialNavigation={initialNavigation} />
  </StrictMode>,
)
