import streamlit as st
import pandas as pd
import textwrap
import datetime as dt
import json
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="MG Decision App – Simulazione", layout="wide")
st.title("MG Decision App – Modalità SIMULAZIONE (Google Sheet)")

st.markdown(
    """
✅ **Salvataggio persistente**: lo storico è salvato su **Google Sheet** (non si perde con restart/deploy).  
Usabile da **PC e cellulare** tramite browser.
"""
)

# Secrets richiesti:
# SHEET_ID="..."
# GCP_SERVICE_ACCOUNT_JSON='''{ ... }'''

SHEET_ID = st.secrets.get("SHEET_ID", "").strip()
if not SHEET_ID:
    st.error("Manca SHEET_ID nei Secrets.")
    st.stop()

raw_sa = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON", "")
if not raw_sa:
    st.error("Manca GCP_SERVICE_ACCOUNT_JSON nei Secrets.")
    st.stop()

try:
    sa_info = json.loads(raw_sa)
except Exception:
    st.error("GCP_SERVICE_ACCOUNT_JSON non è un JSON valido. Ricontrolla i tre apici e che sia completo da { a }.")
    st.stop()

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

try:
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPE)
    gc = gspread.authorize(creds)
except Exception:
    st.error("Errore credenziali: quasi sempre private_key incollata male nel JSON (\\n o blocco incompleto).")
    st.stop()

COLUMNS = ["Campionato", "Partita", "Giocata", "Quota", "Esito", "Note", "DataInserimento"]

@st.cache_resource(show_spinner=False)
def open_ws():
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1
    values = ws.get_all_values()
    if not values:
        ws.append_row(COLUMNS)
    else:
        header = values[0]
        if header != COLUMNS:
            ws.clear()
            ws.append_row(COLUMNS)
    return ws

def sheet_to_df(ws) -> pd.DataFrame:
    values = ws.get_all_values()
    if len(values) <= 1:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(values[1:], columns=values[0])
    df["Quota"] = pd.to_numeric(df["Quota"], errors="coerce")
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNS]

def df_to_sheet(ws, df: pd.DataFrame) -> None:
    ws.clear()
    ws.append_row(COLUMNS)
    if not df.empty:
        rows = df.fillna("").astype(str).values.tolist()
        ws.append_rows(rows, value_input_option="USER_ENTERED")

ws = open_ws()

if "storico" not in st.session_state:
    st.session_state.storico = sheet_to_df(ws)

st.sidebar.header("Storage")
if st.sidebar.button("Ricarica da Google Sheet"):
    st.session_state.storico = sheet_to_df(ws)
    st.sidebar.success("Ricaricato.")

if st.sidebar.button("Salva su Google Sheet (forza)"):
    df_to_sheet(ws, st.session_state.storico)
    st.sidebar.success("Salvato.")

st.subheader("➕ Inserisci simulazione")

campionato = st.selectbox(
    "Campionato",
    ["Serie A", "Premier League", "Liga", "Bundesliga", "Ligue 1", "Altro"]
)
partita = st.text_input("Partita (es. Arsenal - Man United)")
giocata = st.text_input("Giocata (es. MG 1-2 Man United)")
quota = st.number_input("Quota", min_value=1.01, step=0.01, format="%.2f")
esito = st.selectbox("Esito", ["Simulata", "Vinta", "Persa"])
note = st.text_area("Note (facoltative)")

if st.button("Aggiungi"):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    nuovo = pd.DataFrame([[campionato, partita, giocata, float(quota), esito, note, now]], columns=COLUMNS)
    st.session_state.storico = pd.concat([st.session_state.storico, nuovo], ignore_index=True)
    df_to_sheet(ws, st.session_state.storico)
    st.success("Aggiunta e salvata su Google Sheet ✅")

st.divider()

st.subheader("🔎 Filtri")
all_camps = sorted(st.session_state.storico["Campionato"].dropna().unique().tolist()) or [
    "Serie A","Premier League","Liga","Bundesliga","Ligue 1","Altro"
]
camp_fil = st.multiselect("Filtra per campionato", options=all_camps, default=all_camps)

