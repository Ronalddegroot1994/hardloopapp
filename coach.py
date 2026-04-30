"""AI-coach: gebruikt Claude om wekelijks trainingsadvies te genereren."""
import streamlit as st
import pandas as pd
from anthropic import Anthropic
from datetime import datetime, timedelta, date
from metrics import add_tss_column, get_current_metrics
from streams import get_zones_for_activities
   from database import get_upcoming_races

MODEL = "claude-sonnet-4-5"

DAGEN_NL = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN_NL = ["januari", "februari", "maart", "april", "mei", "juni",
              "juli", "augustus", "september", "oktober", "november", "december"]


def datum_nl(d) -> str:
    """Formatteer datum als 'woensdag 29 april 2026'."""
    if isinstance(d, datetime):
        d = d.date()
    return f"{DAGEN_NL[d.weekday()]} {d.day} {MAANDEN_NL[d.month - 1]} {d.year}"


SYSTEM_PROMPT = """Je bent een ervaren, nuchtere Nederlandse hardlooptrainer met decennia ervaring in het begeleiden van amateur- en sub-elitelopers. Je communiceert direct, vriendelijk en concreet — geen wollige theorie, geen slogans.

Je primaire focus voor deze loper:
1. **Blessurepreventie boven prestatie.** Hij heeft eerder na marathons blessures gehad. Hij wil dit voorkomen, ook als dat betekent dat hij iets minder snel naar zijn doel toe werkt.
2. **Realistisch en uitvoerbaar advies.** Geen plannen die in theorie mooi zijn maar in een drukke werkweek niet vol te houden.
3. **Eerlijkheid over haalbaarheid.** Als zijn doel niet realistisch lijkt, zeg dat. Als hij goed op koers ligt, zeg dat ook.

**Hoe je plant:**
- Gebruik de feiten zoals ze hieronder worden meegegeven. Niet zelf gaan rekenen of interpreteren.
- Maak een plan vanaf VANDAAG t/m de zondag van volgende week.
- Als hij vandaag al heeft getraind, neem dat mee.
- Cross-training (fietsen, wandelen) telt mee als belasting/herstel.

**Hoe je zone-data leest:**
- Friel-zones gebaseerd op LTHR=170: Z1 (<144 bpm) = herstel, Z2 (144-152) = aerobe basis, Z3 (153-161) = tempo, Z4 (162-170) = drempel, Z5 (>170) = VO2max.
- Voor 10K-prep is een goede mix: ~60-70% Z1+Z2, 10-15% Z3, 15-20% Z4-Z5.
- Voor marathon-prep was: ~80% Z1+Z2, 5-10% Z3, 10-15% Z4-Z5.
- Veel Z1 (>50%) en weinig Z2 betekent: rustige loopjes zijn TE rustig — waarschijnlijk goed voor recovery, niet voor training-stimulus.
- Veel Z3 (>25%) is "grijze zone" — vermoeiend zonder veel snelheidswinst.
- Gebruik de zone-data om concreet advies te geven: bv. "deze week minder Z1, meer Z3-Z4".

Je adviezen zijn altijd:
- **Concreet:** dag voor dag, met afstand/duur en intensiteit (in HR-zones of pace)
- **Geprioriteerd:** wat is de belangrijkste sessie deze week
- **Toegelicht:** waarom deze opbouw, wat is het doel
- **Voorzichtig in opbouw:** maximaal ~10% volume-toename per week

Bij intensiteiten gebruik je waar mogelijk:
- **Z1/Z2:** rustig, kunnen praten in volzinnen (HR <152)
- **Z3:** tempo-rondje, half-praten (HR 153-161)
- **Z4 / drempel:** comfortabel-hard, paar woorden tegelijk (HR 162-170)
- **Z5 / VO2max:** all-out intervallen (HR >170)
- **MP / HMP / 10K-pace:** specifieke wedstrijdpace

Format van je antwoord:
1. **Korte beoordeling** (3-5 zinnen): waar staat hij, hoe ligt hij op schema? Verwijs naar de zone-verdeling als die opvalt.
2. **Focus deze periode:** wat is het hoofddoel
3. **Schema:** dag voor dag, vanaf vandaag t/m zondag van volgende week. Schrijf de datum erbij.
4. **Aandachtspunten:** wat letten we op, wanneer aanpassen
5. **Vraag terug:** stel 1 vraag waarvan jij denkt dat het belangrijk is om te weten voor volgend advies

Toon: zoals een ervaren trainer-vriend tegen een serieuze amateur. Geen formaliteiten."""


