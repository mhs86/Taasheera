import type { RouteObject } from 'react-router'
import AuthRoute from './AuthRoute'
import { readNavigation } from './navigation'
import Layout from './Layout'
import Faq from './pages/Faq'
import Home from './pages/Home'
import Passport from './pages/Passport'
import NotFound from './pages/NotFound'
import ServerError from './pages/ServerError'
import AdminDashboard from './pages/AdminDashboard'
import Applications from './pages/Applications'

// The root errorElement catches a crash in the layout itself; the pathless
// child catches page crashes so the header and footer stay on screen.
export const routes: RouteObject[] = [
  {
    element: <Layout />,
    errorElement: <ServerError standalone />,
    children: [
      {
        errorElement: <ServerError />,
        children: [
          { index: true, element: <Home /> },
          { path: 'faq', element: <Faq /> },
          { path: 'passport', element: <Passport /> },
          { path: 'passport/:uploadId', element: <Passport /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
  { path: 'sign-in', loader: () => readNavigation(window), element: <AuthRoute /> },
  { path: 'account', loader: () => readNavigation(window), element: <AuthRoute accountPage /> },
  { path: 'backoffice', element: <AdminDashboard />, errorElement: <ServerError standalone /> },
  { path: 'my-applications', element: <Applications />, errorElement: <ServerError standalone /> },
  { path: 'reset-password', loader: () => readNavigation(window), element: <AuthRoute /> },
]
