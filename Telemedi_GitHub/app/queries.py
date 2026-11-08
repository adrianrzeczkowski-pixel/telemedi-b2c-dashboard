"""Aggregated queries for the public dashboard. No patient identifiers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
PAID_CHANNELS = ("google_cpc", "meta_paid", "tiktok_paid")


def _path(name: str) -> str:
    return (DATA / name).as_posix()


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    return con


def _table(name: str) -> pd.DataFrame:
    con = connect()
    frame = con.execute(f"SELECT * FROM read_parquet('{_path(name)}')").fetchdf()
    con.close()
    return frame


def headlines() -> dict:
    return json.loads((DATA / "headlines.json").read_text(encoding="utf-8"))


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


@dataclass
class Filters:
    date_from: date
    date_to: date
    devices: tuple[str, ...]
    channels: tuple[str, ...]
    campaigns: tuple[str, ...]
    all_devices: tuple[str, ...]
    all_channels: tuple[str, ...]
    all_campaigns: tuple[str, ...]
    date_min: date
    date_max: date

    @property
    def device_narrowed(self) -> bool:
        return set(self.devices) != set(self.all_devices)

    @property
    def channel_narrowed(self) -> bool:
        return set(self.channels) != set(self.all_channels)

    @property
    def campaign_narrowed(self) -> bool:
        return set(self.campaigns) != set(self.all_campaigns)

    @property
    def date_narrowed(self) -> bool:
        return self.date_from != self.date_min or self.date_to != self.date_max

    @property
    def full_window(self) -> bool:
        return not any(
            (self.date_narrowed, self.device_narrowed, self.channel_narrowed, self.campaign_narrowed)
        )


def dimensions() -> dict:
    con = connect()
    devices = con.execute(
        f"SELECT DISTINCT device FROM read_parquet('{_path('session_day.parquet')}') ORDER BY 1"
    ).fetchdf()["device"].tolist()
    channels = con.execute(
        f"""
        SELECT DISTINCT channel FROM (
            SELECT channel FROM read_parquet('{_path('session_day.parquet')}')
            UNION
            SELECT channel FROM read_parquet('{_path('cohort_day.parquet')}')
            UNION
            SELECT channel FROM read_parquet('{_path('spend_day.parquet')}')
        )
        ORDER BY 1
        """
    ).fetchdf()["channel"].tolist()
    campaigns = con.execute(
        f"""
        SELECT DISTINCT campaign FROM (
            SELECT campaign FROM read_parquet('{_path('session_day.parquet')}')
            UNION
            SELECT campaign FROM read_parquet('{_path('cohort_day.parquet')}')
            UNION
            SELECT campaign FROM read_parquet('{_path('spend_day.parquet')}')
        )
        ORDER BY 1
        """
    ).fetchdf()["campaign"].tolist()
    bounds = con.execute(
        f"SELECT min(date), max(date) FROM read_parquet('{_path('daily_kpi.parquet')}')"
    ).fetchone()
    con.close()
    return {
        "devices": devices,
        "channels": channels,
        "campaigns": campaigns,
        "date_min": _as_date(bounds[0]),
        "date_max": _as_date(bounds[1]),
    }


def default_filters() -> Filters:
    dim = dimensions()
    return Filters(
        date_from=dim["date_min"],
        date_to=dim["date_max"],
        devices=tuple(dim["devices"]),
        channels=tuple(dim["channels"]),
        campaigns=tuple(dim["campaigns"]),
        all_devices=tuple(dim["devices"]),
        all_channels=tuple(dim["channels"]),
        all_campaigns=tuple(dim["campaigns"]),
        date_min=dim["date_min"],
        date_max=dim["date_max"],
    )


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _where(filters: Filters, *, device: bool, channel: bool, campaign: bool, testqa: bool | None = None) -> str:
    parts = [
        f"date >= DATE '{filters.date_from.isoformat()}'",
        f"date <= DATE '{filters.date_to.isoformat()}'",
    ]
    if device and filters.device_narrowed:
        parts.append(f"device IN ({_sql_list(filters.devices)})")
    if channel and filters.channel_narrowed:
        parts.append(f"channel IN ({_sql_list(filters.channels)})")
    if campaign and filters.campaign_narrowed:
        parts.append(f"campaign IN ({_sql_list(filters.campaigns)})")
    if testqa is True:
        parts.append("is_test_qa")
    elif testqa is False:
        parts.append("NOT is_test_qa")
    return " AND ".join(parts)


def _one(query: str) -> dict:
    con = connect()
    frame = con.execute(query).fetchdf()
    con.close()
    if frame.empty:
        return {}
    row = frame.iloc[0].to_dict()
    return {key: (None if pd.isna(value) else value) for key, value in row.items()}


def overview(filters: Filters) -> dict:
    sessions = _one(
        f"""
        SELECT
            coalesce(sum(sessions), 0) AS sessions,
            coalesce(sum(service_selected), 0) AS service_selected,
            coalesce(sum(slot_selected), 0) AS slot_selected,
            coalesce(sum(payment_started), 0) AS payment_started,
            coalesce(sum(commercial_purchase), 0) AS commercial_purchase,
            coalesce(sum(go_only), 0) AS go_only,
            coalesce(sum(browse_only), 0) AS browse_only,
            coalesce(sum(testqa_purchase), 0) AS testqa_purchase
        FROM read_parquet('{_path('session_day.parquet')}')
        WHERE {_where(filters, device=True, channel=True, campaign=True)}
        """
    )
    orders = _one(
        f"""
        SELECT
            coalesce(sum(orders), 0) AS orders,
            coalesce(sum(net), 0) AS net,
            coalesce(sum(doctor), 0) AS doctor,
            coalesce(sum(order_contribution), 0) AS order_contribution
        FROM read_parquet('{_path('order_day.parquet')}')
        WHERE {_where(filters, device=True, channel=True, campaign=True, testqa=False)}
        """
    )
    go = _one(
        f"""
        SELECT coalesce(sum(go_fee), 0) AS go_fee, coalesce(sum(memberships), 0) AS memberships
        FROM read_parquet('{_path('go_day.parquet')}')
        WHERE {_where(filters, device=True, channel=True, campaign=True)}
        """
    )
    marketing_available = not filters.device_narrowed
    spend = {"media_spend": 0, "clicks": 0}
    patients = {"patients": 0, "affiliate_patients": 0}
    if marketing_available:
        spend = _one(
            f"""
            SELECT coalesce(sum(media_spend), 0) AS media_spend, coalesce(sum(clicks), 0) AS clicks
            FROM read_parquet('{_path('spend_day.parquet')}')
            WHERE {_where(filters, device=False, channel=True, campaign=True)}
            """
        )
        patients = _one(
            f"""
            SELECT
                coalesce(sum(patients), 0) AS patients,
                coalesce(sum(affiliate_patients), 0) AS affiliate_patients
            FROM read_parquet('{_path('cohort_day.parquet')}')
            WHERE {_where(filters, device=False, channel=True, campaign=True)}
            """
        )
    contribution_before = float(orders["order_contribution"]) + float(go["go_fee"])
    affiliate_cost = 25.0 * float(patients["affiliate_patients"]) if marketing_available else None
    contribution_after = None
    if marketing_available:
        contribution_after = contribution_before - float(spend["media_spend"]) - affiliate_cost
    return {
        **sessions,
        **orders,
        **go,
        "patients": patients["patients"] if marketing_available else None,
        "media_spend": spend["media_spend"] if marketing_available else None,
        "affiliate_cost": affiliate_cost,
        "contribution_before_marketing": contribution_before,
        "contribution_after_marketing": contribution_after,
        "marketing_available": marketing_available,
    }


def daily_series(filters: Filters) -> pd.DataFrame:
    con = connect()
    device_clause = ""
    if filters.device_narrowed:
        device_clause = f"AND device IN ({_sql_list(filters.devices)})"
    channel_clause = ""
    if filters.channel_narrowed:
        channel_clause = f"AND channel IN ({_sql_list(filters.channels)})"
    campaign_clause = ""
    if filters.campaign_narrowed:
        campaign_clause = f"AND campaign IN ({_sql_list(filters.campaigns)})"
    marketing_sql = "NULL::DOUBLE"
    affiliate_sql = "NULL::DOUBLE"
    patients_sql = "NULL::BIGINT"
    if not filters.device_narrowed:
        marketing_sql = "m.media_spend"
        affiliate_sql = "a.affiliate_cost"
        patients_sql = "n.patients"
    frame = con.execute(
        f"""
        WITH days AS (
            SELECT date FROM read_parquet('{_path('daily_kpi.parquet')}')
            WHERE date >= DATE '{filters.date_from.isoformat()}'
              AND date <= DATE '{filters.date_to.isoformat()}'
        ),
        sessions AS (
            SELECT date,
                sum(sessions) AS sessions,
                sum(service_selected) AS intent_sessions,
                sum(commercial_purchase) AS commercial_purchases
            FROM read_parquet('{_path('session_day.parquet')}')
            WHERE date >= DATE '{filters.date_from.isoformat()}'
              AND date <= DATE '{filters.date_to.isoformat()}'
              {device_clause} {channel_clause} {campaign_clause}
            GROUP BY 1
        ),
        orders AS (
            SELECT date, sum(orders) AS commercial_orders, sum(net) AS net,
                   sum(doctor) AS doctor, sum(order_contribution) AS order_contribution
            FROM read_parquet('{_path('order_day.parquet')}')
            WHERE NOT is_test_qa
              AND date >= DATE '{filters.date_from.isoformat()}'
              AND date <= DATE '{filters.date_to.isoformat()}'
              {device_clause} {channel_clause} {campaign_clause}
            GROUP BY 1
        ),
        go AS (
            SELECT date, sum(go_fee) AS go_fee
            FROM read_parquet('{_path('go_day.parquet')}')
            WHERE date >= DATE '{filters.date_from.isoformat()}'
              AND date <= DATE '{filters.date_to.isoformat()}'
              {device_clause} {channel_clause} {campaign_clause}
            GROUP BY 1
        ),
        media AS (
            SELECT date, sum(media_spend) AS media_spend
            FROM read_parquet('{_path('spend_day.parquet')}')
            WHERE date >= DATE '{filters.date_from.isoformat()}'
              AND date <= DATE '{filters.date_to.isoformat()}'
              {channel_clause} {campaign_clause}
            GROUP BY 1
        ),
        newp AS (
            SELECT date, sum(patients) AS patients, 25 * sum(affiliate_patients) AS affiliate_cost
            FROM read_parquet('{_path('cohort_day.parquet')}')
            WHERE date >= DATE '{filters.date_from.isoformat()}'
              AND date <= DATE '{filters.date_to.isoformat()}'
              {channel_clause} {campaign_clause}
            GROUP BY 1
        )
        SELECT
            d.date,
            coalesce(s.sessions, 0) AS sessions,
            coalesce(s.intent_sessions, 0) AS intent_sessions,
            coalesce(s.commercial_purchases, 0) AS commercial_purchases,
            coalesce(o.commercial_orders, 0) AS commercial_orders,
            coalesce(o.net, 0) AS net,
            coalesce(o.order_contribution, 0) AS order_contribution,
            coalesce(g.go_fee, 0) AS go_fee,
            {patients_sql} AS new_patients,
            {marketing_sql} AS media_spend,
            {affiliate_sql} AS affiliate_cost,
            coalesce(o.order_contribution, 0) + coalesce(g.go_fee, 0) AS contribution
        FROM days d
        LEFT JOIN sessions s ON s.date = d.date
        LEFT JOIN orders o ON o.date = d.date
        LEFT JOIN go g ON g.date = d.date
        LEFT JOIN media m ON m.date = d.date
        LEFT JOIN newp a ON a.date = d.date
        LEFT JOIN newp n ON n.date = d.date
        ORDER BY d.date
        """
    ).fetchdf()
    con.close()
    frame["date"] = pd.to_datetime(frame["date"])
    if not filters.device_narrowed:
        frame["contribution_after_acquisition_cost"] = (
            frame["contribution"].fillna(0)
            - frame["media_spend"].fillna(0)
            - frame["affiliate_cost"].fillna(0)
        )
    return frame


def retention(filters: Filters) -> dict:
    """Repeat purchase within N days. Device is not a cohort dimension."""
    row = _one(
        f"""
        SELECT
            coalesce(sum(patients), 0) AS patients,
            coalesce(sum(n_d7), 0) AS n_d7,
            coalesce(sum(n_d30), 0) AS n_d30,
            coalesce(sum(n_d60), 0) AS n_d60,
            coalesce(sum(n_d90), 0) AS n_d90,
            coalesce(sum(repurchased_d7), 0) AS repurchased_d7,
            coalesce(sum(repurchased_d30), 0) AS repurchased_d30,
            coalesce(sum(repurchased_d60), 0) AS repurchased_d60,
            coalesce(sum(repurchased_d90), 0) AS repurchased_d90,
            coalesce(sum(session_active_d7), 0) AS session_active_d7,
            coalesce(sum(session_active_d30), 0) AS session_active_d30,
            coalesce(sum(session_active_d90), 0) AS session_active_d90,
            coalesce(sum(repeat_orders_d90), 0) AS repeat_orders_d90,
            coalesce(sum(net_d90), 0) AS net_d90,
            coalesce(sum(contribution_d90), 0) AS contribution_d90,
            coalesce(sum(contribution_d30), 0) AS contribution_d30,
            coalesce(sum(net_unbounded), 0) AS net_unbounded,
            coalesce(sum(contribution_unbounded), 0) AS contribution_unbounded
        FROM read_parquet('{_path('cohort_day.parquet')}')
        WHERE {_where(filters, device=False, channel=True, campaign=True)}
        """
    )
    for horizon in (7, 30, 60, 90):
        denom = float(row[f"n_d{horizon}"] or 0)
        row[f"repeat_purchase_within_{horizon}_days"] = (
            float(row[f"repurchased_d{horizon}"]) / denom if denom else None
        )
    for horizon in (7, 30, 90):
        denom = float(row[f"n_d{horizon}"] or 0)
        row[f"session_within_{horizon}_days"] = (
            float(row[f"session_active_d{horizon}"]) / denom if denom else None
        )
    n90 = float(row["n_d90"] or 0)
    row["orders_per_patient_d90"] = ((n90 + float(row["repeat_orders_d90"])) / n90) if n90 else None
    row["ltv_net_d90"] = (float(row["net_d90"]) / n90) if n90 else None
    row["contribution_per_patient_d90"] = (float(row["contribution_d90"]) / n90) if n90 else None
    row["device_ignored"] = filters.device_narrowed
    return row


def cohort_monthly(filters: Filters) -> pd.DataFrame:
    con = connect()
    frame = con.execute(
        f"""
        SELECT
            date_trunc('month', date) AS cohort_month,
            sum(patients) AS patients,
            sum(n_d30) AS n_d30,
            sum(n_d90) AS n_d90,
            sum(repurchased_d30) AS repurchased_d30,
            sum(repurchased_d90) AS repurchased_d90,
            sum(net_d90) AS net_d90,
            sum(contribution_d90) AS contribution_d90
        FROM read_parquet('{_path('cohort_day.parquet')}')
        WHERE {_where(filters, device=False, channel=True, campaign=True)}
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchdf()
    con.close()
    frame["cohort_month"] = pd.to_datetime(frame["cohort_month"])
    frame["repeat_purchase_within_30_days"] = frame["repurchased_d30"] / frame["n_d30"].where(frame["n_d30"] > 0)
    frame["repeat_purchase_within_90_days"] = frame["repurchased_d90"] / frame["n_d90"].where(frame["n_d90"] > 0)
    frame["contribution_per_patient_d90"] = frame["contribution_d90"] / frame["n_d90"].where(frame["n_d90"] > 0)
    return frame


