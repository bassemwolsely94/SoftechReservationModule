/**
 * MobileApprovalsPage.jsx — approvals inbox (route: /m/approvals).
 *
 * A segmented toggle keeps OPERATIONAL and HR approvals separate within one
 * surface (avoids a 5th bottom tab):
 *
 *   تشغيلية (operational):
 *     1. Generic engine, category='operational'  → approvalsApi.pending({category:'operational'})
 *     2. Item price/discount change requests       → pricingApprovalsApi.list({status:'pending'})
 *   HR:
 *     Generic engine, category='hr' (leave/overtime/advance/expense/…)
 *
 * Both engine kinds decide via approvalsApi.decide(id, {decision, notes}); pricing
 * uses its own approve/reject.
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { approvalsApi, pricingApprovalsApi } from '../../api/client'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}
function ago(d) {
  try { return toLatin(formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true })) }
  catch { return '' }
}

function PriceChangeSummary({ oldValues = {}, newValues = {} }) {
  const keys = Object.keys(newValues || {})
  if (keys.length === 0) return null
  return (
    <div className="mt-1.5 space-y-0.5">
      {keys.map(k => (
        <div key={k} className="text-[11px] text-gray-500 flex items-center gap-1.5" dir="ltr">
          <span className="font-mono">{k}</span>
          <span className="text-gray-400">{oldValues?.[k] ?? '—'} → </span>
          <span className="font-semibold text-gray-700">{newValues[k]}</span>
        </div>
      ))}
    </div>
  )
}

function ContextSummary({ body, context = {} }) {
  const entries = Object.entries(context || {}).slice(0, 5)
  if (!body && entries.length === 0) return null
  return (
    <div className="mt-1.5 space-y-0.5">
      {body && <div className="text-xs text-gray-600">{body}</div>}
      {entries.map(([k, v]) => (
        <div key={k} className="text-[11px] text-gray-500">
          <span className="text-gray-400">{k}:</span> {String(v)}
        </div>
      ))}
    </div>
  )
}

const TABS = [
  { key: 'operational', label: 'تشغيلية' },
  { key: 'hr',          label: 'HR' },
]

export default function MobileApprovalsPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('operational')

  const opQuery = useQuery({
    queryKey: ['m-approvals-op'],
    enabled: tab === 'operational',
    queryFn: () => approvalsApi.pending({ category: 'operational' }).then(r => r.data),
  })
  const priceQuery = useQuery({
    queryKey: ['m-approvals-pricing'],
    enabled: tab === 'operational',
    queryFn: () => pricingApprovalsApi.list({ status: 'pending' }).then(r => r.data?.results || r.data),
  })
  const hrQuery = useQuery({
    queryKey: ['m-approvals-hr'],
    enabled: tab === 'hr',
    queryFn: () => approvalsApi.pending({ category: 'hr' }).then(r => r.data),
  })

  const items = useMemo(() => {
    if (tab === 'hr') {
      return (hrQuery.data || []).map(r => ({
        kind: 'approval', id: r.id, when: r.requested_at, overdue: r.is_overdue,
        tag: r.workflow_name, title: r.title, who: r.requested_by_name,
        step: r.current_step_name, body: r.body, context: r.context_data, raw: r,
      })).sort((x, y) => new Date(y.when) - new Date(x.when))
    }
    const a = (opQuery.data || []).map(r => ({
      kind: 'approval', id: r.id, when: r.requested_at, overdue: r.is_overdue,
      tag: r.workflow_name, title: r.title, who: r.requested_by_name,
      step: r.current_step_name, body: r.body, context: r.context_data, raw: r,
    }))
    const p = (priceQuery.data || []).map(r => ({
      kind: 'pricing', id: r.id, when: r.requested_at, overdue: false,
      tag: 'تغيير سعر/خصم', title: r.item_name, who: r.requested_by_name,
      reason: r.reason, oldValues: r.old_values, newValues: r.new_values, raw: r,
    }))
    return [...a, ...p].sort((x, y) => new Date(y.when) - new Date(x.when))
  }, [tab, opQuery.data, priceQuery.data, hrQuery.data])

  const [target, setTarget] = useState(null)   // { kind, id, decision }
  const [notes, setNotes]   = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  async function run() {
    setSaving(true); setError('')
    try {
      if (target.kind === 'approval') {
        await approvalsApi.decide(target.id, { decision: target.decision, notes })
      } else if (target.decision === 'approved') {
        await pricingApprovalsApi.approve(target.id, notes)
      } else {
        await pricingApprovalsApi.reject(target.id, notes)
      }
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['m-approvals-op'] }),
        qc.invalidateQueries({ queryKey: ['m-approvals-pricing'] }),
        qc.invalidateQueries({ queryKey: ['m-approvals-hr'] }),
        qc.invalidateQueries({ queryKey: ['m-approvals-count'] }),
      ])
      setTarget(null); setNotes('')
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر تنفيذ القرار')
    } finally {
      setSaving(false)
    }
  }

  const active  = tab === 'hr' ? [hrQuery] : [opQuery, priceQuery]
  const loading = active.some(q => q.isLoading)
  const errored = active.every(q => q.isError)
  const retry   = () => active.forEach(q => q.refetch())

  return (
    <div className="p-3 space-y-3">
      {/* Segmented toggle */}
      <div className="flex bg-gray-100 rounded-xl p-1">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === t.key ? 'bg-white text-brand-700 shadow-sm' : 'text-gray-500'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <h1 className="text-base font-bold text-gray-900">
          {tab === 'hr' ? 'موافقات الموارد البشرية' : 'الموافقات التشغيلية'}
        </h1>
        {!loading && <span className="text-xs text-gray-400">{toLatin(items.length)} بانتظارك</span>}
      </div>

      {loading ? (
        <MobileLoading />
      ) : errored ? (
        <MobileError text="تعذّر تحميل الموافقات" onRetry={retry} />
      ) : items.length === 0 ? (
        <MobileEmpty icon="🎉" text="لا توجد موافقات بانتظارك" />
      ) : (
        <div className="space-y-2.5">
          {items.map(it => (
            <div key={`${it.kind}-${it.id}`} className="bg-white rounded-2xl border border-gray-200 p-4">
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
                  it.kind === 'pricing' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                }`}>{it.tag}</span>
                {it.overdue && <span className="text-[11px] text-red-600 font-medium">متأخر</span>}
              </div>

              <div className="font-bold text-sm text-gray-900 leading-snug">{it.title}</div>
              {it.kind === 'pricing'
                ? <PriceChangeSummary oldValues={it.oldValues} newValues={it.newValues} />
                : <ContextSummary body={it.body} context={it.context} />}
              {it.kind === 'approval' && it.step && <div className="text-[11px] text-gray-500 mt-0.5">الخطوة: {it.step}</div>}
              {it.reason && <div className="text-xs text-gray-500 mt-1">السبب: {it.reason}</div>}

              <div className="flex items-center justify-between text-xs text-gray-400 mt-2">
                <span>{it.who || '—'}</span>
                <span>{ago(it.when)}</span>
              </div>

              <div className="grid grid-cols-2 gap-2 mt-3">
                <button
                  onClick={() => { setTarget({ kind: it.kind, id: it.id, decision: 'approved' }); setNotes(''); setError('') }}
                  className="py-2.5 rounded-xl bg-green-600 text-white text-sm font-semibold active:opacity-90"
                >اعتماد</button>
                <button
                  onClick={() => { setTarget({ kind: it.kind, id: it.id, decision: 'rejected' }); setNotes(''); setError('') }}
                  className="py-2.5 rounded-xl bg-red-500 text-white text-sm font-semibold active:opacity-90"
                >رفض</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Decision sheet */}
      {target && (
        <div className="fixed inset-0 bg-black/40 flex items-end justify-center z-50" onClick={() => !saving && setTarget(null)}>
          <div className="bg-white rounded-t-2xl shadow-2xl w-full p-5 pb-safe-bottom" dir="rtl" onClick={e => e.stopPropagation()}>
            <h3 className="font-bold text-gray-800 text-base mb-1 text-center">
              {target.decision === 'approved' ? 'اعتماد الطلب؟' : 'رفض الطلب؟'}
            </h3>
            <textarea
              rows={2}
              className="input-field w-full resize-none mt-3"
              placeholder={target.decision === 'rejected' ? 'سبب الرفض (مستحسن)...' : 'ملاحظة (اختياري)...'}
              value={notes}
              onChange={e => setNotes(e.target.value)}
              autoFocus
            />
            {error && <div className="text-sm text-red-600 mt-2 text-center">{error}</div>}
            <div className="flex gap-2 mt-4">
              <button onClick={() => setTarget(null)} disabled={saving} className="btn-secondary flex-1 text-sm">إلغاء</button>
              <button onClick={run} disabled={saving}
                className={`flex-1 text-sm text-white rounded-xl font-medium disabled:opacity-50 ${target.decision === 'approved' ? 'bg-green-600' : 'bg-red-500'}`}>
                {saving ? 'جارٍ التنفيذ...' : 'تأكيد'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
