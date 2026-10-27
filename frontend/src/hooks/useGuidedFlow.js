import { useEffect, useMemo, useRef, useState } from 'react'

/*
 * useGuidedFlow — shared navigation for the POS guided (wizard) mode, used by both the
 * desktop GuidedMode overlay and the mobile guided sheet. Stages are grouped views over the
 * same reactive `workflow` engine (usePosOrder), so guided mode never forks state. The flow
 * AUTO-ADVANCES: when the active stage transitions into "done", it jumps to the next
 * incomplete stage — but a stage that was already done when you arrive (or that you navigate
 * back to) does NOT yank you forward, so manual review stays possible.
 */

export const STAGE_TAB = { customer: 'header', items: 'items', claim: 'contract', payment: 'payment' }

export default function useGuidedFlow(P) {
  const wf = P.workflow

  const stages = useMemo(() => {
    const s = [
      { key: 'customer', title: 'العميل والقناة', icon: '🧭', stepKeys: ['channel', 'seller', 'customer'] },
      { key: 'items', title: 'الأصناف والكميات', icon: '💊', stepKeys: ['items'] },
    ]
    if (P.isClaim) s.push({ key: 'claim', title: 'بيانات التعاقد', icon: '📋', stepKeys: ['claim'] })
    s.push({ key: 'payment', title: 'السداد والمراجعة', icon: '💵', stepKeys: ['payment'] })
    return s
  }, [P.isClaim])

  const stStatus = (stg) => {
    const sts = stg.stepKeys.map(k => wf.steps.find(x => x.key === k)?.status).filter(Boolean)
    if (sts.some(x => x === 'blocked')) return 'blocked'
    if (sts.length && sts.every(x => x === 'done' || x === 'skip')) return 'done'
    return 'active'
  }

  const firstIncomplete = Math.max(0, stages.findIndex(s => stStatus(s) !== 'done'))
  const [idx, setRaw] = useState(firstIncomplete)
  const clamp = i => Math.min(Math.max(0, i), stages.length - 1)
  const safeIdx = clamp(idx)                 // stages can shrink (claim drops) → never index past the end
  const stage = stages[safeIdx]
  const isLast = safeIdx === stages.length - 1
  const curStatus = stStatus(stage)

  // auto-advance on the false→true completion edge of the *active* stage only
  const prevRef = useRef({})
  useEffect(() => {
    const key = stage.key
    const prev = prevRef.current[key]
    prevRef.current[key] = curStatus
    if (prev && prev !== 'done' && curStatus === 'done' && !isLast) {
      const ni = stages.findIndex((s, i) => i > safeIdx && stStatus(s) !== 'done')
      setRaw(ni !== -1 ? ni : clamp(safeIdx + 1))
    }
  }, [stage.key, curStatus])  // eslint-disable-line

  return {
    stages, safeIdx, stage, isLast, curStatus, stStatus,
    setIdx: i => setRaw(clamp(i)),
    goNext: () => setRaw(clamp(safeIdx + 1)),
    goPrev: () => setRaw(clamp(safeIdx - 1)),
  }
}
