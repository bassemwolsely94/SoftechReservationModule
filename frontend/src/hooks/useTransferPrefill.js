/**
 * useTransferPrefill — POS «تحويل من …» opens /transfers/new?item=<softech_id>&from=<branch pk>
 * in a new tab. This reads those two params once: `from` → the supplying branch, `item` → the
 * item added as the first line (resolved through the normal /items/ search by code).
 */
import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import api from '../api/client'

export default function useTransferPrefill({ setSupplying, addItem }) {
  const [params] = useSearchParams()
  const done = useRef(false)
  useEffect(() => {
    if (done.current) return
    const from = params.get('from'), code = params.get('item')
    if (!from && !code) return
    done.current = true
    if (from) setSupplying(String(from))
    if (code) {
      api.get('/items/', { params: { search: code, page_size: 10 } })
        .then(r => {
          const rows = r.data.results || r.data
          const hit = rows.find(x => String(x.softech_id) === String(code))
          if (hit) addItem(hit)
        })
        .catch(() => {})
    }
  }, [params, setSupplying, addItem])
}
