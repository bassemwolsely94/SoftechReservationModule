/**
 * SortTh — a sortable column header: <th aria-sort> holding a full-width button (Enter / Space
 * work natively) with the label and the shared SortIcon. Spread `headerProps(key, type)` from
 * useSortableRows / useServerSort. Without `onSort` it renders a plain <th> (unsortable column).
 *
 *   <SortTh {...headerProps('net', 'number')} className="px-3 py-2" title="…">صافي</SortTh>
 */
import { SortIcon } from './DataTable'

// Enter / Space belong to the sort button, never to a surrounding useGridKeyboard grid
const keep = e => { if (e.key === 'Enter' || e.key === ' ') e.stopPropagation() }

export default function SortTh({ active = false, dir, onSort, ariaSort, className = '', title, children, ...rest }) {
  if (!onSort) return <th className={className} title={title} {...rest}>{children}</th>
  return (
    <th className={className} title={title} aria-sort={ariaSort || (active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none')} {...rest}>
      <button type="button" onClick={onSort} onKeyDown={keep}
              className="w-full bg-transparent p-0 cursor-pointer select-none hover:text-brand-700 [font:inherit] [color:inherit] [text-align:inherit]">
        {children}<span className="ms-1"><SortIcon active={active} dir={dir} /></span>
      </button>
    </th>
  )
}
