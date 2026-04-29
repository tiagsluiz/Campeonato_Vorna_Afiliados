import re
from datetime import datetime
from math import floor
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="Campeonato de Afiliados Vorna", page_icon="🏆", layout="wide")

SHEET_URL_DEFAULT = "https://docs.google.com/spreadsheets/d/1j_24WY5fInRTL6IgXvb9wd3LplWUqGWffxjKNamCjaI/edit?gid=2095829184#gid=2095829184"
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
    "monthly_prize_total": 10000.0,
    "monthly_prizes_default": {1: 5000, 2: 2500, 3: 1250, 4: 750, 5: 500},
    "final_prizes": {1: 30000, 2: 20000, 3: 10000},
    "turnover_bonus": [(35000, 500), (70000, 1500), (150000, 3000)],
    "ftd_bonus": [(40, 500), (80, 1500), (150, 3000)],
}

ALIASES = {
    "user_id": ["user id", "userid", "id usuario", "id usuário", "cliente id", "customer id", "user"],
    "aff_id": ["aff id", "affid", "affiliate id", "afiliado", "id afiliado", "source", "source id"],
    "date": ["correct data", "correct date", "data correta", "date", "data", "created at", "registration date", "ftd date"],
    "success": ["is successful", "successful", "success", "sucesso", "status"],
    "transaction_type": ["transaction type", "type", "tipo", "tipo transacao", "tipo transação"],
    "amount": ["transaction amount", "amount", "valor", "deposit amount", "montante"],
    "turnover": ["total investment", "turnover", "volume", "investment", "investimento", "giro"],
    "registration_date": ["registration date", "data cadastro", "created at", "created", "signup", "data de cadastro"],
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
    """Carrega os dados diretamente do Google Sheets configurado no código.
    O link não fica exposto no dashboard.
    """
    return pd.read_excel(google_export_url(SHEET_URL_DEFAULT), sheet_name=None, engine="openpyxl")


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Series(df.columns).duplicated().values]
    return df


def find_col(df: pd.DataFrame, key: str, required: bool = True) -> Optional[str]:
    norm_cols = {normalize_text(c): c for c in df.columns}
    for alias in ALIASES[key]:
        n_alias = normalize_text(alias)
        if n_alias in norm_cols:
            return norm_cols[n_alias]
    for alias in ALIASES[key]:
        n_alias = normalize_text(alias)
        for n_col, original in norm_cols.items():
            if n_alias in n_col or n_col in n_alias:
                return original
    if required:
        raise ValueError(f"Coluna não encontrada para: {key}. Colunas disponíveis: {list(df.columns)}")
    return None


def pick_sheet(sheets: Dict[str, pd.DataFrame], wanted: str) -> pd.DataFrame:
    wanted_norm = normalize_text(wanted)
    for name, df in sheets.items():
        if wanted_norm == normalize_text(name):
            return clean_columns(df)
    for name, df in sheets.items():
        if wanted_norm in normalize_text(name):
            return clean_columns(df)
    raise ValueError(f"Aba não encontrada: {wanted}. Abas disponíveis: {list(sheets.keys())}")


def to_number(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0)
    s = series.astype(str).str.replace("R$", "", regex=False).str.replace("$", "", regex=False)
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce").fillna(0)


