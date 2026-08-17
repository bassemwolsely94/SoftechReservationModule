/**
 * CatalogIntelligencePage.jsx
 *
 * Four-tab page:
 *  1. Variant Groups   — group items that are the same product in different forms
 *  2. Product Bundles  — curated bundles with optional discount
 *  3. FBT Pairs        — read-only view of Frequently Bought Together data
 *  4. AI Enrichment    — batch enrichment management + catalog quality dashboard
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { catalogIntelApi, recommendationsApi, enrichmentApi } from '../api/client'
import ItemSearchWidget from '../components/ItemSearchWidget'

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmt = (n) => n != null ? Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—'

// ── Variant Groups Tab ────────────────────────────────────────────────────────
function VariantGroupsTab() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState(null)
  const [q, setQ] = useState('')
  const [newGroupName, setNewGroupName] = useState('')
  const [newGroupNameAr, setNewGroupNameAr] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['variant-groups', q],
    queryFn: () => catalogIntelApi.variantGroups(q || undefined).then(r => r.data),
  })
  const groups = Array.isArray(data) ? data : (data?.results ?? [])

  const createMutation = useMutation({
    mutationFn: (d) => catalogIntelApi.createVariantGroup(d),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['variant-groups'] })
      setSelected(res.data.id)
      setShowCreate(false)
      setNewGroupName(''); setNewGroupNameAr('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => catalogIntelApi.deleteVariantGroup(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variant-groups'] })
      setSelected(null)
    },
  })

  const addMemberMutation = useMutation({
    mutationFn: ({ groupId, item }) =>
      catalogIntelApi.addVariantMember(groupId, { item: item.id, variant_label: '', sort_order: 0 }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['variant-groups'] }),
  })

  const removeMemberMutation = useMutation({
    mutationFn: ({ groupId, memberId }) => catalogIntelApi.removeVariantMember(groupId, memberId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['variant-groups'] }),
  })

  const selectedGroup = groups.find(g => g.id === selected)

  return (
    <div className="flex gap-4 h-full" dir="rtl">
      {/* Left: list */}
      <div className="w-72 flex-shrink-0">
        <div className="flex items-center gap-2 mb-3">
          <input
            value={q} onChange={e => setQ(e.target.value)}
            placeholder="بحث في المجموعات..."
            className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <button
            onClick={() => setShowCreate(true)}
            className="px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >+</button>
        </div>

        {showCreate && (
          <div className="mb-3 p-3 border border-blue-200 bg-blue-50 rounded-xl space-y-2">
            <input value={newGroupName} onChange={e => setNewGroupName(e.target.value)}
              placeholder="الاسم (إنجليزي) *"
              className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm focus:outline-none" />
            <input value={newGroupNameAr} onChange={e => setNewGroupNameAr(e.target.value)}
              placeholder="الاسم (عربي)"
              className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm focus:outline-none" />
            <div className="flex gap-2">
              <button
                onClick={() => createMutation.mutate({ name: newGroupName, name_ar: newGroupNameAr })}
                disabled={!newGroupName || createMutation.isPending}
                className="flex-1 py-1.5 bg-blue-600 text-white text-xs rounded disabled:opacity-50"
              >إنشاء</button>
              <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 bg-gray-100 text-xs rounded">إلغاء</button>
            </div>
          </div>
        )}

        <div className="space-y-1 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 280px)' }}>
          {isLoading && <div className="text-center text-gray-400 py-4 text-sm">جارٍ التحميل...</div>}
          {!isLoading && groups.length === 0 && (
            <div className="text-center text-gray-400 py-6 text-sm">لا توجد مجموعات</div>
          )}
          {groups.map(g => (
            <button
              key={g.id} onClick={() => setSelected(g.id)}
              className={`w-full text-right px-3 py-2.5 rounded-lg border text-sm transition-colors ${
                selected === g.id
                  ? 'bg-blue-50 border-blue-300 text-blue-800'
                  : 'bg-white border-gray-100 hover:border-gray-200 text-gray-700'
              }`}
            >
              <div className="font-medium truncate">{g.name_ar || g.name}</div>
              <div className="text-xs text-gray-400">{g.member_count} صنف</div>
            </button>
          ))}
        </div>
      </div>

      {/* Right: detail */}
      <div className="flex-1 bg-white border border-gray-200 rounded-xl p-5 overflow-y-auto">
        {!selectedGroup && (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <div className="text-5xl mb-3">🔗</div>
            <p>اختر مجموعة أو أنشئ مجموعة جديدة</p>
          </div>
        )}
        {selectedGroup && (
          <>
            <div className="flex items-start justify-between mb-4">
              <div>
                <h2 className="text-lg font-bold text-gray-800">{selectedGroup.name_ar || selectedGroup.name}</h2>
                {selectedGroup.name_ar && selectedGroup.name !== selectedGroup.name_ar && (
                  <p className="text-sm text-gray-500">{selectedGroup.name}</p>
                )}
              </div>
              <button
                onClick={() => { if (window.confirm('حذف هذه المجموعة؟')) deleteMutation.mutate(selectedGroup.id) }}
                className="text-xs text-red-500 hover:text-red-700 border border-red-200 px-2 py-1 rounded hover:bg-red-50"
              >
                🗑 حذف
              </button>
            </div>

            {/* Add item */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-600 mb-1">إضافة صنف للمجموعة</label>
              <ItemSearchWidget
                selected={null}
                onSelect={(item) => addMemberMutation.mutate({ groupId: selectedGroup.id, item })}
                onClear={() => {}}
                placeholder="ابحث باسم الصنف أو الكود أو الباركود..."
              />
            </div>

            {/* Members */}
            <h3 className="text-sm font-semibold text-gray-700 mb-2">
              الأصناف في المجموعة ({selectedGroup.members?.length || 0})
            </h3>
            {(!selectedGroup.members || selectedGroup.members.length === 0) ? (
              <p className="text-sm text-gray-400">لا يوجد أصناف بعد — أضف أصنافاً من البحث أعلاه</p>
            ) : (
              <div className="space-y-2">
                {selectedGroup.members.map(m => (
                  <div key={m.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-100">
                    <div>
                      <span className="text-sm font-medium text-gray-800">{m.item_name}</span>
                      <span className="text-xs text-gray-400 font-mono mr-2">{m.item_code}</span>
                      {m.item_price && (
                        <span className="text-xs text-green-600">{fmt(m.item_price)} ج.م</span>
                      )}
                      {m.variant_label && (
                        <span className="mr-2 px-1.5 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full">
                          {m.variant_label}
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => removeMemberMutation.mutate({ groupId: selectedGroup.id, memberId: m.id })}
                      className="text-gray-300 hover:text-red-400 text-sm"
                    >✕</button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Product Bundles Tab ───────────────────────────────────────────────────────
function BundlesTab() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState(null)
  const [q, setQ] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newBundle, setNewBundle] = useState({
    name: '', name_ar: '', description: '',
    discount_type: 'none', discount_value: '0', is_active: true,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['bundles', q],
    queryFn: () => catalogIntelApi.bundles(q || undefined).then(r => r.data),
  })
  const bundles = Array.isArray(data) ? data : (data?.results ?? [])

  const createMutation = useMutation({
    mutationFn: (d) => catalogIntelApi.createBundle(d),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['bundles'] })
      setSelected(res.data.id)
      setShowCreate(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => catalogIntelApi.updateBundle(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bundles'] }),
  })

  const addItemMutation = useMutation({
    mutationFn: ({ bundleId, item }) =>
      catalogIntelApi.addBundleItem(bundleId, { item: item.id, quantity: 1 }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bundles'] }),
  })

  const removeItemMutation = useMutation({
    mutationFn: ({ bundleId, biId }) => catalogIntelApi.removeBundleItem(bundleId, biId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bundles'] }),
  })

  const selectedBundle = bundles.find(b => b.id === selected)

  return (
    <div className="flex gap-4 h-full" dir="rtl">
      {/* Left: list */}
      <div className="w-72 flex-shrink-0">
        <div className="flex items-center gap-2 mb-3">
          <input
            value={q} onChange={e => setQ(e.target.value)}
            placeholder="بحث في الباقات..."
            className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-400"
          />
          <button onClick={() => setShowCreate(true)}
            className="px-3 py-2 bg-purple-600 text-white text-sm rounded-lg hover:bg-purple-700">+</button>
        </div>

        {showCreate && (
          <div className="mb-3 p-3 border border-purple-200 bg-purple-50 rounded-xl space-y-2">
            <input value={newBundle.name} onChange={e => setNewBundle(b => ({ ...b, name: e.target.value }))}
              placeholder="الاسم (إنجليزي) *"
              className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm" />
            <input value={newBundle.name_ar} onChange={e => setNewBundle(b => ({ ...b, name_ar: e.target.value }))}
              placeholder="الاسم (عربي)"
              className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm" />
            <select value={newBundle.discount_type}
              onChange={e => setNewBundle(b => ({ ...b, discount_type: e.target.value }))}
              className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm">
              <option value="none">بدون خصم</option>
              <option value="pct">خصم %</option>
              <option value="fixed">خصم ثابت</option>
            </select>
            {newBundle.discount_type !== 'none' && (
              <input type="number" min="0" step="0.01"
                value={newBundle.discount_value}
                onChange={e => setNewBundle(b => ({ ...b, discount_value: e.target.value }))}
                placeholder={newBundle.discount_type === 'pct' ? '10 %' : '50 ج.م'}
                className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm" />
            )}
            <div className="flex gap-2">
              <button
                onClick={() => createMutation.mutate({
                  ...newBundle,
                  discount_value: newBundle.discount_value || '0',
                })}
                disabled={!newBundle.name || createMutation.isPending}
                className="flex-1 py-1.5 bg-purple-600 text-white text-xs rounded disabled:opacity-50"
              >إنشاء</button>
              <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 bg-gray-100 text-xs rounded">إلغاء</button>
            </div>
          </div>
        )}

        <div className="space-y-1 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 280px)' }}>
          {isLoading && <div className="text-center text-gray-400 py-4 text-sm">جارٍ التحميل...</div>}
          {!isLoading && bundles.length === 0 && (
            <div className="text-center text-gray-400 py-6 text-sm">لا توجد باقات</div>
          )}
          {bundles.map(b => (
            <button key={b.id} onClick={() => setSelected(b.id)}
              className={`w-full text-right px-3 py-2.5 rounded-lg border text-sm transition-colors ${
                selected === b.id
                  ? 'bg-purple-50 border-purple-300 text-purple-800'
                  : 'bg-white border-gray-100 hover:border-gray-200 text-gray-700'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className="font-medium truncate flex-1">{b.name_ar || b.name}</span>
                {!b.is_active && <span className="text-xs text-gray-400 bg-gray-100 px-1.5 rounded">مخفي</span>}
              </div>
              <div className="text-xs text-gray-400">
                {b.items?.length || 0} صنف
                {b.discount_type !== 'none' && (
                  <span className="text-purple-600 mr-1">
                    · {b.discount_type === 'pct' ? `${fmt(b.discount_value)}%` : `${fmt(b.discount_value)} ج.م`} خصم
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Right: detail */}
      <div className="flex-1 bg-white border border-gray-200 rounded-xl p-5 overflow-y-auto">
        {!selectedBundle && (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <div className="text-5xl mb-3">📦</div>
            <p>اختر باقة أو أنشئ باقة جديدة</p>
          </div>
        )}
        {selectedBundle && (
          <>
            <div className="flex items-start justify-between mb-4">
              <div>
                <h2 className="text-lg font-bold text-gray-800">{selectedBundle.name_ar || selectedBundle.name}</h2>
                {selectedBundle.description && (
                  <p className="text-sm text-gray-500 mt-0.5">{selectedBundle.description}</p>
                )}
              </div>
              <button
                onClick={() => updateMutation.mutate({
                  id: selectedBundle.id,
                  data: { is_active: !selectedBundle.is_active },
                })}
                className={`text-xs px-3 py-1.5 rounded border ${
                  selectedBundle.is_active
                    ? 'text-green-700 border-green-200 bg-green-50 hover:bg-green-100'
                    : 'text-gray-500 border-gray-200 bg-gray-50 hover:bg-gray-100'
                }`}
              >
                {selectedBundle.is_active ? '✅ نشطة' : '⏸ مخفية'}
              </button>
            </div>

            {selectedBundle.discount_type !== 'none' && (
              <div className="mb-4 p-3 bg-purple-50 border border-purple-200 rounded-lg text-sm">
                <span className="font-semibold text-purple-700">الخصم: </span>
                {selectedBundle.discount_type === 'pct'
                  ? `${fmt(selectedBundle.discount_value)}% على الباقة`
                  : `${fmt(selectedBundle.discount_value)} ج.م خصم ثابت`}
              </div>
            )}

            {/* Add item */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-600 mb-1">إضافة صنف للباقة</label>
              <ItemSearchWidget
                selected={null}
                onSelect={(item) => addItemMutation.mutate({ bundleId: selectedBundle.id, item })}
                onClear={() => {}}
                placeholder="ابحث باسم الصنف أو الكود أو الباركود..."
              />
            </div>

            {/* Items */}
            <h3 className="text-sm font-semibold text-gray-700 mb-2">
              أصناف الباقة ({selectedBundle.items?.length || 0})
            </h3>
            {(!selectedBundle.items || selectedBundle.items.length === 0) ? (
              <p className="text-sm text-gray-400">لا يوجد أصناف بعد</p>
            ) : (
              <div className="space-y-2">
                {selectedBundle.items.map(bi => (
                  <div key={bi.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-100">
                    <div className="flex-1">
                      <span className="text-sm font-medium text-gray-800">{bi.item_name}</span>
                      <span className="text-xs text-gray-400 font-mono mr-2">{bi.item_code}</span>
                      {bi.item_price && (
                        <span className="text-xs text-green-600">{fmt(bi.item_price)} ج.م</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">×{fmt(bi.quantity)}</span>
                      <button
                        onClick={() => removeItemMutation.mutate({ bundleId: selectedBundle.id, biId: bi.id })}
                        className="text-gray-300 hover:text-red-400 text-sm"
                      >✕</button>
                    </div>
                  </div>
                ))}
                {/* Total */}
                <div className="flex justify-between items-center pt-2 border-t border-gray-200 text-sm font-semibold">
                  <span className="text-gray-600">الإجمالي</span>
                  <span className="text-gray-800">
                    {fmt(selectedBundle.items.reduce((s, i) => s + (Number(i.item_price || 0) * Number(i.quantity || 1)), 0))} ج.م
                  </span>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── FBT Pairs Tab ─────────────────────────────────────────────────────────────
function FBTPairsTab() {
  const [filterItem, setFilterItem] = useState(null)

  const { data: runData } = useQuery({
    queryKey: ['rec-run'],
    queryFn: () => recommendationsApi.latestRun().then(r => r.data),
    retry: false,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['fbt-pairs', filterItem?.id],
    queryFn: () => recommendationsApi.fbtList({ item_a: filterItem?.id, limit: 50 }).then(r => r.data),
  })

  const pairs = Array.isArray(data) ? data : (data?.results ?? [])

  return (
    <div dir="rtl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-700">بيانات يُشترى معه عادةً (FBT)</h3>
          {runData && (
            <p className="text-xs text-gray-400 mt-0.5">
              آخر تشغيل: {new Date(runData.started_at).toLocaleDateString('en-US')}
              · {runData.fbt_pairs_count?.toLocaleString('en-US') || 0} زوج
            </p>
          )}
        </div>
        {filterItem && (
          <button onClick={() => setFilterItem(null)}
            className="text-xs text-gray-500 hover:text-gray-700 bg-gray-100 px-2 py-1 rounded">
            إلغاء الفلتر ✕
          </button>
        )}
      </div>

      <div className="mb-4">
        <ItemSearchWidget
          selected={filterItem}
          onSelect={setFilterItem}
          onClear={() => setFilterItem(null)}
          placeholder="فلتر بصنف معين (اسم أو كود أو باركود)..."
        />
        {filterItem && (
          <p className="text-xs text-blue-600 mt-1">
            يعرض أزواج: <strong>{filterItem.name}</strong>
          </p>
        )}
      </div>

      {isLoading ? (
        <div className="text-center text-gray-400 py-8 text-sm">جارٍ التحميل...</div>
      ) : pairs.length === 0 ? (
        <div className="text-center text-gray-400 py-8">
          <div className="text-4xl mb-2">📊</div>
          <p className="text-sm">لا توجد بيانات — شغّل محرك التوصيات أولاً</p>
        </div>
      ) : (
        <div className="border border-gray-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm" dir="rtl">
            <thead className="bg-gray-50 text-xs text-gray-500">
              <tr>
                <th className="px-4 py-2.5 text-right">الصنف A</th>
                <th className="px-4 py-2.5 text-right">الصنف B</th>
                <th className="px-4 py-2.5 text-center">تكرار معاً</th>
                <th className="px-4 py-2.5 text-center">الثقة</th>
                <th className="px-4 py-2.5 text-center">Lift</th>
                <th className="px-4 py-2.5 text-center">النقاط</th>
              </tr>
            </thead>
            <tbody>
              {pairs.slice(0, 50).map((p, i) => (
                <tr key={i} className="border-t border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-gray-800 break-words max-w-[180px]">
                      {p.item_a_name || p.item_a}
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-gray-800 break-words max-w-[180px]">
                      {p.item_b_name || p.item_b}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-center text-gray-600">{p.co_occurrences}</td>
                  <td className="px-4 py-2.5 text-center">
                    <span className="text-blue-600 font-medium">
                      {p.confidence != null ? `${Math.round(p.confidence * 100)}%` : '—'}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-center text-gray-600">
                    {p.lift != null ? p.lift.toFixed(2) : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <span className="font-semibold text-green-700">
                      {p.score != null ? p.score.toFixed(3) : '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Tab 4: AI Enrichment Management ──────────────────────────────────────────

const SCOPE_OPTIONS = [
  { value: 'all',       label: 'كل الكتالوج' },
  { value: 'low_score', label: 'أقل من حد الاكتمال' },
  { value: 'category',  label: 'تصنيف محدد' },
  { value: 'supplier',  label: 'مورّد محدد' },
  { value: 'selected',  label: 'أصناف محددة' },
]

const BATCH_STATUS_CFG = {
  pending:   { label: 'في الانتظار', cls: 'bg-gray-100 text-gray-600'  },
  running:   { label: 'جارٍ',        cls: 'bg-blue-100 text-blue-700'  },
  success:   { label: 'اكتمل',       cls: 'bg-green-100 text-green-700' },
  failed:    { label: 'فشل',         cls: 'bg-red-100 text-red-600'    },
  cancelled: { label: 'ملغي',        cls: 'bg-yellow-100 text-yellow-700' },
}

function BatchStatusBadge({ status }) {
  const cfg = BATCH_STATUS_CFG[status] || BATCH_STATUS_CFG.pending
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cfg.cls}`}>
      {cfg.label}
    </span>
  )
}

function MiniProgressBar({ pct, status }) {
  const color =
    status === 'success'  ? 'bg-green-500' :
    status === 'failed'   ? 'bg-red-400'   :
    status === 'running'  ? 'bg-blue-500'  : 'bg-gray-300'
  return (
    <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden w-full">
      <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  )
}

function StatCard({ label, value, sub, color = 'blue' }) {
  const colors = {
    blue:   'bg-blue-50   border-blue-200   text-blue-700',
    green:  'bg-green-50  border-green-200  text-green-700',
    yellow: 'bg-yellow-50 border-yellow-200 text-yellow-700',
    red:    'bg-red-50    border-red-200    text-red-700',
    purple: 'bg-purple-50 border-purple-200 text-purple-700',
    gray:   'bg-gray-50   border-gray-200   text-gray-600',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <div className="text-2xl font-bold">{value ?? '—'}</div>
      <div className="text-sm font-medium mt-0.5">{label}</div>
      {sub && <div className="text-xs opacity-70 mt-1">{sub}</div>}
    </div>
  )
}

function EnrichmentManagementTab() {
  const qc = useQueryClient()

  // ── Create-batch form state ───────────────────────────────────────────
  const [scopeType, setScopeType]           = useState('low_score')
  const [threshold, setThreshold]           = useState(0.85)
  const [batchName, setBatchName]           = useState('')
  const [scopeParam, setScopeParam]         = useState('')  // category / supplier value
  const [showCreateForm, setShowCreateForm] = useState(false)

  // ── Queue filters ─────────────────────────────────────────────────────
  const [qSearch, setQSearch]       = useState('')
  const [qDebounced, setQDebounced] = useState('')
  const [qScore, setQScore]         = useState('')  // empty | partial | complete
  const [qHasPending, setQHasPending] = useState(true)
  const [qPage, setQPage]           = useState(1)

  const handleQSearch = (v) => {
    setQSearch(v)
    clearTimeout(handleQSearch._t)
    handleQSearch._t = setTimeout(() => { setQDebounced(v); setQPage(1) }, 350)
  }

  // ── Queries ───────────────────────────────────────────────────────────
  const { data: report, isFetching: reportLoading, refetch: refetchReport } = useQuery({
    queryKey: ['enrReport'],
    queryFn:  () => enrichmentApi.report().then(r => r.data),
    staleTime: 30_000,
  })

  const { data: batchData, isFetching: batchLoading } = useQuery({
    queryKey: ['enrBatches'],
    queryFn:  () => enrichmentApi.batches({ ordering: '-created_at', page_size: 20 }).then(r => r.data),
    staleTime: 15_000,
    // v5: refetchInterval receives the Query object, not data — access via query.state.data
    refetchInterval: (query) => {
      const d = query.state.data
      const running = (d?.results || (Array.isArray(d) ? d : [])).some(
        b => b.status === 'running' || b.status === 'pending'
      )
      return running ? 6_000 : false
    },
  })

  const batches = batchData?.results || batchData || []

  const queueParams = {
    ordering: 'completeness_score',
    page_size: 25,
    page: qPage,
    ...(qDebounced  && { search: qDebounced }),
    ...(qHasPending && { has_pending: true }),
    ...(qScore === 'empty'    && { score_max: 5 }),
    ...(qScore === 'partial'  && { score_min: 5, score_max: 79 }),
    ...(qScore === 'complete' && { score_min: 80 }),
  }

  const { data: queueData, isFetching: queueLoading } = useQuery({
    queryKey: ['enrQueue', queueParams],
    queryFn:  () => enrichmentApi.queue(queueParams).then(r => r.data),
    placeholderData: (prev) => prev,   // v5 replacement for keepPreviousData
    staleTime: 20_000,
  })

  const queueItems = queueData?.results || queueData || []
  const queueTotal = queueData?.count   || queueItems.length
  const totalPages  = Math.ceil(queueTotal / 25)

  // ── Mutations ─────────────────────────────────────────────────────────
  const createBatch = useMutation({
    mutationFn: (data) => enrichmentApi.createBatch(data),
    onSuccess: () => {
      qc.invalidateQueries(['enrBatches'])
      qc.invalidateQueries(['enrReport'])
      setShowCreateForm(false)
      setBatchName('')
    },
  })

  const cancelBatch = useMutation({
    mutationFn: (id) => enrichmentApi.cancelBatch(id),
    onSuccess: () => qc.invalidateQueries(['enrBatches']),
  })

  const bulkApprove = useMutation({
    mutationFn: ({ itemId, conf }) => enrichmentApi.bulkApprove(itemId, conf),
    onSuccess: () => {
      qc.invalidateQueries(['enrQueue', queueParams])
      qc.invalidateQueries(['enrReport'])
    },
  })

  const recompute = useMutation({
    mutationFn: () => enrichmentApi.recomputeScores(),
    onSuccess: () => {
      qc.invalidateQueries(['enrReport'])
      qc.invalidateQueries(['enrQueue'])
    },
  })

  const generate = useMutation({
    mutationFn: ({ itemPk }) => enrichmentApi.generate(itemPk, false),
    onSuccess: () => qc.invalidateQueries(['enrQueue', queueParams]),
  })

  // ── Derived report values ─────────────────────────────────────────────
  const rpt     = report || {}
  const total   = rpt.total_items        || 0
  const avg     = Math.round(rpt.avg_score || 0)
  const complete = rpt.complete           || 0
  const partial  = rpt.partial            || 0
  const empty    = rpt.empty              || 0
  const pending  = rpt.suggestions_pending  || 0
  const approved = rpt.suggestions_approved || 0

  // ── Helpers ───────────────────────────────────────────────────────────
  const buildScopeParams = () => {
    if (scopeType === 'category' && scopeParam) return { category: scopeParam }
    if (scopeType === 'supplier' && scopeParam) return { supplier: scopeParam }
    return {}
  }

  const handleCreateBatch = () => {
    createBatch.mutate({
      name:                   batchName || `دفعة ${new Date().toLocaleDateString('en-US')}`,
      scope_type:             scopeType,
      scope_params:           buildScopeParams(),
      auto_publish_threshold: threshold,
    })
  }

  return (
    <div className="flex gap-5 h-full overflow-hidden">

      {/* ── LEFT COLUMN: Report + Batch Management ───────────────────── */}
      <div className="w-80 flex-shrink-0 flex flex-col gap-4 overflow-y-auto">

        {/* Quality Report */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-gray-800 text-sm">📊 تقرير جودة الكتالوج</h3>
            <button
              onClick={() => refetchReport()}
              disabled={reportLoading}
              className="text-xs text-blue-600 hover:underline disabled:opacity-40"
            >
              {reportLoading ? '...' : '↻ تحديث'}
            </button>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-2 gap-2">
            <StatCard label="إجمالي الأصناف"   value={total}    color="blue"   />
            <StatCard label="متوسط الاكتمال"   value={`${avg}%`} color={avg >= 70 ? 'green' : avg >= 40 ? 'yellow' : 'red'} />
            <StatCard label="مكتملة ≥80%"      value={complete}  color="green"  />
            <StatCard label="ناقصة"            value={partial}   color="yellow" />
            <StatCard label="فارغة"            value={empty}     color="red"    />
            <StatCard label="اقتراحات معلّقة"  value={pending}   color="purple" />
          </div>

          {/* Completeness bar */}
          {total > 0 && (
            <div>
              <div className="text-xs text-gray-500 mb-1">توزيع الاكتمال</div>
              <div className="flex h-3 rounded-full overflow-hidden gap-0.5">
                <div className="bg-green-500"  style={{ width: `${(complete / total) * 100}%` }} title={`مكتمل: ${complete}`} />
                <div className="bg-yellow-400" style={{ width: `${(partial  / total) * 100}%` }} title={`ناقص: ${partial}`} />
                <div className="bg-red-300"    style={{ width: `${(empty    / total) * 100}%` }} title={`فارغ: ${empty}`} />
              </div>
              <div className="flex justify-between text-xs text-gray-400 mt-1">
                <span className="text-green-600">مكتمل {complete}</span>
                <span className="text-yellow-600">ناقص {partial}</span>
                <span className="text-red-500">فارغ {empty}</span>
              </div>
            </div>
          )}

          <button
            onClick={() => recompute.mutate()}
            disabled={recompute.isPending}
            className="w-full py-2 bg-gray-100 text-gray-700 rounded-lg text-xs font-medium hover:bg-gray-200 disabled:opacity-40 transition-colors"
          >
            {recompute.isPending ? 'جارٍ إعادة الحساب...' : '🔄 إعادة حساب نسب الاكتمال'}
          </button>
        </div>

        {/* Batch Management */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-gray-800 text-sm">⚙️ دفعات الإثراء</h3>
            <button
              onClick={() => setShowCreateForm(v => !v)}
              className="text-xs bg-blue-600 text-white px-3 py-1 rounded-lg hover:bg-blue-700 transition-colors"
            >
              {showCreateForm ? '✕ إلغاء' : '＋ دفعة جديدة'}
            </button>
          </div>

          {/* Create form */}
          {showCreateForm && (
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 space-y-2.5">
              <div>
                <label className="text-xs text-gray-600 block mb-1">اسم الدفعة (اختياري)</label>
                <input
                  value={batchName}
                  onChange={e => setBatchName(e.target.value)}
                  placeholder={`دفعة ${new Date().toLocaleDateString('en-US')}`}
                  className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                />
              </div>

              <div>
                <label className="text-xs text-gray-600 block mb-1">نطاق الدفعة</label>
                <select
                  value={scopeType}
                  onChange={e => { setScopeType(e.target.value); setScopeParam('') }}
                  className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                >
                  {SCOPE_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>

              {(scopeType === 'category' || scopeType === 'supplier') && (
                <div>
                  <label className="text-xs text-gray-600 block mb-1">
                    {scopeType === 'category' ? 'اسم التصنيف' : 'كود المورّد'}
                  </label>
                  <input
                    value={scopeParam}
                    onChange={e => setScopeParam(e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                  />
                </div>
              )}

              <div>
                <label className="text-xs text-gray-600 block mb-1">
                  حد النشر التلقائي — {Math.round(threshold * 100)}%
                </label>
                <input
                  type="range" min={0.5} max={1.0} step={0.05}
                  value={threshold}
                  onChange={e => setThreshold(parseFloat(e.target.value))}
                  className="w-full accent-blue-600"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                  <span>50%</span><span>75%</span><span>100%</span>
                </div>
              </div>

              <button
                onClick={handleCreateBatch}
                disabled={createBatch.isPending}
                className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-40 transition-colors"
              >
                {createBatch.isPending ? 'جارٍ الإنشاء...' : '🚀 تشغيل الدفعة'}
              </button>
            </div>
          )}

          {/* Batch list */}
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {batchLoading && !batches.length && (
              <div className="text-center py-4 text-xs text-gray-400">جارٍ التحميل...</div>
            )}
            {batches.map(b => {
              const pct = b.total_items > 0
                ? Math.round((b.processed_items / b.total_items) * 100)
                : (b.status === 'success' ? 100 : 0)
              return (
                <div key={b.id} className="border border-gray-100 rounded-xl p-3 space-y-1.5 bg-gray-50">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-gray-700 truncate flex-1">
                      {b.name || `دفعة #${b.id}`}
                    </span>
                    <BatchStatusBadge status={b.status} />
                    {(b.status === 'running' || b.status === 'pending') && (
                      <button
                        onClick={() => cancelBatch.mutate(b.id)}
                        disabled={cancelBatch.isPending}
                        className="text-xs text-red-500 hover:text-red-700 disabled:opacity-40"
                        title="إلغاء"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                  <MiniProgressBar pct={pct} status={b.status} />
                  <div className="flex justify-between text-xs text-gray-400">
                    <span>{b.processed_items} / {b.total_items} صنف</span>
                    <span>{b.suggestions_generated} اقتراح · {b.auto_published} نُشر</span>
                  </div>
                  {b.error_count > 0 && (
                    <div className="text-xs text-red-500">{b.error_count} خطأ</div>
                  )}
                </div>
              )
            })}
            {!batchLoading && batches.length === 0 && (
              <div className="text-center py-4 text-xs text-gray-400">لا توجد دفعات بعد</div>
            )}
          </div>
        </div>
      </div>

      {/* ── RIGHT COLUMN: Item Queue ──────────────────────────────────── */}
      <div className="flex-1 flex flex-col gap-3 min-w-0 overflow-hidden">
        {/* Queue header + filters */}
        <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex-shrink-0 space-y-2">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-bold text-gray-800 text-sm">📋 قائمة الأصناف بحاجة للإثراء</h3>
            <span className="text-xs text-gray-400">{queueTotal} صنف</span>
          </div>
          <div className="flex gap-2 flex-wrap items-center">
            <input
              value={qSearch}
              onChange={e => handleQSearch(e.target.value)}
              placeholder="بحث بالاسم أو الكود..."
              className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 w-56"
            />
            {[['', 'الكل'], ['empty', 'فارغة'], ['partial', 'ناقصة'], ['complete', 'مكتملة']].map(([v, l]) => (
              <button
                key={v}
                onClick={() => { setQScore(v); setQPage(1) }}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                  qScore === v
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-500 border-gray-200 hover:border-blue-300'
                }`}
              >
                {l}
              </button>
            ))}
            <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer mr-1">
              <input
                type="checkbox" checked={qHasPending}
                onChange={e => { setQHasPending(e.target.checked); setQPage(1) }}
                className="rounded"
              />
              لديها اقتراحات معلّقة
            </label>
          </div>
        </div>

        {/* Queue table */}
        <div className="flex-1 bg-white rounded-xl border border-gray-200 overflow-hidden flex flex-col">
          <div className="flex-1 overflow-y-auto">
            {queueLoading && !queueItems.length && (
              <div className="text-center py-12 text-sm text-gray-400">جارٍ التحميل...</div>
            )}
            {!queueLoading && queueItems.length === 0 && (
              <div className="text-center py-12 text-sm text-gray-400">لا توجد نتائج</div>
            )}

            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr className="text-right">
                  <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 border-b border-gray-100">الصنف</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 border-b border-gray-100 w-36">الاكتمال</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 border-b border-gray-100 text-center w-20">معلّق</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 border-b border-gray-100 text-center w-20">منشور</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 border-b border-gray-100 w-56 text-center">إجراءات</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {queueItems.map(item => {
                  const pct   = Math.round(item.completeness_score || 0)
                  const color = pct >= 80 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-400' : 'bg-red-400'
                  return (
                    <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-800">{item.item_name}</div>
                        <div className="text-xs text-gray-400 font-mono">{item.item_code}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                            <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
                          </div>
                          <span className="text-xs font-bold text-gray-600 w-8 text-left">{pct}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {item.pending_count > 0 ? (
                          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-orange-100 text-orange-700 text-xs font-bold">
                            {item.pending_count}
                          </span>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className={`text-xs font-medium ${item.is_published ? 'text-green-600' : 'text-gray-400'}`}>
                          {item.is_published ? '✓ منشور' : '—'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-center gap-1.5">
                          {/* Generate suggestions */}
                          <button
                            onClick={() => generate.mutate({ itemPk: item.item_id })}
                            disabled={generate.isPending}
                            className="px-2.5 py-1 bg-blue-50 text-blue-700 rounded-lg text-xs font-medium hover:bg-blue-100 disabled:opacity-40 transition-colors border border-blue-200"
                            title="استخراج اقتراحات"
                          >
                            🔍 استخراج
                          </button>
                          {/* Bulk approve ≥80% */}
                          {item.pending_count > 0 && (
                            <button
                              onClick={() => bulkApprove.mutate({ itemId: item.item_id, conf: 0.80 })}
                              disabled={bulkApprove.isPending}
                              className="px-2.5 py-1 bg-green-50 text-green-700 rounded-lg text-xs font-medium hover:bg-green-100 disabled:opacity-40 transition-colors border border-green-200"
                              title="قبول كل الاقتراحات ≥80% ثقة"
                            >
                              ✓ قبول ≥80%
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 bg-gray-50 flex-shrink-0">
              <button
                onClick={() => setQPage(p => Math.max(1, p - 1))}
                disabled={qPage === 1}
                className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-white disabled:opacity-40 transition-colors"
              >
                ← السابق
              </button>
              <span className="text-xs text-gray-500">
                صفحة {qPage} من {totalPages} · {queueTotal} صنف
              </span>
              <button
                onClick={() => setQPage(p => Math.min(totalPages, p + 1))}
                disabled={qPage === totalPages}
                className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-white disabled:opacity-40 transition-colors"
              >
                التالي →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────
const TABS = [
  { key: 'variants',    label: '🔗 مجموعات المتغيرات' },
  { key: 'bundles',     label: '📦 الباقات' },
  { key: 'fbt',         label: '🧩 يُشترى معه عادةً' },
  { key: 'enrichment',  label: '🤖 إثراء الكتالوج' },
]

export default function CatalogIntelligencePage() {
  const [tab, setTab] = useState('variants')

  return (
    <div className="flex flex-col h-screen bg-gray-50" dir="rtl">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <h1 className="text-xl font-bold text-gray-800">🧠 ذكاء الكتالوج</h1>
        <p className="text-xs text-gray-400 mt-0.5">
          إدارة مجموعات المتغيرات والباقات وبيانات الشراء المتزامن · إثراء بيانات الكتالوج بالذكاء الاصطناعي
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 bg-white px-6">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-3 text-sm font-medium transition-colors ${
              tab === t.key
                ? 'border-b-2 border-blue-600 text-blue-700'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden p-6">
        {tab === 'variants'   && <VariantGroupsTab />}
        {tab === 'bundles'    && <BundlesTab />}
        {tab === 'fbt'        && <FBTPairsTab />}
        {tab === 'enrichment' && <EnrichmentManagementTab />}
      </div>
    </div>
  )
}
