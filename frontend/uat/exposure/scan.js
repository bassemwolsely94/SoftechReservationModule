// W4 scanning helpers: capture a screen's JSON, look for reference customers' full numbers and for
// records of a branch the user may not see, and emit findings. Never writes a full number anywhere:
// findings name the customer by PIC and the number by last3().
import zlib from 'node:zlib'
import { reference, phoneDigits, last3 } from '../lib/expected.js'
import { finding } from '../lib/findings.js'
import { WS, phoneRule, branchRule, seesBranchValue, sees } from './rules.js'

const AR_DIGITS = /[٠-٩۰-۹]/g
const toAscii = s => s.replace(AR_DIGITS, ch => String((ch.charCodeAt(0) & 0xF) % 10))
/** Digits joined across the separators people and formatters put inside a number. */
export const normalise = s => toAscii(String(s ?? '')).replace(/(?<=\d)[\s\-–.()+‎‏‪-‮⁦-⁩]+(?=\d)/g, '')

/** The part of a number that must never show in full: last 10 digits (covers 0 / +20 / 0020
 *  prefixes); a shorter landline in full; under 8 digits is too short to tell from other numbers. */
export function needleOf(phone) {
  const d = phoneDigits(phone)
  if (d.length >= 10) return d.slice(-10)
  if (d.length >= 8) return d
  return null
}

export function refCustomers() {
  const out = []
  for (const b of ['A', 'B']) {
    for (const c of reference(b).customers || []) {
      const needle = needleOf(c.phone)
      if (needle) out.push({ ...c, branch: b, needle, tail: phoneDigits(c.phone).slice(-3) })
    }
  }
  return out
}

/** A URL path safe for a finding: no query string (it may hold a searched number), no long digit runs. */
export const safePath = u => String(u || '').replace(/^https?:\/\/[^/]+/, '').split('?')[0].replace(/\d{8,}/g, '#')
const safeText = s => String(s).replace(/\d{8,}/g, '#')

// ── capture ──────────────────────────────────────────────────────────────────────────────────

/** Collect every JSON /api/ response the page receives until `done()` is awaited. */
export function captureJson(page) {
  const bodies = []
  const pending = []
  const onResponse = r => {
    const url = r.url()
    if (!url.includes('/api/')) return
    const ct = r.headers()['content-type'] || ''
    if (!ct.includes('json')) {
      bodies.push({ url, status: r.status(), json: null })
      return
    }
    pending.push(r.text().then(t => {
      if (t.length > 8_000_000) { bodies.push({ url, status: r.status(), json: null, big: true }); return }
      let json = null
      try { json = JSON.parse(t) } catch { /* not JSON */ }
      bodies.push({ url, status: r.status(), json })
    }).catch(() => {}))
  }
  page.on('response', onResponse)
  return {
    bodies,
    async done() {
      page.off('response', onResponse)
      await Promise.allSettled(pending)
      return bodies
    },
  }
}

export async function pageText(page) {
  return (await page.locator('body').innerText({ timeout: 10_000 }).catch(() => '')) || ''
}

// ── JSON walking ─────────────────────────────────────────────────────────────────────────────

// Keys that name the branch a record belongs to (preferred / home branch = the CUSTOMER's, not the record's).
const RECORD_BRANCH_KEYS = ['branch', 'branch_id', 'branch_code', 'branch_name', 'requesting_branch',
  'requesting_branch_id', 'supplying_branch', 'supplying_branch_id', 'fulfilling_branch', 'order_branch',
  'pos_branch', 'assigned_branch', 'branchcode', 'source_branch', 'target_branch']
// Keys that echo what the user typed into a search box.
const ECHO_KEYS = new Set(['q', 'query', 'search', 'term', 'searched', 'phone_query', 'input'])

/** Every leaf of `json` whose normalised text contains `needle`: [{path, ancestors}]. */
export function jsonHits(json, needle) {
  const hits = []
  const walk = (v, path, ancestors) => {
    if (v == null) return
    if (typeof v === 'string' || typeof v === 'number') {
      if (normalise(v).includes(needle)) hits.push({ path, ancestors })
      return
    }
    if (Array.isArray(v)) { v.forEach((x, i) => walk(x, `${path}[${i}]`, ancestors)); return }
    if (typeof v === 'object') {
      const anc = [...ancestors, v]
      for (const [k, x] of Object.entries(v)) {
        if (ECHO_KEYS.has(k)) continue
        walk(x, path ? `${path}.${k}` : k, anc)
      }
    }
  }
  walk(json, '', [])
  return hits
}

