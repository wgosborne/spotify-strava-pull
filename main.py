import sys
from datetime import datetime
import strava_pull
import spotify_pull
import song_matcher

def log_poll(message):
    """Log with timestamp in format [HH:MM:SS]"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def run_pipeline():
    """Run the complete polling and matching pipeline."""
    log_poll("=== Pipeline Start ===")

    # Step 1: Poll Strava
    try:
        log_poll("Step 1/3: Running Strava poll...")
        strava_pull.run_strava_poll()
    except Exception as e:
        log_poll(f"Error in Strava poll: {e}")
        log_poll("Continuing with next step...")

    # Step 2: Poll Spotify
    try:
        log_poll("Step 2/3: Running Spotify poll...")
        spotify_pull.run_spotify_poll()
    except Exception as e:
        log_poll(f"Error in Spotify poll: {e}")
        log_poll("Continuing with next step...")

    # Step 3: Match songs and update Strava
    try:
        log_poll("Step 3/3: Running song matcher...")
        song_matcher.match_and_update_activities()
    except Exception as e:
        log_poll(f"Error in song matching: {e}")
        log_poll("Pipeline completed with errors")
        return False

    log_poll("=== Pipeline Complete ===")
    return True

if __name__ == "__main__":
    success = run_pipeline()
    sys.exit(0 if success else 1)
