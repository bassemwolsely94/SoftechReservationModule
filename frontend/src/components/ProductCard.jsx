/**
 * ProductCard 2.0 — visual POS product tile (owner "Visual POS" brainstorm §3,§5). Image + name +
 * price + live stock + semantic badges (cold-chain / batch-required / offer) + backend-owned safety
 * flags, and a CONTEXTUAL action bar that surfaces only the relevant action (§5): Add is prominent
 * when in stock, Find-Stock when local=0, etc. Built entirely from the POS Design System so it reads
 * the same as every other surface. Backend owns all decisions (rules 4/7); this only renders them.
 *
 * props: { item, onSelect, onFindStock, onTransfer, onAlternatives, onHistory, onBatches, compact }
 *   item: { id, softech_id, name, pack_price, qty_at_branch?, image?, tags?,
 *           safety_flags?: [{code,severity,label_ar}], cold_chain?, batch_required?, has_offer? }
 */
import { StockBadge, ColdChainBadge, BatchBadge, OfferBadge, SafetyBadge, ActionTile, Icon } from '../pos/design'

export default function ProductCard({ item, onSelect, onFindStock, onTransfer, onAlternatives, onHistory, onBatches, compact = false }) {
  const flags = item.safety_flags || []
  const blocking = flags.some((f) => f.severity === 'block')
  const stock = typeof item.qty_at_branch === 'number' ? item.qty_at_branch : null
  const inStock = stock == null || stock > 0

  // Contextual actions (§5): render only what's relevant, promote the primary one.
  const actions = []
  if (!blocking) actions.push({ icon: 'plus', label: 'إضافة', onClick: () => onSelect?.(item), prominent: inStock })
  if (stock === 0 && onFindStock) actions.push({ icon: 'store', label: 'بحث برصيد', onClick: () => onFindStock(item), prominent: true })
  if (stock === 0 && onTransfer) actions.push({ icon: 'transfer', label: 'تحويل', onClick: () => onTransfer(item) })
  if (onAlternatives) actions.push({ icon: 'repeat', label: 'بديل', onClick: () => onAlternatives(item) })
  if (item.batch_required && onBatches) actions.push({ icon: 'package', label: 'باتش', onClick: () => onBatches(item) })
  if (onHistory) actions.push({ icon: 'clock', label: 'سجل', onClick: () => onHistory(item) })

  return (
    <div className={`group text-right w-full flex flex-col gap-1 rounded-xl border p-2 transition-all bg-surface hover:shadow-md
        ${blocking ? 'border-red-200' : 'border-line hover:border-line-strong'}`}>
      <button type="button" onClick={() => onSelect?.(item)} disabled={blocking}
              title={blocking ? 'هذا الصنف عليه قيد بيع — راجع التنبيه' : item.name}
              className="text-right w-full flex items-start gap-2 disabled:cursor-not-allowed">
        <div className="w-10 h-10 shrink-0 rounded-lg bg-surface-2 border border-line-soft overflow-hidden flex items-center justify-center">
          {item.image
            ? <img src={item.image} alt="" className="w-full h-full object-cover" loading="lazy" />
            : <span className="text-base">💊</span>}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold text-content leading-tight line-clamp-2">{item.name}</div>
          <div className="text-[10px] text-faint">{item.softech_id}</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="text-[11px] tabnum font-bold text-brand-600">{Number(item.pack_price || 0).toFixed(2)}</span>
            <StockBadge qty={stock} size="xs" />
          </div>
        </div>
      </button>

      {/* semantic + safety badges */}
      {(item.cold_chain || item.batch_required || item.has_offer || flags.length > 0 || item.tags?.length > 0) && (
        <div className="flex flex-wrap gap-1">
          {item.has_offer && <OfferBadge />}
          {item.batch_required && <BatchBadge />}
          {item.cold_chain && <ColdChainBadge />}
          {flags.slice(0, 3).map((f) => <SafetyBadge key={f.code} flag={f} />)}
          {(item.tags || []).slice(0, 2).map((t) => (
            <span key={t.id || t.slug} className="text-[9px] border border-line rounded px-1 text-muted"
                  style={t.color ? { borderColor: t.color, color: t.color } : undefined}>
              {t.name_ar || t.name}
            </span>
          ))}
        </div>
      )}

      {/* contextual action bar */}
      {!compact && actions.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-0.5 border-t border-line-soft">
          {actions.map((a, i) => <ActionTile key={i} {...a} />)}
        </div>
      )}

      {/* compact tiles stay dense, but an OOS item still surfaces the network-stock lookup (§37) */}
      {compact && stock === 0 && onFindStock && (
        <button type="button" onClick={(e) => { e.stopPropagation(); onFindStock(item) }}
                title="بحث عن رصيد بالفروع الأخرى"
                className="mt-0.5 self-start inline-flex items-center gap-1 text-[10px] text-sky-700 hover:underline">
          <Icon name="store" size={11} /> بحث برصيد
        </button>
      )}
    </div>
  )
}
