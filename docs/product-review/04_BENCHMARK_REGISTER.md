# 04 — External Benchmark & Source Register

**Compiled:** 2026-10-30 from web research. Rows marked *(snippet)* were judged from search-result text only. **Open
the source before quoting it externally.** "Dated" means published before 2018. Nothing here is a benchmark for our
own numbers. Where no credible numeric benchmark exists, we set our own baseline and pilot.

Each topic is laid out in three parts:
- **Fact:** what the source states.
- **Our state:** what this review observed in our system.
- **Adaptation:** our proposed adaptation, which is inference.

## 1. Egyptian regulation (highest relevance)

| Source | Fact | Our state | Adaptation | Confidence |
|---|---|---|---|---|
| **EDA Decree 475/2025**, unified national track-and-trace. [PDF](https://www.edaegypt.gov.eg/media/o0hnfrts/475-2025_en.pdf), Gazette 11 Aug 2025 (full text read) | Packs are tracked to dispensing or destruction. **Art. 4:** registered pharmacies must provide readers, printers and software, and link to the system. **Art. 5:** imported products from 1/2/2026, local products from 1/8/2026, phased by dosage form or group | No pack-ID capture anywhere | Read guideline 804/2025 ([PDF](https://www.edaegypt.gov.eg/media/me5loqeg/804-2025_en2.pdf), not read). Ask SOFTECH for its compliance plan before we design anything | High (fact) / unknown (our obligation detail) |
| EDA Decree 47/2025, expired-product recall. Masrawy [Feb](https://www.masrawy.com/news/news_egypt/details/2025/2/17/2728886), [Oct 2025](https://www.masrawy.com/news/news_egypt/details/2025/10/18/2874754) (snippet) | Companies accept expired packs from pharmacies within 90 days, smallest unit. 17M packs withdrawn by Oct 2025 | Disposal records exist; no supplier/company return ledger reconciled to SOFTECH | Expired-returns ledger by company, ready for the collection window (Batch 2) | Medium |
| **PDPL Law 151/2020 + Executive Regulations.** [Al Tamimi](https://www.tamimi.com/law-update/general/articles/from-policy-to-practice-egypt-issues-executive-regulations-of-the-personal-data-protection-law/), [CMS](https://cms.law/en/are/legal-updates/egypt-s-pdpl-executive-regulations-issued-one-year-compliance-countdown-begins), [Mondaq](https://www.mondaq.com/privacy-protection/1731130/) | Electronic direct marketing needs prior consent, sender identification and a free opt-out. **One law-firm source reports a compliance deadline of about 1 Nov 2026** (unverified against the Gazette). Health data is sensitive (general knowledge, not checked here) | No customer-level consent. Campaigns can target by chronic condition | P-05. **Escalate to legal now** | Medium (law-firm commentary) |
| Supreme Media Council + EDA on medicine advertising. [Ahram Gate](https://gate.ahram.org.eg/News/5079154.aspx) (snippet) | Medicine ads on media or social need approval (approval number + QR) | Campaigns and offers have no medicine exclusion | Default-block Rx/branded-medicine promotion (P-01, P-05) | Medium |
| Law 127/1955 (EDA translation) [PDF](https://edaegypt.gov.eg/media/4d5hhv1f/pharmacy-law-127-1955-translated.pdf) | Pharmacy licensing and ownership | Pharmacist-presence / dispensing rules **not verified** | Verify before any delivery or remote-dispensing design | Low (unverified) |
| UHI rollout. [Ahram](https://english.ahram.org.eg/News/578970.aspx), [Enterprise Aug 2026](https://enterpriseam.com/egypt/2026/08/11/egypt-prepares-to-double-universal-health-ins-reach-before-phase-1-results-are-in/) | Phase 1 covers six governorates; Phase 2 starts with Minya. **Cairo/Giza not in phases 1–2** | Insurance module covers private insurers | Monitor only | Medium |

## 2. Egyptian market

| Source | Fact | Adaptation |
|---|---|---|
| SFE + B Investments / El Ezaby, [Enterprise 9 May 2023](https://enterpriseam.com/egypt/2023/05/09/sfe-buys-49-of-el-ezaby-launches-pharma-logistics-firm-with-b-investments/) | Fund took 49%; shared digital/logistics services planned for 500+ pharmacies (**plan, no outcome**) | Our ops layer is the same idea at our scale |
| El Ezaby / Seif app store listings (snippet) | Delivery, online availability check (**capability claims**) | Expose branch-stock lookup to call centre and WhatsApp agents before building any app |
| Chefaa, [Wamda 2019](https://www.wamda.com/2019/08/chefaa-closes-figure-seed-funding-round), [2022](https://www.wamda.com/index.php/2022/03/chefaa-secures-undisclosed-venture-round) | Aggregator selling scheduled chronic-medicine packages (**claims**) | Chronic patients are a contested segment; keep them through refill service |

**No credible numeric benchmark** was found for Egyptian chains' loyalty, refill, expiry or training outcomes.

## 3. Interventions with demonstrated outcomes

| Source | Setting | Outcome (denominator, limits) | Applicability |
|---|---|---|---|
| Walgreens late-to-refill RCT, [PMC5338963](https://pmc.ncbi.nlm.nih.gov/articles/PMC5338963) (2017, dated) | US, pharmacist calls when a refill is 3 days late | n=735,218 (Medicare D). Refill within 14 days **+6.09 points**, but PDC≥80% only **+0.97 points**. Chain-authored | High; cheap with existing call-centre staff. **Expect modest effect** |
| Holdford & Saxena, appointment-based med sync, [PMC10398300](https://pmc.ncbi.nlm.nih.gov/articles/PMC10398300) (2015, dated) | 71-store US chain | Adjusted OR 2.3–3.6 for PDC≥0.80. **Self-selection** (enrolees already more adherent), industry-funded | Medium: a one-pick-up-date idea for multi-item chronic patients |
| Kooy et al. reminder device RCT, [PMC3665928](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3665928/) (2013, dated) | NL, 24 pharmacies | **Null overall** | Caution: reminders alone may not work, so measure |
| CVS ScriptSync, JAPhA 2017 ([PDF](https://scholar.harvard.edu/sites/scholar.harvard.edu/files/nkc/files/2017_the_impact_of_a_retail_prescription_sync_j_am_pharm_assoc.pdf), snippet) | US | ~+4.7 points net adherence (denominator not checked) | As above |
| KwaZulu-Natal redistribution, [BMC HSR 2023](https://bmchealthservres.biomedcentral.com/counter/pdf/10.1186/s12913-023-10096-4.pdf) | ZA public sector, 8 facilities | Descriptive: overstock/short-dated stock drove 68% of redistribution | Supports destination-aware transfers; **no outcome benchmark** |

**No credible benchmark** was found for near-expiry redistribution outcomes, pharmacy OOS customer response, or
cycle-count accuracy. A widely quoted "~4% of sales lost to OOS" figure could not be traced to its source, so it is
**not used**.

## 4. Staff capability & drug information

| Source | Fact | Adaptation |
|---|---|---|
| Abdelaziz et al. 2019, [PMC6627069](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6627069/), simulated patients, Minia, Egypt | ~150 pharmacies / 238 visits. **98.3% dispensed amoxicillin for viral respiratory scenarios**; 63% asked no relevant questions; interviews contradicted practice | Strong Egyptian rationale for short case-based scenarios + counselling checklist + internal mystery-shopper audits as the outcome measure (Batch 6) |
| FIP Global Competency Framework v2 (2020), [FIP](https://developmentgoals.fip.org/resources/executive-summary-fip-global-competency-framework-supporting-the-development-of-foundation-and-early-career-pharmacists-version-2-2020/) | 23 domains, ~124 behavioural statements, open access | Select 10–15 statements as a branch competency checklist |
| BNF licensing, [NICE](https://www.nice.org.uk/bnf-uk-only), [Pharmaceutical Press](https://www.pharmaceuticalpress.com/bnf-publications/) | BNF online is UK-only. Non-NHS reuse in third-party systems needs a licence | **Do not embed** BNF content (our interaction seed cites BNF, so check provenance). Link out or license |
| UpToDate / Lexidrug, [Wolters Kluwer](https://www.wolterskluwer.com/en-my/solutions/uptodate/pro) | Individual list prices exist; institutional pricing by quote | One HQ drug-information licence, not per counter |

## 5. International chains (capability claims unless stated)

| Source | Claim | Transferable part |
|---|---|---|
| Walgreens micro-fulfilment ([Supply Chain Dive](https://www.supplychaindive.com/news/walgreens-opens-ninth-micro-fulfillment-center-automating-operations/639957/)) | Central fill for 5,000+ stores; self-reported savings | Central pre-picking of chronic refills at HQ (no robotics) |
| Boots Pharmacy First ([newsroom](https://www.boots-uk.com/newsroom/news/boots-delivers-over-one-million-nhs-pharmacy-first-consultations-in-england)) | 1M+ consultations; volume, not outcomes | Structured minor-ailment protocols with referral flags |
| Nahdi FY2024 (Tadawul, snippet, verify) | Loyalty members reportedly >70% of revenue | Loyalty ID = backbone for refill and segmentation; our PIC link fits |
| Al-Dawaa ([Argaam 2022](https://www.argaam.com/en/article/articledetail/id/1538732)) | E-commerce 5% of net sales 2021 | Realistic online-share expectation |
| MedPlus FY24 annual report (BSE) | Private label 13.3% of revenue | Not in scope now |

## 6. Cold chain
WHO TRS 1025 Annex 7 (GSDP, current) and TRS 908 Annex 9 (2003, dated; scope includes community pharmacies). The EDA
inspection templates found cover **warehouses**: recorded thermometer/hygrometer readings. **No EDA community-pharmacy
fridge range was found**; 2–8 °C is the usual reference but is unverified for Egypt. → Batch 6: a twice-daily
fridge log in the QA module.
