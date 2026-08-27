# ARIN IPv4 Waiting List Monitor

When the script runs, it launches a headless Chromium browser, loads the ARIN IPv4 Waiting List page, extracts the rendered table, locates your entry by matching the exact “Date and Time Added to Waiting List”, and posts your current position to a Fluxer channel via an [incoming webhook](https://docs.fluxer.app/api-reference/webhooks/execute-webhook). The previous position is stored locally so progress can be tracked over time.

Official Fluxer and self-hosted instances both work — paste the webhook URL your instance gives you. Email notifications remain optional if SMTP is configured.

---

## One-Line Installation

The following command installs system dependencies, creates a Python virtual environment and downloads the script and example environment file:

```bash
apt update && apt install -y python3 python3-venv python3-pip curl && \
git clone https://github.com/Phoenix-Net/arin-waitlist-monitor.git && \
python3 -m venv ~/arin-waitlist && \
source ~/arin-waitlist/bin/activate && \
pip install --upgrade pip -r ~/arin-waitlist-monitor/requirements.txt && \
python -m playwright install --with-deps chromium
```

---

## Edit the Environment Variables

The script automatically loads `.env` or `arin_waitlist.env` from the same directory as `arin_waitlist.py` (no `source` required). Docker Compose mounts `arin_waitlist.env` into the container, so edit that file in place:

```bash
nano ~/arin-waitlist-monitor/arin_waitlist.env
```

For a native (non-Docker) install you can also copy it to `.env`:

```bash
cp ~/arin-waitlist-monitor/arin_waitlist.env ~/arin-waitlist-monitor/.env
nano ~/arin-waitlist-monitor/.env
```

Update the following fields:

- **ARIN_TARGET_DATE**

    This must exactly match the “Date and Time Added to Waiting List” shown on the ARIN IPv4 Waiting List page.
    The match is case-sensitive and includes the day name and timezone.

- **FLUXER_WEBHOOK_URL**

    Full incoming webhook URL from the Fluxer channel (Integrations → Webhooks).
    Official URLs look like `https://api.fluxer.app/v1/webhooks/{id}/{token}`.
    For a self-hosted server, paste the URL that instance shows you.

- **FLUXER_WEBHOOK_USERNAME** *(optional)*

    Display name used for webhook posts. Leave unset to keep the webhook’s own name.

Email is optional. Leave the SMTP fields blank to skip it, or fill them in to also send the update by email:

- **SMTP_HOST** — hostname of your SMTP server
- **SMTP_PORT** — `465` for SMTPS or `587` for STARTTLS
- **SMTP_USER** / **SMTP_PASS** — SMTP credentials
- **MAIL_FROM** / **MAIL_TO** — sender and recipients (comma/semicolon/space separated)

---

## Run with Docker

Build the image locally and start the monitor. Watch mode is the default (one check per day).

```bash
docker compose up --build -d
```

A one-shot check (useful for testing your env file):

```bash
docker compose run --rm arin-waitlist --once
```

Rebuild after pulling updates:

```bash
docker compose up --build -d
```

Waitlist position is stored in `./data/` on the host so it survives container rebuilds. Logs:

```bash
docker compose logs -f
```

---

## Run the Script Manually

Run this to test the script and make sure your env file is set up properly.

```
source ~/arin-waitlist/bin/activate
python ~/arin-waitlist-monitor/arin_waitlist.py --once
```

---

## Run the Script Automatically

Edit the crontab and add whichever you prefer, changing the location of the script files as needed.

```
crontab -e
```

This will make the script run every day at midnight:

```
0 0 * * * /home/[user]/arin-waitlist/bin/python /home/[user]/arin-waitlist-monitor/arin_waitlist.py --once >> /home/[user]/arin-waitlist-monitor/log/arin_waitlist.log 2>&1
```

This will make the script run every 12 hours:

```
0 */12 * * * /home/[user]/arin-waitlist/bin/python /home/[user]/arin-waitlist-monitor/arin_waitlist.py --once >> /home/[user]/arin-waitlist-monitor/arin_waitlist.log 2>&1
```

You can also leave it running in watch mode (default interval is 24 hours):

```
python ~/arin-waitlist-monitor/arin_waitlist.py --watch
```

---

## Notification Format

Fluxer gets a rich embed (colored sidebar, title, and inline fields). The sidebar is green if you moved up the list, gray if nothing changed, and red if you moved down.

Email (if SMTP is configured) stays plain text:

```
Your current ARIN IPv4 waiting list position is:
XXX/XXX.

Your last position was:
XXX/XXX.

You joined the waitlist on:
<Date searched for>

Max Prefix: /XX | Min Prefix: /XX

Time Checked:
MM/DD/YYYY HH:MMPM CST
```
![Email Example](https://share.bray.lat/u/clean-warlike-alpinegoat.png)
