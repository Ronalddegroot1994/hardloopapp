"""Strava API koppeling: tokens beheren en activiteiten ophalen."""
import time
import json
import requests
from datetime import datetime, timedelta, timezone
from database import save_activity, save_tokens, get_tokens

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


def refresh_access_token(client_id: str, client_secret: str):
    """Vernieuw het access token als het verlopen is."""
    tokens = get_tokens()
    if not tokens:
        raise RuntimeError("Geen tokens gevonden. Doe eerst de OAuth-koppeling.")

    if tokens["expires_at"] > int(time.time()) + 60:
        return tokens["access_token"]

    response = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    })
    response.raise_for_status()
    data = response.json()
    save_tokens(data["access_token"], data["refresh_token"], data["expires_at"])
    return data["access_token"]


def exchange_code_for_token(client_id: str, client_secret: str, code: str):
    """Eerste keer: ruil de auth code in voor access + refresh token."""
    response = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    })
    if response.status_code != 200:
        raise RuntimeError(
            f"Strava antwoordde {response.status_code}: {response.text}\n"
            f"Client ID gebruikt: {client_id}\n"
            f"Client Secret lengte: {len(client_secret)} tekens\n"
            f"Code lengte: {len(code)} tekens"
        )
    data = response.json()
    save_tokens(data["access_token"], data["refresh_token"], data["expires_at"])
    return data


def fetch_activities(access_token: str, per_page: int = 50, pages: int = 4):
    """Haal activiteiten op (per_page x pages = max aantal)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    all_activities = []
    for page in range(1, pages + 1):
        response = requests.get(
            STRAVA_ACTIVITIES_URL,
            headers=headers,
            params={"per_page": per_page, "page": page},
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        all_activities.extend(batch)
    return all_activities


def parse_and_save(activities: list):
    """Zet ruwe Strava-data om en sla in bulk op."""
    from database import save_activities_bulk

    rows = []
    for act in activities:
        distance_km = act.get("distance", 0) / 1000
        moving_min = act.get("moving_time", 0) / 60
        pace = (moving_min / distance_km) if distance_km > 0 else None

        rows.append({
            "strava_id": act["id"],
            "name": act.get("name", ""),
            "type": act.get("sport_type") or act.get("type", ""),
            "start_date": act.get("start_date_local", ""),
            "distance_km": round(distance_km, 2),
            "moving_time_min": round(moving_min, 1),
            "elapsed_time_min": round(act.get("elapsed_time", 0) / 60, 1),
            "avg_heartrate": act.get("average_heartrate"),
            "max_heartrate": act.get("max_heartrate"),
            "avg_pace_min_per_km": round(pace, 2) if pace else None,
            "elevation_gain": act.get("total_elevation_gain"),
            "avg_cadence": act.get("average_cadence"),
            "suffer_score": act.get("suffer_score"),
            "raw_json": json.dumps(act),
        })

    save_activities_bulk(rows)

def sync_all(client_id: str, client_secret: str):
    """Volledig sync-proces: token vernieuwen, ophalen, opslaan."""
    access_token = refresh_access_token(client_id, client_secret)
    activities = fetch_activities(access_token)
    parse_and_save(activities)
    return len(activities)


def auto_sync(client_id: str, client_secret: str, force: bool = False) -> dict:
    """Automatische sync + backfill voor bij elke pagina-load.

    Hergebruikt sync_all() en backfill_batch() als bouwstenen. Synct alleen als de
    laatste sync >15 min geleden was (of bij force=True), en backfillt daarna max
    5 activiteiten zonder zone-data. Een actieve rate-limit-cooldown geldt ook bij
    force=True — force omzeilt alleen de 15-minuten-verversingscheck, niet de
    Strava-failsafe.

    Retourneert: {"state": "fresh"|"synced"|"rate_limited"|"error",
                  "message": str, "synced_count": int, "backfilled_count": int}
    """
    import streamlit as st
    from database import get_sync_status, mark_sync_success, mark_sync_issue
    from streams import get_activities_without_zones, backfill_batch

    now = datetime.now(timezone.utc)
    result = {"state": "fresh", "message": "", "synced_count": 0, "backfilled_count": 0}

    status = get_sync_status()
    blocked_until = st.session_state.get("strava_rate_limited_until") or (
        status.get("rate_limited_until") if status else None
    )
    if blocked_until and now < blocked_until:
        st.session_state["strava_rate_limited_until"] = blocked_until
        result["state"] = "rate_limited"
        result["message"] = "Strava rate-limit bereikt, wacht 15 min"
        return result
    st.session_state.pop("strava_rate_limited_until", None)

    last_sync_at = status.get("last_sync_at") if status else None
    needs_sync = force or last_sync_at is None or (now - last_sync_at) > timedelta(minutes=15)

    if needs_sync:
        try:
            count = sync_all(client_id, client_secret)
            mark_sync_success()
            st.cache_data.clear()
            result["state"] = "synced"
            result["synced_count"] = count
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                rate_limited_until = now + timedelta(minutes=15)
                mark_sync_issue("rate_limited", "Strava rate-limit bereikt", rate_limited_until)
                st.session_state["strava_rate_limited_until"] = rate_limited_until
                result["state"] = "rate_limited"
                result["message"] = "Strava rate-limit bereikt, wacht 15 min"
            else:
                mark_sync_issue("error", str(e)[:200])
                result["state"] = "error"
                result["message"] = "Strava tijdelijk niet bereikbaar"
            return result
        except Exception as e:
            mark_sync_issue("error", str(e)[:200])
            result["state"] = "error"
            result["message"] = "Strava tijdelijk niet bereikbaar"
            return result

    # Auto-backfill: max 5 activiteiten zonder zone-data per pagina-load
    # (bewust laag gehouden zodat 50 nieuwe activiteiten niet in één keer 50 API-calls kosten)
    try:
        todo = get_activities_without_zones(limit=5)
        if todo:
            access_token = refresh_access_token(client_id, client_secret)
            success, failed, msg = backfill_batch(access_token, 5)
            result["backfilled_count"] = success
            if "Rate-limit" in msg:
                rate_limited_until = now + timedelta(minutes=15)
                mark_sync_issue("rate_limited", "Strava rate-limit bereikt tijdens backfill", rate_limited_until)
                st.session_state["strava_rate_limited_until"] = rate_limited_until
                result["state"] = "rate_limited"
                result["message"] = "Strava rate-limit bereikt, wacht 15 min"
                return result
            if success > 0:
                st.cache_data.clear()
    except Exception:
        pass

    return result
