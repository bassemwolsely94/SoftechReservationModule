# Full project audit (2026-11-15)

Start with [01 Executive summary](01_EXECUTIVE_SUMMARY.md), then [14 Decision register](14_DECISION_REGISTER.md).

| # | Report |
|---|---|
| 01 | [Executive summary](01_EXECUTIVE_SUMMARY.md) |
| 02 | [Complete module inventory](02_COMPLETE_MODULE_INVENTORY.md) |
| 03 | [Security audit](03_SECURITY_AUDIT.md) |
| 04 | [Backend audit](04_BACKEND_AUDIT.md) |
| 05 | [Frontend and UX audit](05_FRONTEND_UX_AUDIT.md) |
| 06 | [SOFTECH integration audit](06_SOFTECH_INTEGRATION_AUDIT.md) |
| 07 | [Performance audit](07_PERFORMANCE_AUDIT.md) |
| 08 | [Business optimization opportunities](08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md) |
| 09 | [Top 30 quick wins / Top 10](09_TOP_30_QUICK_WINS.md) |
| 10 | [Test strategy and results](10_TEST_STRATEGY_AND_RESULTS.md) |
| 11 | [Bug fix register](11_BUG_FIX_REGISTER.md) |
| 12 | [Release readiness](12_RELEASE_READINESS.md) |
| 13 | [Implementation roadmap](13_IMPLEMENTATION_ROADMAP.md) |
| 14 | [Decision register](14_DECISION_REGISTER.md) |

Relationship to earlier work: this audit was done from scratch and then compared with the product review
(`docs/product-review/`, 2026-10-30) and security rounds 1–2 (`docs/security/`); each finding is marked new /
already known / already fixed in its report. Reports 03–08 were written by independent read-only reviewers
and every finding fixed here was re-verified in the code first.

**Checkpoint for a later session:** fixes are on branch `claude/full-project-audit` (one commit per fix);
nothing is merged or deployed; open decisions are D-01…D-28; next steps are Wave 0 in
[13](13_IMPLEMENTATION_ROADMAP.md).
