export class ResetError extends Error {
  invalidLink: boolean
  constructor(message: string, invalidLink = false) {
    super(message)
    this.invalidLink = invalidLink
  }
}

async function post(path: string, body: object): Promise<Response> {
  try {
    return await fetch(`/auth/${path}`, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    })
  } catch {
    throw new ResetError(path === 'forgot-password'
      ? 'Could not confirm the email request. Check your connection and try again. An earlier request may still have sent an email.'
      : 'Could not confirm the password change. Check your connection and try again. If it already succeeded, sign in with the new password or request a new code.')
  }
}

export async function requestPasswordReset(email: string): Promise<string> {
  const response = await post('forgot-password', { email: email.trim() })
  if (response.status === 202) {
    const body: unknown = await response.json().catch(() => null)
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail
    }
  }
  if (response.status === 422) throw new ResetError('Enter a valid email address and try again.')
  if (response.status === 429) throw new ResetError('Too many requests. Please wait before trying again.')
  throw new ResetError('Password reset email is temporarily unavailable. Please try again later.')
}

export async function verifyResetCode(email: string, code: string): Promise<string> {
  let response: Response
  try {
    response = await post('verify-reset-code', { email: email.trim(), code })
  } catch {
    throw new ResetError('Could not confirm the code. Check your connection. If it was already used, request a new code.')
  }
  if (response.status === 200) {
    const body: unknown = await response.json().catch(() => null)
    if (body && typeof body === 'object' && 'reset_token' in body &&
      typeof body.reset_token === 'string' && /^[A-Za-z0-9_-]{43}$/.test(body.reset_token)) return body.reset_token
  }
  if (response.status === 400) throw new ResetError('This code is invalid, expired, or already used. Check it or request a new code.')
  if (response.status === 422) throw new ResetError('Enter the six-digit code from your email.')
  if (response.status === 429) throw new ResetError('Too many code attempts. Please wait 15 minutes before trying again.')
  throw new ResetError('Could not verify the code. Please try again later.')
}

export async function submitPasswordReset(token: string, password: string): Promise<void> {
  const response = await post('reset-password', { token, password })
  if (response.status === 204) return
  if (response.status === 400) throw new ResetError('This reset session is invalid, expired, or already used. Request a new code.', true)
  if (response.status === 422) throw new ResetError('Use at least 8 characters and at most 72 UTF-8 bytes for your password.')
  if (response.status === 429) throw new ResetError('Too many reset attempts. Please wait one hour before trying again.')
  throw new ResetError('Could not change your password. Please try again later.')
}

export function passwordValidation(password: string, confirmation: string): string {
  if (Array.from(password).length < 8 || new TextEncoder().encode(password).length > 72) {
    return 'Use at least 8 characters and at most 72 UTF-8 bytes.'
  }
  return password === confirmation ? '' : 'Passwords must match.'
}
