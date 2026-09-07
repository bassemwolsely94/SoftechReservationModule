/**
 * ImageEnrichmentPage.jsx
 * Route: /image-enrichment
 *
 * Tabs:
 *  1. Dashboard     — coverage stats + active jobs
 *  2. Review Queue  — approve / reject candidates (with watermark indicator)
 *  3. Batch Launch  — advanced filters: scope, category, producer, ABC, top-sold
 *  4. Revise All    — re-run search for existing images to replace bad ones
 *  5. Job History   — full audit log
 */
import { useState, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { imageApi } from '../api/client'

// ── Shared styles ─────────────────────────────────────────────────────────────
const card  = { background: '#fff', borderRadius: 10, padding: '20px 24px', boxShadow: '0 1px 4px rgba(0,0,0,.08)', marginBottom: 16 }
const btn   = (color = '#2563eb', outline = false, small = false) => ({
  padding: small ? '5px 12px' : '8px 18px',
  borderRadius: 7, border: outline ? `1.5px solid ${color}` : 'none',
  background: outline ? 'transparent' : color, color: outline ? color : '#fff',
  cursor: 'pointer', fontWeight: 600, fontSize: small ? 12 : 13,
  transition: 'opacity .15s', whiteSpace: 'nowrap',
})
const badge = (color, text) => (
  <span style={{ display:'inline-block', padding:'2px 9px', borderRadius:20,
                 fontSize:11, fontWeight:600, background:color+'22', color, marginRight:4 }}>
    {text}
  </span>
)
const input = { padding:'8px 10px', borderRadius:7, border:'1px solid #e2e8f0', fontSize:13, width:'100%' }
const selectStyle = { ...input }

const STATUS_COLOR = { pending:'#f59e0b', running:'#3b82f6', done:'#10b981', failed:'#ef4444', skipped:'#9ca3af', cancelled:'#6b7280' }
const score = n => (n * 100).toFixed(0) + '%'
const wm_color = wm => wm > 0.6 ? '#dc2626' : wm > 0.3 ? '#f59e0b' : '#10b981'
const wm_label = wm => wm > 0.6 ? 'علامة مائية واضحة' : wm > 0.3 ? 'علامة مائية محتملة' : 'نظيف'

// ── CoverageBar ───────────────────────────────────────────────────────────────
function CoverageBar({ pct: p, label }) {
  return (
    <div>
      {label && <div style={{fontSize:12,color:'#64748b',marginBottom:4}}>{label}</div>}
      <div style={{background:'#f1f5f9',borderRadius:8,height:12,overflow:'hidden'}}>
        <div style={{width:Math.min(p,100)+'%',height:'100%',background:'#2563eb',borderRadius:8,transition:'width .5s'}}/>
      </div>
    </div>
  )
}

// ── Advanced Filter Panel ─────────────────────────────────────────────────────
function FilterPanel({ filters, onChange, meta }) {
  const cats      = meta?.categories || []
  const producers = meta?.producers  || []
  const abcCounts = meta?.abc_counts || {}

  return (
    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:12}}>
      {/* Scope */}
      <label>
        <div style={{fontSize:12,fontWeight:600,marginBottom:4,color:'#374151'}}>النطاق</div>
        <select value={filters.scope} onChange={e=>onChange({...filters,scope:e.target.value})} style={selectStyle}>
          <option value="no_image">منتجات بلا صور</option>
          <option value="all_active">كل المنتجات النشطة</option>
          <option value="low_score">نقاط إثراء منخفضة</option>
          <option value="top_qty">الأعلى مبيعاً بالكمية</option>
          <option value="top_value">الأعلى مبيعاً بالقيمة</option>
        </select>
      </label>

      {/* Category */}
      <label>
        <div style={{fontSize:12,fontWeight:600,marginBottom:4,color:'#374151'}}>الفئة</div>
        <select value={filters.category_id||''} onChange={e=>onChange({...filters,category_id:e.target.value||null})} style={selectStyle}>
          <option value="">كل الفئات</option>
          {cats.map(c=><option key={c.id} value={c.id}>{c.name_ar||c.name}</option>)}
        </select>
      </label>

      {/* Producer */}
      <label>
        <div style={{fontSize:12,fontWeight:600,marginBottom:4,color:'#374151'}}>الشركة المصنعة</div>
        <select value={filters.producer_name||''} onChange={e=>onChange({...filters,producer_name:e.target.value||''})} style={selectStyle}>
          <option value="">كل الشركات</option>
          {producers.map(p=><option key={p} value={p}>{p}</option>)}
        </select>
      </label>

      {/* ABC class */}
      <label>
        <div style={{fontSize:12,fontWeight:600,marginBottom:4,color:'#374151'}}>فئة ABC</div>
        <select value={filters.abc_class||''} onChange={e=>onChange({...filters,abc_class:e.target.value||''})} style={selectStyle}>
          <option value="">كل الفئات</option>
          <option value="A">A — حركة عالية {abcCounts.A?`(${abcCounts.A.toLocaleString()})`:''}</option>
          <option value="B">B — حركة متوسطة {abcCounts.B?`(${abcCounts.B.toLocaleString()})`:''}</option>
          <option value="C">C — حركة منخفضة {abcCounts.C?`(${abcCounts.C.toLocaleString()})`:''}</option>
        </select>
      </label>

      {/* Limit */}
      <label>
        <div style={{fontSize:12,fontWeight:600,marginBottom:4,color:'#374151'}}>الحد الأقصى</div>
        <input type="number" min={1} max={500} value={filters.limit}
               onChange={e=>onChange({...filters,limit:Math.min(500,+e.target.value)})} style={input}/>
      </label>

      {/* Priority */}
      <label>
        <div style={{fontSize:12,fontWeight:600,marginBottom:4,color:'#374151'}}>الأولوية</div>
        <select value={filters.priority} onChange={e=>onChange({...filters,priority:+e.target.value})} style={selectStyle}>
          <option value={1}>منخفضة</option>
          <option value={2}>عادية</option>
          <option value={3}>عالية</option>
          <option value={4}>عاجلة</option>
        </select>
      </label>
    </div>
  )
}

