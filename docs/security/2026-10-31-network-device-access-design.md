# Network + Device + User access gating — findings and design (DISCUSSION DRAFT)

Status: 🔍 discovery, nothing built. 2026-10-31. Owner decisions needed (§7).

Goal: every request is allowed only what **both** factors allow:

- **Factor A — where from:** the network (company LAN/VPN vs internet) and the device (registered and approved vs unknown).
- **Factor B — who:** role, module matrix, branch scope and per-user flags.

The goal serves two threats: **intrusion** (stolen passwords, hijacked sessions, brute force, internet reaching SOFTECH) and **leakage** (bulk exports, phones, finance, SOFTECH reads reaching places they should not).

---

## 1. Feasibility — yes

Users never talk to SOFTECH. Only the server does, through `config/sybase.py`. A static test (`apps/tests/security/static_scan.py`, empty baseline) guarantees nothing else connects. So "can this person read/write SOFTECH" is a **server decision per request**. It can be enforced at one choke point regardless of what the browser does.

The hard part is not the gate. It is **knowing reliably where a request came from**, because today everyone reaches the VPS over the public internet (see §2).

---

## 2. Current state — network path

| Fact | Evidence |
|---|---|
| DNS: `elrezeikyapp` → 41.196.0.34 (public) only; no split DNS | runbook §3 |
| Branch PCs, VPN laptops (ZeroTier/SSTP/WG) all browse the public IP → VPS sees the office/branch **public** NAT IP, never 192.168.x / 10.x | runbook L637 "VPS always sees the office as 41.32.31.187" |
| nginx listens on **all** interfaces (public 41.196.0.34, ZT 10.50.50.77, SSTP 10.0.0.77); ufw opens 443 on all | `deploy/nginx.conf:21,28`, runbook §4.4 |
| nginx is the edge (DNS-only, no CDN) → `$remote_addr` is the true peer; `core/client_ip.py` + `NUM_PROXIES=1` reads it correctly | `core/client_ip.py:12-20` |
| VPS has return routes only for 192.168.1/3/4/30/70 + ZT 10.50.50.0/24 (tunnel watcher) | runbook §5.0 L447-451 |
| Only network rule today: nginx `/admin/` allows 10/8, 172.16/12, 192.168/16 → the **whole shared ZeroTier** passes | `nginx.conf:55-64` |
| `/ws/` does not forward X-Forwarded-For | `nginx.conf:113-122` |
| Rate limits keyed per IP → all of HQ (behind one NAT IP) shares one login bucket | `nginx.conf:17-18`, `settings.py:302-304` |
| `https://10.50.50.77/...` would be refused (not in `ALLOWED_HOSTS`) | runbook §8.2 |

## 3. Current state — user, session and device

| Area | Today | Gap |
|---|---|---|
| Login | JWT access 1 h / refresh 7 d, httpOnly SameSite=Strict cookies, rotation + blacklist; disabled account refused every request | Tokens carry no network/device claim; refresh works from anywhere for 7 d |
| 2FA (TOTP) | Exists; `MFA_REQUIRED_ROLES` = admin/supervisor/purchasing; enforcement switch `security.mfa_enforced` **default OFF** | Not enforced; "remember device" = 30-day **bearer** token in localStorage, not bound to a device, not revocable per device |
| Brute force | Per-IP throttle 10/min + nginx 5/min | **No per-account lockout**; shared office IP buckets |
| RBAC | Matrix + `ModuleAccessMiddleware`; `RBAC_ENFORCEMENT` **default `log`** (enforce planned at cutover) | Not enforced yet; no network/device dimension; menus filtered by hard-coded role arrays |
| Branch scope | `core/branch_scope.py` (Batch 5) | — |
| Device | **No device model.** Phone vs desktop is decided by screen width in `LoginPage.jsx`; `PushSubscription.user_agent` is the only per-device record | Everything |
| Login log | `UserActivityLog` with IP | No user-agent, no device, no "new device/new network" alert |
| WebSocket | JWT + Origin checked at connect only | Socket outlives token expiry, disable, network change (24 h) |
| Django admin | Session auth, no 2FA; nginx private-range rule | Whole ZeroTier qualifies |

## 4. Current state — SOFTECH reach

