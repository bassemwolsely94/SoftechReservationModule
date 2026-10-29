# ElRezeiky Platform — Link Datacenter VPS Runbook (single production environment)

> Target: Link Datacenter (LDC) SolidCP «PowerVPS» hosting space **dawalvry**, SpaceID 17631,
> location LDCOLSCLS1, Hyper-V. Quota: **1 VPS · 4 vCPU · 8 GB RAM · 300 GB disk**.
> Domain: **dawalvry.com** (nameservers already at ns10/11/12.linkdatacenter.net).
>
> This file is the step-by-step for THIS server. `deploy/DEPLOY.md` is the generic guide;
> everything here builds on the files in `deploy/` (systemd units, nginx.conf,
> staging.env.example) — nothing is duplicated, only filled in for this host.
>
> Written 2026-10-26. Status: **not started**.

---

## 0. The big picture — read before clicking anything

```
                Internet (HTTPS 443)
                       │
   ┌───────────────────▼─────────────────────────────────────────────┐
   │  LDC VPS  (Ubuntu 24.04, public IPv4)                            │
   │                                                                  │
   │  Nginx ── elrezeikyapp.dawalvry.com → Daphne :8000 (PRODUCTION)  │
   │  Scheduler · Redis · PostgreSQL 16 (elrezeiky_db)                │
   │  Local OCR: Tesseract + RapidOCR (in-app) · PaddleOCR :8077      │
   │                                                                  │
   │  Workbench /home/bassemwolsely94/work/app  (code editing + tests only:    │
   │  no website, no own DB, read-only DB role, SOFTECH read-only)    │
   │                                                                  │
   │  ZeroTier 10.50.50.77 (primary) · SSTP 10.0.0.77 (backup) ┐      │
   └───────────────────────────────────────────────────────────┼──────┘
                         encrypted tunnels (section 5.0)       │
   ┌───────────────────────────────────────────────────────────▼──────┐
   │  HQ office LAN                                                    │
   │  HQ MikroTik RB1100AHx4 «Bab El Haded HQ» (RouterOS 7.24.5)       │
   │      ZT 10.50.50.1 / SSTP 10.0.0.1 · src-NAT to 192.168.1.201     │
   │      only Sybase/PBX ports                                        │
   │      → SOFTECH HQ  192.168.1.8:5000 (Sybase ASE)                  │
   │      → branch nodes 192.168.3.x / .4.x / .30.x / .70.x :5000      │
   │        (over the existing SSTP / ZeroTier branch links)           │
   │      → Issabel PBX (AMI 5038 / CDR MySQL 3306 / SFTP recordings)  │
   └───────────────────────────────────────────────────────────────────┘
```

### Three facts that drive the whole plan

1. **SOFTECH is not on the internet, and must never be.** All six SOFTECH nodes (HQ + 5
   branches) live on private 192.168.x addresses. A server in a datacenter cannot reach them
   until a **site-to-site VPN** exists. Without the VPN the app starts, but every sync, the POS
   writer, ISR, insurance… fails. **The VPN (section 5) is the critical path.** Never "solve" it
   by port-forwarding Sybase 5000 to the internet.
2. **Only one copy of the scheduler and the SOFTECH writers may run anywhere.** Today they run
   on the office Windows machine. If the office machine and the VPS both run them, every sync
   runs twice and, worse, writers (ISR, POS queue flush, coverage, invoices…) can **post twice
   to SOFTECH**. The cutover (section 11) is a strict, ordered switch-over.
3. **One environment only: production — and development continues on it** (owner decision,
   2026-10-26). There is no dev website and no dev database. Development happens in a
   **workbench** folder on the same server (section 13): you and Claude Code edit code and run
   tests there, with a **read-only** database login and the SOFTECH kill-switch on, so the
   workbench can look at everything and change nothing. Code reaches the live folder only through
   Git + `release.sh`. Each release is a live change for every branch — hence small releases,
   a backup before each, and releases outside busy hours.

### Resource budget (8 GB RAM, with local OCR)

| Process | Typical RAM |
|---|---|
| PostgreSQL (tuned, section 7.3: shared_buffers 1.5 GB) | 2–2.5 GB |
| Daphne web + JVM (JPype/jConnect) | 0.8 GB |
| + OCR inside the web process (Tesseract per page, RapidOCR) | +0.3–0.6 GB while OCR runs |
| Scheduler + JVM | 0.8–1 GB, spikes during sync |
| PaddleOCR sidecar (own service, capped) | 1–1.5 GB, hard cap 2 GB |
| Redis, Nginx, OS | 0.5 GB |
| Workbench while you develop (VS Code server, Claude Code, tests, Vite) | 0.5–1 GB |
| **EasyOCR (torch) — only if selected; stays loaded in the web process** | **+1.5–2 GB** |

Verdict: **8 GB runs production + Tesseract + RapidOCR + PaddleOCR**, with the sidecar
capped and 4 GB swap (section 4.6) as a safety net. It does **not** comfortably hold EasyOCR
as well: EasyOCR's model stays in the web process's memory after its first use. So EasyOCR is
installed but never the default engine. CPU is the other limit: a 50-page invoice bundle keeps
the 4 vCPUs busy for minutes, so OCR is throttled (section 8.4) to keep the screens responsive
for branches.

**Recommended:** ask LDC for a quote to raise the plan to **16 GB / 8 vCPU**. That removes both
limits (EasyOCR and faster-whisper call transcription become possible, and OCR stops competing
with the branches for CPU). Everything in this runbook works unchanged on the bigger plan.

**Decision (2026-10-26): start on 8 GB with the OCR caps; upgrade later if needed.** Signs that
it's time to upgrade: `free -h` shows swap in steady use, `elrezeiky-ocr` restarts after hitting
its 2 GB cap, or branches report slow screens while invoice bundles are being read. Upgrading
is a SolidCP resize plus the 16 GB values noted in 7.3 (`shared_buffers`) and 8.4 b (sidecar caps).

Disk (300 GB) is comfortable: DB 8.5 GB today + growth, 14 nightly dumps (~2 GB each
compressed), media 0.7 GB, OCR models ~1.5 GB, venvs/node_modules ~8 GB.

---

## 1. Before you create the VPS — preparation on the office machine

### 1.1 Get all code into Git (MANDATORY)

The server gets its code from GitHub (`bassemwolsely94/SoftechReservationModule`), never by
copying the OneDrive folder. Today the working tree has **~229 uncommitted files** and
`origin/main` was last updated in May 2026. Whatever is not pushed will not exist on the server.

1. Review and commit the pending work on the current branch.
2. Push the branch, open a PR, merge into `main` (or decide which branch production runs from).
3. Production runs `main`. Work in progress lives on feature branches until it is merged.

Make sure these are **NOT** in Git (they are git-ignored already): `.env`, `media/`,
`staticfiles/`, `logs/`, `backups/`, `venv/`. `libs/jconn3.jar` **is** in Git — good, the
server needs it.

Local-OCR files (section 8.4):
- `ocr_sidecar/` (PaddleOCR server) is currently **untracked** — commit it, the server needs it.
- `ocr_tessdata/` (ara/eng/osd traineddata, 27 MB) is **git-ignored** on purpose — you'll copy
  it to the server with `scp` (section 8.4).

> Small cleanup: `.gitignore` line 52 reads `.envdocs/architecture/softech_gift_vouchers_investigation.txt`
> — two entries glued together (missing newline). Harmless for `.env` (line 5 covers it), but fix it.

### 1.2 Inventory the current `.env`

Open the office `.env` and make a private list (password manager, not chat/email) of every
value you'll need on the server: Sybase host/user/password, PG password, Gemini keys, WhatsApp
token / phone id / app secret / verify token, Meta Graph secrets, `OMNI_CREDENTIALS_KEY`, AMI /
Issabel CDR credentials, VAPID keys, and **every `*_ENABLED` writer flag and its current value**.
You'll re-create production `.env` from this list (section 8.2).

> ⚠️ `OMNI_CREDENTIALS_KEY`: stored channel credentials are encrypted with it (or with a key
> derived from `SECRET_KEY` when it is empty). If the office `.env` has no `OMNI_CREDENTIALS_KEY`,
> compute the derived key from the CURRENT `SECRET_KEY` and pin it — see `deploy/DEPLOY.md` §3 —
> before you generate a new `SECRET_KEY` for the server. Otherwise WhatsApp/social accounts must
> be re-entered.

### 1.3 HQ VPN end = the HQ MikroTik router (decided)

The HQ router is a **MikroTik** that runs WireGuard, so the tunnel ends on the router itself —
no extra box at HQ. Confirmed on 2026-10-26 from the router «Bab El Haded HQ»:

| Fact | Value | What it means here |
|---|---|---|
| Model / version | RB1100AHx4 Dude Edition, **RouterOS 7.24.5 stable** | WireGuard supported — no upgrade needed |
| Router RAM / flash | 1 GB (863 MB free) / 128 MB (78 MB free) | plenty for one more tunnel; backups fit |
| HQ LAN address | **192.168.1.201/24 on ether4** | VPS traffic will be src-NATed to this address |
| WAN | ether1 `41.32.31.187/28` (static public, "WAN 2") + ether2 `192.168.2.5/24` (behind an ISP router, "WAN") | the tunnel dials out on whichever WAN is active; on failover it re-connects by itself (the VPS learns the new address) |
| Existing WireGuard | `wg0` 10.20.20.0/24, `wg-mobile` 10.30.30.0/24 (+10.99.99 disabled), `wg-Mohsen-Backup` 10.60.60.0/24 | the new interface is named **`wg-vps`** with **10.77.0.0/24** — no name or address clash in the part printed |
| Other VPNs | back-to-home-vpn (10.250.250/192.168.216), ZeroTier `ZT-ELREZEIKY-HQ` 10.50.50.0/24, SSTP branch tunnels (`sstp-RC03-AinShams`, `sstp-RC09-Alzahar`, … on 10.0.0.x) | branches are reached over SSTP/ZeroTier — the VPS will use those same paths; nothing changes on the branch side |

> **Why not just add the VPS to the existing ZeroTier network?** It would work, but it puts the
> VPS inside a network with every other ZeroTier member and depends on ZeroTier's cloud
> controller. A dedicated WireGuard interface lets the router's firewall limit the VPS to
> exactly the Sybase/PBX ports (section 5.2 d).

Still to collect before VPS day:
- The rest of `/ip address print` (the output stopped at item 12) — run
  `/ip address print without-paging where address~"10.77."` and
  `/ip route print where dst-address~"10.77."` — both must return **nothing**. ✅ **Checked 2026-10-26: both empty — 10.77.0.0/24 is free.** If they ever return
  something, pick another tunnel subnet (e.g. 10.78.0.0/24) everywhere in section 5.
- The list of SOFTECH addresses: HQ 192.168.1.8 + each branch's `db_host` from the Branch table,
  and the Issabel PBX address.

The router only needs **outbound** internet; HQ does not need a static public IP. The tunnel
is dialled from HQ to the VPS.

Also confirm with whoever manages the SOFTECH servers and the PBX: they must accept connections
**from 192.168.1.201** (the router src-NATs all VPS traffic to it).

---

## 2. Create the VPS in SolidCP (your screenshot 1)

Hosting Space Menu → HyperV → **Create New VPS**.

### 2.1 Name & OS