def _format_recent_activities(df: pd.DataFrame, days: int = 14) -> str:
    """Maak een leesbare lijst van recente activiteiten — alle sporten."""
    cutoff = datetime.now() - timedelta(days=days)
    recent = df[df["start_date"] >= cutoff].copy()
    recent = recent.sort_values("start_date", ascending=True)

    if recent.empty:
        return "Geen activiteiten in de afgelopen periode."

    lines = []
    for _, row in recent.iterrows():
        d = row["start_date"]
        date_str = f"{DAGEN_NL[d.weekday()]} {d.day:02d}-{d.month:02d}"
        sport = row.get("type", "?")
        name = row.get("name", "")
        km = row.get("distance_km", 0)
        min_total = row.get("moving_time_min", 0)
        pace = row.get("avg_pace_min_per_km")
        hr = row.get("avg_heartrate")
        tss = row.get("tss", 0)

        pace_str = ""
        if pace and not pd.isna(pace) and sport in ("Run", "VirtualRun", "TrailRun"):
            p_min = int(pace)
            p_sec = round((pace - p_min) * 60)
            pace_str = f", {p_min}:{p_sec:02d}/km"

        hr_str = f", HR {int(hr)}" if hr and not pd.isna(hr) else ""

        lines.append(
            f"- {date_str}: [{sport}] {name} — {km:.1f} km in {int(min_total)} min{pace_str}{hr_str}, TSS {tss:.0f}"
        )

    return "\n".join(lines)


def _aggregate_zones(df_run: pd.DataFrame, days: int) -> dict:
    """Aggregeer zone-tijden voor de laatste N dagen."""
    cutoff = datetime.now() - timedelta(days=days)
    recent = df_run[df_run["start_date"] >= cutoff]
    if recent.empty:
        return {"total_min": 0, "z1_pct": 0, "z2_pct": 0, "z3_pct": 0, "z4_pct": 0, "z5_pct": 0}

    strava_ids = recent["strava_id"].tolist()
    zones = get_zones_for_activities(strava_ids)
    if not zones:
        return {"total_min": 0, "z1_pct": 0, "z2_pct": 0, "z3_pct": 0, "z4_pct": 0, "z5_pct": 0}

    totals = {z: 0 for z in ["z1", "z2", "z3", "z4", "z5"]}
    for sid, z in zones.items():
        if z.get("has_streams"):
            for zn in totals:
                totals[zn] += z.get(f"hr_{zn}_sec") or 0

    total_sec = sum(totals.values())
    if total_sec == 0:
        return {"total_min": 0, "z1_pct": 0, "z2_pct": 0, "z3_pct": 0, "z4_pct": 0, "z5_pct": 0}

    return {
        "total_min": total_sec / 60,
        "z1_pct": totals["z1"] / total_sec * 100,
        "z2_pct": totals["z2"] / total_sec * 100,
        "z3_pct": totals["z3"] / total_sec * 100,
        "z4_pct": totals["z4"] / total_sec * 100,
        "z5_pct": totals["z5"] / total_sec * 100,
    }


