"""AI-coach: gebruikt Claude om wekelijks trainingsadvies te genereren."""
import streamlit as st
import pandas as pd
from anthropic import Anthropic
from datetime import datetime, timedelta
from metrics import add_tss_column, get_current_metrics

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

**Belangrijk over de planning:**
- Plan ALTIJD vanaf de dag NA vandaag, voor 7 dagen vooruit.
- Neem de activiteiten van de afgelopen dagen serieus mee. Als hij gisteren al gefietst heeft, plan je dat niet opnieuw.
- Cross-training (fietsen, wandelen) telt mee als belasting/herstel — benoem dat ook.
- Houd rekening met wat hij zelf aangeeft over hoe hij zich voelt.

Je adviezen zijn altijd:
- **Concreet:** dag voor dag, met afstand/duur en intensiteit
- **Geprioriteerd:** wat is de belangrijkste sessie deze week, wat is optioneel
- **Toegelicht:** waarom deze opbouw, wat is het doel
- **Voorzichtig in opbouw:** maximaal ~10% volume-toename per week, geen plotselinge sprongen

Bij intensiteiten gebruik je waar mogelijk:
- **Z1/Z2:** rustig, kunnen praten in volzinnen
- **Z3:** tempo-rondje, half-praten
- **Z4 / drempel:** comfortabel-hard, paar woorden tegelijk
- **Z5 / VO2max:** all-out intervallen
- **MP / HMP / 10K-pace:** specifieke wedstrijdpace

Format van je antwoord:
1. **Korte beoordeling** (3-5 zinnen): waar staat hij, hoe ligt hij op schema?
2. **Focus deze week:** wat is het hoofddoel
3. **Weekschema:** dag voor dag, beginnend bij de dag NA vandaag, 7 dagen vooruit. Schrijf de datum erbij (bv. 'donderdag 30 april').
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


def _build_user_message(df_all: pd.DataFrame, df_run: pd.DataFrame, race: dict, user_feeling: str) -> str:
    """Bouw de gebruikersboodschap met alle context."""
    df_all_tss = add_tss_column(df_all)
    df_run_tss = add_tss_column(df_run)
    metrics = get_current_metrics(df_run)  # CTL/ATL/TSB op basis van Run
    recent_str = _format_recent_activities(df_all_tss, days=14)

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
**Race-doel:**
- {race['name']}
- Datum: {datum_nl(race['race_date'])} (over {days_to_race} dagen / {weeks_to_race:.1f} weken)
- Afstand: {race['distance_km']} km
- Streeftijd: {target_min}:{target_sec:02d} (pace {tp_min}:{tp_s:02d}/km)
- Notities: {race.get('notes', '')}
"""

    feeling_str = f"\n**Hoe ik me voel deze week:**\n{user_feeling}\n" if user_feeling.strip() else ""

    return f"""**Vandaag is {datum_nl(today)}.**
Plan vanaf morgen voor 7 dagen vooruit.
{race_str}
**Huidige trainingsbelasting (alleen op basis van hardlopen):**
- Fitness (CTL, 42-daags): {metrics['ctl']:.0f}
- Vermoeidheid (ATL, 7-daags): {metrics['atl']:.0f}
- Form (TSB): {metrics['tsb']:+.0f} ({metrics['label']})

**Volume hardlopen per week, laatste 12 weken (km):**
{weekly_summary}

**Alle activiteiten afgelopen 14 dagen (hardlopen + fiets + andere):**
{recent_str}
{feeling_str}
**Vraag:** Geef advies voor de komende 7 dagen. Houd rekening met wat ik recent heb gedaan (incl. fiets), mijn herstel na de marathon en mijn voorkeur om blessurevrij te blijven."""


def generate_weekly_advice(df_all: pd.DataFrame, df_run: pd.DataFrame, race: dict, user_feeling: str = "") -> str:
    """Vraag Claude om weekadvies op basis van de data."""
    api_key = st.secrets["ANTHROPIC_API_KEY"]
    client = Anthropic(api_key=api_key)

    user_msg = _build_user_message(df_all, df_run, race, user_feeling)

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    return response.content[0].text


def continue_conversation(history: list[dict], df_all: pd.DataFrame, df_run: pd.DataFrame,
                           race: dict, user_message: str) -> str:
    """Voer een vervolgvraag uit op het advies."""
    api_key = st.secrets["ANTHROPIC_API_KEY"]
    client = Anthropic(api_key=api_key)

    # Eerste bericht is de oorspronkelijke context
    if not history:
        history = [{"role": "user", "content": _build_user_message(df_all, df_run, race, "")}]

    messages = history + [{"role": "user", "content": user_message}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return response.content[0].text