| Field | Value |
|---|---|
| Host name | left box `elrezeikyerp`, right box `dawalvry.com` (→ **`elrezeikyerp.dawalvry.com`**, chosen 2026-10-26). Untick "Generate hostname automatically". |
| Operating system | **Ubuntu 24.04** — NOT 26.04 and NOT Windows Server. |
| Administrator password | A long random password (24+ chars) saved in your password manager. This is the **root** password; you'll switch to SSH keys and disable password login in section 4. |
| Send summary e-mail | Optional. The e-mail contains the root password in clear text — untick it, or delete that e-mail afterwards. |

Why Ubuntu 24.04 LTS:
- `deploy/DEPLOY.md`, the systemd units and nginx.conf are written for Ubuntu/Debian.
- It ships **Python 3.12** (PaddleOCR wheels need ≤ 3.12) and **PostgreSQL 16** — the same
  major version as the office database, so the dump restores cleanly.
- Daphne/Channels/JPype are far simpler on Linux; Windows Server would also cost a licence and
  ~2 GB more RAM.
- 26.04 is still young; third-party wheels (torch, paddle, onnxruntime) lag behind it.

### 2.2 Configuration (resources)

The values on the SolidCP Configuration page (checked against the 2026-10-26 screenshot):

| Field | Set to | Why |
|---|---|---|
| CPU | **4** cores | the whole quota |
| RAM | **8192** MB | the whole quota |
| HDD | **300** GB | the whole quota |
| Dynamic memory enabled | **unticked** ✅ | PostgreSQL and the JVM behave badly when RAM shrinks under them |
| Number of snapshots | shows **0** and is greyed out → your plan has **no snapshot quota** | see 2.5 — ask LDC to enable it |
| DVD drive installed | ticked is fine (harmless; you can untick it) | not used |
| Boot from CD | **unticked** | the VPS must boot from its disk |
| "Num Lock" enabled | **tick it** (harmless either way) | only affects typing on the number pad inside the SolidCP **web console** (the emergency screen). SSH, the app and Cockpit don't use it |
| Allowed actions | Start/Turn off/Shutdown ✅, Pause/Resume ✅, Reboot ✅, Re-install ✅ (Reset is greyed) | keep **Re-install** while you set the server up (a clean restart if the first install goes wrong), but remember it **erases the whole VPS** — never click it after go-live |

**Which power button to use later**

