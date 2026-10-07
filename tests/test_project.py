#!/usr/bin/env python3
"""Small, meaningful consistency checks for committed project outputs."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "outputs" / "run_20260915"
TABLES = RUN / "tables"


class ProjectOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metrics = json.loads((RUN / "analysis_metrics.json").read_text(encoding="utf-8"))
        cls.monthly = pd.read_csv(TABLES / "monthly_kpis.csv")
        cls.cohort = pd.read_csv(TABLES / "cohort_repeat.csv")
        cls.segments = pd.read_csv(TABLES / "rfm_segment_summary.csv")

    def test_financial_identity_closes(self) -> None:
        financial = self.metrics["financial"]
        self.assertAlmostEqual(financial["gross_sales"] - financial["return_amount"], financial["net_revenue"], places=2)

    def test_monthly_totals_match_full_period(self) -> None:
        self.assertAlmostEqual(self.monthly["net_revenue"].sum(), self.metrics["financial"]["net_revenue"], places=2)
        self.assertEqual(int(self.monthly["sale_orders"].sum()), self.metrics["orders"]["sale_orders"])

    def test_repeat_rate_uses_eligible_denominator(self) -> None:
        repeat = self.metrics["repeat"]
        self.assertAlmostEqual(repeat["repeat_90d_customers"] / repeat["eligible_90d_customers"], repeat["repeat_90d_rate"], places=12)
        self.assertTrue((self.cohort.loc[self.cohort["mature_90d"], "eligible_90d"] > 0).all())

    def test_rfm_shares_close(self) -> None:
        self.assertAlmostEqual(self.segments["customer_share"].sum(), 1.0, places=5)
        self.assertAlmostEqual(self.segments["gross_value_share"].sum(), 1.0, places=5)
        self.assertAlmostEqual(self.segments["net_value_share"].sum(), 1.0, places=5)
        self.assertEqual(int(self.segments["customers"].sum()), self.metrics["rfm"]["entity_count"])

    def test_incomplete_december_is_excluded_from_month_comparison(self) -> None:
        row = self.monthly.loc[self.monthly["month"] == "2011-12"].iloc[0]
        self.assertFalse(bool(row["is_complete_month"]))
        self.assertNotEqual(self.metrics["monthly"]["lowest_net_revenue_month"], "2011-12")


if __name__ == "__main__":
    unittest.main(verbosity=2)
