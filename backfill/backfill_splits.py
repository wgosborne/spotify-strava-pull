#!/usr/bin/env python3
"""
One-off backfill script to fetch and insert splits for historical Strava activities.
Queries activities table for all strava_ids without splits, fetches their details from
Strava API, extracts splits_metric, and inserts into the splits table.
"""

import os
import time
import requests
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

import db

load_dotenv()
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
DATABASE_URL = os.getenv("DATABASE_URL")

access_token = None
expires_at = None


def log_backfill(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def calculate_wait_until_next_quarter_hour(buffer_seconds=12):
    """
    Calculate seconds to wait until the next 15-minute boundary (:00, :15, :30, :45),
    plus a buffer for clock drift.
    Returns (wait_seconds, target_time_with_buffer)
    """
    now = datetime.now()
    current_minute = now.minute

    # Determine next boundary minute
    if current_minute < 15:
        next_boundary_minute = 15
    elif current_minute < 30:
        next_boundary_minute = 30
    elif current_minute < 45:
        next_boundary_minute = 45
    else:  # 45 <= current_minute < 60
        next_boundary_minute = 0  # Next hour

    # Create target time at the boundary (:00 seconds)
    if next_boundary_minute == 0:
        target_time = now.replace(hour=(now.hour + 1) % 24, minute=0, second=0, microsecond=0)
    else:
        target_time = now.replace(minute=next_boundary_minute, second=0, microsecond=0)

    # Calculate time to wait (boundary time + buffer - current time)
    time_to_boundary = (target_time - now).total_seconds()
    total_wait_seconds = int(time_to_boundary) + buffer_seconds

    # Target time after buffer
    target_time_with_buffer = target_time + timedelta(seconds=buffer_seconds)

    return total_wait_seconds, target_time_with_buffer


def refresh_access_token():
    """Refresh Strava access token using refresh token. Updates expires_at."""
    global access_token, expires_at

    refresh_token = db.get_refresh_token('strava')
    if not refresh_token:
        raise ValueError("No refresh token found in database - need to run strava_auth.py first")

    response = requests.post(
        "https://www.strava.com/api/v3/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )

    token_data = response.json()
    access_token = token_data["access_token"]
    expires_at = token_data.get("expires_at")

    if "refresh_token" in token_data:
        db.save_refresh_token('strava', token_data['refresh_token'])

    return access_token


def get_activities_without_splits():
    """Query activities table for all strava_ids that don't have any splits yet."""
    if not DATABASE_URL:
        log_backfill("Error: DATABASE_URL not set")
        return []

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # Left join activities to splits; select activities with no splits
        cur.execute("""
            SELECT a.id, a.strava_id, a.name
            FROM activities a
            LEFT JOIN splits s ON s.activity_id = a.strava_id
            WHERE s.id IS NULL
            ORDER BY a.id
        """)

        results = cur.fetchall()
        cur.close()
        conn.close()
        return results

    except Exception as e:
        log_backfill(f"Error querying activities without splits: {e}")
        if conn:
            conn.close()
        return []


def fetch_and_store_splits(activity_id, strava_id, activity_name):
    """
    Fetch splits for an activity from Strava API and store them in the database.
    Returns count of splits inserted.
    """
    global access_token

    try:
        # Fetch detailed activity data (includes splits)
        activity_detail_response = requests.get(
            f"https://www.strava.com/api/v3/activities/{strava_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if activity_detail_response.status_code == 401:
            log_backfill("  Access token expired, refreshing...")
            refresh_access_token()
            activity_detail_response = requests.get(
                f"https://www.strava.com/api/v3/activities/{strava_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        # Handle rate limiting (429)
        if activity_detail_response.status_code == 429:
            current_time = datetime.now().strftime("%H:%M")
            pause_seconds, target_time = calculate_wait_until_next_quarter_hour(buffer_seconds=12)
            target_time_str = target_time.strftime("%H:%M:%S")

            log_backfill(f"Rate limited at {current_time} — waiting until {target_time_str} for next reset window")
            time.sleep(pause_seconds)

            # Retry the same activity after rate limit pause
            log_backfill(f"  Retrying activity {strava_id} after rate limit pause...")
            activity_detail_response = requests.get(
                f"https://www.strava.com/api/v3/activities/{strava_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if activity_detail_response.status_code != 200:
            log_backfill(f"  Warning: Strava API returned {activity_detail_response.status_code} for activity {strava_id}")
            return 0

        activity_detail = activity_detail_response.json()
        splits = activity_detail.get("splits_metric", [])

        if splits:
            start_offset_seconds = 0
            inserted_count = 0
            for split_number, split in enumerate(splits, 1):
                distance = split.get("distance", 0)  # in meters
                elapsed_time = split.get("elapsed_time", 0)  # in seconds
                average_speed = split.get("average_speed", 0)  # in m/s

                if db.insert_split(strava_id, split_number, distance, elapsed_time, average_speed, start_offset_seconds):
                    inserted_count += 1

                # Next split starts after this one finishes
                start_offset_seconds += elapsed_time

            duplicate_count = len(splits) - inserted_count
            if duplicate_count > 0:
                log_backfill(f'  Stored {inserted_count} splits for "{activity_name}", {duplicate_count} duplicates skipped')
            else:
                log_backfill(f'  Stored {inserted_count} splits for "{activity_name}"')

            return inserted_count
        else:
            log_backfill(f'  No splits found for "{activity_name}" (activity type may not support splits)')
            return 0

    except Exception as e:
        log_backfill(f"  Warning: Could not fetch splits for activity {strava_id}: {e}")
        return 0


def backfill_splits():
    """Main backfill loop: fetch activities without splits, query Strava API, insert splits."""
    global access_token, expires_at

    # Check if token is expired and refresh if needed
    if expires_at is None or datetime.now().timestamp() > expires_at:
        log_backfill("Access token expired or not set, refreshing...")
        refresh_access_token()

    # Get all activities without splits
    activities_without_splits = get_activities_without_splits()

    if not activities_without_splits:
        log_backfill("No activities found without splits. Backfill complete.")
        return

    total_activities = len(activities_without_splits)
    log_backfill(f"Found {total_activities} activities without splits")
    log_backfill(f"Starting backfill (will pause 1-2 seconds between API calls)...")
    print()

    total_splits_inserted = 0
    activities_with_no_splits = 0

    for idx, (activity_id, strava_id, activity_name) in enumerate(activities_without_splits, 1):
        splits_count = fetch_and_store_splits(activity_id, strava_id, activity_name)

        if splits_count == 0:
            activities_with_no_splits += 1

        total_splits_inserted += splits_count

        # Log progress every 10 activities
        if idx % 10 == 0:
            log_backfill(f"Processed {idx}/{total_activities} — {total_splits_inserted} splits inserted so far")

        # Rate limiting: 100 requests per 15 minutes = 1 request per 9 seconds max
        # Using 1-2 seconds is well under the limit
        time.sleep(1.5)

    # Print final summary
    print()
    print("=" * 60)
    print("SPLITS BACKFILL COMPLETE")
    print("=" * 60)
    print(f"Total activities processed:  {total_activities}")
    print(f"Total splits inserted:       {total_splits_inserted}")
    print(f"Activities with no splits:   {activities_with_no_splits}")
    print("=" * 60)


if __name__ == "__main__":
    backfill_splits()
