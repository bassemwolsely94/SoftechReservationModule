# ElRezeiky Platform — VPS Deployment Guide

## Architecture (3 separate processes)

```
Internet → Nginx (443/80) → Daphne :8000 (ASGI web)
                                    ↘ PostgreSQL
                          Scheduler (separate process) ↗
```

The scheduler is **always** a separate process — never inside the web server.
This prevents the thread-pool crash that causes 500 on every request after a reload.

---

## 1. Server preparation

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip nginx postgresql postgresql-contrib
```

Create a dedicated system user:
```bash
sudo useradd -r -s /bin/bash -d /opt/elrezeiky elrezeiky
sudo mkdir -p /opt/elrezeiky
sudo chown elrezeiky:elrezeiky /opt/elrezeiky
```

---

## 2. Deploy application code

```bash
sudo -u elrezeiky git clone <your-repo-url> /opt/elrezeiky
cd /opt/elrezeiky
sudo -u elrezeiky python3.12 -m venv venv
sudo -u elrezeiky venv/bin/pip install -r requirements.txt
```

---

## 3. Configure environment

```bash
sudo -u elrezeiky cp .env.example .env
sudo -u elrezeiky nano .env
```

Critical settings for production:
```env
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,YOUR_VPS_IP
SCHEDULER_AUTOSTART=False          # MUST be False — scheduler runs separately
SECRET_KEY=<generate a long random key>
```

---

## 4. Database setup

```bash
sudo -u postgres psql -c "CREATE USER elrezeiky WITH PASSWORD 'your_db_password';"
sudo -u postgres psql -c "CREATE DATABASE elrezeiky_db OWNER elrezeiky;"
sudo -u elrezeiky venv/bin/python manage.py migrate
sudo -u elrezeiky venv/bin/python manage.py collectstatic --noinput
sudo -u elrezeiky venv/bin/python manage.py createsuperuser
```

---

## 5. Install systemd services

```bash
sudo cp deploy/elrezeiky-web.service       /etc/systemd/system/
sudo cp deploy/elrezeiky-scheduler.service /etc/systemd/system/

# Edit paths/user if different from /opt/elrezeiky
sudo nano /etc/systemd/system/elrezeiky-web.service
sudo nano /etc/systemd/system/elrezeiky-scheduler.service

sudo systemctl daemon-reload
sudo systemctl enable elrezeiky-web elrezeiky-scheduler
sudo systemctl start  elrezeiky-web elrezeiky-scheduler
```

Check they are running:
```bash
sudo systemctl status elrezeiky-web
sudo systemctl status elrezeiky-scheduler
```

---

## 6. Install Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/elrezeiky
# Edit YOUR_DOMAIN_OR_IP and SSL cert paths in that file
sudo nano /etc/nginx/sites-available/elrezeiky

sudo ln -s /etc/nginx/sites-available/elrezeiky /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

### SSL with Let's Encrypt:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
# certbot will edit nginx.conf automatically
sudo systemctl reload nginx
```

---

## 7. Build the React frontend

On your dev machine (or on the VPS):
```bash
cd frontend
npm install
npm run build
# Output goes to frontend/dist — served by Nginx /
```

---

## 8. Ongoing operations

### View live logs
```bash
# Web server logs
journalctl -u elrezeiky-web -f

# Scheduler logs
journalctl -u elrezeiky-scheduler -f

# Both together
journalctl -u elrezeiky-web -u elrezeiky-scheduler -f
```

### Restart after code update
```bash
cd /opt/elrezeiky
sudo -u elrezeiky git pull
sudo -u elrezeiky venv/bin/pip install -r requirements.txt   # if dependencies changed
sudo -u elrezeiky venv/bin/python manage.py migrate          # if migrations added
sudo -u elrezeiky venv/bin/python manage.py collectstatic --noinput

sudo systemctl restart elrezeiky-web
sudo systemctl restart elrezeiky-scheduler
```

### If the scheduler is stuck / not running jobs
```bash
sudo systemctl restart elrezeiky-scheduler
# Then watch it come back up:
journalctl -u elrezeiky-scheduler -f
```

### Emergency: reset admin password
```bash
sudo -u elrezeiky /opt/elrezeiky/venv/bin/python manage.py shell \
  -c "from django.contrib.auth.models import User; u=User.objects.get(username='bassemwolsely94'); u.set_password('NewPassword123!'); u.save(); print('done')"
```

---

## 9. Why this architecture is stable for prolonged uptime

| Risk | How it's handled |
|------|-----------------|
| Web crash | `Restart=always` — systemd brings it back in 5s |
| Scheduler crash | `Restart=always` — independent of web, back in 10s |
| Autoreload killing thread pool | Impossible in production — no autoreload (`DEBUG=False`, Daphne not runserver) |
| Multi-worker job duplication | Scheduler is one process, web is separate — no overlap |
| VPS reboot | Both services have `WantedBy=multi-user.target` — start automatically |
| Tight crash loop | `StartLimitBurst=5` — stops after 5 restarts in 60s, alerts via journal |
| In-flight sync job on shutdown | `TimeoutStopSec=90` on scheduler — waits up to 90s before SIGKILL |

---

## 10. Development workflow (local Windows)

Always run in **two separate terminals**:

```
# Terminal 1 — web server
venv\Scripts\python.exe manage.py runserver

# Terminal 2 — scheduler  
venv\Scripts\python.exe manage.py run_scheduler
```

Never set `SCHEDULER_AUTOSTART=True` in `.env`.
