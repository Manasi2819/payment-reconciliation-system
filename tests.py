"""
tests.py — Test Suite for Payment Reconciliation System

Contains both hand-crafted manual test cases and automated assertions
for each reconciliation agent and the coordinator.

Run with:
    python -m unittest tests -v
    # or
    python -m pytest tests.py -v
"""

import unittest
from datetime import datetime, timedelta
from typing import ClassVar, Dict, List

import numpy as np
import pandas as pd

from reconciliation_agents import (
    AmountMismatchAgent,
    DateMismatchAgent,
    DuplicateDetectionAgent,
    Issue,
    MatchingAgent,
    MissingSettlementAgent,
    RefundConsistencyAgent,
    UnmatchedSettlementAgent,
)
from coordinator import ReconciliationCoordinator
from data_generation import generate_datasets


# ---------------------------------------------------------------------------
# Helpers — build small hand-crafted DataFrames
# ---------------------------------------------------------------------------

def _make_transactions(rows: list) -> pd.DataFrame:
    """
    Convenience: rows is a list of dicts with keys
    transaction_id, user_id, timestamp, amount, currency, status.
    """
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def _make_settlements(rows: list) -> pd.DataFrame:
    """
    Convenience: rows is a list of dicts with keys
    settlement_id, transaction_id, settlement_date, settled_amount, currency.
    """
    if not rows:
        return pd.DataFrame(
            columns=["settlement_id", "transaction_id", "settlement_date",
                      "settled_amount", "currency"]
        )
    df = pd.DataFrame(rows)
    df["settlement_date"] = pd.to_datetime(df["settlement_date"])
    return df


# =========================================================================
# Manual (hand-crafted) test cases — one per agent
# =========================================================================

class TestMatchingAgent(unittest.TestCase):
    """Manual test: verify matching agent separates matched/unmatched."""

    def test_matching_splits_correctly(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
            {"transaction_id": "T2", "user_id": "U2", "timestamp": "2025-10-02",
             "amount": 200.0, "currency": "EUR", "status": "success"},
            {"transaction_id": "T3", "user_id": "U3", "timestamp": "2025-10-03",
             "amount": 50.0, "currency": "GBP", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 100.0, "currency": "USD"},
            {"settlement_id": "S2", "transaction_id": "T2",
             "settlement_date": "2025-10-03", "settled_amount": 200.0, "currency": "EUR"},
            {"settlement_id": "S4", "transaction_id": "T4",
             "settlement_date": "2025-10-04", "settled_amount": 75.0, "currency": "INR"},
        ])

        agent = MatchingAgent()
        agent.analyze(txns, stls)

        self.assertEqual(len(agent.matched), 2, "Should match T1 and T2")
        self.assertEqual(len(agent.unmatched_transactions), 1, "T3 has no settlement")
        self.assertEqual(len(agent.unmatched_settlements), 1, "T4 has no transaction")


class TestMissingSettlementAgent(unittest.TestCase):
    """Manual test: transaction with no settlement is flagged."""

    def test_detects_missing_settlement(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
            {"transaction_id": "T2", "user_id": "U2", "timestamp": "2025-10-02",
             "amount": 200.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 100.0, "currency": "USD"},
        ])

        agent = MissingSettlementAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].transaction_id, "T2")
        self.assertEqual(issues[0].issue_type, "missing_settlement")
        self.assertEqual(issues[0].severity, "high")


class TestUnmatchedSettlementAgent(unittest.TestCase):
    """Manual test: settlement with no transaction is flagged."""

    def test_detects_extra_settlement(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 100.0, "currency": "USD"},
            {"settlement_id": "S2", "transaction_id": "T99",
             "settlement_date": "2025-10-03", "settled_amount": 500.0, "currency": "USD"},
        ])

        agent = UnmatchedSettlementAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].transaction_id, "T99")
        self.assertEqual(issues[0].issue_type, "unmatched_settlement")
        self.assertEqual(issues[0].severity, "high")


class TestAmountMismatchAgent(unittest.TestCase):
    """Manual test: rounding and exact mismatches detected."""

    def test_rounding_difference(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.00, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 99.98, "currency": "USD"},
        ])

        agent = AmountMismatchAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "rounding_error")
        self.assertEqual(issues[0].severity, "low")

    def test_exact_mismatch(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.00, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 110.00, "currency": "USD"},
        ])

        agent = AmountMismatchAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "amount_mismatch")
        self.assertEqual(issues[0].severity, "medium")

    def test_no_mismatch_on_exact_match(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 50.00, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 50.00, "currency": "USD"},
        ])

        agent = AmountMismatchAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 0, "No issue when amounts match exactly")


