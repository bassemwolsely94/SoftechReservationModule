# Stage 7: Critic review (design, structure, style)

**Target and reviewers**
- Target: `docs/security/2026-11-05-full-project-test-plan.md`, FeatureRange lines 1–83.
- Reviewers, each in a fresh context: `egm-design` (standard: feature-spec), `egm-structural`
  (standard: feature-spec) and `egm-style` (persona rules). All three completed.

**Result after de-duplication:** 1 Blocker, 13 Majors, 21 Nits.

**What the reviewers confirmed.** Several claims in the plan were checked and hold:
- the manifest has 60 entries, 36 of them `kind=write`;
- 3 write sites have `idempotency=None`;
- `PENDING.md` holds only W-1;
- `RBAC_ENFORCED_ROLES` defaults to `accountant`;
- the frontend has only dev and build scripts;
- `INSTALLED_APPS` holds 67 apps. The Stage 5 count of 65 came from `apps.py` files.

## 🔴 Blocker

**B1. No alternatives considered** (design #1, structural #1; lines 1–83)

The plan takes one path and never weighs the options against it:
- a full re-check versus a delta round (late modules plus batches 7 and 8);
- ranking apps by counting test files versus by coverage;
- serial, green-gated batches versus running independent ones in parallel.

**Fix:** add an "Alternatives considered" section that gives each rejected option and the
concrete reason it was rejected.

## 🟡 Majors

**M1. No Risks & Limits and no Non-goals; goals and problem are mixed** (design #2, structural #2–3; lines 8–83)

- Round 1's non-goals (no VPS pen-test, no rewrites, no pytest) are not restated.
- The plan's own risks have no mitigation next to them: CI time, the live office writer, shared
  test DBs, Playwright flakiness, and stop-and-ask items stalling the green-gated chain.

**Fix:** add sections for Problem, Goals, Non-goals and Risks (risk, likelihood, mitigation).

**M2. The stop-and-ask exit rule is unresolved** (design #2, comprehension #10; lines 25, 41–47, 86)

"Fixed in the same batch, not known failing" clashes with fixes that wait for the owner.

**Fix:** state whether the round-1 `@pending` / `PENDING.md` mechanism still applies when the
owner holds or declines a fix.

**M3. The office writer is not protected by the rules** (design #4; lines 29–36, 62)

- The §2 rules protect only `manage.py test`.
- The office laptop is a live production writer with 16 flags ON, and `run_startup_checks()`
  returns early under `test`.
- R1 changes exactly these writers.

**Fix:** add a hard rule that round-2 development and verification run on a non-writer copy
(`WRITER_INSTANCE=False`). Define "production" as the VPS and the office writer.

**M4. The write-site baseline hides bigger gaps** (design #5; line 61)

- 13 of the 36 real writes have `dry_run_default=False`. R1's "dry-run is the default" would fail
  13 proofs, most of them stop-and-ask.
- Weak or racy guards are not counted: MAX+1 races, no row locks, approve_isr re-stamping.

**Fix:** report these in §3, and reword R1 to "dry-run default or a documented reason".

**M5. No audit baseline** (design #6; lines 23, 61)

The manifest records known audit gaps: force_replication logs only, complete_half_reversal does
not audit failures, the motalba before-value is not kept, and command paths record no actor.
Without a baseline, "every sensitive action is audited" cannot be measured.

**Fix:** add an "Audit gaps" row.

**M6. "Sweeps cover every route" overstates, and baseline debt is missing** (design #7, style #3, zoom-out M1; line 60)

- The sweeps enumerate every route, but `role_unproven` holds about 460 lines.
- `role_crashes` and `role_overblocks` (463) are listed, `sql_from_text` holds 222, and the
  bandit baseline holds 568.
- The canary sweep covers list routes and per-model planting only.

**Fix:** reword line 60, add a baseline-count row, and assign the debt to batches.

**M7. "No weakening" doesn't cover inline suppressions** (design #8, style #2; lines 37–40, 59)

- The red CI was cleared by four `# nosec B608` comments, bypassing the reviewed bandit-baseline
  route.
- Line 59 also calls a suppression a "fix".

**Fix:**
- Extend the rule to `nosec`, `noqa`, allow-list `# reason:` lines and pending markers.
- Consider a ratchet that counts them.
- Reword line 59.

**M8. Aim 2 (break-ins) has no batch** (design #3; lines 12–13, 19)

There is no auth, session, WebSocket or network-zone delta for the new modules.

**Fix:** add one, or list it as a non-goal with a reason.

**M9. The feature part doesn't describe the approach** (structural #4; lines 1–83)

How round 2 works (re-run the sweeps, add delta cases, close specific gaps) appears only in §4.

**Fix:** add a short approach section.

**M10. Undefined terms and unlinked references** (structural #5, comprehension #1–8, #12)

- **Undefined terms:** SOFTECH, writer and reader copy, sweeps and canaries, baseline and STALE,
  motalba, the W-n ID scheme.
- **References with no link:** "doc 35", "doc 33", "Project 1–5", N0–N6, CLAUDE.md batch rules.

**Fix:** add a short system overview, a glossary, and links.

**M11. Aim 4's wording forbids all SOFTECH reads** (style #4; lines 20–21)

**Fix:** reach SOFTECH only through the guarded connection (reads) and the manifest-registered
writers (writes).

**M12. Line 25 says the test is fixed, not the hole** (style #5)

**Fix:** "A hole that a test exposes is closed in the same batch; the test is not left known
failing."

**M13. Aim 5 "no big bugs" can't be measured** (style #6; line 22)

**Fix:** make the following sentence the definition: totals deterministic, writes idempotent,
sensitive actions audited.

## 🟢 Nits

| # | Source | Lines | Finding |
|---|---|---|---|
| N1 | design #9, style #1 | 58–59 | "All pass in CI" contradicts "CI at 1929463d pending". |
| N2 | design #10 | 48–50 | Named per-user grants and the owner-decision sources are not identified as authoritative. |
| N3 | design #11 | 34, 63 | "Production" is ambiguous (VPS or office writer?). |
| N4 | design #12, style #8 | 11, 74–82 | The late-module list is unmapped to batches; it omits stock_audit, access and trace, and mixes apps with features. |
| N5 | style, structural #9 | 61 | "Real write" is undefined: name the `kind` values. TEST_SUITE.md still says 59 sites. |
| N6 | style | 61–62 | The motalba risk (no guard plus its flag ON) is not stated as a risk. |
| N7 | style | 63 | "Views enforce on their own" and "log mode" are vague. |
| N8 | style | 64 | The "Pending" label is unclear. |
| N9 | style, structural #6 | 3–6 | The header mixes links and code spans; the slash command is workflow metadata. |
| N10 | style, structural #12 | 10 | Write ISO dates; "merged to `main`". |
| N11 | style | 12–15 | "Same aims" is stated twice. |
| N12 | style | 33 | "Charges anything" should be "triggers a payment". |
| N13 | style | 39–40 | "Baseline line" and "STALE" have no definition or link. |
| N14 | style | 47 | "Small diff" should be "as a diff". |
| N15 | style, structural #8 | 68 | The counting method for "thinnest" is not given. |
| N16 | structural #7 | 68, 74 | List labels should be H3s or bold labels. |
| N17 | structural #10 | 56–66 | Table cells are written inconsistently. |
| N18 | structural #11 | 41–47 | A loose paragraph sits inside a list item. |
| N19 | structural #13 | 8, 27, 54 | Heading names don't follow the standard. |
| N20 | style | 3 | The Goldfish term is not explained. |
| N21 | comprehension | 14, 15, 17–25 | LDC VPS, PIC, RecordingSybase and the domain terms are undefined. Covered by the M10 glossary. |