| Button | What it does | When |
|---|---|---|
| **Reboot** / **Shutdown** | asks Ubuntu to stop cleanly: services stop, PostgreSQL saves its data, then restart / power off | **always use these** |
| **Turn off** | pulls the power cable — no clean stop | only if the server is frozen and SSH + the web console don't respond |
| **Reset** (greyed out — LDC doesn't offer it on this plan) | presses the hardware reset button — same risk as Turn off | not needed; Turn off + Start does the same |
| **Pause / Resume** | freezes the VPS in memory | avoid in production: while paused, every sync, POS push and branch screen stops |

After a hard Turn off, PostgreSQL recovers by itself on the next start (it's crash-safe), and the
SOFTECH writers are idempotent, so nothing is double-posted — but in-flight work is lost and the
first start takes longer. That's why Reboot/Shutdown are the normal buttons.

### 2.3 External Network

Tick **External network enabled** and make sure **one public IPv4** is assigned.

On 2026-10-26 the pool offered exactly one address (quota "1 max"):
**`41.196.0.34`**, gateway **`41.196.0.1`**, VLAN 0. Pick **"Select IP addresses from the list"**
and **click that line so it is highlighted** before pressing Next. ("Randomly select" would
give the same address, since it's the only one, but choosing it explicitly removes any doubt.)
This runbook uses 41.196.0.34 everywhere (DNS, SSH, MikroTik endpoint, scp). After creation,
confirm it on VPS Menu → your VPS → Network and note the subnet mask and DNS servers shown.

Private network: not needed.

### 2.4 Summary → Create

Wait for provisioning (Running Tasks in the side menu shows progress). When the VPS shows as
running, open **VPS Menu → your VPS** and confirm the public IP. Use the SolidCP VPS console
(the in-browser screen) only if SSH doesn't work.

### 2.5 Snapshots — your plan has none yet

The Configuration page shows **Number of snapshots: 0 (greyed out)**: the PowerVPS plan has
no snapshot quota. Snapshots are the fastest undo button (a whole-server rollback in minutes),
so open a ticket with LDC:

> *"Please enable Hyper-V snapshots for the VPS elrezeikyerp.dawalvry.com in space dawalvry
> (SpaceID 17631) — at least 3 — and tell us any extra cost."*

- **If they enable it:** VPS Menu → Snapshots → take `00-clean-install` now, and one at each 📸
  mark below (`01-hardened`, `02-vpn-ok`, `03-app-installed`, `04-live`). Keep only the last 2–3;
  they use disk and slow Hyper-V down when many pile up.
- **Until then** (and in any case), every 📸 mark means: **write down what you changed**, and from
  section 10 onward take a `pg_dump` (section 12.1) plus a copy of `/opt/elrezeiky/app/.env`.
  Before the app is installed, the honest fallback is SolidCP **Re-install** + re-running the
  runbook steps — which is why every step here is written as copy-paste commands.
- Snapshots never replace the nightly backups + off-site copy (section 12.1): a snapshot lives
  on the same LDC host as the VPS.

---

## 3. DNS — why `dawalvry.com` says "can't reach this page" (your screenshot 3)

`DNS_PROBE_FINISHED_NXDOMAIN` = "this name does not exist". I checked: the domain IS delegated
to `ns10/11/12.linkdatacenter.net`, but those nameservers have **no records** for it yet. That's
expected — nothing has been created there yet. It is NOT a problem with the domain itself.

Create these records (once the VPS has its public IP):

| Type | Name | Value | Purpose |
|---|---|---|---|
| A | `dawalvry.com` (@) | 41.196.0.34 | optional — the app does not use it (Nginx and the certificate serve `elrezeikyapp` only) |
| A | `elrezeikyapp` | 41.196.0.34 | **the service**: staff open `https://elrezeikyapp.dawalvry.com`; WhatsApp webhook, portal links, certificate. Never changes, even if the server is replaced |
| A | `elrezeikyerp` | 41.196.0.34 | **the machine**: SSH, VS Code Remote, admin. If the server is ever replaced, the new one gets its own name and only `elrezeikyapp` is re-pointed |
| CNAME | `www` | `dawalvry.com` | optional |

How:
1. In SolidCP look for **Hosting Space Menu → Domains** (or Account Menu → Domains/DNS Zones).
   Add `dawalvry.com` as a domain, open its DNS zone, add the records above.
2. If your hosting space has no Domains/DNS item (the plan shown is VPS-only), open a ticket
   with LDC: *"Please create a DNS zone for dawalvry.com on your nameservers with A records
   @, elrezeikyapp and elrezeikyerp → 41.196.0.34"*, or ask them for DNS-zone access.
3. Alternative that gives you full control: move DNS to Cloudflare (free) by changing the
   domain's nameservers at the registrar (LDC). If you use Cloudflare, set the records to
   **DNS only (grey cloud)** at first, so Let's Encrypt and WebSockets work simply.

Check from the office PC (it can take minutes to a few hours):
```bash
nslookup elrezeikyapp.dawalvry.com 8.8.8.8
```
It must return the VPS IP before you can request TLS certificates (section 9.3).

---

## 4. First login and hardening the server

Everything below runs on the VPS over SSH. From the office Windows PC (PowerShell has `ssh`):

```bash
ssh root@41.196.0.34
```

### 4.0 Check that the system disk really has the 300 GB

First login on 2026-10-26 showed **"Usage of /: 28.8% of 22.94GB"**: the operating system's
partition is only ~23 GB although the VPS was created with a 300 GB disk. The LDC Ubuntu
template is a small image; the extra space must be handed to `/` before installing anything
(the database alone will need far more than 23 GB). Check:
```bash
lsblk                      # disk size vs partition sizes
df -h /
vgs; lvs                   # only if the system uses LVM (ubuntu-vg / ubuntu-lv)
```
Then, depending on what it shows:

| What you see | Fix |
|---|---|
| LVM, and `vgs` shows **VFree ≈ 277G** | `lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv` |
| Disk `sda` = 300G but its last partition is ~23G | grow the partition first: `apt -y install cloud-guest-utils` → `growpart /dev/sda <partition number>` → then LVM: `pvresize /dev/sdaN` + the `lvextend` above; no LVM: `resize2fs /dev/sdaN` |
| Disk `sda` itself is only ~25G | the 300 GB never reached the VM → ticket to LDC |

Finish with `df -h /` — it must show ~295 G.

✅ **Done 2026-10-26:** `sda` was 300G with `sda3` only 46.9G (LVM, 23.5G used by `/`). `growpart /dev/sda 3` → `pvresize /dev/sda3` → `lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv` → `/` = **293G** (6.7G used). Tip: if pasted commands arrive with `^[[200~` in front, run `echo 'set enable-bracketed-paste off' >> ~/.inputrc` once.

### 4.1 Update + basic tools + timezone

```bash
apt update && apt -y full-upgrade
apt -y install curl wget git unzip htop ufw fail2ban ca-certificates gnupg build-essential \
               software-properties-common unattended-upgrades
timedatectl set-timezone Africa/Cairo          # settings.TIME_ZONE = 'Africa/Cairo'
hostnamectl set-hostname elrezeikyerp.dawalvry.com
reboot
```

### 4.2 Admin user + SSH keys

On the office PC (once), create a key if you don't have one:
```bash
ssh-keygen -t ed25519 -C "bassem-office"
```
On the VPS:
```bash
adduser bassemwolsely94                     # your personal admin login
usermod -aG sudo bassemwolsely94
mkdir -p /home/bassemwolsely94/.ssh && chmod 700 /home/bassemwolsely94/.ssh
nano /home/bassemwolsely94/.ssh/authorized_keys     # paste the content of C:\Users\basse\.ssh\id_ed25519.pub
chmod 600 /home/bassemwolsely94/.ssh/authorized_keys && chown -R bassemwolsely94:bassemwolsely94 /home/bassemwolsely94/.ssh
```
Open a **second** terminal and confirm `ssh bassemwolsely94@41.196.0.34` works **before** the next step.

Simpler from Windows (no copy-paste), at the `PS C:\>` prompt — asks the user's password once:
`type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh bassemwolsely94@41.196.0.34 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"`

✅ **Done 2026-10-26:** user `bassemwolsely94` (sudo), key `C:\Users\basse\.ssh\id_ed25519`
(ed25519, passphrase, SHA256:PBCbi8vO…) — key login + `sudo whoami` → root verified.

### 4.3 Lock SSH down

> ⚠ **Ubuntu cloud images trap:** `/etc/ssh/sshd_config.d/50-cloud-init.conf` contains
> `PasswordAuthentication yes`, and sshd keeps the **first** value it reads (files are read in
> name order). A file called `99-…` would be silently ignored — so ours is named **`00-…`**.

```bash
sudo tee /etc/ssh/sshd_config.d/00-hardening.conf >/dev/null <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 4
EOF
sudo sshd -t                     # no output = config is valid
sudo systemctl restart ssh
sudo sshd -T | grep -Ei '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|maxauthtries) '
```
The last command must print `permitrootlogin no`, `passwordauthentication no`,
`kbdinteractiveauthentication no`, `maxauthtries 4`.

Keep the current session open and test from a **new** PowerShell window:
- `ssh bassemwolsely94@41.196.0.34` → logs in with the key ✅
- `ssh root@41.196.0.34` → `Permission denied (publickey)` ✅
- `ssh -o PubkeyAuthentication=no bassemwolsely94@41.196.0.34` → `Permission denied (publickey)` ✅ (passwords refused)

If you ever lose the key: the SolidCP **web console** (VPS Menu → your VPS) still accepts the
root password — these rules only apply to SSH.

### 4.4 Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp          # SSH (later restrict: sudo ufw allow from <office public IP> to any port 22)
sudo ufw allow 80/tcp          # HTTP → redirect + Let's Encrypt
sudo ufw allow 443/tcp         # HTTPS
sudo ufw allow 51820/udp       # WireGuard
# Cockpit (9090) is opened later on the VPN interface only — section 12.3
sudo ufw enable
sudo ufw status verbose
```
PostgreSQL (5432), Redis (6379) and Daphne (8000/8001) are **never** opened — they listen on
127.0.0.1 only.

### 4.5 fail2ban + automatic security updates

```bash
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd                    # jail "sshd" active
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' | sudo tee /etc/apt/apt.conf.d/20auto-upgrades
# stay on 24.04 LTS: stop the "New release 26.04 available — run do-release-upgrade" offer
sudo sed -i 's/^Prompt=.*/Prompt=never/' /etc/update-manager/release-upgrades
```
✅ §4.3 verified 2026-10-27: `sshd -T` → root/password/keyboard-interactive all `no`;
`ssh root@…` and password logins → `Permission denied (publickey)`; key login works.

### 4.6 Swap (safety net for the 8 GB budget)

```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf && sudo sysctl --system
```

📸 Snapshot `01-hardened`.

---

## 5. The VPN to HQ (critical path)

### 5.0 ✅ FINAL SETUP (built + failover-tested 2026-10-27) — read this first

WireGuard turned out to be **filtered between the office and the datacenter in both directions**
(ICMP and plain UDP pass, WireGuard handshakes never arrive — DPI-style VPN filtering). The
production design is therefore:

| Role | Tunnel | VPS address | Router address | Notes |
|---|---|---|---|---|
| **Primary** | **ZeroTier** network `8d1c312afae365aa` (ElRezeiky-HQ-Zerotier, controller my.zerotier.com) | `10.50.50.77` (node `869b7a6010`, iface `ztu7tnet2q`) | `10.50.50.1` (`ZT-ELREZEIKY-HQ`) | approved + fixed IP in ZeroTier Central; Central pushes **no** office routes |
| **Backup** | **SSTP** to `41.32.31.187:443` (same VPN as the branches) | `10.0.0.77` (iface `sstp-hq`) | `10.0.0.1` | router PPP secret `elrezeiky-vps`; VPS pins the router CA `myCA` (`/etc/ppp/sstp-hq-ca.pem`, valid to 2033); router leaf `vpn-cert` **expires 2027-03-14** |
| Dormant | WireGuard (`wg-vps` / `wg0`, sections 5.1–5.3 below) | 10.77.0.1 | 10.77.0.2 | kept **disabled** pending the LDC ticket |

**VPS pieces**
- `zerotier-one` (installed with ZeroTier's GPG-signed installer; joined + authorised).
- SSTP: `apt install sstp-client` (**with `APT::Install-Recommends "false"`** — otherwise it drags in
  NetworkManager + 120 desktop packages; purge them if that happened), `/etc/ppp/peers/sstp-hq`,
  `/etc/ppp/chap-secrets` (`elrezeiky-vps sstp-hq "<password>" *`, chmod 600), systemd
  `elrezeiky-sstp.service` (`pppd call sstp-hq nodetach`, Restart=always).
- Failover: `/usr/local/sbin/elrezeiky-tunnel-watch` + `elrezeiky-tunnel-watch.service`. Every 20 s:
  ZeroTier gateway answers → office routes (192.168.1/3/4/30/70) `via 10.50.50.1`; else SSTP
  answers → `dev sstp-hq`; routes re-applied every cycle; switches logged
  (`sudo journalctl -t elrezeiky-tunnel`). Tested: ZeroTier stopped → SSTP in < 1 min, all
  SOFTECH + PBX reachable; ZeroTier started → back to ZeroTier.

**Router pieces** (on top of 5.2 c/e/f/g)
- Address list `elrezeiky-vps-sources` = 10.50.50.77 + 10.0.0.77; the `VPS:` filter rules, the NAT
  rule and the two MSS rules match **`src/dst-address-list=elrezeiky-vps-sources`**, not an
  interface (ZeroTier is shared with staff members — rules must key on the VPS's own IPs).
- `/32` route `41.196.0.34 via 41.32.31.177` (static WAN2) — **required** so SSTP replies leave on
  the same line the VPS connected to.
- PPP secret `elrezeiky-vps` (profile default-encryption, local 10.0.0.1, remote 10.0.0.77).
- Netwatch host 10.50.50.77.
- Router backups: before-wireguard, after-wireguard, after-wireguard-2, after-zerotier-rules,
  after-tunnels-final.

**Known branch-side issue (not the VPS):** Ain Shams 192.168.3.0/24 is routed by the HQ router via
the old WireGuard `wg0` (distance 1, dead) instead of its live SSTP (10.0.0.4, distance 5) — fix
with a failover-capable route on the router.

IT-OPS summary for WhatsApp: `scratch/IT_OPS_server_handover_whatsapp.txt` (git-ignored).

---

*Sections 5.1–5.3 below are the original WireGuard design — kept for reference / re-activation.*

WireGuard: the VPS is the "server" with the public IP; the **HQ MikroTik router** (RouterOS 7)
dials out to it and forwards traffic to the SOFTECH servers, **src-NATting it to the router's
HQ LAN address** so the Sybase servers and branch routers need no route changes.

Tunnel subnet: `10.77.0.0/24` (VPS = .1, HQ MikroTik = .2, your laptop = .10 later).

> **Check for an address clash first.** On the VPS run `ip -4 addr; ip route`. If LDC's own
> network uses any of 192.168.1/3/4/30/70.x, tell me — we'd need a different approach (NAT
> 1:1 `netmap` on the MikroTik).

### 5.1 On the VPS

**a) Keys** (the private key never leaves a root-only file):
```bash
sudo apt -y install wireguard
sudo sh -c 'umask 077; wg genkey > /etc/wireguard/vps.key; wg pubkey < /etc/wireguard/vps.key > /etc/wireguard/vps.pub'
sudo cat /etc/wireguard/vps.pub
```
✅ Done 2026-10-27 — VPS public key: **`kkgyLB4fzSxvm6+rGLuVd5WKy9SRkE00tHk4bNbQCxY=`**
(goes into the MikroTik peer, 5.2 b). Router `wg-vps` public key (5.2 b, 2026-10-27): **`WakFF0PGtz4rgpaWxApt5/4uxU2+5MBkhWXUILQWiW4=`** (router listen-port 55748, it dials out).

**b) Config** — after 5.2 b has given you the router's public key. The private key is loaded
from its file by `PostUp`, so it is never pasted into the config:
```bash
sudo tee /etc/wireguard/wg0.conf >/dev/null <<'EOF'
[Interface]
Address    = 10.77.0.1/24
ListenPort = 51820
PostUp     = wg set %i private-key /etc/wireguard/vps.key

# HQ MikroTik «Bab El Haded HQ» — carries HQ (incl. PBX) + the 4 branch subnets
[Peer]
PublicKey  = ROUTER_PUBLIC_KEY
AllowedIPs = 10.77.0.2/32, 192.168.1.0/24, 192.168.3.0/24, 192.168.4.0/24, 192.168.30.0/24, 192.168.70.0/24
EOF
sudo sed -i 's|ROUTER_PUBLIC_KEY|<paste the router public-key here>|' /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/wg0.conf
sudo systemctl enable --now wg-quick@wg0
sudo wg show
```
Subnets = the networks of every Branch `db_host` (192.168.1/3/4/30/70); the PBX
(192.168.1.155) is inside 192.168.1.0/24.

### 5.2 On the HQ MikroTik router (RouterOS 7)

The HQ MikroTik already routes HQ ↔ branches (that's how the office PC reaches every branch's
Sybase today). It becomes the HQ end of the tunnel: it **dials out** to the VPS, so no port
forwarding, no static public IP, and no change on the branch routers.

Work in **WinBox → New Terminal** (or SSH to the router). Press **Ctrl+X** first to enter
**Safe Mode**: if a mistake cuts your connection, the router undoes the changes by itself.
Press Ctrl+X again at the end to keep them.

#### a) Check the version and take a backup

```routeros
/system resource print            # confirmed 7.24.5 stable — no upgrade needed
/export file=before-wireguard     # readable config copy (Files menu)
/system backup save name=before-wireguard
```
Download both files from **Files** to your PC (the router has 78 MB free flash — plenty).

Confirm the tunnel subnet is free (both must print nothing — see 1.3; ✅ both were empty on 2026-10-26):
```routeros
/ip address print without-paging where address~"10.77."
/ip route print where dst-address~"10.77."
/interface wireguard print        # existing: wg0, wg-mobile, wg-Mohsen-Backup → "wg-vps" is free
```

#### b) Create the tunnel

```routeros
/interface wireguard add name=wg-vps mtu=1420 comment="ElRezeiky VPS tunnel"
/interface wireguard print detail where name=wg-vps     # copy public-key → VPS wg0.conf [Peer] PublicKey
/ip address add address=10.77.0.2/24 interface=wg-vps comment="ElRezeiky VPS tunnel"
/interface wireguard peers add interface=wg-vps comment="ElRezeiky VPS" \
    public-key="<content of /etc/wireguard/vps.pub>" \
    endpoint-address=41.196.0.34 endpoint-port=51820 \
    allowed-address=10.77.0.0/24 persistent-keepalive=25s
```
RouterOS generates the router's private key itself; it never leaves the router. The route to
10.77.0.0/24 appears automatically from the address. `persistent-keepalive` keeps the tunnel
alive through the ISP's NAT.

Now put the router's public key into the VPS `/etc/wireguard/wg0.conf` (`[Peer] PublicKey`) and
on the VPS: `sudo systemctl restart wg-quick@wg0`.

#### c) Say exactly what the VPS may reach (address list)

Only the SOFTECH servers and the PBX — not the whole office network:
```routeros
/ip firewall address-list
add list=elrezeiky-vps-targets address=192.168.1.8    comment="SOFTECH HQ"
add list=elrezeiky-vps-targets address=192.168.1.5    comment="SOFTECH Ramsis Sq, Bab ElHadid"
add list=elrezeiky-vps-targets address=192.168.3.10   comment="SOFTECH Ain Shams, Ahmed Esmat St"
add list=elrezeiky-vps-targets address=192.168.30.12  comment="SOFTECH ElNozha ElGedida #2 ElAdib"
add list=elrezeiky-vps-targets address=192.168.4.11   comment="SOFTECH Giza Sq, 3 Mourad St"
add list=elrezeiky-vps-targets address=192.168.70.14  comment="SOFTECH ElGeish Sq, Abbasia"
add list=elrezeiky-vps-targets address=192.168.1.155  comment="Issabel PBX (AMI 5038, CDR 3306, recordings 22)"
```
Addresses taken 2026-10-27 from the Branch table (`db_host`, all port 5000), `SYBASE_HOST`
and `AMI_HOST` / `ISSABEL_CDR_HOST` in the office `.env`. If a branch server changes address,
update both this list and the Branch table.

#### d) Firewall — allow only those ports, from the tunnel

```routeros
/ip firewall filter
add chain=forward in-interface=wg-vps dst-address-list=elrezeiky-vps-targets protocol=tcp dst-port=5000 action=accept comment="VPS: Sybase SOFTECH"
add chain=forward in-interface=wg-vps dst-address-list=elrezeiky-vps-targets protocol=tcp dst-port=5038,3306,22 action=accept comment="VPS: Issabel AMI / CDR / recordings"
add chain=forward in-interface=wg-vps protocol=icmp action=accept comment="VPS: ping"
add chain=forward in-interface=wg-vps action=drop comment="VPS: nothing else on the LAN"
add chain=input   in-interface=wg-vps protocol=icmp action=accept comment="VPS: ping router"
add chain=input   in-interface=wg-vps action=drop comment="VPS: may not manage the router"
```
New rules land at the **bottom** of the list, and RouterOS reads top-down. Open **IP → Firewall →
Filter Rules** in WinBox and **drag these six rules (keeping their order) above the first
`drop` rule** of the existing config. Check with `/ip firewall filter print` that the four
`forward` rules come before any forward drop, and the two `input` rules before any input drop.

Even if the VPS were ever compromised, it can only talk to Sybase/PBX ports — never to staff
PCs, cameras or the router's admin.

#### e) NAT — make VPS traffic look like it comes from the HQ router

```routeros
/ip firewall nat add chain=srcnat src-address=10.77.0.0/24 dst-address-list=elrezeiky-vps-targets \
    action=src-nat to-addresses=192.168.1.201 place-before=0 comment="VPS -> SOFTECH/PBX as HQ router"
```
Why `src-nat` to the HQ LAN address (and not plain masquerade), and why at the top:
- Branch routers and branch Sybase servers already know how to answer HQ addresses (that's how
  the office PC on 192.168.1.x reaches them over the SSTP / ZeroTier links today) — they need
  no new route for 10.77.0.0/24, and nothing changes on the branch side.
- If HQ↔branch links are **IPsec** with policies like "HQ subnet ↔ branch subnet", the traffic
  must carry an HQ source address to match those policies (RouterOS checks IPsec policies after
  src-nat). Masquerade on a WAN rule could pick the wrong address and the packets would leak to
  the internet unencrypted or be dropped.
- `place-before=0` keeps it above the default WAN masquerade rule.

The Sybase / Issabel servers will see connections from `192.168.1.201`. If any of them restricts
clients by IP, allow that address (section 1.3).

#### f) MSS clamp (prevents "large queries hang" over the tunnel)

```routeros
/ip firewall mangle
add chain=forward in-interface=wg-vps  protocol=tcp tcp-flags=syn action=change-mss new-mss=clamp-to-pmtu passthrough=yes comment="VPS tunnel MSS"
add chain=forward out-interface=wg-vps protocol=tcp tcp-flags=syn action=change-mss new-mss=clamp-to-pmtu passthrough=yes comment="VPS tunnel MSS"
```
Sybase result sets are big. Without this, small queries work but big syncs freeze mid-transfer
when the WAN is PPPoE or has a smaller MTU. If you still see hangs, lower `mtu` on `wg-vps`
(and on the VPS: `MTU = 1380` under `[Interface]`) to 1380.

#### f2) Send VPS traffic out the static line (ether1) — needed at Bab El Haded HQ

Found 2026-10-27: the default route is **WAN1-Primary via 192.168.2.1** (ether2, behind the
ISP box) and the tunnel knocks sent that way **never reached the VPS** (router `tx` grew,
`rx=0`, VPS `tcpdump` empty). WAN2 is the static **41.32.31.187** via **41.32.31.177**. Pin
only the VPS address to WAN2; `check-gateway=ping` falls back to the default route if WAN2
is down:
```routeros
/ip route add dst-address=41.196.0.34/32 gateway=41.32.31.177 check-gateway=ping distance=1 comment="ElRezeiky VPS via WAN2 static 41.32.31.187"
```
Side benefit: the VPS always sees the office as 41.32.31.187, so UDP 51820 (and later SSH) can
be limited to that address in `ufw`.

> **Two RouterOS traps met on 2026-10-27:**
> - **Safe Mode** undoes everything since it was switched on if the WinBox session drops
>   (e.g. ZeroTier on the PC disconnected) — the six `VPS:` filter rules were lost that way.
>   Leave Safe Mode with **Ctrl+X** as soon as a block of commands is done.
> - `move … destination=0` uses the numbers of the **last full `print`**, not the current list —
>   it put the rules in reverse order. Position rules with `place-before=[find where comment=…]`
>   or `destination=[find …]` instead, and check the real order with
>   `:foreach i in=[/ip firewall filter find where comment~"^VPS: "] do={:put ([/ip firewall filter get $i chain] . "  " . [/ip firewall filter get $i comment])}`

#### g) Watch the tunnel

```routeros
/tool netwatch add host=10.77.0.1 interval=1m comment="ElRezeiky VPS tunnel" \
    down-script=":log error \"ElRezeiky VPS tunnel DOWN\"" up-script=":log info \"ElRezeiky VPS tunnel UP\""
```
If the router has e-mail configured (`/tool e-mail`), add `/tool e-mail send …` to the
down-script so you get an alert.

Press **Ctrl+X** to leave Safe Mode and keep the changes, then save a fresh backup:
`/system backup save name=after-wireguard`.

#### h) Check from the router

```routeros
/interface wireguard peers print detail     # "last-handshake" a few seconds ago, rx/tx growing
/ping 10.77.0.1 count=3                     # the VPS
```

### 5.3 Prove the tunnel from the VPS

```bash
sudo wg show                                  # "latest handshake: x seconds ago"
ping -c3 10.77.0.2                            # gateway
nc -vz 192.168.1.8 5000                       # SOFTECH HQ Sybase
for h in <each branch db_host>; do nc -vz -w3 $h 5000; done
```
Every branch must answer "succeeded". If one fails, it's routing from HQ to that branch or the
branch firewall — fix it at the network level, not in the app. Where to look on the MikroTik:

| Symptom | Check on the router |
|---|---|
| No handshake | `/interface wireguard peers print detail` — wrong public key on either side, wrong `endpoint-address`, or UDP 51820 not open on the VPS (`sudo ufw status`) |
| Handshake OK, `ping 10.77.0.2` fails | input rules: the two `VPS:` input rules must sit above the input drop |
| Router answers, SOFTECH doesn't | forward rules above the forward drop? address missing from `elrezeiky-vps-targets`? NAT rule at the top? Watch counters: `/ip firewall filter print stats where comment~"VPS"` and `/ip firewall nat print stats` |
| HQ works, one branch doesn't | `/tool torch interface=wg-vps` while running `nc` — packets leave toward the branch? Branch tunnel/IPsec up? Branch Sybase allows `192.168.1.201`? |
| Small queries work, syncs freeze | MSS clamp (5.2 f), then MTU 1380 |

Latency matters: syncs are chatty. `ping 192.168.1.8` from the VPS should be under ~40 ms
(the office diagnostic measured 39 ms TCP on the LAN). Slow branches already get the tiered
fast/slow sync.

📸 Snapshot `02-vpn-ok`.

---

## 6. Install the runtime stack

```bash
sudo apt -y install python3.12 python3.12-venv python3.12-dev python3-pip \
    postgresql-16 postgresql-contrib-16 postgresql-client-16 \
    redis-server nginx \
    openjdk-11-jre-headless \
    tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng tesseract-ocr-osd \
    libpq-dev libjpeg-dev zlib1g-dev libgl1 libglib2.0-0 libgomp1 \
    netcat-openbsd
# nginx's "Welcome" page must not be public until our site is configured (§9):
sudo rm -f /etc/nginx/sites-enabled/default && sudo systemctl reload nginx
```
(The server has `APT::Install-Recommends "false"` — so `tesseract-ocr-osd` / `-eng` are listed
explicitly; nothing else from the "recommended" lists is needed.)

- **Java 11** = the same JVM the office machine uses (Temurin 11); `libs/jconn3.jar` is tested
  with it. JPype finds it automatically; if not, set `JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64`
  in `.env`.
- **Tesseract + Arabic** for local invoice OCR (`TESSERACT_CMD=/usr/bin/tesseract`).
- **Redis** is needed because the scheduler is a separate process: without a shared channel
  layer, notifications created by scheduled jobs never reach the browser over WebSocket.
  `channels-redis` is in `requirements.txt`; settings switch to it when `REDIS_URL` is set.

Redis: keep it local-only (default on Ubuntu: `bind 127.0.0.1 ::1`). Verify:
```bash
sudo systemctl enable --now redis-server && redis-cli ping     # PONG
```

Node.js **24 LTS** (Node 20 reached end-of-life in April 2026; 24 also matches the office PC) —
to build the React frontend and for Vite + Claude Code in the workbench. Signed apt repo, no
`curl | bash`:
```bash
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt update && sudo apt -y install nodejs
node -v && npm -v
```

---

## 7. PostgreSQL

### 7.1 Users and databases

```bash
sudo -u postgres psql <<'SQL'
CREATE USER elrezeiky;
CREATE DATABASE elrezeiky_db OWNER elrezeiky ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8' TEMPLATE template0;
-- the workbench login (section 13): reads production, writes nothing there,
-- may create the throw-away test_* database the Django test runner needs
CREATE USER elrezeiky_work CREATEDB;
ALTER ROLE elrezeiky_work IN DATABASE elrezeiky_db SET default_transaction_read_only = on;
REVOKE ALL ON DATABASE elrezeiky_db FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE elrezeiky_db TO elrezeiky;
SQL
```
Passwords are typed at a hidden prompt (never on the command line, so they are not kept in
`~/.bash_history` and never pasted into a chat):
```bash
sudo -u postgres psql -c '\password elrezeiky'
sudo -u postgres psql -c '\password elrezeiky_work'
```
The read grants for `elrezeiky_work` (incl. CONNECT) are given in section 13.2, after the data
is restored. Its real guard is those **SELECT-only grants**; `default_transaction_read_only` is
a second layer (a session could switch it off, the grants it cannot).

Extensions the app uses (pg_trgm for item/customer search):
```bash
sudo -u postgres psql -d elrezeiky_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
sudo -u postgres psql -d template1    -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"   # so test DBs get it too
```

### 7.2 Listen on localhost only

`/etc/postgresql/16/main/postgresql.conf` → `listen_addresses = 'localhost'` (the default).

### 7.3 Tune for 8 GB shared with everything else

Ubuntu's `postgresql.conf` already reads every file in `conf.d/`, so our settings live in one
file of our own (package upgrades never touch it):
```bash
sudo tee /etc/postgresql/16/main/conf.d/elrezeiky.conf >/dev/null <<'EOF'
shared_buffers = 1536MB                 # leaves room for local OCR (raise to 4GB on a 16 GB plan)
effective_cache_size = 3GB
work_mem = 32MB
maintenance_work_mem = 512MB
max_connections = 100
random_page_cost = 1.1
checkpoint_completion_target = 0.9
wal_compression = on
max_wal_size = 4GB
timezone = 'Africa/Cairo'
log_min_duration_statement = 2000      # log queries slower than 2 s
EOF
sudo systemctl restart postgresql
sudo -u postgres psql -Atc "SELECT name, setting, unit FROM pg_settings WHERE name IN ('shared_buffers','effective_cache_size','work_mem','listen_addresses','TimeZone')"
```
(`shared_buffers` is shown in 8 kB pages: 196608 = 1536 MB.)

---

## 8. Application code + production `.env`

### 8.1 App user and code

```bash
sudo useradd -r -m -s /bin/bash -d /opt/elrezeiky elrezeiky
sudo -u elrezeiky ssh-keygen -t ed25519 -C "elrezeikyerp.dawalvry.com deploy" -f /opt/elrezeiky/.ssh/id_ed25519 -N ""
sudo cat /opt/elrezeiky/.ssh/id_ed25519.pub
```
GitHub → repo → Settings → **Deploy keys** → Add (read-only) with that public key. Then:
```bash
sudo -u elrezeiky git clone git@github.com:bassemwolsely94/SoftechReservationModule.git /opt/elrezeiky/app
```

> Layout note: `deploy/DEPLOY.md` and the systemd units assume the code IS `/opt/elrezeiky`.
> Here the code goes in `/opt/elrezeiky/app` so the home folder (keys, venvs, backups) stays
> outside the repo. The paths in sections 9.1 and 9.2 are adjusted accordingly.

```bash
cd /opt/elrezeiky/app
sudo -u elrezeiky git checkout main
sudo -u elrezeiky python3.12 -m venv /opt/elrezeiky/venv
sudo -u elrezeiky /opt/elrezeiky/venv/bin/pip install --upgrade pip wheel
# CPU-only torch first, or easyocr drags in ~3 GB of CUDA libraries:
sudo -u elrezeiky /opt/elrezeiky/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
sudo -u elrezeiky /opt/elrezeiky/venv/bin/pip install -r requirements.txt
sudo -u elrezeiky mkdir -p logs media backups
```
This installs every in-app local OCR engine: Tesseract bindings, RapidOCR (ONNX), EasyOCR
(torch, CPU) and the PDF renderer. PaddleOCR gets its own venv (section 8.4).
`faster-whisper` installs too but stays off (`WHISPER_ENABLED=False`) on 8 GB.

### 8.2 Production `.env` — FIRST BOOT IS READ-ONLY

```bash
sudo -u elrezeiky cp deploy/staging.env.example .env
sudo -u elrezeiky nano .env
chmod 600 .env
```
Start from the **staging** template on purpose: SOFTECH kill-switch ON and every writer OFF.
You flip them to the office values only at cutover (section 11). Fill in:

```env
DEBUG=False
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_urlsafe(50))">
ALLOWED_HOSTS=elrezeikyapp.dawalvry.com,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://elrezeikyapp.dawalvry.com
FRONTEND_BASE_URL=https://elrezeikyapp.dawalvry.com
BEHIND_HTTPS_PROXY=True
SCHEDULER_AUTOSTART=False
MEDIA_ACCEL_REDIRECT=True
RBAC_ENFORCEMENT=log                # same as office today; 'enforce' once the rbac log is quiet
REDIS_URL=redis://127.0.0.1:6379/0

PG_NAME=elrezeiky_db
PG_USER=elrezeiky
PG_PASSWORD=<prod password from 7.1>
PG_HOST=localhost
PG_PORT=5432

SOFTECH_READ_ONLY=True              # ← stays True until cutover step 11.6
SYBASE_HOST=192.168.1.8             # reached through the VPN
SYBASE_PORT=5000
SYBASE_USER=<from office .env>
SYBASE_PASSWORD=<from office .env>
SOFTECH_PROFILE=<from office .env>
SOFTECH_BRANCH_HOST_OVERRIDE=       # EMPTY in production → real branch hosts from the Branch table

OMNI_CREDENTIALS_KEY=<the SAME value as the office — see 1.2>
WHISPER_ENABLED=False               # RAM budget (True only on a 16 GB plan)
# WhatsApp / Meta / AMI / Issabel / VAPID: copy from office, but keep WhatsApp/AMI EMPTY until cutover

# ── Local OCR (section 8.4) ──
TESSERACT_CMD=/usr/bin/tesseract
TESSERACT_TESSDATA_PREFIX=          # empty → the project's ocr_tessdata/ (copied in 8.4)
OMP_THREAD_LIMIT=1                  # one CPU per Tesseract page, so OCR can't freeze the screens
PADDLE_OCR_URL=http://127.0.0.1:8077/boxes
INVOICE_OCR_ENGINE=auto             # local first; Gemini only for pages local OCR reads badly
#INVOICE_OCR_ENGINE=tesseract       # ← 100% local: no page ever leaves the server
INVOICE_OCR_ESCALATE_THRESHOLD=0.6
GEMINI_API_KEY=<from office>        # leave EMPTY to forbid any cloud OCR
```

Never copy Windows paths (`C:\…`) from the office `.env` — JVM path, Tesseract path, tessdata
must be the Linux ones above or empty.

### 8.3 Sanity check (no data yet)

```bash
cd /opt/elrezeiky/app
sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py check --deploy
sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py test_sybase_vps       # NO --write flag
```
`test_sybase_vps` checks: JPype, JVM, jconn3.jar, TCP to Sybase through the VPN, driver load,
JDBC login. All must PASS. (Its write dry-run option is refused anyway while
`SOFTECH_READ_ONLY=True` — don't use it.)

### 8.4 Local OCR on the server

What runs where:

| Engine | Where it runs | Used for | RAM |
|---|---|---|---|
| **Tesseract** (+ Arabic) | a short `tesseract` process per page, started by the web app | default free engine for supplier invoices (`auto` tries it first) | 0.2–0.4 GB per page, then freed |
| **RapidOCR** (ONNX) | inside the web process | invoice-bundle page splitting; optional price "field voting" (`INVOICE_OCR_FIELD_VOTING`) | ~0.3 GB |
| **PaddleOCR** | its own service `elrezeiky-ocr` on 127.0.0.1:8077 (own Python venv) | `paddleocr` engine — better boxes for some vendors (PharmaOverseas) | 1–1.5 GB, capped at 2 GB |
| **EasyOCR** (torch) | inside the web process, model kept loaded after first use | only when someone explicitly picks `easyocr` | +1.5–2 GB — keep for the 16 GB plan |

OCR jobs run in background threads of the web process (single uploads and bundles), so they
compete with branch users for CPU. The settings below keep them polite.

#### a) Tesseract language data

The app reads Arabic best with the project's own `ocr_tessdata/` (ara + eng + osd, the full
"tessdata" models — better than Ubuntu's small `tesseract-ocr-ara` package). It is
git-ignored, so copy it from the office PC:
```bash
# office PC (PowerShell, in the project folder)
scp -r ocr_tessdata bassemwolsely94@41.196.0.34:/tmp/ocr_tessdata
# VPS
sudo rsync -a /tmp/ocr_tessdata/ /opt/elrezeiky/app/ocr_tessdata/ && sudo chown -R elrezeiky:elrezeiky /opt/elrezeiky/app/ocr_tessdata
TESSDATA_PREFIX=/opt/elrezeiky/app/ocr_tessdata tesseract --list-langs     # ara, eng, osd
```
With `TESSERACT_TESSDATA_PREFIX` empty, `apps/invoices/engines.py` uses that folder by itself.

#### b) PaddleOCR sidecar (its own venv + service)

`ocr_sidecar/` pins the PaddleOCR 2.x stack (paddlepaddle 2.6.2 + paddleocr 2.7.3, numpy 1.x),
which clashes with the app's own packages — so it gets a separate venv, exactly as on Windows.
Ubuntu 24.04's Python 3.12 is supported.
```bash
sudo -u elrezeiky python3.12 -m venv /opt/elrezeiky/ocr-venv
sudo -u elrezeiky /opt/elrezeiky/ocr-venv/bin/pip install --upgrade pip
sudo -u elrezeiky /opt/elrezeiky/ocr-venv/bin/pip install -r /opt/elrezeiky/app/ocr_sidecar/requirements.txt
# first start downloads the Arabic models into /opt/elrezeiky/.paddleocr — do it once by hand:
cd /opt/elrezeiky/app/ocr_sidecar && sudo -u elrezeiky /opt/elrezeiky/ocr-venv/bin/python server.py
#   (wait for "serving on 127.0.0.1:8077", then Ctrl+C)
```
`sudo nano /etc/systemd/system/elrezeiky-ocr.service`:
```ini
[Unit]
Description=ElRezeiky — PaddleOCR box sidecar (local OCR)
After=network.target

[Service]
Type=simple
User=elrezeiky
Group=elrezeiky
WorkingDirectory=/opt/elrezeiky/app/ocr_sidecar
Environment=PADDLE_HOST=127.0.0.1
Environment=PADDLE_PORT=8077
Environment=OMP_NUM_THREADS=2
ExecStart=/opt/elrezeiky/ocr-venv/bin/python server.py
Restart=always
RestartSec=10
# Keep OCR from starving the web app and PostgreSQL on the 8 GB / 4 vCPU plan
MemoryHigh=1536M
MemoryMax=2G
CPUQuota=200%
Nice=10
SyslogIdentifier=elrezeiky-ocr

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now elrezeiky-ocr
curl -s http://127.0.0.1:8077/health          # {"ok": true, "lang": "arabic"}
```
If paddle is ever killed by `MemoryMax`, systemd restarts it and the app falls back to the
other engines for that page. On a 16 GB plan raise `MemoryMax` to 4G and `CPUQuota` to 400%.

> The sidecar code asks for PP-OCRv5 but the pinned 2.x stack provides PP-OCRv3 Arabic
> (README: the 2.x pin was chosen because 3.x crashes on **Windows** CPU). On Linux the 3.x
> stack with PP-OCRv5 may work and reads Arabic better — that is a later, separate benchmark
> experiment, not part of go-live.

#### c) Warm up and prove each engine

```bash
cd /opt/elrezeiky/app
sudo -u elrezeiky /opt/elrezeiky/venv/bin/python -c "import easyocr; easyocr.Reader(['ar','en'], gpu=False)"   # downloads EasyOCR models once (~100 MB)
sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py shell -c "from apps.invoices import engines; print(engines.available_engines())"
```
The list must include `tesseract`, `paddleocr` and `easyocr`. Then, after the data restore
(section 10), open `/invoices`, upload one real supplier invoice per main vendor and check that
the lines match — compare with what the office produced for the same invoice.

#### d) Which engine runs by default

- `INVOICE_OCR_ENGINE=auto` (today's office behaviour): Tesseract first, Gemini only for pages
  whose local result scores below `INVOICE_OCR_ESCALATE_THRESHOLD`.
- `INVOICE_OCR_ENGINE=tesseract` and `GEMINI_API_KEY` empty: **fully local** — no invoice image
  ever leaves the server, at the cost of more manual line review on poor scans.
- `paddleocr` / `easyocr` can be used for a single invoice through the re-run-OCR action
  (`POST /api/invoices/{id}/run-ocr/` accepts an `engine`) without changing the default.

---

## 9. Services, Nginx, TLS

### 9.1 systemd units (from `deploy/`, paths adjusted)

```bash
sudo cp deploy/elrezeiky-web.service       /etc/systemd/system/
sudo cp deploy/elrezeiky-scheduler.service /etc/systemd/system/
sudo sed -i 's#WorkingDirectory=/opt/elrezeiky#WorkingDirectory=/opt/elrezeiky/app#; s#EnvironmentFile=/opt/elrezeiky/.env#EnvironmentFile=/opt/elrezeiky/app/.env#' \
     /etc/systemd/system/elrezeiky-web.service /etc/systemd/system/elrezeiky-scheduler.service
sudo systemctl daemon-reload
sudo systemctl enable elrezeiky-web          # start it after the data restore (section 10)
# the scheduler is NOT enabled yet — only at cutover (section 11)
```
Add `After=redis-server.service zerotier-one.service elrezeiky-tunnel-watch.service` to both
`[Unit]` sections, so they start after Redis and the VPN on reboot. (Not `wg-quick@wg0`:
WireGuard is dormant and disabled — section 5.0.)

### 9.2 Nginx (from `deploy/nginx.conf`)

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/elrezeiky
sudo sed -i 's#YOUR_DOMAIN_OR_IP#elrezeikyapp.dawalvry.com#g; s#YOUR_DOMAIN#elrezeikyapp.dawalvry.com#g; s#/opt/elrezeiky/#/opt/elrezeiky/app/#g; s#root /opt/elrezeiky;#root /opt/elrezeiky/app;#' \
     /etc/nginx/sites-available/elrezeiky
sudo ln -s /etc/nginx/sites-available/elrezeiky /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
```
`/admin/` is limited to private ranges. Through the public name your request arrives from a
public address and is refused; over ZeroTier your laptop (a 10.50.50.x member, section 13.3) is
inside 10/8, so open Django admin at `https://10.50.50.77/admin/` (accept the name warning) —
admin works only via the VPN. Good.

Nginx needs to read static/media files: `sudo chmod 755 /opt/elrezeiky /opt/elrezeiky/app`.

### 9.3 TLS certificate (DNS must resolve first — section 3)

The config references certificates that don't exist yet, so Nginx won't start. Get them
with the standalone mode first:
```bash
sudo apt -y install certbot python3-certbot-nginx
sudo systemctl stop nginx
sudo certbot certonly --standalone -d elrezeikyapp.dawalvry.com -m <your e-mail> --agree-tos
sudo nginx -t && sudo systemctl enable --now nginx
sudo certbot renew --dry-run        # auto-renewal is installed as a systemd timer
```
Edit the cert paths if certbot names the folder `elrezeikyapp.dawalvry.com` (it will — matches the sed above).

### 9.4 Build the frontend

```bash
cd /opt/elrezeiky/app/frontend
sudo -u elrezeiky npm ci
sudo -u elrezeiky npm run build                # → ../staticfiles/frontend
cd .. && sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py collectstatic --noinput
```

📸 Snapshot `03-app-installed`.

---

## 10. Move the data (office PostgreSQL 16 → VPS)

Don't re-sync 8.5 GB from SOFTECH — copy the database. It holds everything SOFTECH doesn't:
reservations, demand, transfers, approvals, insurance claims, audit trail, gamification,
help edits, ISR history, idempotency keys. **A rehearsal first, the real copy at cutover.**

### 10.1 Rehearsal (now, while the office keeps running)

On the office PC (PowerShell; adjust the pg_dump path to your install):
```bash
& "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" -h localhost -U <office pg user> -Fc -Z 6 -f elrezeiky_rehearsal.dump elrezeiky_db
scp elrezeiky_rehearsal.dump bassemwolsely94@41.196.0.34:/tmp/
```
On the VPS:
```bash
sudo -u postgres pg_restore --no-owner --role=elrezeiky -d elrezeiky_db -j 4 /tmp/elrezeiky_rehearsal.dump
cd /opt/elrezeiky/app
sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py migrate      # applies anything newer than the office DB
sudo systemctl start elrezeiky-web
```
Media (uploads, 674 MB):
```bash
scp -r media bassemwolsely94@41.196.0.34:/tmp/media     # from the office folder; or zip first
sudo rsync -a /tmp/media/ /opt/elrezeiky/app/media/ && sudo chown -R elrezeiky:elrezeiky /opt/elrezeiky/app/media
```

### 10.2 Verify the rehearsal (still read-only, no scheduler)

From any browser: `https://elrezeikyapp.dawalvry.com`
- [ ] Login works; the 2FA roles still get their TOTP prompt.
- [ ] `/reservations`, `/demand`, `/transfers`, `/insurance`, `/supply` show office data.
- [ ] An uploaded prescription / invoice image opens (signed media + X-Accel works).
- [ ] Notifications bell connects (DevTools → WS `/ws/…` = 101 Switching Protocols).
- [ ] `/sync` page: run ONE manual read-only sync (e.g. items for one branch) → succeeds over the VPN.
- [ ] Data-freshness bar shows the domains.
- [ ] `journalctl -u elrezeiky-web -n 200` has no tracebacks.
- [ ] `/help` loads (help content ships with the code).
- [ ] Local OCR: upload one real supplier invoice → lines appear (Tesseract), and re-run it with `paddleocr` → works; compare with the office result.
- [ ] Try something a writer would do (e.g. push a POS order) → it is **refused** by the kill-switch. That's correct now.

Fix anything found, then repeat 10.1 if needed. The rehearsal DB is thrown away at cutover.

---

## 11. Cutover day — office → VPS (ordered, no step skipped)

Pick a quiet window (e.g. after closing, ~1–2 hours). Announce to branches that the system
is down during the window and that the new address is `https://elrezeikyapp.dawalvry.com`.

> The order exists to make a double post to SOFTECH impossible. Don't reorder.

**11.1 Freeze the office writers.** In the office `.env` set `SOFTECH_READ_ONLY=True`, restart
the office web + scheduler. From now on the office machine cannot write to SOFTECH.

**11.2 Drain what's in flight — checked on the office instance:**
- `/api/pos-orders/queue-status/` → queued / push_failed must be **0**. If not, temporarily
  undo 11.1, flush (`flush_pos_orders`), confirm 0, redo 11.1.
- No ISR / invoice / A/P / insurance pushes in "pushing" state. Review open ISR drafts — memory
  notes **duplicate live ISR drafts #30/#32 of already-pushed #29**: cancel those duplicates
  before migrating so they can never be pushed from the new server.
- Note the last successful run time of each sync domain (freshness bar) — compare after the move.

**11.3 Stop the office instance completely.** Stop the office scheduler and web server, and
disable anything that starts them automatically (`install_service.bat` service, Task Scheduler
entries, `start_server.bat` in Startup). Confirm in Task Manager: no `python.exe … run_scheduler`.

**11.4 Final dump + restore.**
```bash
# office
& "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" -h localhost -U <user> -Fc -Z 6 -f elrezeiky_cutover.dump elrezeiky_db
scp elrezeiky_cutover.dump bassemwolsely94@41.196.0.34:/tmp/
# VPS
sudo systemctl stop elrezeiky-web
sudo -u postgres dropdb elrezeiky_db
sudo -u postgres createdb -O elrezeiky -E UTF8 -T template0 elrezeiky_db
sudo -u postgres psql -d elrezeiky_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
sudo -u postgres pg_restore --no-owner --role=elrezeiky -d elrezeiky_db -j 4 /tmp/elrezeiky_cutover.dump
cd /opt/elrezeiky/app && sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py migrate
sudo rsync -a --delete <fresh media copy>/ /opt/elrezeiky/app/media/
sudo -u postgres vacuumdb --analyze-in-stages -d elrezeiky_db
```

**11.5 Start the VPS, still read-only, now WITH the scheduler.**
```bash
sudo systemctl start elrezeiky-web
sudo systemctl enable --now elrezeiky-scheduler
journalctl -u elrezeiky-scheduler -f          # watch the jobs register and the first syncs run
```
Watch one full sync cycle succeed (sales, stock, in-transit, expiry, …) on the freshness bar.

**11.6 Turn SOFTECH writes back on — one writer at a time.** In the VPS `.env`:
1. `SOFTECH_READ_ONLY=False`
2. Set each `*_ENABLED` flag to its **office value** from your inventory (1.2) — no more than the
   office had. Recommended order, verifying each with a real transaction and a SOFTECH read-back
   before the next: POS writer → POS cancel log → discount/pricing → ISR (+auto-approve) →
   coverage → invoices → A/P (still OFF — it was gated OFF in the office) → insurance → shortage →
   loyalty/others.
3. `sudo systemctl restart elrezeiky-web elrezeiky-scheduler` after each change.

**11.7 External channels.** Put the WhatsApp / Meta / AMI / Issabel / VAPID values into the VPS
`.env`, restart, then:
- Meta developer console → WhatsApp → Configuration → Webhook URL
  `https://elrezeikyapp.dawalvry.com/api/whatsapp/webhook/` (same verify token). Same for
  Messenger/Instagram/Telegram webhooks under `/api/social/…`.
- AMI bridge: Issabel must allow AMI logins from the HQ router's LAN IP (src-NAT, section 5.2 e). Check
  `/pbx/live` shows calls.
- Web Push: users may need to re-enable notifications once (new origin = new subscription).
- `FRONTEND_BASE_URL` makes WhatsApp/portal links point at the new domain.

**11.8 Users.** Branches open `https://elrezeikyapp.dawalvry.com` (bookmark it, install as home-screen
app on phones — `/m` mobile pages). Old LAN addresses no longer work. Remove the old office
bookmarks.

**11.9 Keep the office copy as a cold fallback** for 2 weeks: data intact, `SOFTECH_READ_ONLY=True`,
services disabled. Rollback = reverse 11.3–11.6 (stop VPS scheduler+writers first, then start the office).

📸 Snapshot `04-live`.

---

## 12. Backups and monitoring (production)

### 12.1 Nightly database + media backup

```bash
sudo -u elrezeiky mkdir -p /opt/elrezeiky/backups
sudo -u elrezeiky crontab -e
```
```cron
# 02:30 nightly DB dump, keep 14 days
30 2 * * * pg_dump -h localhost -U elrezeiky -Fc -Z 6 elrezeiky_db -f /opt/elrezeiky/backups/db_$(date +\%F).dump && find /opt/elrezeiky/backups -name 'db_*.dump' -mtime +14 -delete
# 03:15 weekly media archive (Fridays), keep 4
15 3 * * 5 tar czf /opt/elrezeiky/backups/media_$(date +\%F).tgz -C /opt/elrezeiky/app media && find /opt/elrezeiky/backups -name 'media_*.tgz' -mtime +28 -delete
```
(Add `elrezeiky`'s password to `/opt/elrezeiky/.pgpass`, `localhost:5432:elrezeiky_db:elrezeiky:<pw>`, chmod 600.)

**Off-site copy is mandatory** — a backup on the same VPS dies with the VPS. Choose one:
- Pull nightly to an HQ machine over the VPN: `rsync -a elrezeiky@10.50.50.77:/opt/elrezeiky/backups/ D:\Backups\erp\` (via WSL/rsync or WinSCP scripting).
- Or SolidCP **Tools → Backup** for the whole space on a schedule (check the retention LDC gives you).
- Test a restore once a month: `createdb elrezeiky_restore_test` → `pg_restore` last night's dump into it → spot-check row counts → `dropdb elrezeiky_restore_test`. A backup you never restored is a hope, not a backup.

### 12.2 Monitoring

- Health at a glance: the in-app data-freshness bar + `/sync`.
- `journalctl -u elrezeiky-web -u elrezeiky-scheduler --since "1 hour ago" -p err`
- Disk: `df -h` (alert at 80%). RAM: `htop` / `free -h`.
- External uptime: free UptimeRobot / Better Stack ping of `https://elrezeikyapp.dawalvry.com/` every 5 min → e-mail/WhatsApp.
- VPN: if both tunnels are down, every sync fails. `sudo journalctl -t elrezeiky-tunnel` shows
  every ZeroTier ⇄ SSTP switch; `ip route get 192.168.1.8` shows which one carries traffic now.
  The MikroTik netwatch (host 10.50.50.77, 5.0) logs it on the router side; on the VPS add a cron
  `ping -c1 10.50.50.1 || ping -c1 10.0.0.1 || <alert>` if you want.
- Log rotation: app logs rotate themselves (`SafeTimedRotatingFileHandler`); journald is capped
  — set `SystemMaxUse=2G` in `/etc/systemd/journald.conf`.

### 12.3 Cockpit — point-and-click server admin (VPN only)

Cockpit is a free web panel from the Ubuntu/Red Hat world. In a browser you get:
- **Overview:** CPU, memory, swap, disk and network graphs, with history.
- **Services:** the status of `elrezeiky-web`, `elrezeiky-scheduler`, `elrezeiky-ocr`,
  PostgreSQL, Redis, Nginx and the VPN (`zerotier-one`, `elrezeiky-sstp`,
  `elrezeiky-tunnel-watch`), each with **Restart / Stop / Start** buttons and its own logs.
- **Logs:** every service's log in one place, filtered by service, time and errors only.
- **Terminal:** a server terminal inside the browser (for the runbook commands).
- **Accounts:** server users and passwords.

It is reachable **only through the VPN**, on `https://10.50.50.77:9090` (ZeroTier) or
`https://10.0.0.77:9090` (SSTP backup). It is never
open to the internet: the panel controls the whole server, so it gets the same protection as
Django admin.

#### a) Install (safe for Ubuntu Server networking)

```bash
sudo apt -y install --no-install-recommends cockpit cockpit-pcp
```
`--no-install-recommends` matters. Without it, apt also installs NetworkManager (for Cockpit's
"Networking" page), which can take over the server's network settings from netplan and cut the
VPS off after a reboot. We don't need that page, the Storage page, or Cockpit's "Software
updates" page (security updates already install themselves, section 4.5). `cockpit-pcp` adds
the history graphs ("what was the memory at 11:00 yesterday?").

#### b) Listen on the VPN address only

```bash
sudo mkdir -p /etc/systemd/system/cockpit.socket.d
sudo nano /etc/systemd/system/cockpit.socket.d/listen.conf
```
```ini
[Socket]
ListenStream=
ListenStream=10.50.50.77:9090
ListenStream=10.0.0.77:9090
FreeBind=yes
```
The empty `ListenStream=` removes the default "all addresses". `FreeBind=yes` lets Cockpit start
at boot even if ZeroTier or SSTP comes up a second later.
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cockpit.socket
sudo ss -ltnp | grep 9090        # must show 10.50.50.77:9090 + 10.0.0.77:9090 — NOT 0.0.0.0 or *
```

#### c) Firewall on the VPS

Open 9090 on the tunnel interfaces only, for your admin addresses. The ZeroTier network is
shared with other staff members, so allow **individual addresses**, never the whole 10.50.50.0/24:
```bash
sudo ufw allow in on ztu7tnet2q from <your laptop ZeroTier IP> to any port 9090 proto tcp
sudo ufw allow in on ztu7tnet2q from <office admin PC IP> to any port 9090 proto tcp
sudo ufw allow in on sstp-hq    from <office admin PC IP> to any port 9090 proto tcp
sudo ufw status numbered
```
Port 9090 is never opened on the public interface. If you try `https://<VPS public IP>:9090`
from outside, it must not answer.

#### d) Reaching it

| From | How |
|---|---|
| **Your laptop, anywhere** | ZeroTier connected (section 13.3) → `https://10.50.50.77:9090` |
| **An admin PC in the HQ office** | Goes through the MikroTik. Add one rule on the router (below). The PC's default gateway must be the MikroTik, or it needs a route `10.50.50.77/32 → 192.168.1.201` |

MikroTik rule for office admin PCs (only these addresses, only Cockpit and SSH):
```routeros
/ip firewall address-list
add list=elrezeiky-vps-admins address=<office admin PC IP> comment="may open Cockpit / SSH on the VPS"
/ip firewall filter
add chain=forward src-address-list=elrezeiky-vps-admins dst-address-list=elrezeiky-vps-sources protocol=tcp dst-port=9090,22 action=accept comment="Admins -> VPS Cockpit/SSH"
```
Drag it next to the other `VPS:` rules. Also check that the router's standard
**"accept established,related"** forward rule sits **above** the `VPS: nothing else on the LAN`
drop, so the VPS's replies come back. (In MikroTik's default config it is the first forward
rule; verify with `/ip firewall filter print where chain=forward`.)

#### e) Logging in

Cockpit uses the server's own user accounts and passwords. SSH stays key-only (section 4.3),
but Cockpit needs a password, so give your account a strong one:
```bash
sudo passwd bassemwolsely94
```
Log in as `bassemwolsely94` and click **"Turn on administrative access"** (top bar) to get the
Restart/Stop buttons. That asks for your password again; it's the same as `sudo`.

The browser will warn about the certificate the first time ("not private"): Cockpit uses its
own certificate for the VPN address. That's expected here. Accept it once on your PC.
(Optional extra: two-factor login for Cockpit with `libpam-google-authenticator`. The VPN plus a
strong password is enough to start.)

#### f) A restart-only account for the IT colleague (optional)

To let someone restart the platform without full server rights:
```bash
sudo adduser itops                    # no sudo group
sudo nano /etc/polkit-1/rules.d/50-elrezeiky-ops.rules
```
```javascript
// itops may start/stop/restart ONLY the ElRezeiky services — nothing else on the server
polkit.addRule(function (action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        subject.user == "itops" &&
        /^elrezeiky-(web|scheduler|ocr)\.service$/.test(action.lookup("unit"))) {
        return polkit.Result.YES;
    }
});
```
`itops` logs into Cockpit, sees the services and logs, and can restart the three ElRezeiky
services only. Nothing else.

#### g) What to click, and what not to

| Situation | In Cockpit |
|---|---|
| Screens show errors / site down | Services → `elrezeiky-web` → read the log → **Restart** |
| Data stopped refreshing (freshness bar old) | Services → `elrezeiky-scheduler` → log → **Restart** |
| Invoice OCR stuck / `paddleocr` unavailable | Services → `elrezeiky-ocr` → **Restart** |
| Server feels slow | Overview → memory/swap/CPU graphs; Services → sort by memory |
| Every sync failing | Services → `elrezeiky-tunnel-watch` (which tunnel is active) → `zerotier-one` / `elrezeiky-sstp` → log; then the MikroTik |

⚠ **Never** click **Stop** on `elrezeiky-scheduler` and leave it stopped without telling the
team: every sync and engine stops. **Never** start a scheduler anywhere else. **Restart**
`elrezeiky-web` only in a quiet moment: users are logged out for ~10 s. Cockpit's terminal
follows the same rule as everything else: **no hand edits in `/opt/elrezeiky/app`**.
Releases go through `release.sh` (13.5).

---

## 13. Developing on production (no separate development environment)

Owner decision (2026-10-26): **one environment — production**. No dev website, no dev
database, no second copy of the app running. Development continues on the production server.

### 13.1 What that means, and the guard for each risk

| Risk when developing on the live server | Guard in this runbook |
|---|---|
| A half-written change breaks the screens for every branch | Nobody edits `/opt/elrezeiky/app`. Code is written in the **workbench** (`/home/bassemwolsely94/work/app`); the live folder changes only through Git + `release.sh` (13.5) |
| A test, probe or script writes to SOFTECH | Workbench `.env`: `SOFTECH_READ_ONLY=True` + every writer `False` (the kill-switch refuses every INSERT/UPDATE/DELETE/EXEC) |
| A script or Claude Code changes live PostgreSQL data | The workbench logs in as **`elrezeiky_work`**: SELECT-only, and every transaction on `elrezeiky_db` is forced read-only. Tests run in their own throw-away `test_*` database |
| A bad migration damages live data | `release.sh` takes a fresh `pg_dump` first, shows the migration plan and waits for your "y". Take a SolidCP snapshot before big releases (once LDC enables snapshots — 2.5) |
| Restarting kicks users out mid-work | Release outside busy hours (before opening / after closing). A restart takes ~10 s; WebSockets reconnect by themselves; pushed POS orders are protected by `client_token` idempotency |
| Two schedulers → double syncs / double posts | The workbench **never** runs `run_scheduler`; there is no service for it |
| The workbench eats RAM that production needs | Stop Vite and test runs when you're done; keep an eye on `htop` |

The workbench is **not** an environment: it has no website, no database of its own, no
scheduler and no writers. It's a desk with a window onto production that can look at
everything and change nothing.

### 13.2 Set up the workbench (once, after the cutover restore — section 11)

**a) Read access for the workbench login** (the tables must exist, so after the restore):
```bash
sudo -u postgres psql -d elrezeiky_db <<'SQL'
GRANT CONNECT ON DATABASE elrezeiky_db TO elrezeiky_work;
GRANT USAGE ON SCHEMA public TO elrezeiky_work;
GRANT SELECT ON ALL TABLES    IN SCHEMA public TO elrezeiky_work;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO elrezeiky_work;
-- tables created by future migrations become readable automatically
ALTER DEFAULT PRIVILEGES FOR ROLE elrezeiky IN SCHEMA public GRANT SELECT ON TABLES    TO elrezeiky_work;
ALTER DEFAULT PRIVILEGES FOR ROLE elrezeiky IN SCHEMA public GRANT SELECT ON SEQUENCES TO elrezeiky_work;
SQL
```
(If you ever restore `elrezeiky_db` again, re-run this block.)

**b) The checkout** (as your own user `bassemwolsely94`, not `elrezeiky`):
```bash
ssh-keygen -t ed25519 -C "bassemwolsely94@erp workbench"     # add the .pub to YOUR GitHub account (Settings → SSH keys) — this key may push
mkdir -p /home/bassemwolsely94/work && cd /home/bassemwolsely94/work
git clone git@github.com:bassemwolsely94/SoftechReservationModule.git app
python3.12 -m venv /home/bassemwolsely94/work/venv
/home/bassemwolsely94/work/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
cd app
/home/bassemwolsely94/work/venv/bin/pip install -r requirements.txt -r requirements-ci.txt
sudo cp -r /opt/elrezeiky/app/ocr_tessdata ./ocr_tessdata && sudo chown -R bassemwolsely94:bassemwolsely94 ocr_tessdata   # git-ignored OCR language data
(cd frontend && npm ci)
cp deploy/staging.env.example .env && chmod 600 .env
git config user.name "bassemwolsely94" && git config user.email "<your GitHub e-mail>"
```

