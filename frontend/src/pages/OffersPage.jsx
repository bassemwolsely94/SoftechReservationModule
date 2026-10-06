/**
 * OffersPage — the Odoo-style offers configuration module (/offers).
 *
 * List + editor for the rich offers engine: 8 types (incl. mix & match / bundle),
 * a flexible any-field product selector with يتضمن / لا يتضمن / يحتوي operators and
 * real-value dropdown pickers, a LIVE match preview you can review + exclude items
 * from, magnitude source, stacking/approval controls, usage limits, a validity
 * window, and a CONTRADICTIONS panel (no-items / sell-at-loss / overlap / priority).
 * All PG-only — SOFTECH execution is gated elsewhere. Backend owns every decision.
 */
import { useEffect, useMemo, useState } from 'react'
import { offersApi } from '../api/client'
import ItemSearchWidget from '../components/ItemSearchWidget'
import { useToast } from '../components/ui'

const TYPES = [
  { v: 'percent', l: 'خصم نسبة مئوية' }, { v: 'fixed', l: 'خصم مبلغ ثابت' },
  { v: 'bxgy', l: 'اشترِ X واحصل على Y (الأقل سعرًا)' }, { v: 'qty_tier', l: 'خصم متدرّج بالكمية' },
  { v: 'gift', l: 'صنف هدية عند الشراء' }, { v: 'spend_threshold', l: 'مكافأة عند تجاوز مبلغ' },
  { v: 'bundle', l: 'باقة بسعر ثابت' }, { v: 'mix_match', l: 'اختر أي N من مجموعة (mix & match)' },
]
const TYPE_HELP = {
  percent: 'خصم نسبة % على كل صنف مطابق.',
  fixed: 'خصم مبلغ ثابت على الصنف المطابق.',
  bxgy: 'اشترِ X واحصل على Y — يُخصَم الأقل سعرًا (1+1، 2+1…).',
  qty_tier: 'كلما زادت الكمية زاد الخصم — شرائح متدرّجة.',
  gift: 'صنف هدية مجاني عند شراء كمية محدَّدة.',
  spend_threshold: 'مكافأة/هدية عند تجاوز إجمالي مبلغ معيّن.',
  bundle: 'باقة أصناف بسعر إجمالي ثابت (combo).',
  mix_match: 'اختر أي N صنف من المجموعة بخصم/سعر موحّد — mix & match.',
}
const STATUSES = [{ v: 'draft', l: 'مسودة' }, { v: 'active', l: 'فعّال' },
                  { v: 'paused', l: 'موقوف' }, { v: 'expired', l: 'منتهي' }]
const CHANNELS = [{ v: 'cash', l: 'كاش' }, { v: 'home_delivery', l: 'توصيل' }, { v: 'contract', l: 'تعاقد' }]
const SEGMENTS = ['vip', 'loyal', 'regular', 'at_risk', 'dormant', 'new']

// per-field icon + one-line "what is this / how to use it" annotation
const FIELD_META = {
  producer_code:      { icon: '🏭', help: 'الشركة المنتِجة (كود) — عرض على كل أصناف منتِج معيّن.' },
  producer_name:      { icon: '🏭', help: 'اسم الشركة المنتِجة.' },
  supplier_code:      { icon: '🚚', help: 'المورد الرئيسي (كود).' },
  supplier_name:      { icon: '🚚', help: 'اسم المورد الرئيسي.' },
  name:               { icon: '🔤', help: 'اسم الصنف — استخدم «يحتوي» لمطابقة جزء من الاسم.' },
  name_scientific:    { icon: '🧪', help: 'الاسم العلمي (قد يكون غير دقيق — راجع قائمة المطابق).' },
  family_code:        { icon: '🧬', help: 'العائلة الدوائية (كود).' },
  family_name:        { icon: '🧬', help: 'اسم العائلة الدوائية.' },
  medicine_type:      { icon: '🏷️', help: 'التصنيف العام (كود).' },
  medicine_type_name: { icon: '🏷️', help: 'التصنيف العام بالاسم.' },
  store_classif:      { icon: '🗂️', help: 'التصنيف الداخلي للمخزن.' },
  origin_code:        { icon: '🌍', help: 'بلد المنشأ (كود).' },
  origin_name:        { icon: '🌍', help: 'اسم بلد المنشأ.' },
  shape_code:         { icon: '💊', help: 'الشكل الصيدلي (كود).' },
  shape_name:         { icon: '💊', help: 'اسم الشكل الصيدلي.' },
  effect_code:        { icon: '⚕️', help: 'المفعول/التأثير.' },
  unit_code:          { icon: '📦', help: 'الوحدة (كود).' },
  unit_name:          { icon: '📦', help: 'اسم الوحدة.' },
  insurance_type:     { icon: '🛡️', help: 'نوع التأمين.' },
  category:           { icon: '📁', help: 'فئة الكتالوج الداخلية.' },
  item_level:         { icon: '⭐', help: 'مستوى الصنف (رقم).' },
  pack_price:         { icon: '💰', help: 'سعر العبوة — استخدم «مدى» لاستهداف نطاق أسعار.' },
  unit_price:         { icon: '💵', help: 'سعر الوحدة.' },
  requires_fridge:    { icon: '❄️', help: 'أصناف الثلاجة.' },
  is_fast_moving:     { icon: '⚡', help: 'أصناف سريعة الحركة.' },
  is_imported:        { icon: '✈️', help: 'صنف مستورد.' },
  no_more_use:        { icon: '🚫', help: 'موقوف/لا يُستخدَم.' },
  item_archive:       { icon: '🗃️', help: 'صنف مؤرشف.' },
  is_stockable:       { icon: '📊', help: 'قابل للتخزين.' },
  in_shortage:        { icon: '📉', help: 'ضمن نواقص السوق.' },
}

