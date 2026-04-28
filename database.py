"""Eenvoudige SQLite-opslag voor activiteiten."""
import sqlite3
from pathlib import Path

DB_PATH = Path("hardloop.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Maak tabellen aan als ze nog niet bestaan."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY,
                strava_id INTEGER UNIQUE,
                name TEXT,
                type TEXT,
                start_date TEXT,
                distance_km REAL,
                moving_time_min REAL,
                elapsed_time_min REAL,
                avg_heartrate REAL,
                max_heartrate REAL,
                avg_pace_min_per_km REAL,
                elevation_gain REAL,
                avg_cadence REAL,
                suffer_score REAL,
                raw_json TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                access_token TEXT,
                refresh_token TEXT,
                expires_at INTEGER
            )
        """)
        conn.commit()


def save_activity(activity: dict):
    """Sla één activiteit op (overschrijft als hij al bestaat)."""
    with get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO activities (
                strava_id, name, type, start_date, distance_km,
                moving_time_min, elapsed_time_min, avg_heartrate,
                max_heartrate, avg_pace_min_per_km, elevation_gain,
                avg_cadence, suffer_score, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            activity["strava_id"], activity["name"], activity["type"],
            activity["start_date"], activity["distance_km"],
            activity["moving_time_min"], activity["elapsed_time_min"],
            activity.get("avg_heartrate"), activity.get("max_heartrate"),
            activity.get("avg_pace_min_per_km"), activity.get("elevation_gain"),
            activity.get("avg_cadence"), activity.get("suffer_score"),
            activity.get("raw_json", ""),
        ))
        conn.commit()


def get_all_activities():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM activities ORDER BY start_date DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def save_tokens(access_token: str, refresh_token: str, expires_at: int):
    with get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO tokens (id, access_token, refresh_token, expires_at)
            VALUES (1, ?, ?, ?)
        """, (access_token, refresh_token, expires_at))
        conn.commit()


def get_tokens():
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tokens WHERE id = 1").fetchone()
        return dict(row) if row else None