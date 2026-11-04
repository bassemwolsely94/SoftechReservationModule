/**
 * useFeatures — server switches for features that ship dark (from /api/auth/me/ `features`).
 * Missing (older server / not logged in) ⇒ everything off.
 */
import useAuthStore from '../store/authStore'

export default function useFeatures() {
  const f = useAuthStore(s => s.user?.features) || {}
  return { cameraScan: !!f.camera_scan, dailyCount: !!f.daily_count }
}