**c) Workbench `.env`** — start from the staging template (it already has every writer OFF
and every external channel empty), then set:
```env
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
SECRET_KEY=<any random value — not the production one>
PG_NAME=elrezeiky_db                 # the LIVE database…
PG_USER=elrezeiky_work               # …through the read-only login
PG_PASSWORD=<workbench password from 7.1>
PG_HOST=localhost
REDIS_URL=                           # empty → in-memory; never touch production's Redis
SOFTECH_READ_ONLY=True               # NEVER change this in the workbench
SYBASE_HOST=192.168.1.8
SYBASE_PORT=5000
SYBASE_USER=<ideally a SELECT-only SOFTECH login — ask the SOFTECH DBA>
SYBASE_PASSWORD=<…>
SOFTECH_BRANCH_HOST_OVERRIDE=        # empty → read the real branch nodes (read-only)
TESSERACT_CMD=/usr/bin/tesseract
PADDLE_OCR_URL=http://127.0.0.1:8077/boxes   # shares the production OCR sidecar (it only reads images)
GEMINI_API_KEY=                      # empty unless you are testing Gemini on purpose
RBAC_ENFORCEMENT=log
```
A **SELECT-only SOFTECH login** for the workbench is the database-level guarantee on top of the
kill-switch. Ask for it; until then the kill-switch protects you.

