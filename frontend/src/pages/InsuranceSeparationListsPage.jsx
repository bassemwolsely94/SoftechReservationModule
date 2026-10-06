/**
 * InsuranceSeparationListsPage — manage name separation lists (قوائم فصل الأسماء).
 * Names on an active list get flagged across motalbas so they can be pulled out
 * and billed separately (e.g. شركة الخدمات الطبية).
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'

const inp = 'w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500'

export default function InsuranceSeparationListsPage() {
  const navigate = useNavigate()
  const [lists, setLists]     = useState([])
  const [sel, setSel]         = useState(null)   // selected list object
  const [names, setNames]     = useState([])
  const [newLabel, setNewLabel] = useState('')
  const [bulkText, setBulkText] = useState('')
  const [msg, setMsg]         = useState(null)
  const [editListId, setEditListId] = useState(null)
  const [editLabel, setEditLabel]   = useState('')
  const [editNameId, setEditNameId] = useState(null)
  const [editNameVal, setEditNameVal] = useState('')
  const [nameFilter, setNameFilter] = useState('')

  const loadLists = () => insuranceApi.separationLists().then(r => setLists(r.data.results || r.data))
  useEffect(() => { loadLists() }, [])
  const loadNames = (l) => { setSel(l); insuranceApi.separationNames(l.id).then(r => setNames(r.data)) }

  const flash = (t) => { setMsg(t); setTimeout(() => setMsg(null), 4000) }

  const createList = async () => {
    if (!newLabel.trim()) return
    await insuranceApi.createSeparationList({ label: newLabel.trim() })
    setNewLabel(''); loadLists()
  }
  const delList = async (l) => {
    if (!window.confirm(`حذف قائمة "${l.label}" وكل أسمائها؟`)) return
    await insuranceApi.deleteSeparationList(l.id)
    if (sel?.id === l.id) { setSel(null); setNames([]) }
    loadLists()
  }
  const addNames = async () => {
    if (!sel || !bulkText.trim()) return
    const { data } = await insuranceApi.addSeparationNames(sel.id, bulkText)
    setBulkText(''); loadNames(sel); loadLists()
    flash(`تمت إضافة ${data.added} اسم (${data.skipped} مكرر) · الإجمالى ${data.total}`)
  }
  const delName = async (n) => {
    if (!window.confirm(`حذف "${n.name}"؟`)) return
    await insuranceApi.deleteSeparationName(sel.id, n.id)
    loadNames(sel); loadLists()
  }
  const saveListEdit = async (l) => {
    if (!editLabel.trim()) return
    await insuranceApi.updateSeparationList(l.id, { label: editLabel.trim() })
    setEditListId(null); loadLists()
    if (sel?.id === l.id) setSel({ ...sel, label: editLabel.trim() })
  }
  const toggleListActive = async (l) => {
    await insuranceApi.updateSeparationList(l.id, { is_active: !l.is_active })
    loadLists()
  }
  const saveNameEdit = async (n) => {
    if (!editNameVal.trim()) return
    await insuranceApi.updateSeparationName(sel.id, n.id, { name: editNameVal.trim() })
    setEditNameId(null); loadNames(sel)
  }

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <button onClick={() => navigate('/insurance')} className="text-blue-600 text-sm hover:underline">← مطالبات التأمين</button>
        <h1 className="text-xl font-bold text-gray-800 mt-1">قوائم فصل الأسماء</h1>
        <p className="text-sm text-gray-500">أسماء تُفصل من مطالباتها وتُضاف إلى مطالبة أخرى — تظهر مطابقاتها في تبويب «فصل الأسماء» بكل مطالبة.</p>
      </div>

      {msg && <div className="mx-6 mt-3 rounded bg-green-50 border border-green-200 text-green-700 px-3 py-2 text-sm">{msg}</div>}

      <div className="px-6 py-5 grid grid-cols-3 gap-6">
        {/* Lists */}
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h3 className="font-semibold text-gray-700 mb-3">القوائم</h3>
          <div className="flex gap-2 mb-3">
            <input className={inp} placeholder="اسم قائمة جديدة…" value={newLabel}
              onChange={e => setNewLabel(e.target.value)} onKeyDown={e => e.key === 'Enter' && createList()} />
            <button onClick={createList} className="px-3 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">+ إضافة</button>
          </div>
          <div className="space-y-1">
            {lists.map(l => (
              <div key={l.id}
                className={`rounded px-3 py-2 ${sel?.id === l.id ? 'bg-blue-50 border border-blue-200' : 'hover:bg-gray-50'} ${l.is_active ? '' : 'opacity-60'}`}>
                {editListId === l.id ? (
                  <div className="flex gap-1 items-center">
                    <input className={inp} value={editLabel} onChange={e => setEditLabel(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && saveListEdit(l)} autoFocus />
                    <button onClick={() => saveListEdit(l)} className="text-blue-600 text-xs px-1">حفظ</button>
                    <button onClick={() => setEditListId(null)} className="text-gray-400 text-xs px-1">إلغاء</button>
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <div className="cursor-pointer flex-1" onClick={() => loadNames(l)}>
                      <div className="text-sm font-medium text-gray-800">{l.label}</div>
                      <div className="text-xs text-gray-400">{l.name_count} اسم {l.is_active ? '' : '· موقوفة'}</div>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <button onClick={() => { setEditListId(l.id); setEditLabel(l.label) }} title="تعديل الاسم" className="text-gray-400 hover:text-blue-600">✏️</button>
                      <button onClick={() => toggleListActive(l)} title={l.is_active ? 'إيقاف' : 'تفعيل'}
                        className={l.is_active ? 'text-green-600' : 'text-gray-400'}>{l.is_active ? 'مُفعَّلة' : 'موقوفة'}</button>
                      <button onClick={() => delList(l)} className="text-red-500 hover:text-red-700">حذف</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
            {lists.length === 0 && <p className="text-sm text-gray-400 text-center py-6">لا قوائم — أنشئ قائمة.</p>}
          </div>
        </div>

        {/* Names of selected list */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 col-span-2">
          {!sel ? (
            <p className="text-sm text-gray-400 text-center py-16">اختر قائمة لعرض أسمائها.</p>
          ) : (
            <>
              <div className="flex items-center justify-between mb-3 gap-2">
                <h3 className="font-semibold text-gray-700">{sel.label} — {names.length} اسم</h3>
                <input className="border border-gray-300 rounded px-3 py-1.5 text-sm w-56" placeholder="بحث في الأسماء…"
                  value={nameFilter} onChange={e => setNameFilter(e.target.value)} />
              </div>
              <div className="mb-3">
                <label className="block text-xs text-gray-600 mb-1">إضافة أسماء (اسم في كل سطر)</label>
                <textarea className={inp + ' h-24 font-mono'} value={bulkText}
                  onChange={e => setBulkText(e.target.value)} placeholder={'اسم أول\nاسم ثانى\n…'} />
                <button onClick={addNames} className="mt-2 px-3 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">إضافة الأسماء</button>
              </div>
              <div className="max-h-[50vh] overflow-y-auto border border-gray-100 rounded">
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-gray-100">
                    {names.filter(n => !nameFilter.trim() || n.name.includes(nameFilter.trim())).map((n, i) => (
                      <tr key={n.id} className="hover:bg-gray-50">
                        <td className="px-2 py-1.5 text-gray-400 w-8">{i + 1}</td>
                        <td className="px-2 py-1.5 text-gray-800">
                          {editNameId === n.id ? (
                            <input className="w-full border border-gray-300 rounded px-2 py-1 text-sm" value={editNameVal}
                              onChange={e => setEditNameVal(e.target.value)}
                              onKeyDown={e => e.key === 'Enter' && saveNameEdit(n)} autoFocus />
                          ) : n.name}
                        </td>
                        <td className="px-2 py-1.5 text-left whitespace-nowrap">
                          {editNameId === n.id ? (
                            <>
                              <button onClick={() => saveNameEdit(n)} className="text-blue-600 text-xs px-1">حفظ</button>
                              <button onClick={() => setEditNameId(null)} className="text-gray-400 text-xs px-1">إلغاء</button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => { setEditNameId(n.id); setEditNameVal(n.name) }} className="text-gray-400 hover:text-blue-600 text-xs px-1">✏️</button>
                              <button onClick={() => delName(n)} className="text-red-500 hover:text-red-700 text-xs px-1">حذف</button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                    {names.length === 0 && <tr><td colSpan={3} className="px-3 py-8 text-center text-gray-400">لا أسماء بعد.</td></tr>}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
