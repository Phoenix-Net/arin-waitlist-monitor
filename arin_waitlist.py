#!/usr/bin/env python3
"""
ARIN IPv4 Waiting List Monitor (Playwright)

- Scrapes ARIN waiting list table (JS-rendered) via Playwright
- Finds your entry by the exact timestamp string
- Posts your current position to Fluxer via an incoming webhook each run
- Optionally emails the same update (STARTTLS or SMTPS)
- Self-hosted Fluxer instances work by pasting that instance's webhook URL
- Loads configuration from .env / arin_waitlist.env automatically

Exit codes:
  0 = found
  2 = not found
  3 = error
"""

import os
import re
import json
import time
import argparse
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:
    ZoneInfo = None  # type: ignore


WAITLIST_URL = "https://www.arin.net/resources/guide/ipv4/waiting_list/"

SCRIPT_DIR = Path(__file__).resolve().parent


def log(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", flush=True)


def err(msg: str) -> None:
    print(f"[ERROR] {msg}", flush=True)


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_env_file(path: Path) -> None:
    """
    Minimal KEY=VALUE loader. Existing environment variables win.
    """
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = _strip_env_value(value)


def load_env_file() -> None:
    """
    Load the first env file found, without overriding already-set variables.
    Preference: python-dotenv if installed, otherwise a small built-in parser.
    """
    candidates = [
        SCRIPT_DIR / ".env",
        SCRIPT_DIR / "arin_waitlist.env",
        Path.cwd() / ".env",
        Path.cwd() / "arin_waitlist.env",
    ]

    chosen: Path | None = None
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            chosen = path
            break

    if chosen is None:
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        _parse_env_file(chosen)
    else:
        load_dotenv(chosen, override=False)

    log(f"Loaded env from {chosen}")


load_env_file()


DEFAULT_TARGET_DATE = os.getenv("ARIN_TARGET_DATE", "Tue, 03 Feb 2026, 12:17:25 EST")
DEFAULT_INTERVAL_SECONDS = int(os.getenv("ARIN_CHECK_INTERVAL_SECONDS", str(24 * 60 * 60)))
DEFAULT_STATE_FILE = os.getenv("ARIN_STATE_FILE", "arin_waitlist_state.json")

# Fluxer webhook (env) — paste the full incoming webhook URL from channel settings
FLUXER_WEBHOOK_URL = os.getenv("FLUXER_WEBHOOK_URL", "").strip()
FLUXER_WEBHOOK_USERNAME = os.getenv("FLUXER_WEBHOOK_USERNAME", "").strip()
FLUXER_WEBHOOK_TIMEOUT = int(os.getenv("FLUXER_WEBHOOK_TIMEOUT", "15"))

# SMTP settings (env) — optional alongside Fluxer
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER)
MAIL_TO_RAW = os.getenv("MAIL_TO", "")
MAIL_SUBJECT_PREFIX = os.getenv("MAIL_SUBJECT_PREFIX", "[ARIN Waitlist]")

SMTP_CONNECT_TIMEOUT = int(os.getenv("SMTP_CONNECT_TIMEOUT", "15"))

# Time checked format requested: "MM/DD/YYYY 00:00PM CST"
# We'll render in America/Chicago if available, otherwise fixed CST offset.
CST_TZ = None
if ZoneInfo is not None:
    try:
        CST_TZ = ZoneInfo("America/Chicago")
    except Exception:
        CST_TZ = None

# Match lines like:
# "473 Tue, 03 Feb 2026, 12:17:25 EST /22 /22"
ROW_RE = re.compile(
    r"^\s*(?P<pos>\d+)\s+(?P<dt>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),.+?)\s+(?P<max>/\d+)\s+(?P<min>/\d+)\s*$"
)