def funnel_breakdown(filters: Filters, dimension: str) -> pd.DataFrame:
    if dimension not in {"device", "channel", "campaign", "landing_page"}:
        raise ValueError(dimension)
    con = connect()
    frame = con.execute(
        f"""
        SELECT
            {dimension} AS segment,
            sum(sessions) AS sessions,
            sum(service_selected) AS service_selected,
            sum(slot_selected) AS slot_selected,
            sum(payment_started) AS payment_started,
            sum(commercial_purchase) AS commercial_purchase,
            sum(go_only) AS go_only,
            sum(browse_only) AS browse_only
        FROM read_parquet('{_path('session_day.parquet')}')
        WHERE {_where(filters, device=True, channel=True, campaign=True)}
        GROUP BY 1
        ORDER BY sessions DESC
        """
    ).fetchdf()
    con.close()
    return frame


def specialization(filters: Filters) -> pd.DataFrame:
    con = connect()
    frame = con.execute(
        f"""
        SELECT
            specialization,
            sum(orders) AS orders,
            sum(net) AS net,
            sum(doctor) AS doctor,
            sum(order_contribution) AS contribution
        FROM read_parquet('{_path('order_day.parquet')}')
        WHERE {_where(filters, device=True, channel=True, campaign=True, testqa=False)}
        GROUP BY 1
        ORDER BY contribution DESC
        """
    ).fetchdf()
    con.close()
    return frame


