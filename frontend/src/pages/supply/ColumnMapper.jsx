/**
 * ColumnMapper.jsx — confirm a supplier file's columns ONCE (name / code / barcode / qty /
 * price / bonus / discount / expiry). The server suggests from the header words; after the
 * person confirms, that supplier's files with the same header row import directly
 * (apps/supply/file_layouts.py). Inline under the import bar — no modal.
 */
import { useState } from 'react'
import { btnGhost, btnPrimary, inputCls } from './supplyUi'

export default function ColumnMapper({ preview, busy, error, onImport, onCancel }) {
  const [mapping, setMapping] = useState(() => ({ ...(preview.suggested || {}) }))
  const roles = preview.roles || {}
  const set = (col, role) => setMapping(m => {
    const n = { ...m }
    // a role (other than «تجاهل») belongs to one column — picking it elsewhere moves it
    if (role && role !== 'ignore') for (const k of Object.keys(n)) if (n[k] === role) delete n[k]
    if (role) n[String(col)] = role; else delete n[String(col)]
    return n
  })
  const hasName = Object.values(mapping).includes('name')
  return (
    <div className="rounded-lg border border-primary/40 bg-primary/5 p-3 space-y-2">
      <div className="text-sm text-content">
        أول ملف بهذا الشكل من هذا المورد — راجع الأعمدة مرة واحدة، وبعدها تُستورد ملفاته مباشرة.
      </div>
      <div className="overflow-auto max-h-72 rounded border border-line bg-surface">
        <table className="text-xs min-w-full">
          <thead className="sticky top-0 bg-surface">
            <tr>
              {preview.columns.map(c => (
                <th key={c.index} className="p-1.5 text-right align-top border-b border-line min-w-[8rem]">
                  <div className="text-content/60 mb-1 truncate" title={c.header}>{c.header || `عمود ${c.index + 1}`}</div>
                  <select value={mapping[String(c.index)] || ''} onChange={e => set(c.index, e.target.value)}
                    className={`${inputCls} text-xs w-full ${mapping[String(c.index)] && mapping[String(c.index)] !== 'ignore'
                      ? 'border-primary' : ''}`}>
                    <option value="">—</option>
                    {Object.entries(roles).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[0, 1, 2, 3].map(r => (
              <tr key={r} className="border-b border-line/50">
                {preview.columns.map(c => (
                  <td key={c.index} className="p-1.5 text-content/70 whitespace-nowrap" dir="auto">{c.samples?.[r] ?? ''}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-2">
        <button type="button" className={btnPrimary} disabled={!hasName || busy}
          onClick={() => onImport({ mapping, header_row: preview.header_row })}>
          {busy ? 'جارٍ الاستيراد…' : 'استيراد وحفظ ترتيب الأعمدة'}</button>
        <button type="button" className={btnGhost} onClick={onCancel} disabled={busy}>إلغاء</button>
        {!hasName && <span className="text-xs text-amber-700">حدد عمود «اسم الصنف».</span>}
        {error && <span className="text-xs text-rose-600">{error}</span>}
      </div>
    </div>
  )
}
