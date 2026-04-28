import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { customersApi, itemsApi, branchesApi, reservationsApi } from '../api/client'
import { PRIORITY_OPTIONS } from '../components/StatusBadge'

// ── Step indicators ────────────────────────────────────────────────────────────
function StepDot({ n, active, done }) {
  return (
    <div className="flex items-center gap-2">
      <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm
        ${done  ? 'bg-brand-600 text-white' :
          active ? 'bg-white border-2 border-brand-600 text-brand-700' :
                   'bg-gray-100 text-gray-400'}`}>
        {done ? '✓' : n}
      </div>
    </div>
  )
}

// ── Step 1: Customer search ────────────────────────────────────────────────────
function StepCustomer({ selected, onSelect }) {
  const [query, setQuery] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [newForm, setNewForm] = useState({ name: '', phone: '', phone_alt: '', address: '' })

  const { data, isFetching } = useQuery({
    queryKey: ['customerSearch', query],
    queryFn: () => customersApi.list({ search: query, page_size: 8 }).then(r => r.data.results || r.data),
    enabled: query.length >= 2,
  })

  return (
    <div dir="rtl">
      <h3 className="font-bold text-gray-700 mb-4">البحث عن العميل</h3>

      {selected ? (
        <div className="card border border-brand-200 bg-brand-50 flex items-center justify-between">
          <div>
            <div className="font-bold text-brand-800">{selected.name}</div>
            <div className="text-sm text-brand-600">{selected.phone}</div>
            {selected.phone_alt && <div className="text-xs text-gray-500">{selected.phone_alt}</div>}
          </div>
          <button onClick={() => onSelect(null)} className="text-sm text-brand-600 hover:underline">تغيير</button>
        </div>
      ) : (
        <>
          <input
            type="text"
            className="input-field mb-3"
            placeholder="ابحث بالاسم أو رقم الهاتف..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            autoFocus
          />

          {isFetching && <div className="text-sm text-gray-400 mb-2">جارٍ البحث...</div>}

          {data && data.length > 0 && (
            <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 mb-3 max-h-64 overflow-auto">
              {data.map(c => (
                <div
                  key={c.id}
                  onClick={() => onSelect(c)}
                  className="flex items-center justify-between px-4 py-2.5 hover:bg-brand-50 cursor-pointer transition-colors"
                >
                  <div>
                    <div className="font-semibold text-sm text-gray-800">{c.name}</div>
                    <div className="text-xs text-gray-500">{c.phone}</div>
                  </div>
                  <span className={`badge ${
                    c.customer_type_color === 'blue'  ? 'bg-blue-100 text-blue-700' :
                    c.customer_type_color === 'green' ? 'bg-green-100 text-green-700' :
                    'bg-gray-100 text-gray-600'
                  }`}>{c.customer_type_label}</span>
                </div>
              ))}
            </div>
          )}

          {data && data.length === 0 && query.length >= 2 && (
            <div className="text-sm text-gray-500 mb-3">لا توجد نتائج.</div>
          )}

          <button
            className="text-brand-600 text-sm font-semibold hover:underline"
            onClick={() => setShowNew(v => !v)}
          >
            {showNew ? 'إخفاء' : '+ إنشاء عميل جديد'}
          </button>

          {showNew && (
            <NewCustomerForm
              form={newForm}
              onChange={setNewForm}
              onCreated={onSelect}
            />
          )}
        </>
      )}
    </div>
  )
}

function NewCustomerForm({ form, onChange, onCreated }) {
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => customersApi.create(form),
    onSuccess: ({ data }) => {
      qc.invalidateQueries(['customerSearch'])
      onCreated(data)
    },
  })

  return (
    <div className="card mt-3 border border-gray-200 animate-fade-in">
      <h4 className="font-bold text-sm text-gray-700 mb-3">عميل جديد</h4>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">الاسم *</label>
          <input className="input-field" value={form.name}
            onChange={e => onChange({ ...form, name: e.target.value })} />
        </div>
        <div>
          <label className="label">رقم الهاتف *</label>
          <input className="input-field" value={form.phone}
            onChange={e => onChange({ ...form, phone: e.target.value })} />
        </div>
        <div>
          <label className="label">هاتف بديل</label>
          <input className="input-field" value={form.phone_alt}
            onChange={e => onChange({ ...form, phone_alt: e.target.value })} />
        </div>
        <div>
          <label className="label">العنوان</label>
          <input className="input-field" value={form.address}
            onChange={e => onChange({ ...form, address: e.target.value })} />
        </div>
      </div>
      {mutation.isError && (
        <div className="text-red-600 text-xs mt-2">
          {mutation.error?.response?.data?.detail || 'خطأ في الإنشاء'}
        </div>
      )}
      <button
        className="btn-primary mt-3 text-sm disabled:opacity-50"
        disabled={!form.name || !form.phone || mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? 'جارٍ الحفظ...' : 'إنشاء العميل'}
      </button>
    </div>
  )
}

// ── Step 2: Item + Branch ──────────────────────────────────────────────────────
function StepItem({ selected, branch, quantity, onSelect, onBranch, onQuantity, branches }) {
  const [query, setQuery] = useState('')

  const { data, isFetching } = useQuery({
    queryKey: ['itemSearch', query],
    queryFn: () => itemsApi.list({ search: query, page_size: 8 }).then(r => r.data.results || r.data),
    enabled: query.length >= 2,
  })

  const { data: stockData } = useQuery({
    queryKey: ['itemStock', selected?.id],
    queryFn: () => itemsApi.stock(selected.id).then(r => r.data),
    enabled: !!selected,
  })

  return (
    <div dir="rtl">
      <h3 className="font-bold text-gray-700 mb-4">اختيار الصنف والفرع</h3>

      {/* Item search */}
      {selected ? (
        <div className="card border border-brand-200 bg-brand-50 mb-4 flex items-center justify-between">
          <div>
            <div className="font-bold text-brand-800">{selected.name}</div>
            {selected.name_scientific && (
              <div className="text-xs text-gray-500 italic">{selected.name_scientific}</div>
            )}
            <div className="text-sm text-brand-600">{selected.unit_price} ج.م</div>
          </div>
          <button onClick={() => onSelect(null)} className="text-sm text-brand-600 hover:underline">تغيير</button>
        </div>
      ) : (
        <div className="mb-4">
          <input
            type="text"
            className="input-field mb-2"
            placeholder="ابحث بالاسم أو الباركود أو الاسم العلمي..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            autoFocus
          />
          {isFetching && <div className="text-sm text-gray-400">جارٍ البحث...</div>}
          {data && data.length > 0 && (
            <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-64 overflow-auto">
              {data.map(item => (
                <div
                  key={item.id}
                  onClick={() => onSelect(item)}
                  className="flex items-center justify-between px-4 py-2.5 hover:bg-brand-50 cursor-pointer"
                >
                  <div>
                    <div className="font-semibold text-sm text-gray-800">{item.name}</div>
                    {item.name_scientific && (
                      <div className="text-xs text-gray-400 italic">{item.name_scientific}</div>
                    )}
                  </div>
                  <div className="text-left">
                    <div className="text-xs font-bold text-brand-700">{item.unit_price} ج.م</div>
                    <div className={`text-xs ${item.total_stock > 0 ? 'text-green-600' : 'text-red-500'}`}>
                      {item.total_stock > 0 ? `${item.total_stock} متاح` : 'نفد'}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Stock per branch */}
      {selected && stockData && (
        <div className="mb-4">
          <label className="label">المخزون حسب الفرع</label>
          <div className="grid grid-cols-2 gap-2">
            {stockData.map(s => (
              <div
                key={s.id}
                onClick={() => onBranch(s.branch)}
                className={`border rounded-lg px-3 py-2 cursor-pointer transition-colors text-sm
                  ${branch === s.branch
                    ? 'border-brand-500 bg-brand-50 text-brand-700'
                    : 'border-gray-200 hover:border-brand-300'}`}
              >
                <div className="font-semibold">{s.branch_name_ar || s.branch_name}</div>
                <div className={`text-xs mt-0.5 ${
                  s.stock_status === 'in_stock' ? 'text-green-600' :
                  s.stock_status === 'low_stock' ? 'text-orange-500' : 'text-red-500'
                }`}>
                  {s.quantity_on_hand} وحدة — {s.stock_status_label}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Branch selector (fallback if no stock data) */}
      {selected && (!stockData || stockData.length === 0) && (
        <div className="mb-4">
          <label className="label">الفرع *</label>
          <select className="input-field" value={branch} onChange={e => onBranch(e.target.value)}>
            <option value="">اختر الفرع</option>
            {(branches || []).map(b => (
              <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Quantity */}
      {selected && (
        <div>
          <label className="label">الكمية المطلوبة *</label>
          <input
            type="number"
            min="1"
            step="1"
            className="input-field w-32"
            value={quantity}
            onChange={e => onQuantity(e.target.value)}
          />
        </div>
      )}
    </div>
  )
}

// ── Step 3: Details ────────────────────────────────────────────────────────────
function StepDetails({ form, onChange }) {
  return (
    <div dir="rtl">
      <h3 className="font-bold text-gray-700 mb-4">تفاصيل الحجز</h3>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">اسم التواصل *</label>
          <input className="input-field" value={form.contact_name}
            onChange={e => onChange({ ...form, contact_name: e.target.value })} />
        </div>
        <div>
          <label className="label">هاتف التواصل *</label>
          <input className="input-field" value={form.contact_phone}
            onChange={e => onChange({ ...form, contact_phone: e.target.value })} />
        </div>
        <div>
          <label className="label">الأولوية</label>
          <select className="input-field" value={form.priority}
            onChange={e => onChange({ ...form, priority: e.target.value })}>
            {PRIORITY_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">تاريخ الوصول المتوقع</label>
          <input type="date" className="input-field" value={form.expected_arrival_date}
            onChange={e => onChange({ ...form, expected_arrival_date: e.target.value })} />
        </div>
        <div>
          <label className="label">تاريخ المتابعة</label>
          <input type="date" className="input-field" value={form.follow_up_date}
            onChange={e => onChange({ ...form, follow_up_date: e.target.value })} />
        </div>
        <div className="col-span-2">
          <label className="label">ملاحظات</label>
          <textarea rows={3} className="input-field" value={form.notes}
            onChange={e => onChange({ ...form, notes: e.target.value })}
            placeholder="أي تفاصيل إضافية..." />
        </div>
      </div>
    </div>
  )
}

// ── Main Wizard ────────────────────────────────────────────────────────────────
export default function NewReservationPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [step, setStep] = useState(1)

  const [customer, setCustomer] = useState(null)
  const [item, setItem] = useState(null)
  const [branch, setBranch] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [details, setDetails] = useState({
    contact_name: '',
    contact_phone: '',
    priority: 'normal',
    notes: '',
    expected_arrival_date: '',
    follow_up_date: '',
  })

  const { data: branches } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })

  // Auto-fill contact from customer
  const handleCustomerSelect = (c) => {
    setCustomer(c)
    if (c) {
      setDetails(d => ({
        ...d,
        contact_name: c.name,
        contact_phone: c.phone,
      }))
    }
  }

  const mutation = useMutation({
    mutationFn: () => reservationsApi.create({
      customer: customer.id,
      item: item.id,
      branch: branch,
      quantity_requested: quantity,
      ...details,
      expected_arrival_date: details.expected_arrival_date || null,
      follow_up_date: details.follow_up_date || null,
    }),
    onSuccess: ({ data }) => {
      qc.invalidateQueries(['reservations'])
      navigate(`/reservations/${data.id}`)
    },
  })

  const canNext = step === 1 ? !!customer
    : step === 2 ? (!!item && !!branch && quantity > 0)
    : (!!details.contact_name && !!details.contact_phone)

  const STEPS = ['العميل', 'الصنف والفرع', 'التفاصيل']

  return (
    <div className="p-6 max-w-2xl mx-auto" dir="rtl">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/reservations')}
          className="text-gray-400 hover:text-gray-600 transition-colors">
          ←
        </button>
        <h1 className="text-xl font-black text-gray-800">حجز جديد</h1>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-3 mb-8">
        {STEPS.map((label, i) => (
          <div key={i} className="flex items-center gap-2">
            <StepDot n={i + 1} active={step === i + 1} done={step > i + 1} />
            <span className={`text-sm font-medium ${step === i + 1 ? 'text-brand-700' : 'text-gray-400'}`}>
              {label}
            </span>
            {i < STEPS.length - 1 && <span className="text-gray-200 mx-1">—</span>}
          </div>
        ))}
      </div>

      {/* Step content */}
      <div className="card min-h-64 mb-6 animate-fade-in">
        {step === 1 && <StepCustomer selected={customer} onSelect={handleCustomerSelect} />}
        {step === 2 && (
          <StepItem
            selected={item}
            branch={branch}
            quantity={quantity}
            onSelect={setItem}
            onBranch={setBranch}
            onQuantity={setQuantity}
            branches={branches}
          />
        )}
        {step === 3 && <StepDetails form={details} onChange={setDetails} />}
      </div>

      {/* Navigation */}
      {mutation.isError && (
        <div className="text-red-600 text-sm mb-3 card border border-red-200 bg-red-50">
          {mutation.error?.response?.data?.detail ||
           JSON.stringify(mutation.error?.response?.data) ||
           'حدث خطأ. تحقق من البيانات وحاول مرة أخرى.'}
        </div>
      )}

      <div className="flex justify-between">
        <button
          disabled={step === 1}
          onClick={() => setStep(s => s - 1)}
          className="btn-secondary disabled:opacity-40"
        >
          السابق
        </button>
        {step < 3 ? (
          <button
            disabled={!canNext}
            onClick={() => setStep(s => s + 1)}
            className="btn-primary disabled:opacity-40"
          >
            التالي
          </button>
        ) : (
          <button
            disabled={!canNext || mutation.isPending}
            onClick={() => mutation.mutate()}
            className="btn-primary disabled:opacity-40"
          >
            {mutation.isPending ? 'جارٍ الحفظ...' : 'تأكيد الحجز'}
          </button>
        )}
      </div>
    </div>
  )
}