def to_date(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_datetime(series, unit="D", origin="1899-12-30", errors="coerce")
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def is_success(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.lower()
    return s.isin(["true", "verdadeiro", "1", "sim", "yes", "successful", "sucesso", "success"])


def contains_deposit(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.lower()
    return s.str.contains("deposit", na=False) | s.str.contains("depósito", na=False) | s.str.contains("deposito", na=False)


def prepare_data(sheets: Dict[str, pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inout = pick_sheet(sheets, "In-out")
    trades = pick_sheet(sheets, "Trades")
    users = pick_sheet(sheets, "Usuários")

    in_cols = {
        "user_id": find_col(inout, "user_id"),
        "aff_id": find_col(inout, "aff_id", required=False),
        "date": find_col(inout, "date"),
        "success": find_col(inout, "success"),
        "transaction_type": find_col(inout, "transaction_type"),
        "amount": find_col(inout, "amount"),
    }
    tr_cols = {
        "user_id": find_col(trades, "user_id"),
        "date": find_col(trades, "date"),
        "turnover": find_col(trades, "turnover"),
    }
    user_cols = {
        "user_id": find_col(users, "user_id"),
        "aff_id": find_col(users, "aff_id", required=False),
        "registration_date": find_col(users, "registration_date", required=False),
    }

    users_std = pd.DataFrame()
    users_std["user_id"] = users[user_cols["user_id"]].astype(str).str.strip()
    users_std["aff_id_user"] = users[user_cols["aff_id"]].astype(str).str.strip() if user_cols["aff_id"] else np.nan
    users_std["registration_date"] = to_date(users[user_cols["registration_date"]]) if user_cols["registration_date"] else pd.NaT
    users_std = users_std.drop_duplicates("user_id")

    inout_std = pd.DataFrame()
    inout_std["user_id"] = inout[in_cols["user_id"]].astype(str).str.strip()
    inout_std["date"] = to_date(inout[in_cols["date"]])
    inout_std["success"] = is_success(inout[in_cols["success"]])
    inout_std["transaction_type"] = inout[in_cols["transaction_type"]].astype(str).str.strip().str.lower()
    inout_std["amount"] = to_number(inout[in_cols["amount"]])
    inout_std["aff_id_inout"] = inout[in_cols["aff_id"]].astype(str).str.strip() if in_cols["aff_id"] else np.nan
    inout_std = inout_std.merge(users_std[["user_id", "aff_id_user", "registration_date"]], on="user_id", how="left")
    inout_std["aff_id"] = inout_std["aff_id_inout"].replace(["", "nan", "None"], np.nan).fillna(inout_std["aff_id_user"])
    inout_std["is_deposit"] = contains_deposit(inout_std["transaction_type"])

    trades_std = pd.DataFrame()
    trades_std["user_id"] = trades[tr_cols["user_id"]].astype(str).str.strip()
    trades_std["date"] = to_date(trades[tr_cols["date"]])
    trades_std["turnover"] = to_number(trades[tr_cols["turnover"]])
    trades_std = trades_std.merge(users_std[["user_id", "aff_id_user"]], on="user_id", how="left")
    trades_std = trades_std.rename(columns={"aff_id_user": "aff_id"})

    return inout_std, trades_std, users_std


def calc_ftds(inout: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    deposits_all = inout[(inout["success"]) & (inout["is_deposit"]) & (inout["amount"] > 0)].copy()
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

    dep = inout[(inout["success"]) & (inout["is_deposit"]) & (inout["amount"] > 0)].copy()
    dep = dep[(dep["date"] >= SEASON_START) & (dep["date"] < SEASON_END_EXCLUSIVE)]
    dep["month"] = dep["date"].dt.strftime("%Y-%m")
    deposits = dep.groupby(["aff_id", "month"], dropna=False)["amount"].sum().reset_index(name="deposits")

    tr = trades[(trades["date"] >= SEASON_START) & (trades["date"] < SEASON_END_EXCLUSIVE)].copy()
    tr["month"] = tr["date"].dt.strftime("%Y-%m")
    turnover = tr.groupby(["aff_id", "month"], dropna=False)["turnover"].sum().reset_index(name="turnover")

    ftd_count = ftds.groupby(["aff_id", "month"], dropna=False)["user_id"].nunique().reset_index(name="valid_ftds")

    affs = pd.Series(pd.concat([deposits["aff_id"], turnover["aff_id"], ftd_count["aff_id"]], ignore_index=True).dropna().astype(str).unique(), name="aff_id")
    grid = pd.MultiIndex.from_product([affs, SEASON_MONTHS], names=["aff_id", "month"]).to_frame(index=False)
    monthly = grid.merge(ftd_count, on=["aff_id", "month"], how="left")
    monthly = monthly.merge(deposits, on=["aff_id", "month"], how="left")
    monthly = monthly.merge(turnover, on=["aff_id", "month"], how="left")
    for c in ["valid_ftds", "deposits", "turnover"]:
        monthly[c] = monthly[c].fillna(0)

    monthly = monthly.sort_values(["aff_id", "month"])
    monthly["cum_ftds"] = monthly.groupby("aff_id")["valid_ftds"].cumsum()
    monthly["cum_turnover"] = monthly.groupby("aff_id")["turnover"].cumsum()
    monthly["qualified_now"] = (monthly["cum_ftds"] >= RULES["qualification_ftd"]) & (monthly["cum_turnover"] >= RULES["qualification_turnover"])
    monthly["qualified_month"] = monthly.groupby("aff_id")["qualified_now"].transform(lambda s: s.idxmax() if s.any() else np.nan)
    month_order = {m: i for i, m in enumerate(SEASON_MONTHS)}
    qual_map = monthly[monthly["qualified_now"]].groupby("aff_id")["month"].first().to_dict()
    monthly["first_qualified_month"] = monthly["aff_id"].map(qual_map)
    monthly["is_after_qualification"] = monthly.apply(lambda r: bool(pd.notna(r["first_qualified_month"]) and month_order[r["month"]] >= month_order[r["first_qualified_month"]]), axis=1)
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

    monthly["monthly_position"] = monthly.groupby("month")["monthly_ranking_points"].rank(method="first", ascending=False).astype(int)
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
    final["final_position"] = final["final_points"].rank(method="first", ascending=False).astype(int)
    final.loc[final["final_points"] <= 0, "final_position"] = np.nan
    final["final_prize_estimated"] = final["final_position"].map(RULES["final_prizes"]).fillna(0)
    final = final.sort_values(["final_points", "season_turnover"], ascending=False)
    return monthly, final, ftds


def money(v, prefix="R$"):
    return f"{prefix} {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def usd(v):
    return f"$ {v:,.2f}"


def main():
    st.markdown("""
    <style>
    .main {background-color: #0b1220;}
    .block-container {padding-top: 1.3rem;}
    h1, h2, h3, p, div, label {color: #f8fafc;}
    [data-testid="stMetric"] {background: #111827; border: 1px solid #1f2937; padding: 16px; border-radius: 18px;}
    [data-testid="stDataFrame"] {background: #ffffff;}
    </style>
    """, unsafe_allow_html=True)

    st.title("🏆 Campeonato de Afiliados Vorna")
    st.caption("Período de teste: Novembro de 2025 a Abril de 2026 | Regras configuradas conforme regulamento")

    with st.sidebar:
        st.header("Filtros")
        view_mode = st.radio("Visão", ["Mensal", "Semestral"], horizontal=True)
        selected_month = st.selectbox("Mês", SEASON_MONTHS, index=0, disabled=view_mode == "Semestral")
        affiliate_filter = st.text_input("Filtrar Aff ID (opcional)")
        st.divider()
        st.subheader("Regras atuais")
        st.write("Qualificação: 40 FTDs + $35k turnover")
        st.write("Atividade mensal: 10 FTDs + $20k turnover")
        st.write("Pontos: FTD 2 | $1k depósitos 5 | $10k turnover 5")

    try:
        with st.spinner("Carregando e processando dados..."):
            sheets = load_workbook()
            inout, trades, users = prepare_data(sheets)
            monthly, final, ftds = build_metrics(inout, trades)
    except Exception as e:
        st.error("Não consegui carregar/processar a planilha. Veja o erro abaixo e confira se o Google Sheets está compartilhado/publicado corretamente.")
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
        show = data[["monthly_position", "aff_id", "valid_ftds", "deposits", "turnover", "points_raw", "valid_for_monthly_ranking", "monthly_prize_estimated", "bonus_to_pay_this_month", "cum_ftds", "cum_turnover", "first_qualified_month"]].copy()
        show = show.rename(columns={
            "monthly_position": "Posição", "aff_id": "Aff ID", "valid_ftds": "FTDs válidos", "deposits": "Depósitos", "turnover": "Turnover", "points_raw": "Pontos do mês", "valid_for_monthly_ranking": "Válido no ranking", "monthly_prize_estimated": "Prêmio mensal estimado", "bonus_to_pay_this_month": "Checkpoint liberado no mês", "cum_ftds": "FTDs acumulados", "cum_turnover": "Turnover acumulado", "first_qualified_month": "Mês de qualificação"
        })
        st.dataframe(show, use_container_width=True, hide_index=True)

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
        show = final[["final_position", "aff_id", "final_points", "valid_months", "season_ftds", "season_deposits", "season_turnover", "first_qualified_month", "total_bonus_unlocked", "final_prize_estimated"]].copy()
        show = show.rename(columns={
            "final_position": "Posição final", "aff_id": "Aff ID", "final_points": "Pontos finais", "valid_months": "Meses válidos", "season_ftds": "FTDs válidos", "season_deposits": "Depósitos", "season_turnover": "Turnover", "first_qualified_month": "Mês de qualificação", "total_bonus_unlocked": "Checkpoints liberados", "final_prize_estimated": "Prêmio final estimado"
        })
        st.dataframe(show, use_container_width=True, hide_index=True)

        chart = final[final["final_points"] > 0].head(15)
        if not chart.empty:
            fig = px.bar(chart, x="aff_id", y="final_points", text="final_points", title="Top 15 por pontos finais")
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("Resumo das regras aplicadas no cálculo"):
        st.markdown("""
        - Temporada considerada neste teste: **01/11/2025 a 30/04/2026**.
        - Qualificação cumulativa: **40 FTDs válidos + $35.000 em turnover**.
        - Depois de qualificado, o afiliado permanece elegível até o final.
        - Para o mês contar no ranking mensal e final, precisa cumprir atividade mínima: **10 FTDs e $20.000 em turnover no mês**.
        - Ranking mensal: zera todo mês e não acumula resultado de meses anteriores.
        - Ranking final: soma apenas meses após qualificação e com atividade mínima cumprida.
        - Pontuação: **1 FTD = 2 pontos | cada $1.000 em depósitos = 5 pontos | cada $10.000 em turnover = 5 pontos**.
        - FTD válido: primeiro depósito do usuário + pelo menos uma operação/trade após o depósito.
        - Checkpoints são cumulativos na temporada.
        """)

    st.caption("Observação: prêmios aparecem como estimativa operacional. A validação final deve seguir auditoria interna da Vorna.")


if __name__ == "__main__":
    main()
