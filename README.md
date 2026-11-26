# Monthly remote health check

An internal web app for a Hong Kong network engineer and colleagues. Each person VPNs or uses AnyDesk into a client site, then records that month’s check here.

There is **no login**. Keep it on your own PC, the office LAN, or an Ubuntu VM that is only reachable over VPN. Do not publish it on the public internet.

A check is a **point-in-time snapshot**. Nothing alerts you between monthly visits, and this is not 24-hour monitoring.

## Run with Docker

You need Docker Engine and Docker Compose v2. The image build downloads packages. After that, start and stop do not need the internet.

```bash
docker compose up -d --build
```

Open **http://127.0.0.1:8080**. On a VM, use `http://<VM LAN IP>:8080`. The app listens on `0.0.0.0:8080`.

```bash
docker compose logs -f     # logs
docker compose stop        # stop, keep data
docker compose start       # start again
docker compose down        # remove the container, keep the volume
docker compose down -v     # delete the database and screenshots too
```

Back up `/data` before upgrading. This version has no database migration. An older SQLite file may not match a newer build.

## Where the data lives

The Compose volume `healthcheck-data` is mounted at `/data` in the container:

- `/data/healthcheck.db` — SQLite database
- `/data/uploads/` — screenshots (jpg, png, webp), not stored in git

The container timezone is `Asia/Hong_Kong`. Days remaining are counted from the **check date**, not from today. The page says so.

To keep files on a directory of your own, change the volume in `docker-compose.yml`:

```yaml
volumes:
  - /srv/healthcheck/data:/data
```

Stop the stack, then copy that directory or volume to back it up.

## Deploy on an internal Ubuntu VM

1. Install Docker Engine and the Compose plugin.
2. Copy this project onto the VM (`git clone` needs access to this private repo, or copy the folder).
3. From the project directory, run `docker compose up -d --build`.
4. Allow port 8080 only from the LAN or VPN. Do not open it to the public internet. For example:

   ```bash
   sudo ufw allow from 10.0.0.0/8 to any port 8080 proto tcp
   ```

   Use your real LAN or VPN range.
5. From a PC already on the VPN, open `http://<VM IP>:8080`.

This version has no HTTPS, SMTP, or SSO. If you later put a reverse proxy in front, terminate TLS there. The app itself stays on port 8080.

## Example data

The first start, on an empty database, loads three example clients. Addresses are in the documentation range `192.0.2.0/24`.

| Client | What you should see |
| --- | --- |
| Client A / Example site | October and November 2026. November is red: AP-01 offline (ISS-001), a new NVR disk fault, and a recovered backup |
| Client B / Head office | October green, November amber (firewall licence enters the 90-day window; the checklist matches last month) |
| Client C / Warehouse | Cover only, so the light is Not started |

Delete them before real use. After they are gone, a restart does **not** load them again. To start over, run `docker compose down -v` and start again. That deletes real records too.

## What you can do

- Several clients. Each has devices, one check per month, issues that carry across months, and expiries.
- Device types: Server, Switch, Firewall, AP, NVR, Other. Fields: name, model, serial, IP, firmware, warranty / support expiry, last check, this month (Normal / Abnormal), exception, follow-up, date first found, screenshots.
- Start a month with check date, engineer, connection (VPN / AnyDesk / Other), duration, and notes.
- Overall light:
  - **Red** — a device check is Abnormal, or something is Expired
  - **Amber** — nothing is red, but something is due within 30 or 90 days
  - **Green** — at least one check is filled in, and nothing above applies
  - **Not started** — no check result yet, and no expiry warning
  - A Normal expiry on its own does not turn the light green
- Each device has its own check list, set once. An NVR might have HDD and playback. An AP might have which AP is down. A router or switch can store the command to run. A new month loads those checks with blank results.
- On the device, mark each check Normal or Abnormal, write the issue, and upload a screenshot.
- Expiries: Licence, Warranty, SSL certificate, Support contract, or Other. Days left use the check date. Status is Expired, Due in 30 days, Due in 90 days, or Normal. Copy a device warranty in only when you choose to.
- Screenshots attach to a device’s month, a checklist item, or an issue. Thumbnails open to the full image. 5 MB each, 8 per item.
- Export one client and month as PDF and Excel. The PDF embeds up to 8 thumbnails. The Excel file lists file names.

## Not in this version

- Login, accounts, or permissions
- Public HTTPS, SMTP, or SSO
- Live monitoring or alerts between monthly visits
- Automatic copy of every device warranty into the expiry list
- A database migration tool
- Inserting a month between two existing months does not rewrite the newer month’s “last month” column. Create months in date order
- The container process runs as root. Keep port 8080 on the internal network

## Local development

Docker is the way to run it. To change the code on your machine:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
DATA_DIR=./data uvicorn app.main:app --host 0.0.0.0 --port 8080
pytest
```

The page uses Noto Sans TC so Chinese notes still render. PDF text uses Noto CJK from the image (`fonts-noto-cjk`).
