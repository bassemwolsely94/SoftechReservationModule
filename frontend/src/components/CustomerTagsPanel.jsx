/**
 * CustomerTagsPanel.jsx
 * Reusable tag panel used in CustomerDetailPage.
 * Global tags from /api/customers/tags/ — autocomplete search.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { customersApi, tagsApi } from '../api/client'

const TYPE_ICONS = {
  doctor:    '👨‍⚕️',
  diagnosis: '🏥',
  general:   '🏷️',
  chronic:   '💊',
  insurance: '📋',
  vip:       '⭐',
}

function TagChip({ ct, onRemove, readonly }) {
  const tag = ct.tag_detail || {}
  return (
    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border"
      style={{
        background: (tag.color || '#6b7280') + '18',
        color:       tag.color || '#6b7280',
        borderColor: (tag.color || '#6b7280') + '44',
      }}>
      <span>{TYPE_ICONS[tag.tag_type] || '🏷️'}</span>
      {tag.name}
      {!readonly && (
        <button onClick={() => onRemove(ct.id)}
          className="hover:opacity-70 ml-0.5 leading-none">
          ✕
        </button>
      )}
    </div>
  )
}

// ── Tag search + create ───────────────────────────────────────────────────────

function TagSearch({ existingTagIds, onAdd }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newTagName, setNewTagName] = useState('')
  const [newTagType, setNewTagType] = useState('general')
  const [newTagColor, setNewTagColor] = useState('#6b7280')
  const qc = useQueryClient()

  const { data: allTags = [] } = useQuery({
    queryKey: ['all-tags', q],
    queryFn: () => tagsApi.list({ search: q }).then(r => r.data.results || r.data),
    staleTime: 30_000,
  })

  const filtered = allTags.filter(t =>
    !existingTagIds.includes(t.id) &&
    (t.name.includes(q) || t.name_en?.toLowerCase().includes(q.toLowerCase()))
  )

  async function handleCreateAndAdd() {
    if (!newTagName.trim()) return
    try {
      const res = await tagsApi.create({
        name: newTagName.trim(),
        tag_type: newTagType,
        color: newTagColor,
      })
      qc.invalidateQueries(['all-tags'])
      onAdd(res.data.id)
      setNewTagName(''); setShowCreate(false); setOpen(false); setQ('')
    } catch { }
  }

  return (
    <div className="relative">
      <input className="input-field text-sm" placeholder="ابحث عن تاج أو أضف جديداً..."
        value={q}
        onChange={e => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
      />
      {open && (
        <div className="absolute z-30 w-full bg-white border border-gray-200 rounded-xl shadow-xl mt-1 max-h-52 overflow-y-auto">
          {filtered.map(tag => (
            <button key={tag.id} type="button"
              className="w-full text-right px-4 py-2.5 hover:bg-brand-50 flex items-center gap-2 border-b border-gray-50 last:border-0"
              onMouseDown={() => { onAdd(tag.id); setQ(''); setOpen(false) }}>
              <span className="text-sm">{TYPE_ICONS[tag.tag_type] || '🏷️'}</span>
              <span className="font-medium text-gray-800 text-sm">{tag.name}</span>
              <span className="text-xs text-gray-400">{tag.tag_type_label}</span>
              <span className="w-3 h-3 rounded-full mr-auto"
                style={{ background: tag.color }} />
            </button>
          ))}
          {q && filtered.length === 0 && (
            <div className="px-4 py-2">
              <div className="text-xs text-gray-400 mb-2">لا توجد تاجات بهذا الاسم</div>
              {!showCreate ? (
                <button onMouseDown={() => { setShowCreate(true); setNewTagName(q) }}
                  className="text-xs text-brand-600 hover:text-brand-800 font-semibold">
                  + إنشاء تاج "{q}"
                </button>
              ) : (
                <div className="space-y-2 pt-1">
                  <input className="input-field text-xs" placeholder="اسم التاج"
                    value={newTagName} onChange={e => setNewTagName(e.target.value)} autoFocus />
                  <div className="flex gap-2">
                    <select className="input-field text-xs flex-1" value={newTagType}
                      onChange={e => setNewTagType(e.target.value)}>
                      {Object.entries(TYPE_ICONS).map(([v, icon]) => (
                        <option key={v} value={v}>{icon} {v}</option>
                      ))}
                    </select>
                    <input type="color" value={newTagColor}
                      onChange={e => setNewTagColor(e.target.value)}
                      className="w-10 h-9 rounded-lg border border-gray-200 cursor-pointer" />
                  </div>
                  <button onMouseDown={handleCreateAndAdd}
                    className="btn-primary text-xs w-full">
                    إنشاء وإضافة
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function CustomerTagsPanel({ customerId, readonly = false }) {
  const qc = useQueryClient()

  const { data: customerTags = [], isLoading } = useQuery({
    queryKey: ['customer-tags', customerId],
    queryFn: () => customersApi.tags(customerId).then(r => r.data),
    enabled: !!customerId,
  })

  const invalidate = () => qc.invalidateQueries(['customer-tags', customerId])

  async function handleAdd(tagId) {
    try {
      await customersApi.addTag(customerId, { tag: tagId })
      invalidate()
    } catch { }
  }

  async function handleRemove(ctId) {
    // ctId is the CustomerTag id (not the Tag id)
    const ct = customerTags.find(c => c.id === ctId)
    if (!ct) return
    await customersApi.removeTag(customerId, ct.tag)
    invalidate()
  }

  const existingTagIds = customerTags.map(ct => ct.tag)

  if (isLoading) return (
    <div className="flex gap-2 flex-wrap animate-pulse">
      {[1,2,3].map(i => <div key={i} className="h-7 w-20 bg-gray-100 rounded-full" />)}
    </div>
  )

  return (
    <div className="space-y-3" dir="rtl">
      <div className="flex flex-wrap gap-2">
        {customerTags.length === 0 && (
          <span className="text-xs text-gray-400">لا توجد تاجات — أضف أول تاج</span>
        )}
        {customerTags.map(ct => (
          <TagChip key={ct.id} ct={ct} onRemove={handleRemove} readonly={readonly} />
        ))}
      </div>
      {!readonly && (
        <TagSearch existingTagIds={existingTagIds} onAdd={handleAdd} />
      )}
    </div>
  )
}
