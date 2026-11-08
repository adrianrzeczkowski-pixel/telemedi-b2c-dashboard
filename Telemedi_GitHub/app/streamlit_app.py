"""Telemedi B2C — publiczny przegląd zagregowanej analizy.

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.queries import (  # noqa: E402
    Filters,
    anomalies,
    anomalies_weekly,
    campaign_economics,
    matched_d90_spend,
    channel_economics,
    cohort_monthly,
    daily_series,
    default_filters,
    dimensions,
    funnel_breakdown,
    headlines,
    overview,
    retention,
    specialization,
    static_table,
)

st.set_page_config(
    page_title="Telemedi B2C",
    page_icon="◎",
    layout="wide",
    initial_sidebar_state="expanded",
)

COLORS = ["#0f6e6b", "#d97706", "#1d4e89", "#be4b4b", "#5b7c6e", "#7c6aad"]

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: "Source Sans 3", "Segoe UI", sans-serif; }
    .stApp { background: #f3f6f6; }
    .block-container { padding-top: 1.2rem; max-width: 1240px; }
    .fictional {
        background: #fff7e8; border: 1px solid #f0d7a2; color: #6b4e16;
        border-radius: 12px; padding: 0.7rem 1rem; margin-bottom: 0.8rem;
    }
    .metric-card {
        background: white; border: 1px solid #e3eaea; border-radius: 14px;
        padding: 0.85rem 1rem 0.7rem; min-height: 108px;
    }
    .metric-card .label { color: #5d7274; font-size: 0.82rem; letter-spacing: 0.01em; }
    .metric-card .value { color: #163033; font-size: 1.45rem; font-weight: 700; margin: 0.15rem 0; }
    .metric-card .hint { color: #7b8e90; font-size: 0.78rem; }
    div[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e3eaea; }
    .stTabs [data-baseweb="tab-list"] { gap: 0.25rem; }
    .stTabs [data-baseweb="tab"] { border-radius: 10px 10px 0 0; padding: 0.4rem 0.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def money(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value):,.0f} zł".replace(",", " ")


def money2(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value):,.2f} zł".replace(",", " ")


def pct(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{100 * float(value):.1f}%"


def num(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{int(round(float(value))):,}".replace(",", " ")


def card(label: str, value: str, hint: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="label">{label}</div>'
        f'<div class="value">{value}</div><div class="hint">{hint}</div></div>',
        unsafe_allow_html=True,
    )


def chart(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=8, r=8, t=48, b=8),
        font=dict(family="Source Sans 3, Segoe UI, sans-serif", size=13, color="#1c2b33"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        colorway=COLORS,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#e6eeef")
    return fig


def filters_from_sidebar() -> Filters:
    dim = dimensions()
    base = default_filters()
    st.sidebar.header("Filtry")
    date_range = st.sidebar.date_input(
        "Data",
        value=(base.date_min, base.date_max),
        min_value=base.date_min,
        max_value=base.date_max,
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        date_from, date_to = date_range
    else:
        date_from, date_to = base.date_min, base.date_max
    # Jedna pozycja zamiast wielu zaznaczonych etykiet. "Wszystkie" jest
    # reprezentowane pełną listą, aby zachować dotychczasowe zapytania SQL.
    def single_filter(label: str, values: list[str]) -> tuple[str, ...]:
        selected = st.sidebar.selectbox(label, ["Wszystkie"] + list(values))
        return tuple(values) if selected == "Wszystkie" else (selected,)

    devices = single_filter("Urządzenie", dim["devices"])
    channels = single_filter("Kanał", dim["channels"])
    campaigns = single_filter("Kampania", dim["campaigns"])
    with st.sidebar.expander("Jak działają filtry?"):
        st.caption(
            "Urządzenie filtruje sesje i zakupy, ale nie kohorty pozyskania ani wydatki reklamowe. "
            "Kanał i kampania dla kohort używają atrybucji last non-direct, a dla zakupów "
            "źródła sesji zakupu. Definicje, anomalie i wnioski mają własne zakresy."
        )
    return Filters(
        date_from=date_from,
        date_to=date_to,
        devices=tuple(devices),
        channels=tuple(channels),
        campaigns=tuple(campaigns),
        all_devices=tuple(dim["devices"]),
        all_channels=tuple(dim["channels"]),
        all_campaigns=tuple(dim["campaigns"]),
        date_min=dim["date_min"],
        date_max=dim["date_max"],
    )


def scope_note(filters: Filters) -> None:
    if filters.full_window:
        published = headlines()
        st.caption(
            "Pełne okno analizy, 1 października 2024 – 30 września 2026. "
            f"Pacjenci komercyjni {num(published['commercial_patients'])}, "
            f"przychód netto {money2(published['commercial_net'])}."
        )
    else:
        bits = []
        if filters.date_narrowed:
            bits.append("daty")
        if filters.device_narrowed:
            bits.append("urządzenia")
        if filters.channel_narrowed:
            bits.append("kanału")
        if filters.campaign_narrowed:
            bits.append("kampanii")
        st.caption("Widok ograniczony filtrem: " + ", ".join(bits) + ". Liczby poniżej nie są nagłówkiem pełnego okna.")


def page_overview(filters: Filters) -> None:
    scope_note(filters)
    totals = overview(filters)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card(
            "Pacjenci komercyjni",
            num(totals["patients"]) if totals["patients"] is not None else "—",
            "Pierwsze zamówienie bez TEST-QA" if totals["patients"] is not None else "Brak wymiaru urządzenia",
        )
    with c2:
        card("Przychód netto", money(totals["net"]), "Zamówienia komercyjne w filtrze")
    with c3:
        card(
            "Kontrybucja przed marketingiem",
            money(totals["contribution_before_marketing"]),
            "Netto − lekarz + opłata GO",
        )
    with c4:
        card(
            "Wynik po marketingu",
            money(totals["contribution_after_marketing"]),
            "Po odjęciu mediów i afiliacji LND" if totals["marketing_available"] else "Koszt mediowy nie ma wymiaru urządzenia",
        )
    if not totals["marketing_available"]:
        st.info(
            "Filtr urządzenia działa na sesje, zamówienia i opłatę GO. "
            "Spend i prowizja afiliacyjna zostają poza tym wynikiem, więc wynik po marketingu nie jest tu liczony."
        )

    if filters.full_window:
        st.markdown("### Co powinien zrobić Head of B2C?")
        a, b, c = st.columns(3)
        with a:
            st.info("**1. Odbudować retencję**\n\nRepeat D90: 20,9% w dojrzałych kohortach; "
                    "trend spadkowy. Testować powroty po pierwszej konsultacji.")
        with b:
            st.info("**2. Poprawić efektywność pozyskania**\n\nOddzielić prospecting "
                    "od brandu i remarketingu. Weryfikować przyrostowość holdoutem.")
        with c:
            st.info("**3. Uszczelnić unit economics**\n\nSprawdzić ujemną "
                    "kontrybucję pediatrii i psychologii oraz kod TEST-QA.")
    else:
        st.caption("Priorytety strategiczne pokazujemy dla pełnego zakresu. Poniżej widok przefiltrowany.")

    series = daily_series(filters)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=series["date"], y=series["contribution"],
        name="Kontrybucja przed marketingiem", line=dict(color=COLORS[0], width=2),
    ))
    if "contribution_after_acquisition_cost" in series.columns:
        fig.add_trace(go.Scatter(
            x=series["date"], y=series["contribution_after_acquisition_cost"],
            name="Wynik po marketingu", line=dict(color=COLORS[1], width=2),
        ))
    chart(fig)
    fig.update_layout(title="Kontrybucja dzienna", yaxis_title="zł")
    st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)
    with left:
        fig2 = go.Figure()
        conversion = series["commercial_purchases"] / series["sessions"].replace(0, float("nan"))
        fig2.add_trace(go.Scatter(
            x=series["date"], y=series["sessions"], name="Sesje",
            line=dict(color=COLORS[2], width=1.7),
        ))
        fig2.add_trace(go.Scatter(
            x=series["date"], y=conversion, name="Zakupy / sesje",
            line=dict(color=COLORS[0], width=2), yaxis="y2",
        ))
        chart(fig2, 340)
        fig2.update_layout(
            title="Ruch i konwersja sesji do zakupu", yaxis_title="Sesje",
            yaxis2=dict(title="Zakupy / sesje", overlaying="y", side="right", tickformat=".0%", showgrid=False),
        )
        st.plotly_chart(fig2, use_container_width=True)
    with right:
        spec = specialization(filters)
        fig3 = go.Figure(go.Bar(
            x=spec["contribution"], y=spec["specialization"], orientation="h",
            marker_color=[COLORS[3] if value < 0 else COLORS[0] for value in spec["contribution"]],
            customdata=spec["contribution"], hovertemplate="%{y}: %{x:,.0f} zł<extra></extra>",
        ))
        chart(fig3, 340)
        fig3.update_layout(title="Kontrybucja zamówień według specjalizacji", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("Specjalizacja jest znana przy zamówieniu. Sesje bez zakupu nie dostają specjalizacji.")


def page_definitions() -> None:
    st.caption("Definicje są policzone na pełnym oknie. Filtry boczne ich nie przeliczają.")
    milestones = static_table("definition_milestones.parquet").iloc[0]
    compare = static_table("definition_comparison.parquet").iloc[0]
    timing = static_table("visit_timing.parquet").iloc[0]
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Pacjent komercyjny", num(milestones["commercial_patients"]), "Pierwsze zamówienie bez TEST-QA")
    with c2:
        card("Wizyta odbyta", num(milestones["patients_with_occurred_visit"]), "Status completed albo refunded, data started_at")
    with c3:
        card("Ukończona i niezwrócona", num(milestones["patients_with_kept_completed"]), "Wyłącznie status completed")
    st.markdown(
        "Wizyta odbyta i wizyta ukończona to dwa kamienie. Zwrot oznacza, że wizyta się odbyła, "
        "przychód netto wynosi zero, a koszt lekarza zostaje. Data odbycia to `started_at`, nie data płatności."
    )
    rows = pd.DataFrame([
        {"Kamień": "Pierwsza odbyta wizyta jest zwrotem", "Pacjenci": int(milestones["first_occurred_is_refunded"])},
        {"Kamień": "Odbył wizytę i nie ma statusu completed", "Pacjenci": int(milestones["occurred_but_never_kept"])},
        {"Kamień": "Ukończenie późniejsze niż pierwsza odbyta wizyta", "Pacjenci": int(milestones["kept_later_than_first_occurred"])},
        {"Kamień": "Start w innym dniu niż płatność", "Pacjenci": int(milestones["first_occurred_on_later_day"])},
        {"Kamień": "Data kohorty przesuwa się po wyłączeniu TEST-QA", "Pacjenci": int(compare["commercial_new_previously_counted_as_returning"])},
    ])
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption(
        f"Mediana od płatności do startu: {float(timing['p50_min_after_payment']):.0f} min. "
        f"W {int(timing['start_date_differs_from_payment'])} wizytach data startu różni się od daty płatności. "
        f"Przychód na 18 przeniesionych pierwszych zamówieniach: {money2(compare['net_on_reclassified_first_orders'])}."
    )


def page_cohorts(filters: Filters) -> None:
    scope_note(filters)
    if filters.device_narrowed:
        st.info("Kohorta pozyskania nie ma wymiaru urządzenia. Powtórny zakup poniżej respektuje datę, kanał i kampanię last non-direct.")
    row = retention(filters)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Repeat purchase within 30 days", pct(row["repeat_purchase_within_30_days"]), f"Mianownik {num(row['n_d30'])} dojrzałych pacjentów")
    with c2:
        card("Repeat purchase within 90 days", pct(row["repeat_purchase_within_90_days"]), f"Mianownik {num(row['n_d90'])}")
    with c3:
        card("LTV netto do 90 dni", money(row["ltv_net_d90"]), "Tylko kohorty, które zdążyły dojrzeć")
    with c4:
        card("Kontrybucja do 90 dni", money(row["contribution_per_patient_d90"]), "Przed kosztem mediowym i afiliacji")
    monthly = cohort_monthly(filters)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=monthly["cohort_month"], y=monthly["repeat_purchase_within_30_days"],
        name="Repeat purchase within 30 days", line=dict(color=COLORS[2], width=2),
    ))
    fig.add_trace(go.Scatter(
        x=monthly["cohort_month"], y=monthly["repeat_purchase_within_90_days"],
        name="Repeat purchase within 90 days", line=dict(color=COLORS[0], width=2),
    ))
    chart(fig)
    fig.update_layout(title="Repeat purchase within N days według miesiąca kohorty", yaxis_tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)
    show = monthly.copy()
    show["cohort_month"] = show["cohort_month"].dt.strftime("%Y-%m")
    show["Repeat purchase within 30 days"] = show["repeat_purchase_within_30_days"].map(pct)
    show["Repeat purchase within 90 days"] = show["repeat_purchase_within_90_days"].map(pct)
    show["Kontrybucja D90 na pacjenta"] = show["contribution_per_patient_d90"].map(
        lambda value: "—" if pd.isna(value) else f"{value:.0f}"
    )
    st.dataframe(
        show[[
            "cohort_month", "patients", "n_d30", "n_d90",
            "Repeat purchase within 30 days", "Repeat purchase within 90 days",
            "Kontrybucja D90 na pacjenta",
        ]],
        hide_index=True, use_container_width=True,
    )
    st.caption(
        "Repeat purchase within N days to kolejne zamówienie komercyjne dowolnego statusu w N dniach od pierwszego zakupu. "
        f"Zalogowana sesja w 90 dniach: {pct(row['session_within_90_days'])}. "
        "To osobna miara aktywności, nie powtórny zakup. Świeże kohorty są wyłączone z mianownika."
    )
    go_impact = static_table("go_impact.parquet")
    st.subheader("TelemediGO")
    st.caption("Podział obserwacyjny na pełnym oknie. Filtr boczny go nie przelicza. Grupa, która kupuje GO później, jest już grupą wracającą.")
    labels = go_impact.apply(
        lambda r: "GO przy pierwszym zamówieniu" if r["go_on_first_order"] else ("GO później" if r["ever_go"] else "Nigdy GO"),
        axis=1,
    )
    figg = go.Figure(go.Bar(x=labels, y=go_impact["contribution_d90"], marker_color=COLORS[0]))
    chart(figg, 320)
    figg.update_layout(title="Kontrybucja D90 na pacjenta według relacji z GO", yaxis_title="zł")
    st.plotly_chart(figg, use_container_width=True)


def page_funnel(filters: Filters) -> None:
    scope_note(filters)
    totals = overview(filters)
    stages = ["Sesja", "Wybór usługi", "Wybór slotu", "Start płatności", "Zakup komercyjny"]
    values = [
        totals["sessions"], totals["service_selected"], totals["slot_selected"],
        totals["payment_started"], totals["commercial_purchase"],
    ]
    fig = go.Figure(go.Funnel(y=stages, x=values, marker={"color": COLORS[:5]}, textinfo="value+percent initial"))
    chart(fig, 420)
    fig.update_layout(title="Lejek sesyjny")
    st.plotly_chart(fig, use_container_width=True)
    st.subheader("Lejek intencji zakupowej")
    intent_values = values[1:]
    intent_fig = go.Figure(go.Funnel(
        y=stages[1:], x=intent_values,
        marker={"color": COLORS[1:5]}, textinfo="value+percent initial",
    ))
    chart(intent_fig, 340)
    intent_fig.update_layout(title="Od wyboru usługi do zakupu")
    st.plotly_chart(intent_fig, use_container_width=True)
    dim = st.radio(
        "Przekrój",
        ["device", "channel", "campaign", "landing_page"],
        horizontal=True,
        format_func=lambda item: {
            "device": "Urządzenie", "channel": "Kanał sesji",
            "campaign": "Kampania sesji", "landing_page": "Landing",
        }[item],
    )
    detail = funnel_breakdown(filters, dim)
    detail["wejście w usługę"] = detail["service_selected"] / detail["sessions"].where(detail["sessions"] > 0)
    detail["zakup / sesja"] = detail["commercial_purchase"] / detail["sessions"].where(detail["sessions"] > 0)
    fig2 = go.Figure(go.Bar(
        x=detail["segment"], y=detail["wejście w usługę"],
        marker_color=COLORS[2], name="Wybór usługi / sesja",
    ))
    chart(fig2, 340)
    fig2.update_layout(title="Wejście w usługę", yaxis_tickformat=".0%", xaxis_tickangle=-30)
    st.plotly_chart(fig2, use_container_width=True)
    view = detail[["segment", "sessions", "service_selected", "commercial_purchase", "go_only"]].copy()
    view["wejście w usługę"] = detail["wejście w usługę"].map(pct)
    view["zakup / sesja"] = detail["zakup / sesja"].map(pct)
    st.dataframe(view, hide_index=True, use_container_width=True)
    st.caption(
        "Konwersja sesji miesza nowych i wracających. Landing /konto opisuje osoby już w produkcie. "
        "Samodzielne GO są osobną ścieżką email, nie etapem lejka konsultacji. "
        f"W tym filtrze sesji go_only: {num(totals['go_only'])}."
    )


def page_marketing(filters: Filters) -> None:
    scope_note(filters)
    if filters.device_narrowed:
        st.info("Koszt mediowy i atrybucja last non-direct nie mają wymiaru urządzenia. Wyczyść filtr urządzenia, żeby zobaczyć ekonomię kanałów.")
        return
    totals = overview(filters)
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Kontrybucja przed marketingiem", money(totals["contribution_before_marketing"]), "Netto − lekarz + GO")
    with c2:
        card(
            "Koszt mediowy + afiliacja LND",
            money((totals["media_spend"] or 0) + (totals["affiliate_cost"] or 0)),
            "Afiliacja 25 zł raz, model LND",
        )
    with c3:
        card("Wynik po marketingu", money(totals["contribution_after_marketing"]), "Rozliczenie atrybucji, nie wpływ przyczynowy")
    st.markdown("### Kanały pozyskania — porównanie dojrzałych kohort")
    st.caption(
        "Kontrybucja D90 i wydatki są przypisane do tego samego okresu dat pozyskania "
        "(tylko kohorty z pełnymi 90 dniami obserwacji). To analiza atrybucyjna, "
        "nie dowód inkrementalnego zwrotu z reklamy."
    )
    matched = matched_d90_spend(filters, "channel")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=matched["segment"], y=matched["contribution_d90"],
                         name="Kontrybucja D90", marker_color=COLORS[0]))
    fig.add_trace(go.Bar(x=matched["segment"], y=matched["acquisition_cost"],
                         name="Media + afiliacja", marker_color=COLORS[1]))
    chart(fig)
    fig.update_layout(title="Kontrybucja D90 i koszt w zgodnym oknie pozyskania",
                      barmode="group", yaxis_title="zł")
    st.plotly_chart(fig, use_container_width=True)
    channels = channel_economics(filters)
    st.markdown("#### Rozliczenie kanałów — cały wybrany okres")
    show = channels.copy()
    show["Repeat purchase within 90 days"] = show["repeat_purchase_within_90_days"].map(pct)
    show["Kontrybucja przed marketingiem, całe okno"] = show["contribution_unbounded"].map(money)
    show["Wynik po marketingu"] = show["contribution_after_marketing"].map(money)
    st.dataframe(
        show[[
            "channel", "new_patients", "media_spend", "affiliate_cost",
            "Repeat purchase within 90 days",
            "Kontrybucja przed marketingiem, całe okno", "Wynik po marketingu",
        ]],
        hide_index=True, use_container_width=True,
    )
    st.caption(
        "Wynik po marketingu odejmuje cały spend kanału od kontrybucji pacjentów przypisanych last non-direct. "
        "Brand i remarketing mogą podpisywać popyt, który i tak by przyszedł."
    )
    st.markdown("#### Kampanie płatne — zgodne okno D90")
    campaign_matched = matched_d90_spend(filters, "campaign")
    paid = campaign_matched[campaign_matched["media_spend"] > 0].sort_values(
        "media_spend", ascending=False
    ).head(12)
    fig2 = go.Figure(go.Bar(
        x=paid["segment"], y=paid["contribution_d90"] - paid["acquisition_cost"],
        marker_color=[COLORS[3] if x < 0 else COLORS[0]
                      for x in paid["contribution_d90"] - paid["acquisition_cost"]],
    ))
    chart(fig2, 340)
    fig2.update_layout(title="Kontrybucja D90 minus koszt kampanii (atrybucja)",
                       yaxis_title="zł", xaxis_tickangle=-30)
    st.plotly_chart(fig2, use_container_width=True)
    sensitivity = static_table("attribution_sensitivity.parquet").iloc[0]
    st.caption(
        f"Wrażliwość afiliacji na pełnym oknie: last non-direct {int(sensitivity['affiliate_lnd'])} pacjentów, "
        f"sesja konwersji {int(sensitivity['affiliate_conversion_session'])}. "
        "Koszt 24 600 zł albo 21 050 zł. Te kwoty są alternatywą. Wynik po marketingu używa modelu last non-direct."
    )


def page_anomalies(filters: Filters) -> None:
    st.caption(
        "Detektor porównuje dzień z medianą poprzednich ośmiu takich samych dni tygodnia. "
        "Filtr daty zawęża listę. Urządzenie, kanał i kampania nie są wymiarem tej tabeli."
    )
    if filters.device_narrowed or filters.channel_narrowed or filters.campaign_narrowed:
        st.info("Lista anomalii nie rozcina się na urządzenie, kanał ani kampanię. Zostawiam te filtry bez wpływu na tabelę.")
    frame = anomalies(filters)
    label = {
        "sessions": "Sesje",
        "intent_sessions": "Sesje z intencją",
        "commercial_purchases": "Zakupy",
        "new_patients": "Nowi pacjenci",
        "net": "Przychód netto",
        "contribution": "Kontrybucja przed marketingiem",
        "go_only": "Sesje samodzielnego GO",
    }
    if frame.empty:
        st.write("W tym zakresie dat detektor nie zgłosił dni.")
    else:
        view = frame.copy()
        view["data"] = view["date"].dt.strftime("%Y-%m-%d")
        view["metryka"] = view["metric"].map(lambda item: label.get(item, item))
        view["zmiana"] = view["pct_vs_baseline"].map(lambda value: f"{100 * float(value):.0f}%")
        st.dataframe(
            view[["data", "metryka", "value", "baseline", "zmiana", "robust_z"]],
            hide_index=True, use_container_width=True,
        )
    weekly = anomalies_weekly()
    st.subheader("Tygodnie")
    st.dataframe(weekly, hide_index=True, use_container_width=True)
    st.markdown("**Jak czytać wyjątki**")
    st.markdown(
        "- 24 grudnia, 1 maja i 3 maja pokrywają się z dniami wolnymi. To hipoteza kalendarza, zgodna z datą.\n"
        "- Tydzień od 28 września 2026 ma w oknie tylko trzy dni. Spadek o połowę jest artefaktem uciętego tygodnia.\n"
        "- Wzrost sesji w tygodniach od 3 i 10 listopada 2025 pokrywa się ze startem kampanii L4. To zbieżność, nie dowód przyczynowy."
    )
    st.subheader("Anomalia do sprawdzenia: kod TEST-QA")
    testqa = static_table("order_day.parquet")
    testqa = testqa[testqa["is_test_qa"] == True]  # noqa: E712
    net = float(testqa["net"].sum())
    doctor = float(testqa["doctor"].sum())
    orders = int(testqa["orders"].sum())
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Zamówienia z kodem", num(orders), "Poza KPI komercyjnym")
    with c2:
        card("Przychód netto kodu", money2(net), "Obserwacja, nie diagnoza")
    with c3:
        card("Koszt lekarza kodu", money(doctor), "Stawka z założeń README")
    st.markdown(
        "Kod rabatowy TEST-QA skupia ukończone wizyty, przy których koszt lekarza jest wielokrotnie wyższy od przychodu. "
        "To jest anomalia do sprawdzenia operacyjnego: czy kod jest testem, kontem wewnętrznym, czy błędem procesu. "
        "Same tabele nie rozstrzygają przyczyny. Kod jest wyłączony z pacjentów, kohort i kontrybucji komercyjnej. "
        "Wyłączenie kodu przesuwa datę pozyskania 18 osób i nie zmienia liczby pacjentów komercyjnych."
    )


def page_conclusions() -> None:
    st.caption("Skrót wniosków z docs/business_analysis.md i docs/recommendations.md. Pełne okno, bez przeliczania filtrów.")
    points = [
        "40 940 pacjentów komercyjnych, 5 458 608,90 zł netto, kontrybucja przed marketingiem 2 917 036,90 zł.",
        "Wynik po marketingu na pełnym oknie to 1 875 129,59 zł po odjęciu 1 017 307,31 zł mediów i 24 600 zł afiliacji last non-direct. To rozliczenie atrybucji.",
        "Repeat purchase within 90 days wynosi 20,9% dojrzałych kohort. Od listopada 2025 kohorty, które zdążyły dojrzeć, mają słabszy powrót i niższą kontrybucję.",
        "Internista daje około 91% kontrybucji zamówień. Pediatra i psycholog są ujemne przy cenniku poniżej stawki lekarza.",
        "Największy ubytek lejka jest przed wyborem usługi. Z osób przy płatności około 89% kupuje.",
        "TikTok L4 i Meta L4 w oknie dojrzałym nie dają nadwyżki przypisanej kontrybucji D90 nad spendem. Brand i remarketing wyglądają nadwyżkowo, bo mogą łapać istniejący popyt.",
        "GO przy pierwszym zamówieniu podnosi kontrybucję o rząd opłaty. Osoby, które kupują GO później, już wracają.",
        "TEST-QA to anomalia do sprawdzenia, nie rozstrzygnięta przyczyna. Luka kosztu lekarza nad przychodem na wizytach z kodem wynosi 42 744 zł w 24 miesiącach.",
    ]
    for index, point in enumerate(points, start=1):
        st.markdown(f"**{index}.** {point}")
    st.subheader("Plan działania Head of B2C — pierwsze 90 dni")
    plan = pd.DataFrame([
        {"Horyzont": "0–30 dni", "Priorytet": "Zdiagnozować spadek retencji D90", "KPI": "Repeat D30/D90, kontrybucja D90", "Decyzja / test": "Segmentacja kohort i hipotezy powrotu"},
        {"Horyzont": "0–30 dni", "Priorytet": "Rozdzielić prospecting, brand i remarketing", "KPI": "Spend, nowi pacjenci LND, CAC", "Decyzja / test": "Nowy raport i definicje atrybucji"},
        {"Horyzont": "0–30 dni", "Priorytet": "Zweryfikować kod TEST-QA", "KPI": "Wizyty i koszt lekarza z kodem", "Decyzja / test": "Audyt operacyjny; nie przesądzać przyczyny"},
        {"Horyzont": "31–60 dni", "Priorytet": "Zwiększyć wejścia w usługę na mobile", "KPI": "Service selection / sesje mobile", "Decyzja / test": "A/B ścieżki i landingów"},
        {"Horyzont": "31–60 dni", "Priorytet": "Przetestować unit economics specjalizacji", "KPI": "Kontrybucja na ukończoną wizytę", "Decyzja / test": "Test ceny pediatrii / psychologii"},
        {"Horyzont": "31–60 dni", "Priorytet": "Sprawdzić przyrostowość kampanii L4", "KPI": "Nowi pacjenci, kontrybucja w holdoucie", "Decyzja / test": "Kontrolowany holdout; bez automatycznych cięć"},
        {"Horyzont": "61–90 dni", "Priorytet": "Uruchomić eksperyment powrotu pacjentów", "KPI": "Repeat D30; D90 po dojrzeniu", "Decyzja / test": "Randomizowany test CRM z grupą kontrolną"},
        {"Horyzont": "61–90 dni", "Priorytet": "Sprawdzić ofertę GO przy pierwszym zakupie", "KPI": "Kontrybucja D90 na pacjenta", "Decyzja / test": "A/B checkoutu; nie wnioskować z korelacji"},
    ])
    st.dataframe(plan, hide_index=True, use_container_width=True)
    st.caption("Terminy oznaczają start prac lub testów. Wynik D90 jest dostępny dopiero po dojrzeniu kohort.")
    st.caption("Żadna kwota z testu nie jest wpisana z góry. Metody szacunku są w docs/recommendations.md. Czego dane nie rozstrzygają: docs/limitations.md.")


def main() -> None:
    st.markdown(
        '<div class="fictional"><strong>Zbiór fikcyjny.</strong> '
        "Aplikacja opisuje symulację B2C na potrzeby zadania analitycznego. "
        "Nie pokazuje prawdziwych pacjentów, wizyt ani identyfikatorów.</div>",
        unsafe_allow_html=True,
    )
    st.title("Telemedi B2C | Growth & Profitability")
    st.write("Dashboard zarządczy: wzrost, retencja, lejek i rentowność. Dane syntetyczne, 2024–2026.")
    filters = filters_from_sidebar()
    overview_tab, definitions_tab, cohorts_tab, funnel_tab, marketing_tab, anomaly_tab, conclusions_tab = st.tabs(
        ["Przegląd", "Definicje", "Kohorty", "Lejek", "Marketing", "Anomalie", "Wnioski"]
    )
    with overview_tab:
        page_overview(filters)
    with definitions_tab:
        page_definitions()
    with cohorts_tab:
        page_cohorts(filters)
    with funnel_tab:
        page_funnel(filters)
    with marketing_tab:
        page_marketing(filters)
    with anomaly_tab:
        page_anomalies(filters)
    with conclusions_tab:
        page_conclusions()


main()
