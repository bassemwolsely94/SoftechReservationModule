/**
 * InsuranceClientsPage.jsx
 * Insurance client / sub-client / contract management.
 *
 * Three panels:
 *   Left:   Insurance clients list   (add + edit)
 *   Middle: Sub-clients for client   (add + edit)
 *   Right:  Contracts for sub-client (add + edit)
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'

function Btn({ children, onClick, variant = 'primary', size = 'sm', disabled, className = '' }) {
  const v = {
    primary: 'bg-blue-600 text-white hover:bg-blue-700',
    secondary: 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50',
    success: 'bg-green-600 text-white hover:bg-green-700',
    danger: 'bg-red-50 text-red-600 border border-red-200 hover:bg-red-100',
  }
  const s = { sm: 'px-2.5 py-1 text-xs', md: 'px-4 py-2 text-sm' }
  return (
    <button onClick={onClick} disabled={disabled}
      className={`inline-flex items-center gap-1 rounded font-medium transition-colors disabled:opacity-50 ${s[size]} ${v[variant]} ${className}`}>
      {children}
    </button>
  )
}

// Small inline edit (pencil) button used inside list rows
function EditIcon({ onClick, active }) {
  return (
    <span
      role="button"
      title="تعديل"
      onClick={(e) => { e.stopPropagation(); onClick() }}
      className={`shrink-0 cursor-pointer rounded px-1.5 py-0.5 text-xs ${
        active ? 'bg-white/20 text-white' : 'text-gray-400 hover:text-blue-600 hover:bg-blue-50'
      }`}>
      ✏️
    </span>
  )
}

const inp = 'w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500'
const lbl = 'block text-xs font-medium text-gray-600 mb-1'

const EMPTY_CLIENT   = { name: '', name_short: '', softech_personcode: '', address: '', notes: '' }
const EMPTY_SUB      = { name: '', softech_personcode: '', additional_personcodes: '', notes: '' }
const EMPTY_CONTRACT = {
  name: '', effective_from: '', effective_to: '',
  local_discount_pct: '17', imported_discount_pct: '6', tarsia_discount_pct: '0',
  softech_ptclassifcodes: '15,10',
}

// ── Client Panel ───────────────────────────────────────────────────────────────
function ClientPanel({ selected, onSelect }) {
  const [clients, setClients] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId]     = useState(null)   // null = create mode
  const [form, setForm]         = useState(EMPTY_CLIENT)
  const [saving, setSaving]     = useState(false)

  const load = () => insuranceApi.clients({}).then(r => setClients(r.data.results || r.data))
  useEffect(() => { load() }, [])

  const openAdd = () => { setEditId(null); setForm(EMPTY_CLIENT); setShowForm(true) }
  const openEdit = (c) => {
    setEditId(c.id)
    setForm({
      name: c.name || '', name_short: c.name_short || '',
      softech_personcode: c.softech_personcode || '',
      address: c.address || '', notes: c.notes || '',
    })
    setShowForm(true)
  }
  const close = () => { setShowForm(false); setEditId(null) }

  const save = async () => {
    setSaving(true)
    try {
      if (editId) {
        const { data } = await insuranceApi.updateClient(editId, form)
        if (selected?.id === editId) onSelect(data)   // refresh the selected object
      } else {
        await insuranceApi.createClient(form)
      }
      close(); load()
    } finally { setSaving(false) }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex justify-between items-center mb-3">
        <h2 className="font-semibold text-gray-700 text-sm">جهات التأمين</h2>
        <Btn onClick={openAdd}>+ جديد</Btn>
      </div>

      {showForm && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-3 space-y-2">
          <p className="text-xs font-semibold text-blue-800">
            {editId ? 'تعديل جهة التأمين' : 'إضافة جهة تأمين'}
          </p>
          <div>
            <label className={lbl}>اسم الجهة *</label>
            <input className={inp} value={form.name} onChange={e => setForm(p => ({...p, name: e.target.value}))} />
          </div>
          <div>
            <label className={lbl}>الاسم المختصر</label>
            <input className={inp} value={form.name_short} onChange={e => setForm(p => ({...p, name_short: e.target.value}))} placeholder="مثال: كهرباء جنوب" />
          </div>
          <div>
            <label className={lbl}>كود العميل في سوفتك</label>
            <input className={inp} value={form.softech_personcode} onChange={e => setForm(p => ({...p, softech_personcode: e.target.value}))} placeholder="personcode..." />
          </div>
          <div>
            <label className={lbl}>العنوان</label>
            <input className={inp} value={form.address} onChange={e => setForm(p => ({...p, address: e.target.value}))} />
          </div>
          <div>
            <label className={lbl}>ملاحظات</label>
            <input className={inp} value={form.notes} onChange={e => setForm(p => ({...p, notes: e.target.value}))} />
          </div>
          <div className="flex gap-2">
            <Btn onClick={save} disabled={!form.name || saving} size="md">
              {saving ? 'جارٍ الحفظ...' : (editId ? 'حفظ التعديل' : 'حفظ')}
            </Btn>
            <Btn onClick={close} variant="secondary" size="md">إلغاء</Btn>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-1">
        {clients.map(c => {
          const active = selected?.id === c.id
          return (
            <div key={c.id} onClick={() => onSelect(c)}
              className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm cursor-pointer transition-colors ${
                active ? 'bg-blue-600 text-white' : 'bg-white border border-gray-200 hover:bg-gray-50 text-gray-800'
              }`}>
              <div className="flex-1 text-right">
                <div className="font-medium">{c.name_short || c.name}</div>
                {c.softech_personcode && (
                  <div className={`text-xs mt-0.5 ${active ? 'text-blue-200' : 'text-gray-400'}`}>
                    كود: {c.softech_personcode}
                  </div>
                )}
              </div>
              <EditIcon active={active} onClick={() => openEdit(c)} />
            </div>
          )
        })}
        {clients.length === 0 && (
          <p className="text-center text-gray-400 py-6 text-sm">لا توجد جهات</p>
        )}
      </div>
    </div>
  )
}

// ── SubClient Panel ────────────────────────────────────────────────────────────
function SubClientPanel({ client, selected, onSelect }) {
  const [subclients, setSubclients] = useState([])
  const [showForm, setShowForm]     = useState(false)
  const [editId, setEditId]         = useState(null)
  const [form, setForm]             = useState(EMPTY_SUB)
  const [saving, setSaving]         = useState(false)

  const load = () => {
    if (!client) { setSubclients([]); return }
    insuranceApi.subclients({ client_id: client.id })
      .then(r => setSubclients(r.data.results || r.data))
  }
  useEffect(() => { load() }, [client?.id])

  const openAdd = () => { setEditId(null); setForm(EMPTY_SUB); setShowForm(true) }
  const openEdit = (sc) => {
    setEditId(sc.id)
    setForm({
      name: sc.name || '', softech_personcode: sc.softech_personcode || '',
      additional_personcodes: sc.additional_personcodes || '', notes: sc.notes || '',
    })
    setShowForm(true)
  }
  const close = () => { setShowForm(false); setEditId(null) }

  const save = async () => {
    setSaving(true)
    try {
      if (editId) {
        const { data } = await insuranceApi.updateSubclient(editId, form)
        if (selected?.id === editId) onSelect(data)
      } else {
        await insuranceApi.createSubclient({ ...form, client: client.id })
      }
      close(); load()
    } finally { setSaving(false) }
  }

  if (!client) return (
    <div className="flex items-center justify-center h-full text-gray-400 text-sm">
      اختر جهة تأمين
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <div className="flex justify-between items-center mb-3">
        <h2 className="font-semibold text-gray-700 text-sm">الفئات — {client.name_short || client.name}</h2>
        <Btn onClick={openAdd}>+ فئة</Btn>
      </div>

      {showForm && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-3 space-y-2">
          <p className="text-xs font-semibold text-blue-800">
            {editId ? 'تعديل الفئة' : 'إضافة فئة'}
          </p>
          <div>
            <label className={lbl}>اسم الفئة *</label>
            <input className={inp} value={form.name} onChange={e => setForm(p => ({...p, name: e.target.value}))}
              placeholder="مثال: العاملين / المعاشات / الأسر" />
          </div>
          <div>
            <label className={lbl}>كود سوفتك (إذا مختلف)</label>
            <input className={inp} value={form.softech_personcode}
              onChange={e => setForm(p => ({...p, softech_personcode: e.target.value}))} />
          </div>
          <div>
            <label className={lbl}>أكواد إضافية (مفصولة بفاصلة)</label>
            <input className={inp} value={form.additional_personcodes}
              onChange={e => setForm(p => ({...p, additional_personcodes: e.target.value}))}
              placeholder="كود1,كود2,كود3" />
          </div>
          <div>
            <label className={lbl}>ملاحظات</label>
            <input className={inp} value={form.notes}
              onChange={e => setForm(p => ({...p, notes: e.target.value}))} />
          </div>
          <div className="flex gap-2">
            <Btn onClick={save} disabled={!form.name || saving} size="md">
              {saving ? 'جارٍ الحفظ...' : (editId ? 'حفظ التعديل' : 'حفظ')}
            </Btn>
            <Btn onClick={close} variant="secondary" size="md">إلغاء</Btn>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-1">
        {subclients.map(sc => {
          const active = selected?.id === sc.id
          return (
            <div key={sc.id} onClick={() => onSelect(sc)}
              className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm cursor-pointer transition-colors ${
                active ? 'bg-purple-600 text-white' : 'bg-white border border-gray-200 hover:bg-gray-50 text-gray-800'
              }`}>
              <div className="flex-1 text-right">
                <div className="font-medium">{sc.name}</div>
                {(sc.softech_personcode || client.softech_personcode) && (
                  <div className={`text-xs mt-0.5 ${active ? 'text-purple-200' : 'text-gray-400'}`}>
                    كود: {sc.softech_personcode || client.softech_personcode}
                  </div>
                )}
              </div>
              <EditIcon active={active} onClick={() => openEdit(sc)} />
            </div>
          )
        })}
        {subclients.length === 0 && (
          <p className="text-center text-gray-400 py-6 text-sm">لا توجد فئات</p>
        )}
      </div>
    </div>
  )
}

// ── Contract Panel ─────────────────────────────────────────────────────────────
function ContractPanel({ subclient }) {
  const [contracts, setContracts] = useState([])
  const [showForm, setShowForm]   = useState(false)
  const [editId, setEditId]       = useState(null)
  const [form, setForm]           = useState(EMPTY_CONTRACT)
  const [saving, setSaving]       = useState(false)

  const load = () => {
    if (!subclient) { setContracts([]); return }
    insuranceApi.contracts({ subclient_id: subclient.id })
      .then(r => setContracts(r.data.results || r.data))
  }
  useEffect(() => { load() }, [subclient?.id])

  const openAdd = () => { setEditId(null); setForm(EMPTY_CONTRACT); setShowForm(true) }
  const openEdit = (c) => {
    setEditId(c.id)
    setForm({
      name: c.name || '',
      effective_from: c.effective_from || '',
      effective_to: c.effective_to || '',
      local_discount_pct: String(c.local_discount_pct ?? ''),
      imported_discount_pct: String(c.imported_discount_pct ?? ''),
      tarsia_discount_pct: String(c.tarsia_discount_pct ?? ''),
      softech_ptclassifcodes: c.softech_ptclassifcodes || '15,10',
    })
    setShowForm(true)
  }
  const close = () => { setShowForm(false); setEditId(null) }

  const save = async () => {
    setSaving(true)
    try {
      if (editId) {
        await insuranceApi.updateContract(editId, form)
      } else {
        await insuranceApi.createContract({ ...form, subclient: subclient.id })
      }
      close(); load()
    } finally { setSaving(false) }
  }

  if (!subclient) return (
    <div className="flex items-center justify-center h-full text-gray-400 text-sm">
      اختر فئة
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <div className="flex justify-between items-center mb-3">
        <h2 className="font-semibold text-gray-700 text-sm">العقود — {subclient.name}</h2>
        <Btn onClick={openAdd}>+ عقد</Btn>
      </div>

      {showForm && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-3 space-y-2">
          <p className="text-xs font-semibold text-amber-800">
            {editId ? 'تعديل العقد' : 'إضافة عقد'}
          </p>
          <div>
            <label className={lbl}>اسم العقد</label>
            <input className={inp} value={form.name} onChange={e => setForm(p => ({...p, name: e.target.value}))}
              placeholder="مثال: عقد 2026" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={lbl}>تاريخ البداية *</label>
              <input type="date" className={inp} value={form.effective_from}
                onChange={e => setForm(p => ({...p, effective_from: e.target.value}))} />
            </div>
            <div>
              <label className={lbl}>تاريخ النهاية</label>
              <input type="date" className={inp} value={form.effective_to}
                onChange={e => setForm(p => ({...p, effective_to: e.target.value}))} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[
              ['خصم المحلى %', 'local_discount_pct'],
              ['خصم المستورد %', 'imported_discount_pct'],
              ['خصم الترسية %', 'tarsia_discount_pct'],
            ].map(([label, key]) => (
              <div key={key}>
                <label className={lbl}>{label}</label>
                <input type="number" step="0.01" min="0" max="100" className={inp}
                  value={form[key]} onChange={e => setForm(p => ({...p, [key]: e.target.value}))} />
              </div>
            ))}
          </div>
          <div>
            <label className={lbl}>أكواد ptclassifcode (مفصولة بفاصلة)</label>
            <input className={inp} value={form.softech_ptclassifcodes}
              onChange={e => setForm(p => ({...p, softech_ptclassifcodes: e.target.value}))}
              placeholder="15,10" />
            <p className="text-xs text-gray-400 mt-0.5">15=تأمين صحي، 10=تعاقدات/آجل</p>
          </div>
          <div className="flex gap-2">
            <Btn onClick={save} disabled={!form.effective_from || saving} size="md">
              {saving ? 'جارٍ الحفظ...' : (editId ? 'حفظ التعديل' : 'حفظ العقد')}
            </Btn>
            <Btn onClick={close} variant="secondary" size="md">إلغاء</Btn>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-2">
        {contracts.map(c => (
          <div key={c.id} className="bg-white border border-gray-200 rounded-lg p-3">
            <div className="flex justify-between items-start mb-2">
              <span className="font-medium text-gray-800 text-sm">{c.name || `عقد ${c.effective_from}`}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">{c.effective_from} → {c.effective_to || 'مفتوح'}</span>
                <EditIcon active={false} onClick={() => openEdit(c)} />
              </div>
            </div>
            <div className="flex gap-4 text-xs">
              <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded">محلى {c.local_discount_pct}%</span>
              <span className="bg-purple-50 text-purple-700 px-2 py-0.5 rounded">مستورد {c.imported_discount_pct}%</span>
              <span className="bg-teal-50 text-teal-700 px-2 py-0.5 rounded">ترسية {c.tarsia_discount_pct}%</span>
            </div>
          </div>
        ))}
        {contracts.length === 0 && (
          <p className="text-center text-gray-400 py-6 text-sm">لا توجد عقود</p>
        )}
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function InsuranceClientsPage() {
  const navigate = useNavigate()
  const [selectedClient,    setSelectedClient]    = useState(null)
  const [selectedSubclient, setSelectedSubclient] = useState(null)

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center gap-3 mb-1">
          <button onClick={() => navigate('/insurance')} className="text-blue-600 text-sm hover:underline">
            ← مطالبات التأمين
          </button>
        </div>
        <h1 className="text-xl font-bold text-gray-900">إدارة العملاء والعقود</h1>
        <p className="text-sm text-gray-500 mt-0.5">جهات التأمين — الفئات — العقود ونسب الخصم</p>
      </div>

      <div className="px-6 py-6 grid grid-cols-3 gap-6 h-[calc(100vh-130px)]">
        <div className="bg-white rounded-xl border border-gray-200 p-4 overflow-hidden flex flex-col">
          <ClientPanel
            selected={selectedClient}
            onSelect={(c) => { setSelectedClient(c); setSelectedSubclient(null) }}
          />
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 overflow-hidden flex flex-col">
          <SubClientPanel
            client={selectedClient}
            selected={selectedSubclient}
            onSelect={setSelectedSubclient}
          />
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 overflow-hidden flex flex-col">
          <ContractPanel subclient={selectedSubclient} />
        </div>
      </div>
    </div>
  )
}