def channel_economics(filters: Filters) -> pd.DataFrame | None:
    if filters.device_narrowed:
        return None
    con = connect()
    frame = con.execute(
        f"""
        WITH patients AS (
            SELECT channel,
                sum(patients) AS new_patients,
                sum(n_d90) AS n_d90,
                sum(repurchased_d90) AS repurchased_d90,
                sum(contribution_d90) AS contribution_d90,
                sum(contribution_unbounded) AS contribution_unbounded,
                sum(affiliate_patients) AS affiliate_patients
            FROM read_parquet('{_path('cohort_day.parquet')}')
            WHERE {_where(filters, device=False, channel=True, campaign=True)}
            GROUP BY 1
        ),
        spend AS (
            SELECT channel, sum(media_spend) AS media_spend, sum(clicks) AS clicks
            FROM read_parquet('{_path('spend_day.parquet')}')
            WHERE {_where(filters, device=False, channel=True, campaign=True)}
            GROUP BY 1
        )
        SELECT
            coalesce(p.channel, s.channel) AS channel,
            coalesce(p.new_patients, 0) AS new_patients,
            coalesce(p.n_d90, 0) AS n_d90,
            coalesce(p.repurchased_d90, 0) AS repurchased_d90,
            coalesce(p.contribution_d90, 0) AS contribution_d90,
            coalesce(p.contribution_unbounded, 0) AS contribution_unbounded,
            coalesce(s.media_spend, 0) AS media_spend,
            CASE WHEN coalesce(p.channel, s.channel) = 'affiliate'
                 THEN 25 * coalesce(p.affiliate_patients, 0) ELSE 0 END AS affiliate_cost
        FROM patients p
        FULL OUTER JOIN spend s ON s.channel = p.channel
        ORDER BY new_patients DESC
        """
    ).fetchdf()
    con.close()
    frame["repeat_purchase_within_90_days"] = frame["repurchased_d90"] / frame["n_d90"].where(frame["n_d90"] > 0)
    frame["contribution_after_marketing"] = (
        frame["contribution_unbounded"] - frame["media_spend"] - frame["affiliate_cost"]
    )
    return frame


