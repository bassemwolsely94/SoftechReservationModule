// C24 — bulk actions on worklists, the FE-10 way (pages/approvalsBulk.js): there is no bulk
// endpoint on purpose. Each ticked row goes through the SAME per-row endpoint as a single click,
// so the server still checks permission, branch scope and state for every row and writes its own
// audit row. One at a time, in order; a refusal on one row does not stop the others, and every
// refusal comes back with its reason so the screen can report it and keep those rows ticked.

export function bulkErrorDetail(err) {
  const d = err?.response?.data
  return (typeof d?.detail === 'string' && d.detail) || (typeof d?.error === 'string' && d.error)
    || (err?.response ? `خطأ ${err.response.status}` : 'لا يوجد اتصال بالسيرفر')
}

// rows: the ticked rows · act(row) → promise · getId(row) → key used in the result
export async function runEach(rows, act, getId = r => r.id) {
  const done = []
  const failed = []
  for (const row of rows) {
    try {
      await act(row)
      done.push(getId(row))
    } catch (err) {
      failed.push({ id: getId(row), detail: bulkErrorDetail(err) })
    }
  }
  return { done, failed }
}

// After a run: keep only the rows that failed ticked (so the user can fix and retry them).
export function keepFailedTicked(result) {
  return Object.fromEntries((result?.failed || []).map(f => [f.id, true]))
}
