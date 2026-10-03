import { useLoaderData } from 'react-router'
import App from './App'
import ActivityTracker from './ActivityTracker'
import type { Navigation } from './navigation'

export default function AuthRoute() {
  return <><ActivityTracker /><App initialNavigation={useLoaderData() as Navigation} /></>
}
