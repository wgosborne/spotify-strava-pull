import os
import time
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    """Get a Postgres connection using DATABASE_URL from .env. Retries up to 3 times with exponential backoff to handle Neon cold-start connection drops."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set")
        return None

    max_retries = 3
    backoff_delays = [2, 4]

    for attempt in range(max_retries):
        try:
            return psycopg2.connect(DATABASE_URL)
        except psycopg2.OperationalError as e:
            if attempt < max_retries - 1:
                delay = backoff_delays[attempt]
                print(f"Connection failed (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print(f"Connection failed (attempt {attempt + 1}/{max_retries}): {e}")
                raise


def insert_play(track_name, artist, played_at, source, album_art_url=None):
    """Insert a single play into the plays table. Returns True if inserted, False if duplicate. Logs errors and continues on failure."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set, skipping database write")
        return False

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return False

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO plays (track_name, artist, played_at, source, album_art_url) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (track_name, artist, played_at) DO NOTHING RETURNING id",
            (track_name, artist, played_at, source, album_art_url)
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return result is not None
    except Exception as e:
        print(f"Database error: {e}")
        if conn:
            conn.close()
        return False


def insert_activity(strava_id, name, distance, moving_time, average_speed, start_date, description=None):
    """Insert or update activity. Returns (success: bool, was_insert: bool). success=True means a row was returned (new insert OR real change applied), False means no-op (identical duplicate)."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set, skipping database write")
        return (False, False)

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return (False, False)

        cur = conn.cursor()
        cur.execute(
            """INSERT INTO activities (strava_id, name, distance, moving_time, average_speed, start_date, description)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (strava_id) DO UPDATE SET
                 name = EXCLUDED.name,
                 description = EXCLUDED.description
               WHERE activities.name IS DISTINCT FROM EXCLUDED.name
                  OR activities.description IS DISTINCT FROM EXCLUDED.description
               RETURNING id, (xmax = 0) AS was_insert""",
            (strava_id, name, distance, moving_time, average_speed, start_date, description)
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if result is not None:
            activity_id, was_insert = result
            return (True, was_insert)
        return (False, False)
    except Exception as e:
        print(f"Database error: {e}")
        if conn:
            conn.close()
        return (False, False)


def insert_split(activity_id, split_number, distance, elapsed_time, average_speed, start_offset_seconds):
    """Insert a single split into the splits table. Returns True if inserted, False if duplicate. Logs errors and continues on failure."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set, skipping database write")
        return False

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return False

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO splits (activity_id, split_number, distance, elapsed_time, average_speed, start_offset_seconds) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (activity_id, split_number) DO NOTHING RETURNING id",
            (activity_id, split_number, distance, elapsed_time, average_speed, start_offset_seconds)
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return result is not None
    except Exception as e:
        print(f"Database error: {e}")
        if conn:
            conn.close()
        return False


