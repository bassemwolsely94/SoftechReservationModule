import React, { useState, useEffect, useRef, useCallback } from 'react';
import { stockCountApi } from '../api/client';
import CanDo from '../components/CanDo';

// ── Constants ─────────────────────────────────────────────────────────────────

const DOCCODE_OPTIONS = [
  { value: 10,  label: '10  - مشتريات من الموردين' },
  { value: 25,  label: '25  - استلام تحويل وارد (فرع / مركز)' },
  { value: 50,  label: '50  - تسوية زيادة جرد' },
  { value: 80,  label: '80  - مبيعات حجوزات' },
  { value: 115, label: '115 - مبيعات' },
  { value: 120, label: '120 - مرتجعات للموردين' },
  { value: 125, label: '125 - تحويل صادر (إلى فرع / مركز)' },
  { value: 150, label: '150 - تسوية نقص جرد' },
];

const PRESETS = [
  { key: 'sold_today',      label: 'مبيعات اليوم',              doccodes: [115, 80], days: 0 },
  { key: 'returns_today',   label: 'مرتجعات للموردين اليوم',    doccodes: [120],     days: 0 },
  { key: 'received_hq',     label: 'استلام تحويل وارد',         doccodes: [25],      days: 7 },
  { key: 'purchased_today', label: 'مشتريات اليوم',             doccodes: [10],      days: 0 },
  { key: 'transferred_out', label: 'تحويلات صادرة',             doccodes: [125],     days: 7 },
  { key: 'full_branch',     label: 'جرد شامل للفرع',            doccodes: [],        days: 0 },
];

const STATUS_COLORS = {
  draft:          { bg: '#f3f4f6', text: '#374151', border: '#d1d5db' },
  snapshot_taken: { bg: '#eff6ff', text: '#1d4ed8', border: '#bfdbfe' },
  exported:       { bg: '#f0fdf4', text: '#15803d', border: '#bbf7d0' },
  uploaded:       { bg: '#fefce8', text: '#a16207', border: '#fde68a' },
  variance_ready: { bg: '#fff7ed', text: '#c2410c', border: '#fed7aa' },
  closed:         { bg: '#1f2937', text: '#f9fafb', border: '#374151' },
};

const STATUS_LABELS = {
  draft:          'مسودة',
  snapshot_taken: 'تم اللقطة',
  exported:       'تم التصدير',
  uploaded:       'تم الرفع',
  variance_ready: 'الفروق جاهزة',
  closed:         'مغلق',
};

const STATUS_STEPS = ['draft', 'snapshot_taken', 'exported', 'uploaded', 'variance_ready', 'closed'];

// ── Utility helpers ───────────────────────────────────────────────────────────

function today() {
  return new Date().toISOString().slice(0, 10);
}

function fmtQty(v) {
  if (v === null || v === undefined) return '—';
  return parseFloat(v).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 3 });
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Shared table cell styles ──────────────────────────────────────────────────

const th = {
  padding: '10px 12px',
  textAlign: 'right',
  fontWeight: 600,
  fontSize: 13,
  borderBottom: '1px solid #1e3a5f',
  whiteSpace: 'nowrap',
};

const td = {
  padding: '9px 12px',
  borderBottom: '1px solid #f3f4f6',
  fontSize: 13,
};

// ── WorkflowProgress ─────────────────────────────────────────────────────────

