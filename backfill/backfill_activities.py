#!/usr/bin/env python3
"""
One-off backfill script to load historical Strava activities from CSV into the database.
Reads backfill/strava_historical.csv and inserts each activity using the existing insert_activity() function.
"""

import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import db

# Try to use pandas for better CSV handling, fall back to csv module
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

# Expected column order from the SSMS export (order matters for alignment)
# raw_json, summary_polyline, and description were excluded from the export query
EXPECTED_COLUMNS = [
    "id", "name", "type", "start_date", "distance", "moving_time", "elapsed_time",
    "average_speed", "max_speed", "total_elevation_gain", "kudos_count", "comment_count",
    "gear_id", "visibility", "location_city", "location_state", "location_country",
    "start_lat", "start_lng", "end_lat", "end_lng", "athlete_id"
]

def parse_start_date(date_str):
    """
    Parse a date string and return an ISO-formatted string for Postgres.
    Handles common formats: ISO 8601, various datetime formats.
    """
    if not date_str or date_str.strip() == "":
        return None

    date_str = str(date_str).strip()

    # Try ISO format first (most common from Strava API)
    common_formats = [
        "%Y-%m-%dT%H:%M:%SZ",  # ISO with Z
        "%Y-%m-%dT%H:%M:%S.%fZ",  # ISO with microseconds and Z
        "%Y-%m-%d %H:%M:%S",  # Standard datetime
        "%Y-%m-%d %H:%M:%S.%f",  # With microseconds
        "%Y-%m-%d",  # Date only
    ]

    for fmt in common_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # Return in ISO format for Postgres
            return dt.isoformat()
        except ValueError:
            continue

    # If none of the standard formats work, try parsing with dateutil if available
    try:
        from dateutil import parser
        dt = parser.parse(date_str)
        return dt.isoformat()
    except (ImportError, ValueError):
        pass

    print(f"Warning: Could not parse date '{date_str}', skipping this activity")
    return None

def backfill_from_csv():
    """Read CSV and insert each activity into the database."""
    csv_path = Path("backfill/strava_historical.csv")

    if not csv_path.exists():
        print(f"Error: CSV file not found at {csv_path}")
        return

    print(f"Starting backfill from {csv_path}...")
    print(f"Total rows to process: 238 activities")
    print()

    inserted_count = 0
    skipped_count = 0
    error_count = 0

    if HAS_PANDAS:
        # Use pandas for better CSV handling (utf-8-sig handles BOM)
        # No header row in file, so read without header and assign column names manually
        df = pd.read_csv(csv_path, encoding='utf-8-sig', header=None)
        total_rows = len(df)

        # Validate column count
        actual_columns = df.shape[1]
        expected_columns = len(EXPECTED_COLUMNS)
        print(f"Column count check:")
        print(f"  Expected: {expected_columns} columns")
        print(f"  Found:    {actual_columns} columns")
        print()

        if actual_columns != expected_columns:
            print("ERROR: Column count mismatch!")
            print(f"The CSV has {actual_columns} columns but we expected {expected_columns}.")
            print(f"Expected columns: {', '.join(EXPECTED_COLUMNS)}")
            print("Aborting backfill to prevent data misalignment.")
            sys.exit(1)

        # Assign column names
        df.columns = EXPECTED_COLUMNS
        print(f"Processing {total_rows} rows...")
        print()

        for idx, row in df.iterrows():
            row_num = idx + 1

            try:
                strava_id = int(row["id"])
                name = str(row["name"]) if pd.notna(row["name"]) else "Unknown"
                distance = float(row["distance"]) if pd.notna(row["distance"]) else 0.0
                moving_time = int(row["moving_time"]) if pd.notna(row["moving_time"]) else 0
                average_speed = float(row["average_speed"]) if pd.notna(row["average_speed"]) else 0.0
                start_date_str = str(row["start_date"]) if pd.notna(row["start_date"]) else None

                start_date = parse_start_date(start_date_str)
                if not start_date:
                    skipped_count += 1
                    continue

                # Call the existing insert_activity function
                if db.insert_activity(strava_id, name, distance, moving_time, average_speed, start_date):
                    inserted_count += 1
                else:
                    skipped_count += 1

                # Log progress every 25 rows
                if row_num % 25 == 0:
                    print(f"Processed {row_num}/{total_rows}")

            except Exception as e:
                print(f"Error processing row {row_num}: {e}")
                error_count += 1

    else:
        # Fall back to csv module (utf-8-sig handles BOM)
        # No header row in file, so pass explicit fieldnames
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            # Read first row to validate column count
            first_row = next(f).split(',')
            actual_columns = len(first_row)
            expected_columns = len(EXPECTED_COLUMNS)

            print(f"Column count check:")
            print(f"  Expected: {expected_columns} columns")
            print(f"  Found:    {actual_columns} columns")
            print()

            if actual_columns != expected_columns:
                print("ERROR: Column count mismatch!")
                print(f"The CSV has {actual_columns} columns but we expected {expected_columns}.")
                print(f"Expected columns: {', '.join(EXPECTED_COLUMNS)}")
                print("Aborting backfill to prevent data misalignment.")
                sys.exit(1)

        # Re-open file and read with explicit fieldnames
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, fieldnames=EXPECTED_COLUMNS)
            rows = list(reader)
            total_rows = len(rows)
            print(f"Processing {total_rows} rows...")
            print()

            for row_num, row in enumerate(rows, 1):
                try:
                    strava_id = int(row["id"])
                    name = row["name"] if row["name"] else "Unknown"
                    distance = float(row["distance"]) if row["distance"] else 0.0
                    moving_time = int(row["moving_time"]) if row["moving_time"] else 0
                    average_speed = float(row["average_speed"]) if row["average_speed"] else 0.0
                    start_date_str = row["start_date"] if row["start_date"] else None

                    start_date = parse_start_date(start_date_str)
                    if not start_date:
                        skipped_count += 1
                        continue

                    # Call the existing insert_activity function
                    if db.insert_activity(strava_id, name, distance, moving_time, average_speed, start_date):
                        inserted_count += 1
                    else:
                        skipped_count += 1

                    # Log progress every 25 rows
                    if row_num % 25 == 0:
                        print(f"Processed {row_num}/{total_rows}")

                except Exception as e:
                    print(f"Error processing row {row_num}: {e}")
                    error_count += 1

    # Print final summary
    print()
    print("=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"Total rows processed:  {inserted_count + skipped_count + error_count}")
    print(f"Inserted:              {inserted_count}")
    print(f"Skipped (duplicates):  {skipped_count}")
    print(f"Errors:                {error_count}")
    print("=" * 60)

if __name__ == "__main__":
    backfill_from_csv()
