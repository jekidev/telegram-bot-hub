"""
Sample Script: Marketplace Report
Generates a summary report of marketplace activity.
"""
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta

DATABASE_URL = os.environ["DATABASE_URL"]

def run():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT COUNT(*) as total FROM users WHERE role='seller'")
    sellers = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) as total FROM users WHERE role='buyer'")
    buyers = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) as total FROM product_requests")
    total_requests = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) as total FROM product_requests WHERE status='accepted'")
    accepted = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) as total FROM ratings")
    total_ratings = cur.fetchone()["total"]

    cur.execute("SELECT ROUND(AVG(stars)::numeric,2) as avg FROM ratings")
    avg_rating = cur.fetchone()["avg"] or 0

    since = datetime.now() - timedelta(hours=24)
    cur.execute("SELECT COUNT(*) as total FROM product_requests WHERE created_at > %s", (since,))
    last_24h = cur.fetchone()["total"]

    cur.execute("""
        SELECT u.username, u.full_name,
               ROUND(AVG(r.stars)::numeric,1) as avg_stars,
               COUNT(r.id) as review_count
        FROM users u
        JOIN ratings r ON r.seller_id = u.telegram_id
        GROUP BY u.telegram_id, u.username, u.full_name
        ORDER BY avg_stars DESC, review_count DESC
        LIMIT 5
    """)
    top_sellers = cur.fetchall()

    cur.close()
    conn.close()

    output = []
    output.append("=" * 40)
    output.append(f"  MARKETPLACE REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    output.append("=" * 40)
    output.append(f"  Sellers:          {sellers}")
    output.append(f"  Buyers:           {buyers}")
    output.append(f"  Total Requests:   {total_requests}")
    output.append(f"  Accepted:         {accepted}")
    output.append(f"  Conversion Rate:  {round(accepted/total_requests*100,1) if total_requests else 0}%")
    output.append(f"  Requests (24h):   {last_24h}")
    output.append(f"  Total Ratings:    {total_ratings}")
    output.append(f"  Avg Rating:       {avg_rating}/5.0")
    output.append("")
    output.append("  TOP SELLERS BY RATING:")
    for i, s in enumerate(top_sellers, 1):
        name = s["username"] or s["full_name"] or "unknown"
        output.append(f"  {i}. @{name} — {s['avg_stars']}★ ({s['review_count']} reviews)")
    output.append("=" * 40)
    return "\n".join(output)

if __name__ == "__main__":
    print(run())
