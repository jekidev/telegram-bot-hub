"""
Sample Script: Cleanup Old Requests
Removes pending requests older than 7 days.
"""
import os
import psycopg2
from datetime import datetime, timedelta

DATABASE_URL = os.environ["DATABASE_URL"]

def run():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(days=7)
    cur.execute(
        "DELETE FROM product_requests WHERE status='pending' AND created_at < %s RETURNING id",
        (cutoff,)
    )
    deleted = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()

    count = len(deleted)
    ids = [str(r[0]) for r in deleted]
    output = []
    output.append(f"Cleanup complete: {count} stale pending request(s) removed.")
    if ids:
        output.append(f"Deleted IDs: {', '.join(ids)}")
    return "\n".join(output)

if __name__ == "__main__":
    print(run())
