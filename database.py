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


# ============================================================
# RACE GOALS — uitgebreide functies
# ============================================================

def get_all_races():
    """Haal alle races op, gesorteerd op datum (oudste eerst)."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM race_goals
            ORDER BY race_date ASC
        """))
        return [dict(row._mapping) for row in result]


def get_upcoming_races():
    """Alleen toekomstige races."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM race_goals
            WHERE race_date >= CURRENT_DATE
            ORDER BY race_date ASC
        """))
        return [dict(row._mapping) for row in result]


def get_next_a_race():
    """Eerstvolgende A-race (hoofddoel) — voor de hero-banner."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM race_goals
            WHERE race_date >= CURRENT_DATE AND race_type = 'A'
            ORDER BY race_date ASC
            LIMIT 1
        """))
        row = result.fetchone()
        return dict(row._mapping) if row else None


def add_race(name: str, distance_km: float, race_date, target_time_seconds: int | None,
             race_type: str = "A", notes: str = ""):
    """Voeg een nieuwe race toe."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO race_goals (name, distance_km, race_date, target_time_seconds, race_type, notes)
            VALUES (:name, :distance_km, :race_date, :target_time_seconds, :race_type, :notes)
        """), {
            "name": name,
            "distance_km": distance_km,
            "race_date": race_date,
            "target_time_seconds": target_time_seconds,
            "race_type": race_type,
            "notes": notes,
        })


def update_race(race_id: int, name: str, distance_km: float, race_date,
                target_time_seconds: int | None, race_type: str, notes: str):
    """Bestaande race bewerken."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE race_goals
            SET name = :name,
                distance_km = :distance_km,
                race_date = :race_date,
                target_time_seconds = :target_time_seconds,
                race_type = :race_type,
                notes = :notes
            WHERE id = :race_id
        """), {
            "race_id": race_id,
            "name": name,
            "distance_km": distance_km,
            "race_date": race_date,
            "target_time_seconds": target_time_seconds,
            "race_type": race_type,
            "notes": notes,
        })


def delete_race(race_id: int):
    """Race verwijderen."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM race_goals WHERE id = :race_id"), {"race_id": race_id})


# ============================================================
# USER PROFILE — notitieboek voor coach
# ============================================================

def get_user_profile() -> dict:
    """Haal het profiel op (altijd id=1)."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM user_profile WHERE id = 1"))
        row = result.fetchone()
        if row:
            return dict(row._mapping)
        return {"about_me": "", "injuries": "", "preferences": ""}


def save_user_profile(about_me: str, injuries: str, preferences: str):
    """Update het profiel."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO user_profile (id, about_me, injuries, preferences, updated_at)
            VALUES (1, :about_me, :injuries, :preferences, NOW())
            ON CONFLICT (id) DO UPDATE SET
                about_me = EXCLUDED.about_me,
                injuries = EXCLUDED.injuries,
                preferences = EXCLUDED.preferences,
                updated_at = NOW()
        """), {
            "about_me": about_me,
            "injuries": injuries,
            "preferences": preferences,
        })


# ============================================================
# PERSONAL RECORDS — handmatige PR-lijst
# ============================================================

def get_all_records():
    """Haal alle records op, gesorteerd op afstand."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM personal_records
            ORDER BY distance_km ASC, time_seconds ASC
        """))
        return [dict(row._mapping) for row in result]


def add_record(distance_label: str, distance_km: float, time_seconds: int,
               record_date, race_name: str = "", notes: str = ""):
    """Voeg een nieuw record toe."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO personal_records
                (distance_label, distance_km, time_seconds, record_date, race_name, notes)
            VALUES
                (:distance_label, :distance_km, :time_seconds, :record_date, :race_name, :notes)
        """), {
            "distance_label": distance_label,
            "distance_km": distance_km,
            "time_seconds": time_seconds,
            "record_date": record_date,
            "race_name": race_name,
            "notes": notes,
        })


def update_record(record_id: int, distance_label: str, distance_km: float,
                   time_seconds: int, record_date, race_name: str, notes: str):
    """Bestaand record bewerken."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE personal_records
            SET distance_label = :distance_label,
                distance_km = :distance_km,
                time_seconds = :time_seconds,
                record_date = :record_date,
                race_name = :race_name,
                notes = :notes
            WHERE id = :record_id
        """), {
            "record_id": record_id,
            "distance_label": distance_label,
            "distance_km": distance_km,
            "time_seconds": time_seconds,
            "record_date": record_date,
            "race_name": race_name,
            "notes": notes,
        })


def delete_record(record_id: int):
    """Record verwijderen."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM personal_records WHERE id = :record_id"),
                     {"record_id": record_id})


# ============================================================
# WEEKLY SCHEDULE — levend weekschema
# ============================================================

def get_active_schedule() -> dict | None:
    """Haal het actieve weekschema op (of None)."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM weekly_schedule
            WHERE is_active = TRUE
            ORDER BY created_at DESC
            LIMIT 1
        """))
        row = result.fetchone()
        return dict(row._mapping) if row else None


def create_schedule(week_start, schedule_text: str):
    """Maak een nieuw actief schema. Zet eerdere schema's op niet-actief."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("UPDATE weekly_schedule SET is_active = FALSE WHERE is_active = TRUE"))
        conn.execute(text("""
            INSERT INTO weekly_schedule (week_start, schedule_text, update_log, is_active)
            VALUES (:week_start, :schedule_text, '', TRUE)
        """), {"week_start": week_start, "schedule_text": schedule_text})


def update_schedule(schedule_id: int, new_schedule_text: str, log_entry: str):
    """Werk het schema bij en voeg een regel toe aan het aanpassings-logje."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE weekly_schedule
            SET schedule_text = :new_text,
                update_log = COALESCE(update_log, '') || :log_entry
            WHERE id = :schedule_id
        """), {
            "schedule_id": schedule_id,
            "new_text": new_schedule_text,
            "log_entry": log_entry,
        })


def archive_active_schedule():
    """Zet het actieve schema op niet-actief (handmatig afsluiten)."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("UPDATE weekly_schedule SET is_active = FALSE WHERE is_active = TRUE"))


def get_schedule_history(limit: int = 10):
    """Haal eerdere (niet-actieve) schema's op voor het historie-overzicht."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM weekly_schedule
            WHERE is_active = FALSE
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit})
        return [dict(row._mapping) for row in result]
