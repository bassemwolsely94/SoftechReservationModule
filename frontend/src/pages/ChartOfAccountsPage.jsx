/**
 * ChartOfAccountsPage.jsx
 * Route: /finance/coa
 *
 * Interactive Chart of Accounts — flat table with type filter + search.
 * Tree view available via "عرض الشجرة" toggle.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { financeApi } from '../api/client'

const TYPE_AR = {
  asset:     'أصول',
  liability: 'التزامات',
  equity:    'حقوق الملكية',
  revenue:   'إيرادات',
  expense:   'مصروفات',
  cogs:      'تكلفة المبيعات',
  contra:    'مقابل',
  memo:      'إيضاح',
  unknown:   'غير محدد',
}

const TYPE_COLORS = {
  asset:     'bg-blue-100 text-blue-700',
  liability: 'bg-red-100 text-red-700',
  equity:    'bg-purple-100 text-purple-700',
  revenue:   'bg-green-100 text-green-700',
  expense:   'bg-orange-100 text-orange-700',
  cogs:      'bg-yellow-100 text-yellow-700',
  other:     'bg-gray-100 text-gray-600',
}

const TYPE_OPTIONS = ['', 'asset', 'liability', 'equity', 'revenue', 'expense', 'cogs', 'contra', 'memo', 'unknown']

function TreeNode({ node, depth = 0 }) {
  const [open, setOpen] = useState(depth < 2)
  const hasChildren = node.children?.length > 0
  return (
    <div className="text-sm">
      <div
        className="flex items-center gap-2 py-1 px-2 rounded hover:bg-gray-50 cursor-pointer"
        style={{ paddingRight: `${8 + depth * 16}px` }}
        onClick={() => hasChildren && setOpen(o => !o)}
      >
        {hasChildren
          ? <span className="text-gray-400 w-4 text-center">{open ? '▾' : '▸'}</span>
          : <span className="w-4 text-center text-gray-300">•</span>
        }
        <span className="font-mono text-gray-500 text-xs w-24 shrink-0">{node.code}</span>
        <span className="text-gray-800 flex-1">{node.name_ar || node.name}</span>
        <span className={`px-1.5 py-0.5 rounded text-xs ${TYPE_COLORS[node.account_type] || TYPE_COLORS.other}`}>
          {TYPE_AR[node.account_type] || node.account_type}
        </span>
      </div>
      {open && hasChildren && (
        <div>
          {node.children.map(child => (
            <TreeNode key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function ChartOfAccountsPage() {
  const [search,    setSearch]    = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [view, setView]           = useState('flat')  // 'flat' | 'tree'

  const { data: flatData, isLoading: flatLoading } = useQuery({
    queryKey: ['finance-accounts', typeFilter, search],
    queryFn:  () => financeApi.accounts({
      account_type: typeFilter || undefined,
      search: search || undefined,
    }).then(r => r.data),
    staleTime: 120_000,
    enabled: view === 'flat',
  })

  const { data: treeData, isLoading: treeLoading } = useQuery({
    queryKey: ['finance-account-tree'],
    queryFn:  () => financeApi.accountTree().then(r => r.data),
    staleTime: 300_000,
    enabled: view === 'tree',
  })

  const accounts = flatData?.results || flatData || []
  const tree     = treeData || []

  return (
    <div className="space-y-4" dir="rtl">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-base font-semibold text-gray-700">دليل الحسابات</h2>
        <div className="flex gap-2 mr-auto flex-wrap">
          {/* View toggle */}
          <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm">
            {['flat','tree'].map(v => (
              <button key={v}
                onClick={() => setView(v)}
                className={`px-3 py-1.5 ${view === v ? 'bg-green-600 text-white' : 'text-gray-600 hover:bg-gray-50'}`}
              >
                {v === 'flat' ? 'قائمة' : 'شجرة'}
              </button>
            ))}
          </div>

          {view === 'flat' && (
            <>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="بحث بالاسم أو الكود…"
                className="border rounded-lg px-3 py-1.5 text-sm w-48 focus:ring-2 focus:ring-green-500"
              />
              <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
                className="border rounded-lg px-3 py-1.5 text-sm">
                {TYPE_OPTIONS.map(t => (
                  <option key={t} value={t}>{t ? TYPE_AR[t] : 'جميع الأنواع'}</option>
                ))}
              </select>
            </>
          )}
        </div>
      </div>

      {/* Loading */}
      {(flatLoading || treeLoading) && (
        <div className="text-center py-12 text-gray-400 animate-pulse">جارٍ تحميل الحسابات…</div>
      )}

      {/* Flat list */}
      {view === 'flat' && !flatLoading && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {accounts.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-4xl mb-2">🗂️</div>
              <div className="text-gray-500 text-sm">
                لا توجد حسابات. قم بتشغيل المزامنة أو أضف حسابات يدوياً من لوحة Django Admin.
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50 text-xs text-gray-500">
                    <th className="px-3 py-2 text-right">الكود</th>
                    <th className="px-3 py-2 text-right">الاسم</th>
                    <th className="px-3 py-2 text-center">النوع</th>
                    <th className="px-3 py-2 text-center">الطبيعة</th>
                    <th className="px-3 py-2 text-center">المستوى</th>
                    <th className="px-3 py-2 text-center">ورقة</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {accounts.map(acc => (
                    <tr key={acc.id} className="hover:bg-gray-50 text-sm">
                      <td className="px-3 py-2 font-mono text-gray-500">{acc.code}</td>
                      <td className="px-3 py-2 text-gray-800">{acc.name_ar || acc.name}</td>
                      <td className="px-3 py-2 text-center">
                        <span className={`px-2 py-0.5 rounded-full text-xs ${TYPE_COLORS[acc.account_type] || TYPE_COLORS.other}`}>
                          {TYPE_AR[acc.account_type] || acc.account_type}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className={`text-xs font-medium ${acc.nature === 'debit' ? 'text-blue-600' : 'text-orange-600'}`}>
                          {acc.nature === 'debit' ? 'مدين' : 'دائن'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center text-gray-500">{acc.level}</td>
                      <td className="px-3 py-2 text-center">
                        {acc.is_leaf
                          ? <span className="text-green-500 text-xs">✓</span>
                          : <span className="text-gray-300 text-xs">—</span>
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tree view */}
      {view === 'tree' && !treeLoading && (
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          {tree.length === 0
            ? <div className="text-center py-8 text-gray-400 text-sm">لا يوجد هيكل حسابي — لم تُزامن الحسابات بعد</div>
            : tree.map(root => <TreeNode key={root.id} node={root} depth={0} />)
          }
        </div>
      )}
    </div>
  )
}
