/**
 * Global drug-assistant side drawer — opens on window 'drug-assistant:open' {detail: {id}}
 * (Ctrl+K: Shift+Enter on an item). Renders nothing while the assistant switch is off.
 */
import { useEffect, useState } from 'react'
import { Icon } from '../pos/design'
import DrugAssistantBody from './DrugAssistantBody'
import useCounsellingStatus from './useCounsellingStatus'

export default function DrugAssistantDrawer() {
  const { assistant } = useCounsellingStatus()
  const [itemId, setItemId] = useState(null)
  useEffect(() => {
    const open = e => setItemId(e.detail?.id || null)
    window.addEventListener('drug-assistant:open', open)
    return () => window.removeEventListener('drug-assistant:open', open)
  }, [])
  if (!assistant || !itemId) return null
  return (
    <div dir="rtl" className="fixed top-14 bottom-0 left-0 z-[60] w-[26rem] max-w-full bg-white border-e shadow-2xl flex flex-col"
         onKeyDown={e => { if (e.key === 'Escape') setItemId(null) }}>
      <div className="flex items-center gap-2 p-3 border-b bg-gray-50">
        <div className="font-semibold text-sm flex-1">معلومات الصنف</div>
        <button type="button" autoFocus onClick={() => setItemId(null)} className="p-1.5 rounded hover:bg-gray-200" title="إغلاق (Esc)">
          <Icon name="x" size={16} />
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-3"><DrugAssistantBody itemId={itemId} /></div>
    </div>
  )
}
