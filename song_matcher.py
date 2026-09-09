import os
import requests
from datetime import datetime
from dotenv import load_dotenv
import db

load_dotenv()
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
OVERRIDE_ACTIVITY_ID = os.getenv("OVERRIDE_ACTIVITY_ID")
if OVERRIDE_ACTIVITY_ID:
    OVERRIDE_ACTIVITY_ID = int(OVERRIDE_ACTIVITY_ID)

def log_poll(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def format_pace(avg_speed_ms):
    """Convert average speed (m/s) to pace string (min:sec per mile)."""
    avg_speed_ms = float(avg_speed_ms)
    if avg_speed_ms <= 0:
        return "N/A"
    miles_per_second = avg_speed_ms / 1609.34
    seconds_per_mile = 1.0 / miles_per_second
    minutes = int(seconds_per_mile // 60)
    seconds = int(seconds_per_mile % 60)
    return f"{minutes}:{seconds:02d}"

access_token = None
expires_at = None

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


def match_and_update_activities():
    """Match songs to splits for activities and update Strava descriptions."""
    global access_token, expires_at

    # Ensure token is fresh
    if access_token is None or expires_at is None or datetime.now().timestamp() > expires_at:
        log_poll("Token expired or not set, refreshing...")
        access_token = refresh_access_token()

    if DRY_RUN:
        log_poll("[DRY RUN MODE] No changes will be written to Strava or database")

    log_poll("Matching songs to splits...")

    # If OVERRIDE_ACTIVITY_ID is set, fetch only that activity; otherwise get all unmatched
    if OVERRIDE_ACTIVITY_ID:
        log_poll(f"[OVERRIDE] Fetching activity {OVERRIDE_ACTIVITY_ID} for testing")
        activity = db.get_activity_by_id(OVERRIDE_ACTIVITY_ID)
        if activity:
            activities_to_match = activity
        else:
            log_poll(f"Activity {OVERRIDE_ACTIVITY_ID} not found")
            return
    else:
        activities_to_match = db.get_activities_needing_song_match()

    if not activities_to_match:
        log_poll("No activities needing song matches")
        return

    matched_count = 0
    for strava_id, activity_name, start_date in activities_to_match:
        # Get top 4 splits with songs
        match_result = db.get_top_splits_with_songs(strava_id)
        if not match_result or not match_result.get("splits"):
            continue

        splits = match_result.get("splits", [])

        # Fetch current description from Strava
        try:
            activity_detail_response = requests.get(
                f"https://www.strava.com/api/v3/activities/{strava_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if activity_detail_response.status_code == 401:
                log_poll("Access token expired while fetching activity, refreshing...")
                access_token = refresh_access_token()
                activity_detail_response = requests.get(
                    f"https://www.strava.com/api/v3/activities/{strava_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )

            activity_detail = activity_detail_response.json()
            current_description = activity_detail.get("description") or ""
        except Exception as e:
            log_poll(f'  Warning: Could not fetch current description for "{activity_name}": {e}')
            continue

        # Build updated description with new format
        description_lines = []

        # Add fastest split (rank 1)
        fastest = splits[0]
        pace = format_pace(fastest["average_speed"])
        if fastest["song"]:
            song_line = f"Fastest split ({pace}/mi): \"{fastest['song']['track_name']}\" by {fastest['song']['artist']}"
        else:
            song_line = f"Fastest split ({pace}/mi): [no song playing]"
        description_lines.append(song_line)

        # Collect songs and artists from ranks 2-4 (only those with matches)
        sotd_songs = []
        aotd_artists = []
        for split in splits[1:4]:
            if split["song"]:
                sotd_songs.append(split["song"]["track_name"])
                aotd_artists.append(split["song"]["artist"])

        # Add SOTD and AOTD lines only if there are songs in ranks 2-4
        if sotd_songs:
            sotd_line = "SOTD: " + ", ".join(f'"{song}"' for song in sotd_songs)
            aotd_line = "AOTD: " + ", ".join(aotd_artists)
            description_lines.append(sotd_line)
            description_lines.append(aotd_line)

        song_section = "\n".join(description_lines)

        if current_description:
            updated_description = f"{current_description}\n\n{song_section}"
        else:
            updated_description = song_section

        if DRY_RUN:
            separator = "*" * 50
            log_poll(separator)
            log_poll(f'DRY RUN — "{activity_name}"')
            log_poll(separator)
            log_poll("New description:")
            for line in updated_description.split("\n"):
                log_poll(line)
            log_poll(separator)
            matched_count += 1
        else:
            # Update description on Strava
            try:
                update_response = requests.put(
                    f"https://www.strava.com/api/v3/activities/{strava_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"description": updated_description},
                )

                if update_response.status_code == 401:
                    log_poll("Access token expired while updating Strava, refreshing...")
                    access_token = refresh_access_token()
                    update_response = requests.put(
                        f"https://www.strava.com/api/v3/activities/{strava_id}",
                        headers={"Authorization": f"Bearer {access_token}"},
                        json={"description": updated_description},
                    )

                if update_response.status_code in (200, 201):
                    db.update_song_matched(strava_id)
                    fastest_song = splits[0].get("song")
                    if fastest_song:
                        log_poll(f'  Matched: "{activity_name}" — {fastest_song["track_name"]} by {fastest_song["artist"]}')
                    else:
                        log_poll(f'  Matched: "{activity_name}" (fastest split)')
                    matched_count += 1
                else:
                    log_poll(f'  Warning: Failed to update Strava for "{activity_name}": HTTP {update_response.status_code}')

            except Exception as e:
                log_poll(f'  Warning: Could not update Strava for "{activity_name}": {e}')

    if matched_count > 0:
        log_poll(f"Song matching complete — {matched_count} activities updated")


if __name__ == "__main__":
    access_token = refresh_access_token()
    match_and_update_activities()
