import os
import requests
from datetime import datetime
from dotenv import load_dotenv
import db

load_dotenv()
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")

def log_poll(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

access_token = None
expires_at = None  # Will be set from token response; tracks expiry as Unix timestamp
last_processed_activity_id = None

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

def fetch_and_store_splits(activity_id, activity_name):
    """Fetch splits for an activity and store them in the database."""
    global access_token

    try:
        # Fetch detailed activity data (includes splits)
        activity_detail_response = requests.get(
            f"https://www.strava.com/api/v3/activities/{activity_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if activity_detail_response.status_code == 401:
            log_poll("Access token expired while fetching splits, refreshing...")
            refresh_access_token()
            activity_detail_response = requests.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        activity_detail = activity_detail_response.json()
        splits = activity_detail.get("splits_metric", [])

        if splits:
            start_offset_seconds = 0
            inserted_count = 0
            for split_number, split in enumerate(splits, 1):
                distance = split.get("distance", 0)  # in meters
                elapsed_time = split.get("elapsed_time", 0)  # in seconds
                average_speed = split.get("average_speed", 0)  # in m/s

                if db.insert_split(activity_id, split_number, distance, elapsed_time, average_speed, start_offset_seconds):
                    inserted_count += 1

                # Next split starts after this one finishes
                start_offset_seconds += elapsed_time

            duplicate_count = len(splits) - inserted_count
            if duplicate_count > 0:
                log_poll(f'  Stored {inserted_count} splits for "{activity_name}", {duplicate_count} duplicates skipped')
            else:
                log_poll(f'  Stored {inserted_count} splits for "{activity_name}"')
        else:
            log_poll(f'  No splits found for "{activity_name}"')

    except Exception as e:
        log_poll(f"  Warning: Could not fetch splits for activity {activity_id}: {e}")

def poll():
    """Fetch recent activities from Strava and insert new ones into database."""
    global access_token, expires_at, last_processed_activity_id

    # Check if token is expired and refresh if needed
    if expires_at is None or datetime.now().timestamp() > expires_at:
        log_poll("Access token expired or not set, refreshing...")
        refresh_access_token()

    activities_response = requests.get(
        "https://www.strava.com/api/v3/athlete/activities",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    # 401 means token expired; refresh and retry once
    if activities_response.status_code == 401:
        log_poll("Access token expired, refreshing...")
        refresh_access_token()
        activities_response = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    output_data = activities_response.json()

    # Filter for new activities (only those with ID later than last processed)
    all_items = output_data if isinstance(output_data, list) else []
    new_items = []

    if all_items:
        for item in all_items:
            activity_id = item.get("id")

            # Include if we haven't processed any activities yet, or if ID is newer
            if last_processed_activity_id is None or activity_id > last_processed_activity_id:
                new_items.append(item)

        # Update tracking to the newest (highest) ID we saw this poll
        if all_items:
            last_processed_activity_id = all_items[0].get("id")  # First item is newest

    already_seen = len(all_items) - len(new_items)
    log_poll(f"Polled Strava — {len(new_items)} new detected, {already_seen} already seen")

    if new_items:
        for item in new_items:
            activity_name = item.get("name", "Unknown")
            activity_type = item.get("type", "Unknown")
            log_poll(f'  -> New: "{activity_name}" ({activity_type})')

        inserted_count = 0
        for item in new_items:
            strava_id = item.get("id")
            name = item.get("name", "Unknown")
            distance = item.get("distance", 0)  # in meters
            moving_time = item.get("moving_time", 0)  # in seconds
            average_speed = item.get("average_speed", 0)  # in m/s
            start_date = item.get("start_date")
            if db.insert_activity(strava_id, name, distance, moving_time, average_speed, start_date):
                inserted_count += 1
                # Fetch and store splits for this activity (only if newly inserted)
                fetch_and_store_splits(strava_id, name)

        duplicate_count = len(new_items) - inserted_count
        if duplicate_count > 0:
            log_poll(f"Stored {inserted_count} activities, {duplicate_count} duplicates skipped")

refresh_access_token()
poll()
