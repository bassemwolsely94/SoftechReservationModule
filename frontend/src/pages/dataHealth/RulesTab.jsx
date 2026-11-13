/**
 * Rules tab (القواعد) of /data-health — admin only (the server refuses everyone else).
 * One grid of the retention register; clicking a rule opens an inline editor under it (no modal):
 * mode, period (never below the minimum), a required reason, Save and Preview. Every refusal comes from
 * the server (policy.set_policy) and is shown inline in Arabic.
 */
import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { dataHealthApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { TD, TH, errText, fmtBytes, fmtDate, fmtInt } from './format'

const MODE_LABEL = { off: 'متوقفة', preview: 'معاينة فقط', on: 'تعمل' }
const MODE_CLS = {
  off: 'bg-gray-100 text-gray-600 border-gray-200',
  preview: 'bg-sky-50 text-sky-800 border-sky-200',
  on: 'bg-emerald-50 text-emerald-700 border-emerald-200',
}
const KIND_LABEL = { row: 'سجلات', file: 'ملفات', p56: 'صيانة يومية' }
const LOCKED_AR = 'مقفلة حتى الانتقال إلى السيرفر'

const ruleValue = (r, key) => {
  if (key === 'last_real_at') return r.last_real?.at
  if (key === 'last_preview_count') return r.last_preview?.count
  return r[key]
}

function LineText({ line, preview }) {
  if (!line) return <span className="text-gray-400">—</span>
  if (line.error) return <span className="text-red-600" title={line.error}>فشل · {fmtDate(line.at, true)}</span>
  return (
    <span>
      {fmtInt(line.count)}{line.bytes ? ` · ${fmtBytes(line.bytes)}` : ''}
      <span className="text-gray-400 text-xs ms-1">· {fmtDate(line.at)}</span>
      {preview && line.skipped_shared ? <span className="text-xs text-gray-500 ms-1">(تخطّى {fmtInt(line.skipped_shared)} مشتركة)</span> : null}
      {!preview && line.stopped_by_breaker ? <span className="text-xs text-amber-700 ms-1">(أوقفها حد الأمان)</span> : null}
    </span>
  )
}

function RuleEditor({ rule, fileRulesLocked, onDone }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState(rule.stored_mode || rule.mode)
  const [days, setDays] = useState(rule.keep_days ?? '')
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState(null)

  const setRow = row => qc.setQueryData(['data-health', 'rules'], old => (old
    ? { ...old, rules: old.rules.map(r => (r.key === row.key ? row : r)) } : old))

  const save = useMutation({
    mutationFn: () => {
      const body = { reason }
      if (mode !== (rule.stored_mode || rule.mode)) body.mode = mode
      if (rule.can_change_days && days !== '' && Number(days) !== rule.keep_days) body.keep_days = Number(days)
      return dataHealthApi.updateRule(rule.key, body)
    },
    onSuccess: ({ data }) => { setRow(data); setReason(''); setMsg({ ok: true, text: 'تم الحفظ وسُجّل في سجل المراجعة.' }) },
    onError: e => setMsg({ ok: false, text: errText(e) }),
  })
  const preview = useMutation({
    mutationFn: () => dataHealthApi.preview(rule.key),
    onSuccess: ({ data }) => { setRow(data); setMsg({ ok: true, text: 'تمت المعاينة. لم يُحذف أي شيء.' }) },
    onError: e => setMsg({ ok: false, text: errText(e) }),
  })

  if (!rule.changeable) {
    return (
      <p className="text-sm text-gray-600">
        هذه خطوة قائمة في الصيانة اليومية وتعمل دائمًا بمدتها الحالية ({rule.keep_days != null ? `${fmtInt(rule.keep_days)} يوم` : '—'}). لا تُعدّل من هنا.
      </p>
    )
  }
  const locked = rule.kind === 'file' && fileRulesLocked
  const busy = save.isPending || preview.isPending
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-600">{rule.reason}</p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-gray-600">الوضع
          <select className="input-field mt-1 block" value={mode} onChange={e => setMode(e.target.value)}>
            <option value="off">{MODE_LABEL.off}</option>
            <option value="preview">{MODE_LABEL.preview}</option>
            <option value="on" disabled={locked}>{MODE_LABEL.on}{locked ? ` (${LOCKED_AR})` : ''}</option>
          </select>
        </label>
        {rule.can_change_days && (
          <label className="text-xs text-gray-600">مدة الاحتفاظ (يوم)
            <input type="number" className="input-field mt-1 block w-32" min={rule.minimum_days ?? undefined} step="1"
                   value={days} onChange={e => setDays(e.target.value === '' ? '' : e.target.value)} />
            <span className="block text-[11px] text-gray-400 mt-0.5">الحد الأدنى {fmtInt(rule.minimum_days)} يوم</span>
          </label>
        )}
        <label className="text-xs text-gray-600 flex-1 min-w-[220px]">سبب التعديل (إلزامي)
          <input type="text" className="input-field mt-1 block w-full" value={reason} maxLength={500}
                 onChange={e => setReason(e.target.value)} placeholder="لماذا تغيّر هذه القاعدة؟" />
        </label>
        <button type="button" className="btn-primary" data-tour="data-health-main-rule-save"
                disabled={busy || !reason.trim()} onClick={() => { setMsg(null); save.mutate() }}>
          حفظ
        </button>
        <button type="button" className="btn-secondary" data-tour="data-health-main-rule-preview"
                disabled={busy} onClick={() => { setMsg(null); preview.mutate() }}>
          {preview.isPending ? 'جارٍ المعاينة…' : 'معاينة'}
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>إغلاق</button>
      </div>
      {locked && <p className="text-xs text-amber-700">{LOCKED_AR}: تبقى قواعد الملفات في وضع المعاينة.</p>}
      {!rule.preview_fresh && <p className="text-xs text-gray-500">التشغيل يحتاج معاينة ناجحة حديثة (أقل من ٧ أيام).</p>}
      {msg && <p className={`text-sm ${msg.ok ? 'text-emerald-700' : 'text-red-600'}`} role="status">{msg.text}</p>}
      {rule.changed_at && (
        <p className="text-xs text-gray-500">
          آخر تعديل: {rule.changed_by || '—'} · {fmtDate(rule.changed_at, true)}{rule.policy_reason ? ` · «${rule.policy_reason}»` : ''}
        </p>
      )}
    </div>
  )
}