- **One choke point:** `get_sybase_connection` :386, `get_branch_connection` :414, `SoftechConnector.connect` :871 → `_connect_with_retry` :362. `probe_connection` :458 is separate.
- **Write channels** (`apps/tests/security/softech_write_manifest.py`) all sit behind `.env` flags (default OFF) + `WRITER_INSTANCE`. The channels are POS push/cancel, invoices + coupons, supplier codes, price/discount, alignment, replication repair, AP recon, insurance reprice/date, loyalty points, offers A/B, document comments, sales rates, ISR, coverage, shortage flags and customer copy/merge/points.
- **~60 user endpoints read SOFTECH live**: POS batches/returns/contracts/discount/points, insurance import/lookup, invoices grid/validate, pricing replication, ISR fulfilment/transfer preview, purchase-expiry candidates, stock-count preview, ERP match, coupons, incentives, personal dashboard, `sync/branch-health?probe=1`, and more.
- **No runtime per-user/role/branch/device SOFTECH switch.** All switches are global, in `.env`, and need a restart.
- **The user is unknown at connect time.** The existing `CurrentUserMiddleware` thread-local is empty for JWT requests. Telemetry already has a contextvar scope (`web` / `cmd:x` / `job:x`) in `apps/sync/softech_load.py` that can be copied.
- **Background threads** (sync trigger, finance trigger, procurement, seasonality, stock-audit refresh, OCR dup scan, `probe_all_nodes`) drop any request context.
- `audit_softech_write` records **no IP**.

## 5. Bugs / holes found during the audit (independent of the new design)

| # | Finding | Risk | Status |
|---|---|---|---|
| H1 | `/api/personal/` is RBAC-exempt yet `persons/search/`, identities and `widgets/<pk>/data/` run **live HQ queries** for any logged-in user | Leakage (person data) to e.g. a rider | **Fixed in N0** (`d2eb797f`) |
| H2 | Rider location endpoint writes the driver's GPS into `order.delivery_lat/lng` — the same field the drop-off geofence checks (`delivery/views.py:1336` vs `:479`) | Geofence defeated | **Fixed in N0** (`091989e0`) |
| H3 | Delivery role holds `approve`+`finalize` → a rider can cancel/close own orders | Fraud | **Fixed in N0** (`091989e0`) |
| H4 | `/rider` has no role guard; the delivery role can open every `/` and `/m` route, limited only by the matrix (which is in `log` mode) | Leakage | **Deferred to N3** (needs the zone/matrix enforcement) |
| H5 | `GET /api/sync/branch-health/?probe=1` is an open read that fans out to 6 SOFTECH nodes | Load / DoS on SOFTECH from any login | **Fixed in N0** (`768eee28`) |
| H6 | Daphne runs `--proxy-headers`; it may take the **leftmost** (client-forgeable) X-Forwarded-For into `REMOTE_ADDR`, and several login/MFA paths fall back to `REMOTE_ADDR` | Spoofed IPs in logs; would break any IP rule — verify before relying on IP | **Fixed in N0** (`b65a2605`) |
| H7 | MFA remember-device = 30-day bearer token in localStorage | Stolen token skips 2FA from anywhere | **Fixed in N0** (`2f0977b4`) |
| H8 | No per-account lockout | Password spraying from many IPs | **Fixed in N0** (`deca2965, b191ff77`) |
| H9 | nginx `/admin/` allows whole 10/8 = every ZeroTier member; Django admin has no 2FA | Intrusion | **Fixed in N0** (`b856136d`) |
| H10 | HR attendance geofence uses client coordinates and never blocks | Attendance fraud (not security-critical) | **Owner decision** (not security-critical) |

## 6. Proposed design

### 6.1 Factor A1 — network: make "internal" unforgeable

**Recommended: company traffic comes in through the tunnel, decided by the interface nginx accepted it on.**

1. **Split DNS** on the HQ + branch MikroTiks (static DNS entry) and on ZeroTier laptops (ZeroTier Central DNS push, or a managed hosts entry): `elrezeikyapp.dawalvry.com` → **10.50.50.77**. Internet users still resolve 41.196.0.34. The same TLS certificate works because the name is unchanged.
2. **Routing:** branch LANs already route over ZT/SSTP to the VPS. The VPS needs return routes for every LAN/VPN range that should count as internal, **without src-NAT**, so nginx sees the real device IP (192.168.x.y / 10.50.50.x).
3. **nginx:** a separate `server` block bound to `10.50.50.77:443` (+ `10.0.0.77:443` for SSTP failover) sets `X-ElR-Network: internal`. The public block sets `external`. Both **overwrite** any client value. Django trusts only this header (from 127.0.0.1).
   - Nobody on the internet can reach 10.50.50.77, so the label cannot be faked by IP spoofing.
