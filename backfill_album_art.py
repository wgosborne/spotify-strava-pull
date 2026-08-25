import os
import asyncio
import httpx
import time
from datetime import datetime
from dotenv import load_dotenv
import db

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

def log_backfill(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def get_spotify_access_token():
    """Get a fresh Spotify access token using the refresh token from database."""
    refresh_token = db.get_refresh_token('spotify')
    if not refresh_token:
        raise ValueError("No refresh token found in database - need to do full login flow first")

    response = httpx.post(
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

def get_matched_songs_needing_art():
    """Query for distinct (track_name, artist) pairs that have NULL album_art_url and appear in matched splits."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set")
        return []

    conn = None
    try:
        conn = db.get_connection()
        if not conn:
            return []

        cur = conn.cursor()
        # Find distinct songs with NULL album_art_url that appear in matched splits
        cur.execute("""
            SELECT DISTINCT p.track_name, p.artist
            FROM plays p
            JOIN activities a ON p.played_at >= a.start_date + (interval '1 second' * 0)
            JOIN splits s ON s.activity_id = a.strava_id
            WHERE p.album_art_url IS NULL
              AND p.played_at >= a.start_date + (interval '1 second' * s.start_offset_seconds)
              AND p.played_at < a.start_date + (interval '1 second' * (s.start_offset_seconds + s.elapsed_time))
              AND s.distance >= 400
              AND s.average_speed <= 5.03
            ORDER BY p.track_name, p.artist
        """)

        results = cur.fetchall()
        cur.close()
        conn.close()
        return results
    except Exception as e:
        print(f"Database error querying matched songs: {e}")
        if conn:
            conn.close()
        return []

async def search_spotify_album_art(client, track_name, artist, access_token, semaphore, max_retries=3):
    """Search Spotify API for a track and extract the album art URL. Handles 429 with backoff."""
    async with semaphore:
        for attempt in range(max_retries):
            try:
                query = f"track:{track_name} artist:{artist}"
                response = await client.get(
                    "https://api.spotify.com/v1/search",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"q": query, "type": "track", "limit": 1}
                )

                if response.status_code == 401:
                    return track_name, artist, None, "token_expired"

                if response.status_code == 429:
                    # Rate limited, back off and retry
                    retry_after = int(response.headers.get("Retry-After", "1"))
                    log_backfill(f"  ⏸  429 Rate limit hit, backing off {retry_after}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_after + 0.5)
                    continue

                if response.status_code != 200:
                    return track_name, artist, None, f"http_{response.status_code}"

                data = response.json()
                tracks = data.get("tracks", {}).get("items", [])

                if not tracks:
                    return track_name, artist, None, "no_match"

                # Get first result's album art
                first_track = tracks[0]
                images = first_track.get("album", {}).get("images", [])
                if images:
                    album_art_url = images[0].get("url")
                    return track_name, artist, album_art_url, "found"
                else:
                    return track_name, artist, None, "no_images"

            except Exception as e:
                return track_name, artist, None, f"error: {str(e)}"

        # All retries exhausted
        return track_name, artist, None, "max_retries_exceeded"

def update_album_art_for_song(track_name, artist, album_art_url):
    """Update all plays with the given track_name and artist with the album_art_url."""
    if not DATABASE_URL:
        return 0

    conn = None
    try:
        conn = db.get_connection()
        if not conn:
            return 0

        cur = conn.cursor()
        cur.execute(
            "UPDATE plays SET album_art_url = %s WHERE track_name = %s AND artist = %s AND album_art_url IS NULL",
            (album_art_url, track_name, artist)
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return updated
    except Exception as e:
        print(f"Database error updating album art: {e}")
        if conn:
            conn.close()
        return 0

async def backfill_album_art():
    """Main backfill routine with concurrent API calls."""
    log_backfill("Starting concurrent album art backfill for songs in matched splits")

    # Get list of songs needing art
    songs = get_matched_songs_needing_art()
    if not songs:
        log_backfill("No songs found needing album art backfill")
        return

    log_backfill(f"Found {len(songs)} distinct songs needing album art lookup")

    # Get access token
    try:
        access_token = get_spotify_access_token()
    except ValueError as e:
        log_backfill(f"Error: {e}")
        return

    stats = {
        "total": len(songs),
        "found": 0,
        "not_found": 0,
        "errors": 0,
        "processed": 0,
    }

    # Create semaphore to limit concurrency to 5
    semaphore = asyncio.Semaphore(5)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Create tasks for all songs
        tasks = [
            search_spotify_album_art(client, track_name, artist, access_token, semaphore)
            for track_name, artist in songs
        ]

        # Execute all tasks concurrently and process results as they complete
        for coro in asyncio.as_completed(tasks):
            track_name, artist, album_art_url, status = await coro

            stats["processed"] += 1

            if status == "token_expired":
                log_backfill(f"[{stats['processed']}/{len(songs)}] Token expired, refreshing...")
                try:
                    access_token = get_spotify_access_token()
                    # Retry this specific song
                    track_name, artist, album_art_url, status = await search_spotify_album_art(
                        client, track_name, artist, access_token, semaphore
                    )
                except ValueError as e:
                    log_backfill(f"  Error refreshing token: {e}")
                    stats["errors"] += 1
                    continue

            if status == "found":
                updated_count = update_album_art_for_song(track_name, artist, album_art_url)
                log_backfill(f"[{stats['processed']}/{len(songs)}] ✓ \"{track_name}\" by {artist} - updated {updated_count} plays")
                stats["found"] += 1
            else:
                log_backfill(f"[{stats['processed']}/{len(songs)}] ✗ \"{track_name}\" by {artist} ({status})")
                stats["not_found"] += 1

    log_backfill("")
    log_backfill("=== Backfill Summary ===")
    log_backfill(f"Total distinct songs processed: {stats['total']}")
    log_backfill(f"Album art found: {stats['found']}")
    log_backfill(f"Not found / errors: {stats['not_found']}")
    log_backfill("Backfill complete!")

if __name__ == "__main__":
    asyncio.run(backfill_album_art())
