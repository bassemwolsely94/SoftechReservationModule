/**
 * WhatsAppShareButton.jsx
 *
 * Calls the backend share-whatsapp endpoint to get a formatted message,
 * then opens WhatsApp Web in a new tab.
 *
 * Props:
 *   type     {string}  — "reservation" | "transfer"
 *   docId    {number}
 *   size     {string}  — "sm" | "md" (default "md")
 */
import { useState } from 'react'
import { reservationsApi, transfersApi } from '../api/client'

export default function WhatsAppShareButton({ type, docId, size = 'md' }) {
  const [loading, setLoading] = useState(false)

  const handleShare = async () => {
    setLoading(true)
    try {
      const fetcher = type === 'reservation'
        ? () => reservationsApi.shareWhatsapp(docId)
        : () => transfersApi.shareWhatsapp(docId)

      const { data } = await fetcher()
      const text     = encodeURIComponent(data.message_text || '')
      window.open(`https://wa.me/?text=${text}`, '_blank', 'noopener,noreferrer')
    } catch {
      // silently ignore — user can retry
    } finally {
      setLoading(false)
    }
  }

  const base  = 'flex items-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-50'
  const small = 'text-xs px-3 py-1.5 border border-green-400 text-green-700 hover:bg-green-50'
  const med   = 'text-sm px-4 py-2 border border-green-400 text-green-700 hover:bg-green-50'

  return (
    <button
      type="button"
      onClick={handleShare}
      disabled={loading}
      className={`${base} ${size === 'sm' ? small : med}`}
    >
      {loading
        ? <span className="w-3.5 h-3.5 border-2 border-green-400 border-t-green-700 rounded-full animate-spin" />
        : (
          <svg className={size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'} viewBox="0 0 24 24" fill="currentColor">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
          </svg>
        )
      }
      {size !== 'sm' && 'مشاركة عبر واتساب'}
    </button>
  )
}
