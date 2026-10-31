import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { JSDOM } from 'jsdom'

for (const [filename, title] of [['privacy.html', 'Privacy policy'], ['terms.html', 'Terms of Service']]) {
  test(`${filename} is a complete public document without authentication or JavaScript`, () => {
    const html = readFileSync(new URL(`../public/${filename}`, import.meta.url), 'utf8')
    const document = new JSDOM(html).window.document
    assert.equal(document.documentElement.lang, 'en')
    assert.equal(document.querySelector('h1').textContent, title)
    assert.match(document.title, /Taasheera/)
    assert.equal(document.querySelectorAll('script, iframe, form, input').length, 0)
    assert.ok(document.querySelector('main'))
    assert.equal(document.querySelector('link[rel="stylesheet"]').getAttribute('href'), '/legal.css')
    for (const path of ['/', '/privacy.html', '/terms.html', 'mailto:sharafm032@gmail.com']) {
      assert.ok(document.querySelector(`a[href="${path}"]`), path)
    }
    assert.equal(document.querySelectorAll('h1').length, 1)
    assert.equal(document.querySelector('time').getAttribute('datetime'), '2026-10-31')
    assert.equal(/localhost|127\.0\.0\.1|YOUR_DOMAIN|example\.com|TODO/.test(html), false)
  })
}

test('the public homepage shell links the exact policy URLs without requiring app startup', () => {
  const document = new JSDOM(readFileSync(new URL('../index.html', import.meta.url), 'utf8')).window.document
  const policies = document.querySelector('footer[aria-label="Taasheera policies"]')
  assert.ok(policies)
  assert.equal(policies.closest('#root'), null)
  assert.ok(policies.querySelector('a[href="/privacy.html"]'))
  assert.ok(policies.querySelector('a[href="/terms.html"]'))
  assert.match(policies.textContent, /Google Sign-In.*authenticate/)
})
