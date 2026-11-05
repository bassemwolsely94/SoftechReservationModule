# Goldfish review: resolution log

**Plan:** `docs/security/2026-11-05-full-project-test-plan.md`

**Stages run:** 5 (zoom-out), 6 (comprehension), 7 (critic), 8 (intermediate zoom-out) and 9
(implementation readiness). The owner chose "conclude", then "revise the plan".

Each finding is either accepted and fixed, or contested by the Elephant with evidence. The
Elephant is the author, who holds the project context the reviewers did not have.

## Blockers

| Finding | Resolution | Where |
|---|---|---|
| Critic B1: no alternatives | Fixed: "Approach and alternatives" table with six choices | §5 |
| IB1: no file boundary | Fixed: every batch has a **Files** list | §7 R0–R8 |
| IB2 (codebase B1): motalba is already guarded | Accepted after the Elephant checked the code (`LOCK_DATE_EDIT`, the applied-run refusal, `expected_old`, `DateEditTests`). Idempotency gaps are now 2; the manifest gets corrected; the real gap (the old date is not kept) becomes owner Q1. | §4.2, R1 steps 3–5, §8 Q1 |
| IB3: R1 checks contradict the manifest | Fixed: a per-site expectation table, the `kind == 'write'` rule, an exception policy, and "twice = no value change" defined for absolute-SET writes | §1 glossary, R1 step 1 |
| IB4: guard design left to the builder | Fixed: lock IDs 7_301_011 / 7_301_012, the mechanism, and the test for each | R1 step 3 |

## Majors

| Finding | Resolution | Where |
|---|---|---|
| Undefined terms and links (comprehension 1–8, 12; critic M10) | Fixed: system overview, glossary, links | §1 |
| No risks, non-goals or problem split (critic M1) | Fixed | §2, §6 |
| Stop-and-ask vs. the "no known failing" rule (critic M2, IM1) | Fixed: `@pending` / `PENDING.md`, the decline path, a default per question | §3 rule 4, §8 |
| Office writer not protected (critic M3) | Fixed: rule 2, round-2 work on a reader copy only; "production" defined | §1, §3 |
| Dry-run, weak guards, audit gaps hidden (critic M4, M5) | Fixed: listed in full | §4.2 |
| Baseline debt ignored (zoom-out M1, critic M6, S8 M1) | Fixed: each baseline has a count, a target and a batch | §4.1, §9 |
| Inline suppressions not covered; "fixed by nosec" (critic M7) | Fixed: rule 3 + R0 suppression counter; §4 now says "suppressed" | §3, §4, R0 |
| Aim 2 has no batch (critic M8) | Fixed: break-in delta | R3 step 5 |
| No approach in the feature part (critic M9) | Fixed | §5 |
| Aims 4 and 5 wording; line 25 wording (critic M11–M13) | Fixed | §2 |
| R0 drift check can't work on a test DB (zoom-out M2, IM2) | Fixed: a read-only `check_schema_drift` command the owner runs on the real databases | R0 step 3 |
| Existing guards re-specified (zoom-out M3, IM3, IM4) | Fixed: §4.3 "Already covered" table; batches extend the named tests | §4.3, R1, R6 |
| Full re-audit of 36 sites (zoom-out M4) | Fixed: tests only for new, changed and hole rows | R1 step 2 |
| New guards vs. "fix in same batch" (zoom-out M5) | Fixed: R0 runs report-only; the owner picks baseline or fix | R0 step 2, §6 |
| Serial chain stalls on R1 (S8 M2) | Fixed: R0 decision pack; R7 and R8 run alongside | §5, R0 step 5 |
| Root cause recurs (S8 M3) | Fixed: new-module definition of done in CLAUDE.md, plus rule 7 | R0 step 4, §3 |
| Canary hand-extension (S8 M4, IM9) | Fixed: ratchet `skipped`, detail routes, flagged routes, GL role-refusal check | R4 |
| Enforce posture not scoped (S8 M5) | Fixed: switching is a non-goal; R3 exit criterion = enforce-ready | §2, R3 step 6 |
| Unclear money properties (IM5, IM6) | Fixed: assertions with formulas and rounding; table tests, no Hypothesis | R2, §5 |
| Nav map / open-to-all list (IM7) | Fixed: Playwright in R8; `open_to_all_staff.txt` | R3, R8, §5 |
| Named grants, missed-sales module, accountant (IM8) | Fixed: caps named, modules corrected, accountant marked covered | §4.3, R3 step 4 |
| Secrets and log capture undefined (IM10) | Fixed: classes, `assertLogs`, mask format, `record_phone` | R4 step 5–6 |
| Uploads that don't exist (IM11) | Fixed: retargeted to `upload-results`; scanning noted as client-side | R5 step 5 |
| Send limits (IM12) | Fixed: owner Q6 with a default | R5 step 6, §8 Q6 |
| Scheduler alert, migration cutoff, sync jobs (IM13) | Fixed: the alert is optional feature work; cutoff and repair rule defined; timeouts named | R6 |
| R7 and R8 tooling and floor (IM14) | Fixed | R7, R8 |

## Contested

| Finding | Why it's contested |
|---|---|
| Codebase "context": the office laptop is not a writer | The reviewer read `config/writers.py` and the settings docstrings, which describe the target setup. The owner's runserver log on 2026-11-03 printed `WRITER_INSTANCE=True SOFTECH_READ_ONLY=False` with 16 writer flags ON. That matches P-54: the office is the writer until cutover. Kept, with the source cited. |
| Zoom-out nit 4: 65 apps, not 67 | `INSTALLED_APPS` lists 67, and the design critic confirmed this. 65 counted `apps.py` files. Kept at 67. |

## Nits

All Nits were applied where the sentence survived the rewrite: ISO dates, "suppressed", defined
terms, full paths, named timeouts, and owner questions with defaults and sources.
