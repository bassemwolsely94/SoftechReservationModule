# Task E3 report
Status: DONE. Tests: 297 OK (test_pbx_*, test_pic_*, test_callcenter_pbx_link, test_endpoint_sweep, kept DB); makemigrations --check: no changes.
Code: apps/pbx/cdr.py (LINE_PREFIXES, split_line_prefix, national_number, phone_key, parse_inbound/outbound), CdrCall.line_prefix (mig 0008), renormalise_pbx_numbers command (also re-keys PhoneLabel), ami_bridge uses cdr.inbound_number, PicResolver/_search prefilter last 8 digits then exact key, numbers._kind handles 11-digit keys, docs 33 s15 + 11_ERP_INDEX.
Dev DB (133,321 calls) pic_match before -> after: single 93387->93905, shared_latest 18638->18718, shared_next 808->819, shared_unresolved 1841->1841, none 15428->14625, no_number 3219->3413 (no_number grew: 8x/9x short codes now key to empty).
Notes: the first --commit run was killed by a tool timeout mid-write; re-run completed, idempotent.
Existing tests: phone_key fixtures in test_pic_* switched to national form (intent kept).

## Fix round 1
- parse_inbound: any raw ^0\d{8,10}$ is already national, so the goip4 call_prefix '0' no longer strips the 0 of Alexandria/other-governorate landlines.
- phone_key: national 0-leading numbers (9-11 digits) are their own key => idempotent, Alexandria distinct from Cairo (property-style test over many forms).
- renormalise _relabel: collisions keep the newest label and print the dropped ones; dry run no longer accumulates the batch.
- linking.py compares phone_key (dial strings use their last segment); callcenter lookups use new cdr.lookup_tail (Cairo landline = last 8 digits, else 9).
- ami_bridge _normalize_caller_num: short code without line prefix; numbers._kind: key starting '01' is a mobile.
- Dev DB re-run (idempotent, 40 rows fixed): single 93899, shared_latest 18718, shared_next 819, shared_unresolved 1841, none 14631, no_number 3413.

## Fix round 2
- lookup_tail returns '' under 7 digits; CallLog._try_match_customer and callcenter lookup (customers + recent calls) skip on ''.
- CallLog match: tail prefilter then exact phone_key confirm, pk order (landline no longer attaches a mobile sharing 8 digits).
- phone_key iterates to a fixpoint (junk -> ''), 20k seeded random property test.
- Test hygiene: bridge _gateway_meta patched with cleanup; staff creation simplified.
- Dev DB re-run (259 rows): single 93805, shared_latest 18831, shared_next 819, shared_unresolved 1855, none 14592, no_number 3419.
