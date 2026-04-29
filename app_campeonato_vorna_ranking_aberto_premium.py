
import re
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="Campeonato de Afiliados Vorna", page_icon="🏆", layout="wide")

# Link fica somente no código. Não aparece no dashboard.
SHEET_URL_DEFAULT = "https://docs.google.com/spreadsheets/d/1j_24WY5fInRTL6IgXvb9wd3LplWUqGWffxjKNamCjaI/edit?gid=2095829184#gid=2095829184"

# Período de teste solicitado
SEASON_START = pd.Timestamp("2025-11-01")
SEASON_END_EXCLUSIVE = pd.Timestamp("2026-05-01")
SEASON_MONTHS = ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04"]

RULES = {
    "qualification_ftd": 40,
    "qualification_turnover": 35000.0,
    "monthly_activity_ftd": 10,
    "monthly_activity_turnover": 20000.0,
    "points_per_ftd": 2,
    "points_deposit_step": 1000.0,
    "points_per_deposit_step": 5,
    "points_turnover_step": 10000.0,
    "points_per_turnover_step": 5,
    "monthly_prizes_default": {1: 5000, 2: 2500, 3: 1250, 4: 750, 5: 500},
    "final_prizes": {1: 30000, 2: 20000, 3: 10000},
    "turnover_bonus": [(35000, 500), (70000, 1500), (150000, 3000)],
    "ftd_bonus": [(40, 500), (80, 1500), (150, 3000)],
}

# Mapeamento EXATO conforme prints enviados
COLS = {
    "inout": {
        "success": "Is Successful",
        "user_id": "User ID",
        "amount": "Transaction amount",
        "transaction_type": "Transaction type",
        "date": "Correct Data",
        "aff_id": "Aff ID",
    },
    "trades": {
        "user_id": "User ID",
        "date": "Correct D",
        "turnover": "Total Investment",
    },
    "users": {
        "user_id": "User ID",
        "registration_date": "Correct Data",
        "aff_id": "Aff ID",
    },
}


def normalize_text(x: object) -> str:
    s = str(x or "").strip().lower()
    s = re.sub(r"[\n\r\t]+", " ", s)
    s = s.replace("ç", "c").replace("ã", "a").replace("á", "a").replace("à", "a").replace("â", "a")
    s = s.replace("é", "e").replace("ê", "e").replace("í", "i").replace("ó", "o").replace("ô", "o").replace("õ", "o").replace("ú", "u")
    s = re.sub(r"\s+", " ", s)
    return s


def google_export_url(url: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not m:
        return url
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=xlsx"


@st.cache_data(ttl=600, show_spinner=False)
def load_workbook() -> Dict[str, pd.DataFrame]:
    return pd.read_excel(google_export_url(SHEET_URL_DEFAULT), sheet_name=None, engine="openpyxl")


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Series(df.columns).duplicated().values]
    return df


def pick_sheet(sheets: Dict[str, pd.DataFrame], wanted: str) -> pd.DataFrame:
    wanted_norm = normalize_text(wanted)
    for name, df in sheets.items():
        if wanted_norm == normalize_text(name) or wanted_norm in normalize_text(name):
            return clean_columns(df)
    raise ValueError(f"Aba não encontrada: {wanted}. Abas disponíveis: {list(sheets.keys())}")


def get_col(df: pd.DataFrame, exact_name: str) -> str:
    # tenta exato
    if exact_name in df.columns:
        return exact_name
    # tenta normalizado
    target = normalize_text(exact_name)
    for c in df.columns:
        if normalize_text(c) == target:
            return c
    # tenta contém
    for c in df.columns:
        if target in normalize_text(c) or normalize_text(c) in target:
            return c
    raise ValueError(f"Coluna '{exact_name}' não encontrada. Colunas disponíveis: {list(df.columns)}")


