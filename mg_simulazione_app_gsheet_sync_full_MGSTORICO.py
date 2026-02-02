
import json
from datetime import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="MG Simulazioni (Sync Google Sheet)", layout="wide")

LEAGUES = [
    "Serie A","Serie B","Premier League","Bundesliga","Liga","Ligue 1",
    "Eredivisie","Primeira Liga (Portogallo)","Altro",
]
OUTCOMES = ["In attesa","Vinta","Persa"]

REQUIRED_COLUMNS = ["ID","Data","Campionato","Partita","Mercato","Quota","Esito","Note"]

# Default tab name (can be overridden by secrets WORKSHEET_NAME)
DEFAULT_WORKSHEET_NAME = "MG STORICO"

# ----------------- Google Sheet -----------------
def _get_creds_info():
    if "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
        raw = st.secrets["GCP_SERVICE_ACCOUNT_JSON"]
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    if "gcp_service_account" in st.secrets:
        return dict(st.secrets["gcp_service_account"])
    raise RuntimeError("Mancano credenziali Google nei Secrets (GCP_SERVICE_ACCOUNT_JSON o [gcp_service_account]).")

@st.cache_resource
def _sheet():
    sheet_id = st.secrets.get("SHEET_ID", "")
    if not sheet_id:
        raise RuntimeError("Manca SHEET_ID nei Secrets.")
    creds_info = _get_creds_info()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)

def _ws(sheet, title: str):
    try:
        return sheet.worksheet(title)
    except Exception:
        # create tab if missing
        return sheet.add_worksheet(title=title, rows=2000, cols=30)

def _ensure_header(ws):
    header = ws.row_values(1)
    if not header:
        ws.update("A1", [REQUIRED_COLUMNS])
        return REQUIRED_COLUMNS
    changed = False
    for c in REQUIRED_COLUMNS:
        if c not in header:
            header.append(c); changed = True
    if changed:
        ws.update("A1", [header])
    return header

def _ensure_ids(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        return df
    df["ID"] = pd.to_numeric(df["ID"], errors="coerce")
    id_num = df["ID"]
    if id_num.notna().sum() and id_num[id_num.notna()].duplicated().any():
        df["ID"] = range(1, len(df)+1)
        return df
    max_id = int(id_num.max()) if id_num.notna().any() else 0
    missing = id_num.isna()
    if missing.any():
        df.loc[missing, "ID"] = list(range(max_id+1, max_id+1+missing.sum()))
    df["ID"] = pd.to_numeric(df["ID"], errors="coerce").astype(int)
    return df

def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    df = df.copy()
    for c in REQUIRED_COLUMNS:
        if c not in df.columns:
            df[c] = ""

    df["Quota"] = pd.to_numeric(df["Quota"], errors="coerce")
    df["Esito"] = df["Esito"].fillna("").replace({"": "In attesa"})
    df.loc[~df["Esito"].isin(OUTCOMES), "Esito"] = "In attesa"

    df["Campionato"] = df["Campionato"].fillna("Altro")
    df.loc[~df["Campionato"].isin(LEAGUES), "Campionato"] = "Altro"

    df["Data"] = df["Data"].fillna("")
    df.loc[df["Data"].astype(str).str.strip().eq(""), "Data"] = datetime.now().strftime("%Y-%m-%d")

    df["Note"] = df["Note"].fillna("")

    df = _ensure_ids(df)
    return df[REQUIRED_COLUMNS].sort_values("ID").reset_index(drop=True)

@st.cache_data(ttl=15)
def load_from_sheet(ws_title: str) -> pd.DataFrame:
    sh = _sheet()
    ws = _ws(sh, ws_title)
    _ensure_header(ws)
    values = ws.get_all_values()
    if not values or len(values) == 1:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    header = values[0]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)
    return _normalize(df)

def write_to_sheet(ws_title: str, df: pd.DataFrame):
    sh = _sheet()
    ws = _ws(sh, ws_title)
    _ensure_header(ws)
    df = _normalize(df)
    values = [REQUIRED_COLUMNS] + df.astype(str).values.tolist()
    ws.clear()
    ws.update("A1", values)
    load_from_sheet.clear()

def profit_unit_stake(odds: float, outcome: str) -> float:
    if pd.isna(odds): return 0.0
    if outcome == "Vinta": return float(odds) - 1.0
    if outcome == "Persa": return -1.0
    return 0.0

# ----------------- UI -----------------
st.title("📊 Simulazione Multigol – Sync Google Sheet")

default_ws = st.secrets.get("WORKSHEET_NAME", DEFAULT_WORKSHEET_NAME)

with st.sidebar:
    st.subheader("Google Sheet")
    st.write("Fonte dati: Google Sheet (sync).")
    ws_title = st.text_input("Nome tab (worksheet)", value=default_ws)
    if st.button("🔄 Aggiorna da Google Sheet"):
        load_from_sheet.clear()
        st.rerun()
    st.caption("Se modifichi il Google Sheet a mano, premi “Aggiorna” per ricaricare qui.")

# Load
try:
    df = load_from_sheet(ws_title)
