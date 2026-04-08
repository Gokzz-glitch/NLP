import asyncio
import aiohttp
import sqlite3
import time
import uuid
import random
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
DB_PATH = "edge_spatial.db"  # Adjust if your DB path is different
API_BASE_URL = "http://localhost:8000"
CONCURRENT_DB_THREADS = 100  # Will it deadlock?
CONCURRENT_API_REQUESTS = 500  # Will the leaky bucket hold?


def brutal_db_write_thread(thread_id):
    """Bypasses API to hammer the SQLite DB directly. Tests WAL and busy_timeout."""
    try:
        # 15 second timeout is our armor. Let's test it.
        conn = sqlite3.connect(DB_PATH, timeout=15.0)
        cursor = conn.cursor()

        # Ensure a dummy table exists for the stress test
        cursor.execute('''CREATE TABLE IF NOT EXISTS stress_test_log 
                          (id TEXT PRIMARY KEY, thread_id INT, timestamp REAL)''')
        conn.commit()

        # Fire 50 rapid inserts per thread
        for _ in range(50):
            cursor.execute("INSERT INTO stress_test_log VALUES (?, ?, ?)",
                           (str(uuid.uuid4()), thread_id, time.time()))
            conn.commit()
            # Random micro-sleep to create chaotic overlapping I/O
            time.sleep(random.uniform(0.001, 0.01))

        conn.close()
        return True
    except sqlite3.OperationalError as e:
        return f"DB_LOCKED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


async def brutal_api_flood(session, endpoint, method="GET", payload=None):
    """Hammers the FastAPI endpoints to test rate limits and async workers."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        if method == "GET":
            async with session.get(url) as response:
                return response.status
        elif method == "POST":
            async with session.post(url, json=payload) as response:
                return response.status
    except Exception:
        return "SERVER_CRASHED"


async def run_chaos_protocol():
    print(f"🔥 INITIATING BRUTAL ENTERPRISE STRESS TEST 🔥")
    start_time = time.time()

    # PHASE 1: SQLITE WAL CONCURRENCY SLAUGHTER
    print(f"\n[PHASE 1] Spawning {CONCURRENT_DB_THREADS} threads to bombard SQLite...")
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=CONCURRENT_DB_THREADS) as pool:
        db_tasks = [
            loop.run_in_executor(pool, brutal_db_write_thread, i)
            for i in range(CONCURRENT_DB_THREADS)
        ]
        db_results = await asyncio.gather(*db_tasks)

    db_failures = [r for r in db_results if r is not True]
    if db_failures:
        print(f"❌ DB FAIL: {len(db_failures)} threads hit locks. WAL/timeout failed.")
        print(f"Sample error: {db_failures[0]}")
    else:
        print(f"✅ DB PASS: SQLite swallowed {CONCURRENT_DB_THREADS * 50} chaotic concurrent writes with 0 locks.")

    # PHASE 2: API DDoS & RATE LIMIT CHECK
    print(f"\n[PHASE 2] Firing {CONCURRENT_API_REQUESTS} concurrent API requests...")
    async with aiohttp.ClientSession() as session:
        # Mix of unauthorized hits and fake webhooks
        api_tasks = []
        for _ in range(CONCURRENT_API_REQUESTS):
            if random.choice([True, False]):
                # Hit the premium endpoint without a key
                api_tasks.append(brutal_api_flood(session, "/api/v1/fleet-routing-hazards"))
            else:
                # Spam fake webhooks
                fake_payload = {"razorpay_payment_id": "fake_id", "razorpay_order_id": "fake_order"}
                api_tasks.append(brutal_api_flood(session, "/api/v1/webhook/razorpay", "POST", fake_payload))

        api_results = await asyncio.gather(*api_tasks)

    status_counts = {}
    for status in api_results:
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f"📊 API Response Breakdown:")
    for status, count in status_counts.items():
        print(f"  HTTP {status}: {count} requests")

    if "SERVER_CRASHED" in status_counts:
        print("❌ API FAIL: The FastAPI server crashed under load.")
    elif status_counts.get(200, 0) == CONCURRENT_API_REQUESTS:
        print("❌ API FAIL: No rate limits applied! Server answered every single request.")
    else:
        print("✅ API PASS: Server stayed alive and correctly rejected/throttled flood traffic (Expected 401s, 400s, or 429s).")

    print(f"\n⏱️ Total Chaos Duration: {round(time.time() - start_time, 2)} seconds")


if __name__ == "__main__":
    asyncio.run(run_chaos_protocol())
