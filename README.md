# ARIN IPv4 Waiting List Monitor

When the script runs, it launches a headless Chromium browser, loads the ARIN IPv4 Waiting List page, extracts the rendered table, locates your entry by matching the exact “Date and Time Added to Waiting List”, and sends an email with your current position. The previous position is stored locally so progress can be tracked over time.

The script supports SMTP STARTTLS and SMTPS and can send notifications to multiple email recipients.

---

## One-Line Installation

The following command installs system dependencies, creates a Python virtual environment and downloads the script and example environment file:

```bash
apt update && apt install -y python3 python3-venv python3-pip curl && \
git clone https://github.com/valornode/arin-waitlist-monitor.git && \
python3 -m venv ~/arin-waitlist && \
source ~/arin-waitlist-monitor/bin/activate && \
pip install --upgrade pip playwright && \
python -m playwright install --with-deps chromium
```

---

## Edit the Environment Variables

Open the file for editing:

```bash
nano ~/arin-waitlist-monitor/arin_waitlist.env
```
Update the following fields:

- **ARIN_TARGET_DATE**

    This must exactly match the “Date and Time Added to Waiting List” shown on the ARIN IPv4 Waiting List page.
    The match is case-sensitive and includes the day name and timezone.
- **SMTP_HOST**
  
    The hostname of your SMTP server.
- **SMTP_PORT**
  
    Use 465 for SMTPS (implicit TLS) or 587 for SMTP with STARTTLS.
- **SMTP_USER**
  
    The username for SMTP authentication (usually an email address).
- **SMTP_PASS**
  
    The password or app-specific password for the SMTP account.
- **MAIL_FROM**
  
    The sender address shown in the email.
- **MAIL_TO**
  
    One or more recipient email addresses. Multiple recipients can be separated by commas, semicolons, or spaces.

---

## Run the Script Manually

Run this to test the script and make sure your .env is setup properly.
```
set -a && source ~/arin-waitlist-monitor/arin_waitlist.env && set +a
source ~/arin-waitlist-monitor/bin/activate
python ~/arin-waitlist-monitor/arin_waitlist.py --once
```

---

## Run the Script Automatically

Edit the crontab and add whichever you prefer, changing the location of the script files as needed.
```
crontab -e
```
This will make the script run every 12 hours:
```
0 */12 * * * set -a && source /home/[user]/arin-waitlist-monitor/arin_waitlist.env && set +a && source /home/[user]/arin-waitlist-monitor/bin/activate && python /home/[user]/arin-waitlist-monitor/arin_waitlist.py --once >> /home/[user]/arin-waitlist-monitor/arin_waitlist.log 2>&1
```
This will make the script run every day at midnight:
```
0 0 * * * set -a && source /home/[user]/arin-waitlist-monitor/arin_waitlist.env && set +a && source /home/[user]/arin-waitlist-monitor/bin/activate && python /home/[user]/arin-waitlist-monitor/arin_waitlist.py --once >> /home/[user]/arin-waitlist-monitor/log/arin_waitlist.log 2>&1
```

---

## Email Format
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