**d) Prove the workbench is harmless** (once, and after any `.env` change):
```bash
cd /home/bassemwolsely94/work/app
../venv/bin/python manage.py shell -c "from django.db import connection as c; cur=c.cursor(); cur.execute('SHOW transaction_read_only'); print(cur.fetchone())"
#   → ('on',)
../venv/bin/python manage.py shell -c "from django.conf import settings; print(settings.SOFTECH_READ_ONLY)"
#   → True
../venv/bin/python manage.py test apps.tests.test_help
#   → runs in test_elrezeiky_db (created and dropped by the test runner) and passes
```

> Some management commands write to our database (syncs, engines, backfills). From the
> workbench they fail with "cannot execute … in a read-only transaction" — that is the guard
> working. Those commands run on production only, deliberately:
> `sudo -u elrezeiky /opt/elrezeiky/venv/bin/python /opt/elrezeiky/app/manage.py <command>`.
> Per project rules, **SOFTECH rollback-probes or any SOFTECH write test are a stop-and-ask
> step** — they are never run from the workbench.

### 13.3 Your tools

1. **VS Code + "Remote - SSH"** on your PC → connect to `bassemwolsely94@elrezeikyerp.dawalvry.com` → open
   `/home/bassemwolsely94/work/app`. You edit server files as if they were local; the terminal runs on the
   server.
