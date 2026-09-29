import type { RouteObject } from 'react-router'
import Layout from './Layout'
import Faq from './pages/Faq'
import Home from './pages/Home'
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
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
]
