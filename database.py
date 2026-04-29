"""PostgreSQL-opslag (Supabase) - geoptimaliseerd met cached engine + bulk insert."""
import streamlit as st
from sqlalchemy import create_engine, text


@st.cache_resource
def get_engine():
    """Eén keer aangemaakt, daarna hergebruikt voor alle queries."""
    db_url = st.secrets["SUPABASE_DB_URL"]
    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )


def init_db():
    """Tabellen bestaan al in Supabase; no-op."""
    pass


def save_activities_bulk(activities: list[dict]):
    """Sla meerdere activiteiten in één keer op (veel sneller)."""
    if not activities:
        return
    engine = get_engine()
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
        """), activities)


def save_activity(activity: dict):
    """Behouden voor compatibiliteit; intern roept hij bulk aan."""
    save_activities_bulk([activity])


def get_all_activities():
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT * FROM activities ORDER BY start_date DESC"
        ))
        return [dict(row._mapping) for row in result]


def save_tokens(access_token: str, refresh_token: str, expires_at: int):
    engine = get_engine()
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
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM tokens WHERE id = 1"))
        row = result.fetchone()
        return dict(row._mapping) if row else None


def get_active_race_goal():
    """Haal het meest recente race-doel op."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM race_goals
            WHERE race_date >= CURRENT_DATE
            ORDER BY race_date ASC
            LIMIT 1
        """))
        row = result.fetchone()
        return dict(row._mapping) if row else None