class TestDateMismatchAgent(unittest.TestCase):
    """Manual test: delayed and abnormal settlement dates detected."""

    def test_settlement_delay(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-11-05", "settled_amount": 100.0, "currency": "USD"},
        ])

        agent = DateMismatchAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "settlement_delay")
        self.assertEqual(issues[0].severity, "medium")

    def test_abnormal_delay(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-12-15", "settled_amount": 100.0, "currency": "USD"},
        ])

        agent = DateMismatchAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "abnormal_delay")
        self.assertEqual(issues[0].severity, "high")

    def test_normal_delay_no_issue(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-04", "settled_amount": 100.0, "currency": "USD"},
        ])

        agent = DateMismatchAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 0, "3-day delay is normal, no issue expected")


class TestDuplicateDetectionAgent(unittest.TestCase):
    """Manual test: duplicates in both datasets detected."""

    def test_duplicate_transaction(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 100.0, "currency": "USD"},
        ])

        agent = DuplicateDetectionAgent()
        issues = agent.analyze(txns, stls)

        txn_issues = [i for i in issues if i.issue_type == "duplicate_transaction"]
        self.assertEqual(len(txn_issues), 1)
        self.assertEqual(txn_issues[0].transaction_id, "T1")

    def test_duplicate_settlement(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 100.0, "currency": "USD"},
            {"settlement_id": "S2", "transaction_id": "T1",
             "settlement_date": "2025-10-03", "settled_amount": 100.0, "currency": "USD"},
        ])

        agent = DuplicateDetectionAgent()
        issues = agent.analyze(txns, stls)

        stl_issues = [i for i in issues if i.issue_type == "duplicate_settlement"]
        self.assertEqual(len(stl_issues), 1)
        self.assertEqual(stl_issues[0].transaction_id, "T1")


class TestRefundConsistencyAgent(unittest.TestCase):
    """Manual test: orphaned refund detected."""

    def test_refund_without_original(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-05",
             "amount": 100.0, "currency": "USD", "status": "refund"},
            # No success transaction for U1 with amount 100.0 before this date
        ])
        stls = _make_settlements([])  # Empty — not relevant for this agent

        agent = RefundConsistencyAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, "refund_without_original")
        self.assertEqual(issues[0].severity, "high")

    def test_refund_with_valid_original(self):
        txns = _make_transactions([
            {"transaction_id": "T0", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-05",
             "amount": 100.0, "currency": "USD", "status": "refund"},
        ])
        stls = _make_settlements([])

        agent = RefundConsistencyAgent()
        issues = agent.analyze(txns, stls)

        self.assertEqual(len(issues), 0, "Valid refund should not be flagged")


# =========================================================================
# Automated test on clean data — no false positives
# =========================================================================

class TestCleanData(unittest.TestCase):
    """Ensure zero issues when data is perfectly clean."""

    def test_no_false_positives(self):
        txns = _make_transactions([
            {"transaction_id": f"T{i}", "user_id": f"U{i}", "timestamp": "2025-10-01",
             "amount": 100.0 + i, "currency": "USD", "status": "success"}
            for i in range(1, 6)
        ])
        stls = _make_settlements([
            {"settlement_id": f"S{i}", "transaction_id": f"T{i}",
             "settlement_date": "2025-10-03", "settled_amount": 100.0 + i,
             "currency": "USD"}
            for i in range(1, 6)
        ])

        coordinator = ReconciliationCoordinator(txns, stls)
        coordinator.run()
        detailed = coordinator.get_detailed_report()

        self.assertEqual(len(detailed), 0, "No issues expected on clean data")


# =========================================================================
# Automated test on generated data — issue counts validation
# =========================================================================

