"""
data_generation.py — Synthetic Data Generator for Payment Reconciliation

Generates realistic transaction and settlement datasets with controlled,
real-world inconsistencies for reconciliation testing.

Assumptions:
    - Transactions span a 3-month window.
    - Settlements normally occur within 1–5 business days of a transaction.
    - Amounts follow a log-normal distribution (most small, few large).
    - Multi-currency: USD (60%), EUR (20%), GBP (10%), INR (10%).
    - ~5% of transactions are refunds, linked to a prior success transaction.
"""

import random
import string
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CURRENCIES = ["USD", "EUR", "GBP", "INR"]
CURRENCY_WEIGHTS = [0.60, 0.20, 0.10, 0.10]
STATUSES = ["success", "refund"]

NUM_USERS = 200
NUM_TRANSACTIONS = 2500

# Date range for transactions: 2025-10-01 to 2025-12-31
START_DATE = datetime(2025, 10, 1)
END_DATE = datetime(2025, 12, 31)

# Issue injection counts
ISSUE_COUNTS = {
    "settlement_delay": 80,
    "rounding_error": 60,
    "duplicate_settlement": 30,
    "duplicate_transaction": 20,
    "refund_without_original": 15,
    "missing_settlement": 100,
    "extra_settlement": 25,
    "random_noise": 10,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_transaction_id() -> str:
    """Generate a realistic transaction ID like 'TXN-A1B2C3D4'."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"TXN-{suffix}"


def _generate_settlement_id() -> str:
    """Generate a realistic settlement ID like 'STL-XXXXXXXX'."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"STL-{suffix}"


def _random_timestamp(start: datetime, end: datetime) -> datetime:
    """Return a random datetime between start and end."""
    delta = end - start
    random_seconds = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=random_seconds)


def _log_normal_amount(mean: float = 4.0, sigma: float = 1.2) -> float:
    """Generate a log-normally distributed amount (most payments are small)."""
    raw = float(np.random.lognormal(mean=mean, sigma=sigma))
    # Clamp to realistic range [1.00, 50000.00]
    return round(max(1.0, min(raw, 50000.0)), 2)


# ---------------------------------------------------------------------------
# Core Generator
# ---------------------------------------------------------------------------

