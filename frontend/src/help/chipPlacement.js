/**
 * chipPlacement.js — where the help chips («جديد هنا؟» offer, the hints bar) sit (UAT W8).
 *
 * On a desktop page they sit bottom-start. On the phone shells (/m/*, /rider) the bottom is taken
 * by the tab bar and every form ends with its submit there, so a bottom chip covered the submit.
 * There they sit just under the slim sticky header, on the end side (away from the «رجوع» link),
 * so they stay visible without covering a form control or the tab bar.
 */
export function isPhoneShell(pathname) {
  const p = pathname || ''
  return p === '/m' || p.startsWith('/m/') || p === '/rider' || p.startsWith('/rider/')
}

export function helpChipPosition(pathname) {
  return isPhoneShell(pathname)
    ? 'top-14 end-3'                     // under the 2.5rem sticky header, clear of the tab bar
    : 'bottom-24 sm:bottom-4 start-4'
}
