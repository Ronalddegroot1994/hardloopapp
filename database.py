"""PostgreSQL-opslag (Supabase) voor activiteiten en tokens."""
import json
import os
from sqlalchemy import create_engine, text
import streamlit as st


def _get_engine():
    """Maak een SQLAlchemy engine op basis van de Streamlit secret."""
    db_url = st.secrets["SUPABASE_DB_URL"]
    return create_engine(db_url, pool_pre_ping=True)


def init_db():
    """Tabellen bestaan al in Supabase; dit is een no-op voor compatibiliteit."""
    pass


def save_activity(activity: dict):
    """Sla één activiteit op (overschrijft als hij al bestaat)."""
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO activities (
                strava_id, name, type, start_date, distance_km,
                moving_time_min, elapsed_time_min, avg_heartrate,
                max_heartrate, avg_pace_min_per_km, elevation_gain,
                avg_cadence, suffer_score, raw_json
            ) VALUES (
                :strava_id, :name, :type, :start_date, :distance_km,
                :moving_time_min, :elapsed_time_min, :avg_heartrate,
                :max_heartrate, :avg_pace_min_per_km, :elevation_gain,
                :avg_cadence, :suffer_score, CAST(:raw_json AS JSONB)
            )
            ON CONFLICT (strava_id) DO UPDATE SET
                name = EXCLUDED.name,
                type = EXCLUDED.type,
                start_date = EXCLUDED.start_date,
                distance_km = EXCLUDED.distance_km,
                moving_time_min = EXCLUDED.moving_time_min,
                elapsed_time_min = EXCLUDED.elapsed_time_min,
                avg_heartrate = EXCLUDED.avg_heartrate,
                max_heartrate = EXCLUDED.max_heartrate,
                avg_pace_min_per_km = EXCLUDED.avg_pace_min_per_km,
                elevation_gain = EXCLUDED.elevation_gain,
                avg_cadence = EXCLUDED.avg_cadence,
                suffer_score = EXCLUDED.suffer_score,
                raw_json = EXCLUDED.raw_json
        """), {
            "strava_id": activity["strava_id"],
            "name": activity["name"],
            "type": activity["type"],
            "start_date": activity["start_date"],
            "distance_km": activity["distance_km"],
            "moving_time_min": activity["moving_time_min"],
            "elapsed_time_min": activity["elapsed_time_min"],
            "avg_heartrate": activity.get("avg_heartrate"),
            "max_heartrate": activity.get("max_heartrate"),
            "avg_pace_min_per_km": activity.get("avg_pace_min_per_km"),
            "elevation_gain": activity.get("elevation_gain"),
            "avg_cadence": activity.get("avg_cadence"),
            "suffer_score": activity.get("suffer_score"),
            "raw_json": activity.get("raw_json", "{}"),
        })


def get_all_activities():
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT * FROM activities ORDER BY start_date DESC"
        ))
        return [dict(row._mapping) for row in result]


def save_tokens(access_token: str, refresh_token: str, expires_at: int):
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO tokens (id, access_token, refresh_token, expires_at)
            VALUES (1, :access_token, :refresh_token, :expires_at)
            ON CONFLICT (id) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at
        """), {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        })


def get_tokens():
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM tokens WHERE id = 1"))
        row = result.fetchone()
        return dict(row._mapping) if row else None


def get_active_race_goal():
    """Haal het meest recente race-doel op."""
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM race_goals
            WHERE race_date >= CURRENT_DATE
            ORDER BY race_date ASC
            LIMIT 1
        """))
        row = result.fetchone()
        return dict(row._mapping) if row else None
