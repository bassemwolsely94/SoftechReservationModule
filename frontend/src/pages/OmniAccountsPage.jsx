/**
 * OmniAccountsPage.jsx — CEP Phase 1 (doc 15)
 *
 * Channel accounts health dashboard: every company communication endpoint
 * (WhatsApp numbers, PBX, future social pages) with live status, heartbeat,
 * per-number load, and per-account credential management.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { omniApi } from '../api/client'

const CHANNEL_META = {
  whatsapp:  { icon: '💬', label: 'واتساب' },
  voice:     { icon: '☎️', label: 'مكالمات' },
  messenger: { icon: '🟦', label: 'ماسنجر' },
  instagram: { icon: '📸', label: 'إنستجرام' },
  telegram:  { icon: '✈️', label: 'تيليجرام' },
  tiktok:    { icon: '🎵', label: 'تيك توك' },
  sms:       { icon: '✉️', label: 'SMS' },
  email:     { icon: '📧', label: 'بريد' },
}

const STATUS_META = {
  connected:    { label: 'متصل',      cls: 'bg-green-100 text-green-700', dot: 'bg-green-500' },
  disconnected: { label: 'منقطع',     cls: 'bg-red-100 text-red-700',     dot: 'bg-red-500' },
  degraded:     { label: 'متدهور',    cls: 'bg-yellow-100 text-yellow-700', dot: 'bg-yellow-500' },
  pending_qr:   { label: 'بانتظار QR', cls: 'bg-gray-100 text-gray-600',   dot: 'bg-gray-400' },
}

const PROVIDER_LABEL = {
  meta_cloud: 'Meta Cloud API', d360: '360dialog', twilio: 'Twilio',
  android_bridge: 'جسر أندرويد', ami: 'Issabel AMI', meta_graph: 'Meta Graph',
  telegram_bot: 'Telegram Bot', other: 'أخرى',
}

const heartbeatAgo = (dt) => {
  if (!dt) return 'لم يُسجَّل'
  const mins = Math.floor((Date.now() - new Date(dt)) / 60_000)
  if (mins < 1) return 'الآن'
  if (mins < 60) return `منذ ${mins} د`
  if (mins < 1440) return `منذ ${Math.floor(mins / 60)} س`
  return `منذ ${Math.floor(mins / 1440)} يوم`
}

// ── Account Card ──────────────────────────────────────────────────────────────
function AccountCard({ acc, onEdit, onProbe, probing }) {
  const ch = CHANNEL_META[acc.channel] || { icon: '💠', label: acc.channel }
  const st = STATUS_META[acc.status] || {}
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 flex flex-col gap-3" dir="rtl">
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="font-bold text-gray-800 truncate">
            <span className="ml-1">{ch.icon}</span>{acc.name}
            {acc.is_default && (
              <span className="mr-2 text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded-full">افتراضي</span>
            )}
          </p>
          <p className="text-xs text-gray-500 mt-0.5" dir="ltr">{acc.phone_or_handle}</p>
        </div>
        <span className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-full shrink-0 ${st.cls || ''}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${st.dot || ''}`} />
          {st.label || acc.status}
        </span>
      </div>

      <div className="grid grid-cols-4 gap-1 text-center">
        {[
          ['محادثات', acc.stats?.threads],
          ['اليوم', acc.stats?.messages_today],
          ['وارد اليوم', acc.stats?.inbound_today],
          ['غير مقروء', acc.stats?.unread],
        ].map(([label, val]) => (
          <div key={label} className="bg-gray-50 rounded p-1.5">
            <p className="font-bold text-gray-800 text-sm">{val ?? 0}</p>
            <p className="text-[10px] text-gray-400">{label}</p>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{PROVIDER_LABEL[acc.provider] || acc.provider}</span>
        <span>نبضة: {heartbeatAgo(acc.last_heartbeat_at)}</span>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className={acc.has_credentials ? 'text-green-600' : 'text-gray-400'}>
          {acc.has_credentials ? '🔐 اعتماد خاص' : acc.channel === 'whatsapp' ? '🔓 اعتماد env الافتراضي' : '—'}
        </span>
        <span className="text-gray-400">{acc.branch_name || 'كل الفروع'}</span>
      </div>

      <div className="flex gap-2 pt-1 border-t border-gray-100">
        <button onClick={() => onEdit(acc)}
                className="flex-1 text-xs text-gray-600 hover:text-indigo-600 py-1">
          ✏️ تعديل
        </button>
        {acc.channel === 'whatsapp' && (
          <button onClick={() => onProbe(acc)} disabled={probing === acc.id}
                  className="flex-1 text-xs text-gray-600 hover:text-indigo-600 py-1 disabled:opacity-50">
            {probing === acc.id ? '⏳ فحص...' : '🩺 فحص الاتصال'}
          </button>
        )}
      </div>
    </div>
  )
}

// ── Create / Edit modal ───────────────────────────────────────────────────────
function AccountModal({ acc, onClose }) {
  const isEdit = Boolean(acc?.id)
  const [form, setForm] = useState({
    channel: acc?.channel || 'whatsapp',
    name: acc?.name || '',
    phone_or_handle: acc?.phone_or_handle || '',
    provider: acc?.provider || 'meta_cloud',
    provider_ref: acc?.provider_ref || '',
    department: acc?.department || '',
    is_default: acc?.is_default || false,
    is_active: acc?.is_active ?? true,
    token: '',
  })
  const qc = useQueryClient()

  const save = useMutation({
    mutationFn: () => {
      const { token, ...fields } = form
      const data = { ...fields }
      if (token.trim()) {
        data.credentials_input = { token: token.trim(), phone_number_id: form.provider_ref }
      }
      return isEdit ? omniApi.updateAccount(acc.id, data) : omniApi.createAccount(data)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['omni-accounts'] })
      onClose()
    },
  })

  const set = (k) => (e) =>
    setForm(f => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" dir="rtl"
         onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 space-y-3"
           onClick={e => e.stopPropagation()}>
        <h2 className="font-bold text-gray-800">{isEdit ? 'تعديل حساب' : 'حساب قناة جديد'}</h2>

        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-gray-500">
            القناة
            <select value={form.channel} onChange={set('channel')} disabled={isEdit}
                    className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm mt-1 disabled:bg-gray-50">
              {Object.entries(CHANNEL_META).map(([k, v]) => (
                <option key={k} value={k}>{v.icon} {v.label}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-500">
            المزوّد
            <select value={form.provider} onChange={set('provider')}
                    className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm mt-1">
              {Object.entries(PROVIDER_LABEL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </label>
        </div>

        <label className="block text-xs text-gray-500">
          اسم الحساب (مثال: واتساب فرع المعادي 1)
          <input value={form.name} onChange={set('name')}
                 className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm mt-1" />
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-gray-500">
            الرقم / المعرف
            <input value={form.phone_or_handle} onChange={set('phone_or_handle')} dir="ltr"
                   placeholder="201001234567"
                   className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm mt-1" />
          </label>
          <label className="text-xs text-gray-500">
            Phone Number ID (Meta)
            <input value={form.provider_ref} onChange={set('provider_ref')} dir="ltr"
                   placeholder="1234567890"
                   className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm mt-1" />
          </label>
        </div>

        <label className="block text-xs text-gray-500">
          Access Token {isEdit && acc.has_credentials ? '(اتركه فارغاً للإبقاء على الحالي)' : '(اختياري — env كبديل)'}
          <input value={form.token} onChange={set('token')} dir="ltr" type="password"
                 placeholder="EAAG..."
                 className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm mt-1" />
        </label>

        <label className="block text-xs text-gray-500">
          القسم
          <input value={form.department} onChange={set('department')}
                 placeholder="مركز الاتصالات / التوصيل / التأمين"
                 className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm mt-1" />
        </label>

        <div className="flex items-center gap-4 text-sm text-gray-600">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={form.is_default} onChange={set('is_default')} />
            الحساب الافتراضي للإرسال
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={form.is_active} onChange={set('is_active')} />
            نشط
          </label>
        </div>

        {save.isError && (
          <p className="text-red-500 text-xs">
            {JSON.stringify(save.error?.response?.data) || 'فشل الحفظ'}
          </p>
        )}

        <div className="flex gap-2 pt-2">
          <button onClick={() => save.mutate()}
                  disabled={!form.name.trim() || !form.phone_or_handle.trim() || save.isPending}
                  className="flex-1 bg-indigo-600 text-white rounded px-3 py-2 text-sm disabled:opacity-50">
            {save.isPending ? 'جاري الحفظ...' : 'حفظ'}
          </button>
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500">إلغاء</button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function OmniAccountsPage() {
  const [modal, setModal] = useState(null)   // null | {} (new) | account (edit)
  const [probing, setProbing] = useState(null)
  const [probeResult, setProbeResult] = useState(null)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['omni-accounts'],
    queryFn: () => omniApi.accounts().then(r => r.data),
    refetchInterval: 30_000,
  })

  const probe = async (acc) => {
    setProbing(acc.id)
    setProbeResult(null)
    try {
      const r = await omniApi.accountHealth(acc.id)
      setProbeResult({ acc: acc.name, ...r.data })
      qc.invalidateQueries({ queryKey: ['omni-accounts'] })
    } catch (e) {
      setProbeResult({ acc: acc.name, probe: { ok: false, detail: e.message } })
    } finally {
      setProbing(null)
    }
  }

  const accounts = data?.results || data || []
  const connected = accounts.filter(a => a.status === 'connected').length

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-gray-800">📡 حسابات القنوات</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {accounts.length} حساب — {connected} متصل
          </p>
        </div>
        <button onClick={() => setModal({})}
                className="bg-indigo-600 text-white rounded-lg px-4 py-2 text-sm">
          + حساب جديد
        </button>
      </div>

      {probeResult && (
        <div className={`mb-4 rounded-lg border px-4 py-2 text-sm flex items-center justify-between
          ${probeResult.probe?.ok ? 'bg-green-50 border-green-200 text-green-800'
                                   : 'bg-red-50 border-red-200 text-red-700'}`}>
          <span>
            {probeResult.probe?.ok
              ? `✅ ${probeResult.acc}: متصل${probeResult.probe.quality_rating ? ` — جودة ${probeResult.probe.quality_rating}` : ''}`
              : `❌ ${probeResult.acc}: ${probeResult.probe?.detail || 'فشل الفحص'}`}
          </span>
          <button onClick={() => setProbeResult(null)} className="text-gray-400">✕</button>
        </div>
      )}

      {isLoading ? (
        <p className="text-center text-gray-400 py-16">جاري التحميل...</p>
      ) : accounts.length === 0 ? (
        <div className="text-center text-gray-400 py-16">
          <p className="text-4xl mb-2">📡</p>
          <p>لا توجد حسابات — أضف رقم واتساب أول</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {accounts.map(acc => (
            <AccountCard key={acc.id} acc={acc}
                         onEdit={setModal} onProbe={probe} probing={probing} />
          ))}
        </div>
      )}

      {modal !== null && <AccountModal acc={modal.id ? modal : null} onClose={() => setModal(null)} />}
    </div>
  )
}
