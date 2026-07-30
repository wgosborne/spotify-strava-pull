import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv("STRAVA_ACCESS_TOKEN")
CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")

if not ACCESS_TOKEN:
    print("ERROR: STRAVA_ACCESS_TOKEN not found in .env")
    exit(1)

# Build the request
url = "https://www.strava.com/api/v3/athlete/activities"
headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

print(f"Request URL: {url}")
print(f"Headers: {headers}")
print()

# Make the request
response = requests.get(url, headers=headers)

print(f"HTTP Status Code: {response.status_code}")
print()

# Print the raw response
if response.text:
    print("Response Body:")
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
        print()

        # If it's a list, show activity summary
        if isinstance(data, list):
            print(f"Total activities in response: {len(data)}")
            if data:
                print()
                print("Activities:")
                for i, activity in enumerate(data, 1):
                    name = activity.get("name", "Unknown")
                    start_date = activity.get("start_date", "Unknown")
                    activity_id = activity.get("id", "Unknown")
                    activity_type = activity.get("type", "Unknown")
                    print(f"  {i}. {name} (ID: {activity_id}, Type: {activity_type}, Date: {start_date})")
        elif isinstance(data, dict):
            if "message" in data or "errors" in data:
                print("API returned an error:")
                print(json.dumps(data, indent=2))
    except json.JSONDecodeError:
        print("Response is not valid JSON:")
        print(response.text)
else:
    print("Response Body: (empty)")