// ── CandidateCard ─────────────────────────────────────────────────────────────
function CandidateCard({ c, onApprove, onReject, loading }) {
  const imgUrl = c.image_url || c.source_url
  const ts     = c.total_score
  const wm     = c.watermark_score || c.score_breakdown?.watermark_score || 0
  const tsColor = ts >= 0.75 ? '#059669' : ts >= 0.50 ? '#f59e0b' : '#dc2626'

  return (
    <div style={{...card, display:'flex', gap:14, alignItems:'flex-start', margin:0, position:'relative'}}>
      {/* Cleaned badge */}
      {c.was_cleaned && (
        <div style={{position:'absolute',top:8,left:8,background:'#7c3aed',color:'#fff',
                     borderRadius:6,padding:'2px 8px',fontSize:10,fontWeight:700}}>
          ✨ تم التنظيف
        </div>
      )}

      {/* Image preview */}
      <div style={{flexShrink:0}}>
        <img src={imgUrl} alt={c.item_name}
             style={{width:120,height:120,objectFit:'contain',borderRadius:8,
                     border:'1.5px solid #e2e8f0',background:'#f8fafc'}}
             onError={e=>{e.target.src='data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs='}}/>
        {/* Watermark indicator bar */}
        <div style={{marginTop:4,height:4,borderRadius:2,background:'#f1f5f9'}}>
          <div style={{width:(wm*100).toFixed(0)+'%',height:'100%',borderRadius:2,background:wm_color(wm)}}/>
        </div>
        <div style={{fontSize:9,color:wm_color(wm),textAlign:'center',marginTop:2,fontWeight:600}}>
          {wm_label(wm)}
        </div>
      </div>

      {/* Info */}
      <div style={{flex:1,minWidth:0}}>
        <div style={{fontWeight:700,fontSize:14}}>{c.item_name}</div>
        <div style={{fontSize:11,color:'#64748b',marginBottom:6}}>{c.item_code}</div>

        {/* Score badges */}
        <div style={{display:'flex',gap:6,flexWrap:'wrap',marginBottom:8}}>
          {badge(tsColor,      'مجموع ' + score(ts))}
          {badge('#3b82f6',    'جودة ' + score(c.quality_score))}
          {badge('#8b5cf6',    'تطابق ' + score(c.confidence_score))}
          {badge(wm_color(wm), 'وتر م. ' + score(wm))}
          {badge('#64748b',    c.source_type)}
          {c.width && c.height && badge('#0ea5e9', c.width+'×'+c.height)}
        </div>

        {/* Source link */}
        {c.source_url && (
          <div style={{fontSize:11,color:'#94a3b8',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap',marginBottom:8}}>
            <a href={c.source_url} target="_blank" rel="noreferrer" style={{color:'#3b82f6'}}>
              {c.source_url.slice(0,80)}…
            </a>
          </div>
        )}

        {/* Actions */}
        <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
          <button style={btn('#059669')} onClick={()=>onApprove(c)} disabled={loading}>✓ قبول</button>
          <button style={btn('#dc2626',true)} onClick={()=>onReject(c)} disabled={loading}>✗ رفض</button>
          {c.source_page_url && (
            <a href={c.source_page_url} target="_blank" rel="noreferrer"
               style={{...btn('#6b7280',true,true),textDecoration:'none'}}>
              صفحة المصدر ↗
            </a>
          )}
        </div>
      </div>

      {/* Score bar */}
      <div style={{width:6,borderRadius:3,background:'#f1f5f9',flexShrink:0,alignSelf:'stretch'}}>
        <div style={{height:(ts*100).toFixed(0)+'%',background:tsColor,borderRadius:3,transition:'height .3s'}}/>
      </div>
    </div>
  )
}

// ── Tab 1: Dashboard ──────────────────────────────────────────────────────────
function DashboardTab() {
  const {data:rpt} = useQuery({queryKey:['img-report'],queryFn:()=>imageApi.report().then(r=>r.data),refetchInterval:15000})
  const {data:jobs}= useQuery({queryKey:['img-jobs-run'],queryFn:()=>imageApi.jobs({status:'running',page_size:10}).then(r=>r.data),refetchInterval:5000})
  const r = rpt || {}

  const stats = [
    {label:'إجمالي المنتجات',    value:(r.total_items||0).toLocaleString(),      color:'#64748b'},
    {label:'بصورة معتمدة',       value:(r.items_with_image||0).toLocaleString(), color:'#059669'},
    {label:'نسبة التغطية',       value:(r.coverage_pct||0)+'%',                  color:'#2563eb'},
    {label:'تنتظر المراجعة',     value:r.pending_review||0,                      color:'#f59e0b'},
    {label:'موافقة تلقائية',     value:r.auto_approved||0,                       color:'#8b5cf6'},
    {label:'مهام جارية',         value:(r.jobs_running||0)+(r.jobs_pending||0),  color:'#3b82f6'},
    {label:'مهام فاشلة',         value:r.jobs_failed||0,                         color:'#ef4444'},
  ]

  return (
    <div>
      <div style={{display:'flex',gap:10,flexWrap:'wrap',marginBottom:16}}>
        {stats.map(s=>(
          <div key={s.label} style={{...card,flex:1,minWidth:120,textAlign:'center',margin:0}}>
            <div style={{fontSize:26,fontWeight:700,color:s.color}}>{s.value}</div>
            <div style={{fontSize:12,color:'#64748b',marginTop:2}}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={card}>
        <div style={{fontWeight:600,marginBottom:8}}>التغطية البصرية</div>
        <CoverageBar pct={r.coverage_pct||0}/>
        <div style={{fontSize:12,color:'#64748b',marginTop:6}}>
          {(r.items_with_image||0).toLocaleString()} من {(r.total_items||0).toLocaleString()} منتج
        </div>
      </div>

      {jobs?.length > 0 && (
        <div style={card}>
          <div style={{fontWeight:600,marginBottom:10}}>المهام الجارية الآن</div>
          {jobs.map(j=>(
            <div key={j.id} style={{display:'flex',gap:12,alignItems:'center',padding:'8px 0',borderBottom:'1px solid #f1f5f9'}}>
              <span style={{fontSize:11,color:'#94a3b8'}}>#{j.id}</span>
              <span style={{flex:1,fontWeight:600,fontSize:13,minWidth:0,overflowWrap:'break-word'}}>{j.item_name}</span>
              <span style={{fontSize:12,color:'#3b82f6'}}>🔍 {j.candidates_scored} مرشح</span>
              {badge(STATUS_COLOR[j.status]||'#6b7280', j.status)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Tab 2: Review Queue ───────────────────────────────────────────────────────
function ReviewQueueTab({ onGallery }) {
  const qc = useQueryClient()
  const [loading,  setLoading]  = useState(false)
  const [maxWm,    setMaxWm]    = useState(1.0)
  const [minScore, setMinScore] = useState(0)

  const {data:queue,isLoading,refetch} = useQuery({
    queryKey: ['img-review-queue', maxWm, minScore],
    queryFn:  () => imageApi.reviewQueue({page_size:60}).then(r=>r.data),
  })

  const filtered = (queue||[]).filter(c => {
    const wm = c.watermark_score || c.score_breakdown?.watermark_score || 0
    return wm <= maxWm && c.total_score >= minScore
  })

  const handle = useCallback(async (c, action) => {
    setLoading(true)
    try {
      await imageApi.reviewCandidate(c.id, {action, set_primary:true})
      qc.invalidateQueries(['img-review-queue'])
      qc.invalidateQueries(['img-report'])
    } finally { setLoading(false) }
  }, [qc])

  const byItem = {}
  filtered.forEach(c => { const k=c.item_code||c.item; (byItem[k]=byItem[k]||[]).push(c) })

  return (
    <div>
      {/* Filters row */}
      <div style={{...card, padding:'14px 20px'}}>
        <div style={{display:'flex',gap:16,alignItems:'center',flexWrap:'wrap'}}>
          <div style={{fontSize:13,fontWeight:600}}>فلتر العرض</div>
          <label style={{display:'flex',alignItems:'center',gap:8,fontSize:13}}>
            حد العلامة المائية: <strong style={{color:wm_color(maxWm)}}>{Math.round(maxWm*100)}%</strong>
            <input type="range" min={0} max={1} step={0.05} value={maxWm}
                   onChange={e=>setMaxWm(+e.target.value)} style={{width:120}}/>
          </label>
          <label style={{display:'flex',alignItems:'center',gap:8,fontSize:13}}>
            حد النقاط:
            <input type="number" min={0} max={100} value={Math.round(minScore*100)}
                   onChange={e=>setMinScore(+e.target.value/100)}
                   style={{...input,width:60}}/>%
          </label>
          <button style={btn('#6b7280',true,true)} onClick={()=>refetch()}>تحديث</button>
          <div style={{marginRight:'auto',fontSize:13,color:'#64748b'}}>
            {filtered.length} صورة • {Object.keys(byItem).length} منتج
          </div>
        </div>
      </div>

      {isLoading && <div style={{padding:40,textAlign:'center',color:'#64748b'}}>تحميل…</div>}

      {!isLoading && filtered.length === 0 && (
        <div style={{padding:48,textAlign:'center',color:'#64748b'}}>
          <div style={{fontSize:36,marginBottom:10}}>✓</div>
          <div style={{fontWeight:600}}>قائمة المراجعة فارغة</div>
          <div style={{fontSize:13,color:'#94a3b8',marginTop:4}}>لا توجد صور تنتظر الموافقة بالمعايير الحالية</div>
        </div>
      )}

      {Object.entries(byItem).map(([code, candidates]) => (
        <div key={code} style={{marginBottom:20}}>
          <div style={{fontWeight:700,fontSize:14,color:'#1e293b',marginBottom:8,
                       borderRight:'3px solid #2563eb',paddingRight:10,
                       display:'flex',alignItems:'center',gap:10}}>
            <span>
              {candidates[0]?.item_name}
              <span style={{color:'#94a3b8',fontWeight:400,marginRight:8}}>— {code}</span>
            </span>
            <button style={{...btn('#8b5cf6',true,true),marginRight:'auto'}}
                    onClick={()=>onGallery&&onGallery(candidates[0]?.item)}>
              🖼️ معرض الصور
            </button>
          </div>
          <div style={{display:'grid',gap:10}}>
            {[...candidates].sort((a,b)=>b.total_score-a.total_score).map(c=>(
              <CandidateCard key={c.id} c={c} loading={loading}
                onApprove={()=>handle(c,'approve')} onReject={()=>handle(c,'reject')}/>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Tab 3: Batch Launch ───────────────────────────────────────────────────────
function BatchLaunchTab({ meta }) {
  const [filters,   setFilters]   = useState({ scope:'no_image', limit:100, priority:2, abc_class:'', category_id:null, producer_name:'' })
  const [threshold, setThreshold] = useState(0.78)
  const [result,    setResult]    = useState(null)
  const [loading,   setLoading]   = useState(false)

  const launch = async () => {
    setLoading(true); setResult(null)
    try {
      const {data} = await imageApi.bulkJobs({...filters, auto_approve_threshold:threshold})
      setResult({ok:true, ...data})
    } catch(e) { setResult({ok:false,error:e.response?.data?.detail||'خطأ'}) }
    finally { setLoading(false) }
  }

  return (
    <div>
      <div style={card}>
        <div style={{fontWeight:700,fontSize:15,marginBottom:16}}>فلاتر متقدمة لإطلاق دفعة بحث</div>
        <FilterPanel filters={filters} onChange={setFilters} meta={meta}/>

        <div style={{marginTop:16}}>
          <div style={{fontSize:12,fontWeight:600,marginBottom:4,color:'#374151'}}>
            حد الموافقة التلقائية: {Math.round(threshold*100)}%
          </div>
          <input type="range" min={0.5} max={1.0} step={0.05} value={threshold}
                 onChange={e=>setThreshold(+e.target.value)} style={{width:'100%'}}/>
          <div style={{display:'flex',justifyContent:'space-between',fontSize:11,color:'#94a3b8',marginTop:2}}>
            <span>50% — أقل تحفظاً (موافقة أسرع)</span>
            <span>100% — أكثر تحفظاً (مراجعة بشرية أكثر)</span>
          </div>
        </div>

        <div style={{marginTop:16,background:'#f0fdf4',border:'1px solid #bbf7d0',borderRadius:8,padding:'10px 14px',fontSize:13}}>
          <strong>تقدير التكلفة:</strong> {filters.limit} منتج × 0 تكلفة API = <strong>مجاني</strong>
          <span style={{color:'#64748b',marginRight:8}}>
            (DuckDuckGo · Open Food Facts · drugs.com · RxList)
          </span>
        </div>

        <div style={{marginTop:12}}>
          <button style={btn('#2563eb')} onClick={launch} disabled={loading}>
            {loading ? 'جارٍ الإطلاق…' : `🚀 إطلاق لـ ${filters.limit} منتج`}
          </button>
        </div>

        {result && (
          <div style={{marginTop:12,padding:'12px 16px',borderRadius:8,
                       background:result.ok?'#f0fdf4':'#fef2f2',
                       border:`1px solid ${result.ok?'#bbf7d0':'#fecaca'}`,fontSize:13}}>
            {result.ok
              ? <span style={{color:'#059669'}}>✓ تم إنشاء {result.created} مهمة — تخطي {result.skipped} (لديها بالفعل مهمة نشطة)</span>
              : <span style={{color:'#dc2626'}}>❌ {result.error}</span>}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Tab 4: Revise Existing ────────────────────────────────────────────────────
function ReviseTab({ meta }) {
  const [filters,   setFilters]   = useState({ scope:'all_active', limit:100, priority:3, abc_class:'', category_id:null, producer_name:'' })
  const [threshold, setThreshold] = useState(0.82)
  const [minScore,  setMinScore]  = useState(0)
  const [result,    setResult]    = useState(null)
  const [loading,   setLoading]   = useState(false)

  const launch = async () => {
    setLoading(true); setResult(null)
    try {
      const {data} = await imageApi.reviseAll({
        ...filters,
        auto_approve_threshold: threshold,
        min_score: minScore,
      })
      setResult({ok:true, ...data})
    } catch(e) { setResult({ok:false, error:e.response?.data?.detail||'خطأ في الاتصال'}) }
    finally { setLoading(false) }
  }

  return (
    <div>
      <div style={{...card,background:'#fffbeb',border:'1px solid #fde68a'}}>
        <div style={{fontWeight:700,fontSize:14,marginBottom:6}}>⚠️ مراجعة شاملة للصور الموجودة</div>
        <div style={{fontSize:13,color:'#92400e'}}>
          هذه العملية ستعيد البحث عن صور أفضل حتى للمنتجات التي لديها صور معتمدة بالفعل.
          استخدمها عندما تريد استبدال صور رديئة أو ذات علامات مائية.
        </div>
      </div>

      <div style={card}>
        <div style={{fontWeight:700,fontSize:15,marginBottom:16}}>إعدادات المراجعة الشاملة</div>
        <FilterPanel filters={filters} onChange={setFilters} meta={meta}/>

        <div style={{marginTop:16,display:'grid',gridTemplateColumns:'1fr 1fr',gap:16}}>
          <label>
            <div style={{fontSize:12,fontWeight:600,marginBottom:4}}>
              حد الموافقة التلقائية: {Math.round(threshold*100)}%
            </div>
            <input type="range" min={0.5} max={1.0} step={0.05} value={threshold}
                   onChange={e=>setThreshold(+e.target.value)} style={{width:'100%'}}/>
          </label>
          <label>
            <div style={{fontSize:12,fontWeight:600,marginBottom:4}}>
              تخطي المنتجات التي نقاطها &gt; {Math.round(minScore*100)}% (0 = أعد الكل)
            </div>
            <input type="range" min={0} max={1.0} step={0.05} value={minScore}
                   onChange={e=>setMinScore(+e.target.value)} style={{width:'100%'}}/>
          </label>
        </div>

        <div style={{marginTop:12}}>
          <button style={btn('#dc2626')} onClick={launch} disabled={loading}>
            {loading ? 'جارٍ الإطلاق…' : `🔄 مراجعة ${filters.limit} منتج (بما فيها ذات الصور)`}
          </button>
        </div>

        {result && (
          <div style={{marginTop:12,padding:'12px 16px',borderRadius:8,
                       background:result.ok?'#f0fdf4':'#fef2f2',
                       border:`1px solid ${result.ok?'#bbf7d0':'#fecaca'}`,fontSize:13}}>
            {result.ok
              ? <span style={{color:'#059669'}}>✓ {result.message}</span>
              : <span style={{color:'#dc2626'}}>❌ {result.error}</span>}
          </div>
        )}
      </div>

      {/* Watermark stats */}
      <div style={card}>
        <div style={{fontWeight:600,marginBottom:12}}>دليل العلامات المائية</div>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:12}}>
          {[
            {color:'#10b981', label:'نظيف', sub:'watermark < 30%', desc:'صورة نظيفة، يمكن قبولها'},
            {color:'#f59e0b', label:'مشبوه', sub:'watermark 30–60%', desc:'قد تحتوي علامة مائية — راجع يدوياً'},
            {color:'#dc2626', label:'علامة مائية', sub:'watermark > 60%', desc:'علامة مائية واضحة — تم التصفية أو التنظيف التلقائي'},
          ].map(({color,label,sub,desc})=>(
            <div key={label} style={{padding:'12px 16px',borderRadius:8,border:`1.5px solid ${color}`,background:color+'11'}}>
              <div style={{fontWeight:700,color,fontSize:14}}>{label}</div>
              <div style={{fontSize:11,color:'#64748b',marginTop:2}}>{sub}</div>
              <div style={{fontSize:12,color:'#374151',marginTop:4}}>{desc}</div>
            </div>
          ))}
        </div>
        <div style={{marginTop:12,padding:'10px 14px',background:'#f0f9ff',borderRadius:8,fontSize:13,color:'#0369a1'}}>
          🤖 <strong>التنظيف التلقائي:</strong> عند اكتشاف علامة مائية في زوايا الصورة، يحاول النظام ملء تلك المنطقة
          بلون الخلفية المحيطة تلقائياً. الصور المنظّفة تظهر بشارة <strong style={{color:'#7c3aed'}}>✨ تم التنظيف</strong>.
        </div>
      </div>
    </div>
  )
}

// ── Tab 5: Job History ────────────────────────────────────────────────────────
function HistoryTab() {
  const [sf, setSf] = useState('')
  const {data:jobs,isLoading} = useQuery({
    queryKey:['img-jobs',sf],
    queryFn:()=>imageApi.jobs({status:sf||undefined,page_size:60}).then(r=>r.data),
    refetchInterval:10000,
  })

  return (
    <div>
      <div style={{display:'flex',gap:6,flexWrap:'wrap',marginBottom:14}}>
        {['','pending','running','done','failed','skipped','cancelled'].map(s=>(
          <button key={s} onClick={()=>setSf(s)}
                  style={btn(STATUS_COLOR[s]||'#64748b', sf!==s, true)}>
            {s||'الكل'}
          </button>
        ))}
      </div>

      {isLoading && <div style={{padding:24,textAlign:'center',color:'#64748b'}}>تحميل…</div>}

      {jobs && (
        <div style={{...card,padding:0,overflow:'hidden'}}>
          <table style={{width:'100%',borderCollapse:'collapse'}}>
            <thead>
              <tr style={{background:'#f8fafc'}}>
                {['#','المنتج','الحالة','مرشحين','أفضل نقطة','وقت','بواسطة'].map(h=>(
                  <th key={h} style={{padding:'10px 12px',textAlign:'right',fontSize:12,color:'#64748b',fontWeight:600,borderBottom:'1px solid #f1f5f9'}}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(jobs||[]).map(j=>(
                <tr key={j.id} style={{borderBottom:'1px solid #f8fafc'}}>
                  <td style={{padding:'8px 12px',fontSize:12,color:'#94a3b8'}}>#{j.id}</td>
                  <td style={{padding:'8px 12px'}}>
                    <div style={{fontWeight:600,fontSize:13}}>{j.item_name}</div>
                    <div style={{fontSize:11,color:'#94a3b8'}}>{j.item_code}</div>
                  </td>
                  <td style={{padding:'8px 12px'}}>
                    {badge(STATUS_COLOR[j.status]||'#6b7280', j.status)}
                    {j.last_error && <div style={{fontSize:10,color:'#dc2626',marginTop:2,maxWidth:160,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{j.last_error}</div>}
                  </td>
                  <td style={{padding:'8px 12px',textAlign:'center',fontSize:13}}>{j.candidates_scored}</td>
                  <td style={{padding:'8px 12px',textAlign:'center',fontWeight:600,fontSize:13,
                              color:j.best_score>=0.75?'#059669':j.best_score>=0.5?'#f59e0b':'#dc2626'}}>
                    {j.best_score ? score(j.best_score) : '—'}
                  </td>
                  <td style={{padding:'8px 12px',fontSize:12,color:'#64748b'}}>{j.duration_seconds!=null ? j.duration_seconds+'s' : '—'}</td>
                  <td style={{padding:'8px 12px',fontSize:12,color:'#64748b'}}>{j.triggered_by_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!jobs?.length && <div style={{padding:24,textAlign:'center',color:'#94a3b8',fontSize:13}}>لا توجد مهام</div>}
        </div>
      )}
    </div>
  )
}

// ── Gallery: Right panel — item image manager ─────────────────────────────────
function ItemImageManager({ item, onClose }) {
  const qc            = useQueryClient()
  const [panel, setPanel] = useState('approved')   // 'approved' | 'candidates' | 'upload' | 'search'
  const [busy,  setBusy]  = useState(false)
  const [uploadFile, setUploadFile] = useState(null)
  const [uploadPrimary, setUploadPrimary] = useState(true)
  const [candStatus, setCandStatus] = useState('all')

  const itemId = item.id

  const {data:gallery, isLoading:galLoad, refetch:refetchGallery} = useQuery({
    queryKey: ['img-gallery', itemId],
    queryFn:  () => imageApi.gallery(itemId).then(r => r.data),
  })

  const {data:candidates, isLoading:candLoad, refetch:refetchCands} = useQuery({
    queryKey: ['img-item-cands', itemId, candStatus],
    queryFn:  () => imageApi.itemCandidates(itemId, {status: candStatus, page_size:100}).then(r => r.data),
    enabled:  panel === 'candidates',
  })

  const refresh = () => { refetchGallery(); refetchCands(); qc.invalidateQueries(['img-product-search']); qc.invalidateQueries(['img-report']) }

  const handleSetPrimary = async (mediaId) => {
    setBusy(true)
    try { await imageApi.setPrimary(itemId, mediaId); refresh() }
    finally { setBusy(false) }
  }

  const handleDelete = async (mediaId, isPrimary) => {
    if (!window.confirm(isPrimary ? 'هذه الصورة الافتراضية — هل تريد حذفها؟' : 'هل تريد حذف هذه الصورة؟')) return
    setBusy(true)
    try { await imageApi.deleteImage(itemId, mediaId); refresh() }
    finally { setBusy(false) }
  }

  const handleApprove = async (cand) => {
    setBusy(true)
    try {
      await imageApi.reviewCandidate(cand.id, { action: 'approve', set_primary: true })
      refresh()
    } finally { setBusy(false) }
  }

  const handleReject = async (cand) => {
    setBusy(true)
    try {
      await imageApi.reviewCandidate(cand.id, { action: 'reject', note: '' })
      refresh()
    } finally { setBusy(false) }
  }

  const handleUpload = async () => {
    if (!uploadFile) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', uploadFile)
      fd.append('set_primary', uploadPrimary ? 'true' : 'false')
      await imageApi.uploadImage(itemId, fd)
      setUploadFile(null)
      setPanel('approved')
      refresh()
    } finally { setBusy(false) }
  }

  const handleLaunchSearch = async () => {
    setBusy(true)
    try {
      await imageApi.createJob({ item_id: itemId, priority: 3, auto_approve_threshold: 0.78, force_rerun: true })
      qc.invalidateQueries(['img-report'])
      alert('تم إطلاق مهمة البحث')
    } catch(e) { alert('فشل الإطلاق') }
    finally { setBusy(false) }
  }

  const images     = gallery?.images || []
  const primary    = images.find(m => m.is_primary)
  const secondary  = images.filter(m => !m.is_primary)
  const pendingCount = (candidates || []).filter(c => c.status === 'pending_review').length

  const panelTab = (id, label, count) => (
    <button onClick={() => setPanel(id)}
            style={{padding:'7px 14px', border:'none', background:'none', cursor:'pointer',
                    fontWeight:600, fontSize:12,
                    color: panel===id ? '#2563eb' : '#64748b',
                    borderBottom: panel===id ? '2px solid #2563eb' : '2px solid transparent',
                    position:'relative'}}>
      {label}
      {count > 0 && <span style={{marginRight:4,background:'#ef4444',color:'#fff',borderRadius:9,
                                   padding:'0 5px',fontSize:10}}>{count}</span>}
    </button>
  )

  return (
    <div style={{display:'flex', flexDirection:'column', height:'100%'}}>

      {/* Header */}
      <div style={{padding:'12px 16px', borderBottom:'1px solid #e2e8f0', background:'#f8fafc',
                   display:'flex', alignItems:'center', gap:10}}>
        <div style={{flex:1, minWidth:0}}>
          <div style={{fontWeight:700, fontSize:14, overflowWrap:'break-word'}}>
            {item.name}
          </div>
          <div style={{fontSize:11, color:'#94a3b8'}}>{item.softech_id} · {item.producer_name}</div>
        </div>
        <div style={{display:'flex', gap:6, flexShrink:0}}>
          {badge(item.has_image ? '#059669' : '#f59e0b', item.has_image ? `${item.approved_count} صورة` : 'لا توجد صور')}
          {item.pending_count > 0 && badge('#ef4444', `${item.pending_count} مرشح`)}
        </div>
        <button onClick={onClose} style={{background:'none', border:'none', cursor:'pointer',
                                          fontSize:18, color:'#94a3b8', padding:'0 4px'}}>✕</button>
      </div>

      {/* Sub-tabs */}
      <div style={{display:'flex', gap:0, borderBottom:'1px solid #e2e8f0', padding:'0 8px',
                   background:'#fff', flexShrink:0}}>
        {panelTab('approved',   '🖼️ الصور المعتمدة', images.length)}
        {panelTab('candidates', '🔍 المرشحون', pendingCount)}
        {panelTab('upload',     '⬆️ رفع صورة', 0)}
        {panelTab('search',     '🚀 بحث جديد', 0)}
      </div>

      {/* Panel content */}
      <div style={{flex:1, overflowY:'auto', padding:'12px 16px'}}>

        {/* ── Approved images panel ── */}
        {panel === 'approved' && (
          <div>
            {galLoad && <div style={{padding:32, textAlign:'center', color:'#94a3b8'}}>تحميل…</div>}
            {!galLoad && images.length === 0 && (
              <div style={{textAlign:'center', padding:'32px 0', color:'#94a3b8'}}>
                <div style={{fontSize:40, marginBottom:8}}>📷</div>
                <div style={{fontWeight:600}}>لا توجد صور معتمدة</div>
                <div style={{fontSize:12, marginTop:4}}>ارفع صورة أو أطلق بحثاً جديداً</div>
              </div>
            )}

            {/* Primary image — large */}
            {primary && (
              <div style={{marginBottom:16, borderRadius:10, border:'2px solid #10b981',
                           background:'#f0fdf4', overflow:'hidden'}}>
                <div style={{display:'flex', gap:12, padding:12}}>
                  <div style={{position:'relative', flexShrink:0}}>
                    <img src={primary.thumb_url || primary.url}
                         style={{width:180, height:180, objectFit:'contain', borderRadius:8,
                                 background:'#fff', border:'1px solid #e2e8f0'}}
                         onError={e => { e.target.style.display='none' }}/>
                    <div style={{position:'absolute', top:4, right:4, background:'#059669',
                                 color:'#fff', borderRadius:20, padding:'1px 7px', fontSize:10, fontWeight:700}}>
                      ⭐ افتراضية
                    </div>
                  </div>
                  <div style={{flex:1}}>
                    <div style={{fontWeight:700, fontSize:13, marginBottom:6}}>الصورة الافتراضية</div>
                    <div style={{marginBottom:8}}>
                      {badge('#64748b', primary.source)}
                      {badge('#0ea5e9', primary.created_at?.slice(0,10))}
                    </div>
                    <a href={primary.url} target="_blank" rel="noreferrer"
                       style={{display:'block', fontSize:11, color:'#3b82f6', marginBottom:10,
                               overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
                      فتح الصورة ↗
                    </a>
                    <button style={btn('#dc2626', true, true)} disabled={busy}
                            onClick={() => handleDelete(primary.id, true)}>
                      🗑 حذف
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Secondary images grid */}
            {secondary.length > 0 && (
              <div>
                <div style={{fontWeight:600, fontSize:12, color:'#64748b', marginBottom:8}}>
                  صور إضافية ({secondary.length}) — انقر لتعيين أي منها كافتراضية
                </div>
                <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(150px,1fr))', gap:10}}>
                  {secondary.map(m => (
                    <div key={m.id} style={{borderRadius:8, border:'1.5px solid #e2e8f0',
                                            overflow:'hidden', background:'#f8fafc'}}>
                      <div style={{position:'relative'}}>
                        <img src={m.thumb_url || m.url}
                             style={{width:'100%', height:130, objectFit:'contain', display:'block'}}
                             onError={e => { e.target.style.display='none' }}/>
                        {!m.approved && (
                          <div style={{position:'absolute', top:4, right:4, background:'#f59e0b',
                                       color:'#fff', borderRadius:4, padding:'1px 5px', fontSize:9}}>
                            غير معتمدة
                          </div>
                        )}
                      </div>
                      <div style={{padding:'6px 8px'}}>
                        <div style={{fontSize:10, color:'#94a3b8', marginBottom:5}}>{m.source}</div>
                        <div style={{display:'flex', gap:4, flexWrap:'wrap'}}>
                          <button style={btn('#059669', false, true)} disabled={busy}
                                  onClick={() => handleSetPrimary(m.id)}>
                            ⭐ افتراضية
                          </button>
                          <button style={btn('#dc2626', true, true)} disabled={busy}
                                  onClick={() => handleDelete(m.id, false)}>
                            🗑
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Candidates panel ── */}
        {panel === 'candidates' && (
          <div>
            {/* Status filter */}
            <div style={{display:'flex', gap:4, marginBottom:12, flexWrap:'wrap'}}>
              {[['all','الكل'],['pending_review','بانتظار المراجعة'],['scored','تم التقييم'],
                ['approved','مقبولة'],['auto_approved','تلقائية'],['rejected','مرفوضة']].map(([v,l]) => (
                <button key={v} onClick={() => setCandStatus(v)}
                        style={btn(candStatus===v?'#2563eb':'#e2e8f0', candStatus!==v, true)}>
                  {l}
                </button>
              ))}
            </div>

            {candLoad && <div style={{padding:32, textAlign:'center', color:'#94a3b8'}}>تحميل…</div>}

            {!candLoad && (!candidates || candidates.length === 0) && (
              <div style={{textAlign:'center', padding:'32px 0', color:'#94a3b8'}}>
                <div>لا توجد مرشحات بهذا الفلتر</div>
              </div>
            )}

            {(candidates || []).map(c => {
              const wm    = c.score_breakdown?.watermark || c.watermark_score || 0
              const ts    = c.total_score || 0
              const tsClr = ts >= 0.75 ? '#059669' : ts >= 0.50 ? '#f59e0b' : '#dc2626'
              const canAct = ['pending_review', 'scored'].includes(c.status)
              const statusClr = { pending_review:'#f59e0b', scored:'#3b82f6', approved:'#059669',
                                   auto_approved:'#8b5cf6', rejected:'#dc2626', error:'#ef4444' }

              return (
                <div key={c.id} style={{...card, margin:'0 0 10px', padding:'10px 12px',
                                         display:'flex', gap:10, alignItems:'flex-start'}}>
                  <div style={{flexShrink:0, position:'relative'}}>
                    <img src={c.image_url || c.source_url}
                         style={{width:100, height:100, objectFit:'contain', borderRadius:6,
                                 border:'1.5px solid #e2e8f0', background:'#f8fafc'}}
                         onError={e => { e.target.src='' }}/>
                    {c.was_cleaned && (
                      <div style={{position:'absolute', bottom:2, right:2, background:'#7c3aed',
                                   color:'#fff', fontSize:8, borderRadius:4, padding:'1px 4px'}}>
                        ✨ نظّف
                      </div>
                    )}
                  </div>
                  <div style={{flex:1, minWidth:0}}>
                    <div style={{display:'flex', gap:4, flexWrap:'wrap', marginBottom:5}}>
                      {badge(statusClr[c.status]||'#6b7280', c.status)}
                      {badge(tsClr, `${score(ts)} مجموع`)}
                      {badge('#3b82f6', `${score(c.quality_score)} جودة`)}
                      {badge(wm_color(wm), `${score(wm)} وتر م.`)}
                      {badge('#64748b', c.source_type)}
                      {c.width && badge('#0ea5e9', `${c.width}×${c.height}`)}
                    </div>
                    <div style={{fontSize:10, color:'#94a3b8', overflow:'hidden', textOverflow:'ellipsis',
                                 whiteSpace:'nowrap', marginBottom:6}}>
                      <a href={c.source_url} target="_blank" rel="noreferrer" style={{color:'#3b82f6'}}>
                        {c.source_url?.slice(0,70)}…
                      </a>
                    </div>
                    {canAct && (
                      <div style={{display:'flex', gap:6}}>
                        <button style={btn('#059669', false, true)} disabled={busy}
                                onClick={() => handleApprove(c)}>
                          ✓ قبول كافتراضية
                        </button>
                        <button style={btn('#dc2626', true, true)} disabled={busy}
                                onClick={() => handleReject(c)}>
                          ✗ رفض
                        </button>
                        <button style={btn('#6b7280', true, true)} disabled={busy}
                                onClick={() => imageApi.redownload(c.id).then(() => refetchCands())}>
                          ↻ إعادة تنزيل
                        </button>
                      </div>
                    )}
                  </div>
                  {/* Score bar */}
                  <div style={{width:5, borderRadius:3, background:'#f1f5f9',
                                flexShrink:0, alignSelf:'stretch', minHeight:60}}>
                    <div style={{height:`${ts*100}%`, background:tsClr, borderRadius:3}}/>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* ── Upload panel ── */}
        {panel === 'upload' && (
          <div>
            <div style={{...card, padding:'20px 24px'}}>
              <div style={{fontWeight:700, fontSize:14, marginBottom:16}}>رفع صورة يدوياً</div>
              <label style={{display:'block', cursor:'pointer'}}>
                <div style={{border:'2px dashed #cbd5e1', borderRadius:10, padding:'32px 20px',
                             textAlign:'center', background:'#f8fafc',
                             ...(uploadFile ? {borderColor:'#2563eb', background:'#eff6ff'} : {})}}>
                  {uploadFile ? (
                    <div>
                      <div style={{fontSize:32, marginBottom:6}}>🖼️</div>
                      <div style={{fontWeight:600}}>{uploadFile.name}</div>
                      <div style={{fontSize:12, color:'#64748b'}}>
                        {(uploadFile.size / 1024).toFixed(0)} KB
                      </div>
                      {/* Preview */}
                      <img src={URL.createObjectURL(uploadFile)}
                           style={{maxWidth:200, maxHeight:200, marginTop:10,
                                   objectFit:'contain', borderRadius:8, border:'1px solid #e2e8f0'}}/>
                    </div>
                  ) : (
                    <div>
                      <div style={{fontSize:36, marginBottom:8}}>⬆️</div>
                      <div style={{fontWeight:600, marginBottom:4}}>اسحب صورة أو انقر للاختيار</div>
                      <div style={{fontSize:12, color:'#94a3b8'}}>JPEG، PNG، WebP — حجم أقصى 5 MB</div>
                    </div>
                  )}
                </div>
                <input type="file" accept="image/*" style={{display:'none'}}
                       onChange={e => setUploadFile(e.target.files[0] || null)}/>
              </label>

              <label style={{display:'flex', alignItems:'center', gap:8, marginTop:14, cursor:'pointer'}}>
                <input type="checkbox" checked={uploadPrimary}
                       onChange={e => setUploadPrimary(e.target.checked)}/>
                <span style={{fontSize:13}}>تعيين كصورة افتراضية للمنتج</span>
              </label>

              <div style={{display:'flex', gap:8, marginTop:14}}>
                <button style={btn('#2563eb')} disabled={!uploadFile || busy} onClick={handleUpload}>
                  {busy ? 'جارٍ الرفع…' : '⬆️ رفع الصورة'}
                </button>
                {uploadFile && (
                  <button style={btn('#6b7280', true)} onClick={() => setUploadFile(null)}>
                    إلغاء
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Search launch panel ── */}
        {panel === 'search' && (
          <div style={{...card, padding:'20px 24px'}}>
            <div style={{fontWeight:700, fontSize:14, marginBottom:8}}>🚀 إطلاق بحث جديد عن صورة</div>
            <div style={{fontSize:13, color:'#64748b', marginBottom:16, lineHeight:1.6}}>
              سيُطلق النظام مهمة بحث جديدة عن صور لهذا المنتج عبر جميع المصادر (drugs.com، DuckDuckGo، Bing…).
              النتائج ستظهر في تبويب "المرشحون" بعد انتهاء البحث.
            </div>
            <div style={{background:'#f0f9ff', border:'1px solid #bae6fd', borderRadius:8,
                         padding:'10px 14px', marginBottom:16, fontSize:13}}>
              <div><strong>المنتج:</strong> {item.name}</div>
              <div><strong>الكود:</strong> {item.softech_id}</div>
              <div><strong>الشركة:</strong> {item.producer_name || '—'}</div>
            </div>
            <button style={btn('#2563eb')} disabled={busy} onClick={handleLaunchSearch}>
              {busy ? 'جارٍ الإطلاق…' : '🔍 ابدأ البحث الآن'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}


// ── Gallery: Left panel — searchable item list ────────────────────────────────
function GalleryTab({ initialItemId = '' }) {
  const [selectedItem, setSelectedItem] = useState(null)
  const [q,            setQ]            = useState('')
  const [debouncedQ,   setDebouncedQ]   = useState('')
  const [hasImage,     setHasImage]     = useState('')
  const [catId,        setCatId]        = useState('')
  const [producer,     setProducer]     = useState('')
  const [page,         setPage]         = useState(1)
  const {data:meta} = useQuery({
    queryKey: ['img-filter-meta'],
    queryFn:  () => imageApi.filterMeta?.().then(r => r.data).catch(() => ({})),
    staleTime: 300000,
  })

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => { setDebouncedQ(q); setPage(1) }, 400)
    return () => clearTimeout(t)
  }, [q])

  // If opened from another tab with an item id, auto-select
  useEffect(() => {
    if (initialItemId) {
      // Try to fetch item info and auto-select
      import('../api/client').then(({ itemsApi }) => {
        itemsApi.get(initialItemId).then(r => {
          const d = r.data
          setSelectedItem({
            id: d.id, softech_id: d.softech_id, name: d.name,
            producer_name: d.producer_name || '', has_image: true, approved_count: 1, pending_count: 0,
          })
        }).catch(() => {})
      })
    }
  }, [initialItemId])

  const {data, isLoading} = useQuery({
    queryKey: ['img-product-search', debouncedQ, hasImage, catId, producer, page],
    queryFn:  () => imageApi.productSearch({
      q: debouncedQ, has_image: hasImage,
      category_id: catId || undefined,
      producer_name: producer || undefined,
      page, page_size: 25,
    }).then(r => r.data),
    keepPreviousData: true,
  })

  const results = data?.results || []
  const totalPages = data?.pages || 1

  const hasImageOpts = [
    {v:'', l:'الكل'},
    {v:'yes', l:'✓ لديها صورة'},
    {v:'no', l:'⊘ بلا صورة'},
    {v:'pending', l:'⏳ لديها مرشحون'},
  ]

  const cats      = meta?.categories || []
  const producers = meta?.producers  || []

  return (
    <div style={{display:'flex', gap:0, height:'calc(100vh - 200px)', minHeight:500}}>

      {/* ── Left: item list ─────────────────────────────────────────────────── */}
      <div style={{width: selectedItem ? '38%' : '100%', flexShrink:0, display:'flex',
                   flexDirection:'column', borderLeft: selectedItem ? '1px solid #e2e8f0' : 'none',
                   transition:'width .2s'}}>

        {/* Filters */}
        <div style={{padding:'12px 14px', background:'#f8fafc',
                     borderBottom:'1px solid #e2e8f0', flexShrink:0}}>
          <div style={{fontWeight:700, fontSize:14, marginBottom:10}}>🖼️ إدارة صور المنتجات</div>
          {/* Search input */}
          <input placeholder="ابحث باسم المنتج أو الكود…" value={q}
                 onChange={e => setQ(e.target.value)}
                 style={{...input, marginBottom:8}}/>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6, marginBottom:8}}>
            <select value={hasImage} onChange={e=>{setHasImage(e.target.value);setPage(1)}} style={selectStyle}>
              {hasImageOpts.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
            </select>
            <select value={catId} onChange={e=>{setCatId(e.target.value);setPage(1)}} style={selectStyle}>
              <option value="">كل الفئات</option>
              {cats.map(c=><option key={c.id} value={c.id}>{c.name_ar||c.name}</option>)}
            </select>
          </div>
          <select value={producer} onChange={e=>{setProducer(e.target.value);setPage(1)}} style={{...selectStyle, width:'100%'}}>
            <option value="">كل الشركات المصنعة</option>
            {producers.map(p=><option key={p} value={p}>{p}</option>)}
          </select>
          {data && (
            <div style={{fontSize:11, color:'#94a3b8', marginTop:6}}>
              {data.total.toLocaleString()} منتج
            </div>
          )}
        </div>

        {/* Item list */}
        <div style={{flex:1, overflowY:'auto'}}>
          {isLoading && <div style={{padding:32, textAlign:'center', color:'#94a3b8'}}>تحميل…</div>}
          {!isLoading && results.length === 0 && (
            <div style={{padding:32, textAlign:'center', color:'#94a3b8', fontSize:13}}>
              لا توجد نتائج
            </div>
          )}
          {results.map(item => (
            <div key={item.id}
                 onClick={() => setSelectedItem(item)}
                 style={{display:'flex', gap:10, alignItems:'center',
                         padding:'10px 14px', cursor:'pointer', borderBottom:'1px solid #f1f5f9',
                         background: selectedItem?.id === item.id ? '#eff6ff' : '#fff',
                         borderRight: selectedItem?.id === item.id ? '3px solid #2563eb' : '3px solid transparent'}}>
              {/* Thumbnail */}
              <div style={{width:52, height:52, borderRadius:6, overflow:'hidden',
                           border:'1.5px solid #e2e8f0', background:'#f8fafc', flexShrink:0,
                           display:'flex', alignItems:'center', justifyContent:'center'}}>
                {item.primary_thumb ? (
                  <img src={item.primary_thumb}
                       style={{width:'100%', height:'100%', objectFit:'contain'}}
                       onError={e => { e.target.style.display='none' }}/>
                ) : (
                  <span style={{fontSize:20, color:'#cbd5e1'}}>📷</span>
                )}
              </div>
              {/* Info */}
              <div style={{flex:1, minWidth:0}}>
                <div style={{fontWeight:600, fontSize:12, overflowWrap:'break-word'}}>
                  {item.name}
                </div>
                <div style={{fontSize:11, color:'#94a3b8'}}>{item.softech_id}</div>
                <div style={{display:'flex', gap:4, marginTop:3, flexWrap:'wrap'}}>
                  {item.has_image
                    ? <span style={{fontSize:10, background:'#dcfce7', color:'#166534',
                                     borderRadius:4, padding:'1px 5px', fontWeight:600}}>
                        ✓ {item.approved_count} صورة
                      </span>
                    : <span style={{fontSize:10, background:'#fef3c7', color:'#92400e',
                                     borderRadius:4, padding:'1px 5px', fontWeight:600}}>
                        بلا صور
                      </span>
                  }
                  {item.pending_count > 0 && (
                    <span style={{fontSize:10, background:'#fee2e2', color:'#991b1b',
                                   borderRadius:4, padding:'1px 5px', fontWeight:600}}>
                      {item.pending_count} مرشح
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center',
                       padding:'8px 14px', borderTop:'1px solid #e2e8f0', flexShrink:0,
                       background:'#f8fafc'}}>
            <button style={btn('#64748b', true, true)} disabled={page<=1}
                    onClick={() => setPage(p => p-1)}>
              ◀ السابق
            </button>
            <span style={{fontSize:12, color:'#64748b'}}>
              {page} / {totalPages}
            </span>
            <button style={btn('#64748b', true, true)} disabled={page>=totalPages}
                    onClick={() => setPage(p => p+1)}>
              التالي ▶
            </button>
          </div>
        )}
      </div>

      {/* ── Right: item image manager ───────────────────────────────────────── */}
      {selectedItem && (
        <div style={{flex:1, minWidth:0, display:'flex', flexDirection:'column',
                     background:'#fff', overflow:'hidden'}}>
          <ItemImageManager
            key={selectedItem.id}
            item={selectedItem}
            onClose={() => setSelectedItem(null)}
          />
        </div>
      )}

      {/* ── Empty state when nothing selected ─────────────────────────────── */}
      {!selectedItem && (
        <div style={{display:'none'}}/>
      )}
    </div>
  )
}


// ── Tab 7: Learning Insights ──────────────────────────────────────────────────
function InsightsTab() {
  const {data, isLoading} = useQuery({
    queryKey: ['img-insights'],
    queryFn:  () => imageApi.insights().then(r => r.data),
    staleTime: 60000,
  })

  const [brandFilter, setBrandFilter] = useState('')
  const [srcFilter,   setSrcFilter]   = useState('')

  const top     = data?.top_sources || []
  const filtered = top.filter(r =>
    (!brandFilter || r.brand.toLowerCase().includes(brandFilter.toLowerCase())) &&
    (!srcFilter   || r.source_type.includes(srcFilter))
  )

  const sourceTypes = [...new Set(top.map(r => r.source_type))].sort()

  const weightColor = w => w >= 1.2 ? '#059669' : w <= 0.8 ? '#dc2626' : '#f59e0b'

  return (
    <div>
      {/* Summary */}
      <div style={{display:'flex', gap:10, marginBottom:16}}>
        {[
          {label:'ماركات تم تعلمها', value: data?.total_brands_learned || 0, color:'#2563eb'},
          {label:'إجمالي الموافقات', value: data?.total_approved_tracked || 0, color:'#059669'},
          {label:'مصادر مرصودة',     value: sourceTypes.length, color:'#8b5cf6'},
        ].map(s => (
          <div key={s.label} style={{...card, flex:1, textAlign:'center', margin:0}}>
            <div style={{fontSize:26, fontWeight:700, color:s.color}}>{(s.value||0).toLocaleString()}</div>
            <div style={{fontSize:12, color:'#64748b', marginTop:2}}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Legend */}
      <div style={{...card, padding:'12px 20px', background:'#f0f9ff', border:'1px solid #bae6fd'}}>
        <div style={{fontSize:12, fontWeight:600, marginBottom:6, color:'#0369a1'}}>
          كيف يعمل نظام التعلم؟
        </div>
        <div style={{fontSize:12, color:'#0369a1', lineHeight:1.7}}>
          في كل مرة يوافق المستخدم على صورة أو يرفضها، يحدّث النظام هذا الجدول.
          المصادر ذات معدل موافقة أعلى تُعطى وزناً أكبر ({'>'}1.0 = تعزيز) في عمليات البحث التالية لنفس الماركة.
          المصادر ذات معدل موافقة منخفض تُقلّل أولويتها ({'<'}1.0 = تقليل).
        </div>
      </div>

      {/* Filters */}
      <div style={{...card, padding:'12px 20px'}}>
        <div style={{display:'flex', gap:12, alignItems:'center'}}>
          <input placeholder="بحث بالماركة…" value={brandFilter}
                 onChange={e => setBrandFilter(e.target.value)}
                 style={{...input, width:180}}/>
          <select value={srcFilter} onChange={e => setSrcFilter(e.target.value)} style={{...selectStyle, width:180}}>
            <option value="">كل المصادر</option>
            {sourceTypes.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <span style={{fontSize:13, color:'#64748b', marginRight:'auto'}}>
            {filtered.length} سجل
          </span>
        </div>
      </div>

      {isLoading && <div style={{padding:32, textAlign:'center', color:'#64748b'}}>جارٍ التحميل…</div>}

      {!isLoading && (
        <div style={{...card, padding:0, overflow:'hidden'}}>
          <table style={{width:'100%', borderCollapse:'collapse'}}>
            <thead>
              <tr style={{background:'#f8fafc'}}>
                {['الماركة','المصدر','موافق','مرشح','معدل الموافقة','متوسط الجودة','الوزن (تعزيز/تقليل)'].map(h => (
                  <th key={h} style={{padding:'10px 12px', textAlign:'right', fontSize:12,
                                     color:'#64748b', fontWeight:600, borderBottom:'1px solid #f1f5f9'}}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr key={i} style={{borderBottom:'1px solid #f8fafc'}}>
                  <td style={{padding:'8px 12px', fontWeight:700, fontSize:13}}>{r.brand}</td>
                  <td style={{padding:'8px 12px'}}>
                    {badge('#6b7280', r.source_type)}
                  </td>
                  <td style={{padding:'8px 12px', textAlign:'center', color:'#059669', fontWeight:600}}>{r.approved}</td>
                  <td style={{padding:'8px 12px', textAlign:'center', color:'#64748b'}}>{r.considered}</td>
                  <td style={{padding:'8px 12px', textAlign:'center'}}>
                    <div style={{fontWeight:700, color: r.approval_rate>=60?'#059669':r.approval_rate>=30?'#f59e0b':'#dc2626'}}>
                      {r.approval_rate}%
                    </div>
                    <div style={{height:4, borderRadius:2, background:'#f1f5f9', marginTop:3, width:60}}>
                      <div style={{width:r.approval_rate+'%', maxWidth:'100%', height:'100%', borderRadius:2,
                                   background:r.approval_rate>=60?'#059669':r.approval_rate>=30?'#f59e0b':'#dc2626'}}/>
                    </div>
                  </td>
                  <td style={{padding:'8px 12px', textAlign:'center', fontSize:12, color:'#64748b'}}>
                    {r.avg_quality_score}%
                  </td>
                  <td style={{padding:'8px 12px', textAlign:'center'}}>
                    <span style={{fontWeight:700, fontSize:14, color:weightColor(r.weight)}}>
                      {r.weight >= 1.0 ? '↑' : '↓'} {r.weight}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div style={{padding:32, textAlign:'center', color:'#94a3b8', fontSize:13}}>
              لا توجد بيانات تعلم بعد — قم بمراجعة بعض الصور أولاً
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ── Main Page ─────────────────────────────────────────────────────────────────
const TABS = [
  {id:'dashboard', label:'📊 لوحة التحكم'},
  {id:'review',    label:'👁️ قائمة المراجعة', badge:'pending_review'},
  {id:'batch',     label:'🚀 إطلاق دفعة'},
  {id:'revise',    label:'🔄 مراجعة شاملة'},
  {id:'history',   label:'📋 السجل'},
  {id:'gallery',   label:'🖼️ معرض المنتج'},
  {id:'insights',  label:'🧠 نتائج التعلم'},
]

export default function ImageEnrichmentPage() {
  const [tab,        setTab]       = useState('dashboard')
  const [galleryItem,setGalleryItem] = useState('')
  const {data:rpt}  = useQuery({queryKey:['img-report'],queryFn:()=>imageApi.report().then(r=>r.data),refetchInterval:30000})
  const {data:meta} = useQuery({queryKey:['img-filter-meta'],queryFn:()=>imageApi.filterMeta?.().then(r=>r.data).catch(()=>({})), staleTime:300000})

  const pending = rpt?.pending_review || 0

  const openGallery = (itemId) => {
    setGalleryItem(String(itemId || ''))
    setTab('gallery')
  }

  return (
    <div dir="rtl" style={{fontFamily:'Segoe UI,Tahoma,Arial,sans-serif',padding:'24px',maxWidth:1200,margin:'0 auto'}}>
      <div style={{marginBottom:18}}>
        <h1 style={{fontSize:22,fontWeight:700,margin:0}}>🖼️ محرك اكتساب صور المنتجات</h1>
        <p style={{fontSize:13,color:'#64748b',margin:'4px 0 0'}}>
          بحث آلي متعدد المصادر · كشف العلامات المائية وإزالتها · تقييم الجودة · مراجعة بشرية · تعلم آلي من الموافقات
        </p>
      </div>

      {/* Tabs */}
      <div style={{display:'flex',gap:2,marginBottom:18,borderBottom:'2px solid #e2e8f0',flexWrap:'wrap'}}>
        {TABS.map(t=>(
          <button key={t.id} onClick={()=>setTab(t.id)}
                  style={{padding:'9px 16px',border:'none',background:'none',cursor:'pointer',
                          fontSize:13,fontWeight:600,position:'relative',
                          color:tab===t.id?'#2563eb':'#64748b',
                          borderBottom:tab===t.id?'2.5px solid #2563eb':'2.5px solid transparent',marginBottom:-2}}>
            {t.label}
            {t.badge==='pending_review' && pending>0 && (
              <span style={{position:'absolute',top:4,right:4,background:'#ef4444',color:'#fff',
                            borderRadius:10,padding:'0 5px',fontSize:10,fontWeight:700}}>
                {pending}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab==='dashboard' && <DashboardTab/>}
      {tab==='review'    && <ReviewQueueTab onGallery={openGallery}/>}
      {tab==='batch'     && <BatchLaunchTab meta={meta}/>}
      {tab==='revise'    && <ReviseTab meta={meta}/>}
      {tab==='history'   && <HistoryTab/>}
      {tab==='gallery'   && <GalleryTab initialItemId={galleryItem}/>}
      {tab==='insights'  && <InsightsTab/>}
    </div>
  )
}
