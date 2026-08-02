import os
import requests
from datetime import datetime
from dotenv import load_dotenv
import db

load_dotenv()
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:8080/callback"

def log_poll(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

# Refresh tokens last much longer than access tokens (~1 hour), so we reuse them
def refresh_access_token():
    refresh_token = db.get_refresh_token('spotify')
    if not refresh_token:
        raise ValueError("No refresh token found in database - need to do full login flow first")

    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )

    new_token_data = response.json()
    new_access_token = new_token_data["access_token"]

    if "refresh_token" in new_token_data:
        db.save_refresh_token('spotify', new_token_data['refresh_token'])

    return new_access_token

access_token = None
last_processed_timestamp = None

# Wrapped in function so it can be called repeatedly without re-auth
def poll():
    global access_token, last_processed_timestamp
    recently_played = requests.get(
        "https://api.spotify.com/v1/me/player/recently-played",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    # 401 means token expired; refresh and retry once
    if recently_played.status_code == 401:
        print("Access token expired, refreshing...")
        access_token = refresh_access_token()
        recently_played = requests.get(
            "https://api.spotify.com/v1/me/player/recently-played",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    output_data = recently_played.json()

    # Filter for new songs (only those with played_at later than last processed)
    all_items = output_data.get("items", [])
    new_items = []

    if all_items:
        newest_timestamp = None
        for item in all_items:
            played_at = item.get("played_at")
            if played_at:
                if newest_timestamp is None:
                    newest_timestamp = played_at

                # Include if we haven't processed any songs yet, or if played_at is newer
                if last_processed_timestamp is None or played_at > last_processed_timestamp:
                    new_items.append(item)

        # Update tracking to the newest timestamp we saw this poll
        if newest_timestamp:
            last_processed_timestamp = newest_timestamp

    already_seen = len(all_items) - len(new_items)
    log_poll(f"Polled Spotify — {len(new_items)} new detected, {already_seen} already seen")

    if new_items:
        for item in new_items:
            track_name = item.get("track", {}).get("name", "Unknown")
            artist_name = item.get("track", {}).get("artists", [{}])[0].get("name", "Unknown")
            log_poll(f'  -> New: "{track_name}" by {artist_name}')

        inserted_count = 0
        for item in new_items:
            track_name = item.get("track", {}).get("name", "Unknown")
            artist_name = item.get("track", {}).get("artists", [{}])[0].get("name", "Unknown")
            played_at = item.get("played_at")
            if db.insert_play(track_name, artist_name, played_at, "spotify"):
                inserted_count += 1

        duplicate_count = len(new_items) - inserted_count
        if duplicate_count > 0:
            log_poll(f"Stored {inserted_count} plays, {duplicate_count} duplicates skipped")

access_token = refresh_access_token()
poll()
