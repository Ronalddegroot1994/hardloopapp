"""Streamlit dashboard - hoofdpagina met donker neon-thema."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from database import (
    init_db, get_all_activities, get_tokens, get_active_race_goal,
    get_all_races, get_upcoming_races, get_next_a_race,
    add_race, update_race, delete_race,
)
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
race = get_next_a_race() or get_active_race_goal()
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
tab_overzicht, tab_belasting, tab_zones, tab_races, tab_coach = st.tabs([
    "📋 Overzicht", "📊 Belasting", "⚡ Zones", "📅 Races", "🤖 Coach"
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

    st.caption("hrTSS berekend met LTHR = 170 bpm. Aanpasbaar in `metrics.py`.")

# ============================================================
# TAB 3 — ZONES
# ============================================================
with tab_zones:
    from streams import get_zones_for_activities

    st.markdown("#### Tijd in zones")
    st.caption(
        "Op basis van Strava-streamdata. Friel-zones gebaseerd op LTHR=170 (HR) "
        "en threshold pace 3:55/km (pace)."
    )

    period = st.radio(
        "Periode",
        ["Laatste 7 dagen", "Laatste 28 dagen", "Laatste 90 dagen", "Alles"],
        horizontal=True,
        index=1,
    )
    days_map = {"Laatste 7 dagen": 7, "Laatste 28 dagen": 28, "Laatste 90 dagen": 90, "Alles": 9999}
    days = days_map[period]

    if days < 9999:
        cutoff = datetime.now() - timedelta(days=days)
        df_period = df_filtered[df_filtered["start_date"] >= cutoff]
    else:
        df_period = df_filtered

    if df_period.empty:
        st.info("Geen activiteiten in deze periode.")
        st.stop()

    strava_ids = df_period["strava_id"].tolist()
    zones_dict = get_zones_for_activities(strava_ids)

    if not zones_dict:
        st.warning("Geen zone-data beschikbaar. Backfill via de sidebar.")
        st.stop()

    hr_totals = {z: 0 for z in ["z1", "z2", "z3", "z4", "z5"]}
    pace_totals = {z: 0 for z in ["z1", "z2", "z3", "z4", "z5"]}
    activities_with_data = 0

    for sid in strava_ids:
        if sid in zones_dict:
            z = zones_dict[sid]
            if z.get("has_streams"):
                activities_with_data += 1
                for zn in ["z1", "z2", "z3", "z4", "z5"]:
                    hr_totals[zn] += z.get(f"hr_{zn}_sec") or 0
                    pace_totals[zn] += z.get(f"pace_{zn}_sec") or 0

    total_hr = sum(hr_totals.values())
    total_pace = sum(pace_totals.values())

    if total_hr == 0:
        st.info("Geen HR-streamdata in deze periode.")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("Activiteiten", activities_with_data)
    c2.metric("Tijd totaal (HR)", f"{total_hr / 3600:.1f} uur")
    z2_pct_kpi = (hr_totals["z2"] / total_hr) * 100 if total_hr > 0 else 0
    c3.metric("Z2-aandeel", f"{z2_pct_kpi:.0f}%")

    z1_pct = hr_totals["z1"] / total_hr * 100
    z2_pct = hr_totals["z2"] / total_hr * 100
    z3_pct = hr_totals["z3"] / total_hr * 100
    z4_pct = hr_totals["z4"] / total_hr * 100
    z5_pct = hr_totals["z5"] / total_hr * 100

    easy = z1_pct + z2_pct
    moderate = z3_pct
    hard = z4_pct + z5_pct

    if z2_pct < 30 and z1_pct > 40:
        verdict = "💤 **Te veel Z1 (te makkelijk)**"
        extra = ("Veel van je 'rustige' loopjes zit in Z1. Dat is herstel-zone, niet trainings-stimulus. "
                 "Als je sneller wilt worden: lopjes iets steviger maken zodat je in Z2 zit "
                 f"(rond {int(170 * 0.85)}-{int(170 * 0.89)} bpm).")
        color = "#00d4ff"
    elif easy >= 75 and hard >= 12 and moderate < 20:
        verdict = "🎯 **Goed gepolariseerd**"
        extra = (f"Mooie 80/20-verdeling: {easy:.0f}% rustig, {hard:.0f}% hard, weinig grijze zone. "
                 "Dit is precies hoe ervaren coaches het voorschrijven.")
        color = "#00ff9d"
    elif moderate > 25:
        verdict = "⚠️ **Te veel grijze zone (Z3)**"
        extra = (f"{moderate:.0f}% in Z3 is veel — dat is 'tempo' wat zwaar genoeg is om vermoeid te raken, "
                 "maar te licht voor echte snelheidswinst. Liever splitsen: meer Z2 + meer Z4-Z5.")
        color = "#ff8c42"
    elif hard < 5 and easy > 90:
        verdict = "💤 **Bijna alles rustig — geen scherpte**"
        extra = ("Voor je 10K-doel heb je drempelwerk en intervallen nodig. "
                 "Streef naar 10-20% Z4-Z5 per week.")
        color = "#00d4ff"
    elif z2_pct >= 50:
        verdict = "✅ **Solide Z2-basis**"
        extra = (f"{z2_pct:.0f}% Z2 is een sterke aerobic basis. Voeg gerust 1-2 kwaliteitssessies "
                 "(Z4-Z5) per week toe voor scherpte.")
        color = "#00ff9d"
    else:
        verdict = "📊 **Gemengde verdeling**"
        extra = "Geen duidelijk dominant patroon. Voor 10K-prep: streef naar ~70% Z2, 5-10% Z3, 15-20% Z4-Z5."
        color = "#8a92a6"

    st.markdown(f"""
    <div style="background: {color}11; border-left: 3px solid {color}; 
                padding: 14px 18px; border-radius: 8px; margin: 16px 0;">
        <div style="font-size: 1.05rem; margin-bottom: 6px;">{verdict}</div>
        <div style="color: #b8bdcc; font-size: 0.9rem; margin-bottom: 10px;">{extra}</div>
        <div style="color: #8a92a6; font-size: 0.82rem; padding-top: 8px; border-top: 1px solid #2a3148;">
        Z1: {z1_pct:.0f}% • Z2: {z2_pct:.0f}% • Z3: {z3_pct:.0f}% • Z4: {z4_pct:.0f}% • Z5: {z5_pct:.0f}%
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("#### Hartslagzones")
    zone_labels = ["Z1 (herstel)", "Z2 (aerobe basis)", "Z3 (tempo)", "Z4 (drempel)", "Z5 (VO2max)"]
    zone_keys = ["z1", "z2", "z3", "z4", "z5"]
    hr_values_min = [hr_totals[z] / 60 for z in zone_keys]
    zone_colors = ["#00d4ff", "#00ff9d", "#ffd700", "#ff8c42", "#ff4d6d"]

    fig_hr = go.Figure(data=[
        go.Bar(
            x=zone_labels, y=hr_values_min,
            marker_color=zone_colors,
            text=[f"{v:.0f} min<br>{v / sum(hr_values_min) * 100:.0f}%" for v in hr_values_min],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>%{y:.0f} min<extra></extra>",
        )
    ])
    fig_hr.update_layout(
        **PLOTLY_TEMPLATE["layout"],
        height=350,
        margin=dict(l=0, r=0, t=20, b=0),
        showlegend=False,
        yaxis_title="Minuten",
    )
    st.plotly_chart(fig_hr, use_container_width=True)

    if total_pace > 0:
        st.markdown("#### Pace-zones (alleen hardlopen)")
        pace_zone_labels = [
            "Z1 (>4:42/km)", "Z2 (4:09-4:42)", "Z3 (3:55-4:09)",
            "Z4 (3:43-3:55)", "Z5 (<3:43/km)",
        ]
        pace_values_min = [pace_totals[z] / 60 for z in zone_keys]

        fig_pace = go.Figure(data=[
            go.Bar(
                x=pace_zone_labels, y=pace_values_min,
                marker_color=zone_colors,
                text=[f"{v:.0f} min<br>{v / sum(pace_values_min) * 100:.0f}%"
                      if sum(pace_values_min) > 0 else "0"
                      for v in pace_values_min],
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>%{y:.0f} min<extra></extra>",
            )
        ])
        fig_pace.update_layout(
            **PLOTLY_TEMPLATE["layout"],
            height=350,
            margin=dict(l=0, r=0, t=20, b=0),
            showlegend=False,
            yaxis_title="Minuten",
        )
        st.plotly_chart(fig_pace, use_container_width=True)

    st.caption(
        "💡 **Polarisatie-richtlijn:** ~80% rustig (Z1+Z2), <10% middenzone (Z3), "
        "~10-20% hard (Z4+Z5). Voor 10K-prep is iets meer Z3-Z4 oké."
    )

