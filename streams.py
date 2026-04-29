"""Strava streams ophalen + zone-tijden berekenen."""
import time
import requests
import streamlit as st
from sqlalchemy import text
from database import get_engine

# === Friel-zones, gebaseerd op LTHR ===
LTHR = 170  # gelijk aan metrics.py
HR_ZONES = [
    (0.00, 0.85, "z1"),
    (0.85, 0.90, "z2"),
    (0.90, 0.95, "z3"),
    (0.95, 1.00, "z4"),
    (1.00, 99.0, "z5"),
]

# === Pace-zones, gebaseerd op threshold pace ===
# We schatten threshold pace uit jouw marathonpace (4:07/km).
# Ervaren lopers: 10K-pace ~= 95% van threshold pace.
# Voor jou nemen we als referentie: threshold pace ~ 3:55/km = 235 sec/km.
THRESHOLD_PACE_SEC = 235  # sec/km - aanpasbaar
PACE_ZONES = [
    (1.20, 99.0, "z1"),   # >120% = trager dan 4:42/km
    (1.06, 1.20, "z2"),   # 106-120% = 4:09-4:42/km (rustige duurloop)
    (1.00, 1.06, "z3"),   # 100-106% = 3:55-4:09/km (tempo)
    (0.95, 1.00, "z4"),   # 95-100% = 3:43-3:55/km (drempel)
    (0.00, 0.95, "z5"),   # <95% = sneller dan 3:43/km (intervallen)
]


def _classify(value: float, zones: list, lthr_or_threshold: float) -> str:
    """Bepaal zone-label voor een waarde (HR of pace)."""
    ratio = value / lthr_or_threshold
    for low, high, label in zones:
        if low <= ratio < high:
            return label
    return "z5"


def fetch_streams(activity_id: int, access_token: str) -> dict | None:
    """Haal HR + tijd + snelheid streams op voor één activiteit."""
    url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"keys": "time,heartrate,velocity_smooth", "key_by_type": "true"}

    response = requests.get(url, headers=headers, params=params, timeout=30)

    # Rate-limit: stop netjes
    if response.status_code == 429:
        raise RuntimeError("RATE_LIMIT")

    if response.status_code != 200:
        return None

    return response.json()


def calculate_zone_seconds(streams: dict, sport_type: str = "Run") -> dict:
    """Bereken seconden per HR-zone en pace-zone uit streams."""
    result = {f"hr_{z}_sec": 0 for z in ["z1", "z2", "z3", "z4", "z5"]}
    result.update({f"pace_{z}_sec": 0 for z in ["z1", "z2", "z3", "z4", "z5"]})

    if not streams or "time" not in streams:
        return result

    time_data = streams["time"]["data"]
    hr_data = streams.get("heartrate", {}).get("data", [])
    vel_data = streams.get("velocity_smooth", {}).get("data", [])

    is_run = sport_type in ("Run", "VirtualRun", "TrailRun")

    for i in range(1, len(time_data)):
        delta = time_data[i] - time_data[i - 1]
        if delta <= 0 or delta > 60:  # negeer pauzes >1 min
            continue

        # HR-zone
        if i < len(hr_data) and hr_data[i] > 0:
            zone = _classify(hr_data[i], HR_ZONES, LTHR)
            result[f"hr_{zone}_sec"] += delta

        # Pace-zone (alleen voor hardlopen, en als snelheid > 1 m/s)
        if is_run and i < len(vel_data) and vel_data[i] > 1.0:
            pace_sec_per_km = 1000 / vel_data[i]
            zone = _classify(pace_sec_per_km, PACE_ZONES, THRESHOLD_PACE_SEC)
            result[f"pace_{zone}_sec"] += delta

    return result


