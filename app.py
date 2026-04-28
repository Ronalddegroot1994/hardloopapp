"""Streamlit dashboard - hoofdpagina."""
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from database import init_db, get_all_activities, get_tokens
from strava_sync import sync_all, exchange_code_for_token

st.set_page_config(page_title="Mijn Hardloopportaal", page_icon="🏃", layout="wide")
init_db()

# === Secrets ophalen ===
CLIENT_ID = st.secrets.get("STRAVA_CLIENT_ID", "")
CLIENT_SECRET = st.secrets.get("STRAVA_CLIENT_SECRET", "")

st.title("🏃 Mijn Hardloopportaal")

# === Eerste keer: OAuth-koppeling ===
tokens = get_tokens()
if not tokens:
    st.warning("Strava is nog niet gekoppeld. Volg de stappen hieronder.")
    redirect_uri = "http://localhost"
    auth_url = (
        f"https://www.strava.com/oauth/authorize?"
        f"client_id={CLIENT_ID}&response_type=code&redirect_uri={redirect_uri}"
        f"&approval_prompt=force&scope=read,activity:read_all"
    )
    st.markdown(f"**Stap 1:** [Klik hier om Strava te koppelen]({auth_url})")
    st.markdown(
        "**Stap 2:** Je wordt doorgestuurd naar een pagina die niet laadt "
        "(`localhost`). Dat is OK. Kopieer de URL uit je browserbalk."
    )
    st.markdown(
        "**Stap 3:** In die URL staat `code=XXXXX&...`. Plak hieronder "
        "alleen de waarde van `code`."
    )
    code = st.text_input("Plak hier de code:")
    if st.button("Koppel Strava") and code:
        try:
            exchange_code_for_token(CLIENT_ID, CLIENT_SECRET, code.strip())
            st.success("Gekoppeld! Ververs de pagina.")
            st.rerun()
        except Exception as e:
            st.error(f"Koppelen mislukt: {e}")
    st.stop()

# === Sync-knop ===
col1, col2 = st.columns([1, 5])
with col1:
    if st.button("🔄 Sync Strava"):
        with st.spinner("Activiteiten ophalen..."):
            try:
                count = sync_all(CLIENT_ID, CLIENT_SECRET)
                st.success(f"{count} activiteiten gesynchroniseerd.")
            except Exception as e:
                st.error(f"Sync mislukt: {e}")

# === Data laden ===
activities = get_all_activities()
if not activities:
    st.info("Nog geen activiteiten. Klik op 'Sync Strava' om te beginnen.")
    st.stop()

df = pd.DataFrame(activities)
df["start_date"] = pd.to_datetime(df["start_date"])
df["week"] = df["start_date"].dt.to_period("W").apply(lambda p: p.start_time)

# === Filter op hardlopen (default) ===
sport_options = sorted(df["type"].unique())
selected_sports = st.multiselect(
    "Sporten",
    sport_options,
    default=[s for s in sport_options if "Run" in s] or sport_options,
)
df_filtered = df[df["type"].isin(selected_sports)]

# === KPI's ===
st.subheader("Deze maand")
last_30 = df_filtered[df_filtered["start_date"] >= datetime.now() - timedelta(days=30)]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Activiteiten", len(last_30))
c2.metric("Kilometers", f"{last_30['distance_km'].sum():.1f}")
c3.metric("Uren", f"{last_30['moving_time_min'].sum() / 60:.1f}")
avg_hr = last_30['avg_heartrate'].mean()
c4.metric("Gem. hartslag", f"{avg_hr:.0f}" if pd.notna(avg_hr) else "—")

# === Grafiek: km per week ===
st.subheader("Kilometers per week")
weekly = df_filtered.groupby("week")["distance_km"].sum().reset_index()
weekly = weekly.tail(16)  # laatste 16 weken
fig = px.bar(weekly, x="week", y="distance_km", labels={"distance_km": "km", "week": "Week"})
fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, use_container_width=True)

# === Tabel ===
st.subheader("Recente activiteiten")
display_cols = [
    "start_date", "name", "type", "distance_km",
    "moving_time_min", "avg_pace_min_per_km", "avg_heartrate",
]
df_display = df_filtered[display_cols].head(30).copy()
df_display["start_date"] = df_display["start_date"].dt.strftime("%d-%m-%Y")
df_display.columns = ["Datum", "Naam", "Type", "km", "Min", "Pace (min/km)", "Gem. HR"]
st.dataframe(df_display, use_container_width=True, hide_index=True)