# ============================================================
# TAB 4 — RACES
# ============================================================
with tab_races:
    st.markdown("#### Race-kalender")
    st.caption("Beheer je komende wedstrijden en doelen.")

    type_emoji = {"A": "🎯", "B": "🧪", "C": "🤝"}
    type_label = {
        "A": "A-race (hoofddoel)",
        "B": "B-race (test/tussenmeting)",
        "C": "C-race (plezier/hazen)",
    }

    with st.expander("➕ Nieuwe race toevoegen", expanded=False):
        with st.form("new_race", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input("Naam *", placeholder="bv. Halve van Egmond")
                new_date = st.date_input("Datum *", value=datetime.now().date() + timedelta(days=30))
                new_distance = st.number_input("Afstand (km) *", min_value=0.1, value=10.0, step=0.1)
            with col2:
                new_type = st.selectbox(
                    "Race-type *",
                    options=["A", "B", "C"],
                    format_func=lambda t: f"{type_emoji[t]} {type_label[t]}",
                )
                st.markdown("**Streeftijd** *(optioneel)*")
                tcol1, tcol2 = st.columns(2)
                with tcol1:
                    new_min = st.number_input("Minuten", min_value=0, max_value=600, value=0, step=1)
                with tcol2:
                    new_sec = st.number_input("Seconden", min_value=0, max_value=59, value=0, step=1)
            new_notes = st.text_area("Notities", placeholder="bv. 'hazen voor Mark, geen prestatiedruk'", height=80)

            submitted = st.form_submit_button("💾 Race toevoegen", type="primary", use_container_width=True)
            if submitted:
                if not new_name.strip():
                    st.error("Naam is verplicht.")
                else:
                    target_sec = (new_min * 60 + new_sec) if (new_min + new_sec) > 0 else None
                    try:
                        add_race(
                            name=new_name.strip(),
                            distance_km=float(new_distance),
                            race_date=new_date,
                            target_time_seconds=target_sec,
                            race_type=new_type,
                            notes=new_notes.strip(),
                        )
                        st.success(f"'{new_name}' toegevoegd!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Toevoegen mislukt: {e}")

    st.divider()

    upcoming = get_upcoming_races()
    if not upcoming:
        st.info("Nog geen komende races. Voeg er één toe hierboven.")
    else:
        st.markdown(f"##### Komende races ({len(upcoming)})")
        for r in upcoming:
            days_to = (r["race_date"] - datetime.now().date()).days
            weeks_to = days_to / 7
            emo = type_emoji.get(r["race_type"], "🏃")

            target_str = "—"
            pace_str = "—"
            if r.get("target_time_seconds"):
                tm = r["target_time_seconds"] // 60
                ts = r["target_time_seconds"] % 60
                target_str = f"{tm}:{ts:02d}"
                tpace = r["target_time_seconds"] / r["distance_km"]
                pace_str = f"{int(tpace // 60)}:{int(tpace % 60):02d}/km"

            with st.container():
                st.markdown(f"""
                <div style="background: #151b2e; border-left: 3px solid #00ff9d; 
                            border-radius: 8px; padding: 14px 18px; margin-bottom: 10px;">
                    <div style="font-size: 1.05rem; font-weight: 600; margin-bottom: 4px;">
                        {emo} {r['name']}
                    </div>
                    <div style="color: #8a92a6; font-size: 0.85rem; margin-bottom: 8px;">
                        {type_label[r['race_type']]} • {r['distance_km']} km
                    </div>
                    <div style="display: flex; gap: 24px; flex-wrap: wrap; font-size: 0.9rem;">
                        <div><span style="color: #8a92a6;">Datum:</span> <b>{r['race_date'].strftime('%d %b %Y')}</b></div>
                        <div><span style="color: #8a92a6;">Over:</span> <b>{days_to} dgn ({weeks_to:.1f} wk)</b></div>
                        <div><span style="color: #8a92a6;">Tijddoel:</span> <b>{target_str}</b></div>
                        <div><span style="color: #8a92a6;">Pace:</span> <b>{pace_str}</b></div>
                    </div>
                    {f'<div style="color: #b8bdcc; font-size: 0.85rem; margin-top: 8px; font-style: italic;">{r["notes"]}</div>' if r.get("notes") else ""}
                </div>
                """, unsafe_allow_html=True)

                bcol1, bcol2, _ = st.columns([1, 1, 4])
                with bcol1:
                    if st.button("✏️ Bewerk", key=f"edit_{r['id']}"):
                        st.session_state[f"editing_{r['id']}"] = True
                with bcol2:
                    if st.button("🗑️ Verwijder", key=f"del_{r['id']}"):
                        st.session_state[f"confirm_del_{r['id']}"] = True

                if st.session_state.get(f"editing_{r['id']}"):
                    with st.form(f"edit_form_{r['id']}"):
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            e_name = st.text_input("Naam", value=r["name"])
                            e_date = st.date_input("Datum", value=r["race_date"])
                            e_distance = st.number_input("Afstand (km)", min_value=0.1,
                                                          value=float(r["distance_km"]), step=0.1)
                        with ec2:
                            e_type = st.selectbox(
                                "Type",
                                options=["A", "B", "C"],
                                index=["A", "B", "C"].index(r["race_type"]),
                                format_func=lambda t: f"{type_emoji[t]} {type_label[t]}",
                            )
                            cur_min = (r["target_time_seconds"] // 60) if r.get("target_time_seconds") else 0
                            cur_sec = (r["target_time_seconds"] % 60) if r.get("target_time_seconds") else 0
                            tc1, tc2 = st.columns(2)
                            with tc1:
                                e_min = st.number_input("Min", min_value=0, max_value=600, value=cur_min)
                            with tc2:
                                e_sec = st.number_input("Sec", min_value=0, max_value=59, value=cur_sec)
                        e_notes = st.text_area("Notities", value=r.get("notes") or "", height=80)

                        bc1, bc2 = st.columns(2)
                        with bc1:
                            saved = st.form_submit_button("💾 Opslaan", type="primary", use_container_width=True)
                        with bc2:
                            cancel = st.form_submit_button("Annuleren", use_container_width=True)

                        if saved:
                            try:
                                tsec = (e_min * 60 + e_sec) if (e_min + e_sec) > 0 else None
                                update_race(r["id"], e_name.strip(), float(e_distance),
                                            e_date, tsec, e_type, e_notes.strip())
                                st.session_state[f"editing_{r['id']}"] = False
                                st.success("Opgeslagen!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Opslaan mislukt: {e}")
                        if cancel:
                            st.session_state[f"editing_{r['id']}"] = False
                            st.rerun()

                if st.session_state.get(f"confirm_del_{r['id']}"):
                    st.warning(f"Weet je zeker dat je '{r['name']}' wilt verwijderen?")
                    cc1, cc2, _ = st.columns([1, 1, 4])
                    with cc1:
                        if st.button("Ja, verwijder", key=f"yes_del_{r['id']}", type="primary"):
                            try:
                                delete_race(r["id"])
                                st.session_state[f"confirm_del_{r['id']}"] = False
                                st.success("Verwijderd.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Mislukt: {e}")
                    with cc2:
                        if st.button("Annuleer", key=f"no_del_{r['id']}"):
                            st.session_state[f"confirm_del_{r['id']}"] = False
                            st.rerun()

    all_races = get_all_races()
    past = [r for r in all_races if r["race_date"] < datetime.now().date()]
    if past:
        with st.expander(f"📜 Geschiedenis ({len(past)} voorbije races)"):
            for r in sorted(past, key=lambda x: x["race_date"], reverse=True):
                emo = type_emoji.get(r["race_type"], "🏃")
                target_str = ""
                if r.get("target_time_seconds"):
                    tm = r["target_time_seconds"] // 60
                    ts = r["target_time_seconds"] % 60
                    target_str = f" — doel was {tm}:{ts:02d}"
                st.markdown(
                    f"- {emo} **{r['name']}** ({r['race_date'].strftime('%d-%m-%Y')}, "
                    f"{r['distance_km']} km{target_str})"
                )

# ============================================================
# TAB 5 — AI-COACH
# ============================================================
with tab_coach:
    st.markdown("#### Wekelijks trainingsadvies")
    st.caption(
        "Claude analyseert je laatste 14 dagen, je belasting, je zone-verdeling "
        "en je race-doel. Bedoeld als richtlijn — niet als verplichting."
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