def get_refresh_token(service):
    """Get the refresh token for a given service from app_tokens table."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set")
        return None

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return None

        cur = conn.cursor()
        cur.execute("SELECT refresh_token FROM app_tokens WHERE service = %s", (service,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        print(f"Database error reading refresh token: {e}")
        if conn:
            conn.close()
        return None


def save_refresh_token(service, refresh_token):
    """Update the refresh token and updated_at timestamp for a service in app_tokens."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set, skipping refresh token update")
        return False

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return False

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO app_tokens (service, refresh_token, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (service) DO UPDATE SET refresh_token = EXCLUDED.refresh_token, updated_at = NOW()",
            (service, refresh_token)
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Database error saving refresh token: {e}")
        if conn:
            conn.close()
        return False


def get_activities_missing_description():
    """Get all activities with missing/NULL description since 2026-07-04. Returns list of (strava_id, name) tuples."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set")
        return []

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return []

        cur = conn.cursor()
        cur.execute(
            "SELECT strava_id, name FROM activities WHERE (description IS NULL OR description = '') AND start_date >= '2026-07-04 00:37:42+00' ORDER BY start_date DESC"
        )
        results = cur.fetchall()
        cur.close()
        conn.close()
        return results if results else []
    except Exception as e:
        print(f"Database error reading activities: {e}")
        if conn:
            conn.close()
        return []


def update_activity_description(strava_id, description):
    """Update the description for an existing activity. Returns True if successful."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set, skipping database write")
        return False

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return False

        cur = conn.cursor()
        cur.execute(
            "UPDATE activities SET description = %s WHERE strava_id = %s",
            (description, strava_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Database error: {e}")
        if conn:
            conn.close()
        return False


def get_activity_by_id(strava_id):
    """Get a single activity by its strava_id, regardless of song_matched value. Returns list of one (strava_id, name, start_date) tuple, or empty list if not found."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set")
        return []

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return []

        cur = conn.cursor()
        cur.execute(
            "SELECT strava_id, name, start_date FROM activities WHERE strava_id = %s",
            (strava_id,)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        return [result] if result else []
    except Exception as e:
        print(f"Database error reading activity: {e}")
        if conn:
            conn.close()
        return []


def get_activities_needing_song_match():
    """Get activities where song_matched = FALSE from the last 7 days, ordered by start_date DESC. Returns list of (strava_id, name, start_date) tuples."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set")
        return []

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return []

        cur = conn.cursor()
        cur.execute(
            "SELECT strava_id, name, start_date FROM activities WHERE song_matched = FALSE AND start_date >= NOW() - INTERVAL '7 days' ORDER BY start_date DESC"
        )
        results = cur.fetchall()
        cur.close()
        conn.close()
        return results if results else []
    except Exception as e:
        print(f"Database error reading activities: {e}")
        if conn:
            conn.close()
        return []


def get_top_splits_with_songs(activity_id):
    """Get top 4 fastest splits for an activity and find the first song during each split's time window.

    Returns dict: {"splits": [
      {"split_number": int, "average_speed": float, "song": {"track_name": str, "artist": str} or None},
      ...
    ]}

    Returns empty dict {} if no activity or splits found.
    """
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set")
        return {}

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return {}

        cur = conn.cursor()
        # Get top 4 fastest splits (by average_speed DESC) with speed sanity filter
        cur.execute(
            """
            SELECT
              s.split_number,
              s.average_speed,
              s.distance,
              s.start_offset_seconds,
              s.elapsed_time,
              a.start_date
            FROM splits s
            JOIN activities a ON s.activity_id = a.strava_id
            WHERE
              s.activity_id = %s
              AND s.average_speed <= 8.94
            ORDER BY s.average_speed DESC
            LIMIT 4
            """,
            (activity_id,)
        )
        split_results = cur.fetchall()

        if not split_results:
            cur.close()
            conn.close()
            return {}

        from datetime import timedelta
        splits_data = []
        for split_number, avg_speed, distance, offset_secs, elapsed_time, start_date in split_results:
            # Calculate time window for this split
            split_start = start_date.replace(tzinfo=None) if start_date.tzinfo else start_date
            split_start_ts = split_start + timedelta(seconds=offset_secs)
            split_end_ts = split_start_ts + timedelta(seconds=elapsed_time)

            # Get first play during this time window
            cur.execute(
                """
                SELECT track_name, artist FROM plays
                WHERE played_at >= %s AND played_at <= %s
                ORDER BY played_at ASC
                LIMIT 1
                """,
                (split_start_ts, split_end_ts)
            )
            play = cur.fetchone()

            song = None
            if play:
                song = {"track_name": play[0], "artist": play[1]}

            splits_data.append({
                "split_number": split_number,
                "average_speed": avg_speed,
                "song": song
            })

        cur.close()
        conn.close()

        return {"splits": splits_data}
    except Exception as e:
        print(f"Database error: {e}")
        if conn:
            conn.close()
        return {}


def update_song_matched(strava_id):
    """Mark an activity as having been matched with a song. Returns True if successful."""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set, skipping database write")
        return False

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return False

        cur = conn.cursor()
        cur.execute(
            "UPDATE activities SET song_matched = TRUE WHERE strava_id = %s",
            (strava_id,)
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Database error: {e}")
        if conn:
            conn.close()
        return False