export default function RulesTab() {
  const [open, setOpen] = useState(null)
  const q = useQuery({ queryKey: ['data-health', 'rules'], queryFn: () => dataHealthApi.rules().then(r => r.data) })
  const rules = q.data?.rules || []
  const { sorted, headerProps: h } = useSortableRows(rules, { getValue: ruleValue, persistKey: 'data-health-rules' })

  if (q.isLoading) return <p className="text-sm text-gray-500">جارٍ التحميل…</p>
  if (q.isError) return <p className="text-sm text-red-600">{errText(q.error)}</p>
  return (
    <div className="card p-0 overflow-x-auto" data-tour="data-health-main-rules">
      {q.data.file_rules_locked && (
        <p className="px-4 py-2 text-xs text-amber-800 bg-amber-50 border-b border-amber-100">
          قواعد الملفات {LOCKED_AR}، فلا تحذف أي ملف حتى يُفعّل ذلك على السيرفر.
        </p>
      )}
      <table className="w-full">
        <thead className="bg-gray-50"><tr>
          <SortTh {...h('label_ar', 'text')} className={TH}>القاعدة</SortTh>
          <SortTh {...h('kind', 'text')} className={TH}>النوع</SortTh>
          <SortTh {...h('mode', 'text')} className={TH}>الوضع</SortTh>
          <SortTh {...h('keep_days', 'number')} className={TH}>المدة (يوم)</SortTh>
          <SortTh {...h('last_real_at', 'date')} className={TH}>آخر تشغيل فعلي</SortTh>
          <SortTh {...h('last_preview_count', 'number')} className={TH}>آخر معاينة</SortTh>
        </tr></thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map(r => (
            <Fragment key={r.key}>
              <tr className={`cursor-pointer hover:bg-gray-50 ${open === r.key ? 'bg-gray-50' : ''}`}
                  onClick={() => setOpen(open === r.key ? null : r.key)} aria-expanded={open === r.key}>
                <td className={TD}>{r.label_ar}</td>
                <td className={TD}>{KIND_LABEL[r.kind] || r.kind}</td>
                <td className={TD}>
                  <span className={`inline-block rounded border px-1.5 py-0.5 text-xs ${MODE_CLS[r.mode] || ''}`}>{MODE_LABEL[r.mode] || r.mode}</span>
                  {r.locked && <span className="ms-1 text-[11px] text-amber-700">🔒</span>}
                </td>
                <td className={`${TD} tabular-nums`}>{fmtInt(r.keep_days)}</td>
                <td className={TD}><LineText line={r.last_real} /></td>
                <td className={TD}><LineText line={r.last_preview} preview /></td>
              </tr>
              {open === r.key && (
                <tr><td colSpan={6} className="px-4 py-3 bg-gray-50">
                  <RuleEditor rule={r} fileRulesLocked={q.data.file_rules_locked} onDone={() => setOpen(null)} />
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
