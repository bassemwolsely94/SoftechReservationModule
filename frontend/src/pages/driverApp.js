/**
 * driverApp.js — pure helpers for /rider (DriverDeliveryApp), UAT W8 2026-11-20.
 *
 * /api/delivery/app/my-route/ and /my-orders/ answer 403 «ليس لديك ملف سائق مرتبط.» for a user
 * who may open /rider (rider module) but has no driver profile linked (supervisor, call center,
 * admin). The screen used to drop that and say «لا توجد مهام حالياً», which reads as "no work".
 */
export const NO_TASKS_TEXT = 'لا توجد مهام حالياً'
export const NO_PROFILE_FALLBACK = 'ليس لديك ملف سائق مرتبط.'

/** The server's refusal text when it refused this user the driver endpoints, else null. */
export function driverRefusal(...errors) {
  for (const e of errors) {
    const st = e?.response?.status
    if (st === 403) {
      const detail = e.response?.data?.detail
      return typeof detail === 'string' && detail.trim() ? detail : NO_PROFILE_FALLBACK
    }
  }
  return null
}

/** Don't retry a refusal (it won't change); retry other failures up to 3 times. */
export function retryUnlessRefused(failureCount, error) {
  const st = error?.response?.status
  if (st === 401 || st === 403) return false
  return failureCount < 3
}
