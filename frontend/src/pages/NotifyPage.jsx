/**
 * NotifyPage.jsx  —  /notify   (PUBLIC, no auth)
 * Customer self-service: scan a shelf QR (or open a link) for an out-of-stock
 * item and leave a phone number to be notified when it's back. Lands as a demand.
 */
import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

const BRAND = 'rgb(var(--c-brand-600))'

function validPhone(raw) {
  const d = (raw || '').replace(/\D/g, '')
  return /^01\d{9}$/.test(d) || /^0[2-9]\d{6,8}$/.test(d)
}

export default function NotifyPage() {
  const [params] = useSearchParams()
  const itemId   = params.get('item')
  const urlBranch = params.get('branch')

  const [item, setItem]       = useState(null)
  const [branches, setBranches] = useState([])
  const [branch, setBranch]   = useState(urlBranch || '')
  const [phone, setPhone]     = useState('')
  const [name, setName]       = useState('')
  const [state, setState]     = useState('form')   // form | done | error
  const [err, setErr]         = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (itemId) {
      fetch(`/api/demand/public/item/?id=${encodeURIComponent(itemId)}`)
        .then(r => r.json()).then(d => { if (d.found) setItem(d) }).catch(() => {})
    }
    if (!urlBranch) {
      fetch('/api/demand/public/branches/')
        .then(r => r.json()).then(d => setBranches(d.branches || [])).catch(() => {})
    }
  }, [itemId, urlBranch])

  async function submit() {
    if (!validPhone(phone)) { setErr('من فضلك أدخل رقم موبايل صحيح (11 رقماً يبدأ بـ 01)'); return }
    if (!branch)            { setErr('اختر الفرع'); return }
    setSubmitting(true); setErr('')
    try {
      const res = await fetch('/api/demand/public/interest/', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item: itemId, branch, phone, name }),
      })
      const data = await res.json()
      if (res.ok) setState('done')
      else { setErr(data.detail || 'تعذّر التسجيل، حاول مرة أخرى'); }
    } catch { setErr('تعذّر الاتصال، حاول مرة أخرى') }
    finally { setSubmitting(false) }
  }

  return (
    <div dir="rtl" className="min-h-screen flex items-center justify-center p-4"
      style={{ background: `linear-gradient(135deg, ${BRAND} 0%, rgb(var(--c-brand-400)) 100%)` }}>
      <div className="w-full max-w-md bg-white rounded-3xl shadow-2xl overflow-hidden">
        <div className="px-6 py-5 text-center" style={{ background: BRAND }}>
          <div className="text-white text-xl font-black">صيدليات الرزيقي</div>
          <div className="text-white/70 text-xs mt-0.5">أبلغني عند توفر الصنف</div>
        </div>

        {state === 'done' ? (
          <div className="p-8 text-center">
            <div className="text-5xl mb-3">✅</div>
            <h2 className="text-lg font-black text-gray-800 mb-2">تم تسجيل طلبك بنجاح</h2>
            <p className="text-sm text-gray-500 leading-relaxed">
              سنتواصل معك على الرقم {phone} فور توفر
              {item ? ` "${item.name}"` : ' الصنف'}. شكراً لك 🌿
            </p>
          </div>
        ) : !itemId ? (
          <div className="p-8 text-center text-gray-500 text-sm">
            <div className="text-4xl mb-3">🔍</div>
            امسح رمز QR الموجود على الرف لتسجيل طلبك على صنف معيّن.
          </div>
        ) : (
          <div className="p-6 space-y-4">
            {/* Item */}
            <div className="bg-brand-50 border border-brand-100 rounded-xl p-4 text-center">
              <div className="text-xs text-brand-600 mb-1">الصنف المطلوب</div>
              <div className="font-bold text-gray-800">{item ? item.name : '...'}</div>
              {item?.softech_id && <div className="text-xs text-gray-400 font-mono mt-0.5">{item.softech_id}</div>}
            </div>

            {!urlBranch && (
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">الفرع</label>
                <select className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-brand-400"
                  value={branch} onChange={e => setBranch(e.target.value)}>
                  <option value="">اختر الفرع...</option>
                  {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">رقم الموبايل *</label>
              <input className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-brand-400"
                placeholder="01003280328" dir="ltr" inputMode="numeric"
                value={phone} onChange={e => setPhone(e.target.value)} />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">الاسم (اختياري)</label>
              <input className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-brand-400"
                placeholder="اسمك" value={name} onChange={e => setName(e.target.value)} />
            </div>

            {err && <div className="text-sm text-red-600 bg-red-50 rounded-xl px-3 py-2">{err}</div>}

            <button onClick={submit} disabled={submitting}
              className="w-full py-3 rounded-xl text-white font-bold text-sm disabled:opacity-50"
              style={{ background: BRAND }}>
              {submitting ? 'جارٍ التسجيل...' : '🔔 أبلغني عند توفره'}
            </button>
            <p className="text-[11px] text-gray-400 text-center leading-relaxed">
              بتسجيل رقمك توافق على تواصل الصيدلية معك بخصوص هذا الصنف فقط.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
