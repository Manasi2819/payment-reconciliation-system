"""
reconciliation_agents.py — Multi-Agent Reconciliation Engine

Each agent independently analyses transactions and settlements to detect
a specific class of inconsistency.  All agents share a common interface
defined by the abstract base class `ReconciliationAgent`.

Agent Catalogue:
    1. MatchingAgent          — joins datasets; produces matched/unmatched sets
    2. MissingSettlementAgent — transactions with no settlement
    3. UnmatchedSettlementAgent — settlements with no transaction
    4. AmountMismatchAgent    — exact + rounding differences
    5. DateMismatchAgent      — delayed / abnormal settlement dates
    6. DuplicateDetectionAgent — duplicates in either dataset
    7. RefundConsistencyAgent  — orphaned refunds
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    """A single reconciliation finding."""
    transaction_id: str
    issue_type: str
    description: str
    severity: str  # "low", "medium", "high"

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "issue_type": self.issue_type,
            "description": self.description,
            "severity": self.severity,
        }


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ReconciliationAgent(ABC):
    """
    Abstract base for all reconciliation agents.

    Subclasses must implement `analyze()` which receives the full
    transactions and settlements DataFrames and returns a list of Issues.
    """

    name: str = "BaseAgent"

    @abstractmethod
    def analyze(
        self,
        transactions: pd.DataFrame,
        settlements: pd.DataFrame,
    ) -> List[Issue]:
        """Run analysis and return discovered issues."""
        ...


# ---------------------------------------------------------------------------
# 1. Matching Agent
# ---------------------------------------------------------------------------

class MatchingAgent(ReconciliationAgent):
    """
    Performs a full outer join on `transaction_id` to identify:
      - Matched pairs
      - Left-only (transaction with no settlement)
      - Right-only (settlement with no transaction)

    Stores results as instance attributes for downstream agents.
    Does NOT produce Issues directly — it is a *support* agent consumed
    by the coordinator and other agents.
    """

    name = "MatchingAgent"

    def __init__(self):
        self.matched: Optional[pd.DataFrame] = None
        self.unmatched_transactions: Optional[pd.DataFrame] = None
        self.unmatched_settlements: Optional[pd.DataFrame] = None

    def analyze(
        self,
        transactions: pd.DataFrame,
        settlements: pd.DataFrame,
    ) -> List[Issue]:
        # Deduplicate before merge to get clean 1:1 matching.
        # Duplicate detection is handled by the DuplicateDetectionAgent.
        txn_dedup = transactions.drop_duplicates(subset=["transaction_id"], keep="first")
        stl_dedup = settlements.drop_duplicates(subset=["transaction_id"], keep="first")

        merged = txn_dedup.merge(
            stl_dedup,
            on="transaction_id",
            how="outer",
            suffixes=("_txn", "_stl"),
            indicator=True,
        )

        self.matched = merged[merged["_merge"] == "both"].copy()
        self.unmatched_transactions = merged[merged["_merge"] == "left_only"].copy()
        self.unmatched_settlements = merged[merged["_merge"] == "right_only"].copy()

        # No issues returned — this agent is a data provider
        return []


# ---------------------------------------------------------------------------
# 2. Missing Settlement Agent
# ---------------------------------------------------------------------------

class MissingSettlementAgent(ReconciliationAgent):
    """Detects transactions that have no corresponding settlement."""

    name = "MissingSettlementAgent"

    def analyze(
        self,
        transactions: pd.DataFrame,
        settlements: pd.DataFrame,
    ) -> List[Issue]:
        settlement_txn_ids = set(settlements["transaction_id"].unique())
        # Consider each unique transaction_id once
        txn_ids = transactions["transaction_id"].drop_duplicates()
        issues: List[Issue] = []

        for txn_id in txn_ids:
            if txn_id not in settlement_txn_ids:
                issues.append(Issue(
                    transaction_id=str(txn_id),
                    issue_type="missing_settlement",
                    description=(
                        f"Transaction {txn_id} has no corresponding settlement record."
                    ),
                    severity="high",
                ))

        return issues


# ---------------------------------------------------------------------------
# 3. Unmatched Settlement Agent
# ---------------------------------------------------------------------------

class UnmatchedSettlementAgent(ReconciliationAgent):
    """Detects settlements with no corresponding transaction."""

    name = "UnmatchedSettlementAgent"

    def analyze(
        self,
        transactions: pd.DataFrame,
        settlements: pd.DataFrame,
    ) -> List[Issue]:
        transaction_ids = set(transactions["transaction_id"].unique())
        stl_txn_ids = settlements["transaction_id"].drop_duplicates()
        issues: List[Issue] = []

        for txn_id in stl_txn_ids:
            if txn_id not in transaction_ids:
                issues.append(Issue(
                    transaction_id=str(txn_id),
                    issue_type="unmatched_settlement",
                    description=(
                        f"Settlement references {txn_id} which has no matching transaction."
                    ),
                    severity="high",
                ))

        return issues


# ---------------------------------------------------------------------------
# 4. Amount Mismatch Agent
# ---------------------------------------------------------------------------

class AmountMismatchAgent(ReconciliationAgent):
    """
    Identifies amount discrepancies between transactions and settlements.

    Classification:
        - |diff| <= 0.05  → rounding_error (severity: low)
        - |diff| >  0.05  → amount_mismatch (severity: medium)
    """

    name = "AmountMismatchAgent"
    ROUNDING_THRESHOLD = 0.05  # inclusive

    def analyze(
        self,
        transactions: pd.DataFrame,
        settlements: pd.DataFrame,
    ) -> List[Issue]:
        # Merge on transaction_id (inner join for matched pairs only)
        txn_dedup = transactions.drop_duplicates(subset=["transaction_id"], keep="first")
        stl_dedup = settlements.drop_duplicates(subset=["transaction_id"], keep="first")

        merged = txn_dedup.merge(
            stl_dedup,
            on="transaction_id",
            how="inner",
            suffixes=("_txn", "_stl"),
        )

        issues: List[Issue] = []

        for _, row in merged.iterrows():
            diff = round(row["settled_amount"] - row["amount"], 2)
            if diff == 0.0:
                continue

            abs_diff = abs(diff)

            if abs_diff <= self.ROUNDING_THRESHOLD:
                issues.append(Issue(
                    transaction_id=row["transaction_id"],
                    issue_type="rounding_error",
                    description=(
                        f"Rounding discrepancy: transaction={row['amount']}, "
                        f"settled={row['settled_amount']}, diff={diff:+.2f}"
                    ),
                    severity="low",
                ))
            else:
                issues.append(Issue(
                    transaction_id=row["transaction_id"],
                    issue_type="amount_mismatch",
                    description=(
                        f"Amount mismatch: transaction={row['amount']}, "
                        f"settled={row['settled_amount']}, diff={diff:+.2f}"
                    ),
                    severity="medium",
                ))

        return issues


# ---------------------------------------------------------------------------
# 5. Date Mismatch Agent
# ---------------------------------------------------------------------------

class DateMismatchAgent(ReconciliationAgent):
    """
    Detects abnormal settlement timing.

    Classification:
        - 30 < delay_days <= 60  → settlement_delay  (severity: medium)
        - delay_days > 60        → abnormal_delay     (severity: high)
        - delay_days < 0         → settlement_before_transaction (severity: high)
    """

    name = "DateMismatchAgent"
    DELAY_THRESHOLD_DAYS = 30
    ABNORMAL_THRESHOLD_DAYS = 60

    def analyze(
        self,
        transactions: pd.DataFrame,
        settlements: pd.DataFrame,
    ) -> List[Issue]:
        txn_dedup = transactions.drop_duplicates(subset=["transaction_id"], keep="first")
        stl_dedup = settlements.drop_duplicates(subset=["transaction_id"], keep="first")

        merged = txn_dedup.merge(
            stl_dedup,
            on="transaction_id",
            how="inner",
            suffixes=("_txn", "_stl"),
        )

        issues: List[Issue] = []

        for _, row in merged.iterrows():
            txn_ts = pd.Timestamp(row["timestamp"])
            stl_ts = pd.Timestamp(row["settlement_date"])
            delay = (stl_ts - txn_ts).days

            if delay < 0:
                issues.append(Issue(
                    transaction_id=row["transaction_id"],
                    issue_type="settlement_before_transaction",
                    description=(
                        f"Settlement date ({stl_ts.date()}) is before "
                        f"transaction date ({txn_ts.date()}) by {abs(delay)} days."
                    ),
                    severity="high",
                ))
            elif delay > self.ABNORMAL_THRESHOLD_DAYS:
                issues.append(Issue(
                    transaction_id=row["transaction_id"],
                    issue_type="abnormal_delay",
                    description=(
                        f"Settlement delayed by {delay} days "
                        f"(txn={txn_ts.date()}, stl={stl_ts.date()})."
                    ),
                    severity="high",
                ))
            elif delay > self.DELAY_THRESHOLD_DAYS:
                issues.append(Issue(
                    transaction_id=row["transaction_id"],
                    issue_type="settlement_delay",
                    description=(
                        f"Settlement delayed by {delay} days "
                        f"(txn={txn_ts.date()}, stl={stl_ts.date()})."
                    ),
                    severity="medium",
                ))

        return issues


# ---------------------------------------------------------------------------
# 6. Duplicate Detection Agent
# ---------------------------------------------------------------------------

class DuplicateDetectionAgent(ReconciliationAgent):
    """
    Finds duplicate `transaction_id` entries in either dataset.

    Duplicate settlements and duplicate transactions are reported separately.
    """

    name = "DuplicateDetectionAgent"

    def analyze(
        self,
        transactions: pd.DataFrame,
        settlements: pd.DataFrame,
    ) -> List[Issue]:
        issues: List[Issue] = []

        # Duplicate transactions
        txn_dupes = transactions[
            transactions.duplicated(subset=["transaction_id"], keep=False)
        ]["transaction_id"].unique()

        for txn_id in txn_dupes:
            count = len(transactions[transactions["transaction_id"] == txn_id])
            issues.append(Issue(
                transaction_id=txn_id,
                issue_type="duplicate_transaction",
                description=(
                    f"Transaction {txn_id} appears {count} times in the "
                    f"transactions dataset."
                ),
                severity="medium",
            ))

        # Duplicate settlements (by transaction_id — same txn settled twice)
        stl_dupes = settlements[
            settlements.duplicated(subset=["transaction_id"], keep=False)
        ]["transaction_id"].unique()

        for txn_id in stl_dupes:
            count = len(settlements[settlements["transaction_id"] == txn_id])
            issues.append(Issue(
                transaction_id=txn_id,
                issue_type="duplicate_settlement",
                description=(
                    f"Transaction {txn_id} has {count} settlement entries."
                ),
                severity="medium",
            ))

        return issues


# ---------------------------------------------------------------------------
# 7. Refund Consistency Agent
# ---------------------------------------------------------------------------

class RefundConsistencyAgent(ReconciliationAgent):
    """
    Verifies that every refund transaction has a corresponding original
    'success' transaction for the same user and amount.

    Detects:
        - Refund with no possible original transaction (orphaned refund)
    """

    name = "RefundConsistencyAgent"

    def analyze(
        self,
        transactions: pd.DataFrame,
        settlements: pd.DataFrame,
    ) -> List[Issue]:
        refunds = transactions[transactions["status"] == "refund"]
        successes = transactions[transactions["status"] == "success"]

        issues: List[Issue] = []

        for _, refund in refunds.iterrows():
            # Look for a matching success transaction: same user, same amount
            match = successes[
                (successes["user_id"] == refund["user_id"])
                & (np.isclose(successes["amount"], refund["amount"], atol=0.01))
                & (successes["timestamp"] < refund["timestamp"])
            ]

            if match.empty:
                issues.append(Issue(
                    transaction_id=refund["transaction_id"],
                    issue_type="refund_without_original",
                    description=(
                        f"Refund {refund['transaction_id']} (user={refund['user_id']}, "
                        f"amount={refund['amount']}) has no matching original transaction."
                    ),
                    severity="high",
                ))

        return issues


# ---------------------------------------------------------------------------
# Agent registry (for coordinator)
# ---------------------------------------------------------------------------

ALL_AGENTS = [
    MatchingAgent,
    MissingSettlementAgent,
    UnmatchedSettlementAgent,
    AmountMismatchAgent,
    DateMismatchAgent,
    DuplicateDetectionAgent,
    RefundConsistencyAgent,
]
