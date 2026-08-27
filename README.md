# ARIN IPv4 Waiting List Monitor

When the script runs, it launches a headless Chromium browser, loads the ARIN IPv4 Waiting List page, extracts the rendered table, locates your entry by matching the exact “Date and Time Added to Waiting List”, and posts your current position to a [Fluxer](https://github.com/beennnii/fluxerpy3) channel. The previous position is stored locally so progress can be tracked over time.

Official Fluxer (`https://api.fluxer.app/v1`) and self-hosted instances are both supported via `FLUXER_API_URL`. Email notifications remain optional if SMTP is configured.

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

The script automatically loads `.env` or `arin_waitlist.env` from the same directory as `arin_waitlist.py` (no `source` required). Copy the example and edit:

```bash
cp ~/arin-waitlist-monitor/arin_waitlist.env ~/arin-waitlist-monitor/.env
nano ~/arin-waitlist-monitor/.env
```

Update the following fields:

- **ARIN_TARGET_DATE**

    This must exactly match the “Date and Time Added to Waiting List” shown on the ARIN IPv4 Waiting List page.
    The match is case-sensitive and includes the day name and timezone.

- **FLUXER_TOKEN**

    Bot token for your Fluxer bot (not a user token).

- **FLUXER_CHANNEL_ID**

    Channel ID where the daily position update should be posted.

- **FLUXER_API_URL**

    API base URL. Defaults to the official instance, `https://api.fluxer.app/v1`.
    For a self-hosted server you can set either the host (`https://fluxer.example.com`) or the full API path (`https://fluxer.example.com/v1`).

Email is optional. Leave the SMTP fields blank to skip it, or fill them in to also send the update by email:

- **SMTP_HOST** — hostname of your SMTP server
- **SMTP_PORT** — `465` for SMTPS or `587` for STARTTLS
- **SMTP_USER** / **SMTP_PASS** — SMTP credentials
- **MAIL_FROM** / **MAIL_TO** — sender and recipients (comma/semicolon/space separated)

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

Posted to Fluxer (and emailed, if SMTP is configured):

```
**[ARIN Waitlist] Position: XXX/XXX**

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
