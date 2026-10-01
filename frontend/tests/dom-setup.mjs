import { registerHooks } from 'node:module'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { JSDOM } from 'jsdom'

// Use the installed TypeScript compiler to load the actual TSX components in
// Node's test runner. CSS has no behavior relevant to these DOM interaction tests.
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('.') && context.parentURL) {
      for (const suffix of ['.ts', '.tsx']) {
        const candidate = new URL(specifier + suffix, context.parentURL)
        if (existsSync(candidate)) return { url: candidate.href, shortCircuit: true }
      }
    }
    return nextResolve(specifier, context)
  },
  load(url, context, nextLoad) {
    if (url.endsWith('.css')) return { format: 'module', source: '', shortCircuit: true }
    if (/\.tsx?$/.test(url)) {
      const source = ts.transpileModule(readFileSync(fileURLToPath(url), 'utf8'), {
        compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 },
      }).outputText
      return { format: 'module', source, shortCircuit: true }
    }
    return nextLoad(url, context)
  },
})

export const dom = new JSDOM('<!doctype html><div id="root"></div>', { url: 'http://127.0.0.1:5173/' })
for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'FormData']) {
  Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let queue = Promise.resolve()
Object.defineProperty(navigator, 'locks', { value: {
  request(_name, action) {
    const result = queue.then(action)
    queue = result.catch(() => {})
    return result
  },
} })
// Any accidental use of token persistence fails the test immediately.
for (const name of ['localStorage', 'sessionStorage']) {
  Object.defineProperty(window, name, { get() { throw new Error('Browser storage must not be used') } })
  Object.defineProperty(globalThis, name, { get() { throw new Error('Browser storage must not be used') } })
}
