/**
 * Honeypot.jsx - hidden bot trap for the public forms (security N6).
 * Humans never see or reach it. The HTML name/id is deliberately NOT "website" (browsers and
 * password managers autofill that and would silently drop a real customer); only the JSON key the
 * page sends to the server is `website`. Hidden by clipping, not by a left offset or display:none
 * (an offset adds horizontal scroll on RTL pages; display:none is skipped by simple bots).
 */
const HIDDEN = {
  position: 'absolute', width: 1, height: 1, margin: -1, padding: 0, border: 0,
  overflow: 'hidden', clipPath: 'inset(50%)', whiteSpace: 'nowrap', opacity: 0, pointerEvents: 'none',
}

export default function Honeypot({ value, onChange }) {
  return (
    <input type="text" name="hp_contact_ref" id="hp_contact_ref" value={value}
      onChange={e => onChange(e.target.value)} autoComplete="off" tabIndex={-1}
      aria-hidden="true" style={HIDDEN} />
  )
}
