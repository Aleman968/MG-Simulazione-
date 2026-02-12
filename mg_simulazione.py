import json
from datetime import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="MG Simulazioni (Singole + Multiple) — Sync Google Sheet", layout="wide")

LEAGUES = [
    "Serie A","Serie B","Premier League","Bundesliga","Liga","Ligue 1",
    "Eredivisie","Primeira Liga (Portogallo)","Altro",
]
OUTCOMES = ["In attesa","Vinta","Persa"]

# ----------------- Columns / Tabs -----------------
REQUIRED_COLUMNS_SINGOLE = ["ID","Data","Campionato","Partita","Mercato","Quota","Esito","Note"]
REQUIRED_COLUMNS_MULTIPLE = ["ID","Data","Multipla","Quota Totale","Stake","Esito","Note"]

DEFAULT_WORKSHEET_NAME_SINGOLE = "MG STORICO"
DEFAULT_WORKSHEET_NAME_MULTIPLE = "MG MULTIPLE"

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

def _ensure_header(ws, required_cols):
    header = ws.row_values(1)
    if not header:
        ws.update("A1", [required_cols])
        return required_cols
    changed = False
    for c in required_cols:
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

def _normalize(df: pd.DataFrame, required_cols, kind: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=required_cols)

    df = df.copy()
    for c in required_cols:
        if c not in df.columns:
            df[c] = ""

    # Common fields
    df["Esito"] = df["Esito"].fillna("").replace({"": "In attesa"})
    df.loc[~df["Esito"].isin(OUTCOMES), "Esito"] = "In attesa"

    df["Data"] = df["Data"].fillna("")
    df.loc[df["Data"].astype(str).str.strip().eq(""), "Data"] = datetime.now().strftime("%Y-%m-%d")

    df["Note"] = df["Note"].fillna("")

    if kind == "singole":
        df["Quota"] = pd.to_numeric(df["Quota"], errors="coerce")
        df["Campionato"] = df["Campionato"].fillna("Altro")
        df.loc[~df["Campionato"].isin(LEAGUES), "Campionato"] = "Altro"
        df["Partita"] = df["Partita"].fillna("")
        df["Mercato"] = df["Mercato"].fillna("")
    elif kind == "multiple":
        df["Quota Totale"] = pd.to_numeric(df["Quota Totale"], errors="coerce")
        df["Stake"] = pd.to_numeric(df["Stake"], errors="coerce").fillna(0.0)
        df["Multipla"] = df["Multipla"].fillna("")
    else:
        raise ValueError("kind must be 'singole' or 'multiple'")

    df = _ensure_ids(df)
    return df[required_cols].sort_values("ID").reset_index(drop=True)

@st.cache_data(ttl=15)
def _load_generic(ws_title: str, kind: str) -> pd.DataFrame:
    sh = _sheet()
    if kind == "singole":
        required_cols = REQUIRED_COLUMNS_SINGOLE
    elif kind == "multiple":
        required_cols = REQUIRED_COLUMNS_MULTIPLE
    else:
        raise ValueError("kind must be 'singole' or 'multiple'")
    ws = _ws(sh, ws_title)
    _ensure_header(ws, required_cols)
    values = ws.get_all_values()
    if not values or len(values) == 1:
        return pd.DataFrame(columns=required_cols)
    header = values[0]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)
    return _normalize(df, required_cols, kind)

def load_singole(ws_title: str) -> pd.DataFrame:
    return _load_generic(ws_title, "singole")

def load_multiple(ws_title: str) -> pd.DataFrame:
    return _load_generic(ws_title, "multiple")

def _write_generic(ws_title: str, df: pd.DataFrame, kind: str):
    sh = _sheet()
    if kind == "singole":
        required_cols = REQUIRED_COLUMNS_SINGOLE
    elif kind == "multiple":
        required_cols = REQUIRED_COLUMNS_MULTIPLE
    else:
        raise ValueError("kind must be 'singole' or 'multiple'")
    ws = _ws(sh, ws_title)
    _ensure_header(ws, required_cols)
    df = _normalize(df, required_cols, kind)
    values = [required_cols] + df.astype(str).values.tolist()
    ws.clear()
    ws.update("A1", values)
    _load_generic.clear()

