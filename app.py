"""Streamlit dashboard - hoofdpagina."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from database import init_db, get_all_activities, get_tokens, get_active_race_goal
from strava_sync import sync_all, exchange_code_for_token
from metrics import add_tss_column, calculate_load_curves, get_current_metrics
from coach import generate_weekly_advice

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
    redirect_uri = "https://ronalds-hardloopapp.streamlit.app"
    auth_url = (
        f"https://www.strava.com/oauth/authorize?"
        f"client_id={CLIENT_ID}&response_type=code&redirect_uri={redirect_uri}"
        f"&approval_prompt=force&scope=read,activity:read_all"
    )
    st.markdown(f"**Stap 1:** [Klik hier om Strava te koppelen]({auth_url})")
    st.markdown(
        "**Stap 2:** Je wordt teruggestuurd naar deze app met `?code=...` in de URL."
    )
    st.markdown("**Stap 3:** Plak alleen de waarde van `code` hieronder.")
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
df["start_date"] = pd.to_datetime(df["start_date"], utc=True).dt.tz_localize(None)
df["week"] = df["start_date"].dt.to_period("W").apply(lambda p: p.start_time)

# === Sport-filter ===
sport_options = sorted(df["type"].unique())
selected_sports = st.multiselect(
    "Sporten",
    sport_options,
    default=[s for s in sport_options if "Run" in s] or sport_options,
)
df_filtered = df[df["type"].isin(selected_sports)]

# === Helpers voor tijdformat ===
def format_pace(p):
    if pd.isna(p) or p is None or p == 0:
        return "—"
    minutes = int(p)
    seconds = round((p - minutes) * 60)
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}"


def format_duration(m):
    if pd.isna(m) or m <= 0:
        return "—"
    hours = int(m // 60)
    mins = int(m % 60)
    return f"{hours}:{mins:02d}" if hours > 0 else f"{mins} min"


# === Tabs ===
tab_overzicht, tab_belasting, tab_coach = st.tabs([
    "📋 Overzicht", "📊 Trainingsbelasting", "🤖 AI-coach"
])

# ============================================================
# TAB 1 — OVERZICHT
# ============================================================
with tab_overzicht:
    st.subheader("Deze maand")
    last_30 = df_filtered[df_filtered["start_date"] >= datetime.now() - timedelta(days=30)]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Activiteiten", len(last_30))
    c2.metric("Kilometers", f"{last_30['distance_km'].sum():.1f}")
    c3.metric("Uren", f"{last_30['moving_time_min'].sum() / 60:.1f}")
    avg_hr = last_30["avg_heartrate"].mean()
    c4.metric("Gem. hartslag", f"{avg_hr:.0f}" if pd.notna(avg_hr) else "—")

    st.subheader("Kilometers per week")
    weekly = df_filtered.groupby("week")["distance_km"].sum().reset_index()
    weekly = weekly.tail(16)
    fig = px.bar(weekly, x="week", y="distance_km", labels={"distance_km": "km", "week": "Week"})
    fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Recente activiteiten")
    display_cols = [
        "start_date", "name", "type", "distance_km",
        "moving_time_min", "avg_pace_min_per_km", "avg_heartrate",
    ]
    df_display = df_filtered[display_cols].head(30).copy()
    df_display["start_date"] = df_display["start_date"].dt.strftime("%d-%m-%Y")
    df_display["avg_pace_min_per_km"] = df_display["avg_pace_min_per_km"].apply(format_pace)
    df_display["moving_time_min"] = df_display["moving_time_min"].apply(format_duration)
    df_display.columns = ["Datum", "Naam", "Type", "km", "Tijd", "Pace", "Gem. HR"]
    st.dataframe(df_display, use_container_width=True, hide_index=True)

# ============================================================
# TAB 2 — TRAININGSBELASTING
# ============================================================
with tab_belasting:
    race = get_active_race_goal()
    if race:
        days_to_race = (race["race_date"] - datetime.now().date()).days
        weeks_to_race = days_to_race / 7
        target_min = race["target_time_seconds"] // 60
        target_sec = race["target_time_seconds"] % 60
        target_pace_sec = race["target_time_seconds"] / race["distance_km"]
        tp_min = int(target_pace_sec // 60)
        tp_s = int(target_pace_sec % 60)

        st.subheader(f"🎯 {race['name']}")
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("Datum", race["race_date"].strftime("%d-%m-%Y"))
        rc2.metric("Nog te gaan", f"{days_to_race} dgn ({weeks_to_race:.1f} wk)")
        rc3.metric("Streeftijd", f"{target_min}:{target_sec:02d}")
        rc4.metric("Doelpace", f"{tp_min}:{tp_s:02d}/km")
        if race.get("notes"):
            st.caption(race["notes"])
        st.divider()

    df_with_tss = add_tss_column(df_filtered)
    curves = calculate_load_curves(df_with_tss)

    if curves.empty:
        st.info("Niet genoeg data voor trainingsbelasting. Sync eerst je Strava.")
        st.stop()

    current = get_current_metrics(df_filtered)
    st.subheader("Huidige status")
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Fitness (CTL)", f"{current['ctl']:.0f}")
    mc2.metric("Vermoeidheid (ATL)", f"{current['atl']:.0f}")
    mc3.metric("Form (TSB)", f"{current['tsb']:+.0f}")
    mc4.metric("Status", current["label"])
    st.info(f"💡 {current['advies']}")

    st.subheader("Belasting over tijd")
    show_days = st.select_slider(
        "Periode tonen:",
        options=[30, 60, 90, 180, 365, 9999],
        value=180,
        format_func=lambda x: "Alles" if x == 9999 else f"{x} dagen",
    )
    if show_days != 9999:
        cutoff = datetime.now() - timedelta(days=show_days)
        curves_view = curves[curves.index >= cutoff]
    else:
        curves_view = curves

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=curves_view.index, y=curves_view["ctl"],
        mode="lines", name="Fitness (CTL)",
        line=dict(color="#1f77b4", width=2.5),
    ))
    fig2.add_trace(go.Scatter(
        x=curves_view.index, y=curves_view["atl"],
        mode="lines", name="Vermoeidheid (ATL)",
        line=dict(color="#d62728", width=2),
    ))
    fig2.add_trace(go.Scatter(
        x=curves_view.index, y=curves_view["tsb"],
        mode="lines", name="Form (TSB)",
        line=dict(color="#2ca02c", width=2),
        fill="tozeroy", fillcolor="rgba(44,160,44,0.1)",
    ))
    fig2.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)
    fig2.update_layout(
        height=420,
        margin=dict(l=0, r=0, t=10, b=0),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("TSS per training")
    tss_df = df_with_tss[["start_date", "name", "distance_km", "moving_time_min", "avg_heartrate", "tss"]].head(20).copy()
    tss_df["start_date"] = tss_df["start_date"].dt.strftime("%d-%m-%Y")
    tss_df["moving_time_min"] = tss_df["moving_time_min"].apply(format_duration)
    tss_df.columns = ["Datum", "Naam", "km", "Tijd", "Gem. HR", "TSS"]
    st.dataframe(tss_df, use_container_width=True, hide_index=True)

    st.caption("Berekend met LTHR = 175 bpm. Aanpasbaar in `metrics.py`.")

# ============================================================
# TAB 3 — AI-COACH
# ============================================================
with tab_coach:
    from coach import continue_conversation

    st.subheader("Wekelijks trainingsadvies")
    st.caption(
        "Claude analyseert je laatste 14 dagen (alle sporten), je trainingsbelasting "
        "en je race-doel. Bedoeld als richtlijn — niet als verplichting."
    )

    race = get_active_race_goal()
    if not race:
        st.warning("Geen actief race-doel gevonden. Voeg er één toe via Supabase.")
        st.stop()

    # df_filtered = alleen geselecteerde sporten (vaak alleen Run)
    # df = alles, voor de coach handig voor cross-training context
    df_for_coach_run = df_filtered  # voor CTL/ATL/TSB
    df_for_coach_all = df  # voor "wat heb je recent gedaan" (incl. fiets)

    st.markdown("**Hoe voel je je deze week?** *(optioneel)*")
    user_feeling = st.text_area(
        "Bijv. 'kuit zeurt nog wat na zaterdag', 'voelt allemaal goed', 'drukke werkweek dus weinig tijd'",
        height=100,
        label_visibility="collapsed",
        key="user_feeling",
    )

    col_a, col_b = st.columns([1, 1])
    with col_a:
        if st.button("🤖 Genereer nieuw weekadvies", type="primary"):
            with st.spinner("Claude denkt na over je week..."):
                try:
                    advice = generate_weekly_advice(
                        df_for_coach_all, df_for_coach_run, race, user_feeling
                    )
                    st.session_state["chat_history"] = [
                        {"role": "assistant", "content": advice}
                    ]
                    st.session_state["advice_timestamp"] = datetime.now()
                except Exception as e:
                    st.error(f"Kon geen advies genereren: {e}")

    with col_b:
        if st.button("🗑️ Wis gesprek"):
            st.session_state.pop("chat_history", None)
            st.session_state.pop("advice_timestamp", None)
            st.rerun()

    # Toon gesprek
    if "chat_history" in st.session_state:
        ts = st.session_state.get("advice_timestamp")
        if ts:
            st.caption(f"Gestart op {ts.strftime('%d-%m-%Y %H:%M')}")
        st.markdown("---")

        for msg in st.session_state["chat_history"]:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("user", avatar="🏃"):
                    st.markdown(msg["content"])

        # Vervolgvraag
        st.markdown("---")
        st.markdown("**Reactie of vervolgvraag:**")
        followup = st.text_area(
            "Stel een vervolgvraag of beantwoord de coach",
            height=100,
            label_visibility="collapsed",
            key="followup_input",
        )
        if st.button("📤 Stuur reactie"):
            if followup.strip():
                with st.spinner("Claude denkt na..."):
                    try:
                        # Bouw history voor Claude (eerste user-bericht is de context)
                        from coach import _build_user_message
                        history_for_claude = [
                            {"role": "user", "content": _build_user_message(
                                df_for_coach_all, df_for_coach_run, race, user_feeling
                            )},
                        ]
                        for m in st.session_state["chat_history"]:
                            history_for_claude.append(m)

                        reply = continue_conversation(
                            history_for_claude,
                            df_for_coach_all,
                            df_for_coach_run,
                            race,
                            followup,
                        )
                        st.session_state["chat_history"].append(
                            {"role": "user", "content": followup}
                        )
                        st.session_state["chat_history"].append(
                            {"role": "assistant", "content": reply}
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Kon geen antwoord genereren: {e}")
