"""Custom CSS injectie voor donker neon-thema."""
import streamlit as st


CUSTOM_CSS = """
<style>
/* === Algemeen === */
.main .block-container {
    padding-top: 1.5rem;
    padding-bottom: 4rem;
    max-width: 1200px;
}

/* === Titel === */
h1 {
    color: #e8eaed !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
    background: linear-gradient(90deg, #00ff9d 0%, #00d4ff 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
h2, h3 {
    color: #e8eaed !important;
    font-weight: 600 !important;
}

/* === KPI metric kaarten === */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #151b2e 0%, #1a2138 100%);
    border: 1px solid #2a3148;
    border-radius: 12px;
    padding: 16px 18px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    transition: border-color 0.2s;
}
[data-testid="stMetric"]:hover {
    border-color: #00ff9d;
}
[data-testid="stMetricLabel"] {
    color: #8a92a6 !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricValue"] {
    color: #00ff9d !important;
    font-size: 1.8rem !important;
    font-weight: 700 !important;
}

/* === Hero banner voor race === */
.race-hero {
    background: linear-gradient(135deg, #1a2138 0%, #0d1525 100%);
    border: 1px solid #2a3148;
    border-left: 4px solid #00ff9d;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 24px;
    box-shadow: 0 4px 16px rgba(0, 255, 157, 0.08);
}
.race-hero-title {
    color: #00ff9d;
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 6px;
}
.race-hero-name {
    color: #e8eaed;
    font-size: 1.6rem;
    font-weight: 700;
    margin-bottom: 12px;
}
.race-hero-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 16px;
}
.race-hero-cell {
    display: flex;
    flex-direction: column;
}
.race-hero-cell-label {
    color: #8a92a6;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
}
.race-hero-cell-value {
    color: #e8eaed;
    font-size: 1.25rem;
    font-weight: 600;
}
.race-hero-note {
    color: #8a92a6;
    font-size: 0.8rem;
    margin-top: 12px;
    font-style: italic;
}

/* === Status badge === */
.status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 600;
    margin-left: 8px;
}
.status-fris { background: #00ff9d22; color: #00ff9d; border: 1px solid #00ff9d44; }
.status-neutraal { background: #00d4ff22; color: #00d4ff; border: 1px solid #00d4ff44; }
.status-belast { background: #ff8c4222; color: #ff8c42; border: 1px solid #ff8c4244; }
.status-risico { background: #ff4d6d22; color: #ff4d6d; border: 1px solid #ff4d6d44; }

/* === Tabs === */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: transparent;
    border-bottom: 1px solid #2a3148;
}
.stTabs [data-baseweb="tab"] {
    background: transparent;
    color: #8a92a6;
    border-radius: 8px 8px 0 0;
    padding: 10px 18px;
    font-weight: 500;
}
.stTabs [aria-selected="true"] {
    color: #00ff9d !important;
    border-bottom: 2px solid #00ff9d !important;
}

/* === Knoppen === */
.stButton > button {
    border-radius: 8px;
    font-weight: 600;
    transition: transform 0.1s;
}
.stButton > button:hover {
    transform: translateY(-1px);
}

/* === Tabellen === */
[data-testid="stDataFrame"] {
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #2a3148;
}

/* === Sidebar === */
[data-testid="stSidebar"] {
    background: #0d1525;
    border-right: 1px solid #2a3148;
}

/* === Info / Caption === */
.stAlert {
    border-radius: 8px;
    border-left: 3px solid #00d4ff;
    background: #00d4ff11 !important;
}

/* === Mobile responsive === */
@media (max-width: 640px) {
    .main .block-container {
        padding-top: 1rem;
        padding-left: 0.75rem;
        padding-right: 0.75rem;
    }
    h1 {
        font-size: 1.5rem !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.4rem !important;
    }
    .race-hero {
        padding: 16px;
    }
    .race-hero-name {
        font-size: 1.3rem;
    }
}
</style>
"""


def apply_style():
    """Injecteer custom CSS in de Streamlit-pagina."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def race_hero_banner(name: str, date_str: str, days_to_go: str,
                     target_time: str, target_pace: str, note: str = ""):
    """Render een hero-banner voor het race-doel."""
    note_html = f'<div class="race-hero-note">{note}</div>' if note else ""
    html = f"""
    <div class="race-hero">
        <div class="race-hero-title">🎯 Volgende race</div>
        <div class="race-hero-name">{name}</div>
        <div class="race-hero-grid">
            <div class="race-hero-cell">
                <div class="race-hero-cell-label">Datum</div>
                <div class="race-hero-cell-value">{date_str}</div>
            </div>
            <div class="race-hero-cell">
                <div class="race-hero-cell-label">Nog te gaan</div>
                <div class="race-hero-cell-value">{days_to_go}</div>
            </div>
            <div class="race-hero-cell">
                <div class="race-hero-cell-label">Streeftijd</div>
                <div class="race-hero-cell-value">{target_time}</div>
            </div>
            <div class="race-hero-cell">
                <div class="race-hero-cell-label">Doelpace</div>
                <div class="race-hero-cell-value">{target_pace}</div>
            </div>
        </div>
        {note_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def status_badge(label: str) -> str:
    """Geef een gekleurde HTML-badge voor de TSB status."""
    label_lower = label.lower()
    if "fris" in label_lower:
        css_class = "status-fris"
    elif "neutraal" in label_lower:
        css_class = "status-neutraal"
    elif "belast" in label_lower or "productief" in label_lower:
        css_class = "status-belast"
    elif "risico" in label_lower:
        css_class = "status-risico"
    else:
        css_class = "status-neutraal"
    return f'<span class="status-badge {css_class}">{label}</span>'