2. **Claude Code in the workbench** — it sees the real code, reads live data through the
   read-only login, and reaches SOFTECH read-only:
   ```bash
   sudo npm install -g @anthropic-ai/claude-code
   cd /home/bassemwolsely94/work/app && claude
   ```
   `CLAUDE.md` comes with the repo. Copy your Claude memory folder from the office PC
   (`C:\Users\basse\.claude\projects\<this project>\memory\`) to the matching folder under
   `/home/bassemwolsely94/.claude/projects/` (the folder name follows the server path, e.g.
   `-home-bassemwolsely94-work-app`), so the project memory comes along.
3. **Your laptop on ZeroTier** to reach the server privately from anywhere (Django admin and
   Cockpit are VPN-only). Join network `8d1c312afae365aa` in the ZeroTier app, authorise the
   laptop in my.zerotier.com with a **fixed IP**, then reach the VPS at `10.50.50.77`. Other
   staff share this network, so the VPS firewall (12.3 c) names your laptop's IP, not the range.

### 13.4 Seeing a change before it goes live

| Kind of change | How you check it before release |
|---|---|
| Business logic / engines / calculations | Tests (`manage.py test …`, hermetic) + read-only shell or command runs against live data in the workbench |
| A screen (React) | Vite in the workbench against the **live** API (below) |
| New API + new screen together | Release it switched off or hidden, then switch it on for yourself first: an `*_ENABLED` flag (default False), or an RBAC module granted to `admin` only; widen access once it's right |
| Migrations | `manage.py makemigrations --check --dry-run` + tests in the workbench; `release.sh` shows the plan before applying |

**Frontend preview against live data** — `frontend/vite.config.js` already proxies `/api` and
`/ws` to `localhost:8000`, which on the server **is** production's Daphne. So:
```bash
# on your PC
ssh -L 5173:localhost:5173 bassemwolsely94@elrezeikyerp.dawalvry.com
# on the server
cd /home/bassemwolsely94/work/app/frontend && npx vite --port 5173 --strictPort
```
Open `http://localhost:5173` on your PC and log in with your normal account. You see your
**new, unreleased screens** running on real data.
⚠ The API behind it is production: anything you **click** (save, approve, push) is real — exactly
as if you did it on `elrezeikyapp.dawalvry.com`. Use the preview to look; perform actions only if you'd do
them for real anyway. Stop Vite when done (Ctrl+C).

**The daily loop:**
```
cd /home/bassemwolsely94/work/app && git checkout main && git pull
git checkout -b feature/<name>
→ code (you / Claude Code) → tests → Vite preview → npm run build (must succeed)
→ git commit → git push → Pull Request on GitHub → review → merge into main
→ release (13.5) in a quiet hour
```
`apps/tests/test_help.py` keeps failing until every new screen has help text — that's by design.

### 13.5 Releasing to production

`/opt/elrezeiky/release.sh` (owned by root: `sudo chown root:root` + `sudo chmod 700`):
```bash
#!/usr/bin/env bash
# Release main to production. Run: sudo /opt/elrezeiky/release.sh
set -euo pipefail
APP=/opt/elrezeiky/app; PY=/opt/elrezeiky/venv/bin/python; U="sudo -u elrezeiky"
cd $APP
OLD=$($U git rev-parse HEAD)
echo "== backup before release"
$U pg_dump -h localhost -U elrezeiky -Fc elrezeiky_db -f /opt/elrezeiky/backups/pre_release_$(date +%F_%H%M).dump
echo "== pull main"
$U git fetch origin && $U git checkout main && $U git pull --ff-only
NEW=$($U git rev-parse HEAD)
if [[ $OLD == "$NEW" ]]; then echo "Nothing new on main."; exit 0; fi
$U git log --oneline $OLD..$NEW
echo "== python deps (app)";  $U /opt/elrezeiky/venv/bin/pip install -q -r requirements.txt
if ! $U git diff --quiet $OLD $NEW -- ocr_sidecar/requirements.txt; then
  echo "== python deps (OCR sidecar)"; $U /opt/elrezeiky/ocr-venv/bin/pip install -q -r ocr_sidecar/requirements.txt
fi
echo "== migrations to apply:"; $U $PY manage.py migrate --plan | tail -25
read -p "Apply these migrations and restart production? [y/N] " a
if [[ $a != y ]]; then echo "Stopped. Code is pulled but NOT live. Undo: sudo -u elrezeiky git checkout $OLD"; exit 1; fi
$U $PY manage.py migrate
echo "== frontend";           (cd frontend && $U npm ci --silent && $U npm run build)
$U $PY manage.py collectstatic --noinput
$U $PY manage.py check --deploy
echo "== restart"
systemctl restart elrezeiky-web
systemctl restart elrezeiky-scheduler
$U git diff --quiet $OLD $NEW -- ocr_sidecar || systemctl restart elrezeiky-ocr
sleep 5; systemctl --no-pager status elrezeiky-web elrezeiky-scheduler elrezeiky-ocr | grep -E "●|Active"
echo "== live: $($U git log -1 --oneline)   (previous: ${OLD:0:8})"
```
After each release: open `https://elrezeikyapp.dawalvry.com`, check the screen you changed, and watch
`journalctl -u elrezeiky-web -u elrezeiky-scheduler -f` for a minute.

**Rollback:** `cd /opt/elrezeiky/app && sudo -u elrezeiky git checkout <previous commit>`,
rebuild the frontend if it changed, restart. If a migration damaged data, restore the
`pre_release_*.dump` (or roll back to the SolidCP snapshot, if snapshots are enabled — 2.5).

Per project rules, **stop and review** before releasing anything that changes SOFTECH sync
schema, pricing/discount logic, checkout/payment, or any writer.

---

## 14. Troubleshooting

| Symptom | Check |
|---|---|
| Site unreachable | `nslookup elrezeikyapp.dawalvry.com 8.8.8.8` · `sudo ufw status` · `sudo systemctl status nginx` · SolidCP: VPS running? |
| 502 Bad Gateway | `journalctl -u elrezeiky-web -n 100` (often a `.env` typo or missing SECRET_KEY/ALLOWED_HOSTS) |
| Every SOFTECH sync fails | VPN: `sudo wg show` handshake age; `nc -vz 192.168.1.8 5000`; HQ internet/MikroTik up? router log for "tunnel DOWN"; see the table in 5.3 |
| One branch fails | `nc -vz <branch db_host> 5000` from the VPS → routing HQ↔branch or branch firewall |
| `JVM not found` | `sudo apt install openjdk-11-jre-headless`; set `JAVA_HOME` in `.env` |
| Notifications don't arrive live | `redis-cli ping`; `REDIS_URL` set in both web + scheduler `.env` (same file); WS 101 in DevTools |
| Uploads 403/404 | `MEDIA_ACCEL_REDIRECT=True`, nginx `/protected-media/` alias path, file ownership `elrezeiky` |
| Writes refused | expected while `SOFTECH_READ_ONLY=True` — check `.env` and restart both services |
| Out of memory / swapping | `htop`: stop workbench Vite/tests; keep EasyOCR/Whisper off; `journalctl -u elrezeiky-ocr` (sidecar hitting its 2 GB cap?); ask LDC for 16 GB |
| OCR slow / screens slow during OCR | expected on 4 vCPU during big bundles; check `OMP_THREAD_LIMIT=1`, sidecar `CPUQuota`; run big bundles after hours; 16 GB / 8 vCPU plan |
| `paddleocr` engine unavailable | `systemctl status elrezeiky-ocr` · `curl 127.0.0.1:8077/health` · `PADDLE_OCR_URL` in `.env` |
| Cert expired | `sudo certbot renew` · `systemctl list-timers | grep certbot` |

---

## 15. Master checklist

- [ ] 1.1 All work committed, pushed, merged to `main`
- [ ] 1.2 Office `.env` inventoried (incl. OMNI key, every writer flag)
- [ ] 1.3 MikroTik on RouterOS 7, LAN IP + SOFTECH/PBX addresses listed; Sybase/PBX allow the router's LAN IP
- [ ] 2 VPS `elrezeikyerp.dawalvry.com` created: Ubuntu 24.04, 4 CPU / 8 GB / 300 GB, no dynamic memory, public IPv4; LDC ticket for snapshot quota
- [ ] 3 DNS zone + A records (@, elrezeikyapp, elrezeikyerp) resolve
- [ ] 4 SSH keys, root/password login off, ufw, fail2ban, swap — snapshot
- [ ] 5 MikroTik backed up; wg-vps + address list + firewall + src-NAT + MSS + netwatch; all 6 SOFTECH nodes + PBX reachable — snapshot
- [ ] 6–7 Stack + PostgreSQL tuned; `elrezeiky` + read-only `elrezeiky_work` logins
- [ ] 8 Code cloned, venv, read-only `.env`, `check --deploy` + `test_sybase_vps` PASS; local OCR: ocr_tessdata copied, `elrezeiky-ocr` healthy, engines listed
- [ ] 9 systemd, nginx, TLS, frontend build — snapshot
- [ ] 10 Rehearsal restore verified (checklist 10.2)
- [ ] 11 Cutover in order 11.1 → 11.9 — snapshot
- [ ] 12 Nightly backups + off-site copy + uptime monitor; Cockpit on 10.50.50.77 / 10.0.0.77 :9090 (VPN only, `ss` shows no 0.0.0.0:9090), MikroTik admin rule, `bassemwolsely94` password set
- [ ] 13 Workbench (read-only grants, `.env`, harmless-proof), VS Code Remote, Claude Code, `release.sh`
