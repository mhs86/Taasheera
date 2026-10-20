import euFlag from 'flag-icons/flags/4x3/eu.svg'

// Bundled SVGs because Windows has no flag emoji (as on the homepage).
const flags: Record<string, string> = { SCHENGEN: euFlag }

export function destinationFlag(destination: string): string | null {
  return flags[destination] ?? null
}
