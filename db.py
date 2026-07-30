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