const BLANK = {
  name: '', name_ar: '', offer_type: 'bxgy', status: 'draft', description: '',
  authorization_source: 'item_card', value: 0, max_discount_amount: null,
  buy_qty: 1, get_qty: 1, get_discount_percent: 100, bxgy_scope: 'group_cheapest',
  qty_tiers: [], gift_item: null, bundle_price: null,
  target_all: false, target_spec: { match: 'all', rules: [] },
  items: [], excluded_items: [], classification_filters: {}, require_stock: true,
  segments: [], channels: [], branches: [], min_basket_amount: 0, min_qty: 0,
  stackable: false, priority: 0, is_clearance: false, requires_approval: false,
  max_uses_total: null, max_uses_per_customer: null, starts_at: null, ends_at: null,
}

export default function OffersPage() {
  const toast = useToast()
  const [rows, setRows] = useState([])
  const [fields, setFields] = useState([])
  const [editing, setEditing] = useState(null)   // null = list view
  const [loading, setLoading] = useState(false)

  const load = () => { setLoading(true); offersApi.list().then(r => setRows(r.data.results || r.data || [])).finally(() => setLoading(false)) }
  useEffect(() => { load(); offersApi.targetFields().then(r => setFields(r.data)).catch(() => {}) }, [])

  if (editing) {
    return <OfferEditor draft={editing} fields={fields} toast={toast}
                        onDone={() => { setEditing(null); load() }} onCancel={() => setEditing(null)} />
  }

  return (
    <div className="page-body">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-lg font-bold text-content">العروض والتخفيضات</h1>
          <p className="text-xs text-faint">محرّك عروض مرن — تُطبَّق عبر نقطة البيع؛ التنفيذ في سوفتك مُقيَّد بمفتاح.</p>
        </div>
        <button className="btn-primary" onClick={() => setEditing({ ...BLANK })}>+ عرض جديد</button>
      </div>

      <div className="card p-0 overflow-x-auto">
        <table className="data-table">
          <thead><tr>
            <th>الاسم</th><th>النوع</th><th>الحالة</th><th>الأولوية</th><th>مصدر القيمة</th><th>أصناف</th><th></th>
          </tr></thead>
          <tbody>
            {rows.map(o => (
              <tr key={o.id} className="cursor-pointer" onClick={() => offersApi.get(o.id).then(r => setEditing(normalize(r.data)))}>
                <td className="font-semibold text-content">{o.name_ar || o.name}</td>
                <td>{TYPES.find(t => t.v === o.offer_type)?.l || o.offer_type}</td>
                <td><span className={`badge ${o.status === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-surface-3 text-muted'}`}>{o.status_label || o.status}</span></td>
                <td className="tabnum">{o.priority}</td>
                <td className="text-xs">{o.authorization_source === 'item_card' ? 'كارت الصنف' : 'العرض (موافقة)'}</td>
                <td className="tabnum text-xs">{o.target_all ? 'الكل' : (o.item_count ?? '—')}</td>
                <td className="text-brand-600 text-xs">تعديل ←</td>
              </tr>
            ))}
            {!rows.length && !loading && <tr><td colSpan={7} className="text-center text-faint py-10">لا عروض بعد.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function normalize(o) {
  // API returns M2M as id arrays; keep as-is and default JSON fields
  return {
    ...BLANK, ...o,
    target_spec: o.target_spec && o.target_spec.rules ? o.target_spec : { match: 'all', rules: [] },
    items: o.items || [], excluded_items: o.excluded_items || [], qty_tiers: o.qty_tiers || [],
    segments: o.segments || [], channels: o.channels || [],
  }
}

// ─────────────────────────────────────────────────────────────────────────────
function OfferEditor({ draft, fields, toast, onDone, onCancel }) {
  const [o, setO] = useState(draft)
  const [saving, setSaving] = useState(false)
  const [checkKey, setCheckKey] = useState(0)   // bump → re-run validate after save
  const set = (k, v) => setO(prev => ({ ...prev, [k]: v }))

  const save = () => {
    if (!o.name && !o.name_ar) { toast?.error?.('أدخل اسم العرض'); return }
    setSaving(true)
    // backend requires `name` (EN); fall back to the Arabic name so filling one is enough
    const body = { ...o, name: o.name || o.name_ar, name_ar: o.name_ar || o.name }
    const req = o.id ? offersApi.update(o.id, body) : offersApi.create(body)
    req.then(r => {
        toast?.success?.('تم حفظ العرض')
        if (!o.id && r?.data?.id) set('id', r.data.id)   // stay in editor, enable panels
        setCheckKey(k => k + 1)
      })
       .catch(e => toast?.error?.(e?.response?.data?.detail || 'فشل الحفظ — تحقق من الصلاحية والحقول'))
       .finally(() => setSaving(false))
  }
  const remove = () => { if (o.id && confirm('حذف العرض؟')) offersApi.remove(o.id).then(onDone) }

  const t = o.offer_type
  return (
    <div className="page-body max-w-4xl">
      <div className="flex items-center justify-between mb-4">
        <button onClick={onCancel} className="text-sm text-muted hover:text-content">→ رجوع للقائمة</button>
        <div className="flex gap-2">
          {o.id && <button onClick={remove} className="btn-danger text-xs">حذف</button>}
          <button onClick={onDone} className="btn-secondary text-xs">تم</button>
          <button onClick={save} disabled={saving} className="btn-primary">{saving ? '…' : 'حفظ العرض'}</button>
        </div>
      </div>

      {/* Contradiction warnings (saved offers) */}
      {o.id && <WarningsPanel offerId={o.id} refreshKey={checkKey} />}

      {/* Basics */}
      <Section title="الأساسيات" icon="📝">
        <Grid>
          <Field label="الاسم (عربي)"><input className="input-field" value={o.name_ar} onChange={e => set('name_ar', e.target.value)} /></Field>
          <Field label="الاسم (EN)"><input className="input-field" value={o.name} onChange={e => set('name', e.target.value)} /></Field>
          <Field label="النوع" help={TYPE_HELP[t]}>
            <select className="input-field" value={t} onChange={e => set('offer_type', e.target.value)}>
              {TYPES.map(x => <option key={x.v} value={x.v}>{x.l}</option>)}
            </select>
          </Field>
          <Field label="الحالة">
            <select className="input-field" value={o.status} onChange={e => set('status', e.target.value)}>
              {STATUSES.map(x => <option key={x.v} value={x.v}>{x.l}</option>)}
            </select>
          </Field>
        </Grid>
        <p className="text-[11px] text-faint mt-2">💡 {TYPE_HELP[t]}</p>
      </Section>

      {/* Type params */}
      <Section title="إعدادات النوع" icon="⚙️">
        <Grid>
          {(t === 'percent' || t === 'fixed' || t === 'mix_match') &&
            <Field label={t === 'fixed' ? 'المبلغ' : 'النسبة %'}><Num v={o.value} on={v => set('value', v)} /></Field>}
          {t === 'percent' && <Field label="حد أقصى للخصم (اختياري)"><Num v={o.max_discount_amount} on={v => set('max_discount_amount', v)} /></Field>}
          {(t === 'bxgy' || t === 'gift') && <Field label="اشترِ (كمية)"><Num v={o.buy_qty} on={v => set('buy_qty', v)} /></Field>}
          {(t === 'bxgy' || t === 'gift') && <Field label="احصل على (كمية)"><Num v={o.get_qty} on={v => set('get_qty', v)} /></Field>}
          {(t === 'bxgy' || t === 'gift' || t === 'spend_threshold') &&
            <Field label="نسبة خصم المجاني % (100=مجانًا)"><Num v={o.get_discount_percent} on={v => set('get_discount_percent', v)} /></Field>}
          {t === 'mix_match' && <Field label="أي N (min qty)"><Num v={o.min_qty} on={v => set('min_qty', v)} /></Field>}
          {t === 'bundle' && <Field label="سعر الباقة"><Num v={o.bundle_price} on={v => set('bundle_price', v)} /></Field>}
          {t === 'spend_threshold' && <Field label="حد المبلغ (أقل إجمالي)"><Num v={o.min_basket_amount} on={v => set('min_basket_amount', v)} /></Field>}
        </Grid>
        {(t === 'gift' || t === 'spend_threshold') &&
          <ItemPick label="صنف الهدية" value={o.gift_item ? [o.gift_item] : []} single
                    onChange={ids => set('gift_item', ids[0] || null)} />}
        {t === 'qty_tier' && <TierEditor tiers={o.qty_tiers} on={v => set('qty_tiers', v)} />}
      </Section>

      {/* Magnitude source */}
      <Section title="مصدر قيمة الخصم" icon="🔑">
        <div className="flex gap-2">
          {[['item_card', 'من كارت الصنف (posdiscp)'], ['offer', 'من العرض (يتطلب موافقة)']].map(([v, l]) => (
            <button key={v} onClick={() => set('authorization_source', v)}
              className={`px-3 py-2 rounded-lg border text-sm ${o.authorization_source === v ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-muted'}`}>{l}</button>
          ))}
        </div>
        <p className="text-[11px] text-faint mt-2">
          {o.authorization_source === 'item_card'
            ? 'يستخدم نسبة خصم كارت الصنف المُعتمَدة مسبقًا — لا يحتاج موافقة إضافية.'
            : 'قيمة العرض تتجاوز كارت الصنف — تتطلّب موافقة وقد تسبّب بيعًا بالخسارة، انتبه للتحذيرات.'}
        </p>
      </Section>

      {/* Flexible selector */}
      <Section title="اختيار الأصناف (مرن)" icon="🎯">
        <label className="flex items-center gap-2 text-sm mb-2">
          <input type="checkbox" checked={o.target_all} onChange={e => set('target_all', e.target.checked)} /> كل الأصناف
        </label>
        {!o.target_all && (
          <>
            <RuleBuilder fields={fields} spec={o.target_spec} on={v => set('target_spec', v)} />
            <div className="grid md:grid-cols-2 gap-3 mt-3">
              <ItemPick label="✅ تضمين يدوي (أصناف تُضاف للمطابقة)" value={o.items} onChange={ids => set('items', ids)} />
              <ItemPick label="⛔ استبعاد يدوي (أصناف تُستثنى)" value={o.excluded_items} onChange={ids => set('excluded_items', ids)} />
            </div>
          </>
        )}
        <label className="flex items-center gap-2 text-sm mt-3">
          <input type="checkbox" checked={o.require_stock} onChange={e => set('require_stock', e.target.checked)} /> يشترط توفر رصيد (يمكن التجاوز بإيقافه)
        </label>
        <MatchReview o={o} set={set} />
      </Section>

      {/* Channel A — flat-rate posdiscp (saved percent offers only) */}
      {o.id && t === 'percent' && <PosdiscpPanel offerId={o.id} />}

      {/* Channel B — native SOFTECH promo table (gift / spend / single-item percent) */}
      {o.id && ['gift', 'spend_threshold', 'percent'].includes(t) && <PromoPanel offerId={o.id} />}

      {/* Eligibility */}
      <Section title="الأهلية" icon="👥">
        <Grid>
          <Field label="أقل إجمالي للسلة"><Num v={o.min_basket_amount} on={v => set('min_basket_amount', v)} /></Field>
          <Field label="أقل كمية مؤهِّلة"><Num v={o.min_qty} on={v => set('min_qty', v)} /></Field>
        </Grid>
        <MultiChips label="شرائح العملاء (فارغ=الكل)" options={SEGMENTS.map(s => ({ v: s, l: s }))} value={o.segments} on={v => set('segments', v)} />
        <MultiChips label="قنوات البيع (فارغ=الكل)" options={CHANNELS} value={o.channels} on={v => set('channels', v)} />
      </Section>

      {/* Controls */}
      <Section title="ضوابط" icon="🎚️">
        <Grid>
          <Field label="الأولوية" help="عند تداخل عرضين على نفس الصنف يُطبَّق الأعلى أولوية؛ لا تكرّر نفس الأولوية لعرضين متعارضين.">
            <Num v={o.priority} on={v => set('priority', v)} /></Field>
          <Field label="حد الاستخدام الكلي"><Num v={o.max_uses_total} on={v => set('max_uses_total', v)} /></Field>
          <Field label="حد الاستخدام لكل عميل"><Num v={o.max_uses_per_customer} on={v => set('max_uses_per_customer', v)} /></Field>
        </Grid>
        <div className="flex flex-wrap gap-4 mt-2 text-sm">
          <Check label="قابل للدمج" v={o.stackable} on={v => set('stackable', v)} />
          <Check label="يتطلب موافقة" v={o.requires_approval} on={v => set('requires_approval', v)} />
          <Check label="تصفية" v={o.is_clearance} on={v => set('is_clearance', v)} />
        </div>
        <Grid>
          <Field label="يبدأ"><input type="datetime-local" className="input-field" value={dtLocal(o.starts_at)} onChange={e => set('starts_at', e.target.value || null)} /></Field>
          <Field label="ينتهي"><input type="datetime-local" className="input-field" value={dtLocal(o.ends_at)} onChange={e => set('ends_at', e.target.value || null)} /></Field>
        </Grid>
      </Section>
    </div>
  )
}

// ── small building blocks ────────────────────────────────────────────────────
const Section = ({ title, icon, children }) => (
  <div className="card mb-3"><div className="section-title flex items-center gap-1.5">{icon && <span>{icon}</span>}{title}</div>{children}</div>)
const Grid = ({ children }) => <div className="grid md:grid-cols-2 gap-3">{children}</div>
const Field = ({ label, help, children }) => (
  <div>
    <label className="label flex items-center gap-1">
      {label}
      {help && <span className="text-faint cursor-help" title={help}>ⓘ</span>}
    </label>
    {children}
  </div>
)
const Num = ({ v, on }) => <input type="number" step="any" className="input-field"
  value={v ?? ''} onChange={e => on(e.target.value === '' ? null : Number(e.target.value))} />
const Check = ({ label, v, on }) => (
  <label className="flex items-center gap-2"><input type="checkbox" checked={!!v} onChange={e => on(e.target.checked)} /> {label}</label>)
const dtLocal = (s) => (s ? String(s).slice(0, 16) : '')

// ── Contradiction warnings (no-items / loss / overlap / priority) ─────────────
const WARN_ICON = { no_items: '🚫', loss: '💸', overlap: '🔀', priority: '⚖️' }
function WarningsPanel({ offerId, refreshKey }) {
  const [warnings, setWarnings] = useState(null)
  const [loading, setLoading] = useState(false)
  const run = () => {
    setLoading(true)
    offersApi.validate(offerId).then(r => setWarnings(r.data.warnings || [])).catch(() => setWarnings([])).finally(() => setLoading(false))
  }
  useEffect(() => { run() }, [offerId, refreshKey])
  if (loading && warnings === null) return null
  if (warnings && !warnings.length) {
    return <div className="card mb-3 border-emerald-200 bg-emerald-50/60">
      <div className="text-sm text-emerald-700 flex items-center gap-2">✓ لا تعارضات — الإعداد سليم.
        <button className="text-[11px] text-emerald-600 underline" onClick={run}>إعادة الفحص</button></div>
    </div>
  }
  return (
    <div className="card mb-3 border-amber-300 bg-amber-50/60">
      <div className="section-title flex items-center justify-between text-amber-800">
        <span>⚠ تنبيهات الإعداد</span>
        <button className="text-[11px] text-amber-700 underline" onClick={run} disabled={loading}>{loading ? '…' : 'إعادة الفحص'}</button>
      </div>
      <ul className="space-y-1 mt-1">
        {(warnings || []).map((w, i) => (
          <li key={i} className={`text-xs flex items-start gap-2 rounded px-2 py-1 border ${w.level === 'error' ? 'bg-red-50 border-red-200 text-red-700' : 'bg-amber-50 border-amber-200 text-amber-800'}`}>
            <span>{WARN_ICON[w.code] || '•'}</span><span>{w.msg}</span>
          </li>
        ))}
      </ul>
      <p className="text-[10px] text-faint mt-1">تُحسب على العرض المحفوظ — احفظ بعد التعديل ثم «إعادة الفحص».</p>
    </div>
  )
}

// ── Live match review + per-item exclude + loss highlight ─────────────────────
function MatchReview({ o, set }) {
  const [data, setData] = useState(null)
  const [expanded, setExpanded] = useState(false)
  const specKey = JSON.stringify([o.target_all, o.target_spec, o.items, o.excluded_items, o.classification_filters, o.require_stock])
  useEffect(() => {
    const id = setTimeout(() => {
      offersApi.targetPreview({
        target_all: o.target_all, target_spec: o.target_spec,
        include_ids: o.items, exclude_ids: o.excluded_items,
        classification_filters: o.classification_filters, require_stock: o.require_stock,
        limit: expanded ? 200 : 14,
      }).then(r => setData(r.data)).catch(() => setData(null))
    }, 350)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specKey, expanded])

  const netOf = (row) => {
    const itemCard = o.authorization_source === 'item_card'
    if (o.offer_type === 'fixed' && !itemCard) return row.pack_price - Number(o.value || 0)
    const disc = itemCard ? row.pos_discp : Number(o.value || 0)
    return disc ? row.pack_price * (1 - disc / 100) : row.pack_price
  }
  const isLoss = (row) => row.cost_price > 0 && netOf(row) < row.cost_price
  const exclude = (id) => set('excluded_items', [...(o.excluded_items || []), id])

  const count = data?.count ?? null
  const lossN = (data?.sample || []).filter(isLoss).length

  return (
    <div className="mt-3 rounded-lg bg-surface-2 border border-line p-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-bold text-content flex items-center gap-2">
          <span>المطابق: {count === null ? '…' : count} صنف</span>
          {count === 0 && <span className="text-red-600">🚫 لا أصناف مطابقة</span>}
          {lossN > 0 && <span className="text-amber-600">💸 {lossN}+ قد يُباع بالخسارة</span>}
        </div>
        {count > 0 && <button className="text-[11px] text-brand-600 underline" onClick={() => setExpanded(e => !e)}>
          {expanded ? 'إخفاء القائمة' : 'مراجعة القائمة'}</button>}
      </div>

      {!expanded && (
        <div className="text-[11px] text-faint mt-1 line-clamp-2">
          {(data?.sample || []).slice(0, 12).map(s => `${s.name} (${s.softech_id})`).join(' · ') || '—'}
        </div>
      )}

      {expanded && (
        <div className="mt-2 max-h-72 overflow-y-auto rounded border border-line bg-surface-1">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-surface-2 text-faint">
              <tr><th className="text-start px-2 py-1">الصنف</th><th className="px-2 py-1">السعر</th><th className="px-2 py-1">الصافي</th><th className="px-2 py-1"></th></tr>
            </thead>
            <tbody>
              {(data?.sample || []).map(row => {
                const loss = isLoss(row)
                return (
                  <tr key={row.id} className={`border-t border-line ${loss ? 'bg-red-50' : ''}`}>
                    <td className="px-2 py-1 text-content">{row.name} <span className="text-faint">({row.softech_id})</span></td>
                    <td className="px-2 py-1 tabnum text-center text-muted">{row.pack_price.toFixed(2)}</td>
                    <td className={`px-2 py-1 tabnum text-center ${loss ? 'text-red-600 font-bold' : 'text-muted'}`}>{netOf(row).toFixed(2)}{loss && ' 💸'}</td>
                    <td className="px-2 py-1 text-center">
                      <button className="text-red-500 hover:text-red-700" title="استبعاد هذا الصنف" onClick={() => exclude(row.id)}>استبعاد ×</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {count > (data?.sample?.length || 0) &&
            <div className="text-[10px] text-faint px-2 py-1">عرض {data.sample.length} من {count} — ضيّق المحدِّد لمراجعة الباقي.</div>}
        </div>
      )}
    </div>
  )
}

function MultiChips({ label, options, value, on }) {
  const toggle = (v) => on(value.includes(v) ? value.filter(x => x !== v) : [...value, v])
  return (
    <div className="mt-2">
      <label className="label">{label}</label>
      <div className="flex flex-wrap gap-1">
        {options.map(o => (
          <button key={o.v} onClick={() => toggle(o.v)}
            className={`text-xs px-2 py-1 rounded border ${value.includes(o.v) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-muted'}`}>{o.l}</button>
        ))}
      </div>
    </div>
  )
}

function TierEditor({ tiers, on }) {
  const add = () => on([...(tiers || []), { min_qty: 1, percent: 0 }])
  const upd = (i, k, v) => on(tiers.map((t, j) => j === i ? { ...t, [k]: Number(v) } : t))
  return (
    <div className="mt-2">
      <label className="label">الشرائح</label>
      {(tiers || []).map((t, i) => (
        <div key={i} className="flex gap-2 mb-1">
          <input type="number" className="input-field" placeholder="من كمية" value={t.min_qty} onChange={e => upd(i, 'min_qty', e.target.value)} />
          <input type="number" step="0.5" className="input-field" placeholder="خصم %" value={t.percent} onChange={e => upd(i, 'percent', e.target.value)} />
          <button className="btn-ghost" onClick={() => on(tiers.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <button className="btn-secondary text-xs" onClick={add}>+ شريحة</button>
    </div>
  )
}

// ── Rule builder: field (icon+tooltip) → operator → smart value input ─────────
const OP_LABEL = {
  eq: 'يساوي', ne: 'لا يساوي', in: 'يتضمن (أحد)', not_in: 'لا يتضمن',
  contains: 'يحتوي', gte: '≥', lte: '≤', range: 'مدى', is_true: 'نعم', is_false: 'لا',
}
const LIST_OPS = new Set(['in', 'not_in'])

function RuleBuilder({ fields, spec, on }) {
  const rules = spec?.rules || []
  const setRules = (r) => on({ ...spec, rules: r })
  const add = () => setRules([...rules, { field: fields[0]?.field || 'producer_code', op: 'in', value: [] }])
  const meta = (f) => fields.find(x => x.field === f)

  const upd = (i, patch) => {
    setRules(rules.map((r, j) => {
      if (j !== i) return r
      const next = { ...r, ...patch }
      // when field changes, keep op if valid else pick first; reset value shape
      if (patch.field) {
        const m = meta(patch.field)
        const ops = m?.ops || ['in']
        if (!ops.includes(next.op)) next.op = ops[0]
      }
      // when op changes (or field-forced), coerce value to the right shape
      const opChanged = patch.op !== undefined || patch.field !== undefined
      if (opChanged) {
        if (next.op === 'range') next.value = Array.isArray(next.value) && next.value.length === 2 ? next.value : [0, 0]
        else if (LIST_OPS.has(next.op)) next.value = Array.isArray(next.value) ? next.value : (next.value ? [next.value] : [])
        else next.value = Array.isArray(next.value) ? (next.value[0] ?? '') : (next.value ?? '')
      }
      return next
    }))
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs text-muted">مطابقة</span>
        <select className="input-field !w-auto" value={spec?.match || 'all'} onChange={e => on({ ...spec, match: e.target.value })}>
          <option value="all">كل الشروط (AND)</option><option value="any">أي شرط (OR)</option>
        </select>
        <span className="text-[11px] text-faint">
          {spec?.match === 'any' ? 'يكفي تحقّق شرط واحد.' : 'يجب تحقّق كل الشروط معًا.'}
        </span>
      </div>
      {rules.map((r, i) => {
        const m = meta(r.field)
        const fm = FIELD_META[r.field] || {}
        const ops = m?.ops || ['in', 'eq']
        const isBool = r.op === 'is_true' || r.op === 'is_false'
        return (
          <div key={i} className="flex flex-wrap gap-2 mb-1.5 items-center bg-surface-1 border border-line rounded-lg p-1.5">
            <span title={fm.help}>{fm.icon || '•'}</span>
            <select className="input-field !w-auto" value={r.field} onChange={e => upd(i, { field: e.target.value })} title={fm.help}>
              {fields.map(f => <option key={f.field} value={f.field}>{(FIELD_META[f.field]?.icon || '') + ' ' + f.label}</option>)}
            </select>
            <select className="input-field !w-auto" value={r.op} onChange={e => upd(i, { op: e.target.value })}>
              {ops.map(op => <option key={op} value={op}>{OP_LABEL[op] || op}</option>)}
            </select>
            <RuleValue rule={r} meta={m} onChange={val => upd(i, { value: val })} />
            <button className="btn-ghost ms-auto" title="حذف الشرط" onClick={() => setRules(rules.filter((_, j) => j !== i))}>×</button>
          </div>
        )
      })}
      <div className="flex items-center gap-2">
        <button className="btn-secondary text-xs" onClick={add}>+ شرط</button>
        {fm_hint(rules)}
      </div>
    </div>
  )
}
function fm_hint(rules) {
  if (rules.length) return null
  return <span className="text-[11px] text-faint">أضف شرطًا لاستهداف أصناف حسب المنتِج / المورد / التصنيف / السعر…</span>
}

function RuleValue({ rule, meta, onChange }) {
  const op = rule.op
  if (op === 'is_true' || op === 'is_false') return null
  if (op === 'range') {
    const v = Array.isArray(rule.value) ? rule.value : [0, 0]
    return (
      <>
        <input type="number" className="input-field !w-24" placeholder="من" value={v[0] ?? ''} onChange={e => onChange([Number(e.target.value), v[1] ?? 0])} />
        <input type="number" className="input-field !w-24" placeholder="إلى" value={v[1] ?? ''} onChange={e => onChange([v[0] ?? 0, Number(e.target.value)])} />
      </>
    )
  }
  // يتضمن / لا يتضمن on a code field → real-value multi picker
  if (LIST_OPS.has(op) && meta?.has_values) {
    return <ValuePicker field={rule.field} value={Array.isArray(rule.value) ? rule.value : []} onChange={onChange} />
  }
  // يتضمن / لا يتضمن on a free field → comma-separated multi text
  if (LIST_OPS.has(op)) {
    return <input className="input-field flex-1 !min-w-40" placeholder="قيم مفصولة بفواصل"
      value={Array.isArray(rule.value) ? rule.value.join(',') : (rule.value ?? '')}
      onChange={e => onChange(e.target.value.split(',').map(s => s.trim()).filter(Boolean))} />
  }
  // eq / ne / contains / gte / lte → single value
  return <input className="input-field flex-1 !min-w-40" placeholder={op === 'contains' ? 'جزء من النص' : 'قيمة'}
    value={Array.isArray(rule.value) ? (rule.value[0] ?? '') : (rule.value ?? '')}
    onChange={e => onChange(e.target.value)} />
}

// Multi-select real values (producers, suppliers, families…) from field-values API
function ValuePicker({ field, value, onChange }) {
  const [q, setQ] = useState('')
  const [opts, setOpts] = useState([])
  const [open, setOpen] = useState(false)
  const [labels, setLabels] = useState({})   // value → label (accumulated)
  const selected = Array.isArray(value) ? value : []

  useEffect(() => {
    if (!open) return
    const id = setTimeout(() => {
      offersApi.fieldValues(field, q).then(r => {
        setOpts(r.data || [])
        setLabels(prev => { const m = { ...prev }; (r.data || []).forEach(o => { m[o.value] = o.label }); return m })
      }).catch(() => setOpts([]))
    }, 250)
    return () => clearTimeout(id)
  }, [field, q, open])

  const toggle = (v) => onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v])

  return (
    <div className="relative flex-1 !min-w-48">
      <div className="flex flex-wrap gap-1 items-center input-field !h-auto min-h-[38px] cursor-text" onClick={() => setOpen(true)}>
        {selected.map(v => (
          <span key={v} className="text-[11px] bg-brand-50 text-brand-700 border border-brand-200 rounded px-1.5 py-0.5">
            {labels[v] || v}<button className="ms-1" onClick={e => { e.stopPropagation(); toggle(v) }}>×</button>
          </span>
        ))}
        <input className="flex-1 !min-w-24 bg-transparent outline-none text-sm" placeholder={selected.length ? '' : 'اختر قيمًا…'}
          value={q} onFocus={() => setOpen(true)} onChange={e => { setQ(e.target.value); setOpen(true) }} />
      </div>
      {open && (
        <div className="absolute z-20 mt-1 w-full max-h-56 overflow-y-auto bg-surface-1 border border-line rounded-lg shadow-lg">
          <div className="flex justify-between px-2 py-1 text-[10px] text-faint border-b border-line">
            <span>{opts.length} قيمة</span>
            <button onClick={() => setOpen(false)}>إغلاق ✕</button>
          </div>
          {opts.map(o => (
            <label key={o.value} className="flex items-center gap-2 px-2 py-1 text-xs hover:bg-surface-2 cursor-pointer">
              <input type="checkbox" checked={selected.includes(o.value)} onChange={() => toggle(o.value)} />
              <span className="text-content">{o.label}</span><span className="text-faint ms-auto">{o.value}</span>
            </label>
          ))}
          {!opts.length && <div className="px-2 py-2 text-[11px] text-faint">لا نتائج — اكتب للبحث.</div>}
        </div>
      )}
    </div>
  )
}

function ApplyLive({ label, onApply }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const go = async () => {
    setBusy(true); setMsg(null)
    try {
      const { data } = await onApply()
      if (data.applied) setMsg({ ok: true, t: `تم التطبيق على سوفتك ✓ (${data.written ?? (data.results ? data.results.length : '')})` })
      else if (data.enabled === false) setMsg({ ok: false, t: '⛔ الكتابة إلى سوفتك غير مُفعَّلة (المفتاح مُغلق) — تخطيط فقط.' })
      else if (data.error === 'no_softech_user') setMsg({ ok: false, t: '⛔ اربط رقم مستخدمك في سوفتك بحسابك أولاً.' })
      else setMsg({ ok: false, t: data.detail || '⛔ تعذّر التطبيق.' })
    } catch (e) {
      const d = e && e.response && e.response.data
      setMsg({ ok: false, t: (d && (d.detail || (d.requires_confirm && 'يتطلب تأكيدًا'))) || '⛔ خطأ.' })
    } finally { setBusy(false); setConfirming(false) }
  }
  return (
    <div className="mt-2">
      {!confirming
        ? <button className="btn-danger text-xs" onClick={() => setConfirming(true)}>{label}</button>
        : (
          <div className="flex items-center gap-2 flex-wrap bg-red-50 border border-red-200 rounded-lg p-2">
            <span className="text-[11px] text-red-700">كتابة فعلية إلى سوفتك — تؤثر على كل مبيعات الكاشير. متأكد؟</span>
            <button className="btn-danger text-xs" onClick={go} disabled={busy}>{busy ? '…' : 'تأكيد الكتابة'}</button>
            <button className="btn-secondary text-xs" onClick={() => setConfirming(false)}>إلغاء</button>
          </div>
        )}
      {msg && <div className={`text-[11px] mt-1 ${msg.ok ? 'text-emerald-600' : 'text-amber-600'}`}>{msg.t}</div>}
    </div>
  )
}

function PosdiscpPanel({ offerId }) {
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const run = () => { setLoading(true); offersApi.posdiscpPlan(offerId).then(r => setPlan(r.data)).finally(() => setLoading(false)) }
  return (
    <Section title="تطبيق على posdiscp (كل مبيعات الكاشير) — معاينة" icon="🏪">
      <p className="text-[11px] text-faint mb-2">
        يضبط نسبة العرض في posdiscp لأصناف المطابقة، فتُطبَّق على كل مبيعات الكاشير (وليس نقطة البيع فقط).
        هذه معاينة فقط — الكتابة إلى سوفتك مُقيَّدة بمفتاح واعتماد.
      </p>
      <button className="btn-secondary text-xs" onClick={run} disabled={loading}>{loading ? '…' : 'احسب التغييرات'}</button>
      {plan && !plan.eligible && <div className="text-xs text-amber-600 mt-2">{plan.reason}</div>}
      {plan && plan.eligible && (
        <div className="mt-2 text-xs">
          <div className="font-bold text-content">سيتغيّر posdiscp لـ {plan.summary.to_change} صنف (نسبة {plan.target_percent}%)، {plan.summary.unchanged} دون تغيير.</div>
          <div className="text-faint mt-1 line-clamp-3">
            {(plan.changes || []).slice(0, 15).map(c => `${c.name}: ${c.current_posdiscp}%→${c.new_posdiscp}%`).join(' · ') || '—'}
          </div>
          {plan.summary.to_change > 0 &&
            <ApplyLive label={`تطبيق فعلي على ${plan.summary.to_change} صنف`}
                       onApply={() => offersApi.posdiscpApply(offerId, true)} />}
        </div>
      )}
    </Section>
  )
}

const PROMO_TYPE_LABEL = {
  1: 'صنف بونص على صنف (هدية)', 2: 'خصم خاص على صنف (نسبة)', 3: 'بونص على إجمالي المبلغ',
}

function PromoPanel({ offerId }) {
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const run = () => { setLoading(true); offersApi.promoPlan(offerId).then(r => setPlan(r.data)).finally(() => setLoading(false)) }
  return (
    <Section title="كتابة عرض سوفتك الأصلي (specialoffers) — معاينة" icon="🎁">
      <p className="text-[11px] text-faint mb-2">
        يُكتب العرض في جدول عروض سوفتك الأصلي (برقم متسلسل)، فيُطبَّق تلقائيًا على الكاشير.
        معاينة فقط — الكتابة مُقيَّدة بمفتاح واعتماد.
      </p>
      <button className="btn-secondary text-xs" onClick={run} disabled={loading}>{loading ? '…' : 'احسب صف العرض'}</button>
      {plan && !plan.eligible && <div className="text-xs text-amber-600 mt-2">{plan.reason}</div>}
      {plan && plan.eligible && (
        <div className="mt-2 text-xs space-y-1">
          <div className="font-bold text-content">نوع سوفتك {plan.softech_type}: {PROMO_TYPE_LABEL[plan.softech_type]}</div>
          {(plan.rows || []).map((r, i) => (
            <div key={i} className="bg-surface-2 border border-line rounded px-2 py-1 text-muted">
              صنف العرض: <b>{r.specialoffer_itemcode}</b>
              {plan.softech_type === 2 && <> · نسبة الخصم: <b>{r.itemqty_from}%</b></>}
              {plan.softech_type === 1 && <> · اشترِ: <b>{r.itemqty_from}</b> · هدية: <b>{r.bonus_itemcode}</b> ×{r.bonus_itemqty}</>}
              {plan.softech_type === 3 && <> · المبلغ من <b>{r.itemqty_from}</b> إلى <b>{r.itemqty_to}</b> · هدية: <b>{r.bonus_itemcode}</b></>}
            </div>
          ))}
          {(plan.extra_items || []).length > 0 && (
            <div className="text-faint">+ {plan.extra_items.length} صنف تحفيز إضافي → specialoffersitems</div>)}
          {(plan.notes || []).map((n, i) => <div key={i} className="text-[10px] text-amber-600">⚠ {n}</div>)}
          <ApplyLive label="كتابة العرض في سوفتك (specialoffers)"
                     onApply={() => offersApi.promoApply(offerId, true)} />
        </div>
      )}
    </Section>
  )
}

function ItemPick({ label, value, onChange, single }) {
  const [items, setItems] = useState([])   // {id, code, name} chips for display
  const add = (it) => {
    const id = it.id || it.item_id
    if (!id || value.includes(id)) return
    setItems(prev => [...prev, { id, code: it.softech_id || it.softech_itemcode, name: it.name || it.item_name }])
    onChange(single ? [id] : [...value, id])
    if (single) return
  }
  const rm = (id) => { setItems(prev => prev.filter(x => x.id !== id)); onChange(value.filter(x => x !== id)) }
  const shown = items.filter(x => value.includes(x.id))
  return (
    <div>
      <label className="label">{label}</label>
      <ItemSearchWidget onSelect={add} placeholder="ابحث لإضافة صنف…" />
      <div className="flex flex-wrap gap-1 mt-1">
        {shown.map(x => (
          <span key={x.id} className="text-[11px] bg-surface-2 border border-line rounded px-1.5 py-0.5">
            {x.name || x.code || x.id}<button className="ms-1 text-faint" onClick={() => rm(x.id)}>×</button>
          </span>
        ))}
        {!shown.length && value.length > 0 && <span className="text-[11px] text-faint">{value.length} مُحدَّد</span>}
      </div>
    </div>
  )
}
