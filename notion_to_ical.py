#!/usr/bin/env python3
"""
notion_to_ical.py
-----------------
Fetches events from Notion databases and writes .ics files
that Apple Calendar can subscribe to.

Configuration is loaded from a .env file — never hardcode secrets here.
"""

import os
import sys
import json
import hashlib
import logging
import requests
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

# ── icalendar is the only non-stdlib calendar dependency ──────────────────────
try:
    from icalendar import Calendar, Event, vText, vDatetime, vDate
except ImportError:
    sys.exit("Missing dependency. Run:  pip3 install icalendar requests python-dotenv")

# ── Load secrets from .env (never committed to version control) ───────────────
load_dotenv(Path(__file__).parent / ".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
OUTPUT_DIR   = os.getenv("OUTPUT_DIR", str(Path.home() / "NotionCalendars"))
DATABASES_JSON = os.getenv("NOTION_DATABASES", "[]")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / "sync.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Notion API constants ───────────────────────────────────────────────────────
NOTION_VERSION = "2022-06-28"
NOTION_BASE    = "https://api.notion.com/v1"
MAX_PAGES      = 500   # safety cap per database


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def notion_headers() -> dict:
    """Return authenticated headers for the Notion API."""
    if not NOTION_TOKEN:
        sys.exit(
            "NOTION_TOKEN is not set. "
            "Add it to your .env file and try again."
        )
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def stable_uid(database_id: str, page_id: str) -> str:
    """
    Generate a stable, unique UID for a calendar event.
    Using a hash means edits update the event instead of duplicating it.
    """
    raw = f"{database_id}:{page_id}"
    return hashlib.sha256(raw.encode()).hexdigest() + "@notion-sync"


def extract_plain_text(rich_text_list: list) -> str:
    """Flatten a Notion rich_text array into a plain string."""
    return "".join(segment.get("plain_text", "") for segment in rich_text_list)


def find_date_property(properties: dict) -> tuple[str | None, dict | None]:
    """
    Return the (name, value) of the first date-type property found.
    Prefers properties named 'Date', 'Due', 'When', or 'Event Date'
    so common naming conventions work out of the box.
    """
    preferred = {"date", "due", "when", "event date", "start", "deadline"}
    date_props = {
        k: v for k, v in properties.items()
        if v.get("type") == "date" and v.get("date")
    }
    # Try preferred names first (case-insensitive)
    for name, value in date_props.items():
        if name.lower() in preferred:
            return name, value
    # Fall back to the first date property found
    for name, value in date_props.items():
        return name, value
    return None, None


def find_description_property(properties: dict) -> str:
    """
    Return the plain-text content of the first usable text property
    that isn't the title (Notes, Description, Details, etc.).
    """
    skip_types = {"title", "date", "checkbox", "select", "multi_select",
                  "number", "formula", "relation", "rollup", "files"}
    text_types  = {"rich_text", "text"}
    candidates  = {"notes", "description", "details", "summary", "body", "content"}

    # Preferred names first
    for name, value in properties.items():
        if name.lower() in candidates and value.get("type") in text_types:
            txt = extract_plain_text(value.get("rich_text", []))
            if txt:
                return txt

    # Any other rich_text property
    for name, value in properties.items():
        if value.get("type") in text_types and value.get("type") not in skip_types:
            txt = extract_plain_text(value.get("rich_text", []))
            if txt:
                return txt

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Notion API calls
# ─────────────────────────────────────────────────────────────────────────────

def fetch_database_pages(database_id: str) -> list[dict]:
    """
    Query all pages in a Notion database (handles pagination automatically).
    Only returns pages that have a date property set.
    """
    pages   = []
    payload = {"page_size": 100}
    url     = f"{NOTION_BASE}/databases/{database_id}/query"

    while True:
        try:
            response = requests.post(
                url,
                headers=notion_headers(),
                json=payload,
                timeout=15,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            log.error("Notion API error for database %s: %s", database_id, exc)
            log.error("Response: %s", exc.response.text if exc.response else "no body")
            break
        except requests.exceptions.RequestException as exc:
            log.error("Network error: %s", exc)
            break

        data    = response.json()
        results = data.get("results", [])
        pages.extend(results)

        if not data.get("has_more") or len(pages) >= MAX_PAGES:
            break

        payload["start_cursor"] = data.get("next_cursor")

    log.info("  Fetched %d page(s) from database %s", len(pages), database_id)
    return pages


def get_database_title(database_id: str) -> str:
    """Retrieve the human-readable title of a Notion database."""
    try:
        response = requests.get(
            f"{NOTION_BASE}/databases/{database_id}",
            headers=notion_headers(),
            timeout=15,
        )
        response.raise_for_status()
        title_parts = response.json().get("title", [])
        return extract_plain_text(title_parts) or database_id
    except requests.exceptions.RequestException as exc:
        log.warning("Could not fetch title for %s: %s", database_id, exc)
        return database_id


# ─────────────────────────────────────────────────────────────────────────────
# ICS generation
# ─────────────────────────────────────────────────────────────────────────────

def page_to_event(page: dict, database_id: str) -> Event | None:
    """
    Convert a single Notion page dict into an icalendar Event.
    Returns None if the page has no usable date.
    """
    properties = page.get("properties", {})
    page_id    = page.get("id", "")

    # ── Title ─────────────────────────────────────────────────────────────────
    title = ""
    for prop in properties.values():
        if prop.get("type") == "title":
            title = extract_plain_text(prop.get("title", []))
            break
    title = title.strip() or "Untitled"

    # ── Date ──────────────────────────────────────────────────────────────────
    _date_name, date_prop = find_date_property(properties)
    if not date_prop:
        return None   # Skip pages without a date

    date_value = date_prop.get("date", {})
    start_str  = date_value.get("start")
    end_str    = date_value.get("end")

    if not start_str:
        return None

    def parse_notion_date(date_str: str):
        """Return (datetime_or_date, is_all_day)."""
        if "T" in date_str:
            # Full datetime — parse and normalise to UTC
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, False
        else:
            # All-day date
            from datetime import date as date_type
            return datetime.strptime(date_str, "%Y-%m-%d").date(), True

    start, all_day = parse_notion_date(start_str)
    end = None
    if end_str:
        end, _ = parse_notion_date(end_str)

    # ── Description ───────────────────────────────────────────────────────────
    description = find_description_property(properties)

    # ── Build the event ───────────────────────────────────────────────────────
    event = Event()
    event.add("summary",  title)
    event.add("uid",      stable_uid(database_id, page_id))
    event.add("dtstamp",  datetime.now(timezone.utc))

    # Notion page URL (deep link back to Notion)
    notion_url = f"https://notion.so/{page_id.replace('-', '')}"
    if description:
        event.add("description", f"{description}\n\n🔗 {notion_url}")
    else:
        event.add("description", f"🔗 {notion_url}")

    if all_day:
        event.add("dtstart", start)
        if end:
            event.add("dtend", end)
        else:
            event.add("dtend", start)
    else:
        event.add("dtstart", start)
        if end:
            event.add("dtend", end)

    # Mark the last time Notion modified this page
    last_edited = page.get("last_edited_time")
    if last_edited:
        event.add("last-modified", datetime.fromisoformat(
            last_edited.replace("Z", "+00:00")
        ))

    return event


def build_calendar(calendar_name: str, events: list[Event]) -> Calendar:
    """Wrap a list of events in an iCalendar object."""
    cal = Calendar()
    cal.add("prodid",  "-//Notion to iCal Sync//EN")
    cal.add("version", "2.0")
    cal.add("calname", calendar_name)   # Display name in Apple Calendar
    cal.add("x-wr-calname", calendar_name)
    cal.add("x-wr-timezone", "UTC")
    cal.add("refresh-interval;value=duration", "PT5M")   # Hint: refresh every 5 min

    for event in events:
        cal.add_component(event)

    return cal


# ─────────────────────────────────────────────────────────────────────────────
# Main sync
# ─────────────────────────────────────────────────────────────────────────────

def sync_database(db_config: dict, output_dir: Path) -> None:
    """Sync one Notion database → one .ics file."""
    database_id   = db_config.get("id", "").replace("-", "")
    calendar_name = db_config.get("name") or get_database_title(database_id)

    log.info("Syncing: %s  (id: %s)", calendar_name, database_id)

    pages  = fetch_database_pages(database_id)
    events = []
    skipped = 0

    for page in pages:
        event = page_to_event(page, database_id)
        if event:
            events.append(event)
        else:
            skipped += 1

    log.info("  → %d event(s) built, %d page(s) skipped (no date)", len(events), skipped)

    cal      = build_calendar(calendar_name, events)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in calendar_name)
    ics_path  = output_dir / f"{safe_name}.ics"

    ics_path.write_bytes(cal.to_ical())
    log.info("  ✓ Written to %s", ics_path)


def main() -> None:
    log.info("─" * 60)
    log.info("Notion → iCal sync started")

    # ── Parse database list from environment ──────────────────────────────────
    try:
        databases = json.loads(DATABASES_JSON)
    except json.JSONDecodeError as exc:
        sys.exit(f"NOTION_DATABASES in .env is not valid JSON: {exc}")

    if not databases:
        sys.exit(
            "No databases configured. "
            "Set NOTION_DATABASES in your .env file."
        )

    # ── Ensure output directory exists ────────────────────────────────────────
    output_dir = Path(OUTPUT_DIR).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Sync each database ────────────────────────────────────────────────────
    errors = 0
    for db in databases:
        try:
            sync_database(db, output_dir)
        except Exception as exc:
            log.error("Failed to sync database %s: %s", db.get("id"), exc, exc_info=True)
            errors += 1

    log.info("Sync complete. %d database(s) processed, %d error(s).", len(databases), errors)


if __name__ == "__main__":
    main()