def campaign_economics(filters: Filters) -> pd.DataFrame | None:
    if filters.device_narrowed:
        return None
    con = connect()
    frame = con.execute(
        f"""
        WITH patients AS (
            SELECT campaign,
                sum(patients) AS new_patients,
                sum(n_d90) AS n_d90,
                sum(contribution_d90) AS contribution_d90,
                sum(repurchased_d90) AS repurchased_d90
            FROM read_parquet('{_path('cohort_day.parquet')}')
            WHERE {_where(filters, device=False, channel=True, campaign=True)}
            GROUP BY 1
        ),
        spend AS (
            SELECT campaign, sum(media_spend) AS media_spend
            FROM read_parquet('{_path('spend_day.parquet')}')
            WHERE {_where(filters, device=False, channel=True, campaign=True)}
            GROUP BY 1
        )
        SELECT
            coalesce(s.campaign, p.campaign) AS campaign,
            coalesce(s.media_spend, 0) AS media_spend,
            coalesce(p.new_patients, 0) AS new_patients,
            coalesce(p.n_d90, 0) AS n_d90,
            coalesce(p.contribution_d90, 0) AS contribution_d90,
            coalesce(p.repurchased_d90, 0) AS repurchased_d90
        FROM spend s
        FULL OUTER JOIN patients p ON p.campaign = s.campaign
        WHERE coalesce(s.media_spend, 0) > 0 OR coalesce(p.new_patients, 0) > 0
        ORDER BY media_spend DESC, new_patients DESC
        """
    ).fetchdf()
    con.close()
    return frame


