/**
 * ForecastingPage — Sales Forecast Engine Dashboard
 * Covers: trigger forecast run, view run history, accuracy tracking, seasonality
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { forecastingApi } from '../api/client'

function KpiCard({ label, value, sub, color = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value ?? '—'}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

const STATUS_COLORS = {
  running:   'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed:    'bg-red-100 text-red-700',
  partial:   'bg-amber-100 text-amber-800',
}

export default function ForecastingPage() {
  const qc   = useQueryClient()
  const [tab, setTab] = useState('runs')
  const [triggerMsg, setTriggerMsg] = useState(null)

  const { data: runsData, isLoading: runsLoading } = useQuery({
    queryKey: ['forecasting', 'runs'],
    queryFn:  () => forecastingApi.runs({}).then(r => r.data),
    enabled:  tab === 'runs',
    refetchInterval: tab === 'runs' ? 15_000 : false,
  })

  const { data: accuracyData, isLoading: accLoading } = useQuery({
    queryKey: ['forecasting', 'accuracy'],
    queryFn:  () => forecastingApi.accuracy({}).then(r => r.data),
    enabled:  tab === 'accuracy',
  })

  const { data: seasonalityData, isLoading: seasonalityLoading } = useQuery({
    queryKey: ['forecasting', 'seasonality'],
    queryFn:  () => forecastingApi.seasonality({}).then(r => r.data),
    enabled:  tab === 'seasonality',
  })

  const triggerRun = useMutation({
    mutationFn: () => forecastingApi.triggerForecast(),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['forecasting', 'runs'] })
      setTriggerMsg(res.data?.detail || 'تم بدء تشغيل التنبؤ بنجاح')
      setTimeout(() => setTriggerMsg(null), 5000)
    },
    onError: e => setTriggerMsg('❌ ' + (e.response?.data?.detail || 'خطأ في التشغيل')),
  })

  const computeSeasonality = useMutation({
    mutationFn: () => forecastingApi.computeSeasonality(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['forecasting', 'seasonality'] }),
  })

  const runs       = runsData?.results       || runsData       || []
  const accuracies = accuracyData?.results   || accuracyData   || []
  const seasonality= seasonalityData?.results|| seasonalityData|| []

  const latestRun   = runs[0]
  const completedRuns = runs.filter(r => r.status === 'completed').length

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">محرك التنبؤ بالمبيعات</h1>
          <p className="text-sm text-gray-500 mt-1">FEFO forecast · موسمية · دقة التنبؤ</p>
        </div>
        <button
          onClick={() => triggerRun.mutate()}
          disabled={triggerRun.isPending}
          className="px-5 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50 flex items-center gap-2"
        >
          {triggerRun.isPending ? '⏳ جاري التشغيل...' : '▶ تشغيل التنبؤ الآن'}
        </button>
      </div>

      {triggerMsg && (
        <div className={`mb-4 px-4 py-3 rounded-lg text-sm ${
          triggerMsg.startsWith('❌') ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-green-50 text-green-700 border border-green-200'
        }`}>
          {triggerMsg}
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <KpiCard label="آخر تشغيل" value={latestRun ? new Date(latestRun.started_at).toLocaleDateString('ar-EG') : '—'} />
        <KpiCard
          label="حالة آخر تشغيل"
          value={latestRun?.status || '—'}
          color={latestRun?.status === 'completed' ? 'text-green-600' : latestRun?.status === 'failed' ? 'text-red-600' : 'text-amber-600'}
        />
        <KpiCard label="التشغيلات المكتملة" value={completedRuns} />
        <KpiCard
          label="متوسط دقة التنبؤ (MAPE)"
          value={accuracies.length ? `${Math.round(accuracies.reduce((s, a) => s + (a.mape || 0), 0) / accuracies.length)}%` : '—'}
          color="text-brand-600"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6">
        {[
          { key: 'runs',        label: '🏃 سجل التشغيلات' },
          { key: 'accuracy',    label: '🎯 دقة التنبؤ'    },
          { key: 'seasonality', label: '📅 مؤشرات الموسمية' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Runs tab */}
      {tab === 'runs' && (
        runsLoading ? (
          <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
        ) : runs.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <div className="text-4xl mb-3">📊</div>
            <p>لم يتم تشغيل أي تنبؤ بعد</p>
            <button onClick={() => triggerRun.mutate()} disabled={triggerRun.isPending}
              className="mt-4 px-5 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50">
              تشغيل أول تنبؤ
            </button>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">بدأ في</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">انتهى في</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الأصناف المعالجة</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">بواسطة</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">ملاحظات</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-700">
                      {r.started_at ? new Date(r.started_at).toLocaleString('ar-EG') : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {r.finished_at ? new Date(r.finished_at).toLocaleString('ar-EG') : r.status === 'running' ? '⏳ جاري...' : '—'}
                    </td>
                    <td className="px-4 py-3">{r.items_processed ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[r.status] || 'bg-gray-100 text-gray-600'}`}>
                        {r.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">{r.triggered_by_name || r.triggered_by || 'scheduler'}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{r.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Accuracy tab */}
      {tab === 'accuracy' && (
        accLoading ? (
          <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
        ) : accuracies.length === 0 ? (
          <div className="text-center py-16 text-gray-400">لا توجد بيانات دقة بعد</div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الصنف</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الفترة</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">التنبؤ</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الفعلي</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">MAPE</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">MAE</th>
                </tr>
              </thead>
              <tbody>
                {accuracies.map(a => (
                  <tr key={a.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">{a.item_name || a.item || '—'}</td>
                    <td className="px-4 py-3 text-gray-500">{a.period_label || a.period || '—'}</td>
                    <td className="px-4 py-3">{a.forecast_qty ?? '—'}</td>
                    <td className="px-4 py-3">{a.actual_qty ?? <span className="text-gray-300">غير مدخل</span>}</td>
                    <td className="px-4 py-3">
                      {a.mape != null ? (
                        <span className={`font-medium ${a.mape < 15 ? 'text-green-600' : a.mape < 30 ? 'text-amber-600' : 'text-red-600'}`}>
                          {a.mape.toFixed(1)}%
                        </span>
                      ) : '—'}
                    </td>
                    <td className="px-4 py-3">{a.mae != null ? a.mae.toFixed(1) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Seasonality tab */}
      {tab === 'seasonality' && (
        <div>
          <div className="flex justify-end mb-4">
            <button
              onClick={() => computeSeasonality.mutate()}
              disabled={computeSeasonality.isPending}
              className="px-4 py-2 text-sm border border-brand-600 text-brand-600 rounded-lg hover:bg-brand-50 disabled:opacity-50"
            >
              {computeSeasonality.isPending ? 'جاري الحساب...' : '↺ إعادة حساب الموسمية'}
            </button>
          </div>
          {seasonalityLoading ? (
            <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
          ) : seasonality.length === 0 ? (
            <div className="text-center py-16 text-gray-400">
              <p>لا توجد مؤشرات موسمية بعد</p>
              <button onClick={() => computeSeasonality.mutate()} disabled={computeSeasonality.isPending}
                className="mt-4 px-5 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700 disabled:opacity-50">
                حساب الموسمية
              </button>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الصنف / التصنيف</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الشهر</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">مؤشر الموسمية</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">آخر تحديث</th>
                  </tr>
                </thead>
                <tbody>
                  {seasonality.map(s => (
                    <tr key={s.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium">{s.item_name || s.category || '—'}</td>
                      <td className="px-4 py-3 text-gray-500">{s.month}</td>
                      <td className="px-4 py-3">
                        <span className={`font-semibold ${
                          s.index_value > 1.2 ? 'text-green-600' :
                          s.index_value < 0.8 ? 'text-red-600' :
                          'text-gray-700'
                        }`}>
                          {s.index_value != null ? s.index_value.toFixed(2) : '—'}
                        </span>
                        {s.index_value > 1 && <span className="text-xs text-gray-400 mr-1">▲ موسم مرتفع</span>}
                        {s.index_value < 1 && <span className="text-xs text-gray-400 mr-1">▼ موسم منخفض</span>}
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {s.updated_at ? new Date(s.updated_at).toLocaleDateString('ar-EG') : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
