/**
 * Which search row the POS may add WITHOUT the cashier choosing it (pharmacy safety, rule 4).
 *
 * The server decides the tier (apps/catalog/wildcard.item_search); this only reads it:
 *  - a queued Enter (pressed while the results were still loading) adds the first row only when
 *    it is a plain text / code hit — `code`, `starts`, `word`, `contains`, `any_order` — with no
 *    chip flag. A learned / sound / approx / ingredient / synonym / code_part row is shown,
 *    highlighted, and waits for the cashier's own Enter or click.
 *  - a camera scan adds a row on its own only when it is an exact code / barcode hit (`code`).
 */
export const EXACTISH_TIERS = ['code', 'starts', 'word', 'contains', 'any_order']

// the row flags the server sets for the picker chips (softech_search `_rows`)
export const CHIP_FLAGS = ['learned', 'sound', 'approx', 'ingredient', 'code_part', 'synonym']

export function isExactishRow(row) {
  if (!row || !EXACTISH_TIERS.includes(row.tier)) return false
  return !CHIP_FLAGS.some(f => row[f])
}

export function isExactCodeRow(row) {
  return !!row && row.tier === 'code' && !CHIP_FLAGS.some(f => row[f])
}