except Exception as e:
    st.error("Errore collegamento Google Sheet.")
    st.code(str(e))
    st.info("Controlla: 1) SHEET_ID corretto 2) sheet condiviso con client_email del service account 3) secrets private_key con \\n")
    st.stop()

# --- Inserimento
st.subheader("➕ Inserisci nuova simulazione")
with st.form("add_form", clear_on_submit=True):
    c1, c2, c3 = st.columns([1,2,2])
    with c1:
        campionato = st.selectbox("Campionato", LEAGUES)
    with c2:
        partita = st.text_input("Partita (es. Juve - Napoli)")
    with c3:
        mercato = st.text_input("Mercato (es. MG 1-2 Casa)")
    c4, c5, c6 = st.columns([1,1,2])
    with c4:
        quota = st.number_input("Quota", min_value=1.01, step=0.01, value=1.60)
    with c5:
        esito = st.selectbox("Esito", OUTCOMES, index=0)
    with c6:
        note = st.text_input("Note (opzionale)")
    add = st.form_submit_button("Aggiungi")

    if add:
        next_id = 1 if df.empty else int(df["ID"].max()) + 1
        new_row = {
            "ID": next_id,
            "Data": datetime.now().strftime("%Y-%m-%d"),
            "Campionato": campionato,
            "Partita": partita.strip(),
            "Mercato": mercato.strip(),
            "Quota": float(quota),
            "Esito": esito,
            "Note": note.strip(),
        }
        df2 = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        write_to_sheet(ws_title, df2)
        st.success(f"Inserita simulazione con ID {next_id} (salvata su Google Sheet)")
        st.rerun()

# --- Tabella editabile
st.subheader("📋 Storico simulazioni (edit diretto)")
edited = st.data_editor(
    df,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "ID": st.column_config.NumberColumn("ID", help="Progressivo univoco", disabled=True),
        "Quota": st.column_config.NumberColumn("Quota", format="%.2f"),
        "Esito": st.column_config.SelectboxColumn("Esito", options=OUTCOMES),
        "Campionato": st.column_config.SelectboxColumn("Campionato", options=LEAGUES),
    },
)

colA, colB = st.columns([1,3])
with colA:
    if st.button("💾 Salva modifiche su Google Sheet"):
        write_to_sheet(ws_title, edited)
        st.success("Salvato su Google Sheet.")
        st.rerun()
with colB:
    st.caption("Nota: se cambi il foglio a mano, clicca “Aggiorna da Google Sheet”.")

# --- Report
st.subheader("📈 Report")
df_calc = df.copy()
df_calc["Quota"] = pd.to_numeric(df_calc["Quota"], errors="coerce")
df_calc["Profit"] = df_calc.apply(lambda r: profit_unit_stake(r["Quota"], r["Esito"]), axis=1)
df_closed = df_calc[df_calc["Esito"].isin(["Vinta","Persa"])].copy()

tot_closed = len(df_closed)
wins = int((df_closed["Esito"] == "Vinta").sum())
losses = int((df_closed["Esito"] == "Persa").sum())
pending = int((df_calc["Esito"] == "In attesa").sum())

win_rate = (wins / tot_closed * 100) if tot_closed else 0.0
avg_odds_wins = float(df_closed[df_closed["Esito"] == "Vinta"]["Quota"].mean()) if wins else 0.0
profit_total = float(df_closed["Profit"].sum()) if tot_closed else 0.0
roi = (profit_total / tot_closed * 100) if tot_closed else 0.0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Chiuse", tot_closed)
c2.metric("Vinte", wins)
c3.metric("Perse", losses)
c4.metric("Win rate", f"{win_rate:.1f}%")
c5.metric("Quota media vinte", f"{avg_odds_wins:.2f}")
c6.metric("Profit (stake=1)", f"{profit_total:+.2f}")
c7, c8 = st.columns(2)
c7.metric("ROI %", f"{roi:.1f}%")
c8.metric("In attesa", pending)

st.caption("Profit simulato (stake=1): Vinta=quota-1, Persa=-1, In attesa=0.")

st.divider()
st.subheader("Riepilogo per campionato (solo chiuse)")
if tot_closed:
    def qmv(sub: pd.DataFrame) -> float:
        w = sub[sub["Esito"] == "Vinta"]
        return float(w["Quota"].mean()) if len(w) else 0.0
    grp = (
        df_closed.groupby("Campionato", as_index=False)
        .agg(
            giocate=("ID","count"),
            vinte=("Esito", lambda s: int((s=="Vinta").sum())),
            perse=("Esito", lambda s: int((s=="Persa").sum())),
            win_rate=("Esito", lambda s: float((s=="Vinta").mean()*100) if len(s) else 0.0),
            profit=("Profit","sum"),
        )
    )
    grp["quota_media_vinte"] = grp["Campionato"].apply(lambda lg: qmv(df_closed[df_closed["Campionato"]==lg]))
    grp["ROI %"] = grp.apply(lambda r: (r["profit"]/r["giocate"]*100) if r["giocate"] else 0.0, axis=1)
    st.dataframe(
        grp.style.format({"win_rate":"{:.1f}%","quota_media_vinte":"{:.2f}","profit":"{:+.2f}","ROI %":"{:.1f}%"}),
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("Nessuna simulazione chiusa (Vinta/Persa).")
