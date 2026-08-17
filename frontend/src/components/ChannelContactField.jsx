/**
 * ChannelContactField.jsx
 *
 * Smart contact-person / company name field that adapts its label and
 * autocomplete behaviour based on the selected sales channel.
 *
 * Channel behaviour:
 *   insurance / تأمين variants → label changes to "شركة التأمين / المؤمَّن"
 *                                  autocomplete from /insurance/clients/ + /insurance/subclients/
 *   All other channels          → label = "اسم التواصل"  (plain text, no autocomplete)
 *
 * Props:
 *   channel     — string  (reservation CHANNEL_CHOICES value: 'pickup'|'home_delivery'|'insurance'|...)
 *   value       — string  (controlled text value)
 *   onChange    — (string) => void
 *   onSuggestSelect — (suggestion: { name, id, type }) => void  (optional, called when a suggestion is clicked)
 *   required    — bool
 *   disabled    — bool
 *   label       — string | null  (override computed label)
 *   className   — extra wrapper classes
 */
import { useState, useEffect, useRef } from 'react'
import { insuranceApi } from '../api/client'

// Sub-channel values that trigger insurance/company autocomplete
// Includes both old values (backward compat) and new contract_subtype values
const INSURANCE_SUBTYPES = new Set([
  // new contract_subtype values
  'health_insurance', 'taakodat', 'compensation',
  // legacy channel values (kept for backward compat)
  'insurance', 'tpa', 'takaful', '15', '16', '17',
])

function isInsuranceChannel(channel, contractSubtype) {
  if (!channel) return false
  const c = String(channel).toLowerCase()
  // Old-style channel value
  if (INSURANCE_SUBTYPES.has(c) || c.includes('insurance') || c.includes('تأمين')) return true
  // New-style: contract_sales with insurance/compensation subtype
  if (c === 'contract_sales' && contractSubtype) {
    return INSURANCE_SUBTYPES.has(contractSubtype)
  }
  return false
}

function computeLabel(channel) {
  if (isInsuranceChannel(channel)) return 'شركة التأمين / المؤمَّن'
  return 'اسم التواصل'
}

function computePlaceholder(channel) {
  if (isInsuranceChannel(channel)) return 'اسم شركة التأمين أو المريض المؤمَّن...'
  return 'الاسم الكامل أو اسم جهة التواصل...'
}

// ── Insurance suggestion row ──────────────────────────────────────────────────