df_filtrato = st.session_state.storico[st.session_state.storico["Campionato"].isin(camp_fil)].copy()

def wrap_text(val, width=40):
    if isinstance(val, str):
        return "\n".join(textwrap.wrap(val, width))
    return val

display_df = df_filtrato.copy()
display_df["Partita"] = display_df["Partita"].apply(lambda x: wrap_text(x, 35))
display_df["Giocata"] = display_df["Giocata"].apply(lambda x: wrap_text(x, 35))
display_df["Note"] = display_df["Note"].apply(lambda x: wrap_text(x, 50))

st.subheader("📋 Storico simulazioni")
st.dataframe(display_df, use_container_width=True, hide_index=True)

st.divider()

st.subheader("✏️ Modifica / elimina (salva subito)")

df_all = st.session_state.storico
if not df_all.empty:
    idx = st.number_input("Indice riga (0 = prima riga)", min_value=0, max_value=len(df_all)-1, step=1)
    col = st.selectbox("Colonna", COLUMNS)
    nuovo_valore = st.text_input("Nuovo valore (Quota: es. 1.75)")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Modifica"):
            df = df_all.copy()
            if col == "Quota":
                try:
                    df.at[idx, col] = float(nuovo_valore)
                except Exception:
                    st.error("Quota non valida. Usa formato tipo 1.75")
                    st.stop()
            else:
                df.at[idx, col] = nuovo_valore
            st.session_state.storico = df
            df_to_sheet(ws, df)
            st.success("Modifica salvata ✅")

    with c2:
        if st.button("Elimina"):
            df = df_all.drop(idx).reset_index(drop=True)
            st.session_state.storico = df
            df_to_sheet(ws, df)
            st.success("Eliminata ✅")
else:
    st.info("Nessuna riga nello storico per ora.")

st.divider()

st.subheader("📊 Report (filtrato)")

df = df_filtrato.copy()
tot = len(df)
vinte = (df["Esito"] == "Vinta").sum()
perse = (df["Esito"] == "Persa").sum()
simulate = (df["Esito"] == "Simulata").sum()

st.write(f"Totale: **{tot}** | Vinte: **{vinte}** | Perse: **{perse}** | Simulate: **{simulate}**")

if tot > 0:
    st.write(f"Win rate (su totale): **{(vinte/tot):.1%}**")
if (vinte + perse) > 0:
    st.write(f"Win rate (solo chiuse): **{(vinte/(vinte+perse)):.1%}**")

if vinte > 0:
    st.write(f"Quota media vinte: **{df.loc[df['Esito']=='Vinta','Quota'].mean():.2f}**")
if perse > 0:
    st.write(f"Quota media perse: **{df.loc[df['Esito']=='Persa','Quota'].mean():.2f}**")
if tot > 0:
    st.write(f"Quota media totale: **{df['Quota'].mean():.2f}**")

st.markdown("### 💰 Profit simulato (stake 1)")
profit = 0.0
for _, r in df.iterrows():
    if r["Esito"] == "Vinta":
        profit += float(r["Quota"]) - 1.0
    elif r["Esito"] == "Persa":
        profit -= 1.0
st.write(f"Profit (solo per studio): **{profit:.2f}u**")

st.markdown("### 📌 Breakdown per campionato (nel filtro attuale)")
if tot > 0:
    grp = df.groupby("Campionato").agg(
        Tot=("Campionato","count"),
        Vinte=("Esito", lambda s: (s=="Vinta").sum()),
        Perse=("Esito", lambda s: (s=="Persa").sum()),
        Simulate=("Esito", lambda s: (s=="Simulata").sum()),
        QuotaMedia=("Quota","mean"),
    ).reset_index()
    st.dataframe(grp, use_container_width=True, hide_index=True)

st.divider()

st.subheader("⬇️ Export")
csv_bytes = st.session_state.storico.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
st.download_button("Scarica CSV dello storico", data=csv_bytes, file_name="mg_storico_export.csv", mime="text/csv")
