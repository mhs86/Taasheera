import { writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

export function redirectRules(rawBackendUrl = '') {
  const backendUrl = rawBackendUrl.trim()
  const rules = []
  if (backendUrl) {
    const parsed = new URL(backendUrl)
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) {
      throw new Error('BACKEND_URL must be a bare HTTPS origin, such as https://api.example.com')
    }
    for (const route of ['auth', 'passports', 'activity', 'assistant']) {
      rules.push(`/${route} ${parsed.origin}/${route} 200`)
      rules.push(`/${route}/* ${parsed.origin}/${route}/:splat 200`)
    }
  }
  rules.push('/* /index.html 200')
  return `${rules.join('\n')}\n`
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  await writeFile(new URL('../dist/_redirects', import.meta.url), redirectRules(process.env.BACKEND_URL ?? ''))
}
