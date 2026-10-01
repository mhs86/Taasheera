import { useLoaderData } from 'react-router'
import App from './App'
import type { Navigation } from './navigation'

export default function AuthRoute() {
  return <App initialNavigation={useLoaderData() as Navigation} />
}
