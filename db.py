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


def insert_play(track_name, artist, played_at, source):
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
            "INSERT INTO plays (track_name, artist, played_at, source) VALUES (%s, %s, %s, %s) ON CONFLICT (track_name, artist, played_at) DO NOTHING RETURNING id",
            (track_name, artist, played_at, source)
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


def insert_activity(strava_id, name, distance, moving_time, average_speed, start_date):
    """Insert a single activity into the activities table. Returns True if inserted, False if duplicate. Logs errors and continues on failure."""
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
            "INSERT INTO activities (strava_id, name, distance, moving_time, average_speed, start_date) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (strava_id) DO NOTHING RETURNING id",
            (strava_id, name, distance, moving_time, average_speed, start_date)
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
