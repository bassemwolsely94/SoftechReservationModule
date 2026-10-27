/**
 * components/HRForm.jsx
 *
 * Shared building blocks for the HR request forms:
 *   - weekdayAr / DateField  — a date input that shows the Arabic weekday name
 *   - IdentityFields         — HR code (mandatory) + on-behalf-of subject picker
 *                              (self / another user / non-login employee) +
 *                              requester-nominated approver multi-select
 *
 * IdentityFields is self-contained (loads the staff list) and emits a payload
 * ready to spread into a submit body:
 *   { subject_staff?, employee_hr_code, employee_name?, approver_ids }
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { usersApi } from '../api/client'
import useAuthStore from '../store/authStore'

// ── Weekday helper ──────────────────────────────────────────────────────────
export function weekdayAr(dateStr) {
  if (!dateStr) return ''
  try { return new Date(dateStr).toLocaleDateString('ar-EG', { weekday: 'long' }) }
  catch { return '' }
}

export function DateField({ label, value, onChange, required }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      <input type="date" value={value || ''} onChange={e => onChange(e.target.value)}
        className="w-full border rounded-lg px-3 py-2 text-sm" />
      {value && <div className="text-[11px] text-brand-600 mt-1">📅 {weekdayAr(value)}</div>}
    </div>
  )
}

// ── Time field with a small helper (kept here for symmetry) ─────────────────
export function TimeField({ label, value, onChange, required }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      <input type="time" value={value || ''} onChange={e => onChange(e.target.value)}
        className="w-full border rounded-lg px-3 py-2 text-sm" />
    </div>
  )
}

// ── Identity + approvers ────────────────────────────────────────────────────
const MANUAL = 'manual'

export function IdentityFields({ onChange }) {
  const { user } = useAuthStore()
  const myId = user?.id
  const myHrCode = user?.hr_code || ''

  const { data } = useQuery({
    queryKey: ['hr', 'staff-options'],
    queryFn:  () => usersApi.list({ page_size: 500 }).then(r => r.data),
    staleTime: 5 * 60_000,
  })
  const staff = data?.results || data || []

  // subject: myId (self) | a staff id | MANUAL (non-login)
  const [subject, setSubject] = useState('self')
  const [hrCode, setHrCode]   = useState(myHrCode)
  const [name, setName]       = useState('')
  const [approverIds, setApproverIds] = useState([])
  const [approverSearch, setApproverSearch] = useState('')

  // Emit the payload whenever any part changes
  useEffect(() => {
    const payload = { employee_hr_code: hrCode, approver_ids: approverIds }
    if (subject === 'self' && myId) payload.subject_staff = myId
    else if (subject !== 'self' && subject !== MANUAL) payload.subject_staff = Number(subject)
    if (subject === MANUAL) payload.employee_name = name
    onChange(payload)
  }, [subject, hrCode, name, approverIds]) // eslint-disable-line

  const onSubjectChange = (val) => {
    setSubject(val)
    if (val === 'self')      { setHrCode(myHrCode); setName('') }
    else if (val === MANUAL) { setHrCode(''); setName('') }
    else {
      const s = staff.find(x => String(x.id) === String(val))
      setHrCode(s?.hr_code || ''); setName(s?.full_name || '')
    }
  }

  const toggleApprover = (id) => setApproverIds(prev =>
    prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const filteredApprovers = useMemo(() => {
    const q = approverSearch.trim()
    return staff.filter(s => !q || (s.full_name || '').includes(q) || String(s.hr_code || '').includes(q))
  }, [staff, approverSearch])

  const selectedNames = staff.filter(s => approverIds.includes(s.id)).map(s => s.full_name)

  return (
    <div className="border-t border-gray-200 pt-4 mt-2 space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="block text-xs text-gray-500 mb-1">الطلب باسم</label>
          <select value={subject} onChange={e => onSubjectChange(e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm">
            <option value="self">نفسي</option>
            <option value={MANUAL}>موظف بدون حساب (إدخال يدوي)</option>
            {staff.filter(s => s.id !== myId).map(s => (
              <option key={s.id} value={s.id}>{s.full_name}{s.hr_code ? ` — ${s.hr_code}` : ''}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">كود الموارد البشرية <span className="text-red-500">*</span></label>
          <input value={hrCode} onChange={e => setHrCode(e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="كود الموظف" />
        </div>
        {subject === MANUAL && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">اسم الموظف <span className="text-red-500">*</span></label>
            <input value={name} onChange={e => setName(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="الاسم" />
          </div>
        )}
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">
          المعتمِدون المختارون {selectedNames.length > 0 && <span className="text-brand-600">({selectedNames.length})</span>}
        </label>
        <input value={approverSearch} onChange={e => setApproverSearch(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm mb-2" placeholder="ابحث عن معتمِد بالاسم أو الكود..." />
        <div className="max-h-32 overflow-y-auto border rounded-lg divide-y divide-gray-100">
          {filteredApprovers.length === 0 ? (
            <div className="text-xs text-gray-400 p-3 text-center">لا نتائج</div>
          ) : filteredApprovers.slice(0, 50).map(s => (
            <label key={s.id} className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-gray-50 cursor-pointer">
              <input type="checkbox" checked={approverIds.includes(s.id)} onChange={() => toggleApprover(s.id)} />
              <span>{s.full_name}</span>
              <span className="text-xs text-gray-400">{s.role_label || s.role}</span>
            </label>
          ))}
        </div>
        <p className="text-[11px] text-gray-400 mt-1">
          يكفي اعتماد أي واحد منهم. تبقى موافقة المدير المباشر مطلوبة دائماً.
        </p>
      </div>
    </div>
  )
}
