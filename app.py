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
    get_user_profile, save_user_profile,
    get_all_records, add_record, update_record, delete_record,
    get_active_schedule, create_schedule, update_schedule,
    archive_active_schedule, get_schedule_history,
    get_widget_cache, save_widget_cache,
    get_user_settings, save_user_settings,
)
from strava_sync import sync_all, exchange_code_for_token
from metrics import add_tss_column, calculate_load_curves, get_current_metrics
from coach import (
    generate_weekly_advice, continue_conversation, _build_user_message,
    generate_schedule, update_schedule_with_feedback,
    generate_today_summary, datum_nl, estimate_lthr_from_activities,
)
from style import apply_style, race_hero_banner, status_badge

st.set_page_config(
    page_title="Hardloopapp Ronald",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="auto",
)
init_db()
apply_style()

# === Plotly mobiel-config (voorkomt zoom-hijack bij scrollen) ===
PLOTLY_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "staticPlot": False,
    "doubleClick": False,
    "showAxisDragHandles": False,
    "showAxisRangeEntryBoxes": False,
}

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

st.title("🏃 Hardloopapp Ronald")

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

settings = get_user_settings()

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


# === Today widget (boven race-hero) ===
_schedule = get_active_schedule()
_today = datetime.now().date()

_df_run_w = df[df["type"].isin(["Run", "VirtualRun", "TrailRun"])]
_metrics_w = get_current_metrics(_df_run_w, settings["lthr"])
_tsb_val = _metrics_w["tsb"]
_tsb_label = _metrics_w["label"]
_label_lower = _tsb_label.lower()
if "fris" in _label_lower:
    _tsb_color = "#00ff9d"
elif "neutraal" in _label_lower or "productief" in _label_lower:
    _tsb_color = "#00d4ff"
else:
    _tsb_color = "#ff8c42"

_today_acts = df[df["start_date"].dt.date == _today]
if not _today_acts.empty:
    _parts = []
    for _, _r in _today_acts.iterrows():
        _parts.append(f"{_r['type']} {_r['distance_km']:.1f} km in {int(_r['moving_time_min'])} min")
    _today_activity_summary = " + ".join(_parts)
    _today_done = True
else:
    _today_activity_summary = "nog niets"
    _today_done = False

_race_w = get_next_a_race() or get_active_race_goal()
_race_line_html = ""
if _race_w:
    _days_left = (_race_w["race_date"] - _today).days
    _race_line_html = f'<span class="tw-race">🎯 Nog {_days_left} dagen tot {_race_w["name"]}</span>'