def parse_recipients(mail_to_raw: str) -> list[str]:
    """
    Accepts comma/semicolon/whitespace-separated recipients.
    Returns a de-duplicated list preserving order.
    """
    if not mail_to_raw:
        return []
    # split on comma, semicolon, or whitespace
    parts = re.split(r"[,\s;]+", mail_to_raw.strip())
    out = []
    seen = set()
    for p in parts:
        if not p:
            continue
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def format_time_checked_cst(now_utc: datetime) -> str:
    """
    Format as: MM/DD/YYYY 00:00PM CST
    Uses America/Chicago if available; otherwise uses fixed CST (UTC-6).
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if CST_TZ is not None:
        local = now_utc.astimezone(CST_TZ)
        # Could be CDT in summer; user asked for "CST" literal, so we will print CST regardless.
        # If you want accurate abbreviation (CST/CDT), tell me and I’ll switch.
        return local.strftime("%m/%d/%Y %I:%M%p") + " CST"
    # fixed CST fallback
    fixed = now_utc.astimezone(timezone.utc).timestamp() - (6 * 3600)
    local = datetime.fromtimestamp(fixed, tz=timezone.utc)
    return local.strftime("%m/%d/%Y %I:%M%p") + " CST"


def redact_webhook_url(url: str) -> str:
    """Hide the webhook token in logs: .../webhooks/{id}/{token} -> .../{id}/***"""
    parsed = urlparse(url)
    parts = parsed.path.split("/")
    try:
        i = parts.index("webhooks")
    except ValueError:
        return f"{parsed.scheme}://{parsed.netloc}/***"
    if i + 2 < len(parts) and parts[i + 2]:
        parts[i + 2] = "***"
    return urlunparse(parsed._replace(path="/".join(parts)))


def webhook_execute_url(url: str) -> str:
    """Ask Fluxer to wait for the message so we can see HTTP errors."""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("wait", "true")
    return urlunparse(parsed._replace(query=urlencode(query)))


def fluxer_configured() -> bool:
    return bool(FLUXER_WEBHOOK_URL)


def email_configured(recipients: list[str] | None = None) -> bool:
    if recipients is None:
        recipients = parse_recipients(MAIL_TO_RAW)
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and recipients and MAIL_FROM)


def send_email(subject: str, body: str) -> bool:
    """
    Supports both STARTTLS SMTP and SMTPS:
      - If SMTP_PORT == 465: SMTPS (implicit TLS) via SMTP_SSL
      - Else: SMTP + STARTTLS
    Multiple recipients supported via MAIL_TO (comma/semicolon/space separated).
    Returns True if the message was sent.
    """
    recipients = parse_recipients(MAIL_TO_RAW)

    log(f"Email config: host={SMTP_HOST!r} port={SMTP_PORT} user={SMTP_USER!r} from={MAIL_FROM!r} to={recipients!r}")

    if not email_configured(recipients):
        warn("SMTP not fully configured; skipping email.")
        return False

    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()

    try:
        if SMTP_PORT == 465:
            log("Sending via SMTPS (SMTP_SSL)")
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_CONNECT_TIMEOUT, context=context) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            log("Sending via SMTP STARTTLS")
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_CONNECT_TIMEOUT) as s:
                s.ehlo()
                s.starttls(context=context)
                s.ehlo()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)

        log("Email sent successfully.")
        return True

    except Exception as e:
        err(f"Email send failed ({SMTP_HOST}:{SMTP_PORT}): {e}")
        return False


# Embed sidebar colors (Discord/Fluxer integer RGB)
COLOR_INFO = 0x3498DB
COLOR_OK = 0x2ECC71
COLOR_WARN = 0xF1C40F
COLOR_BAD = 0xE74C3C
COLOR_NEUTRAL = 0x95A5A6


def _iso_timestamp(now_utc: datetime) -> str:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _position_change(current_pos: int, last_pos: int | None) -> tuple[str, int]:
    """
    Lower waitlist number is better. Returns (label, embed color).
    """
    if last_pos is None:
        return "First check", COLOR_INFO
    if current_pos < last_pos:
        return f"▲ {last_pos - current_pos}", COLOR_OK
    if current_pos > last_pos:
        return f"▼ {current_pos - last_pos}", COLOR_BAD
    return "No change", COLOR_NEUTRAL


def build_fluxer_embed(
    *,
    title: str,
    description: str,
    color: int,
    now_utc: datetime,
    time_checked: str,
    fields: list[dict],
) -> dict:
    return {
        "type": "rich",
        "title": title,
        "url": WAITLIST_URL,
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": f"Checked {time_checked}"},
        "timestamp": _iso_timestamp(now_utc),
    }


def embed_found(
    *,
    current_pos: int,
    total: int,
    last_pos: int | None,
    joined: str,
    maxp: str,
    minp: str,
    now_utc: datetime,
    time_checked: str,
) -> dict:
    change, color = _position_change(current_pos, last_pos)
    last_pos_str = str(last_pos) if last_pos is not None else "—"
    return build_fluxer_embed(
        title=f"ARIN IPv4 Waitlist — {current_pos}/{total}",
        description="Your current ARIN IPv4 waiting list position.",
        color=color,
        now_utc=now_utc,
        time_checked=time_checked,
        fields=[
            {"name": "Current", "value": f"**{current_pos}/{total}**", "inline": True},
            {"name": "Last", "value": f"{last_pos_str}/{total}", "inline": True},
            {"name": "Change", "value": change, "inline": True},
            {"name": "Max Prefix", "value": maxp, "inline": True},
            {"name": "Min Prefix", "value": minp, "inline": True},
            {"name": "Joined", "value": joined, "inline": True},
        ],
    )


def embed_not_found(*, target: str, total: int, now_utc: datetime, time_checked: str) -> dict:
    return build_fluxer_embed(
        title="ARIN IPv4 Waitlist — Not Found",
        description="Could not find your entry in the ARIN waiting list table.",
        color=COLOR_WARN,
        now_utc=now_utc,
        time_checked=time_checked,
        fields=[
            {"name": "Target timestamp", "value": target, "inline": False},
            {"name": "Rows parsed", "value": str(total), "inline": True},
        ],
    )


def embed_error(*, error: str, now_utc: datetime, time_checked: str) -> dict:
    return build_fluxer_embed(
        title="ARIN IPv4 Waitlist — Error",
        description="The waitlist check failed.",
        color=COLOR_BAD,
        now_utc=now_utc,
        time_checked=time_checked,
        fields=[
            {"name": "Error", "value": f"```{error[:1000]}```", "inline": False},
        ],
    )


def send_fluxer(subject: str, body: str, embed: dict | None = None) -> bool:
    """
    POST the waitlist update to a Fluxer incoming webhook as a rich embed.
    Official or self-hosted — the webhook URL already includes the host.
    """
    if not fluxer_configured():
        warn("Fluxer not configured (need FLUXER_WEBHOOK_URL); skipping.")
        return False

    parsed = urlparse(FLUXER_WEBHOOK_URL)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        err(f"FLUXER_WEBHOOK_URL is not a valid http(s) URL: {FLUXER_WEBHOOK_URL!r}")
        return False

    payload: dict = {
        "embeds": [embed]
        if embed is not None
        else [
            {
                "type": "rich",
                "title": subject,
                "description": body,
                "color": COLOR_INFO,
                "url": WAITLIST_URL,
            }
        ],
    }
    if FLUXER_WEBHOOK_USERNAME:
        payload["username"] = FLUXER_WEBHOOK_USERNAME

    url = webhook_execute_url(FLUXER_WEBHOOK_URL)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "arin-waitlist-monitor",
        },
    )

    log(f"Posting to Fluxer webhook {redact_webhook_url(FLUXER_WEBHOOK_URL)}")
    try:
        with urllib.request.urlopen(req, timeout=FLUXER_WEBHOOK_TIMEOUT) as resp:
            if resp.status not in (200, 204):
                err(f"Fluxer webhook returned HTTP {resp.status}")
                return False
        log("Fluxer webhook posted successfully.")
        return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        err(f"Fluxer webhook failed (HTTP {e.code}): {detail or e.reason}")
        return False
    except Exception as e:
        err(f"Fluxer webhook failed: {e}")
        return False


def notify(subject: str, body: str, embed: dict | None = None) -> None:
    """
    Send the update to Fluxer and/or email, whichever is configured.
    If nothing is sent, print the message instead.
    """
    sent = False

    if fluxer_configured():
        sent = send_fluxer(subject, body, embed=embed) or sent
    else:
        log("Fluxer notifications disabled (set FLUXER_WEBHOOK_URL to enable).")

    if email_configured():
        sent = send_email(subject, body) or sent

    if not sent:
        warn("No notification channel succeeded; printing message instead.")
        print("Subject:", subject, flush=True)
        print(body, flush=True)


def scrape_waitlist_rows() -> list[dict]:
    """
    Returns list of dicts:
      { position:int, dt_str:str, max_prefix:str, min_prefix:str }
    """
    rows_out: list[dict] = []

    log("Launching Chromium (headless)")
    with sync_playwright() as p:
        # Chromium's sandbox and tiny /dev/shm often fail inside Docker.
        in_docker = Path("/.dockerenv").exists()
        launch_args = ["--disable-dev-shm-usage"]
        if in_docker or os.getenv("PLAYWRIGHT_NO_SANDBOX"):
            launch_args.append("--no-sandbox")
        browser = p.chromium.launch(headless=True, args=launch_args)
        page = browser.new_page()

        log("Loading ARIN waiting list page")
        try:
            page.goto(WAITLIST_URL, wait_until="networkidle", timeout=60000)
        except PWTimeoutError:
            warn("networkidle timed out; retrying with wait_until=load")
            page.goto(WAITLIST_URL, wait_until="load", timeout=60000)

        log("Locating table rows")
        rows = page.locator("table tbody tr")
        count = rows.count()
        log(f"Found {count} rows (including any non-data rows)")

        for i in range(count):
            txt = rows.nth(i).inner_text().replace("\n", " ").strip()
            m = ROW_RE.match(txt)
            if not m:
                continue

            rows_out.append(
                {
                    "position": int(m.group("pos")),
                    "dt_str": m.group("dt").strip(),
                    "max_prefix": m.group("max").strip(),
                    "min_prefix": m.group("min").strip(),
                    "raw": txt,
                }
            )

        browser.close()

    log(f"Parsed {len(rows_out)} data rows")
    return rows_out


def find_entry(rows: list[dict], target_dt_str: str) -> dict | None:
    """
    Match by exact timestamp string (normalized whitespace).
    """
    target_norm = " ".join(target_dt_str.split())
    for r in rows:
        if " ".join(r["dt_str"].split()) == target_norm:
            return r
    return None


def build_body(current_pos: int, total: int, last_pos: int | None, joined: str, maxp: str, minp: str, time_checked: str) -> str:
    last_pos_str = str(last_pos) if last_pos is not None else "None"
    return (
        "Your current ARIN IPv4 waiting list position is:\n"
        f"{current_pos}/{total}.\n\n"
        "Your last position was:\n"
        f"{last_pos_str}/{total}.\n\n"
        "You joined the waitlist on:\n"
        f"{joined}\n\n"
        f"Max Prefix: {maxp} | Min Prefix: {minp}\n\n"
        "Time Checked:\n"
        f"{time_checked}\n"
    )


def run_once(target_dt_str: str, state_file: str) -> int:
    log("Starting ARIN waitlist check")
    now_utc = datetime.now(timezone.utc)
    state = load_state(state_file)

    try:
        rows = scrape_waitlist_rows()
        total = len(rows)
        log(f"Searching for target timestamp: {target_dt_str}")

        match = find_entry(rows, target_dt_str)
        if not match:
            warn("Entry not found in table")
            subject = f"{MAIL_SUBJECT_PREFIX} NOT FOUND"
            time_checked = format_time_checked_cst(now_utc)
            body = (
                "Could not find your entry in the ARIN waiting list table.\n\n"
                f"Target timestamp:\n{target_dt_str}\n\n"
                f"Rows parsed:\n{total}\n\n"
                "Time Checked:\n"
                f"{time_checked}\n"
            )
            notify(
                subject,
                body,
                embed=embed_not_found(
                    target=target_dt_str,
                    total=total,
                    now_utc=now_utc,
                    time_checked=time_checked,
                ),
            )
            return 2

        current_pos = match["position"]
        last_pos = state.get("last_position")
        last_pos = int(last_pos) if last_pos is not None else None
        log(f"Match found! Current position = {current_pos}/{total}")

        time_checked = format_time_checked_cst(now_utc)
        body = build_body(
            current_pos=current_pos,
            total=total,
            last_pos=last_pos,
            joined=target_dt_str,
            maxp=match["max_prefix"],
            minp=match["min_prefix"],
            time_checked=time_checked,
        )

        subject = f"{MAIL_SUBJECT_PREFIX} Position: {current_pos}/{total}"
        notify(
            subject,
            body,
            embed=embed_found(
                current_pos=current_pos,
                total=total,
                last_pos=last_pos,
                joined=target_dt_str,
                maxp=match["max_prefix"],
                minp=match["min_prefix"],
                now_utc=now_utc,
                time_checked=time_checked,
            ),
        )

        state["last_position"] = current_pos
        state["last_checked_utc"] = now_utc.isoformat()
        save_state(state_file, state)
        log(f"State saved to {state_file}")
        log("Done")
        return 0

    except Exception as e:
        err(f"Run failed: {e}")
        subject = f"{MAIL_SUBJECT_PREFIX} ERROR"
        time_checked = format_time_checked_cst(now_utc)
        body = (
            "Error while checking ARIN waiting list:\n"
            f"{e}\n\n"
            "Time Checked:\n"
            f"{time_checked}\n"
        )
        notify(
            subject,
            body,
            embed=embed_error(error=str(e), now_utc=now_utc, time_checked=time_checked),
        )
        return 3


def main() -> None:
    ap = argparse.ArgumentParser(description="Monitor ARIN IPv4 waiting list position (Playwright).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run once and exit.")
    mode.add_argument("--watch", action="store_true", help="Run continuously (default).")

    ap.add_argument("--target", default=DEFAULT_TARGET_DATE, help="Target timestamp as shown on ARIN page.")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS, help="Watch interval in seconds (default 24h).")
    ap.add_argument("--state-file", default=DEFAULT_STATE_FILE, help="Path to state file.")

    args = ap.parse_args()

    if args.once:
        raise SystemExit(run_once(args.target, args.state_file))

    log(f"Watch mode enabled. Interval={args.interval}s (default 24h)")
    log(f"Target={args.target}")
    log(f"State file={args.state_file}")

    while True:
        run_once(args.target, args.state_file)
        log(f"Sleeping for {args.interval} seconds")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
