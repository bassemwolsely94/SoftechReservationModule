/**
 * POS semantic icon set — zero-dependency inline SVG (no lucide/heroicons install).
 * Every icon strokes `currentColor` so it inherits the tone color from its badge/chip
 * (theme-aware, light + dark). One <Icon name=…/> is the single source; never inline
 * ad-hoc emoji/SVG in POS components again — add a name here instead.
 *
 * Names are SEMANTIC (what it means), not shape names — see semantics.js MEANINGS.
 */
const P = {
  // status
  check:     'M20 6 9 17l-5-5',
  alert:     'M12 9v4 M12 17h.01 M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z',
  x:         'M18 6 6 18 M6 6l12 12',
  info:      'M12 16v-4 M12 8h.01 M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z',
  block:     'M4.93 4.93l14.14 14.14 M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z',
  // pharmacy / product
  package:   'M21 8-9-4-9 4 9 4 9-4Z M3 8v8l9 4 9-4V8 M12 12v8',
  snow:      'M12 2v20 M4.5 7l15 10 M19.5 7l-15 10 M8 4l4 3 4-3 M8 20l4-3 4 3',
  rx:        'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z M14 2v6h6 M8 13h5 M8 17h4',
  pill:      'M10.5 20.5a4.95 4.95 0 0 1-7-7l6-6a4.95 4.95 0 1 1 7 7l-6 6Z M8.5 8.5l7 7',
  usercheck: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M16 11l2 2 4-4',
  // commerce
  tag:       'M12.6 2.7 21 11a2 2 0 0 1 0 2.8l-7.2 7.2a2 2 0 0 1-2.8 0L2.7 12.6A2 2 0 0 1 2 11V4a2 2 0 0 1 2-2h7a2 2 0 0 1 1.6.7Z M7 7h.01',
  gift:      'M20 12v9H4v-9 M2 7h20v5H2z M12 22V7 M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7 M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7',
  star:      'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14l-5-4.87 6.91-1.01L12 2Z',
  repeat:    'M17 2l4 4-4 4 M3 11v-1a4 4 0 0 1 4-4h14 M7 22l-4-4 4-4 M21 13v1a4 4 0 0 1-4 4H3',
  clock:     'M12 6v6l4 2 M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z',
  trending:  'M22 7 13.5 15.5l-5-5L2 17 M16 7h6v6',
  // fulfillment / omni
  store:     'M3 9l1.5-5h15L21 9 M4 9v11h16V9 M9 20v-6h6v6',
  truck:     'M10 17h4V5H2v12h3 M20 17h-3v-6h4l1 3v3h-2 M7.5 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4 M17.5 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4',
  bookmark:  'M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2Z',
  transfer:  'M8 3 4 7l4 4 M4 7h16 M16 21l4-4-4-4 M20 17H4',
  phone:     'M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3-8.6A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.3 1.8.6 2.7a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.4-1.2a2 2 0 0 1 2.1-.5c.9.3 1.8.5 2.7.6a2 2 0 0 1 1.7 2Z',
  chat:      'M21 11.5a8.4 8.4 0 0 1-9 8.4 8.4 8.4 0 0 1-3.9-.9L3 21l1.9-4.1A8.4 8.4 0 1 1 21 11.5Z',
  // actions
  plus:      'M12 5v14 M5 12h14',
  minus:     'M5 12h14',
  search:    'M21 21l-4.3-4.3 M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z',
}

export function Icon({ name, size = 14, className = '', strokeWidth = 2, ...rest }) {
  const d = P[name]
  if (!d) return null
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
         strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
         className={`inline-block shrink-0 ${className}`} aria-hidden="true" {...rest}>
      {d.split(' M').map((seg, i) => <path key={i} d={(i ? 'M' : '') + seg} />)}
    </svg>
  )
}

export const ICON_NAMES = Object.keys(P)
