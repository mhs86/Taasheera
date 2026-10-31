import type { RouteObject } from 'react-router'
import AuthRoute from './AuthRoute'
import AdminLayout from './admin/AdminLayout'
import AdminUser from './admin/AdminUser'
import AdminUsers from './admin/AdminUsers'
import { readNavigation } from './navigation'
import Layout from './Layout'
import Faq from './pages/Faq'
import Home from './pages/Home'
import Passport from './pages/Passport'
import Apply from './pages/Apply'
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
          // Not /applications: that prefix is the API, proxied to the backend.
          { path: 'apply', element: <Apply /> },
          { path: 'apply/:applicationId', element: <Apply /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
  // Every /admin page, including unknown ones, sits behind the admin layout's access check.
  {
    path: 'admin',
    element: <AdminLayout />,
    errorElement: <ServerError standalone />,
    children: [
      { index: true, element: <AdminUsers /> },
      { path: 'users/:userId', element: <AdminUser /> },
      { path: '*', element: <NotFound /> },
    ],
  },
  { path: 'sign-in', loader: () => readNavigation(window), element: <AuthRoute /> },
  { path: 'account', loader: () => readNavigation(window), element: <AuthRoute accountPage /> },
  { path: 'reset-password', loader: () => readNavigation(window), element: <AuthRoute /> },
]
