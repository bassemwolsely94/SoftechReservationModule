/**
 * DataTable.jsx — reusable sortable + resizable + scrollable table
 *
 * Column definition shape:
 *   key        string           data key on each row object
 *   label      string           header text
 *   type       'text'|'number'|'currency'|'percent'|'integer'
 *              used for sort comparison (text = locale; others = numeric)
 *   width      number           initial column width in px (default 120)
 *   minWidth   number           minimum width during resize (default 60)
 *   sortable   bool             (default true)
 *   render     (value, row, i) => ReactNode   custom cell content
 *   headerClass  string         extra classes on <th>
 *   cellClass    string         extra classes on <td>
 *   align      'right'|'left'|'center'   (default 'right' — RTL)
 *
 * Props:
 *   columns       array of column defs
 *   rows          array of data objects
 *   rowKey        (row, i) => key  (default: index)
 *   rowClassName  (row, i) => string
 *   emptyLabel    string shown when rows is empty
 *   stickyHeader  bool (default true)
 *   maxHeight     CSS string e.g. 'calc(100vh - 300px)' — enables vertical scroll
 *   defaultSort   { key, dir: 'asc'|'desc' }
 *   theadClass    string extra classes on <thead>
 */
import { useState, useRef, useMemo, useCallback } from 'react'

function SortIcon({ active, dir }) {
  if (!active) {
    return (
      <span className="inline-block opacity-25 ml-1 text-[10px] leading-none">↕</span>
    )
  }
  return (
    <span className="inline-block text-brand-600 ml-1 text-[10px] leading-none font-bold">
      {dir === 'asc' ? '↑' : '↓'}
    </span>
  )
}

export default function DataTable({
  columns = [],
  rows = [],
  rowKey,
  rowClassName,
  emptyLabel = 'لا توجد بيانات',
  stickyHeader = true,
  maxHeight,
  defaultSort,
  theadClass = 'bg-gray-50 text-xs text-gray-500',
}) {
  const [sortKey, setSortKey] = useState(defaultSort?.key ?? null)
  const [sortDir, setSortDir] = useState(defaultSort?.dir ?? 'desc')
  const [widths,  setWidths]  = useState(() => columns.map(c => c.width ?? 120))

  // ── resize tracking via ref (no stale closures) ──────────────────────
  const dragRef = useRef(null)

  const onResizeStart = useCallback((e, colIndex) => {
    e.preventDefault()
    e.stopPropagation()
    const startX     = e.clientX
    const startWidth = widths[colIndex]
    dragRef.current  = { colIndex, startX, startWidth }

    const onMove = (ev) => {
      if (!dragRef.current) return
      const { colIndex: ci, startX: sx, startWidth: sw } = dragRef.current
      const minW = columns[ci]?.minWidth ?? 60
      const newW = Math.max(minW, sw + ev.clientX - sx)
      setWidths(prev => {
        const next = [...prev]
        next[ci] = newW
        return next
      })
    }

    const onUp = () => {
      dragRef.current = null
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup',   onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
  }, [widths, columns])

  // ── column sort toggle ────────────────────────────────────────────────
  const handleSort = useCallback((key, type) => {
    setSortKey(prev => {
      if (prev === key) {
        setSortDir(d => d === 'asc' ? 'desc' : 'asc')
        return key
      }
      // First click: asc for text, desc for numbers
      setSortDir(type === 'text' ? 'asc' : 'desc')
      return key
    })
  }, [])

  // ── sorted rows ───────────────────────────────────────────────────────
  const sortedRows = useMemo(() => {
    if (!sortKey) return rows
    const col  = columns.find(c => c.key === sortKey)
    const type = col?.type ?? 'text'
    return [...rows].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey]
      let cmp
      if (type === 'text') {
        cmp = String(av ?? '').localeCompare(String(bv ?? ''), 'ar-EG')
      } else {
        cmp = (Number(av) || 0) - (Number(bv) || 0)
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [rows, sortKey, sortDir, columns])

  const totalWidth = widths.reduce((a, b) => a + b, 0)

  const containerStyle = {}
  if (maxHeight) {
    containerStyle.maxHeight  = maxHeight
    containerStyle.overflowY  = 'auto'
  }

  return (
    <div className="overflow-x-auto w-full" style={containerStyle}>
      <table
        style={{
          tableLayout: 'fixed',
          width: totalWidth,
          borderCollapse: 'collapse',
        }}
      >
        <thead
          className={`${theadClass} ${stickyHeader ? 'sticky top-0 z-10' : ''}`}
          style={stickyHeader ? { boxShadow: '0 1px 0 #e5e7eb' } : {}}
        >
          <tr>
            {columns.map((col, ci) => {
              const canSort = col.sortable !== false
              const align   = col.align ?? 'right'
              return (
                <th
                  key={col.key}
                  style={{
                    width:    widths[ci],
                    minWidth: col.minWidth ?? 60,
                    position: 'relative',
                    userSelect: 'none',
                  }}
                  className={`px-3 py-2.5 whitespace-nowrap font-semibold
                    text-${align}
                    ${canSort ? 'cursor-pointer hover:bg-gray-100' : ''}
                    ${col.headerClass ?? ''}
                  `}
                  onClick={() => canSort && handleSort(col.key, col.type ?? 'text')}
                >
                  {col.label}
                  {canSort && (
                    <SortIcon active={sortKey === col.key} dir={sortDir} />
                  )}

                  {/* Resize handle — thin draggable strip at the right edge */}
                  <div
                    onMouseDown={e => onResizeStart(e, ci)}
                    onClick={e => e.stopPropagation()}
                    title="اسحب لتغيير العرض"
                    style={{
                      position: 'absolute',
                      right:  0,
                      top:    0,
                      bottom: 0,
                      width:  5,
                      cursor: 'col-resize',
                      zIndex: 1,
                    }}
                    className="group"
                  >
                    <div className="absolute inset-0 rounded-sm opacity-0 group-hover:opacity-100 bg-brand-400 transition-opacity" />
                  </div>
                </th>
              )
            })}
          </tr>
        </thead>

        <tbody>
          {sortedRows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="text-center py-14 text-gray-400 text-sm"
              >
                {emptyLabel}
              </td>
            </tr>
          ) : (
            sortedRows.map((row, i) => (
              <tr
                key={rowKey ? rowKey(row, i) : i}
                className={`border-b border-gray-50 hover:bg-gray-50 transition-colors ${
                  rowClassName ? rowClassName(row, i) : ''
                }`}
              >
                {columns.map((col, ci) => {
                  const align = col.align ?? 'right'
                  const raw   = row[col.key]
                  return (
                    <td
                      key={col.key}
                      style={{ width: widths[ci] }}
                      className={`px-3 py-2 text-sm whitespace-nowrap text-${align} ${col.cellClass ?? ''}`}
                    >
                      {col.render
                        ? col.render(raw, row, i)
                        : raw ?? '—'}
                    </td>
                  )
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
