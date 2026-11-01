# 05 — Prioritised Proposal Backlog (with KPI & pilot plan)

**Provisional ranking basis.** No business weights have been set yet, so the order below is qualitative:
1. Safety and compliance risk first.
2. Then measured evidence × number of staff affected.
3. Then data readiness.
4. Then low implementation and adoption burden.

**Benefit hygiene:**
- Revenue ≠ gross profit ≠ contribution after incremental cost.
- Cash released from inventory ≠ accounting profit.
- Staff time saved ≠ cash saved unless headcount or overtime changes.
- Overlapping proposals do not double-count.

**Nothing in this document is authorised for implementation.** Approval of a card = approval to *specify* unless
the owner says "build".

---

## DECISION BATCH 1 — foundations before any further feature work

### P-01 · Pharmacy-safety guardrails on the commercial engines
**Module(s):** recommendations, offers, incentives, enrichment · **Type:** optimize

**Current situation.** Item-level safety exists (`catalog/safety.py`). The commercial paths bypass customer- and
class-level safety:
- **S1.** POS basket suggestions do not apply the customer's allergy/interaction filter
  (`recommendations/basket_intelligence.py:87`). The filter already exists in `recommendations/engine.py:386`.
- **S2.** Offer targeting has no Rx or sensitive-class exclusion (`offers/targeting.py:181`).
- **S3.** Incentive rules can pay on any item, including supplier-sponsored ones (`incentives/models.py`).
- **S4.** AI enrichment auto-approves clinical fields at ≥0.90 confidence (`enrichment/suggestion_generator.py:305`).
  78 indications and 11 Rx/OTC values are approved [M]; auto vs human cannot be distinguished.

**Problem.** Violates non-negotiable Rule 4 (safety beats sales) and Rule 10 (no AI clinical decisions). Risk is low
today only because offers execution, incentives and campaigns are barely used. It becomes real the moment they are
switched on.

**Proposed behaviour.**
- **(a)** Basket suggestions reuse the existing customer-unsafe filter. An unsafe item never appears.
- **(b)** A pharmacist-maintained **"no-promotion / no-incentive" class list**, default-deny for Rx-only, antibiotics
  and psychotropics. Offers, incentives and campaigns refuse those items with a clear Arabic reason.
- **(c)** Enrichment never auto-approves clinical fields (indication, contraindication, interactions, pregnancy,
  rx_otc, dosage). Those always need a named pharmacist approval. Existing approved clinical values get flagged
  "needs pharmacist review".
- **(d)** The VIP "premium" boost is removed until it is margin-based and safety-filtered.

**Example (illustrative).** A customer recorded as penicillin-allergic buys paracetamol. Today basket intelligence
could suggest an amoxicillin-containing item that is "frequently bought together". After (a) it cannot.

**Expected benefit.** Clinical risk reduction and trust. No sales benefit claimed.

**Evidence.** Code refs above. Abdelaziz 2019 (98% antibiotic dispensing for viral scenarios, Egypt) shows the
antibiotic class is a real local risk. EDA/SMC advertising controls.

**SOFTECH/data.** Customer allergies (B, sparse). The class list needs new capture by a pharmacist (C), seeded from
SOFTECH item classes plus `chronic.IngredientClass` (91 rows).

**Measurement.**
- Unsafe suggestions shown: target 0, verified by an automated test.
- Count of class-list items in active offers/incentive rules: target 0.
- Clinical enrichment values awaiting pharmacist review: burn down to 0.

**Effort.** Small. (a) reuses existing code; (b) is one model plus three checks; (c) is a field allow-list plus a
data flag. Touches no SOFTECH write and no pricing calculation.

**Recurring cost.** A pharmacist owns the class list (review quarterly).

**Adoption burden.** Very low. Invisible except refusals.

**Risks.**
- Over-blocking OTC promotions. Mitigation: a pharmacist can allow-list individual items, with audit.

**Smallest version.** (a) + (c) only: about a day of work, no new data.

**Alternatives.** Policy plus training only. Rejected, because code paths would still allow it.

**Confidence.** High (verified in code).

**Recommendation.** **Build now** (a, c, d); **specify** (b) with the pharmacist owner.

**Decision required.** Approve building (a)+(c)+(d) now and a spec for the class list (b)? And who is the pharmacist
owner of the list?

---

### P-02 · Make alerts mean something again (transit alert reset + notification hygiene)
**Module(s):** notifications, transits, delivery, sync · **Type:** simplify

**Current situation [M].**
- 399k notifications in 30 days to 90 people. 84% are `transit_critical`: one per stuck transfer per day, sent to every
  branch user **plus all admins** (`transits/.../sync_in_transit.py:822-900`).
- Two users got ~31k each. Nothing has been marked read since 2026-10-19. 1.69M rows, with no retention.
- 1,021 transfers show "in transit", 776 of them for 14+ days.
- **Unknown:** are these genuinely unreceived, or is 125↔25 receipt linking failing? Transit linking uses docnumber
  only, and docnumbers are not unique per branch.

**Problem.** Alert fatigue hides the alerts that matter (demand SLA, reserved item back in stock, connectivity).
Staff time is wasted. Accountability is lost.

**Proposed behaviour.**
1. **Verify first:** sample 20 "stuck ≥14 days" transfers against SOFTECH doc 25. Read-only; outcome decides the fix.
2. Transit alerts become **one daily digest per receiving branch** ("7 transfers awaiting receipt — oldest 23 days")
   to the branch manager only. Admins get one network digest. Per-transfer pings are dropped.
3. A per-type routing table: who gets it, instant vs digest, auto-expire. Low-priority types are digested.
4. A retention job: read >30 days and unread >90 days are archived or deleted. Same for NotificationLog.
5. Fix the transit link key to (branch, doctype, docnumber, date) if step 1 shows mislinks.

**Example (illustrative).** A Giza branch manager sees one morning card listing 4 unreceived transfers instead of
~160 pings a day.

**Expected benefit.** Staff time and responsiveness; restores the alert channel for demand/reservation alerts. If
step 1 finds real stuck stock, it also releases cash and improves availability.

**Evidence.** Measured volumes above; producer code.

**SOFTECH/data.** Notifications (A); transits (B, link quality to verify).

**Measurement.**
- Notifications per user per day: baseline ~150 for top recipients.
- % read within 24 h: baseline 0%.
- Median days-to-receipt for 125 docs.
- Count of transfers >14 days: baseline 776.
- Evaluate 4 weeks after the change.

**Effort.** Small–medium. Digest job, routing table, retention job, verification query.

**Recurring cost.** None material.

**Adoption burden.** Low; fewer, clearer alerts.

**Risks.** A genuinely urgent item lost in a digest. Mitigation: keep instant delivery for a short list of critical
types (demand SLA, stock-available-for-reservation, connectivity).

**Smallest version.** Verification sample + transit digest + retention.

**Alternatives.** Mute transit alerts entirely. Loses the stuck-transfer signal.

**Confidence.** High on the problem; medium on the root cause until step 1.

**Recommendation.** **Build now** (after the step-1 check).

**Decision required.** Approve the verification sample and the digest + retention change? Who should own stuck
transfers — branch manager or a central transfers coordinator?

---

### P-03 · Automatic outcome matching: "did the customer actually buy?"
**Module(s):** demand, reservations, followups, erp (retire), customers · **Type:** optimize + retire

**Current situation.**
- Recovery and fulfilment are self-reported. Recovered revenue defaults to the estimated value
  (`demand/service.py:562`).
- The only sale-matching job (follow-up auto-close) reads `erp.ERPTransaction`, whose **last data is 2026-04-30 [M]**,
  and it isn't scheduled.
- Callcenter and patient-profile code also read that stale mirror.
- The live `PurchaseHistory` mirror is current (2026-10-27) and customer-linked.

**Problem.** We cannot tell whether lost-sales recovery, reservations or refill follow-ups produce sales. That makes
every future decision about these modules (merge, invest, retire) guesswork.

**Proposed behaviour.**
- A scheduled matcher (after each sales sync) looks for an open demand line, reservation or follow-up task. For a
  matching customer + item (same item; later, an approved composition-equivalent), a **sale (doc 115) within N days**
  sets `matched_sale` (branch, date, value, cost_at_sale).
- Staff can still mark "recovered" manually. The KPI shows **verified** and **self-reported** separately.
- Readers of the `erp` mirror are repointed to PurchaseHistory, and the `erp` app is retired.

**Example (illustrative).** A demand line for an out-of-stock inhaler, customer PIC known, is matched 3 days later to
a sale at another branch. It is marked "verified recovered — EGP 210 sales, EGP 32 gross margin".

**Expected benefit.** Measurement integrity, not direct sales. It enables honest lost-sales recovery value and
refill follow-through, and identifies which intake path converts.

**Evidence.** Code refs; [M] mirror dates.

**SOFTECH/data.**
- PurchaseHistory: A for identified customers.
- Requests captured by phone only need a phone→customer match: B.
- Walk-in placeholder accounts cannot be matched.

**Measurement.**
- % of closed requests with a verified sale.
- Verified recovered gross margin per month.
- Self-reported vs verified gap.
- Baseline is unknown today: the first month *is* the baseline.

**Effort.** Medium. Matcher job + fields/migration + KPI change + repoint 3 readers + retire the `erp` sync.

**Recurring cost.** Small DB load after each sync.

**Adoption burden.** None. Automatic.

**Risks.**
- False matches (the customer bought the item for another reason). Mitigation: time window + same item only; label
  it "attributed", not "caused".
- Privacy: none new (internal data).

**Smallest version.** Match demand lines and follow-up tasks only, same item, 14-day window, read-only report before
writing any status.

**Alternatives.** Keep self-reporting. Then the numbers stay unverifiable.

**Confidence.** High on feasibility (data verified); medium on match rate (depends on customer identification at
capture).

**Recommendation.** **Pilot** (report-only first).

**Decision required.** Approve a report-only pilot? Which match window do you consider fair: 7 or 14 days?

---

### P-04 · Measure real usage before cutover, and retire what's dead
**Module(s):** platform (frontend router, sync), purchasing, batches, erp, forecasting, tasks · **Type:** simplify / retire

**Current situation.**
- There is no screen-usage telemetry, and `last_login` is not updated by JWT [C]. We cannot see which of ~100 screens
  staff use.
- Several generators produce output nobody consumes [M/C]:
  - TransferRecommendation: 527,841 pending.
  - `StockBatch` / `near_expiry_scan` on an empty table.
  - `forecast_30d/90d` with no reader.
  - The stale `erp` mirror.
  - Task schedules that never fire.
  - The unrouted `PurchasingPage.jsx`.

**Problem.** Every unused path costs maintenance, test time, DB growth and staff confusion (the sidebar has ~90
entries). Without usage data, the rest of this review relies on interviews and row counts.

**Proposed behaviour.**
1. A lightweight `ScreenView` event: user, role, branch, route, timestamp. One insert per navigation, no content.
   Plus a monthly "who uses what" report.
2. Retire or stop list (owner confirms each):
   - TransferRecommendation generation (keep the code, stop the job, purge rows).
   - StockBatch / FEFO path + `near_expiry_scan`.
   - Item forecast job, unless P-xx wires it to reorder.
   - `erp` sync (with P-03).
3. Fix or schedule: task schedules runner; shortage-flag retry; follow-up generation.
4. After 60 days of telemetry, hide screens with zero use from the sidebar (still reachable by URL).

**Expected benefit.** Lower maintenance and DB load; a simpler sidebar (staff time); real adoption evidence for every
later batch.

**Evidence.** Measured counts; code refs in `02_CURRENT_STATE_FINDINGS.md` §1, §6.

**SOFTECH/data.** Screen usage needs new capture (C). No SOFTECH involvement.

**Measurement.**
- Weekly active users per module.
- Screens with zero use in 60 days.
- DB size of retired tables reclaimed.
- Sidebar items before vs after.

**Effort.** Small (telemetry + job removals).

**Recurring cost.** Negligible.

**Adoption burden.** None.

**Risks.** Retiring something a quiet user relies on. Mitigation: stop jobs before deleting code; 60-day observation;
data kept until confirmed.

**Smallest version.** Telemetry + stop the TransferRecommendation job + retention on its table.

**Alternatives.** Interview-only usage assessment.

**Confidence.** High.

**Recommendation.** **Build now** (telemetry before VPS cutover so production usage is captured from day 1).

**Decision required.** Approve the telemetry and the first retire list (TransferRecommendation job, StockBatch/FEFO
scan)?

---

### P-05 · Customer contact consent & one outbound suppression rule (PDPL)
**Module(s):** customers, campaigns, followups (refill reminders), demand (restock WhatsApp), whatsapp, omni ·
**Type:** new capability (small) + simplify

**Current situation [C].**
- No customer-level consent record exists.
- Three outbound paths have three different suppression rules:
  - campaigns, which ignore refill/demand opt-outs and closed/deceased accounts;
  - refill reminders (OFF);
  - demand restock WhatsApp (OFF).
- Campaigns can target by chronic condition and send free-form text to cold audiences (Meta will reject outside 24 h).

**Problem.** Egypt's PDPL requires prior consent + identification + free opt-out for electronic direct marketing, and
health data is sensitive. A law-firm source reports a compliance deadline of **about 1 Nov 2026** (unverified). The
retention features (refill reminders, restock messages) cannot be switched on safely until this exists. Benchmark
evidence (Walgreens RCT) suggests refill outreach is worth having, but modest.

**Proposed behaviour.**
- A `ContactConsent` record per customer: purpose (service / refill / marketing), channel, granted_at, source
  (counter, call, WhatsApp reply, portal), withdrawn_at.
- One `can_contact(customer, purpose, channel)` service used by **every** sender.
- Service messages (your order is ready) are separate from marketing.
- Counter staff capture consent in one tap at the POS customer bar.
- Campaigns: templates only; no health-condition targeting without explicit health-purpose consent.

**Example (illustrative).** A chronic customer agrees at the counter to refill reminders but not offers. The refill
reminder goes; the summer-sunscreen campaign skips them automatically.

**Expected benefit.** Legal compliance; customer trust. It unblocks refill and restock outreach, whose value is
measured later in pilots.

**Evidence.** PDPL commentary (04 §1); code refs; Walgreens/Kooy RCTs (04 §3).

**SOFTECH/data.** New capture (C). No SOFTECH write.

**Measurement.**
- % of active customers with a recorded consent decision.
- Opt-out rate.
- Messages blocked by suppression.
- Later: refill-on-time rate in a consented pilot vs control branches.

**Effort.** Medium. Model + service + POS one-tap + rewiring three senders + campaign template switch.

**Recurring cost.** Small staff time at the counter.

**Adoption burden.** Medium; a new counter habit. Script and training needed.

**Risks.** Legal interpretation. **Must be confirmed by counsel** before relying on it.

**Smallest version.** Model + `can_contact` + block all marketing sends until consent exists (sends are mostly OFF, so
this is low-disruption).

**Alternatives.** Keep all outbound marketing OFF indefinitely.

**Confidence.** Medium (legal facts from secondary sources).

**Recommendation.** **Research further (legal) this week + specify**; build after legal confirmation.

**Decision required.** Will you ask your legal adviser to confirm PDPL obligations and the deadline, and approve
writing the specification meanwhile?

---

## DECISION BATCH 2 — expiry & stock cash (owner-chosen focus, 2026-10-30)

### Measured picture (office PG, 2026-10-28 snapshots; read-only)
All values are at **current** `Item.cost_price`, not historical cost; treat them as order-of-magnitude.

**Expiry** (`StockExpiryBalance`, all 6 nodes synced 2026-10-28). Batch qty matches `stkbal` for 87–95% of
branch items, so branch batch data is trustworthy.

| Bucket | Value (cost) | Note |
|---|---|---|
| HQ store **110**, "expired" | **1.61M** | 100% more than 2 years expired. **Zero movements in 12 months** (stock ledger). Not in the `ItemStock` mirror. Book residue, not shelf stock |
| HQ quarantine 102/103/105, expired | 1.14M (767k more than 2 years) | Active stores: about 206k EGP/yr leaves via doc 120 (purchase return) |
| HQ live stores 100/101/104, expired | 160k | |
| Branches 130–170, expired, still on stock | 102k | |
| Branches, expiring in 0–180 days | **413k** | ≈ **232k (1,615 lots) will not sell before expiry at the branch's own rate**; 160k of that has zero local sales |

The earlier "~1.77M expired backlog at HQ" is mostly store 110 book residue. **The physical shelf-expiry problem is
about one-fifth of that headline.**

