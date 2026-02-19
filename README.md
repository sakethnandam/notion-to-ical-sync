# 📅 Notion → Calendar Sync

Sync any Notion database with a date property to your calendar. Automatically. Every 5 minutes.

Works with Apple Calendar, Google Calendar, Outlook, or anything that supports iCal subscriptions.

> 📹 *Video walkthrough coming soon*

---

## How It Works

```
Notion Database  →  notion_to_ical.py  →  .ics file  →  serve_ical.py  →  Your Calendar App
                     (runs every 5 min)                  (localhost:8080)
```

Each Notion **page** becomes a calendar **event**. The title, date, and any notes field are pulled in automatically. Pages without a date are skipped.

---

## Setup

### 1. Install dependencies

```bash
git clone https://github.com/your-username/notion-ical-sync.git
cd notion-ical-sync
python3 -m venv venv
source venv/bin/activate
pip install requests icalendar python-dotenv
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Fill in three things:

```
NOTION_TOKEN=secret_yourtoken
OUTPUT_DIR=/Users/yourname/NotionCalendars
NOTION_DATABASES=[{"id":"your-database-id","name":"My Calendar"}]
```

### 3. Get your Notion token

Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New integration** → copy the token. Then open your Notion database → **"..." → Connections** → connect your integration.

### 4. Get your database ID

It's in the URL:
```
notion.so/myworkspace/THIS-PART-HERE?v=...
```

### 5. Run it

```bash
python3 notion_to_ical.py   # generates .ics files
python3 serve_ical.py       # starts local server at localhost:8080
```

### 6. Subscribe in your calendar app

| App | How to subscribe |
|---|---|
| **Apple Calendar** | File → New Calendar Subscription → `http://localhost:8080/My Calendar.ics` |
| **Google Calendar** | Other calendars → From URL → same URL |
| **Outlook** | Add calendar → From internet → same URL |

Set refresh to **every 5 minutes**.

### 7. Automate it (macOS)

Edit both `.plist` files — replace `sakethnandam` with your username (`whoami` in Terminal) — then:

```bash
cp com.notion.ical.sync.plist ~/Library/LaunchAgents/
cp com.notion.ical.server.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.notion.ical.sync.plist
launchctl load ~/Library/LaunchAgents/com.notion.ical.server.plist
```

**On Windows?** Use Task Scheduler. **On Linux?** Use `cron`.

---

## Adding a New Database

1. Share it with your integration (Notion → **"..." → Connections**)
2. Add it to `NOTION_DATABASES` in `.env`:
   ```
   NOTION_DATABASES=[
     {"id":"existing-id","name":"Work"},
     {"id":"new-id-here","name":"New Calendar"}
   ]
   ```
3. Run `python3 notion_to_ical.py` and subscribe in your calendar app

---

## Using With Google Calendar or Outlook

The `.ics` files are standard — any calendar app can use them. The catch is that `localhost:8080` is only reachable from your own machine.

**If you want Google Calendar or Outlook to subscribe**, you need the files hosted somewhere public:

- **Easiest:** Upload `.ics` files to Dropbox/Google Drive and use the public share link
- **More robust:** Host on a VPS or home server with a public URL
- **Simplest for personal use:** Just keep Apple Calendar as the bridge — it syncs to iCloud which flows to your other devices

---

## Logs & Debugging

```bash
tail -f sync.log                                    # live sync log
tail -f ~/Library/Logs/notion-ical-sync-error.log  # launchd errors
```

| Problem | Fix |
|---|---|
| `401 Unauthorized` | Token is wrong — re-copy from Notion |
| `404` on database | Share the database with your integration |
| Events missing | Check the page has a date field filled in |
| Calendar URL not loading | `serve_ical.py` isn't running |

---

## FAQ

**How long until changes in Notion show up?**
Up to ~10 minutes (5 min sync + 5 min calendar refresh).

**Will edits create duplicate events?**
No — events use a stable ID tied to the Notion page, so edits update in place.

**Can I sync multiple databases?**
Yes — add as many entries as you want to `NOTION_DATABASES`. Each gets its own calendar.

**Is this accessible to others on my network?**
No — the server only listens on `127.0.0.1` (your machine only).

**How do I remove a calendar?**
Delete it from `NOTION_DATABASES`, delete the `.ics` file, and unsubscribe in your calendar app.
