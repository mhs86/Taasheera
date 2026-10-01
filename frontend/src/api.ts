import { toast } from 'sonner'

// Requests stay on the frontend origin (Vite proxies them locally, the static
// host rewrites them in production), so the HttpOnly auth cookies are first-party.
export class ApiError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type ApiOptions = RequestInit & {
  // Callers that show their own inline error (e.g. form validation) opt out of the toast.
  silent?: boolean
}

export async function apiFetch(path: string, { silent = false, ...options }: ApiOptions = {}): Promise<Response> {
  let response: Response
  try {
    response = await fetch(path, {
      credentials: 'same-origin',
      signal: AbortSignal.timeout(15000),
      ...options,
    })
  } catch {
    throw report(new ApiError('We could not reach Taasheera. Check your connection and try again.', null), silent)
  }
  // 4xx responses mean the request itself needs fixing; the caller explains those in context.
  if (response.status >= 500) {
    throw report(new ApiError('Something went wrong on our side. Your application is safe, please try again in a moment.', response.status), silent)
  }
  return response
}

function report(error: ApiError, silent: boolean) {
  if (!silent) toast.error(error.message, { id: 'api-error' })
  return error
}