**Slow and dead stock** (latest engine run #104, 2026-10-27; stock > 0).

| Bucket | Value (cost) | Note |
|---|---|---|
| Branch stock with **no local sale in 6+ months** | **1.87M** | Across 5 branches |
| … of which the item **sells at other branches** | **1.43M** | ≈ **713k fits directly into another branch's 2-month gap** |
| … of which the item sells nowhere in the network | 437k | Return / liquidate / stop |
| Overstock above the doc-22 ceilings (A4/B5/C6 months), branches | ≈ 383k | HQ excess +257k |
| `strategic_hold` items | 0 set | The field exists; nobody has used it |

**Benefit hygiene.** Moving stock to where it sells converts trapped stock to sales. The cash benefit is the **avoided
purchase** at the receiving branch plus the **avoided write-off**. It is not the full stock value.

### Owner input (2026-10-30) — supersedes assumptions in the cards below

**Store meanings**

| Store | Meaning (owner) | Bucket |
|---|---|---|
| 110 | **A closed branch. It should hold no stock at all** | Clean-up: zero it per the accountant (write-off or transfer) |
| 102 | Expired items accumulated over the years that could not be returned | Write-off / destroy candidates |
| 105 | Recently expired items that may still be returnable to main suppliers | **Return candidates** (time-critical) |
| 103 | Expired cosmetics | Cosmetics expired (destroy or cosmetics-supplier return) |

**Today's practice**
- **Dead stock:** WhatsApp group posts and HQ pull-backs both happen, but rarely. **Mostly the stock just sits, which
  leads to large losses.** A local prescriber change is a likely cause. Moving stock to where it sells is the
  confirmed fix.
- **Near expiry:** the branch puts the item in the near-expiry corner, tries to sell it, posts it on WhatsApp for
  other branches, and later sends expired items to the HQ collection. This is the isolation into 105/102.
  **Branches notice too late.**

**Supplier return terms**
- Suppliers accept returns, but not everything.
- **Window = expiry month −2 to expiry month +1.** Credit is given.
- **Pharma Overseas (565, ≈40.5M EGP/yr purchases, the largest supplier)** and **Ibn Sina (260, ≈4.8M/yr)**
  let us enter return items ourselves in their system. They answer immediately whether each item is accepted and
  which expiry dates are allowed.

**Process rule:** review all recommendations first; building starts after all the discussions.

**Measured with the owner's window rule** (stock batch matched to a Pharma Overseas / Ibn Sina purchase entry by
item + expiry month; a heuristic, since another supplier may have delivered the same expiry):

| Location | In window now | Window closes this month | Window opens next month | Window already missed |
|---|---|---|---|---|
| Branch shelves | 47k | 7k | 33k | 17k |
| Store 105 | 16k | 8k | — | 64k |
| Store 102 | — | — | 1k | 32k |
| **Total (2 suppliers)** | **≈64k** | **≈15k** | **≈36k** | **≈113k** |

Every month, tens of thousands of EGP enter these two suppliers' windows. Value already sitting past its window is a
direct, recurring cash loss. **This makes the return window the most time-critical lever in Batch 2.**

### P-26 · One honest expiry number: separate live risk from book residue
**Module(s):** batches, dashboard, insights · **Type:** simplify

**Current situation.**
- Expiry is reported from four sources: `StockBatch` (dead), `PurchaseExpiryEntry`, `StockExpiryBalance`, and
  `ItemDemandMetrics.expected_expiry_risk_value` used by insights.
- "Expired backlog" headlines mix in store 110: 1.61M EGP, all more than 2 years old, no movement in 12 months.
- Long-expired quarantine stock is also mixed in. None of this is shelf risk.

**Problem.** Management sees a large, unchanging number nobody can act on. Real shelf exposure (≈102k expired on
branch stock, ≈232k at risk within 180 days) is buried.

**Proposed behaviour.**
- `StockExpiryBalance` becomes the single expiry truth.
- Every view and KPI splits stock into three buckets:
  - **Shelf risk:** live sales stores.
  - **Awaiting disposal/return:** quarantine.
  - **Book residue:** stores with no movement in 12 months, or batches more than 2 years expired.
- A one-off **write-off/clean-up list for the accountant**: store 110 + quarantine more than 2 years. Staff post the
  SOFTECH adjustment natively; our system only lists and later verifies via the ledger.
- Retire `StockBatch`/FEFO + `near_expiry_scan`. Insights reads the same source.

**Example (illustrative).** The dashboard tile reads "Shelf: 102k expired · 232k at risk in 180 days |
Quarantine: 1.14M awaiting return/destroy | Book residue: 1.61M — needs write-off decision".

**Expected benefit.**
- Decision quality and management visibility.
- Inventory valuation corrected after write-off. That is an accounting effect, **not cash**.

**Evidence.** Measurements above. Dead path: `batches.StockBatch` has no caller of `receive_from_invoice`.

**SOFTECH/data.** A for branch batches. B for HQ store semantics: confirm with SOFTECH or the accountant what store 110
is.

**Measurement.**
- Shelf-risk value per branch (weekly).
- Book-residue value, which should go to about 0 after the write-off decision.

**Effort.** Small (classification + KPI + list). Store 110 meaning must be confirmed first.

**Recurring cost.** None.

**Adoption burden.** Low.

**Risks.**
- Writing off stock that physically exists. Mitigation: a physical check of a sample of store 110 lines before any
  write-off; the decision stays with the accountant.

**Smallest version.** Bucket split + dashboard tile + store-110 list export.

**Alternatives.** Exclude store 110 from reports silently. This hides the valuation problem.

**Confidence.** High on the measurements; medium on what store 110 represents.

**Recommendation.** **Build now** (after you confirm what store 110 is).

**Decision required.** ~~What is store 110?~~ Answered: a closed branch.

**Revision after owner input:**
- Buckets become:
  - Shelf risk (live stores).
  - **Return candidates (105)**.
  - **Write-off/destroy (102)**.
  - **Expired cosmetics (103)**.
  - **Closed-branch stock (110), which must be zero.**
- Closed stores are excluded from every report.
- A standing alert fires if any closed store holds stock.

**Decision:** approved for specification. Build after the full review.

---

### P-27 · Dead-stock recovery: move what sells elsewhere, return or stop what sells nowhere
**Module(s):** purchasing (`/cash-optimization`, `distribution.py`), supply (توزيعة), catalog (`strategic_hold`) ·
**Type:** extend existing design

**Current situation.**
- Doc 22 (owner-validated 2026-09-15) designed spike, dead-stock and overstock detectors. Only **spike** is built.
  The dead and overstock tabs on `/cash-optimization` are disabled placeholders (`CashOptimizationPage.jsx:153`).
- The توزيعة engine (doc 30, phase A built, B–D awaiting your decision) only treats branch stock as movable when it
  is **above the branch's SOFTECH max-stock ceiling**. That ceiling exists only for items the branch sells
  (`distribution.py` `_branch_ceilings`).
- **So stock that stopped selling at one branch but sells at another is invisible to it: ≈1.43M EGP.**
- The old TransferEngine produced 527k unused recommendations (shortage-driven, fractional units, no value
  threshold).

**Problem.** Cash is trapped and expiry risk grows in the wrong branch, while another branch buys the same item.

**Proposed behaviour.** Build doc 22 step 2 as designed: location-classified dead stock, cause hint, `strategic_hold`
exclusion. Then add one new lane:
- **"Locally dead, sells elsewhere"** (no local sale ≥ 6 months, stock received ≥ 6 months ago, network rate > 0)
  becomes a **new category in the توزيعة plan**, moved through the existing ISR legs (branch → HQ → branch).
- Doc-30 value threshold applies; nothing under 100 EGP per move.
- Destination = the branch with the largest gap.
- **Short-dated lots go first**, to the fastest-selling branch.
- **"Dead everywhere"** (≈437k) goes to an HQ return list, gated by the returning-supplier class (doc 22 §3.4,
  advisory per your 2026-09-15 decision), or a "stop item" (موقوف) suggestion.

**Example (illustrative).** Branch 150 has held 6 packs of an inhaler with no local sale for 8 months. Branch 160
sells 4 a month and has 1 left. The plan proposes moving 6 packs 150 → HQ → 160 in the next توزيعة wave. If HQ already
has an ISR line to 160 for that item, the doc-30 wave-0 netting removes the duplicate.

**Expected benefit.**
- Avoided purchases at receiving branches + reduced expiry write-off.
- Upper bound ≈713k EGP of stock matching an existing 2-month gap. The realised share is unknown until piloted; count
  only lines actually received and later sold.
- Extra transfer handling cost: one leg pair per route per wave, batched.

**Evidence.** Measurements above; doc 22 §3.2, §4; doc 30 §1 (half of branch-sourced moves are under 100 EGP, so the
threshold matters).

**SOFTECH/data.** A: `ItemDemandMetrics` last_sale_date / monthly_avg / current_stock; ISR writer is live. B: "stock
received ≥ 6 months ago" needs stock age from the ledger or `stkbal.opendate`; `last_sale_date` null may mean "no sale
within the data window", not "never".

**Measurement.**
- Branch-dead value (baseline 1.87M), locally-dead-sells-elsewhere value (baseline 1.43M).
- Moved value and **sold-within-90-days-of-receipt rate**.
- Avoided-purchase estimate.
- Pilot: 2 source branches × 8 weeks vs the other 3 branches.

**Effort.** Medium. The detector reuses engine fields; the plan category reuses doc-30 waves and ISR legs. Depends
on doc 30 phase B (ordered waves).

**Recurring cost.** HQ handling of the extra legs.

**Adoption burden.** Medium. Branches must actually ship and receive; the existing ISR/إذن الصرف flow is used, so no
new screen for branches.

**Risks.**
- Moving cold-chain items: exclude fridge items in the pilot.
- Moving stock a branch needs for a known patient: `strategic_hold`.
- Shuffling the same stock back and forth: no move-back within 6 months.

**Smallest version.** Read-only dead-stock tab with three lanes (move / return / stop) and an Excel export. Moves are
added to توزيعة only after you review the first list.

