import os
import webbrowser
import requests
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import db

load_dotenv()
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8080/callback"

auth_code = None

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

scope = "activity:read_all,activity:write"
auth_url = f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&scope={scope}"

webbrowser.open(auth_url)

server = HTTPServer(("localhost", 8080), CallbackHandler)
print("Listening for Strava callback on http://localhost:8080...")
server.handle_request()

print("Exchanging code for access token...")
token_response = requests.post(
    "https://www.strava.com/api/v3/oauth/token",
    data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": auth_code,
        "grant_type": "authorization_code",
    },
)
token_data = token_response.json()
access_token = token_data["access_token"]
refresh_token = token_data.get("refresh_token")

if access_token:
    env_file = ".env"

    lines = []
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            lines = f.readlines()

    updated_lines = [line for line in lines if not line.startswith("STRAVA_ACCESS_TOKEN=") and not line.startswith("STRAVA_REFRESH_TOKEN=")]
    updated_lines.append(f"STRAVA_ACCESS_TOKEN={access_token}\n")
    if refresh_token:
        updated_lines.append(f"STRAVA_REFRESH_TOKEN={refresh_token}\n")

    with open(env_file, "w") as f:
        f.writelines(updated_lines)
    print("Saved access token and refresh token to .env")

    if refresh_token:
        db.save_refresh_token('strava', refresh_token)
        print("Saved refresh token to Postgres")

    print("Strava authentication complete!")
