# Stage 6: Comprehension test

Target: `docs/security/2026-11-05-full-project-test-plan.md` · FeatureRange 1–83, DetailedRange 84–212
Reviewer: `egm-comprehension` (fresh context, document only, no standard)

## What this proposes

This is a second round of security and correctness testing for the whole project. It is needed
because new modules were built after their round-1 batches had closed, and two suite batches (7
and 8) never started. The round has nine batches in the order of the owner's five aims:

- R0 re-measures the current state and changes nothing.
- R1 re-audits writes to SOFTECH.
- R2 tests that money and stock calculations are deterministic.
- R3 covers authorization changes.
- R4 covers branch scoping and privacy.
- R5 covers injection and abuse.
- R6 covers scheduler, migration and sync reliability.
- R7 adds tests for the apps that have the fewest.
- R8 adds frontend lint, unit tests and end-to-end tests.

Every batch must end green, and a hole found by a test is fixed in the same batch. Fixes that touch
SOFTECH writes, pricing, checkout or auth wait for the owner to approve a diff. Four owner
questions are open (§5), and the plan defines "done" in §6.

## How the existing system works, per this document

There is a Django backend (`manage.py`, 67 apps) and a React frontend. The backend reads from an
external system called SOFTECH, which appears to be a Sybase database, and from branch servers.

Writes to SOFTECH go through "writers". They are gated by per-feature flags and by
`WRITER_INSTANCE`/`SOFTECH_READ_ONLY`, and are listed in a manifest of 60 sites, of which 36 are
real writes. Only the office laptop runs as the writer, with 16 flags ON.

Access control is a role and module matrix seeded by `seed_permissions.py`. Production runs it in
"log" mode, and individual views enforce access themselves. Only `accountant` is fully enforced.
Automated "sweeps" check every route for each role and method, plus cross-branch and phone
"canaries". The backend has 6,046 passing tests, and the frontend has no lint or test tooling yet.
The business domain seems to be retail pharmacy or POS. That is inferred, not stated.

## Findings (0 Blockers, 12 Majors, 13 Nits)

### 🟡 Majors

1. **"SOFTECH" is never defined** (lines 4, 20–21, 33, 61–62 and throughout). The document does
   not say what it is, who owns it, why writing to it is the top risk, or how it relates to
   "Sybase" (lines 59, 103, 116, 175).
2. **"This system", "writer", "reader copy" and "office writer" are undefined** (lines 20–21, 62,
   118–119). The topology is assumed: one office laptop is the only writer, and other deployments
   are readers. How they relate to the LDC VPS (line 34) is not explained.
3. **The suite terms are unexplained** (line 60): "generic sweeps", "enforce and log mode",
   "cross-branch canary", "phone canary", "static guards" and "manifest". R3 to R5 "extend" them,
   so the reader cannot judge what extending means.
4. **"Baseline line", "STALE" and "static guard baseline" are undefined** (lines 39–40, 161–162,
   206).
5. **The enforcement settings are vague** (line 63). It isn't clear which views enforce access
   themselves, or what `RBAC_ENFORCED_ROLES` does. `NETWORK_POLICY_ENFORCEMENT` is never defined.
6. **The rule that sorts writes is unstated** (lines 61, 99). The document doesn't say what the
   other 24 manifest sites are, or how a site counts as a "real" write.
7. **The W-1 / W-4 ID scheme is undefined** (lines 64, 161). R5's export scope ("since W-4")
   cannot be worked out.
8. **"Doc 35", "doc 33" and "Project 1–5" have no links or titles** (lines 76–82).
9. **The date cutoffs disagree** (line 10 vs lines 74, 151): round 1 ran until 11-03, R4 uses
   "since 2026-11-01", and §3 gives no dates.
10. **The exit rule clashes with stop-and-ask fixes** (lines 25, 86 vs 41–47, 196). The plan
    doesn't say what happens to a batch if the owner declines or delays a fix. Is the batch
    blocked, or is the test marked and the batch closed?
11. **Owner question 2 assumes the deploy flow is known** (lines 197–198). How does code reach the
    office laptop, and does a merge to `main` deploy there automatically?
12. **"Motalba" is unexplained** (lines 61, 110), even though it is the top-priority R1 fix.

### 🟢 Nits

13. **Line 10:** what batches 0–6 and N0–N6 covered is not summarized.
14. **Line 34:** "LDC VPS" is undefined.
15. **Lines 80, 151:** "PIC" is undefined.
16. **Lines 58 and 59 disagree:** "all pass in CI" sits next to "last CI red, fix pending".
17. **Line 103:** the purpose of `RecordingSybase` is not stated.
18. **Lines 128, 129, 133:** "drafting engine", "points formula", "strip/pack quantities" and
    "replacement payouts" are undefined. "Documented SOFTECH formulas" has no link.
19. **Line 130:** what a "safety flag" is, is not stated.
20. **Lines 131, 133, 134:** "period lock", "points formula" and "status machine" state no
    property to test.
21. **Lines 92–93 vs 172–173:** the two sets of incident labels may be the same incidents.
22. **Lines 143, 144, 169, 175:**
    - The list of views open to all staff has no location.
    - `cap` is undefined.
    - The scheduler technology is not named.
    - "Fetch budget" is undefined.
23. **Line 199:** "~45-minute CI" doesn't say whether that is the current time or a projection.
24. **Lines 191, 207:** "never pushed" doesn't say pushed where. `PENDING.md` has no path or link.
25. **Line 3:** the Goldfish process term is undefined.

## Reviewer summary

The reviewer could paraphrase every section. But the plan relies on project knowledge it doesn't
state: SOFTECH, the writer and reader topology, sweeps and canaries, the baseline, the ID and
document references, and the enforcement settings.

The reviewer suggests a short glossary and a two-sentence system overview at the top. Two
structural issues also need the author:
- **#10:** what happens to a batch when the owner holds a fix;
- **#9:** which scope cutoff date applies.
