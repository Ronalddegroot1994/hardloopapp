"""Strava API koppeling: tokens beheren en activiteiten ophalen."""
import time
import json
import requests
from datetime import datetime
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