class DataGenerator:
    """
    Generates synthetic transaction and settlement datasets with
    controlled, traceable data-quality issues.

    Usage:
        gen = DataGenerator(seed=42)
        transactions, settlements, manifest = gen.generate()
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        np.random.seed(seed)
        random.seed(seed)
        self.user_ids = [f"USR-{str(i).zfill(5)}" for i in range(1, NUM_USERS + 1)]
        self.manifest: Dict[str, List[str]] = {key: [] for key in ISSUE_COUNTS}

    # ----- public API -----

    def generate(self) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, List[str]]]:
        """
        Generate transactions and settlements DataFrames, plus a manifest
        documenting which transaction_ids were affected by each issue.

        Returns:
            (transactions_df, settlements_df, manifest)
        """
        transactions = self._generate_transactions()
        settlements = self._generate_settlements(transactions)

        # Inject issues (order matters — some depend on prior state)
        transactions, settlements = self._inject_refund_without_original(transactions, settlements)
        transactions, settlements = self._inject_missing_settlements(transactions, settlements)
        settlements = self._inject_settlement_delays(transactions, settlements)
        settlements = self._inject_rounding_errors(settlements)
        settlements = self._inject_duplicate_settlements(settlements)
        transactions = self._inject_duplicate_transactions(transactions)
        settlements = self._inject_extra_settlements(settlements)
        settlements = self._inject_random_noise(settlements)

        # Reset indices
        transactions = transactions.reset_index(drop=True)
        settlements = settlements.reset_index(drop=True)

        return transactions, settlements, self.manifest

    # ----- private: base data -----

    def _generate_transactions(self) -> pd.DataFrame:
        """Create the base transactions table (all success + some refunds)."""
        records = []
        refund_pool: List[str] = []  # transaction_ids eligible for refund

        for _ in range(NUM_TRANSACTIONS):
            txn_id = _generate_transaction_id()
            user_id = random.choice(self.user_ids)
            ts = _random_timestamp(START_DATE, END_DATE)
            amount = _log_normal_amount()
            currency = random.choices(CURRENCIES, weights=CURRENCY_WEIGHTS, k=1)[0]

            # ~5 % refunds
            if random.random() < 0.05 and refund_pool:
                status = "refund"
            else:
                status = "success"
                refund_pool.append(txn_id)

            records.append({
                "transaction_id": txn_id,
                "user_id": user_id,
                "timestamp": ts,
                "amount": amount,
                "currency": currency,
                "status": status,
            })

        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def _generate_settlements(self, transactions: pd.DataFrame) -> pd.DataFrame:
        """Create a settlement for every transaction (1:1). Issues added later."""
        records = []
        for _, txn in transactions.iterrows():
            # Normal settlement delay: 1–5 business days
            delay_days = random.randint(1, 5)
            settlement_date = txn["timestamp"] + timedelta(days=delay_days)

            records.append({
                "settlement_id": _generate_settlement_id(),
                "transaction_id": txn["transaction_id"],
                "settlement_date": settlement_date,
                "settled_amount": txn["amount"],  # exact match initially
                "currency": txn["currency"],
            })

        df = pd.DataFrame(records)
        df["settlement_date"] = pd.to_datetime(df["settlement_date"])
        return df

    # ----- private: issue injection -----

    def _inject_settlement_delays(
        self, transactions: pd.DataFrame, settlements: pd.DataFrame
    ) -> pd.DataFrame:
        """Push some settlements 30–45 days into the future (next-month delay)."""
        count = ISSUE_COUNTS["settlement_delay"]
        eligible = settlements.sample(n=count, random_state=self.seed).index

        for idx in eligible:
            txn_id = settlements.at[idx, "transaction_id"]
            extra_days = random.randint(30, 45)
            settlements.at[idx, "settlement_date"] += timedelta(days=extra_days)
            self.manifest["settlement_delay"].append(txn_id)

        return settlements

    def _inject_rounding_errors(self, settlements: pd.DataFrame) -> pd.DataFrame:
        """Introduce small floating-point diffs (±0.01 to ±0.03)."""
        count = ISSUE_COUNTS["rounding_error"]
        eligible = settlements.sample(n=count, random_state=self.seed + 1).index

        for idx in eligible:
            txn_id = settlements.at[idx, "transaction_id"]
            offset = round(float(random.choice([-0.03, -0.02, -0.01, 0.01, 0.02, 0.03])), 2)
            settlements.at[idx, "settled_amount"] = round(
                settlements.at[idx, "settled_amount"] + offset, 2
            )
            self.manifest["rounding_error"].append(txn_id)

        return settlements

    def _inject_duplicate_settlements(self, settlements: pd.DataFrame) -> pd.DataFrame:
        """Duplicate some settlement rows with new settlement_ids."""
        count = ISSUE_COUNTS["duplicate_settlement"]
        dupes = settlements.sample(n=count, random_state=self.seed + 2).copy()

        for idx in dupes.index:
            self.manifest["duplicate_settlement"].append(dupes.at[idx, "transaction_id"])

        dupes["settlement_id"] = [_generate_settlement_id() for _ in range(len(dupes))]
        return pd.concat([settlements, dupes], ignore_index=True)

    def _inject_duplicate_transactions(self, transactions: pd.DataFrame) -> pd.DataFrame:
        """Duplicate some transaction rows (exact copies)."""
        count = ISSUE_COUNTS["duplicate_transaction"]
        dupes = transactions.sample(n=count, random_state=self.seed + 3).copy()

        for idx in dupes.index:
            self.manifest["duplicate_transaction"].append(dupes.at[idx, "transaction_id"])

        return pd.concat([transactions, dupes], ignore_index=True)

    def _inject_refund_without_original(
        self, transactions: pd.DataFrame, settlements: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Create refund entries whose 'original' transaction is then removed,
        so the refund has no matching original in the final dataset.
        """
        count = ISSUE_COUNTS["refund_without_original"]
        success_txns = transactions[transactions["status"] == "success"]

        if len(success_txns) < count:
            count = len(success_txns)

        chosen = success_txns.sample(n=count, random_state=self.seed + 4)

        orphan_refunds = []
        removed_txn_ids = []

        for _, row in chosen.iterrows():
            refund_id = _generate_transaction_id()
            orphan_refunds.append({
                "transaction_id": refund_id,
                "user_id": row["user_id"],
                "timestamp": row["timestamp"] + timedelta(days=random.randint(1, 10)),
                "amount": row["amount"],
                "currency": row["currency"],
                "status": "refund",
            })
            removed_txn_ids.append(row["transaction_id"])
            self.manifest["refund_without_original"].append(refund_id)

        # Remove the original transactions (and their settlements)
        transactions = transactions[~transactions["transaction_id"].isin(removed_txn_ids)]
        settlements = settlements[~settlements["transaction_id"].isin(removed_txn_ids)]

        # Add the orphan refund rows
        transactions = pd.concat(
            [transactions, pd.DataFrame(orphan_refunds)], ignore_index=True
        )

        return transactions, settlements

    def _inject_missing_settlements(
        self, transactions: pd.DataFrame, settlements: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Remove settlements for some transactions (no settlement exists)."""
        count = ISSUE_COUNTS["missing_settlement"]
        # Only pick transactions that currently have a settlement
        has_settlement = settlements["transaction_id"].unique()
        eligible_txns = transactions[
            transactions["transaction_id"].isin(has_settlement)
        ]["transaction_id"]

        if len(eligible_txns) < count:
            count = len(eligible_txns)

        to_remove = eligible_txns.sample(n=count, random_state=self.seed + 5).values

        for txn_id in to_remove:
            self.manifest["missing_settlement"].append(txn_id)

        settlements = settlements[~settlements["transaction_id"].isin(to_remove)]
        return transactions, settlements

    def _inject_extra_settlements(self, settlements: pd.DataFrame) -> pd.DataFrame:
        """Add settlement rows that reference fabricated transaction_ids."""
        count = ISSUE_COUNTS["extra_settlement"]
        extras = []
        for _ in range(count):
            fake_txn_id = _generate_transaction_id()
            extras.append({
                "settlement_id": _generate_settlement_id(),
                "transaction_id": fake_txn_id,
                "settlement_date": _random_timestamp(START_DATE, END_DATE),
                "settled_amount": _log_normal_amount(),
                "currency": random.choices(CURRENCIES, weights=CURRENCY_WEIGHTS, k=1)[0],
            })
            self.manifest["extra_settlement"].append(fake_txn_id)

        return pd.concat([settlements, pd.DataFrame(extras)], ignore_index=True)

    def _inject_random_noise(self, settlements: pd.DataFrame) -> pd.DataFrame:
        """
        Introduce random anomalies: currency mismatch or extreme amount deviation.
        """
        count = ISSUE_COUNTS["random_noise"]
        eligible = settlements.sample(n=count, random_state=self.seed + 6).index

        for idx in eligible:
            txn_id = settlements.at[idx, "transaction_id"]
            if random.random() < 0.5:
                # Currency mismatch
                orig_currency = settlements.at[idx, "currency"]
                other = [c for c in CURRENCIES if c != orig_currency]
                settlements.at[idx, "currency"] = random.choice(other)
            else:
                # Extreme amount deviation (±50–200 %)
                factor = random.uniform(1.5, 3.0) * random.choice([-1, 1])
                settlements.at[idx, "settled_amount"] = round(
                    abs(settlements.at[idx, "settled_amount"] * factor), 2
                )
            self.manifest["random_noise"].append(txn_id)

        return settlements


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def generate_datasets(seed: int = 42) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, List[str]]]:
    """
    Convenience wrapper.  Returns (transactions, settlements, manifest).
    """
    gen = DataGenerator(seed=seed)
    return gen.generate()


if __name__ == "__main__":
    txns, stls, manifest = generate_datasets()
    print(f"Transactions: {len(txns)} rows")
    print(f"Settlements:  {len(stls)} rows")
    print("\nInjected issues:")
    for issue, ids in manifest.items():
        print(f"  {issue}: {len(ids)} occurrences")
