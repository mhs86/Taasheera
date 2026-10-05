export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

// Checked in the browser so a wrong file fails instantly; the server checks the real content again.
export function checkFile(file: File): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return "That file isn't a JPEG, PNG or WebP photo. Choose a photo of your passport."
  if (file.size > MAX_UPLOAD_BYTES) return 'That photo is larger than 10 MB. Choose a smaller one.'
  return null
}
