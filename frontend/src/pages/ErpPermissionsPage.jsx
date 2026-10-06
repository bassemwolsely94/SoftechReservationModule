/**
 * ErpPermissionsPage — review & adjust SOFTECH→platform permission inheritance.
 *   • System→module map (add / remove, re-derives instantly)
 *   • Per-group derived module permissions (view/edit/cost)
 *   • SOFTECH systems reference (screen counts)
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi } from '../api/client'

const PLATFORM_MODULES = [
  'catalog', 'customers', 'vouchers', 'purchasing', 'invoices', 'transfers',
  'sync', 'callcenter', 'delivery', 'insurance', 'finance', 'stockcount', 'shortage',
]

function Check({ on }) {
  return <span className={on ? 'text-emerald-600' : 'text-gray-300'}>{on ? '✓' : '·'}</span>
}

export default function ErpPermissionsPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('map')
  const [newMap, setNewMap] = useState({ system: '', module: 'catalog', note: '' })

  const { data: map } = useQuery({ queryKey: ['erp-map'], queryFn: () => usersApi.erpMap().then(r => r.data) })
  const { data: systems } = useQuery({ queryKey: ['erp-systems'], queryFn: () => usersApi.erpSystems().then(r => r.data) })
  const { data: groups } = useQuery({ queryKey: ['erp-groups'], queryFn: () => usersApi.erpGroups().then(r => r.data) })

  const addMap = useMutation({
    mutationFn: (d) => usersApi.erpMapAdd(d),
    onSuccess: () => { qc.invalidateQueries(['erp-map']); qc.invalidateQueries(['erp-groups']); setNewMap({ system: '', module: 'catalog', note: '' }) },
  })
  const delMap = useMutation({
    mutationFn: (id) => usersApi.erpMapDelete(id),
    onSuccess: () => { qc.invalidateQueries(['erp-map']); qc.invalidateQueries(['erp-groups']) },
  })
  const rebuild = useMutation({
    mutationFn: () => usersApi.erpRebuild(),
    onSuccess: () => { qc.invalidateQueries(['erp-groups']); qc.invalidateQueries(['erp-map']) },
  })

  // module → systems (for the map view)
  const byModule = {}
  ;(map || []).forEach(m => { (byModule[m.module] = byModule[m.module] || []).push(m) })

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">صلاحيات Softech الموروثة</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              تُشتق صلاحيات الوحدات تلقائياً من مجموعة المستخدم في Softech — Softech هو المصدر، يُعاد البناء يومياً.
            </p>
          </div>
          <button onClick={() => rebuild.mutate()} disabled={rebuild.isPending}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-60">
            {rebuild.isPending ? 'جاري…' : 'إعادة الاشتقاق الآن'}
          </button>
        </div>

        <div className="flex gap-1 border-b border-gray-200">
          {[['map', 'ربط الأنظمة بالوحدات'], ['groups', 'صلاحيات المجموعات'], ['systems', 'أنظمة Softech']].map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === k ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500'}`}>
              {l}
            </button>
          ))}
        </div>

        {/* ── System → module map ─────────────────────────────────────────── */}
        {tab === 'map' && (
          <div className="space-y-4">
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-2 text-sm text-amber-800">
              أكّد الربط الغامض: <b>transfers</b> يأتي من نظام المبيعات للفروع (MB). عدّل أدناه إن لزم.
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-end gap-2 flex-wrap">
              <div>
                <label className="block text-xs text-gray-500 mb-1">نظام Softech</label>
                <input value={newMap.system} onChange={e => setNewMap(s => ({ ...s, system: e.target.value.toUpperCase() }))}
                  placeholder="IM" className="border border-gray-300 rounded px-2 py-1.5 text-sm w-20" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">الوحدة</label>
                <select value={newMap.module} onChange={e => setNewMap(s => ({ ...s, module: e.target.value }))}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm">
                  {PLATFORM_MODULES.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <input value={newMap.note} onChange={e => setNewMap(s => ({ ...s, note: e.target.value }))}
                placeholder="ملاحظة" className="border border-gray-300 rounded px-2 py-1.5 text-sm flex-1 min-w-[120px]" />
              <button onClick={() => newMap.system && addMap.mutate({ system: newMap.system, module: newMap.module, note: newMap.note })}
                className="bg-emerald-600 text-white text-sm px-4 py-1.5 rounded-lg hover:bg-emerald-700">إضافة ربط</button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {Object.entries(byModule).map(([module, rows]) => (
                <div key={module} className="bg-white rounded-xl border border-gray-200 p-3">
                  <div className="font-bold text-gray-800 text-sm mb-2">{module}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {rows.map(r => (
                      <span key={r.id} className="inline-flex items-center gap-1 bg-blue-50 border border-blue-200 rounded px-2 py-0.5 text-xs">
                        <span className="font-mono">{r.system}</span>
                        <button onClick={() => delMap.mutate(r.id)} className="text-red-400 hover:text-red-600">✕</button>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Per-group derived permissions ───────────────────────────────── */}
        {tab === 'groups' && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="bg-gray-50 border-b text-right">
                <th className="px-3 py-2 sticky right-0 bg-gray-50">المجموعة</th>
                {PLATFORM_MODULES.map(m => <th key={m} className="px-2 py-2 text-center whitespace-nowrap">{m}</th>)}
              </tr></thead>
              <tbody>
                {(groups || []).map(g => (
                  <tr key={g.usergroup} className="border-b border-gray-100">
                    <td className="px-3 py-2 sticky right-0 bg-white font-medium whitespace-nowrap">
                      <span className="font-mono text-gray-400">{g.usergroup}</span> {g.name}
                    </td>
                    {PLATFORM_MODULES.map(m => {
                      const p = g.modules?.[m]
                      const show = p && p.view
                      return (
                        <td key={m} className="px-2 py-2 text-center">
                          {show ? (
                            <span title={`view${p.edit ? ' · edit' : ''}${p.see_cost ? ' · cost' : ''}`}>
                              <Check on={p.view} />
                              {p.edit && <span className="text-blue-500">✎</span>}
                              {p.see_cost && <span className="text-amber-500">$</span>}
                            </span>
                          ) : <span className="text-gray-200">·</span>}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="p-3 text-xs text-gray-400 border-t">
              ✓ عرض · <span className="text-blue-500">✎</span> تعديل · <span className="text-amber-500">$</span> رؤية التكلفة/المال
            </div>
          </div>
        )}

        {/* ── SOFTECH systems reference ───────────────────────────────────── */}
        {tab === 'systems' && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead><tr className="bg-gray-50 border-b text-right">
                <th className="px-3 py-2">النظام</th><th className="px-3 py-2">عدد الشاشات</th><th className="px-3 py-2">مثال</th>
                <th className="px-3 py-2">مربوط بـ</th>
              </tr></thead>
              <tbody>
                {(systems || []).map(s => {
                  const mods = (map || []).filter(m => m.system === s.system).map(m => m.module)
                  return (
                    <tr key={s.system} className="border-b border-gray-100">
                      <td className="px-3 py-2 font-mono font-semibold">{s.system}</td>
                      <td className="px-3 py-2">{s.screens}</td>
                      <td className="px-3 py-2 text-gray-500">{s.sample}</td>
                      <td className="px-3 py-2">
                        {mods.length ? mods.map(m => <span key={m} className="inline-block bg-blue-50 text-blue-700 rounded px-1.5 py-0.5 text-xs ml-1">{m}</span>)
                          : <span className="text-gray-300">— غير مربوط</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
