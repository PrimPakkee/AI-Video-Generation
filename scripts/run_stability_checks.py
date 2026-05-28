#!/usr/bin/env python3
"""
Prompt Mode Stability Checks Script (v0.4.10)

Runs read-only checks for code and database integrity. Does not call
external APIs and does not modify the database.

Usage:
    python scripts/run_stability_checks.py
"""

STABILITY_CHECKS_VERSION = "v0.4.10"

import sys
import os
import subprocess
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta


class StabilityChecker:
    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = 0

    def check_python_compile(self):
        """Check Python syntax by compilation"""
        print("\n" + "="*80)
        print("Python Compilation Check")
        print("="*80)

        py_files = [
            "web/app.py",
            "web/db/repository.py",
            "web/db/repository_review.py",
            "web/db/database.py",
            "web/db/models.py",
            "scripts/llm_topic_enhancer.py",
            "scripts/audit_and_repair_prompt_history.py",
            "scripts/run_stability_checks.py",
            "scripts/cleanup_ai_reviews.py"
        ]

        all_passed = True
        for py_file in py_files:
            result = subprocess.run(
                ["python3", "-m", "py_compile", py_file],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"  [OK] {py_file}")
            else:
                print(f"  [FAIL] {py_file}")
                print(f"    Error: {result.stderr}")
                all_passed = False

        if all_passed:
            print("\n[OK] Python compilation passed")
            self.checks_passed += 1
        else:
            print("\n[FAIL] Python compilation failed")
            self.checks_failed += 1

    def check_js_syntax(self):
        """Check JavaScript syntax"""
        print("\n" + "="*80)
        print("JavaScript Syntax Check")
        print("="*80)

        js_files = [
            "web/static/main.js",
            "web/static/ai_review.js"
        ]

        all_passed = True
        for js_file in js_files:
            result = subprocess.run(
                ["node", "--check", js_file],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"  [OK] {js_file}")
            else:
                print(f"  [FAIL] {js_file}")
                print(f"    Error: {result.stderr}")
                all_passed = False

        if all_passed:
            print("\n[OK] JavaScript syntax passed")
            self.checks_passed += 1
        else:
            print("\n[FAIL] JavaScript syntax failed")
            self.checks_failed += 1

    def check_database_integrity(self):
        """Check database integrity"""
        print("\n" + "="*80)
        print("Database Integrity Check")
        print("="*80)

        db_path = "data/prompt_history.db"
        if not os.path.exists(db_path):
            print(f"  [FAIL] Database not found: {db_path}")
            self.checks_failed += 1
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check 1: Empty prompt_text
        cursor.execute("SELECT COUNT(*) FROM prompt_history WHERE prompt_text IS NULL OR prompt_text = ''")
        empty_count = cursor.fetchone()[0]
        if empty_count > 0:
            print(f"  [WARN] {empty_count} records with empty prompt_text")
            self.warnings += 1
        else:
            print(f"  [OK] No empty prompt_text")

        # Check 2: Short prompt_text
        cursor.execute("SELECT id, title, length(prompt_text) as len FROM prompt_history WHERE length(prompt_text) < 500")
        short_records = cursor.fetchall()
        if short_records:
            print(f"  [WARN] {len(short_records)} records with prompt_text < 500 chars:")
            for id, title, length in short_records:
                print(f"    id={id} title={title[:40]} len={length}")
            self.warnings += 1
        else:
            print(f"  [OK] No suspiciously short prompt_text")

        # Check 3: Empty topic_group_id
        cursor.execute("SELECT COUNT(*) FROM prompt_history WHERE topic_group_id IS NULL OR topic_group_id = ''")
        no_group_count = cursor.fetchone()[0]
        if no_group_count > 0:
            print(f"  [WARN] {no_group_count} records without topic_group_id")
            self.warnings += 1
        else:
            print(f"  [OK] All records have topic_group_id")

        # Check 4: Duplicate slugs
        cursor.execute("SELECT slug, COUNT(*) as cnt FROM prompt_history GROUP BY slug HAVING cnt > 1")
        duplicate_slugs = cursor.fetchall()
        if duplicate_slugs:
            print(f"  [WARN] {len(duplicate_slugs)} duplicate slugs:")
            for slug, count in duplicate_slugs:
                print(f"    slug={slug} count={count}")
            self.warnings += 1
        else:
            print(f"  [OK] No duplicate slugs")

        # Check 5: Duplicate version numbers within same topic_group_id
        cursor.execute("""
            SELECT topic_group_id, version_number, COUNT(*) as cnt
            FROM prompt_history
            GROUP BY topic_group_id, version_number
            HAVING cnt > 1
        """)
        duplicate_versions = cursor.fetchall()
        if duplicate_versions:
            print(f"  [WARN] {len(duplicate_versions)} duplicate version numbers:")
            for group_id, version, count in duplicate_versions:
                print(f"    topic_group_id={group_id} version={version} count={count}")
            self.warnings += 1
        else:
            print(f"  [OK] No duplicate version numbers")

        # Check 6: Orphan reviews
        cursor.execute("""
            SELECT pr.id, pr.history_id
            FROM prompt_reviews pr
            LEFT JOIN prompt_history ph ON pr.history_id = ph.id
            WHERE ph.id IS NULL
        """)
        orphan_reviews = cursor.fetchall()
        if orphan_reviews:
            print(f"  [WARN] {len(orphan_reviews)} orphan reviews:")
            for review_id, history_id in orphan_reviews:
                print(f"    review_id={review_id} history_id={history_id}")
            self.warnings += 1
        else:
            print(f"  [OK] No orphan reviews")

        # Check 7: Long-running generating status
        cursor.execute("""
            SELECT id, history_id, status, updated_at
            FROM prompt_reviews
            WHERE status = 'generating'
        """)
        generating_reviews = cursor.fetchall()
        now = datetime.utcnow()
        timeout_threshold = now - timedelta(minutes=5)

        stuck_reviews = []
        for id, history_id, status, updated_at in generating_reviews:
            if updated_at:
                updated_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                if updated_dt < timeout_threshold:
                    stuck_reviews.append((id, history_id, updated_at))

        if stuck_reviews:
            print(f"  [WARN] {len(stuck_reviews)} reviews stuck in generating status (>5 min):")
            for id, history_id, updated_at in stuck_reviews:
                print(f"    review_id={id} history_id={history_id} updated_at={updated_at}")
            self.warnings += 1
        else:
            print(f"  [OK] No stuck generating reviews")

        # Check 8: Failed reviews
        cursor.execute("SELECT COUNT(*) FROM prompt_reviews WHERE status = 'failed'")
        failed_count = cursor.fetchone()[0]
        if failed_count > 0:
            print(f"  [INFO] {failed_count} failed reviews (this is OK, just informational)")
        else:
            print(f"  [OK] No failed reviews")

        # Check 9: Stale reviews
        cursor.execute("SELECT COUNT(*) FROM prompt_reviews WHERE status = 'stale'")
        stale_count = cursor.fetchone()[0]
        if stale_count > 0:
            print(f"  [INFO] {stale_count} stale reviews (this is OK, just informational)")
        else:
            print(f"  [OK] No stale reviews")

        conn.close()

        if empty_count == 0 and len(short_records) == 0:
            print("\n[OK] Database integrity check passed")
            self.checks_passed += 1
        else:
            print("\n[WARN] Database has some issues (see warnings above)")
            self.checks_passed += 1  # Not a failure, just warnings

    def check_v049_fixes(self):
        """v0.4.9-specific source-level checks (no external calls, no DB writes)."""
        print("\n" + "="*80)
        print(f"v0.4.9 Fix Sanity Checks")
        print("="*80)

        all_passed = True

        # Check 1: /api/health uses text() wrapper for SQLAlchemy 2.0
        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                app_src = f.read()
            if 'db.execute(text("SELECT 1"))' in app_src:
                print("  [OK] /api/health uses SQLAlchemy 2.0 text() wrapper")
            else:
                print("  [WARN] /api/health may not use text() wrapper")
                self.warnings += 1

            # Check 2: stale review branch surfaces prior review content
            if '"status": "stale"' in app_src and 'stale_review_data' in app_src:
                print("  [OK] /review surfaces prior review content on stale")
            else:
                print("  [WARN] /review stale branch may not return prior review")
                self.warnings += 1

            # Check 3: debug endpoint no longer references invented fields.
            # Use word boundaries so 'record.version_number' is not a false positive.
            import re as _re
            for bad_field in ('record.prompt_id', 'record.version', 'record.prompt_hash'):
                pattern = _re.escape(bad_field) + r'(?![A-Za-z0-9_])'
                if _re.search(pattern, app_src):
                    print(f"  [FAIL] debug endpoint still references {bad_field}")
                    all_passed = False

            # Check 4: web/app.py must have a top-level `import json`.
            # The stale review branch and debug endpoint use json.loads at runtime,
            # so a missing top-level import will cause NameError that gets swallowed
            # by broad `except Exception` and silently returns review: null.
            has_top_level_json_import = False
            for line in app_src.splitlines():
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                # Top-level only: no leading whitespace.
                if line == 'import json' or line.startswith('import json '):
                    has_top_level_json_import = True
                    break
                if line.startswith('import json,') or line.startswith('import json;'):
                    has_top_level_json_import = True
                    break
                # also accept 'from json import ...' at top level
                if line.startswith('from json '):
                    has_top_level_json_import = True
                    break
            if has_top_level_json_import:
                print("  [OK] web/app.py has top-level `import json`")
            else:
                print("  [FAIL] web/app.py is missing top-level `import json` "
                      "(stale review branch will swallow NameError and return null)")
                all_passed = False
        except Exception as e:
            print(f"  [WARN] Could not inspect web/app.py: {e}")
            self.warnings += 1

        # Check 4: Cleanup script exists
        if os.path.exists("scripts/cleanup_ai_reviews.py"):
            print("  [OK] scripts/cleanup_ai_reviews.py present")
        else:
            print("  [FAIL] scripts/cleanup_ai_reviews.py missing")
            all_passed = False

        # Check 5: Stuck generating reviews warning is preserved by integrity check
        # (the actual count is reported by check_database_integrity).
        print("  [INFO] Stuck-generating warning is reported by Database Integrity Check")

        if all_passed:
            print(f"\n[OK] {STABILITY_CHECKS_VERSION} fix sanity checks passed")
            self.checks_passed += 1
        else:
            print(f"\n[FAIL] {STABILITY_CHECKS_VERSION} fix sanity checks failed")
            self.checks_failed += 1

    def check_v0410_fixes(self):
        """v0.4.10-specific source-level checks (read-only)."""
        print("\n" + "="*80)
        print("v0.4.10 Fix Sanity Checks")
        print("="*80)

        all_passed = True

        # Check 1: download_all endpoint adds ai_review.md and metadata.json
        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                app_src = f.read()
            if "'ai_review.md'" in app_src or '"ai_review.md"' in app_src:
                print("  [OK] download_all bundles ai_review.md")
            else:
                print("  [FAIL] download_all is missing ai_review.md entry")
                all_passed = False
            if "'metadata.json'" in app_src or '"metadata.json"' in app_src:
                print("  [OK] download_all bundles metadata.json")
            else:
                print("  [FAIL] download_all is missing metadata.json entry")
                all_passed = False
            if "_build_ai_review_markdown" in app_src:
                print("  [OK] _build_ai_review_markdown helper present")
            else:
                print("  [WARN] _build_ai_review_markdown helper missing")
                self.warnings += 1
        except Exception as e:
            print(f"  [WARN] Could not inspect web/app.py: {e}")
            self.warnings += 1

        # Check 2: Frontend getOverviewPlainText helper exists and is used
        try:
            with open("web/static/main.js", "r", encoding="utf-8") as f:
                main_src = f.read()
            if "function getOverviewPlainText" in main_src:
                print("  [OK] main.js defines getOverviewPlainText()")
            else:
                print("  [FAIL] main.js missing getOverviewPlainText() helper")
                all_passed = False
            if "getOverviewPlainText()" in main_src:
                # Make sure it is referenced in copy / download paths.
                used_in_copy_or_download = main_src.count("getOverviewPlainText()") >= 2
                if used_in_copy_or_download:
                    print("  [OK] getOverviewPlainText() used in copy + download paths")
                else:
                    print("  [WARN] getOverviewPlainText() referenced fewer than 2 times")
                    self.warnings += 1
        except Exception as e:
            print(f"  [WARN] Could not inspect web/static/main.js: {e}")
            self.warnings += 1

        # Check 3: AI Review table has exactly 5-col header and no duplicate weight
        try:
            with open("web/static/ai_review.js", "r", encoding="utf-8") as f:
                review_src = f.read()
            weight_th_count = review_src.count(">Weight</th>")
            if weight_th_count == 1:
                print("  [OK] ai_review.js has exactly one Weight <th>")
            else:
                print(f"  [FAIL] ai_review.js has {weight_th_count} Weight <th> entries (expected 1)")
                all_passed = False
        except Exception as e:
            print(f"  [WARN] Could not inspect web/static/ai_review.js: {e}")
            self.warnings += 1

        # Check 4: Freeze spec doc exists
        if os.path.exists("docs/prompt_mode_freeze_spec.md"):
            print("  [OK] docs/prompt_mode_freeze_spec.md present")
        else:
            print("  [FAIL] docs/prompt_mode_freeze_spec.md missing")
            all_passed = False

        # Check 5: download_all() must NOT call get_review_status().
        # download_all is a GET endpoint and must be read-only;
        # get_review_status() may mutate the DB by marking stuck
        # generating reviews as failed.
        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                _src = f.read()
            marker = "async def download_all"
            start = _src.find(marker)
            if start == -1:
                print("  [WARN] Could not locate download_all() in web/app.py")
                self.warnings += 1
            else:
                # Find the end of the function: next top-level @app. decorator
                # or top-level `def `/`async def ` after `start`.
                tail = _src[start:]
                # Skip past the def line itself before searching for the next route.
                next_route = tail.find("\n@app.", 1)
                next_top_def = tail.find("\nasync def ", 1)
                next_plain_def = tail.find("\ndef ", 1)
                candidates = [c for c in (next_route, next_top_def, next_plain_def) if c != -1]
                end = min(candidates) if candidates else len(tail)
                body = tail[:end]
                # Strip whole-line comments so doc/comments mentioning the
                # forbidden call don't trigger a false positive. Inline `#`
                # comments are also stripped per line.
                code_only_lines = []
                for line in body.splitlines():
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if "#" in line:
                        line = line.split("#", 1)[0]
                    code_only_lines.append(line)
                code_only = "\n".join(code_only_lines)
                if "get_review_status(" in code_only:
                    print("  [FAIL] download_all() calls get_review_status() "
                          "(must be strictly read-only — would mutate DB)")
                    all_passed = False
                else:
                    print("  [OK] download_all() does not call get_review_status()")

                # download_all() must NOT use get_review_by_history_id() either:
                # that helper filters to the current schema and would hide
                # legacy reviews that v0.4.10 expects to export as stale.
                if "get_review_by_history_id(" in code_only:
                    print("  [FAIL] download_all() calls get_review_by_history_id() "
                          "(filters current schema only — legacy reviews would be lost)")
                    all_passed = False
                else:
                    print("  [OK] download_all() does not call get_review_by_history_id()")

                # And it must directly query the PromptReview table so legacy
                # schema rows are visible.
                if "PromptReview" in code_only and "db.query(PromptReview)" in code_only:
                    print("  [OK] download_all() reads PromptReview directly (db.query)")
                else:
                    print("  [FAIL] download_all() must read PromptReview directly via "
                          "db.query(PromptReview) for legacy-schema export support")
                    all_passed = False
        except Exception as e:
            print(f"  [WARN] Could not scan download_all() body: {e}")
            self.warnings += 1

        if all_passed:
            print(f"\n[OK] {STABILITY_CHECKS_VERSION} fix sanity checks passed")
            self.checks_passed += 1
        else:
            print(f"\n[FAIL] {STABILITY_CHECKS_VERSION} fix sanity checks failed")
            self.checks_failed += 1

    def check_required_files(self):
        """Check required files exist"""
        import glob

        print("\n" + "="*80)
        print("Required Files Check")
        print("="*80)

        # Core files - missing any of these is a hard FAIL.
        required_files = [
            "web/app.py",
            "web/db/database.py",
            "web/db/models.py",
            "web/db/repository.py",
            "web/db/repository_review.py",
            "web/static/main.js",
            "web/static/ai_review.js",
            "web/static/style.css",
            "web/static/index.html",
            "scripts/llm_topic_enhancer.py",
            "data/prompt_history.db",
        ]

        # Doc presence checks: use version-prefix globs instead of exact
        # Chinese filenames so cross-platform encoding quirks don't cause
        # false FAILs. Missing docs are a WARN, not a FAIL.
        required_doc_globs = [
            "docs/v0.4.6.9_*.md",
            "docs/v0.4.6.8_*.md",
            "docs/prompt_mode_freeze_spec.md",
        ]

        all_exist = True
        for file_path in required_files:
            if os.path.exists(file_path):
                print(f"  [OK] {file_path}")
            else:
                print(f"  [FAIL] Missing: {file_path}")
                all_exist = False

        for pattern in required_doc_globs:
            matches = glob.glob(pattern)
            if matches:
                print(f"  [OK] {pattern} -> {os.path.basename(matches[0])}")
            else:
                print(f"  [WARN] No doc matches pattern: {pattern}")
                self.warnings += 1

        if all_exist:
            print("\n[OK] All required core files exist")
            self.checks_passed += 1
        else:
            print("\n[FAIL] Some required files are missing")
            self.checks_failed += 1

    def print_summary(self):
        """Print final summary"""
        print("\n" + "="*80)
        print("Stability Check Summary")
        print("="*80)
        print(f"  Checks Passed: {self.checks_passed}")
        print(f"  Checks Failed: {self.checks_failed}")
        print(f"  Warnings: {self.warnings}")
        print("="*80 + "\n")

        if self.checks_failed == 0:
            print("✅ ALL CHECKS PASSED")
            if self.warnings > 0:
                print(f"⚠️  {self.warnings} warnings (see details above)")
            return 0
        else:
            print(f"❌ {self.checks_failed} CHECKS FAILED")
            return 1


def main():
    print("\n" + "="*80)
    print(f"Prompt Mode Stability Checks - {STABILITY_CHECKS_VERSION}")
    print("="*80)

    checker = StabilityChecker()

    try:
        checker.check_required_files()
        checker.check_python_compile()
        checker.check_js_syntax()
        checker.check_v049_fixes()
        checker.check_v0410_fixes()
        checker.check_database_integrity()
    except Exception as e:
        print(f"\n[ERROR] Stability check failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    exit_code = checker.print_summary()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