function WorkflowProgress({ status }) {
  const idx = STATUS_STEPS.indexOf(status);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, margin: '8px 0' }}>
      {STATUS_STEPS.map((step, i) => {
        const done   = i < idx;
        const active = i === idx;
        const color  = done ? '#10b981' : active ? '#3b82f6' : '#d1d5db';
        return (
          <React.Fragment key={step}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 60 }}>
              <div style={{
                width: 24, height: 24, borderRadius: '50%',
                background: color, color: '#fff',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 12, fontWeight: 'bold',
              }}>
                {done ? '✓' : i + 1}
              </div>
              <span style={{
                fontSize: 9,
                color: active ? '#1d4ed8' : done ? '#059669' : '#9ca3af',
                marginTop: 2, textAlign: 'center',
              }}>
                {STATUS_LABELS[step]}
              </span>
            </div>
            {i < STATUS_STEPS.length - 1 && (
              <div style={{ flex: 1, height: 2, background: done ? '#10b981' : '#e5e7eb', marginBottom: 16 }} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ── StatusBadge ───────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.draft;
  return (
    <span style={{
      padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600,
      background: c.bg, color: c.text, border: `1px solid ${c.border}`,
    }}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

// ── CreateSessionModal ────────────────────────────────────────────────────────

function CreateSessionModal({ onClose, onCreate }) {
  const [form, setForm] = useState({
    name: '', branch_code: '', mode: 'transaction',
    doccodes: [10, 25, 80],
    date_from: today(), date_to: today(),
    user_code_filter: '', category_filter: '',
    item_codes_filter: [], notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState('');

  function applyPreset(preset) {
    if (preset.key === 'full_branch') {
      setForm(f => ({ ...f, mode: 'full', doccodes: [], date_from: '', date_to: '' }));
    } else {
      const end = new Date();
      const start = new Date();
      start.setDate(start.getDate() - preset.days);
      setForm(f => ({
        ...f, mode: 'transaction', doccodes: preset.doccodes,
        date_from: start.toISOString().slice(0, 10),
        date_to:   end.toISOString().slice(0, 10),
      }));
    }
  }

  function toggleDoccode(val) {
    setForm(f => ({
      ...f,
      doccodes: f.doccodes.includes(val)
        ? f.doccodes.filter(d => d !== val)
        : [...f.doccodes, val],
    }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      const payload = { ...form };
      if (form.mode === 'full') { payload.doccodes = []; payload.date_from = null; payload.date_to = null; }
      const res = await stockCountApi.create(payload);
      onCreate(res.data);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || JSON.stringify(err.response?.data) || 'خطأ في الحفظ');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{ background: '#fff', borderRadius: 12, width: 'min(680px,95vw)', maxHeight: '90vh', overflowY: 'auto', padding: 32, direction: 'rtl' }}>
        <h2 style={{ margin: '0 0 20px', fontSize: 20 }}>إنشاء جلسة جرد جديدة</h2>

        {/* Presets */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 8 }}>بدء سريع:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {PRESETS.map(p => (
              <button key={p.key} onClick={() => applyPreset(p)} style={{
                padding: '6px 14px', borderRadius: 20, border: '1px solid #e5e7eb',
                background: '#f9fafb', cursor: 'pointer', fontSize: 13,
              }}>{p.label}</button>
            ))}
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div style={{ gridColumn: '1/-1' }}>
              <label style={{ fontSize: 13, fontWeight: 600 }}>اسم الجلسة *</label>
              <input required value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 10px', marginTop: 4, boxSizing: 'border-box' }} />
            </div>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600 }}>كود الفرع *</label>
              <input required value={form.branch_code} onChange={e => setForm(f => ({ ...f, branch_code: e.target.value }))}
                style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 10px', marginTop: 4, boxSizing: 'border-box' }} />
            </div>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600 }}>النوع</label>
              <select value={form.mode} onChange={e => setForm(f => ({ ...f, mode: e.target.value }))}
                style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 10px', marginTop: 4, boxSizing: 'border-box' }}>
                <option value="transaction">مبني على الحركات</option>
                <option value="full">جرد شامل</option>
                <option value="filtered">جرد مفلتر</option>
              </select>
            </div>
            {form.mode === 'transaction' && (
              <>
                <div>
                  <label style={{ fontSize: 13, fontWeight: 600 }}>من تاريخ</label>
                  <input type="date" value={form.date_from} onChange={e => setForm(f => ({ ...f, date_from: e.target.value }))}
                    style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 10px', marginTop: 4, boxSizing: 'border-box' }} />
                </div>
                <div>
                  <label style={{ fontSize: 13, fontWeight: 600 }}>إلى تاريخ</label>
                  <input type="date" value={form.date_to} onChange={e => setForm(f => ({ ...f, date_to: e.target.value }))}
                    style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 10px', marginTop: 4, boxSizing: 'border-box' }} />
                </div>
              </>
            )}
          </div>

          {form.mode === 'transaction' && (
            <div style={{ margin: '16px 0' }}>
              <label style={{ fontSize: 13, fontWeight: 600 }}>أكواد المستند</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
                {DOCCODE_OPTIONS.map(opt => (
                  <label key={opt.value} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: 13 }}>
                    <input type="checkbox" checked={form.doccodes.includes(opt.value)} onChange={() => toggleDoccode(opt.value)} />
                    {opt.label}
                  </label>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600 }}>فلتر كود المستخدم</label>
              <input value={form.user_code_filter} onChange={e => setForm(f => ({ ...f, user_code_filter: e.target.value }))}
                placeholder="اتركه فارغاً للكل"
                style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 10px', marginTop: 4, boxSizing: 'border-box' }} />
            </div>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600 }}>فلتر التصنيف</label>
              <input value={form.category_filter} onChange={e => setForm(f => ({ ...f, category_filter: e.target.value }))}
                placeholder="اتركه فارغاً للكل"
                style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 10px', marginTop: 4, boxSizing: 'border-box' }} />
            </div>
            <div style={{ gridColumn: '1/-1' }}>
              <label style={{ fontSize: 13, fontWeight: 600 }}>ملاحظات</label>
              <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} rows={2}
                style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 10px', marginTop: 4, boxSizing: 'border-box', resize: 'vertical' }} />
            </div>
          </div>

          {error && (
            <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, padding: '8px 12px', color: '#dc2626', marginTop: 12, fontSize: 13 }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', marginTop: 24 }}>
            <button type="button" onClick={onClose}
              style={{ padding: '8px 20px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer' }}>
              إلغاء
            </button>
            <button type="submit" disabled={saving}
              style={{ padding: '8px 20px', borderRadius: 6, border: 'none', background: '#2563eb', color: '#fff', cursor: 'pointer', fontWeight: 600 }}>
              {saving ? 'جاري الإنشاء...' : 'إنشاء الجلسة'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── SessionsTab ───────────────────────────────────────────────────────────────

function SessionsTab({ onSelect, refresh }) {
  const [sessions, setSessions]   = useState([]);
  const [loading, setLoading]     = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch]       = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (statusFilter) params.status = statusFilter;
      if (search) params.search = search;
      const res = await stockCountApi.list(params);
      setSessions(res.data.results || res.data);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, search]);

  useEffect(() => { load(); }, [load, refresh]);

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          placeholder="بحث بالاسم أو الفرع..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 200, border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 12px' }}
        />
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          style={{ border: '1px solid #d1d5db', borderRadius: 6, padding: '8px 12px' }}>
          <option value="">كل الحالات</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <CanDo module="admin" action="create">
          <button onClick={() => setShowCreate(true)} style={{
            padding: '8px 20px', borderRadius: 6, border: 'none',
            background: '#2563eb', color: '#fff', cursor: 'pointer', fontWeight: 600,
          }}>
            + جلسة جديدة
          </button>
        </CanDo>
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#6b7280', padding: 32 }}>جاري التحميل...</div>}

      {!loading && sessions.length === 0 && (
        <div style={{ textAlign: 'center', color: '#6b7280', padding: 48, background: '#f9fafb', borderRadius: 8 }}>
          لا توجد جلسات جرد. أنشئ جلسة جديدة للبدء.
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {sessions.map(s => (
          <div key={s.id} onClick={() => onSelect(s)} style={{
            border: '1px solid #e5e7eb', borderRadius: 10, padding: '16px 20px',
            cursor: 'pointer', background: '#fff', transition: 'box-shadow 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)'}
          onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
              <div>
                <span style={{ fontWeight: 700, fontSize: 16 }}>{s.name}</span>
                <span style={{ marginRight: 12, color: '#6b7280', fontSize: 13 }}>فرع: {s.branch_code}</span>
              </div>
              <StatusBadge status={s.status} />
            </div>
            <WorkflowProgress status={s.status} />
            <div style={{ display: 'flex', gap: 24, marginTop: 8, fontSize: 13, color: '#6b7280' }}>
              <span>الأصناف: <strong style={{ color: '#111' }}>{s.item_count || 0}</strong></span>
              <span style={{ color: '#16a34a' }}>زيادة: <strong>{s.surplus_count || 0}</strong></span>
              <span style={{ color: '#dc2626' }}>نقص: <strong>{s.deficit_count || 0}</strong></span>
              <span style={{ color: '#059669' }}>مطابق: <strong>{s.ok_count || 0}</strong></span>
              <span style={{ marginRight: 'auto' }}>
                {new Date(s.created_at).toLocaleDateString('en-US')}
              </span>
            </div>
          </div>
        ))}
      </div>

      {showCreate && (
        <CreateSessionModal
          onClose={() => setShowCreate(false)}
          onCreate={s => { setSessions(prev => [s, ...prev]); onSelect(s); }}
        />
      )}
    </div>
  );
}

// ── SnapshotTab ───────────────────────────────────────────────────────────────

function SnapshotTab({ session, onRefresh }) {
  const [preview, setPreview]   = useState(null);
  const [loading, setLoading]   = useState(false);
  const [snapping, setSnapping] = useState(false);
  const [msg, setMsg]           = useState('');

  async function handlePreview() {
    setLoading(true); setMsg(''); setPreview(null);
    try {
      const res = await stockCountApi.previewItems(session.id);
      setPreview(res.data);
    } catch (err) {
      setMsg(err.response?.data?.detail || 'خطأ في الاستعلام');
    } finally {
      setLoading(false);
    }
  }

  async function handleSnapshot() {
    if (!window.confirm('سيتم تجميد الكميات المتوقعة الآن. هل أنت متأكد؟')) return;
    setSnapping(true); setMsg('');
    try {
      const res = await stockCountApi.generateSnapshot(session.id);
      setMsg(`✓ تم أخذ اللقطة بنجاح — ${res.data.item_count} صنف`);
      onRefresh();
    } catch (err) {
      setMsg(err.response?.data?.detail || 'خطأ في أخذ اللقطة');
    } finally {
      setSnapping(false);
    }
  }

  const canSnap = !['variance_ready', 'closed'].includes(session.status);

  return (
    <div>
      <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 8, padding: 16, marginBottom: 20, fontSize: 14 }}>
        <strong>ℹ️ اللقطة (Snapshot)</strong>: تُجمّد الكميات المتوقعة من SOFTECH في لحظة بعينها.
        بعد أخذ اللقطة لن تتغير الكميات المتوقعة حتى لو تغيرت البيانات في SOFTECH.
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <button onClick={handlePreview} disabled={loading} style={{
          padding: '10px 24px', borderRadius: 6, border: '1px solid #2563eb',
          color: '#2563eb', background: '#fff', cursor: 'pointer', fontWeight: 600,
        }}>
          {loading ? 'جاري الاستعلام...' : '🔍 معاينة الأصناف'}
        </button>
        {canSnap && (
          <button onClick={handleSnapshot} disabled={snapping} style={{
            padding: '10px 24px', borderRadius: 6, border: 'none',
            background: '#2563eb', color: '#fff', cursor: 'pointer', fontWeight: 600,
          }}>
            {snapping ? 'جاري أخذ اللقطة...' : '📸 أخذ اللقطة'}
          </button>
        )}
      </div>

      {msg && (
        <div style={{
          padding: '10px 16px', borderRadius: 6, marginBottom: 16, fontSize: 14,
          background: msg.startsWith('✓') ? '#f0fdf4' : '#fef2f2',
          border: `1px solid ${msg.startsWith('✓') ? '#bbf7d0' : '#fecaca'}`,
          color: msg.startsWith('✓') ? '#15803d' : '#dc2626',
        }}>{msg}</div>
      )}

      {preview && (
        <div>
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 15 }}>
            معاينة: {preview.item_count} صنف من {preview.source}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#1e3a5f', color: '#fff' }}>
                  <th style={th}>كود الصنف</th>
                  <th style={th}>اسم الصنف</th>
                  <th style={th}>التصنيف</th>
                  <th style={th}>الكمية المتوقعة</th>
                </tr>
              </thead>
              <tbody>
                {(preview.items || []).slice(0, 100).map((item, i) => (
                  <tr key={item.item_code} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                    <td style={td}>{item.item_code}</td>
                    <td style={td}>{item.item_name}</td>
                    <td style={td}>{item.category_name || '—'}</td>
                    <td style={{ ...td, textAlign: 'center' }}>{fmtQty(item.expected_qty)}</td>
                  </tr>
                ))}
                {(preview.items || []).length > 100 && (
                  <tr>
                    <td colSpan={4} style={{ ...td, textAlign: 'center', color: '#6b7280' }}>
                      ... و {preview.items.length - 100} صنف آخر
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── CountTab ──────────────────────────────────────────────────────────────────

function CountTab({ session, onRefresh }) {
  const [downloading, setDownloading] = useState(false);
  const [uploading, setUploading]     = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [error, setError]             = useState('');
  const fileRef = useRef();

  async function handleDownload() {
    setDownloading(true);
    try {
      const res = await stockCountApi.exportSheet(session.id);
      const cd    = res.headers['content-disposition'] || '';
      const match = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
      const fname = match ? match[1].replace(/['"]/g, '') : `stock_count_${session.id}.xlsx`;
      downloadBlob(res.data, fname);
    } catch {
      setError('خطأ في تحميل ورقة العد');
    } finally {
      setDownloading(false);
    }
  }

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) { setError('اختر ملف أولاً'); return; }
    setUploading(true); setError(''); setUploadResult(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await stockCountApi.uploadResults(session.id, formData);
      setUploadResult(res.data);
      onRefresh();
    } catch (err) {
      setError(err.response?.data?.detail || 'خطأ في رفع الملف');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  const hasSnapshot = session.status !== 'draft';

  return (
    <div>
      {!hasSnapshot && (
        <div style={{ background: '#fef3c7', border: '1px solid #fcd34d', borderRadius: 8, padding: 16, marginBottom: 20, fontSize: 14 }}>
          ⚠️ يجب أخذ اللقطة أولاً قبل تحميل ورقة العد.
        </div>
      )}

      {/* Step 1 — Download */}
      <div style={{ border: '1px solid #e5e7eb', borderRadius: 10, padding: 20, marginBottom: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 12 }}>
          <span style={{
            background: '#2563eb', color: '#fff', borderRadius: '50%',
            width: 24, height: 24, display: 'inline-flex', alignItems: 'center',
            justifyContent: 'center', fontSize: 13, marginLeft: 8,
          }}>1</span>
          تحميل ورقة العد الفارغة
        </div>
        <p style={{ color: '#6b7280', fontSize: 14, margin: '0 0 12px' }}>
          احفظ الملف، أدخل الكميات المعدودة في عمود "الكمية المعدودة" (العمود الأصفر)، ثم ارفع الملف في الخطوة التالية.
        </p>
        <button onClick={handleDownload} disabled={downloading || !hasSnapshot} style={{
          padding: '10px 24px', borderRadius: 6, border: '1px solid #059669',
          color: '#059669', background: '#fff', cursor: 'pointer', fontWeight: 600,
          opacity: !hasSnapshot ? 0.5 : 1,
        }}>
          {downloading ? 'جاري التحميل...' : '⬇️ تحميل Excel / CSV'}
        </button>
      </div>

      {/* Step 2 — Upload */}
      <div style={{ border: '1px solid #e5e7eb', borderRadius: 10, padding: 20 }}>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 12 }}>
          <span style={{
            background: '#2563eb', color: '#fff', borderRadius: '50%',
            width: 24, height: 24, display: 'inline-flex', alignItems: 'center',
            justifyContent: 'center', fontSize: 13, marginLeft: 8,
          }}>2</span>
          رفع نتائج العد
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" style={{
            border: '1px dashed #d1d5db', borderRadius: 6, padding: '10px 16px',
            cursor: 'pointer', flex: 1, minWidth: 200,
          }} />
          <button onClick={handleUpload} disabled={uploading || !hasSnapshot} style={{
            padding: '10px 24px', borderRadius: 6, border: 'none',
            background: '#2563eb', color: '#fff', cursor: 'pointer', fontWeight: 600,
            opacity: !hasSnapshot ? 0.5 : 1,
          }}>
            {uploading ? 'جاري الرفع...' : '⬆️ رفع النتائج'}
          </button>
        </div>

        {error && (
          <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, padding: '10px 14px', color: '#dc2626', marginTop: 12, fontSize: 13 }}>
            {error}
          </div>
        )}

        {uploadResult && (
          <div style={{ marginTop: 20 }}>
            <div style={{ fontWeight: 600, color: '#15803d', marginBottom: 12 }}>
              ✓ تم الرفع بنجاح — {uploadResult.processed} صنف تمت معالجته
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
              {[
                { label: 'إجمالي الأصناف', value: uploadResult.processed,     color: '#2563eb' },
                { label: 'مطابق',          value: uploadResult.ok_count,       color: '#059669' },
                { label: 'زيادة',          value: uploadResult.surplus_count,  color: '#d97706' },
                { label: 'نقص',            value: uploadResult.deficit_count,  color: '#dc2626' },
              ].map(c => (
                <div key={c.label} style={{ border: `1px solid ${c.color}33`, borderRadius: 8, padding: '12px 16px', textAlign: 'center' }}>
                  <div style={{ fontSize: 24, fontWeight: 700, color: c.color }}>{c.value}</div>
                  <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{c.label}</div>
                </div>
              ))}
            </div>
            {uploadResult.unmatched_count > 0 && (
              <div style={{ background: '#fefce8', border: '1px solid #fde68a', borderRadius: 6, padding: '8px 14px', marginTop: 12, fontSize: 13, color: '#92400e' }}>
                ⚠️ {uploadResult.unmatched_count} صنف لم يُعثر عليه في اللقطة وتم تجاهله.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── VarianceTab ───────────────────────────────────────────────────────────────

function VarianceTab({ session, onRefresh }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter]   = useState('');
  const [minDiff, setMinDiff] = useState('');
  const [exporting, setExporting] = useState(false);
  const [closing, setClosing]     = useState(false);

  const load = useCallback(async () => {
    if (!['variance_ready', 'closed', 'uploaded'].includes(session.status)) return;
    setLoading(true);
    try {
      const params = {};
      if (filter) params.variance_type = filter;
      if (minDiff) params.min_abs_diff = minDiff;
      const res = await stockCountApi.varianceReport(session.id, params);
      setData(res.data);
    } finally {
      setLoading(false);
    }
  }, [session.id, session.status, filter, minDiff]);

  useEffect(() => { load(); }, [load]);

  async function handleAdjExport() {
    setExporting(true);
    try {
      const res = await stockCountApi.adjustmentExport(session.id);
      const cd    = res.headers['content-disposition'] || '';
      const match = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
      const fname = match ? match[1].replace(/['"]/g, '') : `adjustment_${session.id}.xlsx`;
      downloadBlob(res.data, fname);
    } finally {
      setExporting(false);
    }
  }

  async function handleClose() {
    if (!window.confirm('هل تريد إغلاق الجلسة نهائياً؟ لن يمكن التعديل بعد ذلك.')) return;
    setClosing(true);
    try {
      await stockCountApi.close(session.id);
      onRefresh();
    } finally {
      setClosing(false);
    }
  }

  if (!['variance_ready', 'closed', 'uploaded'].includes(session.status)) {
    return (
      <div style={{ textAlign: 'center', color: '#6b7280', padding: 48, background: '#f9fafb', borderRadius: 8 }}>
        يجب رفع نتائج العد أولاً لعرض تقرير الفروق.
      </div>
    );
  }

  return (
    <div>
      {/* Summary cards */}
      {data && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
          {[
            { label: 'إجمالي الأصناف', value: data.summary?.item_count    || session.item_count,    color: '#2563eb' },
            { label: 'مطابق',          value: data.summary?.ok_count      || session.ok_count,      color: '#059669' },
            { label: 'زيادة',          value: data.summary?.surplus_count || session.surplus_count, color: '#d97706' },
            { label: 'نقص',            value: data.summary?.deficit_count || session.deficit_count, color: '#dc2626' },
          ].map(c => (
            <div key={c.label} style={{ border: `2px solid ${c.color}`, borderRadius: 10, padding: 16, textAlign: 'center', background: '#fff' }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: c.color }}>{c.value || 0}</div>
              <div style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>{c.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filters + actions */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        {[
          { key: '',        label: 'الكل' },
          { key: 'surplus', label: 'زيادة فقط' },
          { key: 'deficit', label: 'نقص فقط' },
          { key: 'ok',      label: 'مطابق فقط' },
        ].map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)} style={{
            padding: '6px 16px', borderRadius: 20, cursor: 'pointer',
            fontWeight: filter === f.key ? 700 : 400,
            border: filter === f.key ? '2px solid #2563eb' : '1px solid #d1d5db',
            background: filter === f.key ? '#eff6ff' : '#fff',
            color: filter === f.key ? '#2563eb' : '#374151',
          }}>{f.label}</button>
        ))}
        <input
          placeholder="فارق أدنى (كمية)"
          value={minDiff}
          onChange={e => setMinDiff(e.target.value)}
          type="number" min="0" step="0.001"
          style={{ border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', width: 140 }}
        />
        <div style={{ marginRight: 'auto', display: 'flex', gap: 8 }}>
          <button onClick={handleAdjExport} disabled={exporting} style={{
            padding: '8px 18px', borderRadius: 6, border: '1px solid #059669',
            color: '#059669', background: '#fff', cursor: 'pointer', fontWeight: 600,
          }}>
            {exporting ? 'جاري...' : '📋 تصدير للتسوية'}
          </button>
          {session.status === 'variance_ready' && (
            <button onClick={handleClose} disabled={closing} style={{
              padding: '8px 18px', borderRadius: 6, border: 'none',
              background: '#1f2937', color: '#fff', cursor: 'pointer', fontWeight: 600,
            }}>
              {closing ? 'جاري...' : '🔒 إغلاق الجلسة'}
            </button>
          )}
        </div>
      </div>

      {/* ERP note */}
      <div style={{ background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 8, padding: 12, marginBottom: 16, fontSize: 13, color: '#9a3412' }}>
        📌 لتسوية الفروق في SOFTECH: أصناف الزيادة ← doccode 50 | أصناف النقص ← doccode 150
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#6b7280', padding: 32 }}>جاري التحميل...</div>}

      {data && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#1e3a5f', color: '#fff' }}>
                <th style={th}>كود الصنف</th>
                <th style={th}>اسم الصنف</th>
                <th style={th}>الكمية المتوقعة</th>
                <th style={th}>الكمية المعدودة</th>
                <th style={th}>الفارق</th>
                <th style={th}>النوع</th>
                <th style={th}>كود ERP</th>
              </tr>
            </thead>
            <tbody>
              {(data.items || []).map((row, i) => {
                const diff   = parseFloat(row.difference || 0);
                const rowBg  = row.variance_type === 'surplus' ? '#fefce8'
                             : row.variance_type === 'deficit' ? '#fef2f2'
                             : row.variance_type === 'ok'      ? '#f0fdf4'
                             : '#fff';
                return (
                  <tr key={row.item_code} style={{ background: i % 2 === 0 ? rowBg : '#f9fafb' }}>
                    <td style={td}>{row.item_code}</td>
                    <td style={td}>{row.item_name}</td>
                    <td style={{ ...td, textAlign: 'center' }}>{fmtQty(row.expected_qty)}</td>
                    <td style={{ ...td, textAlign: 'center' }}>
                      {row.counted_qty !== null ? fmtQty(row.counted_qty) : <span style={{ color: '#9ca3af' }}>لم يُعَد</span>}
                    </td>
                    <td style={{ ...td, textAlign: 'center', fontWeight: 700,
                      color: diff > 0 ? '#15803d' : diff < 0 ? '#dc2626' : '#6b7280',
                    }}>
                      {diff !== 0 ? (diff > 0 ? '+' : '') + fmtQty(diff) : '—'}
                    </td>
                    <td style={{ ...td, textAlign: 'center' }}>
                      {row.variance_type === 'surplus' && <span style={{ color: '#d97706', fontWeight: 600 }}>زيادة ▲</span>}
                      {row.variance_type === 'deficit' && <span style={{ color: '#dc2626', fontWeight: 600 }}>نقص ▼</span>}
                      {row.variance_type === 'ok'      && <span style={{ color: '#059669', fontWeight: 600 }}>مطابق ✓</span>}
                      {!row.variance_type              && <span style={{ color: '#9ca3af' }}>—</span>}
                    </td>
                    <td style={{ ...td, textAlign: 'center', fontWeight: 700, color: '#7c3aed' }}>
                      {row.erp_doccode || '—'}
                    </td>
                  </tr>
                );
              })}
              {(!data.items || data.items.length === 0) && (
                <tr>
                  <td colSpan={7} style={{ ...td, textAlign: 'center', color: '#6b7280', padding: 32 }}>
                    لا توجد بيانات
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const TABS = [
  { key: 'sessions', label: '📋 الجلسات' },
  { key: 'snapshot', label: '📸 اللقطة' },
  { key: 'count',    label: '📊 العد' },
  { key: 'variance', label: '📉 الفروق' },
];

export default function StockCountPage() {
  const [activeTab, setActiveTab]           = useState('sessions');
  const [selectedSession, setSelectedSession] = useState(null);
  const [refresh, setRefresh]               = useState(0);

  function handleSelect(s) {
    setSelectedSession(s);
    setActiveTab('snapshot');
  }

  async function refreshSession() {
    if (!selectedSession) return;
    try {
      const res = await stockCountApi.get(selectedSession.id);
      setSelectedSession(res.data);
    } catch { /* ignore */ }
    setRefresh(r => r + 1);
  }

  return (
    <div style={{ direction: 'rtl', fontFamily: 'Cairo, Segoe UI, sans-serif', minHeight: '100vh', background: '#f8fafc' }}>
      {/* Header */}
      <div style={{ background: '#1e3a5f', color: '#fff', padding: '20px 32px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>🏪 جرد المخزون</h1>
        {selectedSession && (
          <div style={{ marginTop: 8, fontSize: 14, color: '#93c5fd' }}>
            الجلسة الحالية: <strong style={{ color: '#fff' }}>{selectedSession.name}</strong>
            <span style={{ marginRight: 16 }}>فرع: {selectedSession.branch_code}</span>
            <button onClick={() => { setSelectedSession(null); setActiveTab('sessions'); }}
              style={{ marginRight: 16, background: 'transparent', border: '1px solid #60a5fa', color: '#60a5fa', borderRadius: 4, padding: '2px 10px', cursor: 'pointer', fontSize: 12 }}>
              ← كل الجلسات
            </button>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ background: '#fff', borderBottom: '1px solid #e5e7eb', padding: '0 32px', display: 'flex', gap: 0 }}>
        {TABS.map(tab => {
          const disabled = tab.key !== 'sessions' && !selectedSession;
          return (
            <button key={tab.key}
              disabled={disabled}
              onClick={() => !disabled && setActiveTab(tab.key)}
              style={{
                padding: '14px 24px', border: 'none', background: 'transparent',
                cursor: disabled ? 'not-allowed' : 'pointer',
                fontWeight: activeTab === tab.key ? 700 : 400,
                color: disabled ? '#d1d5db' : activeTab === tab.key ? '#2563eb' : '#374151',
                borderBottom: activeTab === tab.key ? '3px solid #2563eb' : '3px solid transparent',
                fontSize: 14, transition: 'all 0.15s',
              }}>
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Session workflow bar */}
      {selectedSession && (
        <div style={{ background: '#fff', padding: '12px 32px', borderBottom: '1px solid #e5e7eb' }}>
          <WorkflowProgress status={selectedSession.status} />
        </div>
      )}

      {/* Content */}
      <div style={{ padding: '24px 32px', maxWidth: 1200, margin: '0 auto' }}>
        {activeTab === 'sessions' && (
          <SessionsTab onSelect={handleSelect} refresh={refresh} />
        )}
        {activeTab === 'snapshot' && selectedSession && (
          <SnapshotTab session={selectedSession} onRefresh={refreshSession} />
        )}
        {activeTab === 'count' && selectedSession && (
          <CountTab session={selectedSession} onRefresh={refreshSession} />
        )}
        {activeTab === 'variance' && selectedSession && (
          <VarianceTab session={selectedSession} onRefresh={refreshSession} />
        )}
      </div>
    </div>
  );
}
