// Full audit FE-10: decide several approval requests at once.
//
// There is no bulk endpoint on purpose: each request goes through the same POST
// /approvals/requests/<id>/decide/ as a single decision, so the server still checks, per request,
// that this user is the approver for its current step (and not its requester). One at a time, in
// order; a refusal on one does not stop the others, and every refusal is reported with its reason.
export async function decideMany(ids, { decision, notes = '' }, decide) {
  const done = []
  const failed = []
  for (const id of ids) {
    try {
      await decide(id, { decision, notes })
      done.push(id)
    } catch (err) {
      const d = err?.response?.data
      const detail = (typeof d?.detail === 'string' && d.detail) || (typeof d?.error === 'string' && d.error)
        || (err?.response ? `خطأ ${err.response.status}` : 'لا يوجد اتصال بالسيرفر')
      failed.push({ id, detail })
    }
  }
  return { done, failed }
}

// A rejection always carries its reason (the help asks for it; the requester sees it).
export function canBulkDecide(decision, count, notes) {
  if (count < 1) return false
  return decision === 'approved' || (notes || '').trim().length > 0
}
