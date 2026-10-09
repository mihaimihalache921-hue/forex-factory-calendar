#!/usr/bin/env python3
"""Cache the official Forex Factory weekly JSON feed in this public repo.

Only public economic-calendar data are stored. No trading-journal data.
Exit non-zero on a failed, incomplete, or malformed HTTP response.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
ROOT = Path(__file__).resolve().parents[1]
WEEK_FOLDER = ROOT / "data" / "weeks"
LATEST_FILE = ROOT / "data" / "latest.json"


def fetch() -> list[dict]:
    request = urllib.request.Request(
        FEED_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; ForexFactoryCalendarArchive/1.0)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"Unexpected HTTP {response.status}")
            payload = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Forex Factory responded with HTTP {exc.code}; keeping existing data") from exc

    if len(payload) > 2_000_000:
        raise ValueError("Response exceeds safety limit (2 MB)")

    events = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(events, list) or not events:
        raise ValueError("Empty/non-array calendar; refusing to overwrite cache")

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"Event {index} is not an object")
        required = ("title", "country", "date", "impact")
        if any(not isinstance(event.get(k), str) or not event.get(k).strip() for k in required):
            raise ValueError(f"Event {index} has missing mandatory fields")
        timestamp = datetime.fromisoformat(event["date"])
        if timestamp.tzinfo is None:
            raise ValueError(f"Event {index} has a timezone-naive timestamp")

    return events


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    events = fetch()
    source_dates = [datetime.fromisoformat(event["date"]).date() for event in events]
    first = min(source_dates)
    # The feed uses a Sunday-to-Saturday Forex Factory week.
    sunday = first - timedelta(days=(first.weekday() + 1) % 7)
    saturday = sunday + timedelta(days=6)

    # Do not silently mix records from distinct source weeks.
    if any(not sunday <= day <= saturday for day in source_dates):
        raise ValueError("Feed unexpectedly spans multiple Forex Factory weeks")

    week_key = sunday.isoformat()
    path = WEEK_FOLDER / f"{week_key}.json"
    saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    archive = {
        "source": FEED_URL,
        "week_start_source_timezone": week_key,
        "week_end_source_timezone": saturday.isoformat(),
        "dates_in_feed": [min(source_dates).isoformat(), max(source_dates).isoformat()],
        "fetched_at_utc": saved_at,
        "events": events,
    }

    changed = True
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        changed = old.get("events") != events

    if changed:
        save_json(path, archive)
        print(f"Saved {len(events)} events to {path.relative_to(ROOT)}")
    else:
        print(f"Unchanged events in {path.relative_to(ROOT)}")

    # A successful check is recorded even if the events were unchanged.
    save_json(
        LATEST_FILE,
        {
            "source": FEED_URL,
            "last_success_utc": saved_at,
            "week_start_source_timezone": week_key,
            "week_file": f"data/weeks/{week_key}.json",
            "event_count": len(events),
            "impact_counts": dict(Counter(event["impact"] for event in events)),
            "note": "Cached public source feed; not a verification of a trade or of economic-calendar completion.",
        },
    )
    print(f"Impacts: {dict(Counter(event['impact'] for event in events))}")
    print("No Google Sheets or personal trading data were accessed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, TimeoutError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