def write_singole(ws_title: str, df: pd.DataFrame):
    _write_generic(ws_title, df, "singole")

def write_multiple(ws_title: str, df: pd.DataFrame):
    _write_generic(ws_title, df, "multiple")

# ----------------- Profit helpers -----------------
def profit_unit_stake(odds: float, outcome: str) -> float:
    if pd.isna(odds): 
        return 0.0
    if outcome == "Vinta": 
        return float(odds) - 1.0
    if outcome == "Persa": 
        return -1.0
    return 0.0

def profit_with_stake(odds: float, outcome: str, stake: float) -> float:
    if pd.isna(odds) or pd.isna(stake):
        return 0.0
    stake = float(stake)
    if outcome == "Vinta":
        return stake * (float(odds) - 1.0)
    if outcome == "Persa":
        return -stake
    return 0.0

# ----------------- UI -----------------
st.title("📊 Simulazioni Multigol — Singole + Multiple (Sync Google Sheet)")

default_ws_s = st.secrets.get("WORKSHEET_NAME_SINGOLE", DEFAULT_WORKSHEET_NAME_SINGOLE)
default_ws_m = st.secrets.get("WORKSHEET_NAME_MULTIPLE", DEFAULT_WORKSHEET_NAME_MULTIPLE)

with st.sidebar:
    st.subheader("Google Sheet")
    st.write("Fonte dati: Google Sheet (sync).")
    ws_singole = st.text_input("Nome tab SINGOLE (worksheet)", value=default_ws_s)
    ws_multiple = st.text_input("Nome tab MULTIPLE (worksheet)", value=default_ws_m)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔄 Aggiorna (SINGOLE)"):
            _load_generic.clear()
            st.rerun()
    with c2:
        if st.button("🔄 Aggiorna (MULTIPLE)"):
            _load_generic.clear()
            st.rerun()

    st.caption("Se modifichi il Google Sheet a mano, premi “Aggiorna” per ricaricare qui.")

# Load data
try:
    df_s = load_singole(ws_singole)
    df_m = load_multiple(ws_multiple)
except Exception as e:
    st.error("Errore collegamento Google Sheet.")
    st.code(str(e))
    st.info("Controlla: 1) SHEET_ID corretto 2) sheet condiviso con client_email del service account 3) secrets private_key con \\n")
    st.stop()

tab_s, tab_m = st.tabs(["✅ Singole", "🧾 Multiple"])

