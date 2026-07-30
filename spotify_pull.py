import os
import webbrowser
import json
import requests
import time
from datetime import datetime
from dotenv import load_dotenv, dotenv_values
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import db

load_dotenv()
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:8080/callback"

def log_poll(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

auth_code = None

# Refresh tokens last much longer than access tokens (~1 hour), so we reuse them
def refresh_access_token():
    refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")
    if not refresh_token:
        raise ValueError("No refresh token found in .env - need to do full login flow first")

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
        env_file = ".env"
        new_token = new_token_data['refresh_token']

        lines = []
        if os.path.exists(env_file):
            with open(env_file, "r") as f:
                lines = f.readlines()

        updated_lines = [line for line in lines if not line.startswith("SPOTIFY_REFRESH_TOKEN=")]
        updated_lines.append(f"SPOTIFY_REFRESH_TOKEN={new_token}\n")

        with open(env_file, "w") as f:
            f.writelines(updated_lines)

    return new_access_token

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        auth_code = query_params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>Authorization successful! You can close this window.</h1>")

    def log_message(self, format, *args):
        pass

scopes = "user-read-recently-played user-top-read user-read-currently-playing user-read-playback-state"
auth_url = f"https://accounts.spotify.com/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&scope={scopes}"

webbrowser.open(auth_url)

server = HTTPServer(("127.0.0.1", 8080), CallbackHandler)
print("Listening for Spotify callback on http://127.0.0.1:8080...")
server.handle_request()

print("Exchanging code for access token...")
token_response = requests.post(
    "https://accounts.spotify.com/api/token",
    data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    },
)
token_data = token_response.json()
access_token = token_data["access_token"]

# Persist refresh token so we don't need to re-auth each run
refresh_token = token_data.get("refresh_token")
if refresh_token:
    env_file = ".env"

    lines = []
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            lines = f.readlines()

    updated_lines = [line for line in lines if not line.startswith("SPOTIFY_REFRESH_TOKEN=")]
    updated_lines.append(f"SPOTIFY_REFRESH_TOKEN={refresh_token}\n")

    with open(env_file, "w") as f:
        f.writelines(updated_lines)
    print("Saved refresh token to .env")

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

# Simple sleep loop instead of scheduler lib—keeps dependencies minimal
print("Starting polling loop (check for new plays every 30 seconds)...")
while True:
    poll()
    time.sleep(30)
