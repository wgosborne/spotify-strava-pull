#!/usr/bin/env python3
"""
One-off backfill script to load Spotify extended streaming history JSON files into the plays table.
Reads all Streaming_History_Audio_*.json files from backfill/, filters to records from 2023-11-27 onward,
and batch inserts them using psycopg2.extras.execute_values for efficiency.
"""

import json
import os
import psycopg2
import psycopg2.extras
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

MIN_PLAY_MS = 5000  # Skip records with less than 5 seconds of play time
EARLIEST_STRAVA = datetime(2023, 11, 27, 0, 0, 0, tzinfo=timezone.utc)  # Earliest Strava activity (timezone-aware UTC)
BATCH_SIZE = 500  # Batch insert size


def log_backfill(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def find_audio_history_files():
    """Find all Streaming_History_Audio_*.json files in backfill/ directory."""
    backfill_dir = Path("backfill")

    if not backfill_dir.exists():
        log_backfill("Error: backfill/ directory not found")
        return []

    audio_files = sorted(backfill_dir.glob("Streaming_History_Audio_*.json"))

    if not audio_files:
        log_backfill("No Streaming_History_Audio_*.json files found in backfill/")
        return []

    return audio_files


def extract_play_info(record):
    """
    Extract play information from a Spotify history record.
    Returns (track_name, artist, played_at) or (None, None, None) if record should be skipped.
    """
    # Extract timestamp first
    ts = record.get("ts")
    if not ts:
        return None, None, None, "no_timestamp"

    # Skip records before earliest Strava activity (2023-11-27)
    try:
        play_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if play_time < EARLIEST_STRAVA:
            return None, None, None, "before_strava"
    except (ValueError, AttributeError):
        return None, None, None, "invalid_timestamp"

    # Check if play time is long enough (skip skips and very brief plays)
    ms_played = record.get("ms_played", 0)
    if ms_played < MIN_PLAY_MS:
        return None, None, None, "too_short"

    # Try music play first (master_metadata fields)
    track_name = record.get("master_metadata_track_name")
    artist = record.get("master_metadata_album_artist_name")

    if track_name and artist:
        return track_name, artist, ts, "music"

    # Fall back to podcast play (episode fields)
    track_name = record.get("episode_name")
    artist = record.get("episode_show_name")

    if track_name and artist:
        return track_name, artist, ts, "podcast"

    # No valid data
    return None, None, None, "no_metadata"


def batch_insert_plays(plays_to_insert):
    """Insert a batch of plays into the database using execute_values for efficiency."""
    if not plays_to_insert or not DATABASE_URL:
        return 0

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # Use execute_values for batch insert with ON CONFLICT DO NOTHING
        query = """
            INSERT INTO plays (track_name, artist, played_at, source)
            VALUES %s
            ON CONFLICT (track_name, artist, played_at) DO NOTHING
        """

        psycopg2.extras.execute_values(cur, query, plays_to_insert, page_size=1000)
        inserted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return inserted

    except Exception as e:
        log_backfill(f"Database error during batch insert: {e}")
        if conn:
            conn.close()
        return 0


def backfill_plays():
    """Main backfill loop: read all audio history JSON files and batch insert plays."""
    audio_files = find_audio_history_files()

    if not audio_files:
        return

    log_backfill(f"Found {len(audio_files)} Streaming_History_Audio_*.json files")
    for f in audio_files:
        log_backfill(f"  - {f.name}")
    print()

    total_records_read = 0
    total_inserted = 0
    total_duplicates = 0
    total_too_short = 0
    total_before_strava = 0
    total_no_metadata = 0

    for file_path in audio_files:
        log_backfill(f"Processing {file_path.name}...")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                records = json.load(f)

            if not isinstance(records, list):
                log_backfill(f"  Warning: {file_path.name} is not a JSON array, skipping")
                continue

            file_inserted = 0
            file_duplicates = 0
            file_too_short = 0
            file_before_strava = 0
            file_no_metadata = 0
            batch = []

            for idx, record in enumerate(records, 1):
                total_records_read += 1

                track_name, artist, played_at, reason = extract_play_info(record)

                if reason == "too_short":
                    total_too_short += 1
                    file_too_short += 1
                    continue
                elif reason == "before_strava":
                    total_before_strava += 1
                    file_before_strava += 1
                    continue
                elif reason in ("no_metadata", "no_timestamp", "invalid_timestamp"):
                    total_no_metadata += 1
                    file_no_metadata += 1
                    continue

                # Add to batch
                batch.append((track_name, artist, played_at, "spotify"))

                # Insert batch when it reaches BATCH_SIZE
                if len(batch) >= BATCH_SIZE:
                    inserted = batch_insert_plays(batch)
                    file_inserted += inserted
                    file_duplicates += len(batch) - inserted
                    total_inserted += inserted
                    total_duplicates += len(batch) - inserted
                    batch = []

                    # Log progress every 500 total records
                    if total_records_read % 500 == 0:
                        log_backfill(f"  Processed {total_records_read} records total — {total_inserted} inserted so far")

            # Insert any remaining records in the batch
            if batch:
                inserted = batch_insert_plays(batch)
                file_inserted += inserted
                file_duplicates += len(batch) - inserted
                total_inserted += inserted
                total_duplicates += len(batch) - inserted

            log_backfill(f"  {file_path.name}: {file_inserted} inserted, {file_duplicates} duplicates, {file_too_short} too short, {file_before_strava} before Strava, {file_no_metadata} no metadata")

        except json.JSONDecodeError as e:
            log_backfill(f"  Error: Failed to parse JSON in {file_path.name}: {e}")
        except Exception as e:
            log_backfill(f"  Error: Failed to process {file_path.name}: {e}")

    # Print final summary
    print()
    print("=" * 70)
    print("PLAYS BACKFILL COMPLETE")
    print("=" * 70)
    print(f"Total records read:        {total_records_read}")
    print(f"Inserted:                  {total_inserted}")
    print(f"Skipped (duplicates):      {total_duplicates}")
    print(f"Skipped (too short):       {total_too_short}")
    print(f"Skipped (before Strava):   {total_before_strava}")
    print(f"Skipped (no metadata):     {total_no_metadata}")
    print("=" * 70)


if __name__ == "__main__":
    backfill_plays()
