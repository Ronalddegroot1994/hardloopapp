"""Trainingsbelasting-metrics: TSS, CTL, ATL, TSB."""
import pandas as pd
from datetime import datetime

# Configuratie - aanpasbaar
LTHR = 175  # Drempelhartslag (bpm) - geschat uit marathon-data
CTL_TIMECONSTANT = 42  # dagen
ATL_TIMECONSTANT = 7   # dagen


def calculate_hrTSS(avg_hr: float, duration_min: float, lthr: float = LTHR) -> float:
    """Bereken hrTSS (heart rate based Training Stress Score).
    1 uur op exact LTHR = 100 TSS.
    """
    if not avg_hr or not duration_min or duration_min <= 0:
        return 0.0
    intensity = avg_hr / lthr
    tss = (duration_min / 60) * (intensity ** 2) * 100
    return round(tss, 1)


def add_tss_column(df: pd.DataFrame) -> pd.DataFrame:
    """Voeg een TSS-kolom toe aan een dataframe met activiteiten."""
    df = df.copy()
    df["tss"] = df.apply(
        lambda row: calculate_hrTSS(row.get("avg_heartrate"), row.get("moving_time_min")),
        axis=1,
    )
    return df


def calculate_load_curves(df: pd.DataFrame) -> pd.DataFrame:
    """Bereken CTL, ATL, TSB per dag op basis van TSS-kolom.
    Returns dataframe met index=datum en kolommen daily_tss, ctl, atl, tsb.
    """
    if df.empty or "tss" not in df.columns:
        return pd.DataFrame(columns=["daily_tss", "ctl", "atl", "tsb"])

    df = df.copy()
    df["date"] = pd.to_datetime(df["start_date"]).dt.date
    daily = df.groupby("date")["tss"].sum().reset_index()
    daily["date"] = pd.to_datetime(daily["date"])

    if daily.empty:
        return pd.DataFrame(columns=["daily_tss", "ctl", "atl", "tsb"])

    start = daily["date"].min()
    end = max(daily["date"].max(), pd.Timestamp(datetime.now().date()))
    full_range = pd.date_range(start=start, end=end, freq="D")
    daily = daily.set_index("date").reindex(full_range, fill_value=0)
    daily.index.name = "date"
    daily = daily.rename(columns={"tss": "daily_tss"})

    daily["ctl"] = daily["daily_tss"].ewm(alpha=1 / CTL_TIMECONSTANT, adjust=False).mean()
    daily["atl"] = daily["daily_tss"].ewm(alpha=1 / ATL_TIMECONSTANT, adjust=False).mean()
    daily["tsb"] = daily["ctl"] - daily["atl"]

    return daily.round(1)


def interpret_tsb(tsb: float) -> tuple[str, str]:
    """Korte interpretatie van de huidige TSB."""
    if tsb > 25:
        return ("Zeer fris", "Je bent uitgerust, maar pas op: te lang in deze zone laat je vorm zakken. Tijd om weer wat belasting toe te voegen.")
    if tsb > 5:
        return ("Fris", "Goed moment voor een pieksessie, race of test. Je staat klaar.")
    if tsb > -10:
        return ("Neutraal", "In balans tussen rust en belasting. Prima om door te trainen.")
    if tsb > -20:
        return ("Productief", "Je bouwt op. Vermoeidheid is normaal in een trainingsblok.")
    if tsb > -30:
        return ("Zwaar belast", "Je traint serieus hard. Bewaak je herstel goed.")
    return ("Risico op overtraining", "TSB zeer negatief. Plan rustdagen of een herstelweek in.")


def get_current_metrics(df: pd.DataFrame) -> dict:
    """Geef de huidige (laatste) CTL/ATL/TSB-waarden + interpretatie."""
    df_with_tss = add_tss_column(df)
    curves = calculate_load_curves(df_with_tss)
    if curves.empty:
        return {"ctl": 0.0, "atl": 0.0, "tsb": 0.0, "label": "Geen data", "advies": ""}

    today = pd.Timestamp(datetime.now().date())
    if today in curves.index:
        row = curves.loc[today]
    else:
        row = curves.iloc[-1]

    label, advies = interpret_tsb(float(row["tsb"]))
    return {
        "ctl": float(row["ctl"]),
        "atl": float(row["atl"]),
        "tsb": float(row["tsb"]),
        "label": label,
        "advies": advies,
    }
