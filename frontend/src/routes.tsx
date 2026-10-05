import type { RouteObject } from 'react-router'
import AuthRoute from './AuthRoute'
import { readNavigation } from './navigation'
import Layout from './Layout'
import Faq from './pages/Faq'
import Home from './pages/Home'
import Passport from './pages/Passport'
import NotFound from './pages/NotFound'
import ServerError from './pages/ServerError'

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
  { path: 'reset-password', loader: () => readNavigation(window), element: <AuthRoute /> },
]
