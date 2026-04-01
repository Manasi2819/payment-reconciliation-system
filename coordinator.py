"""
coordinator.py — Reconciliation Coordinator (Main Engine)

Orchestrates all reconciliation agents, deduplicates findings, and
produces structured reports (detailed + summary).

Architecture:
    Coordinator
      ├── MatchingAgent
      ├── MissingSettlementAgent
      ├── UnmatchedSettlementAgent
      ├── AmountMismatchAgent
      ├── DateMismatchAgent
      ├── DuplicateDetectionAgent
      └── RefundConsistencyAgent
"""

import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from reconciliation_agents import (
    ALL_AGENTS,
    Issue,
    MatchingAgent,
    ReconciliationAgent,
)


class ReconciliationCoordinator:
    """
    Central orchestrator for the multi-agent reconciliation system.

    Responsibilities:
        1. Instantiate and execute all agents.
        2. Collect and deduplicate issues.
        3. Build a detailed mismatch report (DataFrame).
        4. Build a summary report (dict).
        5. Export reports to CSV.

    Usage:
        coordinator = ReconciliationCoordinator(transactions, settlements)
        coordinator.run()
        detailed = coordinator.get_detailed_report()
        summary  = coordinator.get_summary_report()
        coordinator.export_reports("output/")
    """

    def __init__(self, transactions: pd.DataFrame, settlements: pd.DataFrame):
        self.transactions = transactions.copy()
        self.settlements = settlements.copy()

        # Agent instances
        self.agents: List[ReconciliationAgent] = [AgentCls() for AgentCls in ALL_AGENTS]
        self.matching_agent: Optional[MatchingAgent] = None

        # Results
        self._issues: List[Issue] = []
        self._detailed_report: Optional[pd.DataFrame] = None
        self._summary: Optional[Dict[str, Any]] = None

    # ----- public API -----

    def run(self) -> None:
        """Execute all agents and aggregate findings."""
        all_issues: List[Issue] = []

        for agent in self.agents:
            findings = agent.analyze(self.transactions, self.settlements)
            all_issues.extend(findings)

            # Store reference to matching agent for stats
            if isinstance(agent, MatchingAgent):
                self.matching_agent = agent

        # Deduplicate: same (transaction_id, issue_type) keeps first
        self._issues = self._deduplicate(all_issues)

        # Build reports
        self._detailed_report = self._build_detailed_report()
        self._summary = self._build_summary()

    def get_detailed_report(self) -> pd.DataFrame:
        """Return the detailed mismatch report as a DataFrame."""
        if self._detailed_report is None:
            raise RuntimeError("Call run() before accessing reports.")
        report = self._detailed_report
        return report.copy()

    def get_summary_report(self) -> Dict[str, Any]:
        """Return the summary report as a dictionary."""
        if self._summary is None:
            raise RuntimeError("Call run() before accessing reports.")
        summary = self._summary
        return dict(summary)

    def export_reports(self, output_dir: str = "output") -> Tuple[str, str]:
        """
        Export detailed and summary reports to CSV files.

        Returns:
            (detailed_csv_path, summary_csv_path)
        """
        os.makedirs(output_dir, exist_ok=True)

        detailed_path = os.path.join(output_dir, "detailed_report.csv")
        summary_path = os.path.join(output_dir, "summary_report.csv")

        detailed = self.get_detailed_report()
        detailed.to_csv(detailed_path, index=False)

        # Convert summary dict to a readable DataFrame
        summary = self.get_summary_report()
        summary_rows = []

        # Top-level stats
        for key in ["total_transactions", "total_settlements",
                     "total_matched", "total_mismatched", "total_issues"]:
            summary_rows.append({"metric": key, "value": summary.get(key, 0)})

        # Issue breakdown
        for issue_type, count in summary.get("breakdown_by_issue_type", {}).items():
            summary_rows.append({
                "metric": f"issue_type:{issue_type}",
                "value": count,
            })

        # Severity breakdown
        for severity, count in summary.get("breakdown_by_severity", {}).items():
            summary_rows.append({
                "metric": f"severity:{severity}",
                "value": count,
            })

        pd.DataFrame(summary_rows).to_csv(summary_path, index=False)

        return detailed_path, summary_path

    # ----- private helpers -----

    @staticmethod
    def _deduplicate(issues: List[Issue]) -> List[Issue]:
        """Remove duplicate issues (same transaction_id + issue_type)."""
        seen = set()
        unique = []
        for issue in issues:
            key = (issue.transaction_id, issue.issue_type)
            if key not in seen:
                seen.add(key)
                unique.append(issue)
        return unique

    def _build_detailed_report(self) -> pd.DataFrame:
        """Create a DataFrame from all deduplicated issues."""
        if not self._issues:
            return pd.DataFrame(
                columns=["transaction_id", "issue_type", "description", "severity"]
            )
        return pd.DataFrame([issue.to_dict() for issue in self._issues])

    def _build_summary(self) -> Dict[str, Any]:
        """Create a summary statistics dictionary."""
        detailed = self._detailed_report
        txn_ids_unique = self.transactions["transaction_id"].nunique()
        stl_ids_unique = self.settlements["transaction_id"].nunique()

        matched = 0
        if self.matching_agent and self.matching_agent.matched is not None:
            matched = len(self.matching_agent.matched)

        mismatched_ids = set()
        if detailed is not None and not detailed.empty:
            mismatched_ids = set(detailed["transaction_id"].unique())

        issue_type_counts = {}
        severity_counts = {}
        if detailed is not None and not detailed.empty:
            issue_type_counts = detailed["issue_type"].value_counts().to_dict()
            severity_counts = detailed["severity"].value_counts().to_dict()

        return {
            "total_transactions": len(self.transactions),
            "total_unique_transaction_ids": txn_ids_unique,
            "total_settlements": len(self.settlements),
            "total_unique_settlement_txn_ids": stl_ids_unique,
            "total_matched": matched,
            "total_mismatched": len(mismatched_ids),
            "total_issues": len(detailed) if detailed is not None else 0,
            "breakdown_by_issue_type": issue_type_counts,
            "breakdown_by_severity": severity_counts,
        }