def _summarize_facts(df_run: pd.DataFrame, df_all: pd.DataFrame) -> str:
    """Maak een feitenblok zodat de coach niet zelf hoeft te interpreteren."""
    today = datetime.now().date()
    today_dt = pd.Timestamp(today)

    cutoff_7 = today_dt - pd.Timedelta(days=7)
    runs_7 = df_run[df_run["start_date"] >= cutoff_7]
    km_7 = runs_7["distance_km"].sum()

    cutoff_14 = today_dt - pd.Timedelta(days=14)
    runs_14 = df_run[df_run["start_date"] >= cutoff_14]
    km_14 = runs_14["distance_km"].sum()

    today_acts = df_all[df_all["start_date"].dt.date == today]
    today_str = "Geen activiteiten vandaag (op moment van advies)."
    if not today_acts.empty:
        parts = []
        for _, r in today_acts.iterrows():
            parts.append(f"{r['type']} {r['distance_km']:.1f} km in {int(r['moving_time_min'])} min")
        today_str = "Vandaag al gedaan: " + " + ".join(parts)

    last_run_str = "Geen recente loopactiviteit."
    if not df_run.empty:
        last_run = df_run.sort_values("start_date", ascending=False).iloc[0]
        days_ago = (today_dt - last_run["start_date"].normalize()).days
        last_run_str = (
            f"Laatste loop: {DAGEN_NL[last_run['start_date'].weekday()]} "
            f"{last_run['start_date'].day:02d}-{last_run['start_date'].month:02d} "
            f"({days_ago} dagen geleden), {last_run['distance_km']:.1f} km."
        )

    weeks_summary = []
    for w in range(0, 4):
        ws = today_dt - pd.Timedelta(days=today_dt.weekday() + 7 * w)
        we = ws + pd.Timedelta(days=7)
        in_week = df_run[(df_run["start_date"] >= ws) & (df_run["start_date"] < we)]
        label = "deze week" if w == 0 else (
            "vorige week" if w == 1 else f"{w} weken geleden"
        )
        weeks_summary.append(
            f"  - {label}: {len(in_week)} loopjes, {in_week['distance_km'].sum():.1f} km"
        )
    weeks_str = "\n".join(weeks_summary)

    zones_7 = _aggregate_zones(df_run, 7)
    zones_28 = _aggregate_zones(df_run, 28)

    if zones_7["total_min"] > 0:
        zones_7_str = (
            f"  - Laatste 7 dagen ({zones_7['total_min']:.0f} min totaal): "
            f"Z1 {zones_7['z1_pct']:.0f}% / Z2 {zones_7['z2_pct']:.0f}% / "
            f"Z3 {zones_7['z3_pct']:.0f}% / Z4 {zones_7['z4_pct']:.0f}% / Z5 {zones_7['z5_pct']:.0f}%"
        )
    else:
        zones_7_str = "  - Laatste 7 dagen: geen zone-data."

    if zones_28["total_min"] > 0:
        zones_28_str = (
            f"  - Laatste 28 dagen ({zones_28['total_min']:.0f} min totaal): "
            f"Z1 {zones_28['z1_pct']:.0f}% / Z2 {zones_28['z2_pct']:.0f}% / "
            f"Z3 {zones_28['z3_pct']:.0f}% / Z4 {zones_28['z4_pct']:.0f}% / Z5 {zones_28['z5_pct']:.0f}%"
        )
    else:
        zones_28_str = "  - Laatste 28 dagen: geen zone-data."

    return f"""**FEITEN (gebruik deze, ga niet zelf interpreteren):**
- {today_str}
- {last_run_str}
- Hardlopen laatste 7 dagen: {len(runs_7)} loopjes, {km_7:.1f} km totaal.
- Hardlopen laatste 14 dagen: {len(runs_14)} loopjes, {km_14:.1f} km totaal.
- Hardlopen per week (4 weken):
{weeks_str}
- HR-zone verdeling:
{zones_7_str}
{zones_28_str}"""


