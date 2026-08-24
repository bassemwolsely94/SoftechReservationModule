import { useEffect, useMemo, useState, useCallback } from 'react'
import api from '../api/client'

/*
 * usePosOrder — shared state + logic for the Indirect-POS screen (web + mobile),
 * mirroring the SOFTECH "In-Direct Point of Sale" screen field-for-field
 * (header band, Items / Payment / Contract-Emp-Data tabs, mode flags). The backend
 * (/pos-orders/) is authoritative; fields not yet persisted server-side are carried
 * in `notes` JSON so nothing the operator enters is lost.
 */

export const CHANNELS = [
  { value: 'cash',      label: 'مبيعات نقدى',  code: '91', hot: 'Ctrl+F2' },   // عميل نقدى
  { value: 'delivery',  label: 'توصيل منزلى',  code: '90', hot: 'Ctrl+F3' },   // Home Delivery
  { value: 'contract',  label: 'مبيعات تعاقد', code: '10', hot: 'Ctrl+F4' },   // Contract Sales
  { value: 'insurance', label: 'تأمين',        code: '15' },
  { value: 'employee',  label: 'موظفين',       code: '11' },
  { value: 'vip',       label: 'VIP',          code: '99' },
  { value: 'permanent', label: 'عميل دائم',    code: '30' },
]
export const DOC_KINDS = [
  { value: 'sale',   label: 'بيع',   code: '115' },
  { value: 'return', label: 'مرتجع', code: '30' },
]
// Indirect-POS collects only نقدى / آجل. Card & cheque tender details are captured on the
// SOFTECH cashier screen after this order is sent — we don't duplicate them here.
export const PAY_METHODS = [
  { value: 'cash',   label: 'نقدى',  code: '30' },
  { value: 'credit', label: 'آجل',   code: '10' },
]
// named-account channels that carry a claim (companiesitems) + per-contract emp-data form — contract/
// insurance AND employee (موظفين) / permanent (عميل دائم); all verified to have a claim natively.
export const CLAIM_CHANNELS = ['contract', 'insurance', 'employee', 'permanent']
// channels whose sales earn SOFTECH purchase points (retail cash-style). Mirrors the backend
// POS_POINTS_ELIGIBLE_CHANNELS; contract/insurance earn 0.
export const CHANNELS_EARN = ['cash', 'delivery']

// Limits from SOFTECH "Sales Setup Options" (2026-07-29). Defaults for this install;
// the backend re-checks authoritatively.
export const POS_LIMITS = {
  MAX_FAKKA: 0.50,       // Max L.C. for خصم فكة (change/rounding discount)
  MAX_QTY_LINE: 10000,   // Max item sales quantity per POS line
  MAX_RETURN_DAYS: 90,   // Max days for a return invoice
  PIC_REQUIRED: ['delivery'],  // channels that must provide a PIC to save
}

// El-Rezeiky receipt header/footer (SOFTECH "POS Receipt" setup, 2026-07-29)
export const RECEIPT = {
  headers: [
    'El-Rezeiky Pharmacies',
    'إدارة صيدليات الرزيقي - ش الجلاء - ميدان رمسيس',
    'الخط الساخن 0225740408',
    'Whatsapp 01014019763',
  ],
  footers: [
    'تنقى طلباتكم على مدار 24 ساعة على الخط الساخن 0225740408',
    'أدوية الثلاجة ومنتجات التجميل لا ترد ولا تستبدل',
    'التجميل والاكسسوار والمستلزمات الطبية شاملة 14% ض.ق.م',
    'Whatsapp 01014019763',
  ],
}

// Contract Emp. Data — the 12 SOFTECH std. slots with their DEFAULT titles + companiesitems column keys.
// A contract relabels/enables a subset via motalba_fields; the live per-contract spec (GET
// /pos-orders/contract-fields/) overrides this static default. Keys = companiesitems columns so the
// entered `claim` maps straight through the serializer. Order = slots 1..12 (see contract_fields.py).
export const CONTRACT_EMP_FIELDS = [
  { key: 'patientname',        label: 'إسم المريض' },
  { key: 'patientno',          label: 'رقم المريض' },
  { key: 'financialno',        label: 'الرقم المالي' },
  { key: 'fileno',             label: 'رقم الملف' },
  { key: 'roshettano',         label: 'رقم الروشتة' },
  { key: 'membershipno',       label: 'رقم العضوية' },
  { key: 'deptname',           label: 'الإدارة / المنطقة' },
  { key: 'patientnationality', label: 'الجنسية' },
  { key: 'relativedegree',     label: 'درجة القرابة' },
  { key: 'comment',            label: 'ملاحظات / الطبيب' },
  { key: 'examdate',           label: 'تاريخ الكشف', type: 'date' },
  { key: 'hi_typecode',        label: 'تصنيف الطبيب' },
]

export const money = n =>
  Number(n || 0).toLocaleString('en-EG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const blankClaim = () => ({
  patientname: '', patientno: '', financialno: '', fileno: '', roshettano: '',
  membershipno: '', deptname: '', patientnationality: '', relativedegree: '',
  comment: '', examdate: '', hi_typecode: '',
})
const today = () => new Date().toISOString().slice(0, 10)
const blankTender = () => ({
  pay_type: 'cash', amount: 0, currency: 'L.E', exchange_rate: 1,
  card_type: '', cheque_card_no: '', due_date: '', internal_payserial: '',
})

