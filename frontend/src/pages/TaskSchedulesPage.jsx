/**
 * TaskSchedulesPage.jsx
 * Manage recurring task schedules (create, edit, run, toggle).
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { tasksApi, branchesApi, usersApi } from '../api/client'

const FREQ_LABELS = { none: 'لا تتكرر', daily: 'يومي', weekly: 'أسبوعي', monthly: 'شهري' }
const TYPE_LABELS = {
  stock_count: 'جرد', receiving: 'استلام', transfer: 'تحويل',
  delivery: 'توصيل', shortage: 'نقص', purchasing: 'مشتريات',
  maintenance: 'صيانة', meeting: 'اجتماع', training: 'تدريب',
  audit: 'تدقيق', customer: 'عملاء', other: 'أخرى',
}
const PRIORITY_LABELS = { low: 'منخفضة', normal: 'عادية', high: 'عالية', urgent: 'عاجلة', critical: 'حرجة' }

const EMPTY_FORM = {
  name: '', task_type: 'other', category: 'operations', priority: 'normal',
  title_template: '', description_template: '',
  branch: '', assign_to: '', assign_to_role: '',
  frequency: 'daily', day_of_week: '', day_of_month: '', time_of_day: '',
  advance_days: 1, estimated_hours: '',
  is_active: true,
}

function fmt(d) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function ScheduleForm({ initial, branches, staff, onSave, onCancel }) {
  const [form, setForm] = useState(initial || EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const submit = async () => {
    if (!form.name.trim() || !form.title_template.trim()) {
      setError('الاسم وقالب العنوان مطلوبان.')
      return
    }
    setSaving(true); setError(null)
    try {
      const payload = { ...form }
      if (!payload.branch) delete payload.branch
      if (!payload.assign_to) delete payload.assign_to
      if (!payload.estimated_hours) delete payload.estimated_hours
      if (!payload.day_of_week && payload.day_of_week !== 0) delete payload.day_of_week
      if (!payload.day_of_month) delete payload.day_of_month
      if (!payload.time_of_day) delete payload.time_of_day
      await onSave(payload)
    } catch (e) {
      setError(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'خطأ')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5" dir="rtl">
      <h3 className="font-bold text-gray-800 mb-4 text-right">{initial?.id ? 'تعديل الجدول' : 'جدول جديد'}</h3>
      {error && <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded mb-3">{error}</div>}

      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">اسم الجدول *</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm text-right" placeholder="مثال: جرد يومي فرع X" value={form.name} onChange={e => set('name', e.target.value)} />
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">قالب عنوان المهمة * <span className="text-gray-400 font-normal">(استخدم {'{date}'} و{'{branch}'})</span></label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm text-right" placeholder="مثال: جرد يومي — {branch} — {date}" value={form.title_template} onChange={e => set('title_template', e.target.value)} />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">النوع</label>
          <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.task_type} onChange={e => set('task_type', e.target.value)}>
            {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">الأولوية</label>
          <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.priority} onChange={e => set('priority', e.target.value)}>
            {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">الفرع</label>
          <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.branch} onChange={e => set('branch', e.target.value)}>
            <option value="">— جميع الفروع —</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">تعيين إلى</label>
          <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.assign_to} onChange={e => set('assign_to', e.target.value)}>
            <option value="">— اختياري —</option>
            {staff.map(s => <option key={s.id} value={s.id}>{s.full_name || s.username}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">التكرار</label>
          <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.frequency} onChange={e => set('frequency', e.target.value)}>
            {Object.entries(FREQ_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">أيام مسبقة للاستحقاق</label>
          <input type="number" min={0} max={30} className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.advance_days} onChange={e => set('advance_days', parseInt(e.target.value) || 1)} />
        </div>

        {form.frequency === 'weekly' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1 text-right">يوم الأسبوع (0=الاثنين)</label>
            <input type="number" min={0} max={6} className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.day_of_week} onChange={e => set('day_of_week', e.target.value)} />
          </div>
        )}
        {form.frequency === 'monthly' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1 text-right">يوم الشهر (1-31)</label>
            <input type="number" min={1} max={31} className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.day_of_month} onChange={e => set('day_of_month', e.target.value)} />
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">الساعات المقدَّرة</label>
          <input type="number" min={0} step={0.5} className="w-full border rounded-lg px-3 py-2 text-sm text-right" placeholder="اختياري" value={form.estimated_hours} onChange={e => set('estimated_hours', e.target.value)} />
        </div>

        <div className="col-span-2">
          <label className="block text-xs font-medium text-gray-600 mb-1 text-right">قالب الوصف</label>
          <textarea className="w-full border rounded-lg px-3 py-2 text-sm text-right resize-none" rows={2} placeholder="اختياري..." value={form.description_template} onChange={e => set('description_template', e.target.value)} />
        </div>

        <div className="col-span-2 flex items-center gap-2 justify-end">
          <label className="text-sm text-gray-600">نشط</label>
          <input type="checkbox" checked={form.is_active} onChange={e => set('is_active', e.target.checked)} className="w-4 h-4 accent-brand-600" />
        </div>
      </div>

      <div className="flex gap-2 mt-4 justify-end">
        <button onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg">إلغاء</button>
        <button onClick={submit} disabled={saving} className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium">
          {saving ? 'جاري الحفظ...' : 'حفظ'}
        </button>
      </div>
    </div>
  )
}

export default function TaskSchedulesPage() {
  const navigate = useNavigate()
  const [schedules, setSchedules] = useState([])
  const [loading, setLoading] = useState(true)
  const [branches, setBranches] = useState([])
  const [staff, setStaff] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editTarget, setEditTarget] = useState(null)
  const [runMsg, setRunMsg] = useState(null)

  useEffect(() => {
    branchesApi.list().then(r => setBranches(r.data || [])).catch(() => {})
    usersApi.list().then(r => setStaff(r.data?.results || r.data || [])).catch(() => {})
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await tasksApi.listSchedules()
      setSchedules(data?.results || data || [])
    } catch {
      setSchedules([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const createSchedule = async (payload) => {
    await tasksApi.createSchedule(payload)
    setShowForm(false)
    load()
  }

  const updateSchedule = async (payload) => {
    await tasksApi.updateSchedule(editTarget.id, payload)
    setEditTarget(null)
    load()
  }

  const deleteSchedule = async (id) => {
    if (!window.confirm('حذف هذا الجدول؟')) return
    try {
      await tasksApi.deleteSchedule(id)
      load()
    } catch {}
  }

  const runNow = async (id, name) => {
    try {
      const { data } = await tasksApi.runSchedule(id)
      setRunMsg(`✅ تم إنشاء المهمة: ${data.task_number}`)
      load()
      setTimeout(() => setRunMsg(null), 4000)
    } catch (e) {
      setRunMsg(`❌ ${e.response?.data?.detail || 'خطأ'}`)
      setTimeout(() => setRunMsg(null), 4000)
    }
  }

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      <div className="bg-white border-b px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">الجداول التلقائية</h1>
          <p className="text-sm text-gray-500 mt-0.5">إنشاء وإدارة المهام المتكررة</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => navigate('/tasks/dashboard')} className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50">← لوحة التحكم</button>
          <button onClick={() => { setEditTarget(null); setShowForm(true) }} className="px-4 py-1.5 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 font-medium">+ جدول جديد</button>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 py-4 space-y-4">
        {runMsg && (
          <div className={`px-4 py-2 rounded-lg text-sm font-medium ${runMsg.startsWith('✅') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
            {runMsg}
          </div>
        )}

        {showForm && (
          <ScheduleForm
            branches={branches}
            staff={staff}
            onSave={createSchedule}
            onCancel={() => setShowForm(false)}
          />
        )}

        {editTarget && (
          <ScheduleForm
            initial={editTarget}
            branches={branches}
            staff={staff}
            onSave={updateSchedule}
            onCancel={() => setEditTarget(null)}
          />
        )}

        {loading ? (
          <div className="text-center py-12 text-gray-400">
            <div className="text-2xl animate-spin mb-2">⟳</div>
            <p className="text-sm">جاري التحميل...</p>
          </div>
        ) : schedules.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <div className="text-4xl mb-3">⏱</div>
            <p className="text-sm mb-3">لا توجد جداول بعد</p>
            <button onClick={() => setShowForm(true)} className="text-sm text-brand-600 underline">إنشاء أول جدول</button>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-right">
              <thead>
                <tr className="bg-gray-50 border-b text-xs text-gray-500 font-semibold">
                  <th className="px-4 py-3">الاسم</th>
                  <th className="px-4 py-3">التكرار</th>
                  <th className="px-4 py-3">الفرع</th>
                  <th className="px-4 py-3">المُعيَّن إليه</th>
                  <th className="px-4 py-3">المهام المولَّدة</th>
                  <th className="px-4 py-3">آخر تشغيل</th>
                  <th className="px-4 py-3">الحالة</th>
                  <th className="px-4 py-3">إجراءات</th>
                </tr>
              </thead>
              <tbody>
                {schedules.map(s => (
                  <tr key={s.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <p className="text-sm font-medium text-gray-800">{s.name}</p>
                      <p className="text-xs text-gray-400">{s.title_template}</p>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{FREQ_LABELS[s.frequency] || s.frequency}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{s.branch_name || 'جميع'}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{s.assign_to_name || '—'}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 text-center">{s.generated_count}</td>
                    <td className="px-4 py-3 text-xs text-gray-400">{fmt(s.last_run_at)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${s.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                        {s.is_active ? 'نشط' : 'موقوف'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        {s.is_active && (
                          <button onClick={() => runNow(s.id, s.name)} className="text-xs text-brand-600 hover:underline">تشغيل</button>
                        )}
                        <button onClick={() => { setShowForm(false); setEditTarget(s) }} className="text-xs text-gray-500 hover:underline">تعديل</button>
                        <button onClick={() => deleteSchedule(s.id)} className="text-xs text-red-400 hover:underline">حذف</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
