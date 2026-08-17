/**
 * NotificationPreferencesModal.jsx — the per-user "Preferences Center".
 * Master on/off, alarm sound, desktop push, and personal per-category mute.
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notificationsApi } from '../api/client'
import { setMuted, setDesktopPush, pushSupported } from '../hooks/useNotificationSocket'
import useNotificationStore from '../store/notificationStore'

function Toggle({ checked, onChange, label, hint, disabled }) {
  return (
    <button type="button" disabled={disabled} onClick={onChange}
      className={`w-full flex items-center justify-between py-2.5 ${disabled ? 'opacity-50' : ''}`}>
      <div className="text-right">
        <div className="text-sm font-medium text-gray-800">{label}</div>
        {hint && <div className="text-[11px] text-gray-400">{hint}</div>}
      </div>
      <span className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0
        ${checked ? 'bg-brand-600' : 'bg-gray-300'}`}>
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform
          ${checked ? '-translate-x-0.5' : '-translate-x-4'}`} />
      </span>
    </button>
  )
}

export default function NotificationPreferencesModal({ onClose }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['notif-prefs'],
    queryFn: () => notificationsApi.getPreferences().then(r => r.data),
  })
  const [local, setLocal] = useState(null)

  useEffect(() => {
    if (data) setLocal({
      enable_notifications: data.enable_notifications,
      enable_sound:         data.enable_sound,
      enable_browser_push:  data.enable_browser_push,
      muted: new Set(data.muted_notification_categories || []),
    })
  }, [data])

  const notifiers = data?.notifiers || []
  const save = useMutation({
    mutationFn: (payload) => notificationsApi.updatePreferences(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notif-prefs'] })
      useNotificationStore.getState().refresh()   // re-pull visible set + counts
      onClose()
    },
  })

  if (!local) {
    return (
      <Shell onClose={onClose}>
        <div className="py-10 text-center text-gray-400 text-sm">جارٍ التحميل…</div>
      </Shell>
    )
  }

  const set = (k, v) => setLocal(s => ({ ...s, [k]: v }))
  const toggleCat = (c) => setLocal(s => {
    const m = new Set(s.muted); m.has(c) ? m.delete(c) : m.add(c); return { ...s, muted: m }
  })

  async function handleSave() {
    // Sound also drives the per-device quick mute (bell toggle) so they agree.
    setMuted(!local.enable_sound)
    // Desktop push: request permission if enabling.
    let pushOk = local.enable_browser_push
    if (local.enable_browser_push && pushSupported() && Notification.permission !== 'granted') {
      try { await Notification.requestPermission() } catch { /* ignore */ }
      pushOk = Notification.permission === 'granted'
    }
    setDesktopPush(local.enable_browser_push && pushOk)
    save.mutate({
      enable_notifications: local.enable_notifications,
      enable_sound:         local.enable_sound,
      enable_browser_push:  local.enable_browser_push && (!pushSupported() || pushOk),
      muted_notification_categories: [...local.muted],
    })
  }

  return (
    <Shell onClose={onClose}>
      <div className="divide-y divide-gray-100">
        <Toggle label="تفعيل الإشعارات" hint="إيقافها يمنع إنشاء أي إشعار لك"
          checked={local.enable_notifications} onChange={() => set('enable_notifications', !local.enable_notifications)} />
        <Toggle label="صوت التنبيه" hint="نغمة عند وصول تنبيه عاجل أو هام"
          checked={local.enable_sound} onChange={() => set('enable_sound', !local.enable_sound)} />
        <Toggle label="تنبيهات سطح المكتب" hint={pushSupported() ? 'إشعار من المتصفح عندما تكون النافذة غير نشطة' : 'غير مدعوم في هذا المتصفح'}
          disabled={!pushSupported()}
          checked={local.enable_browser_push} onChange={() => set('enable_browser_push', !local.enable_browser_push)} />
      </div>

      <div className="mt-4">
        <div className="text-xs font-semibold text-gray-500 mb-1">كتم فئات معيّنة (لك وحدك)</div>
        <div className="text-[11px] text-gray-400 mb-2">الفئات المكتومة لا تظهر لك ولا تُصدر تنبيهاً (تبقى مسجّلة).</div>
        <div className="grid grid-cols-2 gap-1.5">
          {notifiers.map(n => {
            const muted = local.muted.has(n.value)
            return (
              <button key={n.value} type="button" onClick={() => toggleCat(n.value)}
                className={`flex items-center justify-between text-xs rounded-lg border px-2.5 py-1.5 transition-colors
                  ${muted ? 'bg-gray-100 text-gray-400 border-gray-200 line-through' : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'}`}>
                <span className="truncate">{n.label}</span>
                <span>{muted ? '🔕' : '🔔'}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex justify-end gap-2 mt-5">
        <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded-xl hover:bg-gray-50">إلغاء</button>
        <button onClick={handleSave} disabled={save.isPending}
          className="px-4 py-2 text-sm bg-brand-600 text-white rounded-xl hover:bg-brand-700 disabled:opacity-50 font-medium">
          {save.isPending ? 'جارٍ الحفظ…' : 'حفظ'}
        </button>
      </div>
    </Shell>
  )
}

function Shell({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-black text-gray-900 text-base">إعدادات الإشعارات</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}
