/**
 * queryErrors.js — plain Arabic text for a failed API read (full audit FE-7).
 *
 * A failed list must never look like an empty one: a 403 or a 500 used to show «لا توجد سجلات».
 * The server's public error text (core/errors.public_error → `detail` / `error`) is used when it is
 * short; otherwise a message by status. 401 is not shown here: the API client refreshes the session
 * or sends the user to /login.
 */

const BY_STATUS = {
  400: 'الطلب غير صحيح',
  403: 'غير مسموح لك بعرض هذه البيانات',
  404: 'البيانات المطلوبة غير موجودة',
  408: 'السيرفر تأخر في الرد',
  429: 'طلبات كثيرة — حاول بعد قليل',
  502: 'السيرفر لا يرد الآن',
  503: 'السيرفر مشغول أو متوقف مؤقتًا',
  504: 'السيرفر تأخر في الرد',
}

export function queryErrorStatus(err) {
  return err?.response?.status ?? null
}

/** True for errors the page should not report itself (session expiry is handled by the API client). */
export function isQuietError(err) {
  return queryErrorStatus(err) === 401 || err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED'
}

export function describeQueryError(err) {
  if (!err) return ''
  const status = queryErrorStatus(err)
  const data = err.response?.data
  const server = typeof data?.detail === 'string' ? data.detail
    : typeof data?.error === 'string' ? data.error : ''
  if (server && server.length <= 160 && !/<[a-z!]/i.test(server)) return server
  if (status && BY_STATUS[status]) return BY_STATUS[status]
  if (status >= 500) return `خطأ في السيرفر (${status})`
  if (status) return `تعذّر التحميل (${status})`
  if (err.code === 'ECONNABORTED') return 'السيرفر تأخر في الرد'
  if (err.response === undefined && (err.isAxiosError || err.request)) return 'لا يوجد اتصال بالسيرفر'
  return 'تعذّر تحميل البيانات'
}
