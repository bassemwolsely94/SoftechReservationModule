/**
 * PosResultRow — Layout A: one line per search result. thumb · name + strength chip + form ·
 * badges · «هنا» pill (bold) · other-branch pills (max 4, +N) · price · next action when stock here is 0.
 * Display only: the stock/next-action decision comes from the server (rule 7).
 */
import { Badge, BranchStockPill, ActionTile, Icon } from '../design'
import useBranchNames from './useBranchNames'

export const MAX_OTHER_PILLS = 4

const money = (v) => { const n = parseFloat(v); return n ? n.toFixed(2) : null }

export function Thumb({ src, size = 38 }) {
  return src
    ? <img src={src} alt="" loading="lazy" style={{ width: size, height: size }} className="rounded object-cover bg-gray-100 shrink-0" />
    : <span style={{ width: size, height: size }} className="rounded bg-gray-100 text-gray-300 flex items-center justify-center shrink-0"><Icon name="package" size={Math.round(size * 0.45)} /></span>
}

/** cold / batch badges (the offer flag is not in the search row). */
export function ItemBadges({ item }) {
  return (
    <>
      {item.requires_fridge && <Badge meaning="cold" size="xs" />}
      {item.batch_required && <Badge meaning="batch" size="xs" />}
    </>
  )
}

export default function PosResultRow({ item, hereBranchId, selected, onAdd, onAction, onPreview, onAlternatives, index }) {
  const nameOf = useBranchNames()
  const here = item.qty_at_branch
  const others = (item.branch_stock || []).filter(b => String(b.branch_id) !== String(hereBranchId))
  const shown = others.slice(0, MAX_OTHER_PILLS)
  const more = others.length - shown.length
  const price = money(item.pack_price)
  const act = item.next_action || { kind: 'add' }
  const form = item.dosage_form || item.form || ''

  return (
    <div role="option" aria-selected={!!selected} data-idx={index}
         onMouseDown={e => { e.preventDefault(); onAdd(item) }}
         className={`flex items-center gap-2 px-2 py-1.5 border-b border-gray-50 last:border-0 cursor-pointer ${selected ? 'bg-brand-50 ring-1 ring-inset ring-brand-200' : 'hover:bg-gray-50'}`}>
      <Thumb src={item.thumb} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-semibold text-sm text-gray-900 leading-snug">{item.name}</span>
          {item.strength && <span className="text-[11px] font-bold px-1.5 rounded bg-[#022871] text-white">{item.strength}</span>}
          {form && <span className="text-[10px] text-gray-400">{form}</span>}
          <ItemBadges item={item} />
        </div>
        <div className="flex items-center gap-1 flex-wrap mt-0.5">
          {here != null && <BranchStockPill name="هنا" qty={here} className="font-bold" />}
          {shown.map(b => (
            <BranchStockPill key={b.branch_id} name={nameOf(b.branch_id) || `#${b.branch_id}`} qty={b.qty} />
          ))}
          {more > 0 && <span className="text-[10px] text-gray-400">+{more}</span>}
        </div>
        {act.kind !== 'add' && (
          <div className="flex items-center gap-1 mt-1" onMouseDown={e => { e.preventDefault(); e.stopPropagation() }}>
            {act.kind === 'transfer' && (
              <ActionTile prominent icon="transfer"
                label={`تحويل من ${nameOf(act.from_branch_id) || 'فرع آخر'}`}
                onClick={e => { e.stopPropagation(); onAction?.('transfer', item, { from_branch_id: act.from_branch_id }) }} />
            )}
            {act.kind === 'demand' && (
              <ActionTile prominent icon="plus" label="تسجيل طلب"
                title="لا رصيد في الشبكة — سجّل طلبًا مفقودًا"
                onClick={e => { e.stopPropagation(); onAction?.('demand', item) }} />
            )}
            <ActionTile icon="bookmark" label="حجز"
              onClick={e => { e.stopPropagation(); onAction?.('reserve', item) }} />
          </div>
        )}
      </div>
      <div className="flex flex-col items-end gap-1 shrink-0">
        {price && <span className="text-xs font-bold text-emerald-700 tabnum">{price}</span>}
        <button type="button" title="معاينة (→)" onMouseDown={e => { e.preventDefault(); e.stopPropagation(); onPreview?.(item) }}
                className="text-gray-400 hover:text-brand-600"><Icon name="info" size={14} /></button>
        {onAlternatives && (
          <button type="button" title="بدائل مؤكدة (F7)" aria-label="بدائل مؤكدة"
                  onMouseDown={e => { e.preventDefault(); e.stopPropagation(); onAlternatives(item) }}
                  className="text-gray-400 hover:text-brand-600"><Icon name="repeat" size={14} /></button>
        )}
      </div>
    </div>
  )
}