class TestGeneratedData(unittest.TestCase):
    """Validate that the reconciliation engine detects at least as many
    issues as were injected by the data generator."""

    transactions: ClassVar[pd.DataFrame]
    settlements: ClassVar[pd.DataFrame]
    manifest: ClassVar[Dict[str, List[str]]]
    coordinator: ClassVar[ReconciliationCoordinator]
    detailed: ClassVar[pd.DataFrame]

    @classmethod
    def setUpClass(cls):
        cls.transactions, cls.settlements, cls.manifest = generate_datasets(seed=99)
        cls.coordinator = ReconciliationCoordinator(cls.transactions, cls.settlements)
        cls.coordinator.run()
        cls.detailed = cls.coordinator.get_detailed_report()

    def test_missing_settlements_detected(self):
        """Engine should detect at least the injected missing settlements."""
        detected = len(self.detailed[
            self.detailed["issue_type"] == "missing_settlement"
        ])
        injected = len(self.manifest["missing_settlement"])
        self.assertGreaterEqual(
            detected, injected * 0.9,
            f"Expected ≥ {int(injected * 0.9)} missing settlements, got {detected}",
        )

    def test_extra_settlements_detected(self):
        """Engine should detect the injected extra settlements."""
        detected = len(self.detailed[
            self.detailed["issue_type"] == "unmatched_settlement"
        ])
        injected = len(self.manifest["extra_settlement"])
        self.assertGreaterEqual(
            detected, injected,
            f"Expected ≥ {injected} unmatched settlements, got {detected}",
        )

    def test_duplicate_transactions_detected(self):
        """Engine should detect injected duplicate transactions."""
        detected = len(self.detailed[
            self.detailed["issue_type"] == "duplicate_transaction"
        ])
        injected = len(self.manifest["duplicate_transaction"])
        self.assertGreaterEqual(
            detected, injected,
            f"Expected ≥ {injected} duplicate transactions, got {detected}",
        )

    def test_duplicate_settlements_detected(self):
        """Engine should detect injected duplicate settlements."""
        detected = len(self.detailed[
            self.detailed["issue_type"] == "duplicate_settlement"
        ])
        injected = len(self.manifest["duplicate_settlement"])
        self.assertGreaterEqual(
            detected, injected,
            f"Expected ≥ {injected} duplicate settlements, got {detected}",
        )

    def test_rounding_errors_detected(self):
        """Engine should detect some rounding errors."""
        detected = len(self.detailed[
            self.detailed["issue_type"] == "rounding_error"
        ])
        # Some rounding errors may be on transactions that were removed
        # for other reasons, so we use a looser bound.
        self.assertGreater(
            detected, 0,
            "Expected at least some rounding errors to be detected",
        )

    def test_settlement_delays_detected(self):
        """Engine should detect delayed settlements."""
        detected = len(self.detailed[
            self.detailed["issue_type"].isin(["settlement_delay", "abnormal_delay"])
        ])
        self.assertGreater(
            detected, 0,
            "Expected at least some settlement delays to be detected",
        )

    def test_refund_issues_detected(self):
        """Engine should detect some refund-without-original issues."""
        detected = len(self.detailed[
            self.detailed["issue_type"] == "refund_without_original"
        ])
        self.assertGreater(
            detected, 0,
            "Expected at least some refund consistency issues",
        )

    def test_total_issues_nonzero(self):
        """Total issues should be substantially nonzero."""
        self.assertGreater(len(self.detailed), 100, "Expected many issues in total")


# =========================================================================
# Coordinator-specific tests
# =========================================================================

class TestCoordinatorDeduplication(unittest.TestCase):
    """Verify the coordinator deduplicates issues properly."""

    def test_dedup_removes_exact_duplicates(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 100.0, "currency": "USD"},
            {"settlement_id": "S2", "transaction_id": "T1",
             "settlement_date": "2025-10-03", "settled_amount": 100.0, "currency": "USD"},
        ])

        coordinator = ReconciliationCoordinator(txns, stls)
        coordinator.run()
        detailed = coordinator.get_detailed_report()

        # Should have exactly one duplicate_transaction + one duplicate_settlement
        dup_txn = detailed[detailed["issue_type"] == "duplicate_transaction"]
        dup_stl = detailed[detailed["issue_type"] == "duplicate_settlement"]
        self.assertEqual(len(dup_txn), 1, "One deduplicated duplicate_transaction issue")
        self.assertEqual(len(dup_stl), 1, "One deduplicated duplicate_settlement issue")


class TestCoordinatorSummary(unittest.TestCase):
    """Verify summary report structure."""

    def test_summary_has_required_keys(self):
        txns = _make_transactions([
            {"transaction_id": "T1", "user_id": "U1", "timestamp": "2025-10-01",
             "amount": 100.0, "currency": "USD", "status": "success"},
        ])
        stls = _make_settlements([
            {"settlement_id": "S1", "transaction_id": "T1",
             "settlement_date": "2025-10-02", "settled_amount": 100.0, "currency": "USD"},
        ])

        coordinator = ReconciliationCoordinator(txns, stls)
        coordinator.run()
        summary = coordinator.get_summary_report()

        required_keys = [
            "total_transactions", "total_settlements",
            "total_matched", "total_mismatched", "total_issues",
            "breakdown_by_issue_type", "breakdown_by_severity",
        ]
        for key in required_keys:
            self.assertIn(key, summary, f"Summary missing key: {key}")


if __name__ == "__main__":
    unittest.main()