def _build_user_message(df_all: pd.DataFrame, df_run: pd.DataFrame, race: dict,
                        user_feeling: str, today_status: str) -> str:
    """Bouw de gebruikersboodschap met alle context."""
    df_all_tss = add_tss_column(df_all)
    df_run_tss = add_tss_column(df_run)
    metrics = get_current_metrics(df_run)
    recent_str = _format_recent_activities(df_all_tss, days=14)
    facts = _summarize_facts(df_run, df_all)

    today = datetime.now().date()
    days_to_race = (race["race_date"] - today).days if race else None
    weeks_to_race = days_to_race / 7 if days_to_race is not None else None

    cutoff_90 = datetime.now() - timedelta(days=90)
    last_90 = df_run_tss[df_run_tss["start_date"] >= cutoff_90].copy()
    last_90["week"] = last_90["start_date"].dt.to_period("W")
    weekly_km = last_90.groupby("week")["distance_km"].sum().round(1).tolist()
    weekly_summary = ", ".join(str(k) for k in weekly_km[-12:])

    race_str = ""
    if race:
        target_min = race["target_time_seconds"] // 60
        target_sec = race["target_time_seconds"] % 60
        target_pace = race["target_time_seconds"] / race["distance_km"]
        tp_min = int(target_pace // 60)
        tp_s = int(target_pace % 60)
        race_str = f"""
**Hoofddoel (A-race):**
- {race['name']}
- Datum: {datum_nl(race['race_date'])} (over {days_to_race} dagen / {weeks_to_race:.1f} weken)
- Afstand: {race['distance_km']} km
- Streeftijd: {target_min}:{target_sec:02d} (pace {tp_min}:{tp_s:02d}/km)
- Notities: {race.get('notes', '')}
"""

        # Andere komende races als context
        upcoming = get_upcoming_races()
        other_races = [r for r in upcoming if r["id"] != race.get("id")]
        if other_races:
            type_emoji = {"A": "🎯", "B": "🧪", "C": "🤝"}
            type_uitleg = {
                "A": "hoofddoel",
                "B": "test-race (redelijk hard, niet all-out)",
                "C": "plezier-race / hazen (geen prestatiedruk)",
            }
            lines = []
            for r in other_races:
                days = (r["race_date"] - datetime.now().date()).days
                emo = type_emoji.get(r["race_type"], "🏃")
                uitl = type_uitleg.get(r["race_type"], "")
                extra_info = ""
                if r.get("target_time_seconds"):
                    tm = r["target_time_seconds"] // 60
                    ts = r["target_time_seconds"] % 60
                    tpace = r["target_time_seconds"] / r["distance_km"]
                    tpm = int(tpace // 60)
                    tps = int(tpace % 60)
                    extra_info = f", doel {tm}:{ts:02d} ({tpm}:{tps:02d}/km)"
                note = f" — {r['notes']}" if r.get("notes") else ""
                lines.append(
                    f"- {emo} **{r['name']}** ({r['race_type']}-race, {uitl}): "
                    f"{datum_nl(r['race_date'])} (over {days} dgn), "
                    f"{r['distance_km']} km{extra_info}{note}"
                )
            race_str += "\n**Andere geplande races (context):**\n" + "\n".join(lines) + "\n"
            race_str += "\n*Belangrijk: B/C-races zijn geen volledige race — niet taperen, beschouwen als kwaliteitssessie of relaxte run.*\n"

    today_str_block = ""
    if today_status.strip():
        today_str_block = f"\n**Wat ik vandaag wil/kan doen:**\n{today_status.strip()}\n"

    feeling_str = ""
    if user_feeling.strip():
        feeling_str = f"\n**Hoe ik me deze week voel:**\n{user_feeling.strip()}\n"

    return f"""**Vandaag is {datum_nl(today)}.**
Maak een plan vanaf vandaag t/m zondag van volgende week.
{race_str}
{facts}

**Trainingsbelasting (op basis van hardlopen):**
- Fitness (CTL, 42-daags): {metrics['ctl']:.0f}
- Vermoeidheid (ATL, 7-daags): {metrics['atl']:.0f}
- Form (TSB): {metrics['tsb']:+.0f} ({metrics['label']})

**Volume hardlopen per week, laatste 12 weken (km):**
{weekly_summary}

**Alle activiteiten afgelopen 14 dagen (incl. fiets, wandel):**
{recent_str}
{today_str_block}{feeling_str}
**Vraag:** Geef een schema vanaf vandaag t/m zondag van volgende week. Houd rekening met wat ik recent heb gedaan, mijn herstel na de marathon en mijn voorkeur om blessurevrij te blijven."""