/** Does the nearest ancestor that names a record branch belong to the user? true / false / null. */
export function recordVisibility(key, ancestors) {
  for (let i = ancestors.length - 1; i >= 0; i--) {
    const o = ancestors[i]
    const vals = RECORD_BRANCH_KEYS.filter(k => o[k] != null && o[k] !== '').map(k => o[k])
    if (!vals.length) continue
    const seen = vals.map(v => seesBranchValue(key, v))
    if (seen.some(x => x === true)) return true
    if (seen.every(x => x === false)) return false
  }
  return null
}

// ── findings ─────────────────────────────────────────────────────────────────────────────────

const emitted = new Set()
function once(id, f) {
  if (emitted.has(id)) return false
  emitted.add(id)
  finding({ ws: WS, ...f })
  return true
}

/**
 * Check a screen for reference customers' full numbers.
 * @param {{key, domain, route, text?, bodies?, files?: Array<{name, text}>, textMayEcho?: boolean,
 *          overMask?: Array<customer>}} o  — overMask: customers this screen is ABOUT (P3 check)
 * @returns {{p0: number, decisions: number}}
 */
export function checkPhones(o) {
  const { key, domain, route } = o
  const text = normalise(o.text || '')
  let p0 = 0, decisions = 0
  for (const c of refCustomers()) {
    const where = []          // [{rule, src, at}]
    for (const b of o.bodies || []) {
      if (!b.json) continue
      for (const h of jsonHits(b.json, c.needle)) {
        const vis = recordVisibility(key, h.ancestors)
        where.push({ ...phoneRule(key, domain, c.branch, vis), at: `${safePath(b.url)} ${h.path.replace(/\[\d+\]/g, '[]')}` })
      }
    }
    for (const f of o.files || []) {
      if (normalise(f.text).includes(c.needle)) where.push({ ...phoneRule(key, domain, c.branch, true), at: `file ${f.name}` })
    }
    if (text.includes(c.needle)) {
      const jsonFull = where.some(w => w.rule === 'full')
      if (!jsonFull) {
        const r = phoneRule(key, domain, c.branch, null)
        where.push(o.textMayEcho && r.rule === 'masked'
          ? { rule: 'decision', src: `${r.src}; rendered text only — may be the typed search echoed`, at: 'rendered text' }
          : { ...r, at: 'rendered text' })
      }
    }
    for (const w of where) {
      if (w.rule === 'masked') {
        if (once(`phone|${key}|${route}|${c.pic}|${w.at}`, {
          key, route, kind: 'phone', severity: 'P0',
          expected: `masked (${w.src})`,
          actual: `full number of branch-${c.branch} customer PIC ${c.pic} (${last3(c.phone)}) in ${safeText(w.at)}`,
        })) p0++
      } else if (w.rule === 'decision') {
        if (once(`dec|${key}|${route}|${c.pic}|${w.src}`, {
          key, route, kind: 'decision', severity: 'P2',
          expected: `owner rule needed: ${w.src}`,
          actual: `full number of branch-${c.branch} customer PIC ${c.pic} (${last3(c.phone)}) in ${safeText(w.at)}`,
        })) decisions++
      }
    }
  }
  // Over-masking: a customer this screen is about, whose number this user may see in full, shows only masked.
  for (const c of o.overMask || []) {
    const r = phoneRule(key, domain, c.branch, true)
    if (r.rule !== 'full' || !c.needle) continue
    const full = text.includes(c.needle) || (o.bodies || []).some(b => b.json && jsonHits(b.json, c.needle).length)
    const masked = new RegExp(`[•*●]{3,}\\s*${c.tail}`).test(o.text || '') ||
      (o.bodies || []).some(b => b.json && new RegExp(`[•*●]{3,}${c.tail}`).test(JSON.stringify(b.json)))
    if (!full && masked) {
      once(`over|${key}|${route}|${c.pic}`, {
        key, route, kind: 'phone', severity: 'P3',
        expected: `full (${r.src})`, actual: `only the masked number of branch-${c.branch} customer PIC ${c.pic} (${last3(c.phone)})`,
      })
    }
  }
  return { p0, decisions }
}

/** String identifiers of a branch's reference records that must not appear where the rule says absent. */
export function refStrings(branch, domain) {
  const r = reference(branch)
  switch (domain) {
    case 'customers': case 'search': return (r.customers || []).map(c => c.pic).filter(Boolean)
    case 'transfers': return (r.transfers || []).map(t => t.number).filter(Boolean)
    case 'demand': return (r.demand || []).map(t => t.number).filter(Boolean)
    case 'sales': return (r.invoices || []).filter(Boolean)
    default: return []
  }
}

const idsOf = (branch, refKey) => (reference(branch)[refKey] || []).map(x => (typeof x === 'object' ? x.id : x))

/**
 * Records of a branch the user may not see must be absent from this screen.
 * @param {{key, domain, route, text, bodies, listApi?: RegExp, refKey?: string, skip?: Set<string>}} o
 *   skip: identifiers (numbers / ids as strings) that are legitimately visible (e.g. a transfer
 *   whose supplying side is the user's).
 */