def save_zones(strava_id: int, zones: dict, has_streams: bool = True):
    """Sla zone-data op in Supabase."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO activity_zones (
                strava_id, hr_z1_sec, hr_z2_sec, hr_z3_sec, hr_z4_sec, hr_z5_sec,
                pace_z1_sec, pace_z2_sec, pace_z3_sec, pace_z4_sec, pace_z5_sec,
                has_streams
            ) VALUES (
                :strava_id, :hr_z1_sec, :hr_z2_sec, :hr_z3_sec, :hr_z4_sec, :hr_z5_sec,
                :pace_z1_sec, :pace_z2_sec, :pace_z3_sec, :pace_z4_sec, :pace_z5_sec,
                :has_streams
            )
            ON CONFLICT (strava_id) DO UPDATE SET
                hr_z1_sec = EXCLUDED.hr_z1_sec,
                hr_z2_sec = EXCLUDED.hr_z2_sec,
                hr_z3_sec = EXCLUDED.hr_z3_sec,
                hr_z4_sec = EXCLUDED.hr_z4_sec,
                hr_z5_sec = EXCLUDED.hr_z5_sec,
                pace_z1_sec = EXCLUDED.pace_z1_sec,
                pace_z2_sec = EXCLUDED.pace_z2_sec,
                pace_z3_sec = EXCLUDED.pace_z3_sec,
                pace_z4_sec = EXCLUDED.pace_z4_sec,
                pace_z5_sec = EXCLUDED.pace_z5_sec,
                has_streams = :has_streams,
                fetched_at = NOW()
        """), {"strava_id": strava_id, "has_streams": has_streams, **zones})


def get_activities_without_zones(limit: int = 50) -> list[dict]:
    """Haal activiteiten op die nog geen zone-data hebben."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT a.strava_id, a.type, a.name, a.start_date
            FROM activities a
            LEFT JOIN activity_zones z ON a.strava_id = z.strava_id
            WHERE z.strava_id IS NULL
            ORDER BY a.start_date DESC
            LIMIT :limit
        """), {"limit": limit})
        return [dict(row._mapping) for row in result]


def get_zones_for_activities(strava_ids: list[int]) -> dict[int, dict]:
    """Haal zone-data op voor een lijst van activity-IDs."""
    if not strava_ids:
        return {}
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT * FROM activity_zones WHERE strava_id = ANY(:ids)"
        ), {"ids": list(strava_ids)})
        return {row._mapping["strava_id"]: dict(row._mapping) for row in result}


def backfill_batch(access_token: str, batch_size: int = 50,
                   progress_callback=None) -> tuple[int, int, str]:
    """Verwerk één batch van activiteiten zonder zone-data.
    
    Returns: (aantal succes, aantal mislukt, status_message)
    """
    activities = get_activities_without_zones(limit=batch_size)
    if not activities:
        return (0, 0, "Geen activiteiten meer om te backfillen — alles is bij!")

    success = 0
    failed = 0
    rate_limit_hit = False

    for idx, act in enumerate(activities):
        if progress_callback:
            progress_callback(idx + 1, len(activities), act["name"])

        try:
            streams = fetch_streams(act["strava_id"], access_token)
            if streams is None:
                save_zones(act["strava_id"], {f"hr_{z}_sec": 0 for z in ["z1","z2","z3","z4","z5"]} |
                           {f"pace_{z}_sec": 0 for z in ["z1","z2","z3","z4","z5"]},
                           has_streams=False)
                failed += 1
            else:
                zones = calculate_zone_seconds(streams, act["type"])
                save_zones(act["strava_id"], zones, has_streams=True)
                success += 1
        except RuntimeError as e:
            if "RATE_LIMIT" in str(e):
                rate_limit_hit = True
                break
            failed += 1
        except Exception:
            failed += 1

        time.sleep(0.3)  # vriendelijk voor Strava

    if rate_limit_hit:
        msg = (f"Rate-limit van Strava bereikt. {success} verwerkt deze batch. "
               f"Wacht ~15 minuten en probeer opnieuw.")
    elif success + failed < batch_size:
        msg = f"{success} verwerkt, {failed} mislukt. Geen activiteiten meer over."
    else:
        msg = f"Batch klaar: {success} succes, {failed} mislukt. Klik nogmaals voor de volgende batch."

    return (success, failed, msg)
