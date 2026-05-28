#!/usr/bin/env python3
"""
Database Audit and Repair Script - v0.4.7

Scans prompt_history.db for data anomalies and repairs them from output files.

Usage:
    python scripts/audit_and_repair_prompt_history.py          # Dry-run, only report
    python scripts/audit_and_repair_prompt_history.py --repair # Actually repair
"""

import sys
import os
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime


class PromptHistoryAuditor:
    def __init__(self, db_path: str, outputs_dir: str):
        self.db_path = db_path
        self.outputs_dir = Path(outputs_dir)
        self.issues = []
        self.repairs = []

    def connect_db(self):
        """Connect to database"""
        return sqlite3.connect(self.db_path)

    def backup_db(self):
        """Backup database before repair"""
        backup_name = f"{self.db_path}.repair_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        import shutil
        shutil.copy2(self.db_path, backup_name)
        print(f"[BACKUP] Database backed up to: {backup_name}")
        return backup_name

    def audit(self):
        """Audit all prompt_history records"""
        conn = self.connect_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, title, topic_group_id, version_number, slug,
                   prompt_text, preview_text, overview_cn, output_dir,
                   length(prompt_text) as prompt_len,
                   length(preview_text) as preview_len,
                   length(overview_cn) as overview_len
            FROM prompt_history
            ORDER BY id
        """)

        records = cursor.fetchall()
        conn.close()

        print(f"\n{'='*80}")
        print(f"Database Audit Report - Total Records: {len(records)}")
        print(f"{'='*80}\n")

        for record in records:
            (id, title, topic_group_id, version_number, slug,
             prompt_text, preview_text, overview_cn, output_dir,
             prompt_len, preview_len, overview_len) = record

            issues = []

            # Check 1: prompt_text is empty
            if prompt_len == 0:
                issues.append("prompt_text_empty")

            # Check 2: prompt_text is suspiciously short
            elif prompt_len < 500:
                issues.append(f"prompt_text_too_short({prompt_len})")

            # Check 3: CRITICAL - prompt_text polluted with preview format
            if prompt_text:
                # Check if starts with preview format indicators (pollution)
                if prompt_text.strip().startswith("BASIC INFO"):
                    issues.append("RAW_POLLUTED_BASIC_INFO")
                elif prompt_text.strip().startswith("PROBLEM & ANSWER"):
                    issues.append("RAW_POLLUTED_PROBLEM_ANSWER")
                elif prompt_text.strip().startswith("PROBLEM AND ANSWER"):
                    issues.append("RAW_POLLUTED_PROBLEM_AND_ANSWER")

                # Check if missing required NotebookLM markers
                has_notebooklm = "NotebookLM" in prompt_text or "notebooklm" in prompt_text.lower()
                has_title = "## Title" in prompt_text
                has_topic = "## Topic" in prompt_text

                if not has_notebooklm and not has_title and not has_topic:
                    # Likely polluted or corrupted
                    issues.append("prompt_text_missing_markers")

            # Check 4: preview_text is empty (less critical)
            if preview_len == 0:
                issues.append("preview_text_empty")

            # Check 5: overview is empty (less critical)
            if overview_len == 0:
                issues.append("overview_cn_empty")

            # Check 6: output_dir exists
            has_output_dir = False
            source_file = None
            if output_dir:
                output_path = Path(output_dir)
                if output_path.exists():
                    has_output_dir = True
                    source_file = output_path / "notebooklm_clean_source.txt"

            # Also check outputs/<slug>/
            if slug:
                slug_output = self.outputs_dir / slug / "notebooklm_clean_source.txt"
                if slug_output.exists():
                    source_file = slug_output
                    has_output_dir = True

            if issues:
                issue_str = " + ".join(issues)
                # HIGH severity for: empty, too short, or POLLUTED
                severity = "HIGH" if (
                    "prompt_text_empty" in issues or
                    "prompt_text_too_short" in issue_str or
                    "RAW_POLLUTED_BASIC_INFO" in issues or
                    "RAW_POLLUTED_PROBLEM_ANSWER" in issues or
                    "RAW_POLLUTED_PROBLEM_AND_ANSWER" in issues
                ) else "MEDIUM"

                self.issues.append({
                    "id": id,
                    "title": title,
                    "slug": slug,
                    "issues": issues,
                    "severity": severity,
                    "prompt_len": prompt_len,
                    "has_source_file": source_file and source_file.exists(),
                    "source_file": source_file
                })

                source_status = f"source_available={source_file}" if source_file and source_file.exists() else "no_source"
                print(f"[{severity}] id={id} title={title[:40]} issues={issue_str} {source_status}")

        print(f"\n{'='*80}")
        print(f"Total Issues: {len(self.issues)}")
        high_issues = [i for i in self.issues if i['severity'] == 'HIGH']
        print(f"High Severity: {len(high_issues)}")
        repairable = [i for i in self.issues if i['has_source_file']]
        print(f"Repairable: {len(repairable)}")
        print(f"{'='*80}\n")

    def repair(self):
        """Repair records using source files"""
        if not self.issues:
            print("[OK] No issues found. Nothing to repair.")
            return

        repairable = [i for i in self.issues if i['has_source_file']]
        if not repairable:
            print("[WARN] No repairable issues found (no source files available).")
            return

        # Backup database first
        self.backup_db()

        conn = self.connect_db()
        cursor = conn.cursor()

        print(f"\n{'='*80}")
        print(f"Repairing {len(repairable)} records...")
        print(f"{'='*80}\n")

        for issue in repairable:
            id = issue['id']
            source_file = issue['source_file']
            old_len = issue['prompt_len']

            try:
                # Read source file
                with open(source_file, 'r', encoding='utf-8') as f:
                    new_prompt_text = f.read()

                new_len = len(new_prompt_text)

                # Only repair if new content is valid
                if new_len < 500:
                    print(f"[SKIP] id={id} source_file_too_short={new_len}")
                    continue

                # Update database
                cursor.execute("""
                    UPDATE prompt_history
                    SET prompt_text = ?
                    WHERE id = ?
                """, (new_prompt_text, id))

                print(f"[REPAIR] id={id} title={issue['title'][:40]} old_len={old_len} new_len={new_len} source={source_file}")

                self.repairs.append({
                    "id": id,
                    "title": issue['title'],
                    "old_len": old_len,
                    "new_len": new_len,
                    "source": str(source_file)
                })

            except Exception as e:
                print(f"[ERROR] id={id} failed to repair: {e}")

        conn.commit()
        conn.close()

        print(f"\n{'='*80}")
        print(f"Repair Summary: {len(self.repairs)} records repaired")
        print(f"{'='*80}\n")

    def verify(self):
        """Verify repairs by re-auditing"""
        print(f"\n{'='*80}")
        print("Verification: Re-auditing after repair...")
        print(f"{'='*80}")

        self.issues = []  # Reset issues
        self.audit()


def main():
    parser = argparse.ArgumentParser(description="Audit and repair prompt_history database")
    parser.add_argument('--repair', action='store_true', help='Actually repair (default: dry-run)')
    parser.add_argument('--db', default='data/prompt_history.db', help='Database path')
    parser.add_argument('--outputs', default='outputs', help='Outputs directory')
    args = parser.parse_args()

    # Check if database exists
    if not os.path.exists(args.db):
        print(f"[ERROR] Database not found: {args.db}")
        sys.exit(1)

    auditor = PromptHistoryAuditor(args.db, args.outputs)

    # Always audit first
    auditor.audit()

    # Repair if requested
    if args.repair:
        auditor.repair()
        auditor.verify()
    else:
        print("[DRY-RUN] To actually repair, run with --repair flag")


if __name__ == "__main__":
    main()