export function checkBranchAbsent(o) {
  const { key, domain, route } = o
  let p0 = 0
  for (const b of ['A', 'B']) {
    if (sees(key, b)) continue
    const rule = branchRule(key, domain, b)
    if (rule.rule !== 'absent') continue
    const strs = refStrings(b, domain).filter(s => !o.skip?.has(String(s)))
    const blob = (o.text || '') + '\n' + (o.bodies || []).map(x => x.json ? JSON.stringify(x.json) : '').join('\n')
    for (const s of strs) {
      if (blob.includes(s)) {
        if (once(`branch|${key}|${route}|${s}`, {
          key, route, kind: 'branch', severity: 'P0',
          expected: `absent (${rule.src})`, actual: `branch-${b} record ${safeText(s)} shown`,
        })) p0++
      }
    }
    if (o.listApi && o.refKey) {
      const ids = new Set(idsOf(b, o.refKey).map(String).filter(s => !o.skip?.has(s)))
      for (const body of o.bodies || []) {
        if (!o.listApi.test(safePath(body.url) + (body.url.includes('?') ? '?' : '')) || !body.json) continue
        const rows = Array.isArray(body.json) ? body.json : (body.json.results || [])
        for (const row of rows) {
          if (row && ids.has(String(row.id))) {
            if (once(`branchid|${key}|${route}|${o.refKey}|${row.id}`, {
              key, route, kind: 'branch', severity: 'P0',
              expected: `absent (${rule.src})`, actual: `branch-${b} ${o.refKey} id ${safeText(row.id)} in ${safePath(body.url)}`,
            })) p0++
          }
        }
      }
    }
  }
  return p0
}

export function decision(key, route, expected, actual) {
  return once(`decision|${key}|${route}|${expected}`, { key, route, kind: 'decision', severity: 'P2',
    expected: safeText(expected), actual: safeText(actual) })
}

export function branchLeak(key, route, expected, actual) {
  return once(`leak|${key}|${route}|${actual}`, { key, route, kind: 'branch', severity: 'P0',
    expected: safeText(expected), actual: safeText(actual) })
}

// ── API calls as the signed-in user (cookie auth; X-Requested-With = our CSRF marker) ─────────

const XHR = { 'X-Requested-With': 'XMLHttpRequest' }
export async function api(page, method, url, data) {
  const call = () => page.request.fetch(url, { method, headers: { ...XHR, ...(data ? { 'Content-Type': 'application/json' } : {}) },
    data: data ? JSON.stringify(data) : undefined, timeout: 120_000 })
  let res = await call()
  if (res.status() === 401) {
    await page.request.post('/api/auth/refresh/', { headers: XHR, data: '{}' }).catch(() => {})
    res = await call()
  }
  return res
}

// ── .xlsx text (a zip of XML parts) without a new dependency ─────────────────────────────────

function unzip(buf) {
  const files = {}
  let eocd = -1
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 65_557); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break }
  }
  if (eocd < 0) throw new Error('not a zip file')
  const count = buf.readUInt16LE(eocd + 10)
  let p = buf.readUInt32LE(eocd + 16)
  for (let n = 0; n < count; n++) {
    const method = buf.readUInt16LE(p + 10)
    const csize = buf.readUInt32LE(p + 20)
    const nameLen = buf.readUInt16LE(p + 28), extraLen = buf.readUInt16LE(p + 30), commentLen = buf.readUInt16LE(p + 32)
    const local = buf.readUInt32LE(p + 42)
    const name = buf.toString('utf8', p + 46, p + 46 + nameLen)
    const lstart = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28)
    const raw = buf.subarray(lstart, lstart + csize)
    files[name] = method === 8 ? zlib.inflateRawSync(raw) : raw
    p += 46 + nameLen + extraLen + commentLen
  }
  return files
}

const xmlUnescape = s => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&')

/** -> {text, rows: {sheetName: rowCount}} — every cell value as text, one per line. */
export function xlsxText(buf) {
  const files = unzip(Buffer.from(buf))
  const parts = []
  const rows = {}
  for (const [name, data] of Object.entries(files)) {
    if (!/^xl\/(sharedStrings|worksheets\/sheet\d+)\.xml$/.test(name)) continue
    const xml = data.toString('utf8')
    for (const m of xml.matchAll(/<(?:t|v)(?:\s[^>]*)?>([^<]*)<\/(?:t|v)>/g)) parts.push(xmlUnescape(m[1]))
    if (name.includes('worksheets')) rows[name] = (xml.match(/<row[\s>]/g) || []).length
  }
  return { text: parts.join('\n'), rows }
}
