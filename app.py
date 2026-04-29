"""Streamlit dashboard - hoofdpagina met donker neon-thema."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from database import init_db, get_all_activities, get_tokens, get_active_race_goal
from strava_sync import sync_all, exchange_code_for_token
from metrics import add_tss_column, calculate_load_curves, get_current_metrics
from coach import generate_weekly_advice, continue_conversation, _build_user_message
from style import apply_style, race_hero_banner, status_badge

st.set_page_config(
    page_title="Hardloopportaal",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="auto",
)
init_db()
apply_style()

# === Plotly donker thema ===
PLOTLY_TEMPLATE = {
    "layout": {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(21,27,46,0.4)",
        "font": {"color": "#e8eaed", "family": "sans-serif"},
        "xaxis": {"gridcolor": "#2a3148", "linecolor": "#2a3148", "zerolinecolor": "#2a3148"},
        "yaxis": {"gridcolor": "#2a3148", "linecolor": "#2a3148", "zerolinecolor": "#2a3148"},
        "colorway": ["#00ff9d", "#00d4ff", "#ff8c42", "#ff4d6d", "#a78bfa"],
    }
}

# === Secrets ===
CLIENT_ID = st.secrets.get("STRAVA_CLIENT_ID", "")
CLIENT_SECRET = st.secrets.get("STRAVA_CLIENT_SECRET", "")

st.title("🏃 Hardloopportaal")

# === OAuth-flow (eerste keer) ===
tokens = get_tokens()
if not tokens:
    st.warning("Strava is nog niet gekoppeld.")
    redirect_uri = "https://ronalds-hardloopapp.streamlit.app"
    auth_url = (
        f"https://www.strava.com/oauth/authorize?"
        f"client_id={CLIENT_ID}&response_type=code&redirect_uri={redirect_uri}"
        f"&approval_prompt=force&scope=read,activity:read_all"
    )
    st.markdown(f"**Stap 1:** [Klik hier om Strava te koppelen]({auth_url})")
    st.markdown("**Stap 2:** Plak de `code` uit de URL hieronder.")
    code = st.text_input("Code:")
    if st.button("Koppel Strava") and code:
        try:
            exchange_code_for_token(CLIENT_ID, CLIENT_SECRET, code.strip())
            st.success("Gekoppeld! Ververs de pagina.")
            st.rerun()
        except Exception as e:
            st.error(f"Koppelen mislukt: {e}")
    st.stop()

# === Data laden ===
activities = get_all_activities()
if not activities:
    st.info("Nog geen activiteiten. Klik op 'Sync Strava' in de zijbalk om te beginnen.")
    if st.sidebar.button("🔄 Sync Strava"):
        with st.spinner("Activiteiten ophalen..."):
            try:
                count = sync_all(CLIENT_ID, CLIENT_SECRET)
                st.success(f"{count} activiteiten gesynchroniseerd.")
                st.rerun()
            except Exception as e:
                st.error(f"Sync mislukt: {e}")
    st.stop()

df = pd.DataFrame(activities)
df["start_date"] = pd.to_datetime(df["start_date"], utc=True).dt.tz_localize(None)
df["week"] = df["start_date"].dt.to_period("W").apply(lambda p: p.start_time)

# === Sidebar: filter + sync ===
with st.sidebar:
    st.markdown("### Instellingen")
    sport_options = sorted(df["type"].unique())
    selected_sports = st.multiselect(
        "Sporten",
        sport_options,
        default=[s for s in sport_options if "Run" in s] or sport_options,
    )
    st.divider()
    if st.button("🔄 Sync Strava", use_container_width=True):
        with st.spinner("Activiteiten ophalen..."):
            try:
                count = sync_all(CLIENT_ID, CLIENT_SECRET)
                st.success(f"{count} gesynchroniseerd.")
                st.rerun()
            except Exception as e:
                st.error(f"Mislukt: {e}")
    st.caption(f"Laatste data: {df['start_date'].max().strftime('%d-%m-%Y')}")
    st.divider()
    st.markdown("##### Zone-data backfill")
    from streams import backfill_batch, get_activities_without_zones
    remaining = len(get_activities_without_zones(limit=10000))
    st.caption(f"Nog te backfillen: **{remaining}** activiteiten")
    if remaining > 0:
        if st.button("⚡ Backfill 50", use_container_width=True):
            tokens_data = get_tokens()
            if tokens_data:
                from strava_sync import refresh_access_token
                try:
                    access_token = refresh_access_token(CLIENT_ID, CLIENT_SECRET)
                    progress_bar = st.progress(0, text="Bezig...")

                    def update_progress(i, total, name):
                        progress_bar.progress(i / total, text=f"{i}/{total}: {name[:30]}")

                    s, f, msg = backfill_batch(access_token, 50, update_progress)
                    progress_bar.empty()
                    if "Rate-limit" in msg:
                        st.warning(msg)
                    else:
                        st.success(msg)
                    st.rerun()
                except Exception as e:
                    st.error(f"Mislukt: {e}")

df_filtered = df[df["type"].isin(selected_sports)]

# === Helpers ===
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


# === Race hero (boven de tabs) ===
race = get_active_race_goal()
if race:
    days_to_race = (race["race_date"] - datetime.now().date()).days
    weeks_to_race = days_to_race / 7
    target_min = race["target_time_seconds"] // 60
    target_sec = race["target_time_seconds"] % 60
    target_pace_sec = race["target_time_seconds"] / race["distance_km"]
    tp_min = int(target_pace_sec // 60)
    tp_s = int(target_pace_sec % 60)

    race_hero_banner(
        name=race["name"],
        date_str=race["race_date"].strftime("%d %b %Y"),
        days_to_go=f"{days_to_race} dgn ({weeks_to_race:.1f} wk)",
        target_time=f"{target_min}:{target_sec:02d}",
        target_pace=f"{tp_min}:{tp_s:02d}/km",
        note=race.get("notes", "") or "",
    )

# === Tabs ===
tab_overzicht, tab_belasting, tab_coach = st.tabs([
    "📋 Overzicht", "📊 Belasting", "🤖 Coach"
])

# ============================================================
# TAB 1 — OVERZICHT
# ============================================================
with tab_overzicht:
    st.markdown("#### Laatste 30 dagen")
    last_30 = df_filtered[df_filtered["start_date"] >= datetime.now() - timedelta(days=30)]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Activiteiten", len(last_30))
    c2.metric("Kilometers", f"{last_30['distance_km'].sum():.0f}")
    c3.metric("Uren", f"{last_30['moving_time_min'].sum() / 60:.1f}")
    avg_hr = last_30["avg_heartrate"].mean()
    c4.metric("Gem. HR", f"{avg_hr:.0f}" if pd.notna(avg_hr) else "—")

    st.markdown("#### Kilometers per week")
    weekly = df_filtered.groupby("week")["distance_km"].sum().reset_index()
    weekly = weekly.tail(16)
    fig = go.Figure(data=[
        go.Bar(
            x=weekly["week"], y=weekly["distance_km"],
            marker=dict(
                color=weekly["distance_km"],
                colorscale=[[0, "#00d4ff"], [1, "#00ff9d"]],
                line=dict(width=0),
            ),
            hovertemplate="<b>%{x|%d %b}</b><br>%{y:.1f} km<extra></extra>",
        )
    ])
    fig.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
        xaxis_title="",
        yaxis_title="km",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Recente activiteiten")
    display_cols = [
        "start_date", "name", "type", "distance_km",
        "moving_time_min", "avg_pace_min_per_km", "avg_heartrate",
    ]
    df_display = df_filtered[display_cols].head(20).copy()
    df_display["start_date"] = df_display["start_date"].dt.strftime("%d-%m")
    df_display["avg_pace_min_per_km"] = df_display["avg_pace_min_per_km"].apply(format_pace)
    df_display["moving_time_min"] = df_display["moving_time_min"].apply(format_duration)
    df_display["distance_km"] = df_display["distance_km"].round(1)
    df_display["avg_heartrate"] = df_display["avg_heartrate"].apply(
        lambda x: f"{int(x)}" if pd.notna(x) else "—"
    )
    df_display.columns = ["Datum", "Naam", "Type", "km", "Tijd", "Pace", "HR"]
    st.dataframe(df_display, use_container_width=True, hide_index=True)

# ============================================================
# TAB 2 — TRAININGSBELASTING
# ============================================================
with tab_belasting:
    df_with_tss = add_tss_column(df_filtered)
    curves = calculate_load_curves(df_with_tss)

    if curves.empty:
        st.info("Niet genoeg data voor trainingsbelasting.")
        st.stop()

    current = get_current_metrics(df_filtered)

    st.markdown("#### Huidige status")
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Fitness (CTL)", f"{current['ctl']:.0f}")
    mc2.metric("Vermoeidheid (ATL)", f"{current['atl']:.0f}")
    mc3.metric("Form (TSB)", f"{current['tsb']:+.0f}")

    st.markdown(
        f"**Status:** {status_badge(current['label'])}",
        unsafe_allow_html=True,
    )
    st.info(f"💡 {current['advies']}")

    st.markdown("#### Belasting over tijd")
    show_days = st.select_slider(
        "Periode",
        options=[30, 60, 90, 180, 365, 9999],
        value=180,
        format_func=lambda x: "Alles" if x == 9999 else f"{x} dgn",
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
        line=dict(color="#00d4ff", width=2.5),
    ))
    fig2.add_trace(go.Scatter(
        x=curves_view.index, y=curves_view["atl"],
        mode="lines", name="Vermoeidheid (ATL)",
        line=dict(color="#ff4d6d", width=2),
    ))
    fig2.add_trace(go.Scatter(
        x=curves_view.index, y=curves_view["tsb"],
        mode="lines", name="Form (TSB)",
        line=dict(color="#00ff9d", width=2),
        fill="tozeroy", fillcolor="rgba(0,255,157,0.08)",
    ))
    fig2.add_hline(y=0, line_dash="dot", line_color="#8a92a6", opacity=0.3)
    fig2.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        height=400,
        margin=dict(l=0, r=0, t=10, b=0),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("#### TSS per training")
    tss_df = df_with_tss[["start_date", "name", "distance_km", "moving_time_min", "avg_heartrate", "tss"]].head(15).copy()
    tss_df["start_date"] = tss_df["start_date"].dt.strftime("%d-%m")
    tss_df["moving_time_min"] = tss_df["moving_time_min"].apply(format_duration)
    tss_df["distance_km"] = tss_df["distance_km"].round(1)
    tss_df["avg_heartrate"] = tss_df["avg_heartrate"].apply(
        lambda x: f"{int(x)}" if pd.notna(x) else "—"
    )
    tss_df["tss"] = tss_df["tss"].round(0).astype(int)
    tss_df.columns = ["Datum", "Naam", "km", "Tijd", "HR", "TSS"]
    st.dataframe(tss_df, use_container_width=True, hide_index=True)

    st.caption("hrTSS berekend met LTHR = 175 bpm. Aanpasbaar in `metrics.py`.")

# ============================================================
# TAB 3 — AI-COACH
# ============================================================
with tab_coach:
    st.markdown("#### Wekelijks trainingsadvies")
    st.caption(
        "Claude analyseert je laatste 14 dagen, je belasting en je race-doel. "
        "Bedoeld als richtlijn — niet als verplichting."
    )

    if not race:
        st.warning("Geen actief race-doel gevonden.")
        st.stop()

    df_for_coach_run = df_filtered
    df_for_coach_all = df

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Hoe voel je je deze week?**")
        user_feeling = st.text_area(
            "feeling",
            placeholder="bv. 'kuit zeurt nog wat', 'voelt allemaal goed', 'drukke werkweek'",
            height=100,
            label_visibility="collapsed",
            key="user_feeling",
        )
    with col_r:
        st.markdown("**Wat wil/kan je vandaag nog doen?**")
        today_status = st.text_area(
            "today",
            placeholder="bv. 'wil vandaag nog 8 km', 'klaar voor vandaag'",
            height=100,
            label_visibility="collapsed",
            key="today_status",
        )

    col_a, col_b = st.columns([3, 1])
    with col_a:
        if st.button("🤖 Genereer weekadvies", type="primary", use_container_width=True):
            with st.spinner("Claude denkt na..."):
                try:
                    advice = generate_weekly_advice(
                        df_for_coach_all, df_for_coach_run, race,
                        user_feeling, today_status,
                    )
                    initial_user_msg = _build_user_message(
                        df_for_coach_all, df_for_coach_run, race,
                        user_feeling, today_status,
                    )
                    st.session_state["chat_history"] = [
                        {"role": "user", "content": initial_user_msg},
                        {"role": "assistant", "content": advice},
                    ]
                    st.session_state["advice_timestamp"] = datetime.now()
                except Exception as e:
                    st.error(f"Mislukt: {e}")
    with col_b:
        if st.button("🗑️ Wis", use_container_width=True):
            st.session_state.pop("chat_history", None)
            st.session_state.pop("advice_timestamp", None)
            st.rerun()

    if "chat_history" in st.session_state:
        ts = st.session_state.get("advice_timestamp")
        if ts:
            st.caption(f"Gestart op {ts.strftime('%d-%m-%Y %H:%M')}")
        st.divider()

        for msg in st.session_state["chat_history"][1:]:
            if msg["role"] == "assistant":
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("user", avatar="🏃"):
                    st.markdown(msg["content"])

        st.divider()
        st.markdown("**Reactie of vervolgvraag:**")
        followup = st.text_area(
            "followup",
            placeholder="Stel een vervolgvraag of beantwoord de coach",
            height=100,
            label_visibility="collapsed",
            key="followup_input",
        )
        if st.button("📤 Stuur reactie"):
            if followup.strip():
                with st.spinner("Claude denkt na..."):
                    try:
                        reply = continue_conversation(
                            st.session_state["chat_history"],
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
                        st.error(f"Mislukt: {e}")
