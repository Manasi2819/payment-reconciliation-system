"""
main.py — Entry Point for the Payment Reconciliation System

Generates synthetic data, runs the multi-agent reconciliation engine,
prints sample outputs, and exports reports to CSV.

Usage:
    python main.py
"""

import os
import sys

import pandas as pd

from data_generation import generate_datasets
from coordinator import ReconciliationCoordinator


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_header(title: str) -> None:
    """Print a formatted section header."""
    width = 72
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_dataframe_sample(df: pd.DataFrame, title: str, n: int = 10) -> None:
    """Print the first n rows of a DataFrame with a title."""
    print(f"\n--- {title} (first {n} rows) ---")
    if df.empty:
        print("  (no records)")
    else:
        print(df.head(n).to_string(index=False))
    print()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    """End-to-end reconciliation pipeline."""

    # ------------------------------------------------------------------
    # Step 1: Generate synthetic data
    # ------------------------------------------------------------------
    print_header("STEP 1: DATA GENERATION")
    transactions, settlements, manifest = generate_datasets(seed=42)

    print(f"  Transactions generated : {len(transactions):,}")
    print(f"  Settlements generated  : {len(settlements):,}")
    print(f"\n  Injected issues:")
    for issue_type, ids in manifest.items():
        print(f"    {issue_type:30s} : {len(ids)} occurrences")

    print_dataframe_sample(transactions, "Transactions")
    print_dataframe_sample(settlements, "Settlements")

    # ------------------------------------------------------------------
    # Step 2: Run reconciliation engine
    # ------------------------------------------------------------------
    print_header("STEP 2: RECONCILIATION ENGINE")
    coordinator = ReconciliationCoordinator(transactions, settlements)
    coordinator.run()

    # ------------------------------------------------------------------
    # Step 3: Detailed mismatch report
    # ------------------------------------------------------------------
    print_header("STEP 3: DETAILED MISMATCH REPORT")
    detailed = coordinator.get_detailed_report()
    print(f"  Total issues found: {len(detailed)}")
    print_dataframe_sample(detailed, "Detailed Report")

    # Show a few examples per issue type
    if not detailed.empty:
        print("--- Sample issues by type ---")
        for issue_type in detailed["issue_type"].unique():
            subset = detailed[detailed["issue_type"] == issue_type]
            print(f"\n  [{issue_type.upper()}] ({len(subset)} total)")
            sample = subset.head(2)
            for _, row in sample.iterrows():
                print(f"    TXN: {row['transaction_id']}  |  "
                      f"Severity: {row['severity']}  |  {row['description']}")

    # ------------------------------------------------------------------
    # Step 4: Summary report
    # ------------------------------------------------------------------
    print_header("STEP 4: SUMMARY REPORT")
    summary = coordinator.get_summary_report()

    print(f"  Total transactions (rows)       : {summary['total_transactions']:,}")
    print(f"  Total unique transaction IDs     : {summary['total_unique_transaction_ids']:,}")
    print(f"  Total settlements (rows)         : {summary['total_settlements']:,}")
    print(f"  Total unique settlement txn IDs  : {summary['total_unique_settlement_txn_ids']:,}")
    print(f"  Total matched                    : {summary['total_matched']:,}")
    print(f"  Total mismatched (unique txn IDs): {summary['total_mismatched']:,}")
    print(f"  Total issues                     : {summary['total_issues']:,}")

    print("\n  Breakdown by issue type:")
    for issue_type, count in sorted(
        summary["breakdown_by_issue_type"].items(), key=lambda x: -x[1]
    ):
        print(f"    {issue_type:35s} : {count}")

    print("\n  Breakdown by severity:")
    for severity, count in sorted(
        summary["breakdown_by_severity"].items(), key=lambda x: -x[1]
    ):
        print(f"    {severity:10s} : {count}")

    # ------------------------------------------------------------------
    # Step 5: Export reports
    # ------------------------------------------------------------------
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    detailed_path, summary_path = coordinator.export_reports(output_dir)

    print_header("STEP 5: REPORTS EXPORTED")
    print(f"  Detailed report : {detailed_path}")
    print(f"  Summary report  : {summary_path}")

    # Also export raw datasets for reference
    transactions.to_csv(os.path.join(output_dir, "transactions.csv"), index=False)
    settlements.to_csv(os.path.join(output_dir, "settlements.csv"), index=False)
    print(f"  Transactions    : {os.path.join(output_dir, 'transactions.csv')}")
    print(f"  Settlements     : {os.path.join(output_dir, 'settlements.csv')}")

    # ------------------------------------------------------------------
    # Edge cases handled
    # ------------------------------------------------------------------
    print_header("EDGE CASES HANDLED")
    edge_cases = [
        "1. Refund transactions with no original success transaction "
        "(orphaned refunds) are detected even when user_id/amount "
        "combinations are ambiguous.",
        "2. Duplicate transaction_ids in both transactions and settlements "
        "are handled without causing merge explosions (dedup before join).",
        "3. Currency mismatches between transaction and settlement records "
        "are surfaced as random noise anomalies.",
        "4. Settlement dates that precede the transaction timestamp are "
        "flagged as settlement_before_transaction (negative delay).",
        "5. Rounding errors as small as ±0.01 are detected and "
        "distinguished from more significant amount mismatches.",
        "6. Multiple issue types can be reported for the same transaction_id "
        "(e.g., a delayed settlement that also has a rounding error).",
    ]
    for case in edge_cases:
        print(f"  • {case}")

    # ------------------------------------------------------------------
    # Production limitations
    # ------------------------------------------------------------------
    print_header("PRODUCTION LIMITATIONS")
    limitations = [
        "1. SCALABILITY: The current in-memory pandas approach works for "
        "thousands of records but would need to be replaced with a "
        "database-backed or distributed (Spark/Dask) solution for "
        "millions of transactions per day.",
        "2. REAL-TIME PROCESSING: This is a batch reconciliation system. "
        "Production systems often need stream-based (Kafka + Flink) "
        "reconciliation for near-real-time settlement matching.",
        "3. MULTI-CURRENCY FX RATES: The system detects currency mismatches "
        "but does not apply exchange rate conversions. Production systems "
        "would need FX rate feeds and tolerance bands per currency pair.",
    ]
    for lim in limitations:
        print(f"  • {lim}")

    print("\n" + "=" * 72)
    print("  Reconciliation complete.")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