4. **Zones inside "internal":** classify by source CIDR: branch LAN (192.168.x → which branch), staff VPN (10.50.50.x ZT, 10.0.0.x SSTP …). This lets a rule say "branch 130 PCs only from 192.168.30.0/24".
5. **Caveat:** ZeroTier is shared with staff. Every authorised ZT member = internal network, so ZT membership must be managed (Central authorisation, naming, revoke on leave). The **device** factor (6.2) covers this.

Rejected alternative: a list of branch public IPs. It is fragile (dynamic ISP IPs, WAN failover), and every guest on branch Wi-Fi would count as internal. Keep it only as a fallback signal.

### 6.2 Factor A2 — device registry

New model `Device`:
- `id`, `kind` (branch_pc / personal_laptop / phone / rider_phone / kiosk), `name`
- `branch` (for shared branch PCs) or `owner` (personal)
- `status` (pending / approved / blocked / retired)
- `allowed_users` / `allowed_roles`
- first/last seen IP + network + UA, `approved_by` / `at`

Enrollment and use:
- **Enrollment:** the first login from an unknown browser creates a *pending* device and issues a random device secret in an httpOnly, Secure, SameSite=Strict cookie (server keeps only a hash). An admin, or the branch manager for branch PCs, approves it in a «الأجهزة» screen. A login alert goes to the user and admin.
- **Every request** carries the device cookie. The server resolves `device` + `status`. A missing, blocked or unknown device → treated as unregistered.
- **Revocation:** block one device; its sessions end (blacklist its refresh tokens).
- **Later, for admin/owner/finance:** a WebAuthn passkey bound to the device, which cannot be copied by malware the way a cookie can.
- Replaces the MFA "remember device" token (H7). A trusted device can skip 2FA only while it is approved.

### 6.3 Combining: access zones

Each request gets a zone = f(network, device). Factor B then applies inside it:

| Zone | Network | Device | Default allowance (role still applies) |
|---|---|---|---|
| **Z1 trusted** | internal | approved | Full role capabilities, incl. SOFTECH live reads + writes the role holds |
| **Z2 internal-unknown** | internal | unregistered / pending | Login allowed; read-only screens; no SOFTECH writes, no exports; banner «جهاز غير معتمد» |
| **Z3 external-trusted** | external | approved + 2FA | Per-role **external profile**: listed modules only; SOFTECH read/write only if the role/user has the external flag; exports off by default |
| **Z4 external-unknown** | external | unregistered | Only roles marked "external allowed" (e.g. delivery → `/api/delivery/app/*` only), 2FA mandatory, no SOFTECH, no exports, phones masked |
| Public | any | none | Only `/api/portal/`, `/api/demand/public/`, `/api/delivery/track/`, customer form — never staff APIs |

Policy data (admin-editable, audited):
- `RoleNetworkPolicy(role, zone)` → allowed modules/actions (an extra column on the existing matrix), `softech_read`, `softech_write`, `export`, `require_mfa`, `max_session_hours`.
- Per-user override (`StaffProfile`) and per-device restriction (`Device.allowed_roles`).

**Example — rider:** zone Z3/Z4, role delivery → only my-orders / my-route / status update / location / collect-cash; no customers list, no SOFTECH, no export; session 12 h; device = their registered phone.

### 6.4 Enforcement points (all server-side)

1. **nginx** stamps `X-ElR-Network` (and adds `proxy_params` to `/ws/`).
2. **`AccessContextMiddleware`** (new, runs early):
   - resolves the user from the JWT (same way `ModuleAccessMiddleware` does), the network header, the client IP → branch/zone, and the device cookie;
   - computes the zone;
   - stores everything in a contextvar (copy of the `softech_load` pattern) and on `request`.
3. **`ModuleAccessMiddleware`** consults the zone policy as well as the role matrix. Exports (`export` action) are checked here.
4. **Login / refresh / MFA verify:**
   - refuse roles not allowed in the zone;
   - require 2FA by zone;
   - tokens get `zone` + `device` claims;
   - **refresh re-evaluates** (a token issued internally does not keep internal rights when used outside).
5. **SOFTECH gate in `config/sybase.py::_connect_with_retry`** (+ `probe_connection`):
   - if scope is `web`, read the context: no `softech_read` → refuse with a distinct `SoftechAccessDenied`;
   - no `softech_write` → wrap with the existing read-only proxy (per request instead of global);
   - scheduler `job:*` / commands `cmd:*` = system policy;
   - web with no context → fail closed;
   - background threads started by views must use `contextvars.copy_context().run`;
   - `SoftechAccessDenied` must never be classified as "branch offline" (POS retry queue `_is_unreachable`).
