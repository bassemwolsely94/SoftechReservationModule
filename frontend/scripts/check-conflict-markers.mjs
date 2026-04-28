import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = new URL('../src/', import.meta.url)
const PATTERN = /^(<<<<<<<|=======|>>>>>>>|@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@)/m
const EXTS = new Set(['.js', '.jsx', '.ts', '.tsx', '.css', '.html'])

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const st = statSync(full)
    if (st.isDirectory()) walk(full, files)
    else files.push(full)
  }
  return files
}

const bad = []
for (const file of walk(ROOT.pathname)) {
  const ext = file.slice(file.lastIndexOf('.'))
  if (!EXTS.has(ext)) continue
  const content = readFileSync(file, 'utf8')
  if (PATTERN.test(content)) bad.push(file)
}

if (bad.length) {
  console.error('Build blocked: merge/diff markers found in source files:')
  for (const file of bad) console.error(` - ${file}`)
  process.exit(1)
}
