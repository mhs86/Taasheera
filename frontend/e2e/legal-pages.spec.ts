import { expect, test } from '@playwright/test'

test.use({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } })

for (const [path, title] of [['/privacy.html', 'Privacy policy'], ['/terms.html', 'Terms of Service']]) {
  test(`${title} is public, readable on mobile and needs no JavaScript or authentication`, async ({ page }) => {
    const authenticationRequests: string[] = []
    page.on('request', request => {
      if (new URL(request.url()).pathname.startsWith('/auth')) authenticationRequests.push(request.url())
    })
    const response = await page.goto(path)
    expect(response?.status()).toBe(200)
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Policy navigation' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Home', exact: true })).toHaveAttribute('href', '/')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(authenticationRequests).toEqual([])
  })
}

test('homepage exposes exact public policy links before the React app starts', async ({ page }) => {
  await page.goto('/')
  const footer = page.getByRole('contentinfo', { name: 'Taasheera policies' })
  await expect(footer.getByRole('link', { name: 'Privacy policy' })).toHaveAttribute('href', '/privacy.html')
  await expect(footer.getByRole('link', { name: 'Terms of Service' })).toHaveAttribute('href', '/terms.html')
  await expect(footer).toContainText('Google Sign-In is used to authenticate your account.')
})
