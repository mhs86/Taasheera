import assert from 'node:assert/strict'
import { test } from 'node:test'
import { redirectRules } from '../scripts/write-netlify-redirects.mjs'

test('Netlify proxies API requests before the SPA fallback', () => {
  assert.equal(redirectRules('https://api.example.com'), [
    '/auth https://api.example.com/auth 200',
    '/auth/* https://api.example.com/auth/:splat 200',
    '/passports https://api.example.com/passports 200',
    '/passports/* https://api.example.com/passports/:splat 200',
    '/activity https://api.example.com/activity 200',
    '/activity/* https://api.example.com/activity/:splat 200',
    '/* /index.html 200',
    '',
  ].join('\n'))
  assert.equal(redirectRules(), '/* /index.html 200\n')
})

test('Netlify backend URL must be an HTTPS origin', () => {
  for (const value of ['http://api.example.com', 'https://user:password@api.example.com', 'https://api.example.com/private', 'https://api.example.com/?key=secret']) {
    assert.throws(() => redirectRules(value))
  }
})
