import os
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "restaurant.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn

def init_db():
    conn = get_db()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    # Demo tables
    tables = [
        ("T01", 2, "Window"),
        ("T02", 2, "Main Dining"),
        ("T03", 4, "Main Dining"),
        ("T04", 4, "Window"),
        ("T05", 4, "Garden"),
        ("T06", 6, "Garden"),
        ("T07", 6, "Main Dining"),
        ("T08", 8, "Private Dining"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO restaurant_tables(table_number, capacity, area) VALUES(?,?,?)",
        tables
    )

    rewards = [
        ("Complimentary Dessert", "A complimentary dessert on your next visit.", 100),
        ("10% Off Your Bill", "Enjoy 10% off a future dine-in bill.", 250),
        ("Chef's Special Treat", "A special treat from the chef.", 400),
    ]
    for name, description, cost in rewards:
        exists = conn.execute("SELECT id FROM rewards WHERE name=?", (name,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO rewards(name, description, points_cost) VALUES(?,?,?)",
                (name, description, cost)
            )

    admin = conn.execute("SELECT id FROM users WHERE email='admin@tableandthyme.local'").fetchone()
    if not admin:
        conn.execute(
            "INSERT INTO users(name,email,phone,password_hash,role) VALUES(?,?,?,?,?)",
            ("Restaurant Admin", "admin@tableandthyme.local", "9000000000",
             generate_password_hash("Admin@123"), "admin")
        )

    demo = conn.execute("SELECT id FROM users WHERE email='ad.demo@example.com'").fetchone()
    if not demo:
        cur = conn.execute(
            "INSERT INTO users(name,email,phone,password_hash,role) VALUES(?,?,?,?,?)",
            ("Ad Demo", "ad.demo@example.com", "9876543210",
             generate_password_hash("Customer@123"), "customer")
        )
        uid = cur.lastrowid
        conn.execute("INSERT INTO loyalty_accounts(user_id, points, lifetime_points) VALUES(?,?,?)", (uid, 180, 180))
        conn.execute(
            "INSERT INTO loyalty_transactions(user_id,points_change,reason) VALUES(?,?,?)",
            (uid, 180, "Welcome demo points")
        )

    conn.commit()
    conn.close()
