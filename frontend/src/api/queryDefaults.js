/**
 * Global TanStack Query defaults (performance Stage 5).
 *
 * - refetchIntervalInBackground: false — no interval refetch while the tab is hidden. It is the
 *   library default too; it is set explicitly so it stays that way, and polling.test.js fails if a
 *   screen turns it back on.
 * - staleTime 30 s — a mount or a window-focus refetch does not repeat a request made seconds ago.
 * - retry 1 — one retry, then the screen shows its error strip.
 */
export const QUERY_DEFAULTS = { staleTime: 30_000, retry: 1, refetchIntervalInBackground: false }
