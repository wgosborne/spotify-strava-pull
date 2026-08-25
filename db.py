import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    """Get a Postgres connection using DATABASE_URL from .env"""
    if not DATABASE_URL:
        print("Warning: DATABASE_URL not set")
        return None
    return psycopg2.connect(DATABASE_URL)


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