function SuggestionRow({ suggestion, onSelect }) {
  return (
    <div
      className="px-3 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-50 last:border-0 transition-colors"
      onMouseDown={e => { e.preventDefault(); onSelect(suggestion) }}
    >
      <div className="font-semibold text-sm text-gray-900">{suggestion.name}</div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${
          suggestion.type === 'client'
            ? 'text-blue-700 bg-blue-50 border-blue-200'
            : 'text-teal-700 bg-teal-50 border-teal-200'
        }`}>
          {suggestion.type === 'client' ? 'عميل رئيسي' : 'عميل فرعي'}
        </span>
        {suggestion.code && (
          <span className="text-[10px] font-mono text-gray-400">{suggestion.code}</span>
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ChannelContactField({
  channel          = '',
  contractSubtype  = '',   // NEW — pass contract_subtype for insurance detection
  value            = '',
  onChange,
  onSuggestSelect,
  required         = false,
  disabled         = false,
  label            = null,
  className        = '',
}) {
  const [suggestions, setSuggestions] = useState([])
  const [open,        setOpen]        = useState(false)
  const [loading,     setLoading]     = useState(false)
  const debounceRef     = useRef(null)
  const inputRef        = useRef(null)
  const dropRef         = useRef(null)
  const justSelectedRef = useRef(false)  // prevents re-search after suggestion pick

  const isInsurance = isInsuranceChannel(channel, contractSubtype)
  const displayLabel = label ?? computeLabel(channel)
  const displayPlaceholder = computePlaceholder(channel)

  // Load insurance suggestions when channel is insurance-type
  useEffect(() => {
    // Skip re-search if value was just set by a suggestion selection
    if (justSelectedRef.current) {
      justSelectedRef.current = false
      return
    }
    if (!isInsurance || !value || value.length < 2) {
      setSuggestions([])
      setOpen(false)
      return
    }
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const [clientsRes, subclientsRes] = await Promise.allSettled([
          insuranceApi.clients({ search: value, page_size: 6 }),
          insuranceApi.subclients({ search: value, page_size: 6 }),
        ])
        const clients    = (clientsRes.status === 'fulfilled'
          ? (clientsRes.value.data.results || clientsRes.value.data) : [])
          .map(c => ({ id: c.id, name: c.name || c.company_name, code: c.code, type: 'client' }))
        const subclients = (subclientsRes.status === 'fulfilled'
          ? (subclientsRes.value.data.results || subclientsRes.value.data) : [])
          .map(s => ({ id: s.id, name: s.name || s.subclient_name, code: s.code, type: 'subclient' }))
        setSuggestions([...clients, ...subclients].slice(0, 10))
        setOpen(true)
      } catch { setSuggestions([]) }
      finally { setLoading(false) }
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [value, isInsurance, channel, contractSubtype])

  // Close on outside click
  useEffect(() => {
    function handler(e) {
      if (
        dropRef.current && !dropRef.current.contains(e.target) &&
        inputRef.current && !inputRef.current.contains(e.target)
      ) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function handleSelect(suggestion) {
    justSelectedRef.current = true        // block the next useEffect run
    clearTimeout(debounceRef.current)     // cancel any pending debounce search
    onChange(suggestion.name)
    onSuggestSelect?.(suggestion)
    setSuggestions([])
    setOpen(false)
  }

  return (
    <div className={`space-y-1 ${className}`}>
      {/* Label */}
      <label className={`label flex items-center gap-1.5 ${required ? '' : ''}`}>
        {isInsurance && <span className="text-blue-500">🏥</span>}
        {displayLabel}
        {required && <span className="text-red-500">*</span>}
        {/* Channel indicator badge */}
        {isInsurance && (
          <span className="text-[10px] text-blue-600 bg-blue-50 border border-blue-200 px-1.5 py-0.5 rounded font-medium">
            تأمين
          </span>
        )}
      </label>

      {/* Input + dropdown */}
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          className={`input-field w-full disabled:bg-gray-100 disabled:cursor-not-allowed ${
            isInsurance ? 'border-blue-300 focus:ring-blue-400 focus:border-blue-400' : ''
          }`}
          placeholder={displayPlaceholder}
          value={value}
          onChange={e => { onChange(e.target.value); setOpen(true) }}
          onFocus={() => { if (suggestions.length > 0) setOpen(true) }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          disabled={disabled}
          autoComplete="off"
          dir="rtl"
        />
        {loading && (
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2">
            <span className="w-3.5 h-3.5 border-2 border-blue-200 border-t-blue-500 rounded-full animate-spin block" />
          </span>
        )}

        {/* Insurance suggestions dropdown */}
        {open && isInsurance && suggestions.length > 0 && (
          <div
            ref={dropRef}
            className="absolute z-30 w-full bg-white border border-blue-200 rounded-xl shadow-xl mt-1 max-h-52 overflow-y-auto"
          >
            {suggestions.map((s, i) => (
              <SuggestionRow key={`${s.type}-${s.id ?? i}`} suggestion={s} onSelect={handleSelect} />
            ))}
          </div>
        )}
      </div>

      {/* Hint for insurance channel */}
      {isInsurance && !value && (
        <p className="text-[11px] text-blue-400 flex items-center gap-1">
          🏥 اكتب اسم شركة التأمين أو المريض للبحث في قاعدة بيانات التأمين
        </p>
      )}
    </div>
  )
}
