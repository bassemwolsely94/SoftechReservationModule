// W5b · HR leave request → approval chain (leave_request workflow: branch supervisor, then admin).
// Submitted on behalf (HR code + typed name, prefixed UAT-W5b) because UAT staff have no HR code.
import { test, expect } from '@playwright/test'
import { TAG, stamp, doers, nonDoers, apiAs, flag, expectRefused, brief } from './_money.js'

const SUBMIT = '/api/hr/leave-requests/submit/'
const DECIDE = id => `/api/approvals/requests/${id}/decide/`
let day = 10
const leave = (who) => {
  day += 1
  const d = `2027-01-${String(day).padStart(2, '0')}`
  return { leave_type_code: 'annual', start_date: d, end_date: d, days_requested: 1,
    reason: `${TAG} ${who}`, employee_hr_code: `UATW5B${stamp()}`, employee_name: `${TAG} ${who}` }
}

async function submit(baseURL, key) {
  const api = await apiAs(baseURL, key)
  try { return await api.post(SUBMIT, leave(key)) } finally { await api.dispose() }
}

// Everyone with hr:create files a leave; each is cancelled again except the salesperson's,
// which goes through the whole chain.
const submitters = doers('hr', 'create')
const filed = {}

for (const key of submitters) {
  test(`${key}: files a leave request`, async ({ baseURL }) => {
    const r = await submit(baseURL, key)
    if (r.status !== 201) {
      flag({ key, route: SUBMIT, kind: 'workflow', severity: 'P1', expected: 'leave submitted (201)', actual: `HTTP ${r.status} ${brief(r.body)}` })
      return
    }
    expect(r.body.status).toBe('submitted')
    expect(r.body.approval_request).toBeTruthy()
    filed[key] = r.body
  })
}

test('chain: branch supervisor approves step 1, admin step 2, the leave is approved', async ({ baseURL }) => {
  const lr = filed.salesperson || (await submit(baseURL, 'salesperson')).body
  test.skip(!lr?.approval_request, 'no salesperson leave')
  const ar = lr.approval_request
  for (const key of ['supervisor', 'admin']) {
    const api = await apiAs(baseURL, key)
    try {
      const pend = await api.get('/api/approvals/requests/pending/')
      if (!(pend.body || []).some(x => x.id === ar)) {
        flag({ key, route: '/api/approvals/requests/pending/', kind: 'workflow', severity: 'P1', expected: `leave request #${ar} waiting in ${key}'s inbox`, actual: 'not in the inbox' })
      }
      const d = await api.post(DECIDE(ar), { decision: 'approved', notes: TAG })
      if (d.status !== 200) {
        flag({ key, route: DECIDE(':id'), kind: 'workflow', severity: 'P1', expected: `${key} approves their step`, actual: `HTTP ${d.status} ${brief(d.body)}` })
        return
      }
    } finally { await api.dispose() }
  }
  const sp = await apiAs(baseURL, 'salesperson')
  try {
    const g = await sp.get(`/api/hr/leave-requests/${lr.id}/`)
    if (g.body?.status !== 'approved') {
      flag({ key: 'salesperson', route: '/api/hr/leave-requests/:id/', kind: 'workflow', severity: 'P1', expected: 'leave approved after the last step', actual: `status ${g.body?.status}` })
    }
  } finally { await sp.dispose() }
})

test('must be refused: the supervisor approving their own leave', async ({ baseURL }) => {
  const own = filed.supervisor || (await submit(baseURL, 'supervisor')).body
  test.skip(!own?.approval_request, 'no supervisor leave')
  const api = await apiAs(baseURL, 'supervisor')
  try {
    const d = await api.post(DECIDE(own.approval_request), { decision: 'approved', notes: `${TAG} self` })
    if (d.status === 200) {
      flag({ key: 'supervisor', route: DECIDE(':id'), kind: 'workflow', severity: 'P0', expected: 'own leave cannot be approved by the requester', actual: 'self-approval allowed (HTTP 200)' })
    } else {
      expect(d.status).toBe(400)
    }
  } finally { await api.dispose() }
})

test('must be refused: an approver role outside the step (pharmacist) and a role without hr:create', async ({ baseURL }) => {
  const target = Object.entries(filed).find(([k]) => k !== 'supervisor' && k !== 'salesperson')?.[1]
  test.skip(!target, 'no open leave to act on')
  const ph = await apiAs(baseURL, 'pharmacist')
  try {
    if (target.submitted_by_name !== 'UAT pharmacist') {
      expectRefused(await ph.post(DECIDE(target.approval_request), { decision: 'approved', notes: TAG }),
        { key: 'pharmacist', route: DECIDE(':id'), what: 'approving a leave outside their approval step' })
    }
  } finally { await ph.dispose() }
  for (const key of nonDoers('hr', 'create').filter(k => k !== 'admin')) {
    const api = await apiAs(baseURL, key)
    try {
      const r = await api.post(SUBMIT, leave(key))
      expectRefused(r, { key, route: SUBMIT, what: 'filing a leave request (no hr:create)' })
      if (r.status === 201) filed[key] = r.body   // cancelled in afterAll
    } finally { await api.dispose() }
  }
})

test.afterAll(async ({ baseURL }) => {
  // cancel every still-open UAT-W5b leave on the copy, by its filer (state may not survive a
  // worker restart, so the list is read back)
  for (const key of [...submitters, ...nonDoers('hr', 'create')]) {
    const api = await apiAs(baseURL, key)
    try {
      const l = await api.get('/api/hr/leave-requests/?page_size=100')
      const rows = Array.isArray(l.body) ? l.body : (l.body?.results || [])
      for (const lr of rows) {
        if (lr.status === 'submitted' && String(lr.reason || '').startsWith(TAG)) {
          await api.post(`/api/hr/leave-requests/${lr.id}/cancel/`, { reason: `${TAG} cleanup` })
        }
      }
    } finally { await api.dispose() }
  }
})