def parse_money_value(x) -> float:
    """Converte valores como '$30,00$', '$2.00', '1.234,56', '1,234.56' sem multiplicar por 100."""
    if pd.isna(x):
        return 0.0
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)

    s = str(x).strip()
    if not s:
        return 0.0

    # remove moeda, espaços e qualquer caractere que não seja dígito, vírgula, ponto ou sinal
    s = s.replace("R$", "").replace("US$", "").replace("USD", "").replace("$", "").strip()
    s = re.sub(r"[^0-9,\.\-]", "", s)

    if not s or s in ["-", ".", ","]:
        return 0.0

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # o último separador costuma ser o decimal
        if s.rfind(",") > s.rfind("."):
            # padrão BR: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:
            # padrão US: 1,234.56
            s = s.replace(",", "")
    elif has_comma:
        # na planilha aparece $30,00 e $2,00
        s = s.replace(".", "").replace(",", ".")
    elif has_dot:
        # se houver vários pontos, assume milhares; se houver um ponto, assume decimal
        if s.count(".") > 1:
            parts = s.split(".")
            s = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(s)
    except ValueError:
        return 0.0


def to_number(series: pd.Series) -> pd.Series:
    return series.apply(parse_money_value).astype(float)


def to_date(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_datetime(series, unit="D", origin="1899-12-30", errors="coerce")
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def is_success(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.lower()
    return s.isin(["true", "verdadeiro", "1", "sim", "yes", "successful", "sucesso", "success"])


def is_deposit_type(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.lower()
    return s.eq("deposit") | s.eq("depósito") | s.eq("deposito")


def is_valid_aff(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    return ~(s.isin(["", "0", "0.0", "nan", "None", "NaN"]))


def prepare_data(sheets: Dict[str, pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, str]]:
    inout = pick_sheet(sheets, "In-out")
    trades = pick_sheet(sheets, "Trades")
    users = pick_sheet(sheets, "Usuários")

    c = {
        "inout_success": get_col(inout, COLS["inout"]["success"]),
        "inout_user_id": get_col(inout, COLS["inout"]["user_id"]),
        "inout_amount": get_col(inout, COLS["inout"]["amount"]),
        "inout_type": get_col(inout, COLS["inout"]["transaction_type"]),
        "inout_date": get_col(inout, COLS["inout"]["date"]),
        "inout_aff_id": get_col(inout, COLS["inout"]["aff_id"]),
        "trades_user_id": get_col(trades, COLS["trades"]["user_id"]),
        "trades_date": get_col(trades, COLS["trades"]["date"]),
        "trades_turnover": get_col(trades, COLS["trades"]["turnover"]),
        "users_user_id": get_col(users, COLS["users"]["user_id"]),
        "users_aff_id": get_col(users, COLS["users"]["aff_id"]),
        "users_registration_date": get_col(users, COLS["users"]["registration_date"]),
    }

    users_std = pd.DataFrame()
    users_std["user_id"] = users[c["users_user_id"]].astype(str).str.strip()
    users_std["aff_id_user"] = users[c["users_aff_id"]].astype(str).str.strip()
    users_std["registration_date"] = to_date(users[c["users_registration_date"]])
    users_std = users_std.drop_duplicates("user_id")

    inout_std = pd.DataFrame()
    inout_std["user_id"] = inout[c["inout_user_id"]].astype(str).str.strip()
    inout_std["date"] = to_date(inout[c["inout_date"]])
    inout_std["success"] = is_success(inout[c["inout_success"]])
    inout_std["transaction_type"] = inout[c["inout_type"]].astype(str).str.strip().str.lower()
    inout_std["amount"] = to_number(inout[c["inout_amount"]])
    inout_std["aff_id_inout"] = inout[c["inout_aff_id"]].astype(str).str.strip()
    inout_std = inout_std.merge(users_std[["user_id", "aff_id_user", "registration_date"]], on="user_id", how="left")

    # Prioriza Aff ID da In-out. Se estiver vazio/0, usa Aff ID da aba Usuários.
    inout_aff = inout_std["aff_id_inout"].where(is_valid_aff(inout_std["aff_id_inout"]), np.nan)
    user_aff = inout_std["aff_id_user"].where(is_valid_aff(inout_std["aff_id_user"]), np.nan)
    inout_std["aff_id"] = inout_aff.fillna(user_aff)
    inout_std["is_deposit"] = is_deposit_type(inout_std["transaction_type"])

    trades_std = pd.DataFrame()
    trades_std["user_id"] = trades[c["trades_user_id"]].astype(str).str.strip()
    trades_std["date"] = to_date(trades[c["trades_date"]])
    trades_std["turnover"] = to_number(trades[c["trades_turnover"]])
    trades_std = trades_std.merge(users_std[["user_id", "aff_id_user"]], on="user_id", how="left")
    trades_std["aff_id"] = trades_std["aff_id_user"].where(is_valid_aff(trades_std["aff_id_user"]), np.nan)

    return inout_std, trades_std, users_std, c


def calc_ftds(inout: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    # FTD = primeiro depósito bem-sucedido do usuário + pelo menos um trade em/apos esse depósito.
    deposits_all = inout[
        (inout["success"])
        & (inout["is_deposit"])
        & (inout["amount"] > 0)
        & (inout["aff_id"].notna())
    ].copy()

    if deposits_all.empty:
        return pd.DataFrame(columns=["user_id", "aff_id", "ftd_date", "month", "valid_ftd"])

    first_dep = deposits_all.sort_values("date").groupby("user_id", as_index=False).first()
    trade_first = trades[trades["turnover"] > 0].groupby("user_id", as_index=False)["date"].min().rename(columns={"date": "first_trade_date"})
    ftd = first_dep.merge(trade_first, on="user_id", how="left")
    ftd["valid_ftd"] = ftd["first_trade_date"].notna() & (ftd["first_trade_date"] >= ftd["date"])
    ftd = ftd[(ftd["date"] >= SEASON_START) & (ftd["date"] < SEASON_END_EXCLUSIVE) & (ftd["valid_ftd"])]
    ftd = ftd.rename(columns={"date": "ftd_date"})
    ftd["month"] = ftd["ftd_date"].dt.strftime("%Y-%m")
    return ftd[["user_id", "aff_id", "ftd_date", "month", "valid_ftd"]]


def calc_bonus(value: float, tiers) -> float:
    bonus = 0
    for threshold, amount in tiers:
        if value >= threshold:
            bonus = amount
    return bonus


def build_metrics(inout: pd.DataFrame, trades: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ftds = calc_ftds(inout, trades)

    dep = inout[
        (inout["success"])
        & (inout["is_deposit"])
        & (inout["amount"] > 0)
        & (inout["aff_id"].notna())
        & (inout["date"] >= SEASON_START)
        & (inout["date"] < SEASON_END_EXCLUSIVE)
    ].copy()
    dep["month"] = dep["date"].dt.strftime("%Y-%m")
    deposits = dep.groupby(["aff_id", "month"], dropna=False)["amount"].sum().reset_index(name="deposits")

    tr = trades[
        (trades["turnover"] > 0)
        & (trades["aff_id"].notna())
        & (trades["date"] >= SEASON_START)
        & (trades["date"] < SEASON_END_EXCLUSIVE)
    ].copy()
    tr["month"] = tr["date"].dt.strftime("%Y-%m")
    turnover = tr.groupby(["aff_id", "month"], dropna=False)["turnover"].sum().reset_index(name="turnover")

    ftd_count = ftds.groupby(["aff_id", "month"], dropna=False)["user_id"].nunique().reset_index(name="valid_ftds")

    all_affs = pd.concat([deposits["aff_id"], turnover["aff_id"], ftd_count["aff_id"]], ignore_index=True).dropna().astype(str).unique()
    affs = pd.Series(all_affs, name="aff_id")
    grid = pd.MultiIndex.from_product([affs, SEASON_MONTHS], names=["aff_id", "month"]).to_frame(index=False)

    monthly = grid.merge(ftd_count, on=["aff_id", "month"], how="left")
    monthly = monthly.merge(deposits, on=["aff_id", "month"], how="left")
    monthly = monthly.merge(turnover, on=["aff_id", "month"], how="left")
    for col in ["valid_ftds", "deposits", "turnover"]:
        monthly[col] = monthly[col].fillna(0)

    monthly = monthly.sort_values(["aff_id", "month"])
    monthly["cum_ftds"] = monthly.groupby("aff_id")["valid_ftds"].cumsum()
    monthly["cum_turnover"] = monthly.groupby("aff_id")["turnover"].cumsum()

    monthly["qualified_now"] = (monthly["cum_ftds"] >= RULES["qualification_ftd"]) & (monthly["cum_turnover"] >= RULES["qualification_turnover"])
    qual_map = monthly[monthly["qualified_now"]].groupby("aff_id")["month"].first().to_dict()
    monthly["first_qualified_month"] = monthly["aff_id"].map(qual_map)

    month_order = {m: i for i, m in enumerate(SEASON_MONTHS)}
    monthly["is_after_qualification"] = monthly.apply(
        lambda r: bool(pd.notna(r["first_qualified_month"]) and month_order[r["month"]] >= month_order[r["first_qualified_month"]]),
        axis=1,
    )

    monthly["monthly_activity_ok"] = (monthly["valid_ftds"] >= RULES["monthly_activity_ftd"]) & (monthly["turnover"] >= RULES["monthly_activity_turnover"])
    monthly["valid_for_monthly_ranking"] = monthly["is_after_qualification"] & monthly["monthly_activity_ok"]
    monthly["valid_for_final_ranking"] = monthly["valid_for_monthly_ranking"]

    monthly["ftd_points"] = monthly["valid_ftds"] * RULES["points_per_ftd"]
    monthly["deposit_points"] = (monthly["deposits"] // RULES["points_deposit_step"]) * RULES["points_per_deposit_step"]
    monthly["turnover_points"] = (monthly["turnover"] // RULES["points_turnover_step"]) * RULES["points_per_turnover_step"]
    monthly["points_raw"] = monthly["ftd_points"] + monthly["deposit_points"] + monthly["turnover_points"]
    monthly["monthly_ranking_points"] = np.where(monthly["valid_for_monthly_ranking"], monthly["points_raw"], 0)
    monthly["final_ranking_points"] = np.where(monthly["valid_for_final_ranking"], monthly["points_raw"], 0)

    monthly["turnover_bonus_unlocked"] = monthly["cum_turnover"].apply(lambda x: calc_bonus(x, RULES["turnover_bonus"]))
    monthly["ftd_bonus_unlocked"] = monthly["cum_ftds"].apply(lambda x: calc_bonus(x, RULES["ftd_bonus"]))
    monthly["total_bonus_unlocked"] = monthly["turnover_bonus_unlocked"] + monthly["ftd_bonus_unlocked"]
    monthly["bonus_to_pay_this_month"] = monthly.groupby("aff_id")["total_bonus_unlocked"].diff().fillna(monthly["total_bonus_unlocked"])

    monthly["monthly_position"] = monthly.groupby("month")["monthly_ranking_points"].rank(method="first", ascending=False)
    monthly.loc[monthly["monthly_ranking_points"] <= 0, "monthly_position"] = np.nan
    monthly["monthly_prize_estimated"] = monthly["monthly_position"].map(RULES["monthly_prizes_default"]).fillna(0)

    final = monthly.groupby("aff_id", as_index=False).agg(
        final_points=("final_ranking_points", "sum"),
        valid_months=("valid_for_final_ranking", "sum"),
        season_ftds=("valid_ftds", "sum"),
        season_deposits=("deposits", "sum"),
        season_turnover=("turnover", "sum"),
        total_bonus_unlocked=("total_bonus_unlocked", "max"),
        first_qualified_month=("first_qualified_month", "first"),
    )
    final["qualified"] = final["first_qualified_month"].notna()
    final = final.sort_values(["final_points", "season_turnover"], ascending=False).reset_index(drop=True)
    final["final_position"] = np.where(final["final_points"] > 0, np.arange(1, len(final) + 1), np.nan)
    final["final_prize_estimated"] = final["final_position"].map(RULES["final_prizes"]).fillna(0)

    return monthly, final, ftds


def usd(v):
    return f"$ {v:,.2f}"


def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def medalha(pos):
    try:
        pos_int = int(pos)
    except Exception:
        return ""
    if pos_int == 1:
        return "🥇"
    if pos_int == 2:
        return "🥈"
    if pos_int == 3:
        return "🥉"
    return ""


def format_usd_cell(v):
    try:
        return f"$ {float(v):,.2f}"
    except Exception:
        return "$ 0.00"


def format_brl_cell(v):
    try:
        return brl(float(v))
    except Exception:
        return "R$ 0,00"


def highlight_ranking(row):
    pos = row.get("Posição final", row.get("Posição", None))
    try:
        pos = int(pos)
    except Exception:
        return [""] * len(row)

    if pos == 1:
        return ["background-color: rgba(255, 215, 0, 0.20); font-weight: 700;"] * len(row)
    if pos == 2:
        return ["background-color: rgba(192, 192, 192, 0.20); font-weight: 700;"] * len(row)
    if pos == 3:
        return ["background-color: rgba(205, 127, 50, 0.22); font-weight: 700;"] * len(row)
    return [""] * len(row)


def main():
    st.markdown("""
    <style>
    .block-container {padding-top: 1.3rem;}
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #111827 0%, #0b1220 100%);
        border: 1px solid #1f2937;
        padding: 16px;
        border-radius: 18px;
        box-shadow: 0 12px 30px rgba(0,0,0,.22);
    }
    h1 {letter-spacing: -0.03em;}
    div[data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid #1f2937;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("🏆 Campeonato de Afiliados Vorna")
    st.caption("Período de teste: Novembro de 2025 a Abril de 2026 | Dados puxados direto do Google Sheets")

    with st.sidebar:
        st.header("Filtros")
        view_mode = st.radio("Visão", ["Mensal", "Semestral"], horizontal=True)
        selected_month = st.selectbox("Mês", SEASON_MONTHS, index=0, disabled=view_mode == "Semestral")
        affiliate_filter = st.text_input("Filtrar Aff ID (opcional)")
        hide_unaffiliated = st.checkbox("Ocultar usuários sem afiliado / Aff ID 0", value=True)
        st.divider()
        st.subheader("Regras atuais")
        st.write("Qualificação: 40 FTDs + $35k turnover")
        st.write("Atividade mensal: 10 FTDs + $20k turnover")
        st.write("Pontos: FTD 2 | $1k depósitos 5 | $10k turnover 5")

    try:
        with st.spinner("Carregando e processando dados..."):
            sheets = load_workbook()
            inout, trades, users, used_cols = prepare_data(sheets)

            if hide_unaffiliated:
                inout = inout[inout["aff_id"].notna()].copy()
                trades = trades[trades["aff_id"].notna()].copy()

            monthly, final, ftds = build_metrics(inout, trades)

    except Exception as e:
        st.error("Não consegui carregar/processar a planilha. Confira se o Google Sheets está acessível e se as colunas continuam com os mesmos nomes.")
        st.exception(e)
        st.stop()

    if affiliate_filter.strip():
        f = affiliate_filter.strip()
        monthly = monthly[monthly["aff_id"].astype(str).str.contains(f, case=False, na=False)]
        final = final[final["aff_id"].astype(str).str.contains(f, case=False, na=False)]

    if view_mode == "Mensal":
        data = monthly[monthly["month"] == selected_month].copy().sort_values(["monthly_ranking_points", "turnover"], ascending=False)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Afiliados qualificados", int(data["is_after_qualification"].sum()))
        c2.metric("Ativos no mês", int(data["monthly_activity_ok"].sum()))
        c3.metric("FTDs válidos", int(data["valid_ftds"].sum()))
        c4.metric("Depósitos", usd(data["deposits"].sum()))
        c5.metric("Turnover", usd(data["turnover"].sum()))

        st.subheader(f"Ranking mensal — {selected_month}")
        show = data[[
            "monthly_position", "aff_id", "valid_ftds", "deposits", "turnover",
            "ftd_points", "deposit_points", "turnover_points", "points_raw",
            "valid_for_monthly_ranking", "monthly_prize_estimated",
            "bonus_to_pay_this_month", "cum_ftds", "cum_turnover", "first_qualified_month"
        ]].copy()
        show = show.rename(columns={
            "monthly_position": "Posição",
            "aff_id": "Aff ID",
            "valid_ftds": "FTDs válidos",
            "deposits": "Depósitos",
            "turnover": "Turnover",
            "ftd_points": "Pts FTD",
            "deposit_points": "Pts Depósito",
            "turnover_points": "Pts Turnover",
            "points_raw": "Pontos do mês",
            "valid_for_monthly_ranking": "Válido no ranking",
            "monthly_prize_estimated": "Prêmio mensal estimado",
            "bonus_to_pay_this_month": "Checkpoint liberado no mês",
            "cum_ftds": "FTDs acumulados",
            "cum_turnover": "Turnover acumulado",
            "first_qualified_month": "Mês de qualificação",
        })

        show["Medalha"] = show["Posição"].apply(medalha)
        show["Status"] = show["Mês de qualificação"].apply(lambda x: "🟢 QUALIFICADO" if pd.notna(x) else "🔴 NÃO QUALIFICADO")
        show["Depósitos"] = show["Depósitos"].apply(format_usd_cell)
        show["Turnover"] = show["Turnover"].apply(format_usd_cell)
        show["Checkpoint liberado no mês"] = show["Checkpoint liberado no mês"].apply(format_brl_cell)
        show["Prêmio mensal estimado"] = show["Prêmio mensal estimado"].apply(format_brl_cell)
        show["Turnover acumulado"] = show["Turnover acumulado"].apply(format_usd_cell)

        show = show[[
            "Medalha", "Posição", "Aff ID", "Status", "Pontos do mês",
            "FTDs válidos", "Depósitos", "Turnover", "Pts FTD", "Pts Depósito",
            "Pts Turnover", "Válido no ranking", "Prêmio mensal estimado",
            "Checkpoint liberado no mês", "FTDs acumulados", "Turnover acumulado",
            "Mês de qualificação"
        ]]

        styled = show.style.apply(highlight_ranking, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)

        chart = data[data["monthly_ranking_points"] > 0].head(15)
        if not chart.empty:
            fig = px.bar(chart, x="aff_id", y="monthly_ranking_points", text="monthly_ranking_points", title="Top 15 por pontos mensais")
            st.plotly_chart(fig, use_container_width=True)

    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Afiliados qualificados", int(final["qualified"].sum()))
        c2.metric("Meses válidos", int(final["valid_months"].sum()))
        c3.metric("FTDs válidos", int(final["season_ftds"].sum()))
        c4.metric("Depósitos", usd(final["season_deposits"].sum()))
        c5.metric("Turnover", usd(final["season_turnover"].sum()))

        st.subheader("Ranking final / semestral")
        show = final[[
            "final_position", "aff_id", "final_points", "valid_months", "season_ftds",
            "season_deposits", "season_turnover", "first_qualified_month",
            "total_bonus_unlocked", "final_prize_estimated"
        ]].copy()
        show = show.rename(columns={
            "final_position": "Posição final",
            "aff_id": "Aff ID",
            "final_points": "Pontos finais",
            "valid_months": "Meses válidos",
            "season_ftds": "FTDs válidos",
            "season_deposits": "Depósitos",
            "season_turnover": "Turnover",
            "first_qualified_month": "Mês de qualificação",
            "total_bonus_unlocked": "Checkpoints liberados",
            "final_prize_estimated": "Prêmio final estimado",
        })

        show["Medalha"] = show["Posição final"].apply(medalha)
        show["Status"] = show["Mês de qualificação"].apply(lambda x: "🟢 QUALIFICADO" if pd.notna(x) else "🔴 NÃO QUALIFICADO")
        show["Depósitos"] = show["Depósitos"].apply(format_usd_cell)
        show["Turnover"] = show["Turnover"].apply(format_usd_cell)
        show["Checkpoints liberados"] = show["Checkpoints liberados"].apply(format_brl_cell)
        show["Prêmio final estimado"] = show["Prêmio final estimado"].apply(format_brl_cell)

        show = show[[
            "Medalha", "Posição final", "Aff ID", "Status", "Pontos finais",
            "Meses válidos", "FTDs válidos", "Depósitos", "Turnover",
            "Mês de qualificação", "Checkpoints liberados", "Prêmio final estimado"
        ]]

        styled = show.style.apply(highlight_ranking, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)

        chart = final[final["final_points"] > 0].head(15)
        if not chart.empty:
            fig = px.bar(chart, x="aff_id", y="final_points", text="final_points", title="Top 15 por pontos finais")
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("Auditoria rápida dos dados"):
        valid_dep = inout[
            (inout["success"])
            & (inout["is_deposit"])
            & (inout["amount"] > 0)
            & (inout["date"] >= SEASON_START)
            & (inout["date"] < SEASON_END_EXCLUSIVE)
            & (inout["aff_id"].notna())
        ]
        valid_tr = trades[
            (trades["turnover"] > 0)
            & (trades["date"] >= SEASON_START)
            & (trades["date"] < SEASON_END_EXCLUSIVE)
            & (trades["aff_id"].notna())
        ]
        st.write("Colunas usadas:", used_cols)
        st.write("Depósitos válidos considerados:", len(valid_dep), "| Soma:", usd(valid_dep["amount"].sum()))
        st.write("Trades considerados:", len(valid_tr), "| Turnover:", usd(valid_tr["turnover"].sum()))
        st.write("Amostra de depósitos válidos")
        st.dataframe(valid_dep[["date", "user_id", "aff_id", "transaction_type", "amount", "success"]].head(20), use_container_width=True, hide_index=True)
        st.write("Amostra de trades")
        st.dataframe(valid_tr[["date", "user_id", "aff_id", "turnover"]].head(20), use_container_width=True, hide_index=True)

    with st.expander("Resumo das regras aplicadas no cálculo"):
        st.markdown("""
        - Temporada considerada neste teste: **01/11/2025 a 30/04/2026**.
        - Depósitos: aba **In-out**, somente **Is Successful = VERDADEIRO**, **Transaction type = deposit**, somando **Transaction amount**.
        - Turnover: aba **Trades**, somando **Total Investment**, com Aff ID cruzado pela aba **Usuários**.
        - Qualificação cumulativa: **40 FTDs válidos + $35.000 em turnover**.
        - Depois de qualificado, o afiliado permanece elegível até o final.
        - Para o mês contar no ranking mensal e final: **10 FTDs e $20.000 em turnover no mês**.
        - Ranking mensal: zera todo mês.
        - Ranking final: soma apenas meses após qualificação e com atividade mínima cumprida.
        - Pontuação: **1 FTD = 2 pontos | cada $1.000 em depósitos = 5 pontos | cada $10.000 em turnover = 5 pontos**.
        - FTD válido: primeiro depósito do usuário + pelo menos uma operação/trade após o depósito.
        """)

    st.caption("Observação: prêmios aparecem como estimativa operacional. A validação final deve seguir auditoria interna da Vorna.")


if __name__ == "__main__":
    main()