**Alternatives.** Branch managers clear their own slow stock via WhatsApp groups (today's practice?); markdown
(pricing, stop-and-ask).

**Confidence.** Medium–high: the data is verified; the sell-through after a move is unproven.

**Recommendation.** **Pilot.**

**Decision required.** Approve building the dead-stock tab (doc 22 step 2) read-only first, and adding the
"locally dead, sells elsewhere" lane to توزيعة after you review the first list?

**Revision after owner input:**
- The owner confirms dead stock "mostly just sits" and that moving it to where it sells is the fix.
- The tab replaces the occasional WhatsApp posts and HQ pull-backs with one ranked list.
- The value threshold stays.

**Decision:** approved for specification. Build after the full review.

---

### P-28 · Near-expiry worklist that predicts "won't sell in time" and checks what happened
**Module(s):** batches (`/batches`, `rebalance.py`), transfers / ISR, stockcount · **Type:** optimize

**Current situation.**
- Near-expiry grids list lots by date (`/batches`); a weekly worklist exists (`expiry_worklists`, Sunday 08:00).
- Rebalance creates DRAFT transfers; markdown is OFF and **chain-wide** (`batches/views.py:221-226`); disposal
  records are never reconciled.
- **Nobody measures whether an at-risk lot was sold, moved, returned or expired.** Zero disposal records exist.
- The grids show **all** near-expiry stock, including lots the branch will sell in time anyway.

**Problem.** Staff see a long list ranked by date, not by what will actually be lost. ≈232k EGP (1,615 lots) of
branch stock is predicted not to sell before expiry; it is mixed in with ≈180k that will sell normally.

**Proposed behaviour.**
- For each branch lot expiring within 180 days, compute **at-risk qty = qty − (branch rate × months to expiry)**
  (FEFO order).
- Show **only at-risk lots**, ranked by at-risk value, each with one suggested action:
  - **Move** to the branch that sells it fastest (feeds P-27's wave).
  - **Return** to the supplier while the return window allows.
  - **Sell-first** flag: shelf front / counter mention.
  - **Accept loss.**
- Each Sunday the list re-computes from the new `stkbalexpiry` snapshot. A lot whose qty fell is marked
  sold/moved/returned (a ledger-doccode check tells which). The rest is marked "expired".

**Example (illustrative).** Branch 130 has 10 packs of a cream expiring in 2 months; it sells 1/month there, so
8 packs are at risk (~EGP 640 at cost). Branch 170 sells 6/month. Suggested: move 8 to 170. Four weeks later the
snapshot shows the lot at 130 = 0 and a doc-125 movement, so it is marked "moved — saved".

**Expected benefit.**
- Reduced expiry write-off on branch stock.
- Upper bound ≈232k EGP at risk in the current 180-day window; the realised saving is measured, not assumed.
- Staff time: a short ranked list instead of a full grid.

**Evidence.** Measurement above; code refs. External: no credible benchmark for community-pharmacy redistribution
outcomes (04 §3), so we set our own baseline.

**SOFTECH/data.** A: `StockExpiryBalance` (daily, all nodes), engine rates, stock ledger (doc 125/120/115). B: units
consistency (batch qty vs monthly_avg, both in packs?) to verify; ledger is an HQ mirror only, so branch-side sale
attribution relies on qty drop + doc type.

**Measurement.**
- At-risk value at T0 vs outcome after expiry: % saved (sold/moved/returned) vs % expired.
- Monthly realised branch write-off.
- Baseline is the first 8 weeks.

**Effort.** Small–medium. Calc + ranked view + weekly outcome snapshot. No SOFTECH write.

**Recurring cost.** None.

**Adoption burden.** Low–medium: a weekly 10-minute review per branch manager.

**Risks.**
- The rate is too optimistic for seasonal items: use the lower of 90d and 365d rates.
- Pushing short-dated stock on chronic patients: sell-first never means dispensing a lot that won't last the
  patient's course. The counselling rule is noted on the card (Rule 4).

**Smallest version.** At-risk calc + ranked list + Excel, branches 130 and 160 only, with an outcome check after
8 weeks.

**Alternatives.**
- Branch-scoped markdown: a **pricing change, so stop-and-ask**; kept as a later option.
- Near-expiry staff incentive: exists, inactive; not recommended (safety).

**Confidence.** Medium: the calc is simple; the units and FEFO assumptions need a quick check.

**Recommendation.** **Pilot.**

**Decision required.** Approve the at-risk worklist pilot for two branches? Which two?

**Revision after owner input:** the suggested action follows a fixed order.
1. **Return.** Use this when the lot's supplier window is open or about to open (expiry month −2) and the supplier
   accepts returns: route it to 105 before the window closes.
2. **Move** to the fastest-selling branch.
3. **Near-expiry corner / sell-first.**
4. **Accept loss.**

This replaces the WhatsApp broadcast with a structured list that is visible early enough. It works together with
P-29.

**Decision:** approved for specification. Build after the full review. Pilot branches still to be named.

---

### P-29 · Supplier returns before they rot: quarantine ageing and returnability list
**Module(s):** batches (disposal), procurement (supplier classes), stock_audit (ledger) · **Type:** extend

**Current situation.**
- HQ quarantine holds ≈1.14M EGP of expired stock; 767k is more than 2 years past expiry.
- Returns do happen: ≈206k EGP/yr leaves quarantine via doc 120. Chain-wide, purchase returns were ≈1.95M EGP in
  12 months (`StockLedgerLine`).
- Nothing shows **which supplier or company should take back which batch, by when**.
- The disposal ledger (`ExpiryDisposalRecord`) exists but has **0 records** and is never reconciled to doc 120.
- EDA Decree 47/2025 (press-reported) requires companies to accept expired packs back within 90 days.

**Problem.** Returnable value ages past supplier windows. Cash credit is lost; quarantine fills with unrecoverable
stock.

**Proposed behaviour.**
- A quarantine ageing view grouped by **source supplier/company**: from the batch's purchase line in
  `PurchaseExpiryEntry` / `PurchaseLine`.
- Returnability per doc 22 §3.4: distributor / manufacturer / warehouse classes accept returns; buy-back accounts
  don't.
- Columns: days in quarantine and value.
- Purchasing ticks a batch "return requested". When a doc 120 for that supplier + item appears in the ledger, it
  auto-marks "returned — EGP X credited". Advisory only; no document drafting, per your 2026-09-15 rule.

**Example (illustrative).** 14 lines from distributor X, EGP 38k, in quarantine 120–300 days. The buyer bundles them
into one return. Ten days later the ledger shows doc 120 for 12 lines and they close automatically; 2 remain flagged.

**Expected benefit.**
- Cash credit recovered from suppliers. This is real cash, unlike book clean-up.
- Smaller quarantine.
- The upper bound is unknown: which share of the 1.14M is still within supplier policy cannot be told without
  supplier terms.

**Evidence.** Measured quarantine and return flows; doc 22 §3.4/§4.5; EDA 47/2025 (04 §1, press-reported).

**SOFTECH/data.**
- A: ledger doc 120, PurchaseLine supplier.
- B: linking a quarantine batch to its purchase supplier needs a batch_no / expiry match.
- C: supplier return-policy windows; purchasing to enter per supplier.

**Measurement.**
- Quarantine value by age band (monthly).
- Return credit value per month (doc 120 from quarantine stores); baseline ≈206k/yr.
- % of returnable batches returned within 90 days.

**Effort.** Small–medium.

**Recurring cost.** Purchasing time to maintain supplier windows.

**Adoption burden.** Low for branches; medium for the purchasing team.

**Risks.**
- Mis-attributing a batch to the wrong supplier: show the match confidence; a human confirms.

**Smallest version.** Quarantine ageing by supplier + Excel; auto-close via doc 120 later.

**Alternatives.** Rely on the supplier rep visits (status quo).

**Confidence.** Medium.

**Recommendation.** **Pilot** (read-only first).

**Decision required.** Approve the read-only quarantine-by-supplier view? Who owns supplier returns (purchasing lead)?

**Revision after owner input — the card is renamed to "Return-window calendar"; highest priority in Batch 2.**
- Per supplier, a monthly list with three columns:
  - **Window opens next month.**
  - **In window now.**
  - **Closes this month.**
- It covers shelf stock and store 105 alike. Rule: expiry month −2 to +1, configurable per supplier.
- For Pharma Overseas and Ibn Sina, the list is laid out in the order and fields staff type into their return
  systems. Staff record the immediate answer (accepted / rejected / allowed expiry) per line. That builds a
  per-supplier acceptance history, so the list learns which items each supplier takes.
- Branches get "send to HQ for return by <date>" lines.
- Auto-close when doc 120 for that supplier + item appears in the stock ledger.
- No integration with the suppliers' systems is assumed; whether they offer any export or API is unknown.

**Baseline (measured above):** ≈64k in window now; ≈36k enters next month; ≈113k already missed.

**KPI:** % of window-eligible value returned before the window closed. Track it monthly per supplier.

**Decision:** approved for specification. Build after the full review.

**Evidence needed:**
- A sample (screenshot or export) of the Pharma Overseas / Ibn Sina return entry screen and the fields it asks for.
- Other main suppliers' return windows (Ramco, Egy Drug, …).
- The returns owner.

---

## DECISION BATCH 3 — buying, replenishment & availability (2026-10-30)

### Measured picture (office PG; read-only)

**Lost-sales estimate.** The engine's estimate (run #104, 30 days) is ≈390k EGP revenue, or ≈82k gross margin.
- **Branch 160 accounts for 223k (57%).** Its A-item availability is 94.4%; the other branches sit at 96.9–98.0%.
- Root-cause split (engine waterfall):
  - "transfer" (stock existed elsewhere) 142k
  - "supplier" (ordered, not delivered) 136k
  - "purchasing" (not ordered) 55k
  - unknown 57k

**That estimate is inferred, not observed.** `lost_sales_engine.py` estimates stockout days as "expected sale days −
actual sale days". That overstates stockouts for items that sell irregularly.

**A measured alternative exists.** The stock ledger mirror carries `newqty` (balance after each transaction) for every
branch: 97k–319k lines per branch per year.
- At branch 160, **412 of 712 A items with movement hit zero stock at least once in 90 days** (2,086 zero events).
- Real stockout duration (zero → next receipt) is computable. Class B: the `newqty` semantics per store must be
  verified on samples.

**`pos_cancel` cannot be used as lost sales as-is.** It shows ≈3.4–5.2M EGP per month of "selected-not-sold". That is
far too large to be lost sales; it mostly records cashier corrections. It needs reason codes before use.

**Orders and invoices.**
- `invoices.PurchaseOrder`: **0 rows**. Supplier orders leave `/supply` as WhatsApp text or Excel.
- OCR invoices: 81 total — 59 in review, 16 finalized, 4 confirmed, 2 push failed.
- SOFTECH has native supply-order tables (`stockordersm`/`stockorders` with `suppcode`, `poclosed`). Whether buyers
  use them for supplier orders is **unknown**.

**Already built (not re-proposed).**
- «يوجد أرخص» cheaper-supplier and «بونص زائد» flags on the shortage sheet (commit a4bdf944). Sized arbitrage
  ≈27K EGP/month.
- SOFTECH-rule ISR, the coverage writer, doc-30 phase A.

**Already pending with the owner (not re-proposed here).** Doc 30 phases B–D (توزيعة waves); doc 31 matching
unification. The order-list-per-winning-supplier idea was rejected 2026-10-08.

### Owner input (2026-10-30) — supersedes assumptions in the Batch 3 cards
**Constraint and availability**
- **Branch 160 is the biggest-selling, busiest branch.** Losses there are expected.
- **The root constraint is cash.** A cash-flow deficit means branches are replenished to only **0.8 months of
  cover**. That is "very low" and causes frequent stockouts, especially of low-selling items.

**Who decides daily replenishment**
- The HQ main-warehouse store specialists (four users) decide what goes out each day.
- Branch salespeople, and sometimes a dedicated person, create ISRs.

**When a top seller runs out**
- A phone call to HQ if HQ has it.
- WhatsApp if urgent, especially for a specific customer.
- **Most often, the branch waits for the next ISR.**

**Supplier orders**
- **Mostly Excel sheets on WhatsApp**, built from our demand pivot sheet. Phone is used for urgent items.
- SOFTECH طلب توريد is used rarely.
- An ISR can still be made from the pivot sheet.

**Supplier behaviour**
- **Unordered items arrive about once or twice a week, from any supplier.** These are supplier mistakes or pushes
  for the supplier's own incentives. They must be spotted and returned straight away.
- Missing bonus happens "sometimes". Prices above agreed: never, from main suppliers.

**Tools in use**
- Buyers **do use the engine's shortage-sheet gap**; the SOFTECH rate report less so.
- Transfer recommendations and the advanced engine **were built to be used**; the system isn't published yet.

**Shortage requests and turnover**
- Shortage requests come via both the screen and WhatsApp.
- **Transfers and faster turnover directly help the cash problem and avoid expiry.**

**Measured cash vs availability** (branches 130–170, run #104, current cost):

| Velocity | Stock held | Monthly cost of sales | Cover | Item×branch at zero | Est. lost margin/30d |
|---|---|---|---|---|---|
| Fast ≥4/mo | 2.56M | 4.48M | ≈0.57 mo | 392 | 69k (85% of the estimate) |
| Medium 1–4/mo | 1.87M | 1.98M | ≈0.94 mo | 1,874 | 11k |
| Slow <1/mo | **2.39M** | 1.45M | ≈1.6 mo | 8,922 | not estimated (the engine skips near-zero movers) |

Slow movers tie up as much cash as fast movers, while fast movers carry most of the measurable lost margin. Giving
every zero-stock slow item one pack would cost ≈2.38M, which is not affordable. Adding 0.4 months of cover to
fast and medium items would cost ≈2.58M. **The cash must be allocated, not spread.**

### P-30 · Measured availability for top sellers + a daily "out here, in stock there" list
**Module(s):** purchasing (lost-sales engine), stock_audit ledger, supply/ISR · **Type:** optimize

**Current situation.** The engine estimates stockouts from missing sale days. This cannot separate "no customer came"
from "no stock".
- A-item availability (94–98%) and lost revenue (≈390k/30d) are model outputs.
- No screen tells a branch or the replenishment buyer *this morning*: "these top sellers are at zero here, and HQ or
  branch X has them".

**Problem.** Availability of fast movers drives sales and customer trust, but it is neither measured precisely nor
managed daily. The "transfer" root cause (≈142k/30d estimated) means the stock was in the network and simply not
moved.

**Proposed behaviour.**
1. Compute **real stockout hours/days** per item × branch from the ledger `newqty` (zero → next inbound). This
   replaces the estimate for A/B items. Lost sales = stockout days × that item's normal daily sales rate.
2. Each morning, one list per branch and one for the HQ buyer: **A/B items at zero (or under 3 days' cover) where
   HQ or another branch has surplus**. One click adds the line to the next ISR, using the existing writer and legs.
3. A weekly availability KPI per branch: % of A-item days in stock (measured).

**Example (illustrative).** At 09:00, branch 160 sees that a top-selling antihypertensive has been at 0 since
yesterday 18:40, while HQ store 100 holds 14 packs. The buyer adds it to today's ISR, and it arrives with the next
إذن صرف.

**Expected benefit.**
- Recovered sales on fast movers.
- The upper bound is unclear because the current ≈390k/30d is an estimate. The first output of this card is the
  *true* figure.
- The gain is gross margin on recovered units, not revenue.

**Evidence.** Measurements above; `lost_sales_engine.py` method; branch 160 outlier.

**SOFTECH/data.**
- B: `StockLedgerLine.newqty` per store (verify on 20 samples against SOFTECH item cards).
- A: engine rates and ItemStock.
- Ledger sync is 2-hourly. A same-morning list is fine; it is not real-time.

**Measurement.**
- Measured A-item availability % per branch: baseline from the first 4 weeks.
- Stockout days on A items.
- Lines added from the list and the time to replenish.

**Effort.** Medium. The stockout calc over the ledger is a nightly job; the list reuses the ISR proposal path.

**Recurring cost.** DB job time.

**Adoption burden.** Low–medium: one buyer's morning routine; branches view it only.

**Risks.**
- `newqty` per store may mix stores, e.g. a branch with two stores. Verify first.
- Moving an item out of a branch that then runs out: only move true surplus (above the source's own cover).

**Smallest version.** Read-only measured-availability report for branch 160 vs one comparison branch, 90 days.

**Alternatives.** Keep the engine estimate. It is cheaper but unmeasured.

**Confidence.** Medium: the data exists; field semantics are unverified.

**Recommendation.** **Pilot** (report first).

**Decision required.** Approve a read-only measured-availability report (branch 160 + one other)? Does the
replenishment buyer (user 21, who raises the daily HQ→160 ISRs) own the morning list?

**Revision after owner input**
- **List owners:**
  - The HQ main-warehouse store specialists get the network list ("out at a branch, in stock at HQ/another branch").
  - Branch salespeople see their own branch's list.
- This replaces the phone and WhatsApp escalations for non-urgent cases with a list visible before the next ISR.
- Customer-specific urgent requests stay on the reservation/demand path.
- Measured stockout data also covers **slow items**, which the current engine skips. That is where the owner reports
  frequent stockouts.
- Pilot branch: **160**.

---

### P-31 · Close the order → receipt loop (use SOFTECH's own order if buyers use it)
**Module(s):** supply (order list), invoices (OCR, PO match), procurement · **Type:** extend

**Current situation.**
- `/supply` produces supplier order text/Excel. Our `PurchaseOrder` table is empty; the invoice PO-match and 3-way
  reconcile exist but have nothing to match.
- Doc 22 names "supplier pushed without our order" as a cause of HQ dead stock.
- The "supplier" lost-sales cause (ordered, not delivered, ≈136k/30d estimated) cannot be checked, because orders
  aren't recorded.

**Problem.** Nobody can answer "did we receive what we ordered, at the agreed price and bonus, on time?" Unordered
pushes, short deliveries, missing bonus and price creep pass unnoticed. Supplier service level
(`SupplierProfile.service_level_pct`) has no order basis.

**Proposed behaviour.**
- **Step 0 (read-only):** check whether buyers already create supplier orders in SOFTECH (`stockordersm` with
  `suppcode`). If yes, mirror them; **no parallel PO in our system** (Rule 6). If no, the `/supply` order commit
  writes our existing `PurchaseOrder`.
- At receipt (doc 10, or OCR invoice), compare against the order per line: qty, price/discount, bonus. Flag:
  - **unordered lines**;
  - **short / over delivery**;
  - **bonus missing**;
  - **price above the agreed price**.
- A supplier scorecard: fill rate, days to deliver, unordered value.

**Example (illustrative).** We order 50 packs + 5 bonus from a distributor. The invoice shows 50 packs, 0 bonus, and
30 packs of an item we never ordered. The receipt check flags "bonus missing (5)" and "unordered 30 packs —
EGP 4,200". The buyer disputes it before posting.

**Expected benefit.**
- Working capital: refuse or return unordered stock.
- Margin: claim missing bonus and correct prices.
- A supplier fill rate to steer orders.
- Size unknown until the first month is compared.

**Evidence.** PO table empty; doc 22 §2 cause; invoices PO-match code (`invoices/views.py:699`,
`writer.reconcile_three_way`).

**SOFTECH/data.**
- A: PurchaseLine (doc 10/120, FOC lines `pharmacydiscp=100`).
- B: SOFTECH `stockordersm/stockorders` supplier usage (probe needed).
- C: if buyers don't use SOFTECH orders, our order commit must capture qty/price/bonus.

**Measurement.**
- % of received lines that match an order.
- Unordered value received per month.
- Bonus claimed vs promised.
- Supplier fill rate.

**Effort.** Medium (depends on step 0).

**Recurring cost.** None material.

**Adoption burden.** Medium: buyers must commit orders through one place.

**Risks.**
- Extra steps for buyers. Mitigation: the order commit is the step they already do (the WhatsApp text); the system
  just keeps a copy.

**Smallest version.** Step 0 probe + an "unordered / short / missing bonus" report for the two largest suppliers.

**Alternatives.** Rely on the invoice OCR review only (today; 59 invoices in review).

**Confidence.** Medium.

**Recommendation.** **Research further (step 0), then pilot.**

**Decision required.** ~~Do your buyers place supplier orders inside SOFTECH?~~ Answered: mostly Excel on
WhatsApp from our demand pivot sheet; SOFTECH orders are rare.

**Revision after owner input — narrowed to "spot unordered and short deliveries the same day":**
- When the buyer exports the order Excel from the shortage sheet or `/supply`, the system **keeps that sheet as the
  order record** (supplier, item, qty, bonus). There is no new step: it is the export they already do.
- When the supplier's purchase lines arrive (doc 10 mirror, refreshed every 30 min), any line with **no matching
  order in the last N days** is flagged **"unordered — return now"** to purchasing. "Bonus missing" is flagged too.
- The price check is dropped: the owner reports main suppliers never exceed the agreed price.
- **Link to P-29:** returning unordered stock immediately also avoids it ageing into expiry.

**Expected frequency:** 1–2 unordered deliveries per week (owner).

**Recommendation:** **pilot** with the two largest suppliers.

**Decision required:** approve the narrowed version for specification?

---

### P-32 · One authority per replenishment decision; retire the unused engines
**Module(s):** purchasing, supply, shortage, forecasting · **Type:** simplify / retire

**Current situation.** About six planners overlap [C]:
- DemandEngine.
- AdvancedEngine (export-only, "experimental").
- SOFTECH-rule ISR vs engine-rule ISR (a buyer picks without guidance).
- TransferEngine: **527,841 recommendations, 1 approved**; used only to label a lost-sales root cause.
- L3 توزيعة.
- ISR fulfilment donor plan, plus shortage stock-check.

Item forecasts `forecast_30d/90d` are computed nightly and read by nothing.

**Problem.** Buyers and maintainers face several answers to "how much do we need and where from". Unused engines cost
run time, DB growth (ItemDemandMetrics 3.27M rows, TransferRecommendation 528k) and confusion.

**Proposed behaviour.** You name one authority for each decision:
- **How much a branch needs:** SOFTECH-rule ISR (in daily use).
- **What moves between branches:** توزيعة (doc 30).
- **What to buy:** the engine gap on the shortage sheet.

Everything else is retired or demoted:
- **Stop** the TransferEngine job. The "transfer" lost-sales cause is recomputed from the distribution plan.
- **Keep AdvancedEngine as a lab tool** (no scheduled run).
- **Drop** `forecast_30d/90d`, or feed it into the gap; you choose.
- **Merge** the shortage stock-check into supply.
- **Add a retention policy** for `ItemDemandMetrics` (keep the last N runs).

**Example.** The ISR screen stops offering an unexplained "engine vs SOFTECH" rule choice. It shows the SOFTECH rule,
with the engine figure as a reference column.

**Expected benefit.** Simplicity and buyer speed; DB and run-time savings; one consistent number in meetings.

**Evidence.** Measured row counts; supply-side reviewer report (02 §7).

**SOFTECH/data.** None new.

**Measurement.**
- Scheduled engine jobs before vs after.
- DB size.
- Buyer-reported confusion: ask the buyers.

**Effort.** Small–medium, mostly removals.

**Recurring cost.** Lower than today.

**Adoption burden.** Low.

**Risks.** Removing something a buyer relies on. Mitigation: confirm with the buyers; stop jobs before deleting code.

**Note.** This repeats part of deferred P-04 (stopping TransferRecommendation). It is raised again only because it is
central to the buying review.

**Smallest version.** Stop the TransferEngine job + an ItemDemandMetrics retention policy.

**Alternatives.** Leave as is.

**Confidence.** High.

**Recommendation.** **Approve for specification**; confirm the authorities with the buyers.

**Decision required.** Do you agree with the three named authorities (SOFTECH-rule ISR / توزيعة / engine gap)?

**Revision after owner input — consolidate before launch; nothing is retired.**
- The owner built transfer recommendations and the advanced engine to use them, and transfers and turnover matter
  for cash. So the change is **consolidate before publishing**:
  - The TransferEngine's shortage-driven moves become a **wave inside توزيعة**, using doc-30's whole packs, value
    threshold and wave ordering, instead of 7k fractional recommendations per run on a separate screen.
  - The advanced engine's **cash-budget ROI ranking** becomes the basis of P-34.
  - Item forecasts feed the gap, or stop.
  - The shortage-sheet gap stays the buying authority. The owner confirms buyers use it.
- **Decision required:** agree to consolidate into those three authorities before publishing?

---

### P-33 · Close the small handoffs in the supply flow (quick fixes bundle)
**Module(s):** shortage, supply, transfers, transits, purchasing · **Type:** optimize

**Current situation [C].**
- **(a)** Shortage stock-check finds donor branches but can only export to Excel (`ShortagePage.jsx:1081`).
- **(b)** Market-shortage flags set while SOFTECH was offline are never retried; the `sync_shortage_softech` retry is
  unscheduled. So the POS warning silently misses them.
- **(c)** Transits link SOFTECH 125 docs to TransferRequests by docnumber only. Docnumbers are per (branch, doctype),
  so mislinks are possible.
- **(d)** Shortage exports read SOFTECH live although a nightly `ItemSupplierLink` mirror exists.
- **(e)** The procurement refresh stalled on 18-10 because the scheduler PC slept. This is resolved by the VPS
  cutover — verify after cutover.

**Proposed behaviour.**
- (a) A "create ISR/transfer draft" button reusing `supply/execution`.
- (b) Schedule the retry hourly.
- (c) Key the link on (branch, doctype, docnumber, date).
- (d) Exports read the mirror.
- (e) A post-cutover freshness check.

**Expected benefit.** Staff time; correct POS shortage warnings; correct transfer status; fewer slow exports.

**Evidence.** Code refs above.

**SOFTECH/data.** A.

**Measurement.**
- Excel exports vs drafts created.
- Unsynced shortage flags (target 0).
- Mislinked transits found.

**Effort.** Small (each item hours, not days).

**Adoption burden.** None.

**Risks.** Low.

**Smallest version.** (b) + (c) — correctness fixes.

**Confidence.** High.

**Recommendation.** **Approve for specification** (quick wins).

**Decision required.** Approve the bundle for specification?

**Revision after owner input:**
- Both channels (the screen and WhatsApp) are used, so the "create transfer draft" action goes on **both** the
  shortage stock-check and the `/supply` WhatsApp-request analysis.
- Turnover and transfers are a direct cash lever (owner).

---

### P-34 · Spend the scarce cash where it earns: velocity-tiered cover under a cash budget
**Module(s):** purchasing (engine gap, SOFTECH-rule ISR, advanced engine phase E, coverage writer), supply, batches
(P-26–29 cash release) · **Type:** optimize / extend existing

**Current situation**
- **Cover is applied uniformly.** Every item goes to about 0.8 months of cover: ISR `itemqty = ceil(rate × 0.8 −
  stock)` (memory: SOFTECH ISR rule).
- **Slow movers tie up 2.39M** at about 1.6 months of cover. Pack rounding means one pack of a slow item lasts months.
- **Fast movers sit at about 0.57 months**, measured mid-cycle, and carry about 85% of the estimated lost margin.
- **The ranking logic already exists.** The advanced engine has a Phase E "ROI priority under a cash budget":
  monthly gross margin per EGP invested × urgency × confidence × ABC (`advanced_engine.py:307-319, 472-485`). It is
  export-only.

**Problem**
- With a fixed purchase budget, uniform cover starves the items that earn and leaves cash in items that rarely sell.
- The owner's stated root cause is "cash-flow deficit → 0.8 months → frequent stockouts".

**Proposed behaviour.** Keep the total cash the same and change where it goes.
1. **Velocity-tiered target cover**, owner-set per tier. Illustrative: fast 1.0 mo, medium 0.8 mo, slow =
   **"presence"** (keep 1 pack only where the item sold at this branch in the last 6 months, or a known chronic
   customer buys it; otherwise **order on demand** via reservation/demand).
2. The shortage sheet gains a **"within budget" column**. The buyer enters this cycle's cash budget. Lines are ranked
   by Phase-E ROI, and lines inside the budget are marked "fund now". There is no auto-ordering; the buyer decides.
3. A **cash loop view**:
   - Cash released this month: supplier returns and credits (P-29), unordered stock returned (P-31), and purchases
     avoided by moving dead stock (P-27).
   - Cash spent on cover.
   - Measured availability (P-30).

**Example (illustrative).** The weekly purchase budget is EGP 1.2M. The sheet ranks needs. A fast-moving
antihypertensive (high margin per EGP, 0.3 months of cover left) is funded first. A slow cosmetic at one branch with
no local sale in 6 months is marked "order on demand" and not funded. The 2.38M "one pack of everything" option never
happens.

**Expected benefit**
- Gross margin from fewer fast-mover stockouts, within the same cash. The upper bound is about 69k/30d of estimated
  lost margin on fast movers; the realised share will be measured via P-30.
- Lower slow-mover stock frees cash over time.
- **Benefit hygiene:** this reallocates cash; it does not add cash. Revenue gains count as gross margin only.

**Evidence**
- Measured table above; ISR rule (memory).
- Advanced engine Phase E code.
- Owner input.

**SOFTECH/data**
- A: engine rates, cost and price, ABC, ISR writer (live).
- B:
  - The tier policy would also change SOFTECH `maxnowqty` via the coverage writer (ON in the office `.env`). This is
    a SOFTECH write and must be confirmed per Rule 3.
  - Chronic-customer item list from followups/customers.

**Measurement**
- Measured A/fast-item availability (P-30).
- Slow-mover stock value.
- Gross margin per EGP of average inventory (GMROI) per branch.
- Stock turns.
- Pilot: branch 160 vs a comparison branch over 8 weeks, same budget share.

**Effort.** Medium.
- The tier policy is configuration in the ISR rule and engine target.
- The budget column reuses Phase E.
- The cash loop view depends on P-27, P-29, P-30 and P-31.

**Recurring cost.** None.

**Adoption burden.** Medium. Buyers set a budget per cycle; branches accept "order on demand" for some slow items.

**Risks and safeguards**
- **Pharmacy service (Rule 4):** never let a chronic patient's medicine drop to on-demand. Presence is guaranteed for
  items with an active chronic customer at that branch.
- **Customer trust:** an on-demand item needs a reliable reservation path with the delivery time stated.
- **Supplier minimums and bonus deals:** these may push toward larger buys. The buyer can override.

**Smallest version.** A read-only "what tiered cover would change" report for branch 160: extra cash needed for fast
movers vs cash freed from slow movers. No change to ISR quantities until reviewed.

**Alternatives**
- Raise cover across the board. This needs cash the business doesn't have.
- Keep the status quo.

**Confidence.** Medium. The direction is well supported; the realised availability gain must be measured.

**Recommendation.** **Pilot** (report first).

**Decision required.** Approve the read-only tiered-cover report for branch 160? And do you agree that slow items
without a local sale in 6 months and without a chronic customer can become "order on demand"?

---

## DECISION BATCH 4 — sales & margin (2026-10-30)

### Measured picture (office PG; sales doc 115, last 90 days; read-only)

**Margin basis.** Gross margin = `line_total` − qty × `cost_at_sale`. **Caution:** sale price may include VAT while
cost is pre-VAT (memory: stock audit). For taxed items this overstates margin. Medicines are largely VAT-exempt.
Confirm the basis with finance.

**Sales by channel** (customer class stamped on the invoice):

| Channel | Revenue 90d | Gross margin | Lines with customer discount | Avg discount when given | Lines below cost |
|---|---|---|---|---|---|
| Contracts / credit (10, تعاقدات/آجل) | **11.26M (≈46%)** | **15.6%** | 100% | 14.7% | 381 |
| Cash (91) | 9.41M | **25.5%** | 15.8% | 7.7% | 190 |
| Delivery (90) | 2.87M | 16.8% (before delivery cost) | 27.0% | 9.3% | 52 |
| Regular customer (30, عميل دائم) | 0.77M | 16.7% | 97.9% | 11.5% | 31 |
| Staff (11) | 0.14M | 13.1% | 99.9% | 13.9% | 13 |
| Donations (16) | 0.20M | −5.8% | 84% | 41.7% | 443 |
| Company compensations (17) | ≈0 revenue / 22.8k cost | — | — | — | 16 |

**Contracts**
- 38 contracts, all at 13–17% margin. None is loss-making.
- 4 contracts make up 62% of contract revenue.
- The lever is credit terms and collection: about half of sales are on credit, while the business is cash-constrained.
  That is finance (Batch 7), not pricing.

**Customer identification (cash channel)**
- **55.9% of cash invoices go to anonymous walk-in placeholder accounts.** Delivery is 0%; regular customers 27%.
- Identified customers in 90 days: 12,425. 28% bought twice or more; 9% bought four times or more.

**Built but dormant**
- The POS writer is OFF: 58 orders ever, none since 2026-09-06.
- Offer execution and both SOFTECH offer channels are OFF; 1 offer exists.
- Django vouchers: 11, not linked to the POS.
- Loyalty runs two ledgers (SOFTECH `picpoints` vs Django). The portal shows the Django one.
- Basket suggestions rank VIP customers by price (`basket_intelligence.py:91`).

**Margin is not used where decisions are made**
- Customer LTV is revenue-only.
- Price-change impact (`discount_impact`) is quantity and revenue only.
- Analytics values "capital tied" at selling price.
- POS orders store COGS that no report reads.

### Owner input (2026-10-30) — supersedes assumptions in the Batch 4 cards

**Discounts**
- **Cashiers may NOT discount beyond the customer's class discount or the item's discount ceiling.**
- So any line above policy is a violation, not a judgement call.

**Promotions**
- **Yes, in-app promotions are planned in the coming months.**
- P-38 is therefore active, and its go-live gate becomes required.

**POS writer**
- Switching on the POS writer is **part of the cutover**.
- The owner states it **needs further development and 100% matching to SOFTECH behaviour**, while still bringing in
  the new capabilities and writing correctly to SOFTECH. → New card P-39.

**Margin visibility**
- The owner looks at margin by branch and channel today, mostly in SOFTECH reports, "but not clearly visible".

**Delivery cost**
- Delivery fee = **item code 2 «D.L.V.»**, charged at 13 EGP per unit, cost 0.
- The rider gets **10 EGP per fee unit**, multiplied for distant orders.
- Motorcycle riders get **a minimum of 50 EGP per day**.
- For inter-branch physical transfers, or distant orders kept to avoid cancellation, **the rider is paid extra in cash
  from the branch** that day.

**Customer identification**
- Salespeople ask for the phone number, but not often and only when reminded.
- **They may skip it when the customer is in a hurry or one person is alone at the counter.**
- **Yes** to counting the identified-sale rate in gamification and branch targets.

**Contracts**
- Finance tracks collection: **contract companies pay in 45–75 days.**
- Indicative: ≈11.26M EGP of contract sales per 90 days ≈ 125k per day. At 45–75 days that means **≈5.6–9.4M EGP
  tied in receivables**, the same order as the whole branch inventory.
- Top item for the finance batch.

**Measured delivery economics** (90d, channel 90):
- **Order size:** 3,550 orders, median EGP 250, average 810.
- **Small orders:** 829 orders (23%) were under EGP 100.
- **Fee line:** «D.L.V.» appears on **2,312 orders (65%)**, so 1,238 delivery orders carried no fee line. Fee revenue
  was EGP 45.3k on 3,483 units; the rider share is ≈34.8k before daily minimums and branch-paid extras.
- **Below the rider's fee:** **278 orders (8%) earned under EGP 10 gross margin.** That includes the fee line at zero
  cost, so the real figure is worse.
- **Branch-paid extras** to riders are **not recorded in any system we mirror** (class C).

### P-35 · One margin basis, used everywhere decisions are made
**Module(s):** analytics, customers (segmentation/LTV), discount_approvals (impact), recommendations, insights,
dashboard · **Type:** optimize

**Current situation.** The margin facts exist: `PurchaseHistoryLine.cost_at_sale` and the per-line discount fields.
But most commercial numbers ignore them [C]:
- LTV = revenue.
- Price-change impact = revenue.
- VIP suggestions ranked by price.
- Inventory capital at selling price.

The VAT treatment is inconsistent between price and cost.

**Problem.** Revenue-based numbers reward volume at any margin. Under a cash constraint, the right measure is gross
margin per EGP of stock (GMROI) and margin per customer and channel.

**Proposed behaviour.**
1. One shared margin function: VAT-aligned, `cost_at_sale`, free units at cost.
2. Swap it into LTV and segments, the price-change impact report, basket ranking (margin, **after** the safety
   filter), and analytics capital (at cost).
3. A **channel × branch margin board**: revenue, gross margin %, discount % and GMROI. Delivery is shown after a
   per-order delivery cost the owner enters.

**Example (illustrative).** The board shows delivery at 16.8% gross margin. At an owner-entered EGP 25 cost per
order, contribution drops to about X%, which informs delivery minimum-order or fee decisions.

**Expected benefit.** Decision quality: which channels, customers and price changes actually earn. No direct cash
claimed.

**Evidence.** The table above; code refs in 02 §3.4.

**SOFTECH/data.**
- A: `cost_at_sale`, discount fields, channel.
- B: the VAT basis (confirm with finance); delivery cost per order is an owner input (C).

**Measurement.**
- Board in use (telemetry or owner check).
- Decisions logged: price changes judged on margin delta.

**Effort.** Small–medium.

**Recurring cost.** None.

**Adoption burden.** Low.

**Risks.** A wrong VAT alignment misstates margin; validate on 20 invoices against SOFTECH.

**Smallest version.** The shared margin function + the channel × branch board.

**Confidence.** High on data, medium on the VAT basis.

**Recommendation.** **Approve for specification.**

**Decision required.** Approve, and who in finance confirms the VAT basis?

**Revision after owner input — delivery contribution per order:**
- Formula: gross margin − (fee units × 10 EGP × distance multiplier) − the share of the motorcycle daily minimum −
  branch-paid extras.
- **Branch-paid extras need capture.** Riders' extra cash from the branch is not recorded anywhere we can read. The
  smallest capture is a one-line "rider extra paid" entry on the delivery order in our delivery module, which already
  has riders and orders.
- The board flags:
  - orders whose margin is below the rider cost;
  - delivery orders without a «D.L.V.» fee line (1,238 in 90 days). Is that intentional free delivery or a missed fee?

The owner says SOFTECH margin reports are "not clearly visible", so the channel × branch board fills a real gap.

---

### P-36 · Discount leakage report (read-only; no change to discount rules)
**Module(s):** stock_audit (below-cost rule exists), customers (sales lines), discount_approvals · **Type:** extend

**Current situation.**
- Six discount paths, each with its own guard: item `posdiscp`, contract `custdiscounts`, offers, vouchers, gift
  coupons, loyalty.
- No order-level margin floor.
- In 90 days: **15.8% of cash-sale lines carry a customer discount (avg 7.7%)**, and **≈670 lines sold below cost**
  across channels.
- stock_audit already flags below-cost sales (all 915 findings are open).

**Problem.** We cannot see which discounts are policy (contract, regular customer) and which are discretionary
(cashier or branch). Nor by whom, at which branch, on which items. Under a cash constraint, leaked margin is lost cash.

**Proposed behaviour.**
- A weekly read-only report by branch, cashier (SOFTECH user on the invoice), channel and item group:
  - discount EGP;
  - discount as % of revenue;
  - lines below cost;
  - **discount above the customer's or item's policy** (actual line discount vs the expected discount for that
    customer class or item).
- No rule changes. Any later change to discount calculation is a separate stop-and-ask decision (CLAUDE.md).

**Example (illustrative).** Branch 150, cashier X: 4.1% of cash revenue given as discount, against a 1.2% network
median. 60% of it is on three cosmetics items above their `posdiscp`. The branch manager reviews it.

**Expected benefit.** Margin recovered by enforcing existing policy. Size unknown until the "above policy" part is
computed; the first report is the baseline.

**Evidence.** Measured shares above; stock_audit rule `sale_below_cost`; discount paths in 02 §3.4.

**SOFTECH/data.**
- A: per-line discount fields, SOFTECH user, channel.
- **B: whether `disc_customer_pct` is the customer-class policy or a manual cashier discount.** Validate by comparing
  to the customer class discount and item `posdiscp` on samples.

**Measurement.**
- Discretionary discount % of cash revenue per branch (baseline first month).
- Below-cost lines per month.

**Effort.** Small–medium.

**Recurring cost.** Branch manager review time.

**Adoption burden.** Low–medium; this is sensitive for staff, so present it as coaching, not blame.

**Risks.** Misreading policy discounts as leakage; the B-validation comes first.

**Smallest version.** Below-cost + above-policy lines for two branches, one month.

**Confidence.** Medium.

**Recommendation.** **Pilot** (read-only).

**Decision required.** ~~Are cashiers allowed beyond policy?~~ Answered: **no**.

**Revision after owner input**
- Every line discounted above the customer-class discount or the item ceiling is a **policy breach**. The report
  lists breaches by branch, cashier and item, with EGP value.
- Below-cost lines stay as a separate list. Some are policy-legal: contract terms, donations (channel 16), and
  company compensations (17), which are shown separately and excluded from breaches.
- B-validation still comes first: confirm that the expected-discount calculation matches SOFTECH on samples.

**Recommendation:** pilot (read-only), all branches. The rule is clear, so a two-branch limit is not needed.

---

### P-37 · Identify the customer at the till (and one loyalty ledger)
**Module(s):** customers, loyalty, portal, pos_orders (search), gamification (optional) · **Type:** optimize /
simplify

**Current situation.**
- 56% of cash invoices go to anonymous placeholder accounts.
- Without the customer, there is no refill follow-up, no allergy safety, no recovery matching and no loyalty.
- Loyalty has two ledgers. The portal shows the Django balance, while SOFTECH `picpoints` is the real one
  (`PortalLoyaltyPage.jsx:28` vs `LoyaltyPage.jsx:61`).

**Problem.** Retention, chronic refill and safety all start with knowing who the customer is. Today that is known for
under half of cash sales.

**Proposed behaviour.**
1. An **identified-sale rate KPI** per branch and per cashier (SOFTECH user on the invoice), shown weekly on the
   dashboard. This is measurement plus feedback.
2. Optionally, gamification points for identified sales (a non-medicine metric, so it carries no safety conflict).
3. Loyalty: **SOFTECH `picpoints` is the only ledger.** The portal and staff pages show it. Django tiers and rewards
   are retired, or kept as display only.
4. The fastest phone-number lookup (already built for the POS search) is also offered on the call-centre and
   reservation screens.

**Example (illustrative).** Branch 140's identified rate is 31% against a network 44%. The branch sets a target of
50%; cashiers ask for the phone number at payment.

**Expected benefit.** It enables retention, refills and safety. Directly measurable as the identified-sale rate.
Commercial benefit comes later through other proposals; it is not claimed here.

**Evidence.** Measured shares; loyalty two-ledger code.

**SOFTECH/data.** A: invoice customer + SOFTECH user. Customer capture happens at the **SOFTECH cashier screen**, so
this is a process lever, not a code lever.

**Measurement.** Identified-sale rate per branch and cashier (baseline 44% cash); repeat-customer rate.

**Effort.** Small (KPI + ledger fix).

**Recurring cost.** None.

**Adoption burden.** Medium: a counter habit (ask for the phone number).

**Risks.**
- Privacy: collecting a phone number needs a purpose notice. Consent was deferred (P-05). Flag it when outbound
  messaging starts.
- Customer annoyance: keep it optional.

**Smallest version.** KPI + portal ledger fix.

**Confidence.** High.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Gamification?~~ Answered: **yes**, in gamification and branch targets.

**Revision after owner input**
- **Skipping is allowed** when the customer is in a hurry or one person is alone at the counter. So the target is a
  realistic rate, not 100%.
- The KPI is read alongside staffing: invoices per counter-hour. That way a single-staffed branch isn't penalised.
- The gamification rule rewards identified sales with a daily cap, consistent with the existing caps.

---

### P-38 · Offers & vouchers: one engine, and a go-live gate
**Module(s):** offers, vouchers, discount_approvals, pos_orders · **Type:** simplify + gate

**Current situation.**
- The offers engine is built: preview live, execution OFF, both SOFTECH channels OFF, 1 offer.
- Django vouchers duplicate offer discount types and are not linked to the POS (manual `mark-used` amount).
- Gift coupons are separate and live.
- Offer evaluation is N+1 (~5 queries per active offer per basket edit).
- Offer targeting has **no Rx/medicine-class exclusion** (`offers/targeting.py:181`).

**Problem.** Two promotion engines, an unguarded medicine path, and execution that touches discount and SOFTECH
writes. Switching on as-is risks margin and Rule 4 breaches.

**Proposed behaviour.**
- Merge Django vouchers into offers as a "coupon code" trigger. Gift coupons stay as they are.
- Before any execution switch-on, a **go-live gate**:
  - (a) Rx/sensitive-class exclusion. This is part of deferred P-01; **it re-surfaces here as a dependency**, as the
    ledger noted it would.
  - (b) An order-level margin floor (needs P-35; a stop-and-ask decision).
  - (c) The N+1 fixed.
  - (d) Offer ROI reporting: uplift in units and margin vs a prior period.
- Until then, offers stay preview-only.

**Expected benefit.** Avoid the risk; promotions measured on margin when they start.

**Evidence.** Code refs above.

**SOFTECH/data.** A for preview. Execution writes `posdiscp` / `specialoffers` (gated; stop-and-ask).

**Measurement.**
- Gate checklist complete.
- After launch: offer margin uplift vs a control period.

**Effort.** Medium.

**Adoption burden.** Low until launch.

**Risks.** As above.

**Smallest version.** Merge vouchers into offers + the class exclusion.

**Confidence.** High.

**Recommendation.** **Approve for specification; execution go-live is a separate decision later.**

**Decision required.** ~~Do you plan promotions?~~ Answered: **yes**.

**Revision after owner input**
- The card is active. The go-live gate is **required before the first promotion**:
  - (a) the Rx/sensitive-class exclusion, from deferred P-01(b), now a hard dependency;
  - (b) the margin floor;
  - (c) the N+1 fix;
  - (d) offer reporting.
- Promotions execute **through the POS writer** (P-39), so the two go live together.
- Promotion content must respect the medicine-advertising controls (04 §1): no medicine promotion on public channels
  without approval.

---

### P-39 · POS go-live: 100% SOFTECH parity, then the new capabilities
**Module(s):** pos_orders (writer, reconcile, offline queue), offers, vouchers/coupons, loyalty points ·
**Type:** extend (go-live readiness)

**Current situation**
- The indirect POS is built: desktop + mobile, 35 endpoints, speed wave, discount authority, FEFO split,
  contract-assist.
- The writer is **OFF**: 58 orders ever, none since 2026-09-06.
- The owner states it needs more development and **100% matching to SOFTECH behaviour** before cutover.

**Prior method (memory)**
- "Golden-template verify": replicate a native sale via a rollback probe and diff every field.
- Points must be written (`personnewbal`).
- Pack/strip quantities: `transqty = round(strips/packqty, 5)`.

**Known POS performance issues [C]**
- Discount-suggest fires on every edit with no debounce.
- About 2 live Sybase queries per item.
- Offer evaluation is N+1.

**Problem**
- The POS is where promotions (P-38), customer identification (P-37), allergy safety and margin control (P-36) all
  meet.
- A writer that differs from the native client risks wrong totals, wrong points or double posting. Rules 2, 3 and 8
  apply.

**Proposed behaviour (specification only; checkout and posting = stop-and-ask at every step)**
1. **Parity suite:** for every sale shape, compare our writer's rows with a native SOFTECH sale of the same basket,
   field by field. Shapes:
   - cash / credit-contract / delivery / regular customer;
   - strips vs packs;
   - FEFO multi-batch;
   - customer + points;
   - posdiscp discount;
   - returns;
   - gift coupon line;
   - offer line.

   It runs on the SOFTECH test host when available, otherwise as a rollback probe (existing method). **100% match is
   the exit criterion.**
2. **Performance before go-live:** debounce and batch discount-suggest; cache reference reads; fix the offer N+1.
3. **Phased go-live:** one branch, one channel (cash) and read-back reconciliation for 2 weeks. Then add channels.
   Then turn on promotions (P-38).
4. **Idempotency:** `client_token` is already unique. Reconcile every order to a final SOFTECH docnumber; the
   offline queue's double-post guard stays as built.

**Expected benefit**
- Enables the new capabilities at the counter.
- Sale-level cost and margin capture (COGS stored per order).
- Fewer re-keying steps for call-centre and delivery orders.

**Evidence**
- Code: `pos_orders` writer flags (`settings.py:484`).
- Adoption counts.
- Memory: golden-template method, points mechanism, strip quantities.

**SOFTECH/data**
- A: the pending-order tables (`stktransm5` / `stktrans5` / `branchesales5`), fully investigated.
- B: per-shape parity proof.

**Measurement**
- Parity: 100% of fields across all shapes.
- Live pilot: reconcile success 100%; 0 double posts; cashier settle time.

**Effort.** Large (parity across shapes is the bulk).

**Recurring cost.** Maintaining the parity suite when SOFTECH updates.

**Adoption burden.** High at the pilot branch: training. Mitigated by the in-app help and tours already built.

**Risks.** Financial accuracy and double posting. Mitigation: parity gate, single writer instance (VPS), kill-switch,
pilot branch.

**Smallest version.** The parity suite for the cash shape + the performance fixes.

**Confidence.** High on method, medium on effort.

**Recommendation.** **Approve for specification** (owner-initiated). Every build step touching posting is
stop-and-ask.

**Decision required.** Approve for specification, and which branch should pilot the POS go-live?

---

## DECISION BATCH 5 — finance & cash (2026-10-30)

### Measured picture (office PG; read-only)

**Receivables**
- **Contract-company receivables are not mirrored anywhere.** The finance mirror (`finance.Payment`,
  `finance.APInvoice`, built for A/P reconciliation, doc 23) holds **suppliers only**.
- Owner (Batch 4): contracts pay in 45–75 days. Contract sales ≈11.26M per 90 days, so **≈5.6–9.4M EGP is tied up**.
- The insurance module has a claim collection lifecycle: submitted → partially paid → paid, expected payment date,
  payments, deductions. **It is unused for collection: 101 claims in "draft" (19.4M, periods 2024-06 → 2026-09),
  4 "submitted", 0 payments recorded.**

**Supplier payments and payables**
- Supplier payments run at ≈4.5–6.5M EGP per month (last 6 months).
- **Post-dated cheques already written:** Nov 2.31M, Dec 1.06M. That is committed cash, already in the mirror.
- **No due dates.** 0 of 6,919 supplier invoices from the last 90 days carry a due date, so supplier credit terms are
  unknown to the system.
- **Most of the balance is not real payables.** SOFTECH supplier balances total 38.3M, but the largest are internal
  or virtual accounts:
  - 1268 gift coupons: 12.5M.
  - 3068 "general supplier" / patient buy-back: 9.05M.
  - Contract suppliers 4470–4472 (replacement entitlements): ≈4.7M.
  - Real distributors are much smaller: Pharma Overseas 3.28M, Ramco 2.27M.

**Open purchase-invoice value (doc 10) by age**

| Age | Open value |
|---|---|
| 0–30 days | 5.59M |
| 31–60 days | 2.89M |
| 61–90 days | 0.35M |
| 91–180 days | 1.33M |
| 181–365 days | 2.38M |
| **More than 1 year** | **10.60M** |

Of the more-than-1-year bucket, 5.36M is service-vendor and ≈1.67M patient-repurchase accounts. This looks like
reconciliation residue, not money owed.

**Stale and standalone tools**
- The finance hub's journal and treasury mirrors stop at **May 2026**. Only the P&L snapshot is scheduled; the rest is
  a manual sync.
- The standalone cheque planner (`apps/cheques`) has **0 plans**. It duplicates the cheques the mirror already holds.
- The A/P reconciliation writer is OFF (doc 23 Phase G, gated); approved allocations are still keyed by hand. This is
  an existing roadmap item, not re-proposed.

### Owner input + read-only SOFTECH probe (2026-10-30) — supersedes assumptions in the Batch 5 cards

**Owner answers**
- **Contract collections:** finance tracks them in **both SOFTECH and Excel**. **Each contract has agreed payment days
  in writing.**
- **Supplier terms:** credit days vary, because **cheques are written per item-category total**, mostly in three
  categories:
  - **local**;
  - **imported**;
  - **non-discounted** (mostly local items without extra discount; a little more credit than local, not handled like
    imported).
- Suppliers are paid **on time**.
- **Early payment does earn a discount or bonus, but the cash constraint prevents it now.**

**Finance screens**
- Used: the **gross-profit page** and the **expense pages**. Branch expenses are recorded there; HQ expenses are in
  Excel.
- Cash flow: not really used.
- **A full accounting module to eliminate Excel is wanted later, not now.** The balance sheet, income statement and
  chart of accounts already in the mirror are a good base.

**Weekly cash view audience**
- All finance users (four named staff) and all admins, including the owner.

**Insurance**
- The team uses the module to **prepare and print claims only**. Submission and payment are tracked elsewhere;
  **embedding that is wanted later.**

**Read-only probe** (owner-approved; `SOFTECH_READ_ONLY=True`; SELECT via the existing
`apps/finance/queries/sybase_reconciliation.py` customer path; scoped to 2 contracts × 120–150 days)
- **Contract receivables ARE in SOFTECH and fully linkable:**
  - sales and returns (`stktransm` 115/30, party = contract code);
  - receipts (`cheques`, party `ptcode = 10`);
  - **receipt-to-invoice allocations** (`chequestrans`).
- **The existing reconciliation engine already supports `party_type='customer'`** (ingest maps 115/30 → customer,
  direction "in"). Only the sync filter is supplier-only. Class **A** after verification.

| Contract | Invoices (120d) | Value | Paid so far | Receipts | **Measured collection days** (value-weighted, invoice → receipt) | Max |
|---|---|---|---|---|---|---|
| 4227 (largest) | 2,621 | 3.41M | 2.50M | 1 per month, ≈0.70–0.78M | **≈44 days** | 60 |
| 4288 | 1,176 | 2.35M | 1.67M | 1 per month, ≈0.44–0.54M | **≈42 days** | 60 |

- **Pattern:** monthly settlement. Each month's invoices are paid at the end of the following month.
- **No due date** on any invoice (`docpaydue` empty).
- **Receivables tied up:** the earlier estimate (≈5.6–9.4M) narrows toward the low end. At ≈125k EGP/day of contract
  sales × ≈43 days, that is **≈5.4M**, still the single largest cash item found.
- **Side note for the cutover:** the office DB has unapplied migrations (`sync` 0006, `help` 0007–0012). The probe's
  load-stat logging failed on the missing local table. The VPS install applies them; this is not a SOFTECH issue.

### P-40 · A 13-week cash view (what's coming in, what's going out, what's committed)
**Module(s):** finance (A/P mirror, P&L), cheques (merge), purchasing (P-34 budget), insurance / P-41 (receivables) ·
**Type:** extend + merge

**Current situation.**
- Cash-relevant facts exist in pieces: post-dated cheques (mirrored), open payables (mirrored, no due dates), and
  sales run-rate (mirrored).
- Receivables are not mirrored.
- The cash-flow page is stale (journal and treasury stop at May).
- The cheque planner is unused.

**Problem.**
- The business is cash-constrained (owner). Purchase cover (P-34), supplier payments and collections are decided
  without one forward view of cash.

**Proposed behaviour.** One weekly view, 13 weeks ahead.
- **Out:**
  - committed post-dated cheques by week;
  - real-supplier payables by due date (after P-42);
  - the planned purchase budget (P-34).
- **In:**
  - cash and delivery sales run-rate by week (from the sales mirror);
  - expected contract collections (P-41).
- **Result:** the projected weekly cash gap, with a "what if" for the purchase budget.

Internal and virtual accounts (1268, 3068, 4469–4472) are shown separately, never mixed with real supplier debt. The
standalone cheque planner merges into this view.

**Example (illustrative).** The view shows week 47 dipping to −0.8M: 1.1M of post-dated cheques due, plus a planned
1.2M purchase, against 1.5M of expected inflows. Finance moves 0.4M of purchases a week later, or chases two
contracts due that week.

**Expected benefit.**
- Fewer cash crunches.
- Purchases timed to cash (feeds P-34).
- Earlier collection action.

Benefit is in decision quality; no profit figure is claimed.

**Evidence.** Measurements above.

**SOFTECH/data.**
- A: cheques (both past and post-dated), purchase invoices, sales.
- C: supplier terms (P-42).
- B/C: receivables (P-41).
- Salaries and fixed expenses: owner input (C), since the expense mirror is stale.

**Measurement.**
- Forecast vs actual weekly cash (accuracy).
- Number of weeks with an unplanned shortfall.

**Effort.** Medium. The view itself is small; it depends on P-41 and P-42 for completeness.

**Recurring cost.** Finance enters fixed outflows monthly.

**Adoption burden.** Low for the owner and finance.

**Risks.** A false sense of precision. Show it as ranges and label every input's source.

**Smallest version.** Committed cheques + sales run-rate + payables by age, with no terms yet.

**Confidence.** High on data for the outflow side.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Who owns it?~~ Answered: all finance users and all admins, including the owner.

**Revision after owner input**
- Contract inflows use **measured settlement behaviour per contract**: end-of-next-month pattern, ≈42–44 days for the
  top two. This replaces a generic assumption.
- Supplier outflows use terms **per supplier × item category** (local / imported / non-discounted), from P-42.
- Adds a **"what early payment would earn"** line: supplier early-pay discounts or bonus foregone because of the cash
  constraint, once P-42 captures them. This makes the cost of the cash shortage visible.

---

### P-41 · Contract receivables tracker (who owes us, since when, what was deducted)
**Module(s):** finance (reuse the A/P mirror pattern), insurance (claim lifecycle), customers (contract accounts) ·
**Type:** extend

**Current situation.**
- About 46% of sales are on contract credit, collected in 45–75 days, which ties up ≈5.6–9.4M.
- Finance tracks collection outside this system.
- The insurance module already models claim submission, expected payment date, payments and per-line deductions, but
  claims stay in "draft".
- The SOFTECH cheque tables used for the A/P mirror also carry receipts. That they hold customer receipts for
  contracts is **unverified** (class B).

**Problem.**
- Collection delays and insurer deductions are invisible inside the system that prepares the claims.
- Deductions (rejected lines) are not fed back to branches, so the same dispensing or documentation errors repeat.

**Proposed behaviour.**
1. **Mirror customer-side receipts.** Use the same SOFTECH cheque tables, filtered to contract parties, with the
   existing A/P mirror and matching engine (Rule 6, no new engine).
2. **Per contract:**
   - billed (claims submitted);
   - received;
   - open by age;
   - **expected date = submission + agreed days**;
   - overdue flag.
3. **Use the existing claim statuses.** Marking a claim "submitted" sets its due date; a matched receipt marks it
   paid or partially paid.
4. **Deductions by reason and branch.** Example: "missing doctor stamp — branch 150 — EGP 4,300 this quarter". This
   becomes a short training note to that branch.

**Example (illustrative).** Contract 4227 (the largest, ≈2.67M per 90 days) has 2 claims open at 68 and 82 days,
against a 60-day agreement. Finance gets a list on Sunday morning. Last quarter's deductions on that contract were
1.8%, mostly expired-prescription reasons.

**Expected benefit.**
- Cash: each day of collection time on ≈125k EGP per day of contract sales is ≈125k of working capital. Even a few
  days' improvement is material. This is a cash-timing benefit, not profit.
- Margin: fewer deductions.

**Evidence.** Measured claim statuses and contract sales; owner's 45–75 days.

**SOFTECH/data.**
- B: customer receipts in the cheque tables. Verify read-only first.
- C: agreed payment days per contract (finance input).
- A: claims and deductions (insurance module).

**Measurement.**
- Collection days per contract: baseline 45–75 (owner).
- Overdue value.
- Deduction % of billed per contract.

**Effort.** Medium.

**Recurring cost.** None material.

**Adoption burden.** Medium. Finance and insurance staff must mark claims submitted and record agreed days; receipts
then match automatically.

**Risks.** Receipts that can't be matched to claims (lump-sum payments). Show them as "on account".

**Smallest version.** A read-only receipts probe + an age report for the top 4 contracts (62% of contract sales).

**Confidence.** Medium (data source to verify).

**Recommendation.** **Pilot.**

**Decision required.** ~~Where tracked? May we probe?~~ Answered: SOFTECH + Excel; probe approved and done.

**Revision after owner input and the probe**
- Data class upgraded to **A** (pending a wider read-only check across all 38 contracts).
- **Scope:**
  - Turn on the **customer side of the existing A/P–A/R sync and engine**: the same queries with
    `party_type='customer'` (no new engine, Rule 6).
  - Add **agreed payment days per contract**, a one-off finance entry.
  - Per contract: open balance by age, measured collection days vs agreed, and an overdue list.
- **Insurance claim embedding stays later** (owner). The tracker works from SOFTECH invoices and receipts without
  needing claim statuses.

**Baseline:** 4227 ≈44 days, 4288 ≈42 days (max 60); other contracts are measured on enablement.

**Recommendation:** **approve for specification**. The pilot is no longer needed for data feasibility.

---

### P-42 · Supplier credit terms and pay-on-due
**Module(s):** finance (A/P mirror, recon), procurement (supplier profiles), purchasing (P-34) · **Type:** extend

**Current situation.**
- Supplier invoices carry no due date (0 of 6,919 in 90 days).
- Payments run at ≈5.4M per month.
- 10.6M of "open" invoices are more than a year old, mostly service-vendor and patient-repurchase accounts. This looks
  like reconciliation residue.

**Problem.**
- Without terms, the business can't tell whether it pays early (losing cash it needs), late (risking supply and
  bonus), or on time.
- The old residue distorts every payables figure.

**Proposed behaviour.**
1. Purchasing or finance records **credit days per real supplier** (one field; start with the top 10 by value).
2. Every open invoice gets a due date. A weekly payment calendar shows due and overdue items. **Paying before the due
   date** is flagged unless an early-payment discount or bonus justifies it.
3. A **residue list** of open items more than 1 year old, by account type, for finance to reconcile or close in
   SOFTECH natively. The A/P reconciliation engine (97.8% shadow match) already proposes matches.

**Example (illustrative).** A distributor's terms are 60 days. The calendar shows 0.9M due next week and 0.4M paid
last month 25 days early. Finance moves future payments to the due date.

**Expected benefit.**
- Working capital from paying on the due date instead of early. Size unknown until terms are entered; it is a timing
  benefit.
- A clean payables figure.

**Evidence.** Measurements above; doc 23 engine.

**SOFTECH/data.**
- A: invoices and payments.
- C: terms per supplier.

**Measurement.**
- Average days paid vs terms, per supplier.
- Value paid early.
- Residue value (target: down).

**Effort.** Small–medium.

**Adoption burden.** Low: a one-off terms entry.

**Risks.** Damaging supplier relationships by stretching to the limit. This is advisory; finance decides.

**Smallest version.** Terms for the top 10 suppliers + a due/paid-early report.

**Confidence.** High.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Fixed credit days?~~ Answered: yes, varying **by item category per supplier** (local /
imported / non-discounted). Paid on time. Early-payment discounts exist but are unaffordable now.

**Revision after owner input**
- Terms are recorded per **supplier × item category**. Each invoice's due date is computed per category share,
  matching how cheques are actually written: one cheque per category total.
- "Paid early" flagging is dropped, since suppliers are paid on time. It is replaced by:
  - (a) a **payment calendar by supplier × category** feeding P-40;
  - (b) an **early-payment opportunity list**: the discount or bonus available if paid early, so that when cash
    allows, the highest-return early payments are chosen first.
- The residue clean-up list stays.

---

### P-43 · Finance hub hygiene: no stale numbers on screen
**Module(s):** finance hub, cheques, payments, analytics, insights, forecasting · **Type:** simplify

**Current situation.**
- Journal and treasury are stale since May: a manual sync, with only the P&L snapshot scheduled.
- The cheque planner is unused (folded into P-40).
- The external-payments module requires double entry, with 0 rows.
- Item forecasts have no consumer.
- Insights findings have no owner.
- Analytics "capital tied" is valued at selling price (folded into P-35).

**Problem.** Stale or unused screens show wrong numbers, and management may act on them.

**Proposed behaviour.**
- Schedule the finance sync (journal, treasury, expenses) nightly, or **hide** those tabs with a "not current" badge
  until it runs.
- Every finance and analytics screen shows its data date (reusing the existing freshness bar).
- Retire or hide the external-payments module unless finance plans to use it.
- Insights stays a narrative layer, with each finding linking to its owning screen.

**Expected benefit.** Trust in the numbers; less clutter.

**Effort.** Small.

**Adoption burden.** None.

**Smallest version.** Freshness badges + schedule the finance sync.

**Confidence.** High.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Which pages are used?~~ Answered: gross profit and expenses (branches) yes; cash flow no;
HQ expenses in Excel.

**Revision after owner input**
- **Keep and freshen** the gross-profit and expense pages: schedule their syncs and show a data date on each.
- **Cash flow** is replaced by P-40.
- **A full accounting module** (to retire Excel, including HQ expenses) is recorded as a **future strategic item**,
  not in scope now. The existing chart of accounts, balance sheet and income statement mirror are its base.
- **Insurance claim submission and payment embedding** is recorded as a future item (owner).

---

## DECISION BATCH 6 — customer service & retention (2026-10-30)

### Measured picture (office PG; read-only)

**Regular repeat buyers** (identified customers, the same item bought ≥3 times in 12 months, about every 20–45
days):

| Channel | Regular customers | Monthly spend | **Lapsed** (overdue > 1.5× their own interval, last seen ≤ 180d ago) | Lapsed monthly spend |
|---|---|---|---|---|
| Cash | 1,249 | 681k | **665** | **233k** |
| Delivery | 441 | 346k | **249** | **90k** |
| Regular customer (عميل دائم) | 118 | 63k | 64 | 20k |
| Contracts | 705 | 1.38M | 407 | 505k (likely membership changes: an employee left or a contract ended) |

- **The catalog chronic list is narrow:** it matches only 80 of the 4,539 cash customer-item pairs. Behaviour finds
  far more regular buyers than the label.
- **Lapse ≠ lost to us.** A lapsed customer may have changed therapy, bought elsewhere, been sold under a walk-in
  account, or died. Revenue shown at sale price; gross margin is ≈25% on cash.

**Follow-up module (refills)**
- 76,840 tasks, **all created in May 2026**.
- Generation and auto-close are **unscheduled**, and auto-close reads the **stale `erp` mirror** (data ends
  2026-04-30). WhatsApp refill sending is OFF.
- The interaction/contraindication base is not used here.

**Intake**
- Reservations: 54 total, none since July. Demand records: 3. Call-centre calls cannot convert to a demand record.
- The omni inbox has no capture action.

**Delivery**
- Delivery-order status history in the app is **100% imported by the 5-minute SOFTECH CRM sync**. No rider or
  dispatcher uses the app workflow.
- Last 90 days:
  - 1,125 mirrored CRM orders, against ≈3,550 delivery-channel invoices. Most delivery sales never pass through the
    CRM order.
  - **258 orders stuck in "ready"/"preparing"**.
  - Median order → delivered ≈20–25 min. P90 = 106 min (branch) / 182 min (call centre). Timestamps are at sync
    resolution.
- **Customer satisfaction:** 435 survey rows created, **0 responses**; sending is gated.
- **SLA fields are never set.**

**Call centre**
- **636 of 647 call logs have purpose "general"**, so reasons are not recorded.
- Calls are mostly auto-created from the PBX.

**Previously deferred items that this batch depends on (re-surfaced as dependencies, not re-proposed)**
- **P-05 consent:** any outbound refill or restock message needs it.
- **P-03 outcome matching:** whether a refill or recovery actually sold. It must use `PurchaseHistory`, not the stale
  `erp` mirror.

### Owner input (2026-10-30) — supersedes assumptions in the Batch 6 cards

**Refills**
- **The call centre owns refill calls.** It **already does refill reminders today by phone and WhatsApp**, selecting
  customers manually.
- Pharmacist review is not needed in general, **only for specific categories** (e.g. diabetic patients).

**Reservations and "not available" requests**
- **Reservations stopped because the system has not gone live yet.** It is close to go-live, so this is not a
  rejection.
- **When an item isn't in stock today:**
  - it is noted on paper or WhatsApp;
  - an alternative is offered sometimes, when the item is in market shortage;
  - staff avoid letting the customer leave, unless the item is heavily short or discontinued.

**Delivery**
- **Free delivery:** delivery invoices without a fee line are mostly **complementary extra orders for the same
  client**. Free delivery for a few PIC customers is uncommon.
- **Measured check:** only **139 of 1,238** fee-less invoices have a same-day fee-carrying invoice for the same
  customer. **1,099 remain unexplained**: 992k EGP of sales, median 296 EGP. They may be adjacent-day companions.
  **The money is small:** at most ≈14k EGP of fees per 90 days.
- **Rider pay:** riders are paid **by the cashier at the end of each shift from branch cash**. The cashier **records
  the total delivery service fees per ride**.
- Riders have smartphones. Riders updating order status themselves is **"maybe in the near future"**.

**Call centre**
- Agents **enter orders directly in SOFTECH CRM during the call.**
- **Most calls are about orders and availability.**

**Consent (P-05), noted once**
- The call centre **already messages customers by WhatsApp** for refills. So the PDPL consent question applies to
  current practice, not just to the future system.
- P-05 stays deferred per the owner. It is recorded here as an existing exposure.

### P-46 · Refill-due worklist for regular customers (call centre / branch), with "did they buy" measured
**Module(s):** followups (refocus), customers, callcenter, reservations · **Type:** optimize existing

**Current situation.**
- The follow-up module exists, but its tasks are stale (May), generation is unscheduled, and the auto-close data
  source is dead.
- Regular-customer behaviour is measured above: 665 cash and 249 delivery customers are currently overdue, with
  ≈323k/month of their usual spend.

**Problem.**
- Regular customers drift away silently.
- Evidence shows a modest but real effect from a timely call. Walgreens RCT (04 §3): refill within 14 days
  **+6.1 points**, but adherence only +1 point. A Dutch RCT of reminders alone was null.

**Proposed behaviour.**
1. A nightly job builds a **"due this week / overdue" list** from `PurchaseHistory`: behavioural regulars, not the
   narrow chronic label. Each line shows the customer, item, usual interval, last purchase and branch.
2. The call centre or branch works the list. **One tap** records: will come / reserve for pickup / deliver / changed
   therapy (stop) / bought elsewhere / do not contact.
   - "Reserve" or "deliver" creates the existing reservation or delivery order. **Stock is pre-picked.**
3. Next day, **auto-match against sales.** If the customer bought the item, it is "refilled". This is the P-03 method
   on `PurchaseHistory`.
4. **Clinical safety (Rule 4):** the call is a service reminder, never a push. Scripted wording: "is your treatment
   still the same?". "Changed therapy" closes the line for good. A pharmacist reviews the first lists.

**Example (illustrative).** A customer has bought a diabetes medicine every ~30 days, last seen 52 days ago. The agent
calls: "Is your treatment still the same, and would you like it reserved or delivered?" They choose delivery, and the
order is created. The sale is matched the next day.

**Expected benefit.**
- Retained gross margin from regular customers.
- The upper bound is the ≈323k/month lapsed spend in cash and delivery (≈80k gross margin per month). The realised
  share is expected to be small (the RCT effect was single-digit points) and is **measured, not assumed**.
- Better service for chronic patients.

**Evidence.** Measurements above; Walgreens / Kooy RCTs; followups module state.

**SOFTECH/data.**
- A: `PurchaseHistory` for identified customers.
- **B: phone number quality** on the customer record.
- **C: consent (P-05)** for WhatsApp. Phone calls to existing customers about their own refill need a legal check
  under PDPL (service vs marketing).

**Measurement.**
- Refill-on-time rate (bought within 1.5× their interval) for called vs not-called regulars.
- Pilot: 2 branches' customers called, 2 branches as control, 8 weeks.

**Effort.** Medium. This reuses followups, reservations, delivery orders and the call-centre screens.

**Recurring cost.** Agent time: about 30–60 calls a day for a pilot.

**Adoption burden.** Medium for the call centre.

**Risks.**
- Annoying customers: cap at one call per customer per month, plus a do-not-contact flag.
- Privacy and consent: legal check first.

**Smallest version.** A read-only due/overdue list for one branch + manual calls + automatic "did they buy" matching.

**Confidence.** Medium.

**Recommendation.** **Pilot.**

**Decision required.** ~~Who works the list?~~ Answered: the call centre, which already does refill reminders by
hand.

**Revision after owner input**
- The list **replaces the call centre's manual selection** of who to remind, so it is not a new task.
- **Pharmacist review** is on only for flagged categories (e.g. diabetes), configurable.
- The outcome taps and the "did they buy" matching are what is new: they make the existing practice **measurable**
  (refill-on-time rate, called vs not called).
- The pilot runs on the call centre's current volume.

**Recommendation:** **approve for specification** (the pilot is folded into a measured rollout).

---

### P-47 · One quick capture for "not available now" requests
**Module(s):** demand (canonical intake), reservations (commitment stage), callcenter, omni, pos_orders ·
**Type:** simplify / merge

**Current situation.**
- Two parallel intake models (DUP-001), both barely used: 54 reservations, 3 demand records.
- A shortage list and the WhatsApp branch-request path also exist (Batch 3).
- Call-centre calls can't become a demand record; the omni inbox can't capture anything.

**Problem.**
- When an item isn't available, the customer request is lost or lives in WhatsApp.
- Lost demand is invisible to buying (P-30 / P-34): it is especially relevant for slow items now on order-on-demand
  (P-34).

**Proposed behaviour.**
- **One capture form**, reachable from the POS search "not in stock" result, the call-centre screen and the omni
  inbox. Fields: phone, item, quantity, branch, "wants: reserve / deliver / just notify".
- It writes one demand record. If the customer commits, it becomes a reservation.
- **When stock arrives**, the branch is notified (an internal alert, not a customer message until P-05).
- The outcome is matched from sales.
- Branch WhatsApp requests stay as they are (Batch 3).

**Expected benefit.**
- Captured demand feeds buying.
- Recovered sales are measured.
- Fewer duplicate screens.

**Evidence.** Adoption counts; DUP-001; code refs (02 §3.1).

**SOFTECH/data.** A.

**Measurement.**
- Captured requests per week.
- % fulfilled within N days (matched).
- Captured lost value vs the engine's statistical estimate.

**Effort.** Medium.

**Adoption burden.** Medium. Staff must capture, and the form must take under 10 seconds.

**Risks.** Another form nobody uses. Mitigation: put it exactly where the "not in stock" moment happens (POS search,
call screen).

**Smallest version.** Capture from POS search + call screen, writing to demand, with internal restock alerts.

**Confidence.** Medium–low. Adoption is the open question.

**Recommendation.** **Research further:** ask why reservations stopped in July.

**Decision required.** ~~Why stopped? How handled today?~~ Answered: not live yet; today it's paper/WhatsApp,
sometimes an alternative.

**Revision after owner input**
- This is not an adoption failure, so **recommendation: approve for specification**.
- The single capture form **replaces the paper/WhatsApp note at the counter**.
- When the item is in **market shortage**, the form shows the approved alternatives (composition index,
  pharmacist-approved only, Rule 5) so staff offer them consistently.
- It ties in with call-centre availability calls (P-49) and order-on-demand for slow items (P-34).

---

### P-48 · Delivery: record what actually happens (rider pay, fee, status) — not a parallel dispatch system
**Module(s):** delivery, pos_orders, finance (branch expenses) · **Type:** simplify + extend

**Current situation.**
- Delivery orders and statuses come only from the SOFTECH CRM sync. Riders and dispatchers don't use the app.
- 258 orders are stuck in open statuses. CSAT: 0 responses. SLA metrics are empty.
- Owner (Batch 4): the rider gets 10 EGP per fee unit (×distance), motorcycle riders a 50 EGP/day minimum, plus
  **cash extras paid by the branch, not recorded**.
- 1,238 delivery invoices in 90 days had no fee line.

**Problem.**
- Delivery cost and accountability live in cash and memory.
- The app's dispatch features are unused, while the information that matters (who was paid what, for which order)
  is uncaptured.

**Proposed behaviour.**
1. **Rider payout ledger:**
   - Per day per rider: orders delivered (from sales and CRM), fee units × 10, distance multipliers, the daily
     minimum top-up, and **branch-paid extras with a reason** (one line, entered by the branch).
   - It reconciles to branch cash and becomes a branch expense in the existing expense pages.
2. **Auto-close** stale delivery statuses once the SOFTECH sale is finalized.
3. **Flag delivery invoices without a «D.L.V.» line**, as intentional (free-delivery rule) or missed.
4. Retire or hide unused dispatch screens until riders are equipped.

**Example (illustrative).** The branch 160 day sheet: rider A delivered 14 orders (17 fee units) = 170 EGP + 40
extra (transfer to branch 140, reason entered) = 210 EGP. The cash drawer matches.

**Expected benefit.**
- Cash accountability.
- True delivery contribution (feeds P-35).
- Recovered missed fees. Size unknown: 1,238 invoices × 13 EGP ≈ 16k per 90 days if all were missed — an upper
  bound.

**SOFTECH/data.**
- A: sales with item 2, CRM orders.
- C: rider identity per order and branch-paid extras.

**Measurement.**
- Unrecorded rider cash, which should go to 0.
- Delivery contribution per order.
- Missed-fee count.

**Effort.** Small–medium.

**Adoption burden.** Low–medium: a branch end-of-day entry.

**Risks.** Riders' identities per order may not be in SOFTECH; capture at the branch.

**Smallest version.** The missed-fee flag + the branch extras entry + stale-status auto-close.

**Confidence.** Medium.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Free delivery? Daily entry?~~ Answered.

**Revision after owner input**
- **Rider payout ledger at ride level.** The cashier already records the total delivery service fees per ride at
  shift end, so the ledger captures exactly that: ride, rider, orders covered, amount paid, and extras with a reason.
  It becomes a branch expense; the cash drawer reconciles.
- **Missed-fee flag is demoted:** most fee-less invoices are companion orders, and the money is small (≤ ≈14k EGP
  per 90 days). It becomes an informational column only, not a workflow.
- **The rider app** (`/rider`, already built) is recorded as a **later option**, once riders update status
  themselves.
- **Stale-status auto-close stays.**

**Recommendation:** approve for specification (ledger + auto-close).

---

### P-49 · Call centre: one-tap call reason and outcome
**Module(s):** callcenter, pbx, omni · **Type:** optimize

**Current situation.**
- Calls are logged automatically from the PBX (626 sessions in 30 days), but **98% have purpose "general"**.
- Calls can convert to a reservation or transfer, not to a demand record or delivery order.

**Problem.** There is no answer to "why do customers call, and what happened?": availability questions, orders,
complaints, prices. So the call-centre load and lost orders can't be managed.

**Proposed behaviour.**
- At hang-up, a **one-tap reason**: order / availability / price / refill / complaint / other.
- Plus an **outcome**: order created / request captured (P-47) / resolved / callback.
- The "order created" outcome links the CRM order (the delivery mirror) automatically by phone and time.
- A weekly reason mix and conversion report.

**Expected benefit.**
- Management visibility.
- Finds availability-driven lost orders (feeds P-30 / P-47).
- Staff time stays low (one tap).

**SOFTECH/data.** A (PBX + CRM orders); C (reason tap).

**Measurement.**
- % of calls with a reason (target ≥90%).
- Call → order conversion by reason.

**Effort.** Small.

**Adoption burden.** Low–medium.

**Smallest version.** The reason tap + a weekly mix report.

**Confidence.** High.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Orders in SOFTECH CRM?~~ Answered: yes, during the call; most calls are orders and
availability.

**Revision after owner input**
- **"Order" outcome links automatically:** the CRM order created during the call is matched by phone and time, so
  "order" needs no tap.
- **Availability calls** that end without an order offer the P-47 capture in one tap. This is the main source of
  phone-side lost demand.
- The reason list is cut to: order / availability / refill / other.

---

## DECISION BATCH 7 — staff capability & clinical quality (2026-10-30)

### Measured picture (office PG; read-only)

**Gamification point sources (all time).** About 82% of points come from sales:

| Source | Points |
|---|---|
| Invoice count | 52.4k |
| Gross profit (cash ×1.5) | 27.6k |
| Sales value | 18.8k |
| Clean day | 11.5k |
| Transfers sent | 5.3k |

Safety, training, counselling and QA: **0 rules exist**.

**Training.** The in-app help has 29 module quizzes, all about **using the system**; there are 0 attempts (pre-launch).
**No pharmacy-knowledge content** exists: no counselling, red flags, antibiotic stewardship or competency tracking.

**Incentives.** Two programmes are flagged **active**: **"Sildenafil"** and **"Male Items"**, created May 2026, with
75 transactions in May only.
- Sildenafil is a **prescription medicine with a serious nitrate interaction**.
- Paying staff per unit sold conflicts with Rule 4 (safety beats sales) and with the medicine-promotion controls
  (04 §1).
- No incentive rule can exclude Rx or sensitive classes (`incentives/models.py`).

**Drug-interaction base** (`chronic.DrugInteraction`)
- 40 rows: 26 cite **BNF**, 8 Drugs.com, 5 FDA, 1 guidelines. Plus 35 contraindications.
- **No reviewer and no review date.**
- Used only by the recommendation engine. **Not used at the POS.**
- **The BNF can't be reused in third-party systems without a licence** (04 §4). The provenance of those 26 rows is a
  licensing risk.

**AI catalog enrichment.** It auto-approves suggestions at ≥0.90 confidence, **including clinical fields**
(indication 78, Rx/OTC 11 approved).

**QA module.** Mobile only. One template with a fridge yes/no item. **0 inspections.** No temperature log, no follow-up
on failed items. Recurring **task schedules never run** (`tasks/scheduler.py` has no caller).

**Local evidence.** Abdelaziz et al. 2019 (simulated patients, Minia): **98.3% dispensed amoxicillin for viral
respiratory scenarios**; 63% without relevant questions (04 §4).

**Previously deferred items in scope here.** The owner chose this clinical batch, so the clinical parts of deferred
**P-01** are raised once for re-decision:
- (a) basket suggestions ignore customer allergies;
- (c) AI auto-approval of clinical fields.

They are not re-proposed as new cards; they sit inside P-52.

### Owner input (2026-10-30) — supersedes assumptions in the Batch 7 cards

**Incentives and gamification**
- **"Sildenafil" and "Male Items" were test programmes** created to test the module, so they are not live policy.
- **Supplier-sponsored incentives are frequent.**
- Incentives on prescription medicines happen **"not frequently"** but are **not to be prohibited**.
- **Gamification:** lowering sales below half of all points would be an **"extreme downgrade"**. But points **must be
  added for training, quality checks and refills.**

**Training and content**
- Pharmacy-knowledge training is done today **by the chain owners**; nobody is dedicated to it.
- **Content owners:** the chain owners now; HR or a dedicated trainer later.
- **Mystery-shopper visits: yes.**

**Drug information**
- References used today: **Drug Eye (Egyptian platform), Medscape, Drugs.com and internet search.**

**Deferred P-01 items** (lettering per the original P-01 card)
- **P-01(c) AI enrichment auto-approval stays ON.** "We need mass data collection now; human review later."
- **P-01(a) customer-allergy filter is moot.** **Customer allergies are not documented per patient in Egypt.**

**Cold chain and inspections**
- No paper fridge log today; a **thermometer is present**.
- **EDA inspectors always ask for it.**
- Branch quality inspections are done **by EDA pharmacists about monthly, at random times**. There is no internal QA
  routine.

### P-50 · Reward safe, competent work — not only sales
**Module(s):** gamification, incentives · **Type:** optimize (rebalance)

**Current situation.**
- Gamification is about 82% sales-driven and gives profit-weighted points.
- Incentives can target any item, and two active programmes target sildenafil and "male items".

**Problem.** Staff behaviour follows what is rewarded. Rewarding prescription-medicine sales and profit, with nothing
for safety or knowledge, works against pharmacy safety and Egyptian promotion controls.

**Proposed behaviour.**
1. **Incentives:**
   - Rules cannot target Rx-only, antibiotic or psychotropic classes. This reuses the class list that is already
     required for promotions (P-38 gate).
   - **Review the two active programmes now** (owner decision).
   - Supplier-sponsored programmes are logged for compliance review.
2. **Gamification:**
   - New rules: quiz passed, QA inspection score, identified-sale rate (P-37), refill outcome recorded (P-46).
   - The **gross-profit (cash ×1.5) rule is capped lower or removed**.
   - **Sales stay part of the score but no longer dominate it.** Target: under 50% of points.

**Expected benefit.** Clinical-risk reduction; aligns staff energy with the approved capability work. No sales benefit
is claimed.

**Evidence.** Measured point mix; active programme names; Rule 4; 04 §1 (promotion controls).

**SOFTECH/data.** A.

**Measurement.**
- Share of points from non-sales behaviours.
- Number of incentive rules on excluded classes (target 0).

**Effort.** Small (rule configuration + one exclusion check).

**Adoption burden.** Low; communicate the change to staff as a positive.

**Risks.** Staff perceive a loss of earning. Phase the change in, and keep the caps.

**Smallest version.** Exclude Rx classes from incentives + review the two programmes + add a quiz-pass rule.

**Confidence.** High.

**Recommendation.** **Approve for specification**; decide the two programmes now.

**Decision required.** ~~The two programmes?~~ Answered: test programmes.

**Revision after owner input**
- **Deactivate the two test programmes.**
- **Rx incentives are allowed, with a guard, not a block** (owner). An incentive rule that targets a prescription item
  requires an explicit **"Rx — approved by" field** (owner or admin) plus a reason, and is audited (Rule 8).
- Items flagged stop-sale or return-only by catalog safety are always excluded.
- **Supplier-sponsored** rules show the sponsor and are listed in a sponsor report.
- **Gamification:** **add** rules for quiz passed, mystery-shopper/QA score, fridge log on time (P-53) and refill
  outcome recorded (P-46). The sales rules stay. The "below 50%" target is dropped (owner: too extreme). The non-sales
  share is tracked as a KPI only.

**Recommendation:** approve for specification.

---

### P-51 · Pharmacy competency, lite: short cases, counselling checklists, measured by mystery shopper
**Module(s):** help (reuse onboarding/quiz engine, trainer editing, revisions), gamification, qa · **Type:** extend

**Current situation.**
- The help module already has role paths, quizzes with a pass mark, trainer editing with history, and a team-progress
  view.
- All content is about the software.

**Problem.** Egyptian evidence shows a large gap between knowledge and practice at the counter: antibiotics for viral
symptoms, few questions asked. There is no structured way to build or check staff pharmacy knowledge.

**Proposed behaviour.**
1. **A short case library**, about 12 cases to start, pharmacist-authored, in Arabic, 3–5 minutes each. Topics:
   - sore throat / cold (antibiotic stewardship);
   - child fever;
   - diarrhoea;
   - pregnancy and OTC;
   - sildenafil and nitrates;
   - diabetes refill questions;
   - fridge items;
   - red flags → refer to the pharmacist or a doctor.

   Each case ends in a 3-question check, using the existing quiz engine.
2. **Counselling checklists** of 3–4 questions per common complaint, shown in the help panel. **Educational, not
   patient-specific decision support.**
3. **Competency map:** 10–15 statements adapted from the FIP Global Competency Framework (open access), tracked per
   staff member.
4. **Outcome measure:** a quarterly **internal mystery-shopper visit** per branch using 2–3 scenarios, scored with the
   checklist. The QA module records it.

**Example (illustrative).** A new salesperson completes "Sore throat" (4 minutes) and passes the check. In the next
mystery visit, they ask about fever and duration and refer appropriately, so the branch score rises.

**Expected benefit.** Safer, more consistent counselling; staff development; trust. Measured by mystery-shopper
scores, **not by sales**.

**Evidence.** Abdelaziz 2019 (Egypt); simulated-patient method reviews; FIP framework (04 §4).

**Content and governance.**
- **A named pharmacist owns the content.** Each case carries a source and a **review date** (annual).
- No unlicensed BNF text; written in our own words, citing open sources (EDA, WHO, FDA labels).
- Privacy: none (no patient data).

**Measurement.**
- Cases completed per staff member.
- Pass rate.
- Mystery-shopper score per branch: baseline from the first round.

**Effort.** Medium, mostly content. The engine exists.

**Recurring cost.** Pharmacist time: about 2–4 hours per case to write, plus an annual review. A mystery shopper costs
staff time.

**Adoption burden.** Medium: 10 minutes a week per staff member.

**Risks.** Content error. Mitigation: pharmacist review, sources, review dates, and a feedback button (exists).

**Smallest version.** 4 cases + 1 mystery-shopper round at 2 branches.

**Confidence.** Medium. Evidence for any single training method is weak, which is why the outcome is measured directly.

**Recommendation.** **Pilot.**

**Decision required.** ~~Content owner?~~ Answered: the chain owners now; HR or a dedicated trainer later.
Mystery shopper: yes.

**Revision after owner input**
- **The case format is chosen to fit owner time:** short cases (≤1 page each), written from a template. The owners
  already do this training informally; the system just captures it so it can be reused.
- When HR or a trainer takes over, the existing trainer-edit permission (`help`/`edit`) and revision history hand
  over cleanly.
- References cite the sources pharmacists already use (Drug Eye, Medscape, Drugs.com) **as links, not copied text**.
- **Mystery-shopper scores** are recorded in the QA module and count in gamification (P-50).

**Recommendation:** pilot (4 cases + 1 mystery-shopper round, 2 branches).

---

### P-52 · Governed drug information (and the two deferred safety fixes)
**Module(s):** chronic (interaction base), enrichment, recommendations, catalog safety · **Type:** optimize + govern

**Current situation.**
- The interaction base has no reviewer or review date, and 26 of its 40 rows cite BNF (a licensing risk).
- AI enrichment auto-approves clinical fields.
- Basket suggestions skip the allergy filter (deferred P-01 a, c).

**Problem.** Clinical information inside the system must be correct, owned, current and licensed before staff rely on
it. Rules 4, 5 and 10 apply.

**Proposed behaviour.**
1. The interaction and contraindication rows get **reviewer, review date and source licence** fields. A pharmacist
   re-sources the 26 BNF rows from licensed or open sources.
2. **Decide the source** (owner):
   - **(a)** link-out only, to a licensed reference the pharmacists already use; or
   - **(b)** one HQ licence of a professional drug database, for the content owner (04 §4: institutional pricing by
     quote).

   No per-counter licences.
3. AI enrichment **never auto-approves** clinical fields. Already-approved values (≈89) are marked "needs pharmacist
   review". *(Deferred P-01 c.)*
4. Basket suggestions apply the existing customer allergy/interaction filter. *(Deferred P-01 a.)*
5. **POS interaction screening stays OFF** until items 1–2 are done. It is then educational warnings only, never
   automatic substitution (Rule 5).

**Expected benefit.** Clinical safety and legal (licensing) safety.

**SOFTECH/data.**
- B: customer allergies are sparse (staff-entered).
- C: governance fields.

**Measurement.**
- Rows with current review (target 100%).
- Unreviewed clinical enrichment values (target 0).

**Effort.** Small for (3)(4); medium for (1).

**Recurring cost.** Annual pharmacist review; an optional licence.

**Adoption burden.** None for counter staff.

**Smallest version.** (3) + (4) + governance fields.

**Confidence.** High.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Revisit P-01 a/c? Source?~~ Answered.

**Revision after owner input**
- **(3) Dropped as a block.** AI auto-approval stays ON for mass collection (owner). The minimal safeguard proposed
  instead:
  - AI-sourced clinical values carry an **"AI — not reviewed" label** wherever they are shown;
  - they are **never used by any safety or decision logic** (safety flags, interaction screening, substitution)
    until a human approves them (Rule 10);
  - **owner to confirm** this safeguard.
- **(4) Dropped.** Customer allergies are not documented per patient, so there is nothing to filter on.
- **Source decision:** **link-out** to the references pharmacists already use (Drug Eye, Medscape, Drugs.com). No
  licensed database for now.
- The 26 BNF-cited interaction rows are re-worded and re-cited from these and open sources (FDA labels).
- Reviewer and review-date fields are added; the owners are the reviewers for now.

**Scope now:** governance fields + re-sourcing + the "AI — not reviewed" label. Small.

---

### P-53 · Cold-chain log and branch QA that leads to action
**Module(s):** qa, tasks (fix scheduler), notifications · **Type:** extend + fix

**Current situation.**
- QA is mobile-only, with 1 template and 0 inspections.
- The fridge check is a yes/no item with no reading.
- Recurring task schedules never fire.
- External guidance (04 §6): WHO good storage practice covers community pharmacies. EDA inspection templates require
  **recorded temperature readings** for warehouses; no EDA community-pharmacy fridge range was found.

**Problem.** Fridge items (insulin, vaccines, some biologics) are safety-critical and costly. Without a recorded
reading, an excursion is neither detected nor proven.

**Proposed behaviour.**
- A **twice-daily fridge reading** per branch fridge in the mobile QA screen: current, min and max reading, plus
  initials, in about 20 seconds.
- **Out of range** → an immediate alert to the branch pharmacist and QA manager, plus a checklist: move stock, check
  the thermometer, log the affected items.
- A missed reading → a reminder (requires the task-scheduler fix).
- A failed QA item auto-creates a task with an owner.
- A monthly branch QA score feeds gamification (P-50).
- Temperature range per item from the catalog fridge flag; 2–8 °C default, **confirmed by the pharmacist**.

**Expected benefit.**
- Avoided cold-chain losses.
- Inspection readiness.
- Safety.

**SOFTECH/data.** C (readings); A (fridge-flag items per branch).

**Measurement.**
- % of readings on time.
- Number of excursions and time to action.
- Value of fridge stock at affected branches.

**Effort.** Small.

**Recurring cost.** About 1 minute per branch per day. A digital logger is optional later.

**Adoption burden.** Low–medium (habit).

**Risks.** Pencil-whipping (readings entered without checking). Use random spot checks during QA visits.

**Smallest version.** The fridge log + out-of-range alert + scheduler fix.

**Confidence.** High.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Paper log?~~ Answered: no log, a thermometer only. **EDA inspectors always ask for it**,
and EDA inspects about monthly at random.

**Revision after owner input — reframed as "EDA inspection readiness":**
- The **fridge log is the evidence EDA asks for**. It is printable per branch per month.
- An **inspection-ready checklist** in the mobile QA screen mirrors what EDA inspectors check. The owners provide the
  item list from recent visits.
- Each **EDA visit is recorded** (date, inspector remarks, items flagged), and a flagged item becomes a task with an
  owner and a due date.
- Branch readiness score.

**Expected benefit:** passing random monthly inspections with evidence on hand, plus cold-chain safety.

**Recommendation:** approve for specification. High value, small effort.

---

## DECISION BATCH 8 — platform & cutover readiness (2026-10-30)

### Measured picture (office PG + office `.env`; read-only; no secret values read)

**Writer switches in the office `.env`.** **15 SOFTECH-writer switches are ON** while the code defaults are OFF:
- AP_RECONCILE_WRITER;
- POS_OFFERS_EXECUTION, POS_OFFERS_POSDISCP_WRITE and POS_OFFERS_PROMO_WRITE;
- CUSTOMER_BRANCH_COPY_WRITE and POINTS_REMOVAL_WRITE;
- ISR_WRITER, SALES_RATE_WRITER, COVERAGE_WRITER + COVERAGE_WRITE_MAXQTY + COVERAGE_AUTO_TOPUP;
- INVOICE_WRITER and INVOICE_SUPPLIER_ITEM_WRITE;
- SHORTAGE_SOFTECH_WRITE;
- COUPON_POS_GUARD and DEMAND_ENGINE_SCHEDULE.

**5 keys appear twice** in the file. Several docs and docstrings still describe these writers as "OFF".
`POS_WRITER_ENABLED` is absent, so it is OFF.

**Database.** 9.9 GB, with no retention on any growing table:

| Table | Size |
|---|---|
| ItemDemandMetrics (every engine run kept) | **2.5 GB** |
| Notification + NotificationLog | **1.53 GB** |
| TransferRecommendation | 0.2 GB |

That is ≈43% of the database. The VPS has 8 GB RAM and 300 GB disk.

**Notifications.** 399k in 30 days, 84% `transit_critical`: one per stuck transfer per day, to every branch user plus all
admins. 0% read since 2026-10-19. 776 transfers show ≥14 days in transit.

**Sync health (30 days)**
- 2,527 runs succeeded and **263 failed (9%)**:
  - 201 SOFTECH connection timeouts;
  - 18 metadata timeouts;
  - **20 Postgres schema mismatches**: not-null `customers_customer.merged_into_pic` and
    `customers_purchasehistory.softech_personcode`. The latter is what the uncommitted `customers/0029` migration
    addresses.
- **9 runs are stuck as "running".**
- Daily run counts swing from 20 to 354. That fits the scheduler PC sleeping (memory: the office scheduler stopped
  2026-10-28).

**Unapplied office migrations:** `sync` 0006, `help` 0007–0012.

**Unscheduled jobs:** task schedules, abuse detection, the shortage-flag retry, the FBT miner, follow-up generation,
and the `erp` sync (stale since April).

**Request timing.** **Not measured.** There is no request-duration logging. Live-SOFTECH-in-request paths are known
from code (02 §5).

**Previously deferred.** P-02 (alert reset) and P-04 (usage telemetry) are raised once more here **because the owner
chose this cutover batch** and production users will meet both from day 1. P-03's method now lives in P-46. P-04's
"stop TransferRecommendation" lives in P-32.

### Owner input + read-only SOFTECH check (2026-10-30) — supersedes assumptions in the Batch 8 cards

**Owner answers**
- **All 15 writers ON at go-live:** replenishment, purchasing, A/P reconciliation, offers, customers, engine schedule.
- **A period where the office AND the VPS both run is possible.** The owner wants to keep developing with Claude Code
  on production "freely like now".
- **Stuck-transfer digest goes to both** the branch manager and the HQ transfers coordinator.
- The owner believes **"something is not syncing correctly"** with in-transit transfers. Branches must record receipt
  in SOFTECH.
- Engine history: **last 10 runs + one per month** is enough.
- **Commit `customers/0029`** as part of the cutover.
- **Usage tracking: yes, and it will be used for both product decisions and individual staff evaluation.**

**The stuck-transfer check: the owner was right, it is a sync bug** (read-only, `SOFTECH_READ_ONLY=True`)
- **19 of 20** randomly sampled "in transit ≥14 days" transfers **already have their receipt (doc 25) in SOFTECH**,
  matching the sync's own strict rule. Receipts were recorded **0–6 days after issue**, weeks before the last sync on
  2026-10-28. The 20th went to branch 210 (May; node unreachable).
- **Root cause (logs):** **13,320 `_detect_receipt failed` warnings**, 18–28 Oct, between about 250 and 3,100 per day,
  **13,320 of them "JZ0C0: Connection is already closed"**.
- When the SOFTECH connection drops mid-run:
  - every remaining receipt check fails;
  - `_detect_receipt` swallows the error and returns "not received" (`sync_in_transit.py:587-646`);
  - the transfer stays "in transit";
  - `_fire_alerts` pings every branch user plus all admins, daily.
- **This explains most of the 776 "stuck" transfers and most of the 399k alerts.**

### P-54 · Cutover safety: one signed-off production switch table
**Module(s):** config/settings, deploy (`.env`, runbook §11), sync scheduler · **Type:** new (small)

**Current situation.** Production `.env` values will decide which SOFTECH writes run. The office file has 15 writers
ON, 5 duplicated keys, and docs that disagree. The single-writer rule (memory: never two schedulers or writers)
depends on getting this right.

**Problem.** A wrong flag on day 1 means unintended SOFTECH writes or a double post (Rule 3). A duplicated key means
nobody knows which value wins.

**Proposed behaviour.**
1. **A switch table.** Every SOFTECH write switch gets: intended production value, owner sign-off, date, and the module
   it protects.
2. A startup check **refuses to start** if `.env` contains a duplicated key, and **logs every ON writer** at boot.
3. **An admin page lists the live switches** (read-only).
4. **Cutover order:**
   1. the office scheduler is confirmed stopped;
   2. migrations are applied;
   3. the kill-switch is tested;
   4. RBAC is set to enforce (already planned);
   5. writers are enabled one by one, each with a read-back check.

**Expected benefit.** Prevents double posts and unintended writes.

**Effort.** Small.

**Adoption burden.** Owner sign-off once.

**Confidence.** High.

**Recommendation.** **Build at cutover** (approve for specification now).

**Decision required.** ~~Which writers ON?~~ Answered: **all ON at go-live** (owner decision, recorded).

**Revision after owner input — STOP-AND-ASK item (CLAUDE.md: anything that could double-post to SOFTECH)**
- **Office and VPS running at the same time with writers ON is a double-post risk.** Both schedulers would push the
  same ISRs, coverage values, invoices, A/P allocations, offer discounts and points removals. Project memory already
  records this rule: never two writer instances.
- **The safeguard that meets the owner's goal** (keep developing freely with Claude Code):
  - **Exactly one writer instance: the VPS.** All 15 writers are ON there, per the owner.
  - **The office instance becomes the development copy:**
    - `SOFTECH_READ_ONLY=True` (the existing global kill-switch blocks every SOFTECH write at the driver level);
    - writer jobs OFF.

    Claude Code keeps working on the office copy as today, reading live SOFTECH safely.
  - **A startup guard:**
    - an instance whose `.env` says `WRITER_INSTANCE=false` refuses to start any writer job, even if a writer flag
      is True;
    - a duplicated `.env` key blocks startup;
    - every ON writer is logged at boot.
- **Go-live order** (unchanged; the owner's "all ON" applies at its last step):
  1. stop the office scheduler's writers;
  2. migrate (incl. `customers/0029`, `sync` 0006, `help` 0007–0012);
  3. kill-switch test;
  4. RBAC enforce;
  5. switch the writers ON, **verifying each with one read-back on day 1**.

**Decision required:** confirm the office instance runs **read-only (no SOFTECH writes)** once the VPS is live.

---

### P-55 · Alerts people will actually read (P-02, re-raised for go-live)
**Module(s):** notifications, transits, sync · **Type:** simplify

**Current situation.** Measured above: 84% of alerts are per-transfer daily pings to every user and admin; nothing is
read.

**Problem.** On day 1 of production, every staff member's bell fills with transit pings. Real alerts (a demand SLA,
a reserved item back in stock, a sync failure) disappear, and staff learn to ignore the bell.

**Proposed behaviour.**
- Transit alerts become **one daily digest per receiving branch**, sent to the branch manager. A network digest goes
  to admins.
- A per-type routing table (who, instant vs digest).
- **Retention**: read notifications after 30 days, unread after 90.
- **Sync-failure alert** after 3 consecutive failures of the same lane, to admins only.

**Measurement.**
- Alerts per user per day (baseline ≈150 for the top recipients).
- % read within 24 hours (baseline 0%).

**Effort.** Small.

**Recommendation.** **Approve for specification** (before go-live).

**Decision required.** ~~Recipients?~~ Answered: both.

**Revision after owner input + root cause**
1. **Fix the sync bug first.** This is the main lever:
   - a closed connection is **reopened and the check retried**;
   - a failed check is recorded as **"unknown — will retry"**, never as "not received";
   - **no alert fires for a transfer whose check failed**;
   - the run reports how many checks failed.
2. **Re-check the existing "in transit" transfers once**, to clear the false ones.
3. Then the digest (branch manager + HQ coordinator), routing and retention as above.

**Expected effect:** most of the 776 "stuck" transfers and most transit alerts disappear because they were false.
The remaining genuinely stuck transfers become visible.

---

### P-56 · Database retention and sync health for the 8 GB server
**Module(s):** sync, purchasing, notifications, pbx, audit · **Type:** optimize

**Current situation.** Measured above: 43% of the DB is unbounded history, 9% of sync runs fail, there are stuck
"running" rows and schema-mismatch failures, and the full stock snapshot is upserted every 5 minutes.

**Proposed behaviour.**
1. **Retention:**
   - ItemDemandMetrics: keep the last N runs plus monthly snapshots.
   - Notifications and their log (P-55).
   - TransferRecommendation (P-32).
   - PBX events: keep 90 days.
   - AuditLog: keep everything that relates to money or SOFTECH writes (Rule 8); trim only noise events.
2. **Sync:**
   - Upsert only stock rows that changed.
   - Mark runs stuck "running" for over 1 hour as failed.
   - Block a manual sync from overlapping a scheduled lane.
   - Chain the 07:30–08:40 morning jobs instead of relying on clock offsets.
3. **Fix the schema mismatches** (commit and apply `customers/0029` and the `merged_into_pic` default) with a test.
4. **Measure before optimising:** add request-duration logging for the slowest API paths, and report the top 10 after
   2 weeks in production. Live-SOFTECH-in-request paths are fixed only where the measurements show it matters
   (POS is already covered by P-39).

**Expected benefit.** Stability on a smaller server, fewer failures, faster screens. **Measured, not assumed.**

**Measurement.**
- DB size.
- Sync failure rate (baseline 9%).
- p95 request time for the top 10 endpoints.

**Effort.** Medium.

**Recommendation.** **Approve for specification.**

**Decision required.** ~~Retention length?~~ Answered: last 10 runs + one per month. `customers/0029` goes on the
cutover list.

**Revision:** the same "reconnect, don't misreport" rule is applied to **every** SOFTECH sync lane. The
transit bug is one instance of a general pattern (02 §5: there is no retry anywhere).

---

### P-57 · Know what staff actually use from day 1 (P-04, re-raised for go-live)
**Module(s):** frontend router, a small events table, dashboard · **Type:** new (small)

**Current situation.**
- There is no screen-usage data, and `last_login` isn't updated by JWT logins.
- The system goes live soon. The owner confirmed the low counts so far reflect pre-launch.

**Problem.** Without usage data, the 26 approved proposals can't be judged after launch ("is the refill list used?
the near-expiry worklist?"), and unused screens can't be retired with evidence.

**Proposed behaviour.**
- One small event per screen visit: user, role, branch, route and time. No content.
- A monthly "who uses what" report per module and branch.
- After 60 days, zero-use screens are proposed for hiding.

**Effort.** Small.

**Adoption burden.** None.

**Privacy.** Staff activity data. Use it for product decisions, not individual performance. Say so to staff.

**Recommendation.** **Approve for specification** (live from go-live).

**Decision required.** ~~Product decisions only?~~ Answered: **both** product decisions **and individual staff
evaluation** (owner decision, recorded).

**Revision after owner input — privacy safeguards for using it in staff evaluation**
- **Tell staff** that screen usage is recorded and used in evaluation. A short notice in the app and in the HR policy:
  transparency for employee data under the PDPL (04 §1, to confirm with legal).
- **The individual view is restricted to admins and HR.** Branch managers see their branch's aggregate.
- **Retention:** 12 months.
- **Never evaluate a person on usage alone.** Screen visits measure activity, not quality. Pair them with outcome
  KPIs: identified-sale rate, refill outcomes, fridge log, QA scores.

---

## Later batches — candidate proposals (not yet carded)

**Quick improvements to existing functionality**

| ID | Proposal | Module | Evidence |
|---|---|---|---|
| P-06 | Debounce + batch POS discount-suggest; cache reference reads | pos_orders | `usePosOrder.js:401-430` |
| P-07 | Stock-audit "escalate" → task + one-click targeted count; recovery per rule | stock_audit, stockcount, tasks | 915 open findings |
| P-08 | Count variance valued at cost + post-snapshot movement netting | stockcount | `stockcount/engine.py` |
| P-09 | *(folded into P-48)* | — | — |
| P-10 | *(folded into P-47 / P-49)* | — | — |
| P-11 | *(folded into P-33)* | — | — |
| P-12 | *(link-key fix folded into P-33; `source_recommendation` moot if P-32 retires TransferEngine)* | — | — |
| P-13 | *(folded into P-35)* | — | — |
| P-14 | *(folded into P-37)* | — | — |

**High-value capabilities needing a pilot**

| ID | Proposal | Module | Note |
|---|---|---|---|
| P-15 | *(superseded by P-26, P-28, P-29 in Batch 2)* | — | — |
| P-16 | Branch/batch-scoped near-expiry markdown (instead of chain-wide `special_discp`) | batches, discount_approvals | **Pricing change → stop-and-ask** |
| P-17 | *(now P-46)* | — | — |
| P-18 | *(now P-31)* | — | — |
| P-19 | *(now P-32)* | — | — |
| P-20 | *(split: margin delta → P-35; leakage report → P-36; margin floor → P-38 gate)* | — | — |

**Strategic investments**

| ID | Proposal | Note |
|---|---|---|
| P-21 | *(now P-50 + P-51)* | — |
| P-22 | *(now P-52)* | — |
| P-23 | *(now P-53)* | — |
| P-24 | EDA track-and-trace readiness (with the SOFTECH vendor) | Decree 475/2025 |
| P-44 | Full accounting module to retire Excel (HQ expenses, journals) on the mirrored chart of accounts / BS / IS | Owner: wanted later, not now |
| P-45 | Insurance claim submission → payment → deductions embedded in the insurance module | Owner: wanted later; P-41 covers collection from SOFTECH meanwhile |
| P-25 | Inter-branch transfer execution: TransferRequest written as a native ISR/125 via the existing writer pattern (end double entry) | SOFTECH write → stop-and-ask |

**Attractive but not worth building now**

| Idea | Why not now |
|---|---|
| Own customer app / e-commerce | Online share is modest even for large GCC chains (Al-Dawaa 5%, 2021); delivery already flows through SOFTECH CRM |
| Autonomous substitution engine | Rule 5; composition data is pharmacist-gated; clinical validation absent |
| More AI narrative or insight rules | 7.4k findings already have no owner or action |
| Social channels (TikTok etc.) expansion | 3 social messages total |
| Robotics / central fill | Scale mismatch; pre-picking at HQ is the transferable part |