export default function usePosOrder() {
  const [branches, setBranches] = useState([])
  const [ref, setRef] = useState(null)
  // header band
  const [branch, setBranch] = useState(() => localStorage.getItem('pos_branch') || '')
  const [storeCode, setStoreCode] = useState('')
  const [docKind, setDocKind] = useState('sale')
  const [channel, setChannel] = useState('cash')
  const [customer, setCustomer] = useState(null)
  // delivery (and any channel needing an individual PIC): the "Home Delivery Customer" is the
  // account (customer); picCustomer is the actual person selected via the directory (real PIC).
  const [picCustomer, setPicCustomer] = useState(null)
  // SOFTECH two-level customer: نوع العميل (type) → إسم العميل (entity) + branch stores
  const [custTypes, setCustTypes] = useState([])
  const [custType, setCustType] = useState('cash')       // selected type KEY
  const [entities, setEntities] = useState([])           // إسم العميل list for the type
  const [entityQuery, setEntityQuery] = useState('')     // search within the entity list
  const [stores, setStores] = useState([])               // من حساب مخزن (branch-dependent)
  const [docDate, setDocDate] = useState(today())
  const [dispenseSerial, setDispenseSerial] = useState('')      // مسلسل صرف (auto/read-only)
  const [salesperson, setSalesperson] = useState('')            // مسؤول البيع — usercode ONLY (to ERP)
  const [salespersonName, setSalespersonName] = useState('')    // display name (not sent)
  const [salespeople, setSalespeople] = useState([])            // {usercode, name} search results
  const [salespersonQuery, setSalespersonQuery] = useState('')  // search by usercode OR name
  const [paymentMethod, setPaymentMethod] = useState('cash')    // أسلوب السداد (header)
  const [changeDiscount, setChangeDiscount] = useState(0)       // خصم فكة (rounding)
  const [patientPayment, setPatientPayment] = useState('')      // ما يسدده المريض (contract co-pay; '' = pays full net)
  const [notes, setNotes] = useState('')                        // ملاحظات
  const [returnInvoice, setReturnInvoice] = useState('')
  // mode flags
  const [altPrice, setAltPrice] = useState(false)               // السعر البديل
  const [sellAtCost, setSellAtCost] = useState(false)           // بيع بالتكلفة
  const [printReceipt, setPrintReceipt] = useState(true)        // طباعة رسيت
  const [itemsReservation, setItemsReservation] = useState(false) // Items Reservation
  // doctor / Rx
  const [doctorName, setDoctorName] = useState('')
  const [doctorCode, setDoctorCode] = useState('')
  const [rx, setRx] = useState(null)
  // contract claim
  const [claim, setClaim] = useState(blankClaim())
  // per-contract emp-data field spec (null = not loaded → use CONTRACT_EMP_FIELDS default;
  // [] = contract has no configured fields; else the live motalba_fields spec for this contract)
  const [contractFields, setContractFields] = useState(null)
  // lines + tenders
  const [lines, setLines] = useState([])
  const [selected, setSelected] = useState(-1)
  const [numMode, setNumMode] = useState('qty')                 // qty | disc | price
  const [tenders, setTenders] = useState([blankTender()])
  const [activeTab, setActiveTab] = useState('items')           // items | payment | contract
  // batch picker + status
  const [batchModal, setBatchModal] = useState(null)
  const [busy, setBusy] = useState(false)
  const [plan, setPlan] = useState(null)
  const [msg, setMsg] = useState('')
  const [errs, setErrs] = useState([])
  // Odoo-style extras
  const [suggest, setSuggest] = useState({ map: {}, caps: {}, ceiling: null })   // discounts + per-item caps
  const [loyalty, setLoyalty] = useState(null)                          // customer points account
  const [pointsInfo, setPointsInfo] = useState({ eligible: true, enrolled: false })  // SOFTECH points earn (per-classification)
  const [fbt, setFbt] = useState([])                                   // frequently-bought-together upsell
  const [queueStatus, setQueueStatus] = useState({ queued: 0, push_failed: 0, pushing: 0 })
  const [parked, setParked] = useState(() => { try { return JSON.parse(localStorage.getItem('pos_parked') || '[]') } catch { return [] } })
  const [favorites, setFavorites] = useState(() => { try { return JSON.parse(localStorage.getItem('pos_favorites') || '[]') } catch { return [] } })

  useEffect(() => {
    api.get('/branches/').then(({ data }) => {
      // POS lists branches you can transact on (active + operational). HQ is kept in the list
      // (used for testing); only cancelled/suspended/CC nodes drop out (can_transact=False).
      const list = (data.results || data).filter(b => b.can_transact)
      setBranches(list)
    }).catch(() => {})
    api.get('/pos-orders/reference/').then(({ data }) => {
      setRef(data)
      if (data.seller_usercode) setSalesperson(data.seller_usercode)
      if (data.seller_name) setSalespersonName(data.seller_name)   // default to the logged-in seller's name
      if (data.default_branch) setBranch(prev => prev || String(data.default_branch))  // the seller's own branch
    }).catch(() => {})
  }, [])

  // clamp the selected branch to the POS-eligible list: a stale/HQ value from localStorage or
  // reference.default_branch is dropped; a lone eligible branch auto-selects.
  useEffect(() => {
    if (!branches.length) return
    const ids = new Set(branches.map(b => String(b.id)))
    setBranch(prev => (prev && ids.has(String(prev))) ? prev
      : (branches.length === 1 ? String(branches[0].id) : ''))
  }, [branches])

  // remember the last-used branch so the operator doesn't re-pick it every session
  useEffect(() => { if (branch) localStorage.setItem('pos_branch', String(branch)) }, [branch])

  // نوع العميل catalog — once
  useEffect(() => {
    api.get('/pos-orders/customer-types/').then(({ data }) => setCustTypes(data.types || [])).catch(() => {})
  }, [])

  // branch → its stores (branch-dependent) + pick the default store. Fall back to the
  // branch code so store is never left blank (which would block submit).
  useEffect(() => {
    if (!branch) { setStores([]); return }
    const b = branches.find(x => String(x.id) === String(branch))
    const fallback = (b?.softech_branch_id || '').slice(0, 3)
    if (fallback) setStoreCode(prev => prev || fallback)
    api.get('/pos-orders/branch-stores/', { params: { branch: Number(branch) } })
      .then(({ data }) => {
        const st = data.stores || []
        setStores(st)
        const def = st.find(s => s.default) || st[0]
        setStoreCode(def ? def.storecode : (fallback || ''))
        if (!st.length && data.note) setMsg(`تعذّر تحميل مخازن الفرع: ${data.note}`)
      }).catch(() => { setStores([]); if (fallback) setStoreCode(fallback) })
  }, [branch, branches])  // eslint-disable-line

  // مسئول البيع search (usercode OR name), debounced. Only the usercode ever reaches the ERP.
  useEffect(() => {
    if (!branch) { setSalespeople([]); return }
    const t = setTimeout(() => {
      api.get('/pos-orders/salespeople/', { params: { branch: Number(branch), q: salespersonQuery || undefined } })
        .then(({ data }) => setSalespeople(data.salespeople || [])).catch(() => setSalespeople([]))
    }, 250)
    return () => clearTimeout(t)
  }, [branch, salespersonQuery])  // eslint-disable-line

  // resolve the display name for a preset/selected usercode (e.g. the logged-in seller)
  useEffect(() => {
    if (!branch || !salesperson || salespersonName) return
    api.get('/pos-orders/salespeople/', { params: { branch: Number(branch), q: salesperson } })
      .then(({ data }) => {
        const hit = (data.salespeople || []).find(p => p.usercode === salesperson)
        if (hit) setSalespersonName(hit.name)
      }).catch(() => {})
  }, [branch, salesperson])  // eslint-disable-line

  const selectSalesperson = (p) => {
    setSalesperson(p?.usercode || '')       // usercode → ERP
    setSalespersonName(p?.name || '')       // name → display only
    setSalespersonQuery('')
  }

  const typeCfg = custTypes.find(t => t.key === custType)

  // نوع العميل change → sync channel + reset the chosen entity
  useEffect(() => {
    if (typeCfg) setChannel(typeCfg.channel)
    setCustomer(null); setEntityQuery('')
  }, [custType, typeCfg?.channel])  // eslint-disable-line

  // إسم العميل entities for the current type (debounced search; contract list is large)
  useEffect(() => {
    if (!branch || !custType) { setEntities([]); return }
    const t = setTimeout(() => {
      api.get('/pos-orders/customer-entities/',
        { params: { branch: Number(branch), type: custType, q: entityQuery || undefined } })
        .then(({ data }) => {
          const ents = data.entities || []
          setEntities(ents)
          // a type with a single fixed entity (نقدى → Walk-In, delivery → Home Delivery)
          // auto-selects it, so the operator doesn't have to pick it every time.
          if (ents.length === 1 && !entityQuery) {
            const e = ents[0]
            setCustomer({ softech_pic: e.pic, name: e.name, personcode: e.personcode })
          }
        }).catch(() => setEntities([]))
    }, 250)
    return () => clearTimeout(t)
  }, [branch, custType, entityQuery])  // eslint-disable-line

  // select an إسم العميل entity → set the customer (pic/name/personcode drive discount + write)
  const selectEntity = (e) => {
    setCustomer(e ? { softech_pic: e.pic, name: e.name, personcode: e.personcode } : null)
  }

  // SOFTECH-style suggested discounts (re-fetch when the item set / channel / branch changes)
  const _codes = lines.map(l => l.softech_itemcode).filter(Boolean).join(',')
  const _personcode = customer?.personcode || ''
  useEffect(() => {
    if (!branch || !_codes) { setSuggest({ map: {}, caps: {}, ceiling: null }); return }
    api.get('/pos-orders/discount-suggest/',
      { params: { branch: Number(branch), channel, items: _codes, personcode: _personcode || undefined } })
      .then(({ data }) => {
        setSuggest({ map: data.suggestions || {}, caps: data.caps || {}, ceiling: data.ceiling })
        // Reconcile EVERY non-manual line's discount with the CURRENT channel (never a hand-set %):
        //   • contract/insurance → the contracted rate (server-capped)
        //   • retail (cash/delivery/permanent/…) → 0. Cap-only: NOTHING auto-applies, and the
        //     point/loyalty system NEVER discounts the line. Resetting to 0 also clears any stale
        //     discount left over from a previous channel/customer — that was the "conflict".
        const supplied = data.suggestions || {}
        const perItemCap = code => {
          const c = data.caps?.[code]
          if (c != null) return Number(c)
          return data.ceiling != null ? Number(data.ceiling) : 100
        }
        setLines(prev => prev.map(l => {
          const cv = perItemCap(l.softech_itemcode)
          if (l.disc_manual)   // keep the hand-set %, but never above the current cap
            return Number(l.cust_discp) > cv ? { ...l, cust_discp: cv } : l
          const r = supplied[l.softech_itemcode]
          const val = (r != null) ? Math.min(Number(r), cv) : 0
          return Number(l.cust_discp) !== val ? { ...l, cust_discp: val } : l
        }))
      }).catch(() => {})
  }, [branch, channel, _codes, _personcode])  // eslint-disable-line

  // per-contract "Contract Emp. Data" field spec — which claim fields to show + their custom labels
  // (SOFTECH motalba_fields, keyed by the contract personcode). Fetched when a contract customer is set.
  useEffect(() => {
    if (!CLAIM_CHANNELS.includes(channel) || !branch || !_personcode) { setContractFields(null); return }
    api.get('/pos-orders/contract-fields/', { params: { branch: Number(branch), customer: _personcode } })
       .then(({ data }) => setContractFields(Array.isArray(data.fields) ? data.fields : null))
       .catch(() => setContractFields(null))
  }, [branch, channel, _personcode])

  // loyalty / points panel for the selected customer
  useEffect(() => {
    if (!customer?.id) { setLoyalty(null); return }
    api.get(`/loyalty/customers/${customer.id}/account/`).then(({ data }) => setLoyalty(data)).catch(() => setLoyalty(null))
  }, [customer?.id])  // eslint-disable-line

  // PIC points: SOFTECH earns points per-item at the cashier's finalization (not reproducible
  // read-only — see apps/pos_orders/points.py). We surface channel-eligibility + live enrollment
  // only (no fabricated figure), refreshed when the effective PIC or channel changes.
  const _picForPoints = picCustomer?.softech_pic || customer?.softech_pic || ''
  useEffect(() => {
    if (!_picForPoints) { setPointsInfo({ eligible: CHANNELS_EARN.includes(channel), enrolled: false }); return }
    api.get('/pos-orders/points-preview/', { params: { channel, pic: _picForPoints } })
      .then(({ data }) => setPointsInfo({ eligible: !!data.eligible, enrolled: !!data.enrolled }))
      .catch(() => setPointsInfo({ eligible: CHANNELS_EARN.includes(channel), enrolled: false }))
  }, [_picForPoints, channel])  // eslint-disable-line

  // queued/offline indicator — poll the count of orders awaiting connectivity
  const refreshQueue = useCallback(() => {
    api.get('/pos-orders/queue-status/', { params: branch ? { branch: Number(branch) } : {} })
      .then(({ data }) => setQueueStatus(data)).catch(() => {})
  }, [branch])
  useEffect(() => {
    refreshQueue()
    const t = setInterval(refreshQueue, 20000)
    return () => clearInterval(t)
  }, [refreshQueue])

  // Frequently-Bought-Together upsell — fetched from apps/recommendations FBT engine for
  // the catalog items in the cart, merged/de-duped, excluding what's already added.
  const _itemPks = lines.map(l => l.item).filter(Boolean).join(',')
  useEffect(() => {
    const ids = lines.map(l => l.item).filter(Boolean).slice(0, 6)
    if (!ids.length) { setFbt([]); return }
    const inCart = new Set(lines.map(l => String(l.softech_itemcode)))
    Promise.all(ids.map(id =>
      api.get('/recommendations/fbt/for-item/', { params: { item_id: id, limit: 6 } })
        .then(({ data }) => (Array.isArray(data) ? data : [])).catch(() => [])
    )).then(lists => {
      const best = new Map()
      for (const list of lists) for (const r of list) {
        if (inCart.has(String(r.softech_id))) continue
        const prev = best.get(r.softech_id)
        if (!prev || r.score > prev.score) best.set(r.softech_id, r)
      }
      setFbt([...best.values()].sort((a, b) => b.score - a.score).slice(0, 8))
    })
  }, [_itemPks])  // eslint-disable-line

  const isClaim = CLAIM_CHANNELS.includes(channel)
  // Resolved Contract-Emp-Data fields to render: the live per-contract spec if loaded (only the
  // enabled fields, with each contract's custom label), else the static 12 std. defaults.
  const empDataFields = useMemo(() => {
    if (contractFields != null) {
      return contractFields.map(f => ({ key: f.column, label: f.label_ar || f.label_en || f.column,
                                        type: f.is_date ? 'date' : undefined }))
    }
    return CONTRACT_EMP_FIELDS
  }, [contractFields])
  // channels that require a separate individual PIC customer (SOFTECH: Home Delivery must
  // provide a PIC). The account (Home Delivery Customer) is the إسم العميل entity; the PIC is
  // an individual picked from the directory.
  const needsPicCustomer = POS_LIMITS.PIC_REQUIRED.includes(channel)
  const customerType = typeCfg?.label || CHANNELS.find(c => c.value === channel)?.label || ''

  // a PIC individual only makes sense for its channel — drop it when the channel changes away
  useEffect(() => { if (!POS_LIMITS.PIC_REQUIRED.includes(channel)) setPicCustomer(null) }, [channel])

  const totals = useMemo(() => {
    let gross = 0, discount = 0, net = 0, tax = 0
    for (const l of lines) {
      const price = Number(l.item_sale_price || 0)
      const qty = Number(l.qty || 0)
      const disc = Number(l.cust_discp || 0)
      const lineGross = price * qty
      const lineNet = +(price * (1 - disc / 100)).toFixed(2) * qty
      gross += lineGross
      discount += lineGross - lineNet
      net += lineNet
      const tp = Number(l.sale_tax_pct || 0)
      if (tp) tax += lineNet - lineNet / (1 + tp / 100)
    }
    net = Math.max(0, net - Number(changeDiscount || 0))
    const paid = tenders.reduce((s, t) => s + Number(t.amount || 0) * Number(t.exchange_rate || 1), 0)
    // خصم العميل % — the effective customer discount rate over the gross
    const custDiscPct = gross > 0 ? (discount / gross) * 100 : 0
    // ما يسدده المريض — contract/insurance patient co-pay; blank ⇒ patient pays the full net.
    // The remainder (net − patient share) is what gets billed to the contract company (the claim).
    const patientPays = isClaim
      ? (patientPayment === '' ? net : Math.min(Number(patientPayment || 0), net))
      : net
    const claimAmount = Math.max(0, net - patientPays)
    return {
      gross: gross.toFixed(2), discount: discount.toFixed(2), tax: tax.toFixed(2),
      net: net.toFixed(2), paid: paid.toFixed(2), change: (paid - net).toFixed(2),
      custDiscPct: custDiscPct.toFixed(2), patientPays: patientPays.toFixed(2),
      claimAmount: claimAmount.toFixed(2),
    }
  }, [lines, tenders, changeDiscount, isClaim, patientPayment])


  // ── auto-accommodate on channel change ──────────────────────────────────────
  // Switching to a collect-now channel (نقدى/توصيل) converts any leftover آجل tender to
  // cash, so the order never carries a credit line the channel can't accept. This is the
  // "change one step → the others accustom" behaviour, applied to payment.
  useEffect(() => {
    if (channel === 'cash' || channel === 'delivery') {
      setTenders(prev => prev.some(t => t.pay_type === 'credit')
        ? prev.map(t => t.pay_type === 'credit' ? { ...t, pay_type: 'cash' } : t) : prev)
    }
  }, [channel])

  // ── workflow guidance engine ────────────────────────────────────────────────
  // A pure, order-independent derivation of the transaction "story": each step's status
  // is computed from the current state (not a fixed sequence), so the operator can enter
  // things in any order and the steps light up as their prerequisites are met. `advisories`
  // are reactive, non-blocking nudges/warnings that appear and clear as the state changes.
  const workflow = useMemo(() => {
    const picRequired = isClaim || POS_LIMITS.PIC_REQUIRED.includes(channel)
    // delivery is satisfied only when the individual PIC customer is chosen (not just the account)
    const hasCustomer = needsPicCustomer ? !!(picCustomer?.softech_pic) : !!(customer?.softech_pic)
    const hasItems = lines.some(l => Number(l.qty) > 0)
    const claimReady = !!(claim.patientname && (!picRequired || hasCustomer))
    const anyTender = tenders.some(t => Number(t.amount) > 0)
    const balanced = anyTender && Math.abs(Number(totals.paid) - Number(totals.net)) < 0.01
    const _cap = r => (suggest.ceiling != null ? Math.min(Number(r), Number(suggest.ceiling)) : Number(r))

    const mk = (key, label, icon, status, hint, tab) => ({ key, label, icon, status, hint, tab })
    const steps = [
      mk('channel', customerType || 'القناة والعميل', '🧭', custType ? 'done' : 'active',
         custType ? null : 'اختر نوع العميل', 'header'),
      mk('seller', 'مسؤول البيع', '👤', salesperson ? 'done' : 'todo',
         salesperson ? null : 'حدد البائع', 'header'),
      mk('customer', 'العميل (PIC)', '🪪',
         !picRequired ? (hasCustomer ? 'done' : 'skip') : (hasCustomer ? 'done' : 'blocked'),
         picRequired && !hasCustomer ? 'مطلوب تحديد العميل لهذه القناة' : null, 'header'),
      mk('items', 'الأصناف', '💊', hasItems ? 'done' : 'active',
         hasItems ? null : 'ابدأ بإضافة الأصناف', 'items'),
    ]
    if (isClaim)
      steps.push(mk('claim', 'بيانات التعاقد', '📋', claimReady ? 'done' : 'blocked',
         claimReady ? null : 'أدخل بيانات المريض', 'contract'))
    steps.push(mk('payment', 'السداد', '💵', !hasItems ? 'todo' : (balanced ? 'done' : 'todo'),
       hasItems && !balanced ? 'وازن السداد مع الصافي' : null, 'payment'))

    const advisories = []
    if (picRequired && !hasCustomer)
      advisories.push({ level: 'warn', text: `قناة «${customerType}» تتطلب تحديد العميل (PIC).`, tab: 'header' })
    const pendingDisc = lines.filter(l => {
      const r = suggest.map?.[l.softech_itemcode]
      return r != null && !l.disc_manual && Math.abs(Number(l.cust_discp) - _cap(r)) > 0.001
    })
    if (pendingDisc.length)
      advisories.push({ level: 'info', text: `خصم مقترح متاح لـ ${pendingDisc.length} صنف — اضغط للتطبيق`, action: 'applyAllSuggested', tab: 'items' })
    if (lines.some(l => Number(l.qty) > POS_LIMITS.MAX_QTY_LINE))
      advisories.push({ level: 'error', text: `صنف يتجاوز الحد الأقصى للكمية (${POS_LIMITS.MAX_QTY_LINE}).`, tab: 'items' })
    if (Number(changeDiscount || 0) > POS_LIMITS.MAX_FAKKA)
      advisories.push({ level: 'error', text: `خصم الفكة يتجاوز الحد (${POS_LIMITS.MAX_FAKKA} جنيه).`, tab: 'header' })
    if (docKind === 'return' && !returnInvoice)
      advisories.push({ level: 'warn', text: 'المرتجع يتطلب رقم الفاتورة الأصلية.', tab: 'header' })
    if (hasItems && anyTender && !balanced)
      advisories.push({ level: 'info', text: `فرق السداد ${money(Number(totals.paid) - Number(totals.net))} — عدّل مبالغ السداد.`, tab: 'payment' })

    const doneCount = steps.filter(s => s.status === 'done' || s.status === 'skip').length
    const progress = Math.round((doneCount / steps.length) * 100)
    const next = steps.find(s => s.status === 'blocked') ||
                 steps.find(s => s.status === 'active') ||
                 steps.find(s => s.status === 'todo') || null
    return { steps, advisories, progress, next, ready: advisories.every(a => a.level !== 'error') && hasItems }
  }, [channel, custType, customerType, customer, salesperson, lines, tenders, claim, totals,
      isClaim, docKind, returnInvoice, changeDiscount, suggest, needsPicCustomer, picCustomer])

  const _newLine = (item, extra = {}) => ({
    item: item.item_id || item.id || null,   // catalog PK (widget sends `id`, favorites send `item_id`)
    softech_itemcode: item.softech_id,
    barcode: item.barcode || '',
    item_name: item.name,
    available_qty: item.qty_at_branch ?? null,     // رصيد متاح
    available_expiry_qty: null,                     // رصيد صلاحية متاح (batch qty)
    item_expiry: null,                              // ت الصلاحية
    batchno: '',                                    // رقم القطعة أو الباتش
    bonus: 0,                                       // العبوة (bonus qty)
    qty: 1,                                         // الكمية (بالعبوات — عدد عشرى للبيع الجزئى)
    // qty is in PACKS, so the base price is the PACK price (SOFTECH items.itemsaleprice).
    // Selling a fraction of a pack (e.g. 0.4) prices as pack_price × 0.4. The live-pricing
    // path already reads the branch pack price; this keeps the offline default consistent.
    item_sale_price: item.pack_price || item.unit_price || 0,  // سعر العبوة (per pack)
    pkg_price: item.pack_price || 0,                // Pkg Price / سعر العبوة
    unit_price: item.unit_price || 0,               // بيع الوحدة (reference)
    sale_tax_pct: 0,                                // ض ق مضافة %
    cust_discp: 0,                                  // خصم %
    is_reservation: false,
    ...extra,
  })

  const addItem = useCallback(async (item) => {
    if (!item) return
    setMsg('')
    // no branch yet → still add the line so the cart can be built in ANY order; availability
    // and batch/expiry resolve once a branch is chosen. (Never drop the selected item.)
    if (!branch) {
      setLines(prev => [...prev, _newLine(item)])
      setMsg(`أُضيف "${item.name}" — اختر الفرع لعرض الرصيد والتشغيلة.`)
      return
    }
    try {
      const { data } = await api.get('/pos-orders/batches/', {
        // pass the SELECTED store — batches live in stkbalexpiry keyed by storecode, NOT the
        // branch code. Without this the read hits the wrong store and everything looks OOS.
        params: { branch: Number(branch), item: item.softech_id, store: storeCode || undefined },
      })
      const avail = item ? { ...item, qty_at_branch: data.total } : item
      if (data.out_of_stock || !data.batches?.length) {
        setLines(prev => [...prev, _newLine(avail, { is_reservation: true })])
        setMsg(`"${item.name}" غير متوفر بالمخزن ${data.store || storeCode || ''} — أُضيف كحجز.`)
      } else {
        setBatchModal({ item: avail, batches: data.batches, total: data.total,
                        picks: data.batches.map(() => ''), need: 1, shortfall: 0 })
      }
    } catch (e) {
      setLines(prev => [...prev, _newLine(item)])
      const why = e.response?.data?.detail
      setMsg(`أُضيف "${item.name}" — تعذّر قراءة الأرصدة${why ? ': ' + why : ''} (بدون تشغيلة).`)
    }
  }, [branch, storeCode])

  const setBatchNeed = useCallback((v) => setBatchModal(m => m ? { ...m, need: v } : m), [])

  // FEFO auto-fill: distribute the requested qty across batches starting from the
  // nearest expiry (batches arrive sorted ascending) until the need is met.
  const fefoFill = useCallback(() => {
    setBatchModal(m => {
      if (!m) return m
      let need = Number(m.need || 0)
      if (!(need > 0)) { setMsg('أدخل الكمية المطلوبة أولاً'); return m }
      const picks = m.batches.map(b => {
        if (need <= 1e-9) return ''
        const take = Math.min(need, Number(b.qty))
        need = +(need - take).toFixed(5)
        return take > 0 ? String(take) : ''
      })
      if (need > 1e-9) setMsg(`المتاح أقل من المطلوب بمقدار ${need} — يمكن إضافة الباقى كحجز.`)
      return { ...m, picks, shortfall: need > 1e-9 ? need : 0 }
    })
  }, [])

  const confirmBatchPick = useCallback(() => {
    setBatchModal(m => {
      if (!m) return null
      const chosen = m.batches.map((b, i) => ({ b, q: Number(m.picks[i] || 0) })).filter(x => x.q > 0)
      const over = chosen.find(x => x.q > x.b.qty)
      if (over) { setMsg(`الكمية من تشغيلة ${over.b.expiry} تتجاوز المتاح (${over.b.qty}).`); return m }
      const extra = []
      if (chosen.length) {
        extra.push(...chosen.map(({ b, q }) =>
          _newLine(m.item, { qty: q, item_expiry: b.expiry, batchno: b.batchno || '', available_expiry_qty: b.qty })))
      }
      // any shortfall after FEFO → a reservation line for the remainder
      if (m.shortfall > 1e-9) extra.push(_newLine(m.item, { qty: m.shortfall, is_reservation: true }))
      // confirmed without picking any batch → still add the item (qty = need) so it never vanishes
      if (!extra.length) extra.push(_newLine(m.item, { qty: Number(m.need) || 1 }))
      setLines(prev => [...prev, ...extra])
      return null
    })
  }, [])

  // per-item discount ceiling: caps[code] (= min(item posdiscp, seller max) for retail,
  // seller max for contract), else the global seller ceiling, else 100.
  const discCapFor = code => {
    const c = suggest.caps?.[code]
    if (c != null) return Number(c)
    return suggest.ceiling != null ? Number(suggest.ceiling) : 100
  }
  const setLine = (i, k, v) => {
    if (k === 'cust_discp') {
      const cap = discCapFor(lines[i]?.softech_itemcode)
      if (v !== '' && !isNaN(Number(v)) && Number(v) > cap) {
        setMsg(`الحد الأقصى للخصم لهذا الصنف ${cap}%`)
        v = cap
      }
    }
    setLines(prev => prev.map((l, idx) =>
      idx === i ? { ...l, [k]: v, ...(k === 'cust_discp' ? { disc_manual: true } : {}) } : l))
  }
  const removeLine = i => { setLines(prev => prev.filter((_, idx) => idx !== i)); setSelected(-1) }
  const setTender = (i, k, v) => setTenders(prev => prev.map((t, idx) => idx === i ? { ...t, [k]: v } : t))
  const addTender = () => setTenders(p => [...p, blankTender()])
  const removeTender = i => setTenders(p => p.length > 1 ? p.filter((_, x) => x !== i) : p)

  // ما يسدده المريض — for contract/insurance this is the patient's cash co-pay. Setting it
  // rebuilds the tenders (cash co-pay + credit remainder billed to the contract), which is
  // what the server turns into patient_payment (pricing.split_payment).
  const setPatientCopay = (v) => {
    setPatientPayment(v)
    if (!isClaim) return
    const net = Number(totals.net)
    const pay = v === '' ? net : Math.min(Math.max(0, Number(v || 0)), net)
    const rest = Math.max(0, +(net - pay).toFixed(2))
    const next = [{ ...blankTender(), pay_type: 'cash', amount: +pay.toFixed(2) }]
    if (rest > 0) next.push({ ...blankTender(), pay_type: 'credit', amount: rest })
    setTenders(next)
  }

  const numpad = useCallback((key) => {
    if (selected < 0) { setMsg('اختر سطراً أولاً'); return }
    const field = numMode === 'qty' ? 'qty' : numMode === 'disc' ? 'cust_discp' : 'item_sale_price'
    setLines(prev => prev.map((l, idx) => {
      if (idx !== selected) return l
      let cur = String(l[field] ?? '')
      if (key === 'back') cur = cur.slice(0, -1)
      else if (key === 'C') cur = ''
      else if (key === '.') cur = cur.includes('.') ? cur : (cur || '0') + '.'
      else if (key === '+/-') cur = cur.startsWith('-') ? cur.slice(1) : '-' + cur
      else cur = (cur === '0' ? '' : cur) + key
      if (field === 'cust_discp' && cur !== '' && !isNaN(Number(cur))) {
        const cap = discCapFor(l.softech_itemcode)
        if (Number(cur) > cap) cur = String(cap)
        return { ...l, cust_discp: cur, disc_manual: true }
      }
      return { ...l, [field]: cur }
    }))
  }, [selected, numMode, suggest])  // eslint-disable-line

  function clientValidate(live) {
    const out = []
    if (!branch) out.push('اختر الفرع.')
    if (docKind === 'return' && !returnInvoice) out.push('رقم الفاتورة الأصلية مطلوب للمرتجع.')
    if (isClaim && !(customer?.softech_pic)) out.push('عميل التعاقد/التأمين يتطلب تحديد العميل (PIC).')
    if (isClaim && !claim.patientname) out.push('بيانات المريض مطلوبة (تبويب بيانات التعاقد).')
    // Home-Delivery needs an individual PIC customer — required only to SAVE (live), not preview.
    if (live && needsPicCustomer && !(picCustomer?.softech_pic))
      out.push('التوصيل المنزلى يتطلب تحديد عميل PIC (بحث/اختيار أو إضافة) قبل الحفظ.')
    if (Number(changeDiscount || 0) > POS_LIMITS.MAX_FAKKA)
      out.push(`خصم الفكة يتجاوز الحد المسموح (${money(POS_LIMITS.MAX_FAKKA)} جنيه).`)
    if (!lines.length) out.push('أضف صنفاً واحداً على الأقل.')
    lines.forEach((l, i) => {
      const n = i + 1
      if (!(Number(l.qty) > 0)) out.push(`سطر ${n}: الكمية يجب أن تكون أكبر من صفر.`)
      else if (Number(l.qty) > POS_LIMITS.MAX_QTY_LINE)
        out.push(`سطر ${n}: الكمية تتجاوز الحد الأقصى (${POS_LIMITS.MAX_QTY_LINE}).`)
      const d = Number(l.cust_discp)
      if (!(d >= 0 && d <= 100)) out.push(`سطر ${n}: الخصم يجب أن يكون بين 0 و 100.`)
      else {
        const cap = discCapFor(l.softech_itemcode)
        if (d > cap) out.push(`سطر ${n}: الخصم (${d}%) يتجاوز الحد المسموح لهذا الصنف (${cap}%).`)
      }
    })
    const pays = tenders.filter(t => Number(t.amount) > 0)
    pays.forEach((t, i) => {
      if (t.pay_type === 'credit' && (channel === 'cash' || channel === 'delivery'))
        out.push(`سداد ${i + 1}: لا يُسمح بالآجل في قناة نقدى/توصيل.`)
    })
    if (live) {
      const sum = pays.reduce((s, t) => s + Number(t.amount) * Number(t.exchange_rate || 1), 0)
      if (Math.abs(sum - Number(totals.net)) > 0.01)
        out.push(`مجموع السداد (${money(sum)}) لا يساوي صافي الأمر (${money(totals.net)}).`)
    }
    return out
  }

  const reset = () => {
    setLines([]); setSelected(-1); setTenders([blankTender()]); setCustomer(null); setPicCustomer(null)
    setDoctorName(''); setDoctorCode(''); setRx(null); setReturnInvoice('')
    setClaim(blankClaim()); setNotes(''); setChangeDiscount(0); setPatientPayment(''); setPlan(null); setActiveTab('items')
  }

  // ── discount suggestions: apply the contracted rate (capped at the seller ceiling) ──
  const _cap = v => suggest.ceiling != null ? Math.min(Number(v), Number(suggest.ceiling)) : Number(v)
  const applySuggested = (i) => {
    const code = lines[i]?.softech_itemcode
    const r = suggest.map[code]
    if (r == null) { setMsg('لا يوجد خصم متعاقد لهذا الصنف'); return }
    setLine(i, 'cust_discp', _cap(r))
  }
  const applyAllSuggested = () => {
    let n = 0
    setLines(prev => prev.map(l => {
      const r = suggest.map[l.softech_itemcode]
      if (r == null) return l
      n++; return { ...l, cust_discp: _cap(r) }
    }))
    setMsg(n ? `طُبّق الخصم المتعاقد على ${n} صنف` : 'لا توجد خصومات متعاقدة')
  }

  // ── held / parked orders (localStorage) ──
  const _persistParked = (list) => { setParked(list); localStorage.setItem('pos_parked', JSON.stringify(list)) }
  const parkOrder = () => {
    if (!lines.length) { setMsg('لا يوجد ما يُعلّق'); return }
    const snap = { id: Date.now(), at: new Date().toISOString(),
      label: customer?.name || `سلة ${parked.length + 1}`, total: totals.net,
      channel, docKind, customer, lines, tenders, claim }
    _persistParked([snap, ...parked]); reset(); setMsg('تم تعليق السلة (Park)')
  }
  const recallOrder = (id) => {
    const s = parked.find(p => p.id === id); if (!s) return
    setChannel(s.channel); setDocKind(s.docKind); setCustomer(s.customer || null)
    setLines(s.lines || []); setTenders(s.tenders || [blankTender()]); setClaim(s.claim || blankClaim())
    _persistParked(parked.filter(p => p.id !== id)); setMsg('تم استرجاع السلة')
  }
  const deleteParked = (id) => _persistParked(parked.filter(p => p.id !== id))

  // ── favorites quick grid + barcode scan ──
  const _favShape = it => ({ item_id: it.item_id || it.id || null, softech_id: it.softech_id,
    name: it.name, pack_price: it.pack_price, unit_price: it.unit_price, barcode: it.barcode })
  const isFavorite = code => favorites.some(f => f.softech_id === code)
  const toggleFavorite = (it) => {
    const next = isFavorite(it.softech_id)
      ? favorites.filter(f => f.softech_id !== it.softech_id)
      : [_favShape(it), ...favorites].slice(0, 24)
    setFavorites(next); localStorage.setItem('pos_favorites', JSON.stringify(next))
  }
  const addByBarcode = async (code) => {
    if (!code) return
    try {
      const { data } = await api.get('/items/', { params: { search: code, page_size: 2 } })
      const r = data.results || data
      if (r.length === 1) addItem(_favShape(r[0]))
      else if (r.length > 1) setMsg('أكثر من صنف لنفس الكود — استخدم البحث')
      else setMsg('لم يُعثر على صنف بهذا الباركود')
    } catch { setMsg('تعذّر البحث بالباركود') }
  }

  // supervisor 'flush now' — retry the queued orders immediately
  const flushNow = async (includeFailed = false) => {
    setBusy(true); setMsg('')
    try {
      const { data } = await api.post('/pos-orders/flush/', { include_failed: includeFailed })
      setMsg(`الطابور: أُرسل ${data.pushed} · لا يزال ${data.still_queued} · فشل ${data.failed}`)
    } catch (e) {
      setMsg('تعذّر تفريغ الطابور: ' + (e.response?.data?.detail || e.message))
    } finally { setBusy(false); refreshQueue() }
  }

  async function submit(live) {
    setMsg(''); setPlan(null); setErrs([])
    const ce = clientValidate(live)
    if (ce.length) { setErrs(ce); return }
    if (live && !window.confirm('سيتم إرسال أمر بيع فعلي إلى شاشة الكاشير في SOFTECH. هل أنت متأكد؟')) return
    setBusy(true)
    try {
      // stable idempotency token for THIS attempt — if the request is queued offline and
      // replayed, the backend get-or-create returns the same order instead of duplicating.
      const clientToken = (crypto?.randomUUID?.() ||
        `${Date.now()}-${Math.random().toString(16).slice(2)}`)
      const payload = {
        client_token: clientToken,
        branch: Number(branch), channel, doc_kind: docKind, store_code: storeCode || undefined,
        // the individual PIC (delivery) drives the PIC + link; the account name is the إسم العميل
        customer: picCustomer?.id || customer?.id || null,
        softech_pic: picCustomer?.softech_pic || customer?.softech_pic || '',
        customer_name: customer?.name || picCustomer?.name || 'Walk-In Customer',
        seller_usercode: salesperson || undefined,   // مسئول البيع — usercode ONLY to the ERP
        referral_doctor_name: doctorName, referral_doctor_code: doctorCode,
        return_of_invoice: docKind === 'return' && returnInvoice ? Number(returnInvoice) : null,
        // SOFTECH header extras (now real columns)
        doc_date: docDate || null, change_discount: Number(changeDiscount || 0),
        payment_method: paymentMethod,
        // ما يسدده المريض flows via the tenders (cash co-pay + credit remainder); the server
        // derives patient_payment from them — see setPatientCopay / pricing.split_payment.
        alt_price: altPrice, sell_at_cost: sellAtCost,
        print_receipt: printReceipt, items_reservation: itemsReservation,
        notes,
        ...(isClaim && claim.patientname ? { claim } : {}),
        lines: lines.map(l => ({
          item: l.item, softech_itemcode: l.softech_itemcode, item_name: l.item_name,
          qty: Number(l.qty), item_sale_price: Number(l.item_sale_price),
          cust_discp: Number(l.cust_discp), sale_tax_pct: Number(l.sale_tax_pct || 0),
          item_expiry: l.item_expiry || null,
          barcode: l.barcode || '', bonus_qty: Number(l.bonus || 0),
          pkg_price: Number(l.pkg_price || 0), batchno: l.batchno || '',
          is_reservation: !!l.is_reservation,
        })),
      }
      const { data: order } = await api.post('/pos-orders/', payload)
      // send FULL tender objects so currency/rate/cheque/card/internal-serial persist
      await api.post(`/pos-orders/${order.id}/ready/`, {
        tenders: tenders.filter(t => Number(t.amount) > 0).map(t => ({
          pay_type: t.pay_type, amount: Number(t.amount),
          currency: t.currency, exchange_rate: Number(t.exchange_rate || 1),
          card_brand: t.card_type || null, cheque_date: t.due_date || null,
          cheque_card_no: t.cheque_card_no || '', internal_payserial: t.internal_payserial || '',
        })),
      })
      const body = live ? { dry_run: false, confirm: true } : { dry_run: true }
      const { data: res } = await api.post(`/pos-orders/${order.id}/push/`, body)
      if (res.queued) {
        setMsg(`⏳ الفرع غير متصل — حُفظ الأمر #${order.id} في الطابور وسيُرسل تلقائياً عند عودة الاتصال.`)
        reset()
      } else if (res.live) {
        setMsg(`✅ تم الإرسال إلى الكاشير — مستند SOFTECH ${res.docnumber || res.softech_docnumber || ''} (أمر #${order.id}).`)
        reset()
      } else {
        setPlan(res.plan)
        setMsg(`أمر #${order.id} — وضع تجريبي (لم يُكتب في SOFTECH). معاينة الحمولة بالأسفل.`)
      }
    } catch (e) {
      const d = e.response?.data
      if (d?.errors) {
        const flat = []
        for (const [k, v] of Object.entries(d.errors)) {
          if (Array.isArray(v)) v.forEach(x => flat.push(typeof x === 'object' ? JSON.stringify(x) : `${k}: ${x}`))
          else flat.push(`${k}: ${v}`)
        }
        setErrs(flat); setMsg(d.detail || 'فشل التحقق من البيانات.')
      } else setMsg('خطأ: ' + (d?.detail || e.message))
    } finally { setBusy(false); refreshQueue() }
  }

  return {
    branches, ref,
    branch, setBranch, storeCode, setStoreCode, docKind, setDocKind, channel, setChannel,
    isClaim, customerType, customer, setCustomer, docDate, setDocDate, dispenseSerial,
    picCustomer, setPicCustomer, needsPicCustomer,
    salesperson, setSalesperson, salespersonName, salespeople, salespersonQuery, setSalespersonQuery, selectSalesperson,
    paymentMethod, setPaymentMethod, changeDiscount, setChangeDiscount,
    patientPayment, setPatientPayment, setPatientCopay,
    notes, setNotes, returnInvoice, setReturnInvoice,
    altPrice, setAltPrice, sellAtCost, setSellAtCost, printReceipt, setPrintReceipt,
    itemsReservation, setItemsReservation,
    doctorName, setDoctorName, doctorCode, setDoctorCode, rx, setRx, claim, setClaim,
    empDataFields, contractFields,
    lines, setLine, removeLine, addItem, selected, setSelected, numMode, setNumMode, numpad,
    batchModal, setBatchModal, confirmBatchPick, setBatchNeed, fefoFill,
    suggest, applySuggested, applyAllSuggested,
    loyalty, pointsInfo, parked, parkOrder, recallOrder, deleteParked,
    favorites, isFavorite, toggleFavorite, addByBarcode,
    fbt, addFbt: (rec) => addByBarcode(rec.softech_id),
    queueStatus, flushNow, refreshQueue,
    // two-level customer + branch stores
    custTypes, custType, setCustType, typeCfg,
    entities, entityQuery, setEntityQuery, selectEntity, stores,
    tenders, setTender, addTender, removeTender, totals, activeTab, setActiveTab,
    workflow,
    submit, reset, busy, plan, setPlan, msg, setMsg, errs,
  }
}
