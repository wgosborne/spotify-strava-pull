#!/usr/bin/env python3
"""One-off script to backfill Strava activity descriptions from CSV."""

import csv
import sys
import os

# Add parent directory to path to import db
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_connection


def backfill_descriptions(csv_path):
    """Read CSV and update activities with descriptions."""
    updated = 0
    skipped = 0
    total = 0

    conn = None
    try:
        conn = get_connection()
        if not conn:
            print("Error: Failed to connect to database")
            return

        cur = conn.cursor()

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # Strip whitespace from fieldnames in case of formatting issues
            reader.fieldnames = [name.strip() if name else name for name in reader.fieldnames]

            for row in reader:
                total += 1
                # Create a new dict with stripped fieldnames
                row = {k.strip() if k else k: v for k, v in row.items()}

                strava_id = row['id'].strip()
                description = row['description'].strip() if row['description'] else None

                # Skip empty/null descriptions
                if not description:
                    skipped += 1
                    continue

                try:
                    cur.execute(
                        "UPDATE activities SET description = %s WHERE strava_id = %s",
                        (description, strava_id)
                    )
                    updated += 1
                except Exception as e:
                    print(f"Error updating strava_id {strava_id}: {e}")
                    skipped += 1

                # Log progress every 50 rows
                if total % 50 == 0:
                    print(f"Processed {total} rows ({updated} updated, {skipped} skipped)")

        conn.commit()
        cur.close()

    except Exception as e:
        print(f"Fatal error: {e}")
        if conn:
            conn.close()
        return
    finally:
        if conn:
            conn.close()

    # Final summary
    print("\n=== Backfill Complete ===")
    print(f"Total rows:    {total}")
    print(f"Updated:       {updated}")
    print(f"Skipped:       {skipped}")


if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), "backfill", "strava_descriptions.csv")

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        sys.exit(1)

    backfill_descriptions(csv_path)
