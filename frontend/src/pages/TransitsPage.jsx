/**
 * TransitsPage.jsx  —  التحويلات قيد النقل (route /transits)
 *
 * The fulfillment half of the inter-branch transfer pipeline, split out of the
 * transfers page into its own route so it's deep-linkable and can grow
 * (picking, stocking, batches, receiving) without bloating the requests page.
 *
 * Deep-link: /transits?id=<transitId> opens that shipment's detail panel
 * directly — used by the "قيد النقل ←" links on a transfer request.
 */
import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import TransferModuleTabs from '../components/TransferModuleTabs'
import InTransitTab from '../components/InTransitTab'

export default function TransitsPage() {
  const [params, setParams] = useSearchParams()
  const [openId, setOpenId] = useState(() => {
    const id = params.get('id')
    return id ? Number(id) : null
  })

  // React to the ?id= param changing (e.g. following another link)
  useEffect(() => {
    const id = params.get('id')
    if (id) setOpenId(Number(id))
  }, [params])

  // Once the detail has been opened, drop the param so a refresh/back is clean
  function clearParam() {
    if (params.get('id')) {
      const next = new URLSearchParams(params)
      next.delete('id')
      setParams(next, { replace: true })
    }
  }

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      <div className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <TransferModuleTabs active="transit" />
      </div>
      <InTransitTab openId={openId} onOpenConsumed={clearParam} />
    </div>
  )
}
