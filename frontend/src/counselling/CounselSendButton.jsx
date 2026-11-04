/**
 * «إرسال إرشادات الاستخدام» — opens SendCardDrawer for the given customer + items. Hidden unless
 * the content or sending switch is on, and only when there is a customer and at least one item.
 */
import { useState } from 'react'
import SendCardDrawer from './SendCardDrawer'
import useCounsellingStatus from './useCounsellingStatus'

export default function CounselSendButton({ customerId, itemIds, branchId, source = 'pos', className = '', label = '📘 إرشادات' }) {
  const { content, cards } = useCounsellingStatus()
  const [open, setOpen] = useState(false)
  const ids = (itemIds || []).filter(Boolean)
  if (!(content || cards) || !customerId || !ids.length) return null
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title="إرسال إرشادات الاستخدام للعميل على واتساب"
              data-tour="counsel-send-open"
              className={className || 'h-8 px-2 rounded border bg-white hover:bg-gray-50'}>{label}</button>
      {open && <SendCardDrawer customerId={customerId} itemIds={ids} branchId={branchId} source={source}
                               onClose={() => setOpen(false)} />}
    </>
  )
}