if not _schedule:
    st.markdown("""
    <div class="today-widget">
        <div class="tw-date">🗓️ Vandaag — geen schema</div>
        <div class="tw-summary">
            Maak een weekschema via de <strong>Coach-tab</strong> om hier je dagplanning te zien.
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    _w_col, _btn_col = st.columns([11, 1])
    with _btn_col:
        if st.button("🔄", help="Widget verversen", key="widget_refresh"):
            st.session_state["widget_force_refresh"] = True
            st.rerun()
    with _w_col:
        _force = st.session_state.get("widget_force_refresh", False)
        _cache = get_widget_cache()
        if _cache and not _force:
            _summary = _cache["widget_text"]
        else:
            with st.spinner("Widget laden..."):
                _summary = generate_today_summary(
                    _schedule["schedule_text"],
                    datum_nl(_today),
                    _today_activity_summary,
                )
            save_widget_cache(_summary)
            st.session_state["widget_force_refresh"] = False

        _done_icon = "✅ Klaar!" if _today_done else "⏳ Nog niet gedaan"
        st.markdown(f"""
        <div class="today-widget">
            <div class="tw-date">🗓️ Vandaag — {datum_nl(_today)}</div>
            <div class="tw-summary">{_summary}</div>
            <div class="tw-row">
                <span class="tw-status">{_done_icon}</span>
                <span class="tw-form" style="color:{_tsb_color}">💪 Vorm: {_tsb_label} (TSB {_tsb_val:+.0f})</span>
                {_race_line_html}
            </div>
        </div>
        """, unsafe_allow_html=True)

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
tab_overzicht, tab_belasting, tab_zones, tab_races, tab_records, tab_instellingen, tab_coach = st.tabs([
    "📋 Overzicht", "📊 Belasting", "⚡ Zones", "📅 Races", "🏆 Records", "⚙️ Instellingen", "🤖 Coach"
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
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

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
    df_with_tss = add_tss_column(df_filtered, settings["lthr"])
    curves = calculate_load_curves(df_with_tss)

    if curves.empty:
        st.info("Niet genoeg data voor trainingsbelasting.")
        st.stop()

    current = get_current_metrics(df_filtered, settings["lthr"])

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
    st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG)

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

    st.caption(f"hrTSS berekend met LTHR = {settings['lthr']} bpm. Pas aan in de Instellingen-tab.")

# ============================================================
# TAB 3 — ZONES
# ============================================================
with tab_zones:
    from streams import get_zones_for_activities

    _tp_display = f"{settings['threshold_pace_seconds'] // 60}:{settings['threshold_pace_seconds'] % 60:02d}"
    st.markdown("#### Tijd in zones")
    st.caption(
        f"Op basis van Strava-streamdata. Friel-zones gebaseerd op LTHR={settings['lthr']} bpm (HR) "
        f"en threshold pace {_tp_display}/km (pace). Pas aan in de Instellingen-tab."
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
                 f"(rond {int(settings['lthr'] * 0.85)}-{int(settings['lthr'] * 0.89)} bpm).")
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
    st.plotly_chart(fig_hr, use_container_width=True, config=PLOTLY_CONFIG)

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
        st.plotly_chart(fig_pace, use_container_width=True, config=PLOTLY_CONFIG)

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
# TAB 5 — RECORDS
# ============================================================
with tab_records:
    st.markdown("#### Persoonlijke records")
    st.caption("Jouw officiële wedstrijd-PR's. Handmatig beheerd — alleen echte races.")

    DISTANCE_OPTIONS = ["10 km", "10 EM", "Halve marathon", "30 km", "Marathon", "Anders"]
    DISTANCE_KM_MAP = {
        "10 km": 10.0, "10 EM": 16.09, "Halve marathon": 21.1,
        "30 km": 30.0, "Marathon": 42.195,
    }

    def fmt_time(secs):
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def fmt_pace(secs, km):
        if km <= 0:
            return "—"
        pace = secs / km
        return f"{int(pace // 60)}:{int(pace % 60):02d}/km"

    with st.expander("➕ Nieuw record toevoegen", expanded=False):
        with st.form("new_record", clear_on_submit=True):
            rc1, rc2 = st.columns(2)
            with rc1:
                r_dist = st.selectbox("Afstand *", options=DISTANCE_OPTIONS)
                r_dist_custom = st.number_input(
                    "Afstand in km (alleen bij 'Anders')",
                    min_value=0.1, value=10.0, step=0.1,
                )
                r_date = st.date_input("Datum *", value=datetime.now().date())
            with rc2:
                st.markdown("**Tijd ***")
                tc1, tc2, tc3 = st.columns(3)
                with tc1:
                    r_h = st.number_input("Uur", min_value=0, max_value=9, value=0)
                with tc2:
                    r_m = st.number_input("Min", min_value=0, max_value=59, value=0)
                with tc3:
                    r_s = st.number_input("Sec", min_value=0, max_value=59, value=0)
                r_race = st.text_input("Wedstrijd", placeholder="bv. Marathon Rotterdam")
            r_notes = st.text_area("Notitie", placeholder="bv. 'warm, lastige wind'", height=70)

            submitted = st.form_submit_button("💾 Record toevoegen", type="primary", use_container_width=True)
            if submitted:
                total_sec = r_h * 3600 + r_m * 60 + r_s
                if total_sec == 0:
                    st.error("Vul een tijd in.")
                else:
                    km = DISTANCE_KM_MAP.get(r_dist, r_dist_custom)
                    label = r_dist if r_dist != "Anders" else f"{r_dist_custom} km"
                    try:
                        add_record(label, km, total_sec, r_date, r_race.strip(), r_notes.strip())
                        st.success(f"Record voor {label} toegevoegd!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Toevoegen mislukt: {e}")

    st.divider()

    records = get_all_records()
    if not records:
        st.info("Nog geen records. Voeg er één toe hierboven.")
    else:
        by_distance = {}
        for r in records:
            by_distance.setdefault(r["distance_label"], []).append(r)

        for label, recs in by_distance.items():
            recs_sorted = sorted(recs, key=lambda x: x["time_seconds"])
            best = recs_sorted[0]
            km = float(best["distance_km"])

            best_race = f" • {best['race_name']}" if best.get("race_name") else ""
            best_notes = ""
            if best.get("notes"):
                best_notes = (f'<div style="color: #b8bdcc; font-size: 0.8rem; '
                              f'margin-top: 4px; font-style: italic;">{best["notes"]}</div>')

            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #151b2e, #1a2138);
                        border-left: 3px solid #ffd700; border-radius: 8px;
                        padding: 14px 18px; margin-bottom: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: baseline;">
                    <div style="font-size: 1.1rem; font-weight: 600;">🏆 {label}</div>
                    <div style="font-size: 1.3rem; font-weight: 700; color: #ffd700;">
                        {fmt_time(best['time_seconds'])}
                    </div>
                </div>
                <div style="color: #8a92a6; font-size: 0.85rem; margin-top: 4px;">
                    {fmt_pace(best['time_seconds'], km)} •
                    {best['record_date'].strftime('%d-%m-%Y')}{best_race}
                </div>
                {best_notes}
            </div>
            """, unsafe_allow_html=True)

            if len(recs_sorted) > 1:
                with st.expander(f"Geschiedenis {label} ({len(recs_sorted)} pogingen)"):
                    for r in recs_sorted:
                        r_race_str = f" — {r['race_name']}" if r.get("race_name") else ""
                        st.markdown(
                            f"- **{fmt_time(r['time_seconds'])}** "
                            f"({fmt_pace(r['time_seconds'], float(r['distance_km']))}) — "
                            f"{r['record_date'].strftime('%d-%m-%Y')}{r_race_str}"
                        )

            bc1, bc2, _ = st.columns([1, 1, 4])
            with bc1:
                if st.button("✏️ Bewerk", key=f"edit_rec_{best['id']}"):
                    st.session_state[f"editing_rec_{best['id']}"] = True
            with bc2:
                if st.button("🗑️ Verwijder", key=f"del_rec_{best['id']}"):
                    st.session_state[f"confirm_del_rec_{best['id']}"] = True

            if st.session_state.get(f"editing_rec_{best['id']}"):
                with st.form(f"edit_rec_form_{best['id']}"):
                    e_race = st.text_input("Wedstrijd", value=best.get("race_name") or "")
                    e_date = st.date_input("Datum", value=best["record_date"])
                    etc1, etc2, etc3 = st.columns(3)
                    cur = best["time_seconds"]
                    with etc1:
                        e_h = st.number_input("Uur", min_value=0, max_value=9, value=cur // 3600)
                    with etc2:
                        e_m = st.number_input("Min", min_value=0, max_value=59, value=(cur % 3600) // 60)
                    with etc3:
                        e_s = st.number_input("Sec", min_value=0, max_value=59, value=cur % 60)
                    e_notes = st.text_area("Notitie", value=best.get("notes") or "", height=70)
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        saved = st.form_submit_button("💾 Opslaan", type="primary", use_container_width=True)
                    with ec2:
                        cancelled = st.form_submit_button("Annuleren", use_container_width=True)
                    if saved:
                        try:
                            update_record(
                                best["id"], best["distance_label"], float(best["distance_km"]),
                                e_h * 3600 + e_m * 60 + e_s, e_date, e_race.strip(), e_notes.strip(),
                            )
                            st.session_state[f"editing_rec_{best['id']}"] = False
                            st.success("Opgeslagen!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Mislukt: {e}")
                    if cancelled:
                        st.session_state[f"editing_rec_{best['id']}"] = False
                        st.rerun()

            if st.session_state.get(f"confirm_del_rec_{best['id']}"):
                st.warning(f"Record {label} ({fmt_time(best['time_seconds'])}) verwijderen?")
                dc1, dc2, _ = st.columns([1, 1, 4])
                with dc1:
                    if st.button("Ja, verwijder", key=f"yes_del_rec_{best['id']}", type="primary"):
                        try:
                            delete_record(best["id"])
                            st.session_state[f"confirm_del_rec_{best['id']}"] = False
                            st.success("Verwijderd.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Mislukt: {e}")
                with dc2:
                    if st.button("Annuleer", key=f"no_del_rec_{best['id']}"):
                        st.session_state[f"confirm_del_rec_{best['id']}"] = False
                        st.rerun()

            st.markdown("")

# ============================================================
# TAB 6 — INSTELLINGEN
# ============================================================
with tab_instellingen:
    import re as _re

    st.markdown("#### ⚙️ Persoonlijke parameters")
    st.caption(
        "Worden gebruikt voor TSS-berekening, HR-zone-indeling en de AI-coach. "
        "Pas aan na een lactaattest of op basis van recente resultaten. "
        "Historische zone-data (backfill) opnieuw verwerken om die bij te werken."
    )

    def _fmt_pace_sec(sec: int) -> str:
        return f"{sec // 60}:{sec % 60:02d}"

    # ─── SECTIE 1: LTHR ──────────────────────────────────────
    st.markdown("""
    <div style="background: linear-gradient(135deg, #151b2e, #1a2138);
                border-left: 3px solid #00d4ff; border-radius: 10px;
                padding: 16px 20px; margin: 12px 0 8px 0;">
        <div style="color: #00d4ff; font-size: 0.8rem; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px;">
            🫀 Drempelhartslag (LTHR)
        </div>
        <div style="color: #e8eaed; font-size: 0.88rem; line-height: 1.5;">
            Hartslag op lactaatdrempel — basis voor TSS-berekening en HR-zone-indeling (Friel-methode).
            Vuistregel: hartslag bij ~60 min all-out inspanning, of 95% van max HR.
        </div>
    </div>
    """, unsafe_allow_html=True)

    sc1_a, sc1_b, sc1_c = st.columns([1, 2, 2])
    with sc1_a:
        st.metric("Huidig", f"{settings['lthr']} bpm")
    with sc1_b:
        new_lthr = st.number_input(
            "LTHR (bpm)", min_value=100, max_value=220,
            value=settings["lthr"], step=1, key="input_lthr",
            label_visibility="collapsed",
        )
    with sc1_c:
        if st.button("💾 Opslaan LTHR", key="save_lthr", use_container_width=True):
            save_user_settings(int(new_lthr), settings["threshold_pace_seconds"], settings["max_hr"])
            st.success(f"LTHR opgeslagen: {int(new_lthr)} bpm")
            st.rerun()
        if st.button("🔵 Bereken uit trainingsdata", key="calc_lthr", use_container_width=True,
                     help="Stuurt top-5 zwaarste sessies (90 dgn) naar Claude voor LTHR-schatting"):
            _df_run_all = df[df["type"].isin(["Run", "VirtualRun", "TrailRun"])]
            _cutoff_90 = datetime.now() - timedelta(days=90)
            _df_r90 = _df_run_all[_df_run_all["start_date"] >= _cutoff_90]
            _df_intense = _df_r90[
                _df_r90["avg_heartrate"].notna() &
                (_df_r90["avg_heartrate"] > settings["max_hr"] * 0.75)
            ]
            _top5 = _df_intense.nlargest(5, "avg_heartrate")
            if _top5.empty:
                st.warning("Geen intensieve sessies gevonden (gem. HR > 75% max HR) in de afgelopen 90 dagen.")
            else:
                _lines = []
                for _, _r in _top5.iterrows():
                    _mhr = f"{int(_r['max_heartrate'])}" if pd.notna(_r.get("max_heartrate")) else "?"
                    _lines.append(
                        f"- {_r['start_date'].strftime('%d-%m-%Y')}: {_r['type']} "
                        f"{_r['distance_km']:.1f} km in {int(_r['moving_time_min'])} min, "
                        f"gem. HR {int(_r['avg_heartrate'])} bpm, max HR {_mhr} bpm"
                    )
                with st.spinner("Claude schat LTHR..."):
                    _lthr_text = estimate_lthr_from_activities("\n".join(_lines))
                st.session_state["lthr_proposal"] = _lthr_text

    if "lthr_proposal" in st.session_state:
        st.info(st.session_state["lthr_proposal"])
        _m = _re.search(r'LTHR[:\s]+(\d+)', st.session_state["lthr_proposal"])
        if _m:
            _proposed_lthr = int(_m.group(1))
            if st.button(f"✅ Overnemen: LTHR = {_proposed_lthr} bpm", key="take_lthr"):
                save_user_settings(_proposed_lthr, settings["threshold_pace_seconds"], settings["max_hr"])
                del st.session_state["lthr_proposal"]
                st.success(f"LTHR ingesteld op {_proposed_lthr} bpm")
                st.rerun()

    st.divider()

    # ─── SECTIE 2: THRESHOLD PACE ─────────────────────────────
    st.markdown("""
    <div style="background: linear-gradient(135deg, #151b2e, #1a2138);
                border-left: 3px solid #00d4ff; border-radius: 10px;
                padding: 16px 20px; margin: 0 0 8px 0;">
        <div style="color: #00d4ff; font-size: 0.8rem; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px;">
            ⚡ Threshold pace
        </div>
        <div style="color: #e8eaed; font-size: 0.88rem; line-height: 1.5;">
            Drempelpace per km — basis voor pace-zone-indeling in de Zones-tab.
            Vuistregel: 10K-PR-pace + 5 sec/km.
        </div>
    </div>
    """, unsafe_allow_html=True)

    sc2_a, sc2_b, sc2_c = st.columns([1, 2, 2])
    with sc2_a:
        st.metric("Huidig", f"{_fmt_pace_sec(settings['threshold_pace_seconds'])}/km")
    with sc2_b:
        _tp_m_cur = settings["threshold_pace_seconds"] // 60
        _tp_s_cur = settings["threshold_pace_seconds"] % 60
        _tp_col1, _tp_col2 = st.columns(2)
        with _tp_col1:
            _tp_m = st.number_input("Min", min_value=2, max_value=9, value=_tp_m_cur, key="tp_min")
        with _tp_col2:
            _tp_s = st.number_input("Sec", min_value=0, max_value=59, value=_tp_s_cur, key="tp_sec")
        _new_tp_sec = _tp_m * 60 + _tp_s
    with sc2_c:
        if st.button("💾 Opslaan pace", key="save_tp", use_container_width=True):
            save_user_settings(settings["lthr"], int(_new_tp_sec), settings["max_hr"])
            st.success(f"Threshold pace opgeslagen: {_fmt_pace_sec(int(_new_tp_sec))}/km")
            st.rerun()
        if st.button("🔵 Bereken uit 10K-PR", key="calc_tp", use_container_width=True,
                     help="Berekent threshold pace op basis van je 10K-PR (10K-pace + 5 sec/km)"):
            _records_all = get_all_records()
            _pr_10k = next(
                (r for r in _records_all if abs(float(r["distance_km"]) - 10.0) < 0.1),
                None,
            )
            if not _pr_10k:
                st.warning("Geen 10K-PR gevonden in de Records-tab.")
            else:
                _pace_10k = _pr_10k["time_seconds"] / float(_pr_10k["distance_km"])
                _proposed_tp = int(_pace_10k) + 5
                _pr_min = _pr_10k["time_seconds"] // 60
                _pr_sec = _pr_10k["time_seconds"] % 60
                st.session_state["tp_proposal"] = {
                    "sec": _proposed_tp,
                    "text": (
                        f"Op basis van je 10K-PR ({_pr_min}:{_pr_sec:02d} min op "
                        f"{_pr_10k['distance_km']} km, pace {_fmt_pace_sec(int(_pace_10k))}/km) "
                        f"is de geschatte threshold pace **{_fmt_pace_sec(_proposed_tp)}/km** "
                        f"(10K-pace + 5 sec/km)."
                    ),
                }

    if "tp_proposal" in st.session_state:
        st.info(st.session_state["tp_proposal"]["text"])
        _p_sec = st.session_state["tp_proposal"]["sec"]
        if st.button(f"✅ Overnemen: {_fmt_pace_sec(_p_sec)}/km", key="take_tp"):
            save_user_settings(settings["lthr"], _p_sec, settings["max_hr"])
            del st.session_state["tp_proposal"]
            st.success(f"Threshold pace ingesteld op {_fmt_pace_sec(_p_sec)}/km")
            st.rerun()

    st.divider()

    # ─── SECTIE 3: MAX HR ─────────────────────────────────────
    st.markdown("""
    <div style="background: linear-gradient(135deg, #151b2e, #1a2138);
                border-left: 3px solid #00d4ff; border-radius: 10px;
                padding: 16px 20px; margin: 0 0 8px 0;">
        <div style="color: #00d4ff; font-size: 0.8rem; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px;">
            💓 Maximale hartslag (max HR)
        </div>
        <div style="color: #e8eaed; font-size: 0.88rem; line-height: 1.5;">
            Gebruikt als drempel voor 'intensieve sessie'-detectie bij de LTHR-schatting (>75% max HR).
        </div>
    </div>
    """, unsafe_allow_html=True)

    sc3_a, sc3_b, sc3_c = st.columns([1, 2, 2])
    with sc3_a:
        st.metric("Huidig", f"{settings['max_hr']} bpm")
    with sc3_b:
        new_max_hr = st.number_input(
            "Max HR (bpm)", min_value=150, max_value=250,
            value=settings["max_hr"], step=1, key="input_max_hr",
            label_visibility="collapsed",
        )
    with sc3_c:
        if st.button("💾 Opslaan max HR", key="save_max_hr", use_container_width=True):
            save_user_settings(settings["lthr"], settings["threshold_pace_seconds"], int(new_max_hr))
            st.success(f"Max HR opgeslagen: {int(new_max_hr)} bpm")
            st.rerun()
        if st.button("🔵 Bereken uit data", key="calc_max_hr", use_container_width=True,
                     help="Zoekt de hoogste hartslag in activiteiten van het afgelopen jaar"):
            _cutoff_yr = datetime.now() - timedelta(days=365)
            _df_yr = df[df["start_date"] >= _cutoff_yr]
            _max_from_max = _df_yr["max_heartrate"].max() if "max_heartrate" in _df_yr.columns else None
            _max_from_avg = _df_yr["avg_heartrate"].max()
            _hr_found = max(
                int(_max_from_max) if pd.notna(_max_from_max) else 0,
                int(_max_from_avg) if pd.notna(_max_from_avg) else 0,
            )
            if _hr_found < 150:
                st.warning("Geen bruikbare HR-data gevonden in het afgelopen jaar.")
            else:
                st.session_state["max_hr_proposal"] = _hr_found

    if "max_hr_proposal" in st.session_state:
        _hr_p = st.session_state["max_hr_proposal"]
        st.info(f"Hoogste hartslag gezien in het afgelopen jaar: **{_hr_p} bpm**. Overnemen als max HR?")
        if st.button(f"✅ Overnemen: max HR = {_hr_p} bpm", key="take_max_hr"):
            save_user_settings(settings["lthr"], settings["threshold_pace_seconds"], _hr_p)
            del st.session_state["max_hr_proposal"]
            st.success(f"Max HR ingesteld op {_hr_p} bpm")
            st.rerun()

# ============================================================
# TAB 7 — AI-COACH (levend weekschema)
# ============================================================
with tab_coach:
    st.markdown("#### Je AI-coach")
    st.caption(
        "De coach maakt een weekschema. Na elke training koppel je terug hoe het "
        "ging — de coach past het resterende schema daarop aan."
    )

    if not race:
        st.warning("Geen actief race-doel gevonden.")
        st.stop()

    # === Profiel-notitieboek (uitklapbaar) ===
    profile = get_user_profile()
    has_profile = any([
        profile.get("about_me", "").strip(),
        profile.get("injuries", "").strip(),
        profile.get("preferences", "").strip(),
    ])
    profile_label = "📝 Mijn profiel (de coach gebruikt dit)" if has_profile else "📝 Mijn profiel — nog niet ingevuld (klap open)"

    with st.expander(profile_label, expanded=False):
        st.caption("Vul hier je achtergrond in. De coach gebruikt dit elke keer als context.")
        with st.form("user_profile_form"):
            about_me = st.text_area(
                "Over mij als loper", value=profile.get("about_me", ""), height=100,
            )
            injuries = st.text_area(
                "Blessure-historie & aandachtspunten", value=profile.get("injuries", ""), height=100,
            )
            preferences = st.text_area(
                "Voorkeuren & praktische context", value=profile.get("preferences", ""), height=100,
            )
            saved = st.form_submit_button("💾 Profiel opslaan", type="primary", use_container_width=True)
            if saved:
                try:
                    save_user_profile(about_me.strip(), injuries.strip(), preferences.strip())
                    st.success("Profiel opgeslagen.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Opslaan mislukt: {e}")

    st.divider()

    active = get_active_schedule()

    # === GEEN actief schema: nieuw schema maken ===
    if not active:
        st.info("Er is nog geen actief weekschema. Maak er hieronder een.")

        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("**Hoe voel je je deze week?**")
            new_feeling = st.text_area(
                "feeling_new",
                placeholder="bv. 'fris en gemotiveerd', 'drukke werkweek'",
                height=90, label_visibility="collapsed", key="feeling_new",
            )
        with col_r:
            st.markdown("**Wat wil/kan je vandaag nog doen?**")
            new_today = st.text_area(
                "today_new",
                placeholder="bv. 'vandaag rustdag', 'wil nog 8 km'",
                height=90, label_visibility="collapsed", key="today_new",
            )

        if st.button("🗓️ Genereer weekschema", type="primary", use_container_width=True):
            with st.spinner("Coach maakt je weekschema..."):
                try:
                    schedule_text = generate_schedule(
                        df, df_filtered, race, new_feeling, new_today,
                    )
                    today = datetime.now().date()
                    week_start = today - timedelta(days=today.weekday())
                    create_schedule(week_start, schedule_text)
                    st.success("Weekschema aangemaakt!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Mislukt: {e}")

    # === WEL actief schema: tonen + terugkoppelen ===
    else:
        ws = active["week_start"]
        st.markdown(f"##### 🗓️ Actief weekschema — week van {ws.strftime('%d-%m-%Y')}")
        st.markdown(
            '<div style="background: #151b2e; border-left: 3px solid #00ff9d;'
            'border-radius: 8px; padding: 16px 20px; margin-bottom: 12px;">',
            unsafe_allow_html=True,
        )
        st.markdown(active["schedule_text"])
        st.markdown("</div>", unsafe_allow_html=True)

        if active.get("update_log", "").strip():
            with st.expander("🔧 Aanpassingen deze week"):
                st.markdown(active["update_log"])

        st.divider()

        st.markdown("**Hoe ging je laatste training?**")
        st.caption(
            "Vertel hoe het ging. De coach kijkt naar het schema en je verse "
            "loopdata, en past de rest van de week zo nodig aan."
        )
        feedback = st.text_area(
            "schedule_feedback",
            placeholder="bv. 'Intervaltraining ging goed maar laatste 2 waren zwaar' "
                        "of 'duurloop overgeslagen, weinig tijd'",
            height=100, label_visibility="collapsed", key="schedule_feedback",
        )

        col_a, col_b = st.columns([3, 1])
        with col_a:
            if st.button("🔄 Werk schema bij", type="primary", use_container_width=True):
                if not feedback.strip():
                    st.warning("Vul eerst je terugkoppeling in.")
                else:
                    with st.spinner("Coach past je schema aan..."):
                        try:
                            new_text = update_schedule_with_feedback(
                                df, df_filtered, race,
                                active["schedule_text"], feedback,
                            )
                            stamp = datetime.now().strftime("%d-%m %H:%M")
                            log_entry = f"\n\n**{stamp}** — terugkoppeling: _{feedback.strip()}_"
                            update_schedule(active["id"], new_text, log_entry)
                            st.success("Schema bijgewerkt!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Mislukt: {e}")
        with col_b:
            if st.button("✅ Week afsluiten", use_container_width=True):
                try:
                    archive_active_schedule()
                    st.success("Week afgesloten. Maak een nieuw schema.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Mislukt: {e}")

    # === Historie ===
    history = get_schedule_history(limit=10)
    if history:
        st.divider()
        with st.expander(f"📜 Eerdere weekschema's ({len(history)})"):
            for h in history:
                st.markdown(f"**Week van {h['week_start'].strftime('%d-%m-%Y')}**")
                st.markdown(h["schedule_text"])
                if h.get("update_log", "").strip():
                    st.caption("Aanpassingen:")
                    st.markdown(h["update_log"])
                st.divider()