def matched_d90_spend(filters: Filters, dimension: str) -> pd.DataFrame:
    """D90 contribution vs spend for the same acquisition-date window.

    Cohorts are eligible only if their acquisition date is at least 90 days
    before the dataset's observation end. Attribution is not incrementality.
    """
    if dimension not in ("channel", "campaign"):
        raise ValueError("Expected channel or campaign")
    if filters.device_narrowed:
        raise ValueError("Device is not an acquisition cohort dimension")
    # Use dataset end, not selected filter end, as maturity is an observation property.
    cutoff = (pd.Timestamp(filters.date_max) - pd.Timedelta(days=90)).date()
    base_where = _where(filters, device=False, channel=True, campaign=True)
    con = connect()
    frame = con.execute(f"""
        WITH cohort AS (
            SELECT {dimension} AS segment,
                   sum(contribution_d90) AS contribution_d90,
                   sum(n_d90) AS n_d90,
                   sum(affiliate_patients) AS affiliate_patients
            FROM read_parquet('{_path('cohort_day.parquet')}')
            WHERE {base_where} AND date <= DATE '{cutoff}'
            GROUP BY 1
        ), spend AS (
            SELECT {dimension} AS segment, sum(media_spend) AS media_spend
            FROM read_parquet('{_path('spend_day.parquet')}')
            WHERE {base_where} AND date <= DATE '{cutoff}'
            GROUP BY 1
        )
        SELECT coalesce(c.segment, s.segment) AS segment,
               coalesce(c.contribution_d90, 0) AS contribution_d90,
               coalesce(c.n_d90, 0) AS n_d90,
               coalesce(s.media_spend, 0) AS media_spend,
               CASE WHEN '{dimension}' = 'channel' AND c.segment = 'affiliate'
                    THEN 25 * coalesce(c.affiliate_patients, 0) ELSE 0 END AS affiliate_cost
        FROM cohort c FULL OUTER JOIN spend s ON c.segment = s.segment
        ORDER BY media_spend DESC
    """).fetchdf()
    con.close()
    frame["acquisition_cost"] = frame["media_spend"] + frame["affiliate_cost"]
    return frame


def anomalies(filters: Filters) -> pd.DataFrame:
    frame = _table("anomalies_daily.parquet")
    frame["date"] = pd.to_datetime(frame["date"])
    mask = (frame["date"].dt.date >= filters.date_from) & (frame["date"].dt.date <= filters.date_to)
    return frame.loc[mask].sort_values(["date", "metric"])


def anomalies_weekly() -> pd.DataFrame:
    frame = _table("anomalies_weekly.parquet")
    return frame


def static_table(name: str) -> pd.DataFrame:
    return _table(name)
