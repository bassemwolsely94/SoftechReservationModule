/**
 * DevicesTab — أجهزتي: the Windows machines allowed to run the robot for me. «إضافة هذا الجهاز»
 * creates one and shows its token ONCE (the server keeps only a hash — a later list never has
 * it). Revoking is one click; the server checks the device is mine (admin: any).
 */
import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { asList, errText, fmtTime } from './shared.jsx'

const ONLINE_MS = 2 * 60 * 1000

function TokenOnce({ token, onDismiss }) {
  const [copied, setCopied] = useState(false)
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(token)
      setCopied(true)
    } catch {
      // clipboard blocked: select the text so Ctrl+C works
      document.getElementById('rpa-token')?.select()
    }
  }, [token])
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
      <div className="text-sm font-semibold">انسخه الآن، لن يظهر مرة أخرى</div>
      <div className="flex flex-wrap items-center gap-2">
        <input id="rpa-token" readOnly dir="ltr" value={token} onFocus={e => e.target.select()}
               className="input-field font-mono text-xs flex-1 min-w-[16rem]" />
        <button type="button" className="btn-primary text-sm" onClick={copy}>{copied ? 'تم النسخ' : 'نسخ'}</button>
        <button type="button" className="btn-ghost text-sm" onClick={onDismiss}>تم، أخفِه</button>
      </div>
      <div className="text-xs text-muted">ضعه في إعدادات برنامج الروبوت على هذا الجهاز. أي شخص يملكه يستطيع تشغيل الروبوت باسمك.</div>
    </div>
  )
}

const online = d => !d.revoked_at && d.last_seen_at && Date.now() - new Date(d.last_seen_at).getTime() < ONLINE_MS
const devValue = (d, k) => (k === 'state' ? (d.revoked_at ? 2 : online(d) ? 0 : 1) : d[k])

export default function DevicesTab() {
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [token, setToken] = useState('')
  const [err, setErr] = useState('')
  const q = useQuery({ queryKey: ['rpa', 'devices'], queryFn: () => rpaApi.devices().then(r => r.data), refetchInterval: 30000 })
  const rows = useMemo(() => asList(q.data), [q.data])
  const { sorted, headerProps } = useSortableRows(rows, { getValue: devValue, persistKey: 'rpa-devices' })

  const add = useMutation({
    mutationFn: () => rpaApi.addDevice(label.trim()).then(r => r.data),
    onSuccess: data => {
      setErr(''); setLabel(''); setToken(data?.token || '')
      qc.invalidateQueries({ queryKey: ['rpa'] })
    },
    onError: e => setErr(errText(e)),
  })
  const revoke = useMutation({
    mutationFn: id => rpaApi.revokeDevice(id),
    onSuccess: () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa'] }) },
    onError: e => setErr(errText(e)),
  })

  return (
    <div className="space-y-4">
      <div data-tour="rpa-main-devices" className="card p-4 space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="label" htmlFor="rpa-device-label">اسم الجهاز</label>
            <input id="rpa-device-label" className="input-field" value={label} maxLength={120}
                   placeholder="مثال: كمبيوتر مخزن الفرع"
                   onChange={e => setLabel(e.target.value)} />
          </div>
          <button type="button" className="btn-primary" disabled={!label.trim() || add.isPending} onClick={() => add.mutate()}>
            {add.isPending ? 'جارٍ الإضافة…' : 'إضافة هذا الجهاز'}
          </button>
        </div>
        {err && <div className="text-sm text-red-600">{err}</div>}
        {token && <TokenOnce token={token} onDismiss={() => setToken('')} />}
      </div>

      <div className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted border-b border-line">
              <SortTh {...headerProps('label')} className="p-2 text-start">الجهاز</SortTh>
              <SortTh {...headerProps('staff_name')} className="p-2 text-start">صاحبه</SortTh>
              <SortTh {...headerProps('last_seen_at', 'date')} className="p-2 text-start">آخر ظهور</SortTh>
              <SortTh {...headerProps('state', 'number')} className="p-2 text-start">الحالة</SortTh>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {sorted.map(d => (
              <tr key={d.id} className="border-b border-line">
                <td className="p-2">{d.label}</td>
                <td className="p-2 text-muted">{d.staff_name || '—'}</td>
                <td className="p-2 text-xs whitespace-nowrap">{fmtTime(d.last_seen_at)}</td>
                <td className="p-2">
                  {d.revoked_at ? <span className="text-muted">ملغى</span>
                    : online(d) ? <span className="text-green-700 dark:text-green-300">متصل</span>
                      : <span className="text-muted">غير متصل</span>}
                </td>
                <td className="p-2 text-end">
                  {!d.revoked_at && (
                    <button type="button" className="btn-ghost text-sm" disabled={revoke.isPending} onClick={() => revoke.mutate(d.id)}>
                      إلغاء الجهاز
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {q.isLoading && <tr><td colSpan={5} className="p-6 text-center text-muted">جارٍ التحميل…</td></tr>}
            {q.isError && <tr><td colSpan={5} className="p-6 text-center text-red-600">تعذّر تحميل الأجهزة.</td></tr>}
            {!q.isLoading && !q.isError && !rows.length && <tr><td colSpan={5} className="p-6 text-center text-muted">لا توجد أجهزة.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
