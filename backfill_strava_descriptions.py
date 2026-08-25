import os
import requests
import time
from datetime import datetime
from dotenv import load_dotenv
import db

load_dotenv()
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")

access_token = None

def log_poll(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def refresh_access_token():
    """Refresh Strava access token using refresh token."""
    global access_token

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

    if "refresh_token" in token_data:
        db.save_refresh_token('strava', token_data['refresh_token'])

    return access_token

def fetch_description_from_strava(strava_id, activity_name):
    """Fetch description for an activity from Strava. Returns description or None."""
    global access_token

    try:
        activity_detail_response = requests.get(
            f"https://www.strava.com/api/v3/activities/{strava_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if activity_detail_response.status_code == 401:
            log_poll(f"Access token expired while fetching {strava_id}, refreshing...")
            refresh_access_token()
            activity_detail_response = requests.get(
                f"https://www.strava.com/api/v3/activities/{strava_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        activity_detail = activity_detail_response.json()
        return activity_detail.get("description")

    except Exception as e:
        log_poll(f"Warning: Could not fetch description for activity {strava_id}: {e}")
        return None

def backfill():
    """Backfill missing descriptions for activities from Strava API."""
    global access_token

    log_poll("Starting description backfill...")
    refresh_access_token()

    activities = db.get_activities_missing_description()
    if not activities:
        log_poll("No activities with missing descriptions found.")
        return

    log_poll(f"Found {len(activities)} activities with missing descriptions")

    backfilled_count = 0
    no_description_count = 0

    for strava_id, name in activities:
        description = fetch_description_from_strava(strava_id, name)

        if description:
            if db.update_activity_description(strava_id, description):
                log_poll(f'  -> Backfilled "{name}" ({strava_id})')
                backfilled_count += 1
            else:
                log_poll(f'  -> Failed to update "{name}" ({strava_id})')
        else:
            log_poll(f'  -> No description found for "{name}" ({strava_id})')
            no_description_count += 1

        time.sleep(0.5)

    log_poll(f"Backfill complete: {backfilled_count} descriptions backfilled, {no_description_count} with no description on Strava")

if __name__ == "__main__":
    backfill()
