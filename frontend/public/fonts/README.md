# ElRezeiky brand fonts

Drop the licensed font files here with these **exact filenames** (case-sensitive).
The `@font-face` rules in `src/index.css` reference them; `.woff2` is preferred,
`.ttf`/`.otf` is the fallback. Providing `.woff2` gives the smallest, fastest load.

| Purpose            | Font                 | Filename(s)                             |
|--------------------|----------------------|-----------------------------------------|
| Arabic (body)      | Jozoor               | `Jozoor.woff2` (+ `Jozoor.ttf`)         |
| Latin / headings   | Harabara Mais Demo   | `HarabaraMaisDemo.woff2` (+ `.ttf`)     |
| Numbers / KPIs     | Berlin Sans FB       | `BerlinSansFB.woff2` (+ `.ttf`)         |

## Notes
- Until the files are present, the app falls back to Cairo (Arabic) and a system
  geometric sans (Latin) automatically — nothing breaks.
- If you only have `.ttf`/`.otf`, convert to `.woff2` for production
  (e.g. `fonttools` or https://cloudconvert.com). Keeping both is fine.
- If a font ships multiple weights as separate files, either use a variable font
  (single file, `font-weight: 100 900`) or add per-weight `@font-face` blocks in
  `src/index.css`.