6. **WebSocket:** same context at connect, plus periodic re-check (e.g. every 5 min) and server push to close the socket on device block, disable or zone change.
7. **Audit:** every login, device event and zone denial goes to `UserActivityLog` with UA + device. `audit_softech_write` gains IP, device and zone.

**Rollout like RBAC:** a `NETWORK_POLICY_ENFORCEMENT=off|log|enforce` switch. Run in **log** first to see who reads SOFTECH from where (add user/zone to `softech_load` telemetry), then enforce.

### 6.5 Intrusion hardening that goes with it

- Per-account lockout / progressive delay (keyed on the account, not IP); alert on spraying.
- 2FA enforced for every login outside Z1; for admin/supervisor/purchasing/finance everywhere.
- Fix H6 (Daphne proxy-headers) before any IP-based rule.
- Django admin: only from the internal network **and** an approved admin device, and only via the internal server block; add the hostname to `ALLOWED_HOSTS` properly.
- New-device / new-network login notification to the user + admin.
- HSTS on; session cap per zone (e.g. external 8 h, no 7-day refresh).

### 6.6 Leakage controls that go with it

- `export` blocked outside Z1 by default; every export audited + watermarked (user, time, device) in the file.
- Phone masking (Batch 5b) stays; in Z3/Z4 every phone is masked unless the module requires it (rider sees only their order's customer phone).
- Bulk-read anomaly alert: one user pulling far more customers/rows than normal → alert + temporary block.
- Close H1 (`/api/personal/` live HQ reads) and H5 (open SOFTECH probe).

### 6.7 Public surfaces (customer-facing) — isolated

Existing: `/notify` (`apps/demand/views.py:1153-1215`), `/portal` (magic link, own auth scheme), `/track/:token`. Any customer data-entry form follows the same pattern:

- Own path prefix `/api/public/...`. Nothing else is reachable anonymously. The middleware denies any anonymous request outside the allow-listed public paths.
- Write-only: a field allow-list, server-side validation, length limits, no read-back of stored data (a customer cannot query whether a phone exists = no enumeration).
- Rate limits per IP **and** per phone; honeypot field + minimum fill time; optional CAPTCHA (owner decision: third-party Turnstile/hCaptcha vs self-hosted).
- Optional signed, expiring link per invitation (token says which customer/branch/campaign) so random visitors cannot submit.
- Entries land in a **staging** table, reviewed or matched before touching `Customer` (no direct overwrite of master data from the public).
- No SOFTECH access, ever, from public paths (enforced by the SOFTECH gate: anonymous context = no access).

## 6.8 Network plan for the chosen option (tunnel + split DNS)

**Target:** a company device resolves `elrezeikyapp.dawalvry.com` → 10.50.50.77. Its packets travel branch → HQ (SSTP) → VPS (ZeroTier, SSTP 10.0.0.77 as backup), **without NAT**, so nginx sees the device's real address. Return packets come back the same way.

| Step | Where | What |
|---|---|---|
| T1 | IT inventory | List every site: name, router model, LAN subnet(s), guest Wi-Fi subnet (must stay **out**), how it reaches HQ (SSTP RC0x / ZeroTier / IPsec), staff VPN pools (SSTP `vpn_pool` 10.10.10.0/24, wg-mobile 10.30.30/24, wg0 10.20.20/24, wg-Mohsen 10.60.60/24, back-to-home 10.250.250/24) and which of them count as internal |
| T2 | HQ MikroTik | Forward rule: internal source list `elrezeiky-internal-clients` (LANs + chosen VPN pools) → 10.50.50.77 / 10.0.0.77 tcp 443 (80 for the redirect) only. No src-NAT for that traffic (place an `accept` above the masquerade rules). Keep the existing VPS→SOFTECH rules unchanged |
| T3 | Each branch router | Static DNS `elrezeikyapp.dawalvry.com A 10.50.50.77` (branch PCs must use the router as DNS; block outbound DNS 53/853 to other resolvers from the staff LAN so it cannot be bypassed). Route 10.50.50.77/32 (+10.0.0.77/32) via the HQ tunnel. Guest Wi-Fi gets **no** such entry/route → always external |
| T4 | HQ LAN | Same static DNS entry on the HQ router |
| T5 | ZeroTier laptops | ZeroTier Central DNS push (search domain + DNS server = a resolver that answers 10.50.50.77), or a managed hosts entry. Laptop off ZeroTier → public IP → external zone (correct behaviour) |
| T6 | VPS | Tunnel watcher: add return routes for every internal range from T1 (today only 192.168.1/3/4/30/70). nginx: second `server` block `listen 10.50.50.77:443 ssl` + `listen 10.0.0.77:443 ssl` with `X-ElR-Network internal`; public block `listen 41.196.0.34:443` with `external`; ufw 443 stays open on all three |
| T7 | Test | From each branch PC: `nslookup` gives 10.50.50.77; the app's «من أين أتصل؟» check (built in N1) shows internal + the branch; from mobile data shows external; ZT down → SSTP failover still internal |

Behaviour notes:
- If both tunnels are down, branch PCs cannot reach the app by name. Fallback: a staff member switches to the public path (mobile data), lands in the external zone with reduced rights. An optional emergency setting can treat a known HQ public IP as internal while the tunnel is down; it is off by default and audited.
- POS traffic from branches now rides the tunnel: ~47 ms measured HQ↔VPS over ZT, fine for the UI.
- Every authorised ZeroTier member is "internal network". Device approval (6.2) is what stops an internal-network stranger. ZT membership must be reviewed (name every member, de-authorise leavers).

## 7. Decisions needed from the owner

1. ~~**How to recognise "internal"**~~ — **DECIDED 2026-10-31: tunnel + split DNS** (§6.8). A list of public IPs is kept only as an optional, audited emergency fallback.
2. ~~**Who approves devices**~~ — **DECIDED 2026-10-31: admin only** (every device kind, incl. branch PCs). Branch managers may see their branch's pending/approved devices but cannot approve, block or edit. Because one person approves everything, the «الأجهزة» screen needs a fast queue: pending list with user, branch, network/IP, UA, first-seen; approve/reject in one keystroke (`useGridKeyboard`); bulk approve for a branch's PCs during rollout; a notification to admins on each new pending device.
3. ~~**Default external profile per role**~~ — **DECIDED 2026-10-31 (accepted as proposed):**

   | Role | Z3 (external, approved device + 2FA) | Z4 (external, unknown device) |
   |---|---|---|
   | admin | All modules; SOFTECH read; SOFTECH write only with per-user flag `external_softech_write`; export off unless per-user flag | Blocked |
   | supervisor, purchasing, quality_manager | Their modules view-only; SOFTECH read; no write; no export | Blocked |
   | call_center | Intake, demand, reservations, customers (phones masked except the active customer); no SOFTECH write; no export | Blocked |
   | delivery | Rider surface only (`/api/delivery/app/*` + status/location/collect-cash); no SOFTECH; no customer list | Same rider surface, 2FA required, 12 h session |
   | pharmacist, salesperson, viewer | No external access | Blocked |

   All external sessions: 2FA required; max 8 h (rider 12 h), no 7-day refresh; phones masked; login alert to user + admins. Every value is editable later per role / per user / per device (audited).
4. ~~**CAPTCHA provider**~~ — **DECIDED 2026-10-31: self-hosted only**, no third-party service. Layers: proof-of-work challenge (open-source, e.g. ALTCHA, served and verified by our server, signed + single-use + expiring), honeypot field, minimum fill time, rate limits per IP and per phone, staging table before master data. No visitor data leaves our server.
5. **Which customer data-entry form** you meant (not found in the repo; `/notify` and `/portal` exist).
6. Fix the H-list first as a separate hardening batch?

## 8. Proposed batches

| Batch | Content | Touches SOFTECH writes? |
|---|---|---|
| N0 | Fix H1–H9 (personal exempt, rider bugs, open probe, proxy-headers, lockout, MFA token, admin) | No |
| N1 | nginx internal block + `X-ElR-Network`; `AccessContextMiddleware` + contextvar; network/zone logging only; telemetry by user/zone | No |
| N2 | Device registry + enrollment + «الأجهزة» screen + login alerts; replaces remember-device | No |
| N3 | Zone policy model + matrix column + login/refresh/middleware enforcement (`log` → `enforce`) | No |
| N4 | SOFTECH gate in `config/sybase.py` (log → enforce), thread context propagation, audit IP/device | **Yes — gate only (stop-and-ask: POS push path)** |
| N5 | WebSocket re-check, export watermark + anomaly alerts | No |
| N6 | Public-surface hardening (notify / portal / form) | No |
| IT | MikroTik split DNS + routes per branch, ZT DNS push, ZT membership discipline | Network side |