# ----------------- TAB: SINGOLE -----------------
with tab_s:
    st.subheader("➕ Inserisci nuova simulazione (Singola)")
    with st.form("add_form_singole", clear_on_submit=True):
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
            esito = st.selectbox("Esito", OUTCOMES, index=0, key="esito_s")
        with c6:
            note = st.text_input("Note (opzionale)", key="note_s")
        add = st.form_submit_button("Aggiungi")

        if add:
            next_id = 1 if df_s.empty else int(pd.to_numeric(df_s["ID"], errors="coerce").max()) + 1
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
            df2 = pd.concat([df_s, pd.DataFrame([new_row])], ignore_index=True)
            write_singole(ws_singole, df2)
            st.success(f"Inserita singola con ID {next_id} (salvata su Google Sheet)")
            st.rerun()

    st.subheader("📋 Storico SINGOLE (edit diretto)")
    edited_s = st.data_editor(
        df_s,
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
        if st.button("💾 Salva SINGOLE su Google Sheet"):
            write_singole(ws_singole, edited_s)
            st.success("Salvato (SINGOLE).")
            st.rerun()
    with colB:
        st.caption("Nota: se cambi il foglio a mano, clicca “Aggiorna (SINGOLE)”.")

    st.subheader("📈 Report SINGOLE (stake=1)")
    df_calc = df_s.copy()
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

# ----------------- TAB: MULTIPLE -----------------
with tab_m:
    st.subheader("➕ Inserisci nuova simulazione (Multipla)")
    st.caption("Inserisci gli eventi della multipla (uno per riga) nel campo “Multipla”. Inserisci Quota Totale e Stake.")

    with st.form("add_form_multiple", clear_on_submit=True):
        multipla = st.text_area("Multipla (eventi uno per riga)", height=140, placeholder="Es.\nJuve - Napoli | MG 1-3\nInter - Roma | Over 1.5\n...")
        c1, c2, c3 = st.columns([1,1,2])
        with c1:
            quota_tot = st.number_input("Quota Totale", min_value=1.01, step=0.01, value=2.50)
        with c2:
            stake = st.number_input("Stake", min_value=0.0, step=1.0, value=10.0)
        with c3:
            esito_m = st.selectbox("Esito", OUTCOMES, index=0, key="esito_m")
        note_m = st.text_input("Note (opzionale)", key="note_m")

        add_m = st.form_submit_button("Aggiungi Multipla")

        if add_m:
            next_id = 1 if df_m.empty else int(pd.to_numeric(df_m["ID"], errors="coerce").max()) + 1
            new_row = {
                "ID": next_id,
                "Data": datetime.now().strftime("%Y-%m-%d"),
                "Multipla": multipla.strip(),
                "Quota Totale": float(quota_tot),
                "Stake": float(stake),
                "Esito": esito_m,
                "Note": note_m.strip(),
            }
            df2 = pd.concat([df_m, pd.DataFrame([new_row])], ignore_index=True)
            write_multiple(ws_multiple, df2)
            st.success(f"Inserita multipla con ID {next_id} (salvata su Google Sheet)")
            st.rerun()

    st.subheader("📋 Storico MULTIPLE (edit diretto)")
    edited_m = st.data_editor(
        df_m,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "ID": st.column_config.NumberColumn("ID", help="Progressivo univoco", disabled=True),
            "Quota Totale": st.column_config.NumberColumn("Quota Totale", format="%.2f"),
            "Stake": st.column_config.NumberColumn("Stake", format="%.2f"),
            "Esito": st.column_config.SelectboxColumn("Esito", options=OUTCOMES),
            "Multipla": st.column_config.TextColumn("Multipla"),
        },
    )

    colA, colB = st.columns([1,3])
    with colA:
        if st.button("💾 Salva MULTIPLE su Google Sheet"):
            write_multiple(ws_multiple, edited_m)
            st.success("Salvato (MULTIPLE).")
            st.rerun()
    with colB:
        st.caption("Nota: se cambi il foglio a mano, clicca “Aggiorna (MULTIPLE)”.")

    st.subheader("📈 Report MULTIPLE (stake variabile)")
    dfm = df_m.copy()
    dfm["Quota Totale"] = pd.to_numeric(dfm["Quota Totale"], errors="coerce")
    dfm["Stake"] = pd.to_numeric(dfm["Stake"], errors="coerce").fillna(0.0)

    dfm["Profit"] = dfm.apply(lambda r: profit_with_stake(r["Quota Totale"], r["Esito"], r["Stake"]), axis=1)
    dfm_closed = dfm[dfm["Esito"].isin(["Vinta","Persa"])].copy()

    tot_closed_m = len(dfm_closed)
    wins_m = int((dfm_closed["Esito"] == "Vinta").sum())
    losses_m = int((dfm_closed["Esito"] == "Persa").sum())
    pending_m = int((dfm["Esito"] == "In attesa").sum())

    win_rate_m = (wins_m / tot_closed_m * 100) if tot_closed_m else 0.0
    avg_odds_wins_m = float(dfm_closed[dfm_closed["Esito"] == "Vinta"]["Quota Totale"].mean()) if wins_m else 0.0

    profit_total_m = float(dfm_closed["Profit"].sum()) if tot_closed_m else 0.0
    stake_total_m = float(dfm_closed["Stake"].sum()) if tot_closed_m else 0.0
    roi_m = (profit_total_m / stake_total_m * 100) if stake_total_m else 0.0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Chiuse", tot_closed_m)
    c2.metric("Vinte", wins_m)
    c3.metric("Perse", losses_m)
    c4.metric("Win rate", f"{win_rate_m:.1f}%")
    c5.metric("Quota media vinte", f"{avg_odds_wins_m:.2f}")
    c6.metric("Profit totale", f"{profit_total_m:+.2f}")
    c7, c8 = st.columns(2)
    c7.metric("Stake totale (chiuse)", f"{stake_total_m:.2f}")
    c8.metric("ROI %", f"{roi_m:.1f}%")

    st.caption("Profit MULTIPLE: Vinta = stake*(quota_tot-1), Persa = -stake, In attesa = 0.")

