/**
 * SavedViewsMenu — C23 «العروض المحفوظة»: one small button next to a screen's filters.
 * Pick a view to apply its filters; save the current filters under a name (optionally as your default
 * for this screen, or shared with colleagues of your role). Delete is a second press, not a dialog.
 * State + server calls live in hooks/useSavedViews.js; the server keeps only allow-listed filter keys.
 */
import { useEffect, useRef, useState } from 'react'

export default function SavedViewsMenu({ sv, className = '' }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [shared, setShared] = useState(false)
  const [armDelete, setArmDelete] = useState(null)
  const [busy, setBusy] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [open])

  const active = sv.views.find(v => v.id === sv.activeId)
  const run = async (fn) => { setBusy(true); try { return await fn() } finally { setBusy(false) } }

  async function onSave(e) {
    e.preventDefault()
    if (!name.trim() || busy) return
    const v = await run(() => sv.save({ name: name.trim(), isDefault, shared }))
    if (v) { setName(''); setIsDefault(false); setShared(false) }
  }
  async function onDelete(id) {
    if (armDelete !== id) { setArmDelete(id); return }
    setArmDelete(null)
    await run(() => sv.remove(id))
  }

  return (
    <div ref={ref} className={`relative ${className}`} data-tour="saved-views">
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open} data-testid="saved-views-button"
              className="px-3 py-1.5 border rounded-lg text-sm bg-white hover:bg-gray-50 dark:bg-gray-900 dark:border-gray-700 whitespace-nowrap">
        ⭐ {active ? active.name : 'العروض'}
      </button>
      {open && (
        <div role="menu" data-testid="saved-views-menu"
             className="absolute z-30 mt-1 end-0 w-72 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg p-2 text-sm">
          {sv.views.length === 0
            ? <p className="px-2 py-1.5 text-xs text-gray-400">لا توجد عروض محفوظة بعد.</p>
            : (
              <ul className="max-h-64 overflow-y-auto">
                {sv.views.map(v => (
                  <li key={v.id} className={`flex items-center gap-1 rounded-lg px-1 ${v.id === sv.activeId ? 'bg-primary/5' : 'hover:bg-gray-50 dark:hover:bg-gray-800'}`}>
                    <button type="button" role="menuitem" onClick={() => { sv.apply(v); setOpen(false) }}
                            className="flex-1 text-start py-1.5 px-1 truncate" title={v.mine ? '' : `من ${v.owner_name}`}>
                      {v.is_default && <span title="افتراضي">★ </span>}{v.name}
                      {v.shared && <span className="text-xs text-gray-400" title="مشترك مع دورك"> 👥</span>}
                      {!v.mine && <span className="block text-[11px] text-gray-400">{v.owner_name}</span>}
                    </button>
                    {v.mine && (
                      <>
                        <button type="button" disabled={busy} onClick={() => run(() => sv.setDefault(v.id, !v.is_default))}
                                title={v.is_default ? 'إلغاء الافتراضي' : 'اجعله الافتراضي'} aria-label="افتراضي"
                                className={`px-1 ${v.is_default ? 'text-amber-500' : 'text-gray-300 hover:text-amber-500'}`}>★</button>
                        <button type="button" disabled={busy} onClick={() => run(() => sv.overwrite(v.id))}
                                title="احفظ الفلاتر الحالية في هذا العرض" aria-label="تحديث" className="px-1 text-gray-400 hover:text-gray-700">⟳</button>
                        <button type="button" disabled={busy} onClick={() => onDelete(v.id)}
                                title={armDelete === v.id ? 'اضغط مرة ثانية للحذف' : 'حذف'} aria-label="حذف"
                                className={`px-1 ${armDelete === v.id ? 'text-red-600 font-bold' : 'text-gray-300 hover:text-red-500'}`}>
                          {armDelete === v.id ? 'حذف؟' : '🗑'}
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          <form onSubmit={onSave} className="mt-2 border-t border-gray-100 dark:border-gray-800 pt-2 space-y-1.5">
            <input value={name} onChange={e => setName(e.target.value)} maxLength={80} placeholder="اسم للفلاتر الحالية"
                   aria-label="اسم العرض" className="w-full border rounded-lg px-2 py-1 text-sm dark:bg-gray-800 dark:border-gray-700" />
            <div className="flex items-center gap-3 text-xs text-gray-600 dark:text-gray-300">
              <label className="flex items-center gap-1"><input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)} /> افتراضي</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={shared} onChange={e => setShared(e.target.checked)} /> مشاركة مع زملاء دوري</label>
              <button type="submit" disabled={!name.trim() || busy}
                      className="ms-auto px-2 py-1 rounded-lg bg-primary text-white disabled:opacity-40">حفظ</button>
            </div>
            {sv.error && <p className="text-xs text-red-600">{sv.error}</p>}
          </form>
        </div>
      )}
    </div>
  )
}
