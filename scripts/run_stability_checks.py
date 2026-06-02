#!/usr/bin/env python3
"""
Prompt Mode + Video Mode Stability Checks Script (v0.5.4)

Runs read-only checks for code and database integrity. Does not call
external APIs and does not modify any database.

Usage:
    python scripts/run_stability_checks.py
"""

STABILITY_CHECKS_VERSION = "v0.5.4"

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
            "web/db/video_database.py",
            "web/db/video_models.py",
            "web/db/video_repository.py",
            "web/db/video_job_repository.py",
            "web/video_providers/__init__.py",
            "web/video_providers/base.py",
            "web/video_providers/mock_provider.py",
            "web/video_asset_pipeline.py",
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

    def check_v051_fixes(self):
        """v0.5.1-specific source-level checks (read-only).

        Validates Video Mode framework wiring without touching any database,
        invoking any LLM, downloading anything, or starting a server.
        """
        print("\n" + "="*80)
        print("v0.5.1 Fix Sanity Checks")
        print("="*80)

        all_passed = True

        # 1) Frontend Mode Selector DOM elements present in index.html.
        try:
            with open("web/static/index.html", "r", encoding="utf-8") as f:
                html_src = f.read()
            for needle, label in (
                ("mode-selector", "mode-selector container"),
                ("mode-selector-btn", "mode-selector-btn"),
                ("mode-dropdown", "mode-dropdown"),
                ("mode-option", "mode-option"),
            ):
                if needle in html_src:
                    print(f"  [OK] index.html has {label}")
                else:
                    print(f"  [FAIL] index.html missing {label}")
                    all_passed = False

            # 1b) Prompt Mode 4 view-mode tabs (raw/preview/overview/review)
            # buttons must be preserved.
            for tab in ('data-mode="raw"', 'data-mode="preview"',
                        'data-mode="overview"', 'data-mode="review"'):
                if tab in html_src:
                    print(f"  [OK] index.html preserves Prompt Mode tab {tab}")
                else:
                    print(f"  [FAIL] index.html missing Prompt Mode tab {tab}")
                    all_passed = False
        except Exception as e:
            print(f"  [WARN] Could not inspect web/static/index.html: {e}")
            self.warnings += 1

        # 2) Frontend mode-aware helpers in main.js.
        try:
            with open("web/static/main.js", "r", encoding="utf-8") as f:
                main_src = f.read()
            for needle, label in (
                ("currentAppMode", "currentAppMode state"),
                ("switchAppMode", "switchAppMode() function"),
                ("getApiPrefix", "getApiPrefix() helper"),
            ):
                if needle in main_src:
                    print(f"  [OK] main.js defines {label}")
                else:
                    print(f"  [FAIL] main.js missing {label}")
                    all_passed = False

            # 2b) No hardcoded real video URL / file references in frontend
            # (the v0.5.1 player must remain src-less).
            import re as _re
            forbidden_video = _re.search(
                r'https?://[^\s"\'`]+\.(?:mp4|mov|m3u8|webm)',
                main_src,
                flags=_re.IGNORECASE,
            )
            if forbidden_video:
                print(f"  [FAIL] main.js contains hardcoded video URL: "
                      f"{forbidden_video.group(0)}")
                all_passed = False
            else:
                print("  [OK] main.js has no hardcoded video URL")
        except Exception as e:
            print(f"  [WARN] Could not inspect web/static/main.js: {e}")
            self.warnings += 1

        # 3) Backend /api/video/* endpoints registered in app.py.
        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                app_src = f.read()
            for endpoint in ('"/api/video/generate"', '"/api/video/history"'):
                if endpoint in app_src:
                    print(f"  [OK] app.py registers {endpoint}")
                else:
                    print(f"  [FAIL] app.py missing endpoint {endpoint}")
                    all_passed = False

            # 3b) /api/health must report video_database field.
            if "video_database" in app_src:
                print("  [OK] /api/health exposes video_database field")
            else:
                print("  [FAIL] /api/health missing video_database field")
                all_passed = False

            # 3c) init_video_db must be wired into startup.
            if "init_video_db" in app_src:
                print("  [OK] app.py wires init_video_db()")
            else:
                print("  [FAIL] app.py missing init_video_db() wiring")
                all_passed = False
        except Exception as e:
            print(f"  [WARN] Could not inspect web/app.py: {e}")
            self.warnings += 1

        # 4) Video Mode DB layer files exist.
        for path in (
            "web/db/video_database.py",
            "web/db/video_models.py",
            "web/db/video_repository.py",
        ):
            if os.path.exists(path):
                print(f"  [OK] {path} present")
            else:
                print(f"  [FAIL] {path} missing")
                all_passed = False

        # 5) Prompt Mode freeze spec preserved.
        if os.path.exists("docs/prompt_mode_freeze_spec.md"):
            print("  [OK] docs/prompt_mode_freeze_spec.md preserved")
        else:
            print("  [FAIL] docs/prompt_mode_freeze_spec.md missing")
            all_passed = False

        # 6) v0.5.2 design doc exists (collapsed v0.5.1 / v0.5.1.2 docs into
        #    a single v0.5.2 release-note doc).
        if os.path.exists("docs/v0.5.2_video_mode_framework.md"):
            print("  [OK] docs/v0.5.2_video_mode_framework.md present")
        else:
            print("  [WARN] docs/v0.5.2_video_mode_framework.md missing")
            self.warnings += 1

        # 7) .gitignore must keep data/video_history.db (and other video DB
        # artifacts) out of Git.
        try:
            if os.path.exists(".gitignore"):
                with open(".gitignore", "r", encoding="utf-8") as f:
                    gi_src = f.read()
                gi_lines = [ln.strip() for ln in gi_src.splitlines()
                            if ln.strip() and not ln.strip().startswith("#")]
                covered = any(
                    pat in gi_lines
                    for pat in (
                        "data/video_history.db",
                        "data/*.db",
                        "data/**/*.db",
                        "*.db",
                    )
                )
                if covered:
                    print("  [OK] .gitignore covers data/video_history.db")
                else:
                    print("  [FAIL] .gitignore does not cover "
                          "data/video_history.db (must not be committed)")
                    all_passed = False
            else:
                print("  [WARN] .gitignore not found")
                self.warnings += 1
        except Exception as e:
            print(f"  [WARN] Could not inspect .gitignore: {e}")
            self.warnings += 1

        if all_passed:
            print(f"\n[OK] {STABILITY_CHECKS_VERSION} fix sanity checks passed")
            self.checks_passed += 1
        else:
            print(f"\n[FAIL] {STABILITY_CHECKS_VERSION} fix sanity checks failed")
            self.checks_failed += 1

    def check_v0512_fixes(self):
        """v0.5.1.2-specific source-level checks (read-only).

        Verifies the 12 Video Mode framework fixes wired without touching
        any database, invoking any LLM, or starting a server.
        """
        print("\n" + "="*80)
        print("v0.5.1.2 Fix Sanity Checks")
        print("="*80)

        all_passed = True

        try:
            with open("web/static/main.js", "r", encoding="utf-8") as f:
                main_src = f.read()
        except Exception as e:
            print(f"  [WARN] Could not read web/static/main.js: {e}")
            self.warnings += 1
            main_src = ""

        try:
            with open("web/static/ai_review.js", "r", encoding="utf-8") as f:
                ai_review_src = f.read()
        except Exception as e:
            print(f"  [WARN] Could not read web/static/ai_review.js: {e}")
            self.warnings += 1
            ai_review_src = ""

        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                app_src = f.read()
        except Exception as e:
            print(f"  [WARN] Could not read web/app.py: {e}")
            self.warnings += 1
            app_src = ""

        try:
            with open("web/db/video_repository.py", "r", encoding="utf-8") as f:
                video_repo_src = f.read()
        except Exception as e:
            print(f"  [WARN] Could not read web/db/video_repository.py: {e}")
            self.warnings += 1
            video_repo_src = ""

        try:
            with open("web/static/index.html", "r", encoding="utf-8") as f:
                html_src = f.read()
        except Exception as e:
            print(f"  [WARN] Could not read web/static/index.html: {e}")
            self.warnings += 1
            html_src = ""

        # 1) main.js has currentAppMode/switchAppMode (regression check).
        for needle, label in (
            ("currentAppMode", "currentAppMode state"),
            ("switchAppMode", "switchAppMode() function"),
            ("getApiPrefix", "getApiPrefix() helper"),
            ("apiUrl(", "apiUrl() helper used"),
        ):
            if needle in main_src:
                print(f"  [OK] main.js has {label}")
            else:
                print(f"  [FAIL] main.js missing {label}")
                all_passed = False

        # 2) Default-tab logic uses currentAppMode (Fixes #1, #2).
        if "getDefaultViewMode" in main_src and "currentAppMode === 'video'" in main_src:
            print("  [OK] main.js getDefaultViewMode() branches on currentAppMode")
        else:
            print("  [FAIL] main.js missing mode-aware default tab logic")
            all_passed = False

        # 3) Web Copy support (Fix #7).
        for needle, label in (
            ("'web_copy'", "web_copy mode literal"),
            ("currentWebCopyText", "currentWebCopyText state"),
        ):
            if needle in main_src:
                print(f"  [OK] main.js references {label}")
            else:
                print(f"  [FAIL] main.js missing {label}")
                all_passed = False
        # Web Copy Download writes a {slug}_web_copy.txt file via the
        # filenameSuffix = 'web_copy' branch in downloadPrompt(). Accept
        # either literal filename or the filenameSuffix assignment.
        if "filenameSuffix = 'web_copy'" in main_src or "web_copy.txt" in main_src:
            print("  [OK] main.js downloads web_copy as web_copy.txt")
        else:
            print("  [FAIL] main.js missing web_copy download wiring")
            all_passed = False

        # 4) Video tab unavailable strings (Fix #8, #10).
        for needle in (
            "Video tab cannot be edited.",
            "Video content cannot be copied.",
            "Video file is not available yet.",
            "Video source is not available yet.",
        ):
            if needle in main_src:
                print(f"  [OK] main.js has tooltip/toast string: {needle!r}")
            else:
                print(f"  [FAIL] main.js missing string: {needle!r}")
                all_passed = False

        # 5) Rename uses /api/video/ via apiUrl (Fix #9).
        if "apiUrl(`/history/group/${topicGroupId}/rename`)" in main_src:
            print("  [OK] main.js finishRenameMode uses apiUrl() for rename")
        else:
            print("  [FAIL] main.js finishRenameMode does not route via apiUrl()")
            all_passed = False

        # 6) Backend Video rename endpoint registered (Fix #9).
        if '"/api/video/history/group/{topic_group_id}/rename"' in app_src:
            print("  [OK] app.py registers /api/video/history/group/{id}/rename")
        else:
            print("  [FAIL] app.py missing /api/video/history/group/{id}/rename endpoint")
            all_passed = False
        if "rename_topic_group" in video_repo_src:
            print("  [OK] video_repository defines rename_topic_group()")
        else:
            print("  [FAIL] video_repository missing rename_topic_group()")
            all_passed = False

        # 7) Video versions endpoint returns "versions" key (Fix #3).
        if '"versions"' in app_src and 'video_get_versions' in app_src:
            print("  [OK] app.py video versions endpoint references 'versions'")
        elif '"versions":' in app_src or "'versions':" in app_src:
            print("  [OK] app.py exposes 'versions' key")
        else:
            print("  [FAIL] app.py /api/video/history/group/{id}/versions missing 'versions' key")
            all_passed = False

        # 8) /api/video/generate and /regenerate return topic_group_id and version_number (Fixes #4, #5).
        for needle in (
            '"topic_group_id"',
            '"version_number"',
            '"web_copy_text"',
        ):
            if needle in app_src:
                print(f"  [OK] app.py returns {needle}")
            else:
                print(f"  [FAIL] app.py missing field {needle} in video responses")
                all_passed = False

        # 9) AI Review placeholder + mode guard (Fix #6).
        # In v0.5.3 the v0.5.1.2-specific phrasing was replaced with a neutral
        # "AI Review for Video Mode is not connected yet." line.
        if "AI Review for Video Mode is not connected yet." in ai_review_src:
            print("  [OK] ai_review.js has Video Mode placeholder text")
        else:
            print("  [FAIL] ai_review.js missing Video Mode placeholder text")
            all_passed = False
        if "renderVideoReviewPlaceholder" in ai_review_src and "isVideoModeForReview" in ai_review_src:
            print("  [OK] ai_review.js defines mode guard helpers")
        else:
            print("  [FAIL] ai_review.js missing mode guard helpers")
            all_passed = False
        # window.getCurrentAppMode export must exist in main.js.
        if "window.getCurrentAppMode" in main_src:
            print("  [OK] main.js exports window.getCurrentAppMode")
        else:
            print("  [FAIL] main.js missing window.getCurrentAppMode export")
            all_passed = False

        # 10) ai_review.js must NOT call /api/history/{id}/review unguarded.
        # Check: every fetch to that path must be inside a function whose
        # prologue contains the mode guard. We approximate by checking that
        # the file does not have a top-level fetch outside the guarded
        # functions — instead require that loadReview/regenerateReview/
        # startReviewPolling each contain isVideoModeForReview() before any
        # fetch( call.
        guard_failures = []
        for fn_name in ("loadReview", "regenerateReview", "startReviewPolling"):
            # Locate function block
            idx = ai_review_src.find(f"function {fn_name}")
            if idx == -1:
                idx = ai_review_src.find(f"async function {fn_name}")
            if idx == -1:
                guard_failures.append(f"{fn_name} not found")
                continue
            # Slice to the next top-level function definition (rough)
            tail = ai_review_src[idx:idx + 4000]
            fetch_idx = tail.find("fetch(")
            guard_idx = tail.find("isVideoModeForReview")
            if fetch_idx == -1:
                # No fetch in this slice; nothing to guard.
                continue
            if guard_idx == -1 or guard_idx > fetch_idx:
                guard_failures.append(f"{fn_name} fetch() not guarded")
        if not guard_failures:
            print("  [OK] ai_review.js guards every Prompt Mode review fetch in Video Mode")
        else:
            print(f"  [FAIL] ai_review.js mode guard incomplete: {guard_failures}")
            all_passed = False

        # 11) No video_review table introduced.
        for src_name, src in (
            ("web/app.py", app_src),
            ("web/db/video_repository.py", video_repo_src),
        ):
            if "video_review" in src.lower():
                print(f"  [FAIL] {src_name} introduces video_review (forbidden)")
                all_passed = False
            else:
                print(f"  [OK] {src_name} has no video_review table")

        # 12) No Seedance / real video provider strings introduced.
        forbidden_provider_terms = ("seedance", "Seedance", "SEEDANCE")
        any_provider = False
        combined = main_src + ai_review_src + app_src + video_repo_src + html_src
        for term in forbidden_provider_terms:
            if term in combined:
                any_provider = True
                print(f"  [FAIL] forbidden provider keyword {term!r} appears in source")
                all_passed = False
        if not any_provider:
            print("  [OK] no Seedance / real provider keywords introduced")

        # 13) .gitignore covers data/*.db (regression check).
        try:
            if os.path.exists(".gitignore"):
                with open(".gitignore", "r", encoding="utf-8") as f:
                    gi_src = f.read()
                gi_lines = [ln.strip() for ln in gi_src.splitlines()
                            if ln.strip() and not ln.strip().startswith("#")]
                covered = any(
                    pat in gi_lines
                    for pat in (
                        "data/video_history.db",
                        "data/*.db",
                        "data/**/*.db",
                        "*.db",
                    )
                )
                if covered:
                    print("  [OK] .gitignore still covers data/*.db")
                else:
                    print("  [FAIL] .gitignore no longer covers data/*.db")
                    all_passed = False
        except Exception as e:
            print(f"  [WARN] Could not inspect .gitignore: {e}")
            self.warnings += 1

        # 14) Prompt Mode freeze spec + v0.5.2 video framework doc preserved.
        for path in (
            "docs/prompt_mode_freeze_spec.md",
            "docs/v0.5.2_video_mode_framework.md",
        ):
            if os.path.exists(path):
                print(f"  [OK] {path} preserved")
            else:
                print(f"  [FAIL] {path} missing")
                all_passed = False

        # 15) Video Mode loading + empty-state copy strings (Fix #11).
        for needle in (
            "Generating your video assets...",
            "No video topics yet.",
        ):
            if needle in main_src:
                print(f"  [OK] main.js has copy: {needle!r}")
            else:
                print(f"  [FAIL] main.js missing copy: {needle!r}")
                all_passed = False

        # 16) Loading element id present in HTML.
        if 'id="loading-text"' in html_src:
            print("  [OK] index.html exposes #loading-text for mode-aware copy")
        else:
            print("  [FAIL] index.html missing #loading-text id")
            all_passed = False

        # 17) Web Copy edit textarea wired.
        if 'id="web-copy-edit-textarea"' in html_src:
            print("  [OK] index.html has #web-copy-edit-textarea")
        else:
            print("  [FAIL] index.html missing #web-copy-edit-textarea")
            all_passed = False

        # 18) showAppToast helper defined.
        if "function showAppToast" in main_src and "window.showAppToast" in main_src:
            print("  [OK] main.js defines showAppToast and exports it")
        else:
            print("  [FAIL] main.js missing showAppToast helper or window export")
            all_passed = False

        if all_passed:
            print(f"\n[OK] {STABILITY_CHECKS_VERSION} fix sanity checks passed")
            self.checks_passed += 1
        else:
            print(f"\n[FAIL] {STABILITY_CHECKS_VERSION} fix sanity checks failed")
            self.checks_failed += 1

    def check_v0512_ui_hotfix(self):
        """v0.5.1.2 UI hotfix-round source-level checks (read-only).

        Verifies the in-frame video toast, unified custom-tooltip wiring,
        per-button unavailable-message routing, and exitEditMode re-entrance
        guard are all in place. Does not touch any DB, LLM, or server.
        """
        print("\n" + "="*80)
        print("v0.5.1.2 UI Hotfix Sanity Checks")
        print("="*80)

        all_passed = True

        try:
            with open("web/static/main.js", "r", encoding="utf-8") as f:
                main_src = f.read()
        except Exception as e:
            print(f"  [WARN] Could not read web/static/main.js: {e}")
            self.warnings += 1
            main_src = ""

        try:
            with open("web/static/style.css", "r", encoding="utf-8") as f:
                css_src = f.read()
        except Exception as e:
            print(f"  [WARN] Could not read web/static/style.css: {e}")
            self.warnings += 1
            css_src = ""

        # 1) main.js defines showVideoPlayerToast helper.
        if "function showVideoPlayerToast" in main_src:
            print("  [OK] main.js defines showVideoPlayerToast()")
        else:
            print("  [FAIL] main.js missing showVideoPlayerToast() helper")
            all_passed = False

        # 2) togglePlay routes the no-source toast through showVideoPlayerToast
        #    with the exact in-frame copy.
        if "showVideoPlayerToast('Video source is not available yet.')" in main_src \
                or 'showVideoPlayerToast("Video source is not available yet.")' in main_src:
            print("  [OK] main.js no-source path uses showVideoPlayerToast()")
        else:
            print("  [FAIL] main.js no-source toast does not use showVideoPlayerToast()")
            all_passed = False

        # 3) style.css defines .video-player-toast positioning.
        if ".video-player-toast" in css_src:
            print("  [OK] style.css defines .video-player-toast")
        else:
            print("  [FAIL] style.css missing .video-player-toast rule")
            all_passed = False

        # 4) updateActionButtonsForCurrentView / setBtnState must NOT call
        #    btn.setAttribute('title', ...) — native browser tooltip is
        #    forbidden in v0.5.1.2 UI hotfix round.
        import re as _re
        forbidden_title_patterns = [
            r"setAttribute\(\s*['\"]title['\"]\s*,",
            r"\.title\s*=\s*tooltipText",
        ]
        title_violations = []
        for pat in forbidden_title_patterns:
            for m in _re.finditer(pat, main_src):
                # Determine 1-based line number for actionable diagnostics.
                line_no = main_src.count("\n", 0, m.start()) + 1
                title_violations.append((line_no, m.group(0)))
        if title_violations:
            print(f"  [FAIL] main.js still sets native title attribute "
                  f"({len(title_violations)} occurrences):")
            for ln, frag in title_violations[:5]:
                print(f"    line {ln}: {frag}")
            all_passed = False
        else:
            print("  [OK] main.js does not set native title attribute on disabled buttons")

        # 5) main.js uses data-unavailable-message as the disabled-state carrier.
        if "data-unavailable-message" in main_src:
            print("  [OK] main.js uses data-unavailable-message")
        else:
            print("  [FAIL] main.js does not use data-unavailable-message")
            all_passed = False

        # 6) Copy button's tooltip text must NOT contain the Download phrase.
        #    The single source of truth is the literal "Video content cannot
        #    be copied." (no Download mention).
        if "Video content cannot be copied." in main_src:
            print("  [OK] main.js Copy tooltip string present")
        else:
            print("  [FAIL] main.js missing Copy tooltip string "
                  "'Video content cannot be copied.'")
            all_passed = False

        # The Copy branch in updateActionButtonsForCurrentView must not also
        # mention the Download phrase. Locate the function and inspect only
        # its copy-button assignment.
        copy_branch_violations = []
        fn_idx = main_src.find("function updateActionButtonsForCurrentView")
        if fn_idx == -1:
            fn_idx = main_src.find("updateActionButtonsForCurrentView = function")
        if fn_idx != -1:
            fn_slice = main_src[fn_idx:fn_idx + 8000]
            # Heuristic: any line in the slice that mentions copyBtn AND
            # references the Download phrase is a violation.
            for line in fn_slice.splitlines():
                if "copy" in line.lower() and \
                        "Download will be available when a video file exists." in line:
                    copy_branch_violations.append(line.strip())
        if copy_branch_violations:
            print("  [FAIL] Copy branch leaks Download phrase:")
            for line in copy_branch_violations[:3]:
                print(f"    {line[:120]}")
            all_passed = False
        else:
            print("  [OK] Copy branch does not mention the Download phrase")

        # 7) Download button's tooltip text combines both sentences.
        download_combined = (
            "Video file is not available yet. "
            "Download will be available when a video file exists."
        )
        if download_combined in main_src:
            print("  [OK] main.js Download tooltip combined sentence present")
        else:
            print("  [FAIL] main.js missing Download tooltip combined sentence")
            all_passed = False

        # 8) No two consecutive exitEditMode() calls.
        consec_exit = _re.search(
            r"exitEditMode\s*\(\s*\)\s*;\s*exitEditMode\s*\(\s*\)\s*;",
            main_src,
        )
        if consec_exit:
            line_no = main_src.count("\n", 0, consec_exit.start()) + 1
            print(f"  [FAIL] main.js has consecutive exitEditMode() calls at line {line_no}")
            all_passed = False
        else:
            print("  [OK] main.js has no consecutive exitEditMode() calls")

        # 9) No two consecutive <span class="icon-tooltip">Save</span> markers
        #    in editBtn.innerHTML assignments.
        save_span = '<span class="icon-tooltip">Save</span>'
        save_dup = _re.search(
            _re.escape(save_span) + r"\s*" + _re.escape(save_span),
            main_src,
        )
        if save_dup:
            line_no = main_src.count("\n", 0, save_dup.start()) + 1
            print(f"  [FAIL] main.js has duplicated Save tooltip span at line {line_no}")
            all_passed = False
        else:
            print("  [OK] main.js has no duplicated Save tooltip span")

        # 10) exitEditMode re-entrance guard wired.
        if "_exitEditModeInFlight" in main_src and "_exitEditModeImpl" in main_src:
            print("  [OK] main.js wraps exitEditMode with re-entrance guard")
        else:
            print("  [FAIL] main.js missing exitEditMode re-entrance guard "
                  "(_exitEditModeInFlight / _exitEditModeImpl)")
            all_passed = False

        # ---- Round 2 (tooltip wrap + Web Copy empty download) ----

        try:
            with open("web/static/index.html", "r", encoding="utf-8") as f:
                html_src = f.read()
        except Exception as e:
            print(f"  [WARN] Could not read web/static/index.html: {e}")
            self.warnings += 1
            html_src = ""

        # 11) Round 4: tooltip rendering moved to a global portal
        #     (.global-icon-tooltip). The legacy in-button .icon-tooltip is
        #     kept as a data source only and must NOT render visually
        #     anymore — we verify it has display:none enforced and that
        #     the global tooltip carries the wrap/max-width/break rules.
        global_idx = css_src.find(".global-icon-tooltip")
        wrap_ok = False
        maxw_ok = False
        breakword_ok = False
        fixed_ok = False
        zindex_ok = False
        if global_idx != -1:
            block = css_src[global_idx:global_idx + 1200]
            if "white-space: normal" in block:
                wrap_ok = True
            if "max-width" in block:
                maxw_ok = True
            if "overflow-wrap" in block or "word-wrap" in block:
                breakword_ok = True
            if "position: fixed" in block:
                fixed_ok = True
            if "z-index:" in block or "z-index :" in block:
                zindex_ok = True
        if wrap_ok:
            print("  [OK] .global-icon-tooltip uses white-space: normal (wraps long copy)")
        else:
            print("  [FAIL] .global-icon-tooltip missing white-space: normal")
            all_passed = False
        if maxw_ok:
            print("  [OK] .global-icon-tooltip has max-width set")
        else:
            print("  [FAIL] .global-icon-tooltip missing max-width")
            all_passed = False
        if breakword_ok:
            print("  [OK] .global-icon-tooltip has overflow-wrap/word-wrap")
        else:
            print("  [FAIL] .global-icon-tooltip missing overflow-wrap/word-wrap")
            all_passed = False
        if fixed_ok:
            print("  [OK] .global-icon-tooltip uses position: fixed")
        else:
            print("  [FAIL] .global-icon-tooltip is not position: fixed "
                  "(would be subject to ancestor stacking contexts)")
            all_passed = False
        if zindex_ok:
            print("  [OK] .global-icon-tooltip declares a z-index")
        else:
            print("  [FAIL] .global-icon-tooltip missing z-index "
                  "(would be hidden by other stacking contexts)")
            all_passed = False

        # 11b) Legacy .icon-tooltip must be visually disabled (no hover-driven
        #      display rule that would surface a second tooltip).
        legacy_hover_present = False
        # Treat any non-commented `.icon-button:hover .icon-tooltip { ... display: ... }`
        # as a violation. We approximate by searching for the hover selector
        # paired with a display-changing block in css_src.
        for sel in (".icon-button:hover .icon-tooltip",
                    ".copy-button.copied .icon-tooltip",
                    ".icon-button.copied .icon-tooltip"):
            sel_idx = css_src.find(sel)
            if sel_idx == -1:
                continue
            # Look for the matching block opener and inspect its body.
            brace_open = css_src.find("{", sel_idx, sel_idx + 200)
            brace_close = css_src.find("}", brace_open, brace_open + 400) if brace_open != -1 else -1
            if brace_open == -1 or brace_close == -1:
                continue
            body = css_src[brace_open + 1:brace_close]
            # If display is set to anything except none, the legacy tooltip
            # would still render.
            import re as _re_legacy
            disp_match = _re_legacy.search(r"display\s*:\s*([^;}\n]+)", body)
            if disp_match and "none" not in disp_match.group(1).lower():
                legacy_hover_present = True
                print(f"  [FAIL] legacy '{sel}' still surfaces tooltip via "
                      f"display: {disp_match.group(1).strip()}")
        if not legacy_hover_present:
            print("  [OK] legacy .icon-tooltip hover rules do not surface a second tooltip")
        else:
            all_passed = False
        # And the .icon-tooltip rule itself should explicitly hide the span.
        # Look for the rule body (with `{`), not the first textual mention
        # (which may live inside a /* ... */ comment).
        ict_idx = css_src.find(".icon-tooltip {")
        if ict_idx == -1:
            ict_idx = css_src.find(".icon-tooltip{")
        if ict_idx != -1:
            ict_block = css_src[ict_idx:ict_idx + 400]
            if "display: none" in ict_block or "display:none" in ict_block:
                print("  [OK] .icon-tooltip span is hidden (data-source only)")
            else:
                print("  [FAIL] .icon-tooltip span is not hidden — would render alongside global tooltip")
                all_passed = False
        else:
            print("  [FAIL] no .icon-tooltip rule body found in style.css")
            all_passed = False

        # 13) Round 3: right-align tooltip variant must be GONE everywhere.
        right_align_violations = []
        if 'data-tooltip-align="right"' in css_src \
                or "data-tooltip-align='right'" in css_src \
                or "[data-tooltip-align=\"right\"]" in css_src \
                or "[data-tooltip-align='right']" in css_src:
            right_align_violations.append("style.css")
        if 'data-tooltip-align="right"' in html_src \
                or "data-tooltip-align='right'" in html_src:
            right_align_violations.append("index.html")
        if "setAttribute('data-tooltip-align'" in main_src \
                or 'setAttribute("data-tooltip-align"' in main_src \
                or "data-tooltip-align', 'right'" in main_src \
                or 'data-tooltip-align", "right"' in main_src:
            right_align_violations.append("main.js")
        if right_align_violations:
            print(f"  [FAIL] right-align tooltip mechanism still present in: "
                  f"{', '.join(right_align_violations)}")
            all_passed = False
        else:
            print("  [OK] right-align tooltip mechanism is fully removed")

        # 14) Round 4: .tooltip-below is now a *marker class* consulted by
        #     the JS placement helper getIconTooltipPlacement (CSS no longer
        #     drives the placement). Verify the helper honors the marker.
        place_idx = main_src.find("function getIconTooltipPlacement")
        if place_idx != -1:
            place_body = main_src[place_idx:place_idx + 400]
            if ("classList.contains('tooltip-below')" in place_body
                    or 'classList.contains("tooltip-below")' in place_body) \
                    and "'below'" in place_body:
                print("  [OK] getIconTooltipPlacement honors .tooltip-below marker (returns 'below')")
            else:
                print("  [FAIL] getIconTooltipPlacement does not branch on "
                      ".tooltip-below — long Download tooltip will not render below")
                all_passed = False
        else:
            print("  [FAIL] getIconTooltipPlacement not defined; cannot verify "
                  ".tooltip-below behavior")
            all_passed = False

        # 15) main.js must add tooltip-below to the Video tab Download button
        #     and clear it when leaving Video tab.
        if "downloadBtnEl.classList.add('tooltip-below')" in main_src \
                or 'downloadBtnEl.classList.add("tooltip-below")' in main_src:
            print("  [OK] main.js adds tooltip-below to Video tab Download button")
        else:
            print("  [FAIL] main.js does not add tooltip-below to Video tab Download button")
            all_passed = False
        # The cleanup must remove tooltip-below from edit/copy/download on
        # every tab change.
        if "classList.remove('tooltip-below')" in main_src \
                or 'classList.remove("tooltip-below")' in main_src:
            print("  [OK] main.js clears tooltip-below on tab change")
        else:
            print("  [FAIL] main.js never clears tooltip-below "
                  "(Prompt Mode would inherit Video tab placement)")
            all_passed = False

        # 16) Round 3: copy/edit/preview/overview must NOT carry tooltip-below
        #     in source. We approximate this by ensuring tooltip-below is only
        #     added once in the Video branch — i.e. there is exactly one
        #     classList.add('tooltip-below') call on a *Btn variable, and it
        #     is on downloadBtnEl. Multiple adds mean someone leaked the
        #     variant onto Edit/Copy.
        import re as _re
        below_adds = _re.findall(
            r"(\w+)\.classList\.add\(\s*['\"]tooltip-below['\"]\s*\)",
            main_src,
        )
        if not below_adds:
            print("  [FAIL] no tooltip-below add call found in main.js")
            all_passed = False
        else:
            non_download = [v for v in below_adds if v != "downloadBtnEl"]
            if non_download:
                print(f"  [FAIL] tooltip-below leaked onto non-Download buttons: {non_download}")
                all_passed = False
            else:
                print("  [OK] tooltip-below is only applied to downloadBtnEl")

        # 14) main.js defines getWebCopyPlainText (or equivalent helper).
        if "function getWebCopyPlainText" in main_src \
                or "getWebCopyPlainText =" in main_src:
            print("  [OK] main.js defines getWebCopyPlainText() helper")
        else:
            print("  [FAIL] main.js missing getWebCopyPlainText() helper")
            all_passed = False

        # 15) downloadPrompt() web_copy branch uses getWebCopyPlainText (not the
        #     bare currentWebCopyText fallback that bails out on empty).
        dl_idx = main_src.find("function downloadPrompt")
        if dl_idx == -1:
            print("  [WARN] could not locate downloadPrompt() in main.js")
            self.warnings += 1
        else:
            dl_body = main_src[dl_idx:dl_idx + 4000]
            web_copy_branch_idx = dl_body.find("'web_copy'")
            if web_copy_branch_idx == -1:
                web_copy_branch_idx = dl_body.find('"web_copy"')
            if web_copy_branch_idx == -1:
                print("  [WARN] downloadPrompt() has no web_copy branch")
                self.warnings += 1
            else:
                # Inspect a small window after the branch marker.
                branch_window = dl_body[web_copy_branch_idx:web_copy_branch_idx + 400]
                if "getWebCopyPlainText(" in branch_window:
                    print("  [OK] downloadPrompt() web_copy branch uses getWebCopyPlainText()")
                else:
                    print("  [FAIL] downloadPrompt() web_copy branch does not call "
                          "getWebCopyPlainText() (empty Web Copy will silently fail to download)")
                    all_passed = False

        # 16) copyPrompt() web_copy branch must also use getWebCopyPlainText
        #     (so Copy is never silently a no-op when the text is empty).
        cp_idx = main_src.find("async function copyPrompt")
        if cp_idx == -1:
            cp_idx = main_src.find("function copyPrompt")
        if cp_idx == -1:
            print("  [WARN] could not locate copyPrompt() in main.js")
            self.warnings += 1
        else:
            cp_body = main_src[cp_idx:cp_idx + 4000]
            wc_idx = cp_body.find("'web_copy'")
            if wc_idx == -1:
                wc_idx = cp_body.find('"web_copy"')
            if wc_idx != -1:
                window = cp_body[wc_idx:wc_idx + 400]
                if "getWebCopyPlainText(" in window:
                    print("  [OK] copyPrompt() web_copy branch uses getWebCopyPlainText()")
                else:
                    print("  [FAIL] copyPrompt() web_copy branch does not call "
                          "getWebCopyPlainText() (Copy on empty Web Copy is silent)")
                    all_passed = False

        # 17) Round-2 regression: AI Review placeholder still present, and
        #     Video Mode does not call Prompt Review API unguarded.
        try:
            with open("web/static/ai_review.js", "r", encoding="utf-8") as f:
                ai_review_src = f.read()
        except Exception:
            ai_review_src = ""
        if "AI Review for Video Mode is not connected yet." in ai_review_src:
            print("  [OK] ai_review.js still carries Video Mode placeholder")
        else:
            print("  [FAIL] ai_review.js Video Mode placeholder missing")
            all_passed = False
        # Sanity: no new video_review table introduced anywhere.
        for src_name, src in (
            ("web/static/main.js", main_src),
            ("web/static/ai_review.js", ai_review_src),
        ):
            if "video_review" in src.lower():
                print(f"  [FAIL] {src_name} introduces video_review (forbidden)")
                all_passed = False

        # 18) Round 4: main.js must define the global tooltip portal helpers.
        #     Each missing helper is a FAIL (not a WARN) — they are the whole
        #     point of round 4.
        portal_helpers = (
            "ensureGlobalIconTooltip",
            "showGlobalIconTooltip",
            "hideGlobalIconTooltip",
            "bindGlobalIconTooltips",
            "getIconTooltipMessage",
            "getIconTooltipPlacement",
        )
        for fn in portal_helpers:
            if f"function {fn}" in main_src or f"{fn} = function" in main_src:
                print(f"  [OK] main.js defines {fn}()")
            else:
                print(f"  [FAIL] main.js missing global tooltip portal helper {fn}()")
                all_passed = False

        # 19) Round 4: showGlobalIconTooltip must position the portal using
        #     viewport coordinates (getBoundingClientRect + window.innerWidth)
        #     so it is unaffected by parent stacking contexts / overflow.
        show_idx = main_src.find("function showGlobalIconTooltip")
        if show_idx == -1:
            show_idx = main_src.find("showGlobalIconTooltip = function")
        if show_idx != -1:
            show_body = main_src[show_idx:show_idx + 4000]
            if "getBoundingClientRect()" in show_body:
                print("  [OK] showGlobalIconTooltip uses getBoundingClientRect()")
            else:
                print("  [FAIL] showGlobalIconTooltip does not call "
                      "getBoundingClientRect() (cannot position the portal)")
                all_passed = False
            if "window.innerWidth" in show_body:
                print("  [OK] showGlobalIconTooltip clamps to window.innerWidth")
            else:
                print("  [FAIL] showGlobalIconTooltip never reads window.innerWidth "
                      "(would let tooltip clip past the viewport edge)")
                all_passed = False
        else:
            print("  [FAIL] could not locate showGlobalIconTooltip in main.js "
                  "(round-4 positioning audit cannot run)")
            all_passed = False

        # 20) Round 4: ensureGlobalIconTooltip must mount the node onto
        #     document.body so it escapes ancestor stacking contexts.
        ensure_idx = main_src.find("function ensureGlobalIconTooltip")
        if ensure_idx == -1:
            ensure_idx = main_src.find("ensureGlobalIconTooltip = function")
        if ensure_idx != -1:
            ensure_body = main_src[ensure_idx:ensure_idx + 2000]
            if "document.body.appendChild" in ensure_body:
                print("  [OK] ensureGlobalIconTooltip mounts the portal onto document.body")
            else:
                print("  [FAIL] ensureGlobalIconTooltip does not append to document.body "
                      "(portal would still be inside a clipped/stacking-context parent)")
                all_passed = False
        else:
            print("  [FAIL] could not locate ensureGlobalIconTooltip in main.js")
            all_passed = False

        # 21) Round 4: DOMContentLoaded must wire the portal up at startup —
        #     ensureGlobalIconTooltip + bindGlobalIconTooltips both fire.
        dom_idx = main_src.find("DOMContentLoaded")
        if dom_idx != -1:
            dom_body = main_src[dom_idx:dom_idx + 6000]
            if "ensureGlobalIconTooltip(" in dom_body \
                    and "bindGlobalIconTooltips(" in dom_body:
                print("  [OK] DOMContentLoaded wires up global tooltip portal")
            else:
                print("  [FAIL] DOMContentLoaded does not initialise the global "
                      "tooltip portal (ensureGlobalIconTooltip/bindGlobalIconTooltips)")
                all_passed = False
        else:
            print("  [WARN] could not find DOMContentLoaded handler in main.js")
            self.warnings += 1

        # 22) Round 4: viewport scroll/resize must dismiss the tooltip so it
        #     never floats at stale coordinates.
        if ("addEventListener('scroll', hideGlobalIconTooltip" in main_src
                or 'addEventListener("scroll", hideGlobalIconTooltip' in main_src):
            print("  [OK] scroll dismisses the global tooltip")
        else:
            print("  [FAIL] scroll handler does not dismiss the global tooltip "
                  "(tooltip would float at stale coordinates)")
            all_passed = False
        if ("addEventListener('resize', hideGlobalIconTooltip" in main_src
                or 'addEventListener("resize", hideGlobalIconTooltip' in main_src):
            print("  [OK] resize dismisses the global tooltip")
        else:
            print("  [FAIL] resize handler does not dismiss the global tooltip")
            all_passed = False

        if all_passed:
            print(f"\n[OK] {STABILITY_CHECKS_VERSION} UI hotfix checks passed")
            self.checks_passed += 1
        else:
            print(f"\n[FAIL] {STABILITY_CHECKS_VERSION} UI hotfix checks failed")
            self.checks_failed += 1

    def check_v053_fixes(self):
        """v0.5.3-specific source-level checks (read-only).

        Audits the Video Mode Job/Provider/Asset base layer added in v0.5.3.
        No service start, no LLM call, no DB write.
        """
        print("\n" + "="*80)
        print("v0.5.3 Fix Sanity Checks")
        print("="*80)

        all_passed = True

        # 1. VideoJob ORM class + table name
        try:
            with open("web/db/video_models.py", "r", encoding="utf-8") as f:
                vm_src = f.read()
            if "class VideoJob(VideoBase)" in vm_src:
                print("  [OK] VideoJob class declared on VideoBase")
            else:
                print("  [FAIL] VideoJob class missing in web/db/video_models.py")
                all_passed = False
            if '__tablename__ = "video_jobs"' in vm_src or "__tablename__ = 'video_jobs'" in vm_src:
                print("  [OK] video_jobs table name set")
            else:
                print("  [FAIL] video_jobs __tablename__ missing")
                all_passed = False
            for col in ("history_id", "provider", "provider_job_id", "status", "stage",
                        "progress", "request_json", "response_json", "error_message",
                        "result_video_path", "result_video_url", "result_thumbnail_path",
                        "duration_seconds", "submitted_at", "completed_at"):
                if col not in vm_src:
                    print(f"  [FAIL] VideoJob missing column reference: {col}")
                    all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect web/db/video_models.py: {e}")
            all_passed = False

        # 2. web/db/__init__.py exports VideoJob and VideoJobRepository
        try:
            with open("web/db/__init__.py", "r", encoding="utf-8") as f:
                init_src = f.read()
            if "VideoJob" in init_src and "VideoJobRepository" in init_src:
                print("  [OK] web/db/__init__.py exports VideoJob + VideoJobRepository")
            else:
                print("  [FAIL] web/db/__init__.py missing VideoJob/VideoJobRepository exports")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect web/db/__init__.py: {e}")
            all_passed = False

        # 3. VideoJobRepository file presence + required methods
        try:
            with open("web/db/video_job_repository.py", "r", encoding="utf-8") as f:
                jr_src = f.read()
            for fn in ("create_job", "get_job", "get_latest_job_for_history",
                       "list_jobs_for_history", "update_job_status", "mark_cancelled"):
                if f"def {fn}(" in jr_src:
                    print(f"  [OK] VideoJobRepository.{fn} present")
                else:
                    print(f"  [FAIL] VideoJobRepository.{fn} missing")
                    all_passed = False
        except FileNotFoundError:
            print("  [FAIL] web/db/video_job_repository.py is missing")
            all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect video_job_repository.py: {e}")
            all_passed = False

        # 4. Provider abstraction layer files
        for path in ("web/video_providers/__init__.py",
                     "web/video_providers/base.py",
                     "web/video_providers/mock_provider.py"):
            if os.path.exists(path):
                print(f"  [OK] {path} present")
            else:
                print(f"  [FAIL] {path} missing")
                all_passed = False

        # 5. base.py declares VideoProvider; mock_provider.py declares MockVideoProvider with provider_name='mock'
        try:
            with open("web/video_providers/base.py", "r", encoding="utf-8") as f:
                base_src = f.read()
            if "class VideoProvider" in base_src and "provider_name" in base_src:
                print("  [OK] VideoProvider base class declared")
            else:
                print("  [FAIL] VideoProvider base class missing")
                all_passed = False
            with open("web/video_providers/mock_provider.py", "r", encoding="utf-8") as f:
                mp_src = f.read()
            if "class MockVideoProvider(VideoProvider)" in mp_src and (
                "provider_name = \"mock\"" in mp_src or "provider_name = 'mock'" in mp_src
            ):
                print("  [OK] MockVideoProvider with provider_name='mock'")
            else:
                print("  [FAIL] MockVideoProvider declaration / provider_name missing")
                all_passed = False
            if "provider_not_configured" in mp_src:
                print("  [OK] MockVideoProvider returns provider_not_configured shell")
            else:
                print("  [FAIL] MockVideoProvider missing provider_not_configured payload")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect provider sources: {e}")
            all_passed = False

        # 6. web/app.py wires VideoJob + Asset endpoints
        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                app_src = f.read()
            for route in (
                '@app.post("/api/video/history/{history_id}/jobs")',
                '@app.get("/api/video/history/{history_id}/jobs/latest")',
                '@app.get("/api/video/jobs/{job_id}")',
                '@app.post("/api/video/jobs/{job_id}/refresh")',
                '@app.post("/api/video/jobs/{job_id}/cancel")',
                '@app.get("/api/video/history/{history_id}/asset/video")',
                '@app.get("/api/video/history/{history_id}/asset/thumbnail")',
            ):
                if route in app_src:
                    print(f"  [OK] route registered: {route}")
                else:
                    print(f"  [FAIL] route missing: {route}")
                    all_passed = False

            # 7. /api/video/generate + regenerate must include video_job in response
            if "'video_job': video_job_dict" in app_src or '"video_job": video_job_dict' in app_src:
                print("  [OK] /api/video/generate returns video_job in response")
            else:
                print("  [FAIL] /api/video/generate response missing video_job")
                all_passed = False

            # 8. Asset endpoint path-resolve safety helper
            if "_resolve_safe_outputs_path" in app_src:
                print("  [OK] _resolve_safe_outputs_path helper present")
            else:
                print("  [FAIL] _resolve_safe_outputs_path helper missing")
                all_passed = False

            # 9. Mock job creation helper
            if "_create_mock_video_job_for_record" in app_src:
                print("  [OK] _create_mock_video_job_for_record helper present")
            else:
                print("  [FAIL] _create_mock_video_job_for_record helper missing")
                all_passed = False

            # 10. export_schema_version must be at least v0.5.3 (v0.5.4 also OK)
            if (
                '"export_schema_version": "video_v0.5.3"' in app_src
                or '"export_schema_version": "video_v0.5.4"' in app_src
            ):
                print("  [OK] download_all uses export_schema_version >= video_v0.5.3")
            else:
                print("  [FAIL] export_schema_version not upgraded to >= video_v0.5.3")
                all_passed = False
            if '"export_schema_version": "video_v0.5.1"' in app_src:
                print("  [FAIL] legacy export_schema_version video_v0.5.1 still present")
                all_passed = False

            # 11. MockVideoProvider import wired
            if "from web.video_providers import MockVideoProvider" in app_src:
                print("  [OK] MockVideoProvider imported in web/app.py")
            else:
                print("  [FAIL] MockVideoProvider import missing in web/app.py")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect web/app.py: {e}")
            all_passed = False

        # 12. Frontend main.js: button swap + multi-stage progress + status panel
        try:
            with open("web/static/main.js", "r", encoding="utf-8") as f:
                main_js = f.read()
            for fn in (
                "function updateGenerateButtonForCurrentMode",
                "VIDEO_GENERATION_STEPS",
                "function startVideoGenerationProgress",
                "function advanceVideoGenerationProgress",
                "function completeVideoGenerationProgress",
                "function failVideoGenerationProgress",
                "function resetVideoGenerationProgress",
                "function renderVideoJobStatus",
                "function applyVideoAssetSrc",
                "let currentVideoJob",
            ):
                if fn in main_js:
                    print(f"  [OK] main.js declares {fn}")
                else:
                    print(f"  [FAIL] main.js missing {fn}")
                    all_passed = False
            # Asset endpoint usage on the player
            if "/api/video/history/${currentHistoryId}/asset/video" in main_js:
                print("  [OK] main.js routes player src through asset endpoint")
            else:
                print("  [FAIL] main.js does not use /asset/video endpoint")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect web/static/main.js: {e}")
            all_passed = False

        # 13. ai_review.js placeholder no longer references v0.5.1.2
        try:
            with open("web/static/ai_review.js", "r", encoding="utf-8") as f:
                review_js = f.read()
            if "is not connected in v0.5.1.2" in review_js:
                print("  [FAIL] ai_review.js still references 'is not connected in v0.5.1.2'")
                all_passed = False
            else:
                print("  [OK] ai_review.js placeholder cleaned of v0.5.1.2 phrasing")
            if "AI Review for Video Mode is not connected yet" in review_js:
                print("  [OK] ai_review.js uses neutral Video Mode AI Review placeholder")
            else:
                print("  [FAIL] ai_review.js missing the expected v0.5.3 placeholder text")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect ai_review.js: {e}")
            all_passed = False

        # 14. index.html: progress panel + job status panel DOM
        try:
            with open("web/static/index.html", "r", encoding="utf-8") as f:
                html = f.read()
            for marker in (
                'id="video-progress-panel"',
                'id="video-progress-list"',
                'id="video-progress-message"',
                'id="video-job-status-panel"',
                'id="video-job-status-pill"',
                'id="video-job-stage"',
                'id="video-job-provider"',
                'id="video-job-progress"',
                'id="video-job-provider-id"',
                'id="video-job-updated"',
                'id="video-job-message"',
            ):
                if marker in html:
                    print(f"  [OK] index.html has {marker}")
                else:
                    print(f"  [FAIL] index.html missing {marker}")
                    all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect index.html: {e}")
            all_passed = False

        # 15. Doc: v0.5.3 framework spec exists
        if os.path.exists("docs/v0.5.3_video_job_provider_framework.md"):
            print("  [OK] docs/v0.5.3_video_job_provider_framework.md present")
        else:
            print("  [FAIL] docs/v0.5.3_video_job_provider_framework.md missing")
            all_passed = False

        # 16. video_status sync helper present in app.py
        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                app_src_for_sync = f.read()
            if "_map_job_status_to_video_status" in app_src_for_sync:
                print("  [OK] _map_job_status_to_video_status helper present")
            else:
                print("  [FAIL] _map_job_status_to_video_status helper missing")
                all_passed = False
            # The helper must explicitly handle the v0.5.3 default state.
            if "provider_not_configured" in app_src_for_sync and "record.video_status" in app_src_for_sync:
                print("  [OK] app.py syncs record.video_status with provider_not_configured")
            else:
                print("  [FAIL] app.py missing record.video_status sync logic for provider_not_configured")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect web/app.py for video_status sync: {e}")
            all_passed = False

        # 17. CHANGELOG.md must contain a v0.5.3 section.
        try:
            with open("CHANGELOG.md", "r", encoding="utf-8") as f:
                changelog_src = f.read()
            if "v0.5.3 - Video Job / Provider / Asset 基础层与生成流程升级" in changelog_src:
                print("  [OK] CHANGELOG.md has v0.5.3 entry")
            else:
                print("  [FAIL] CHANGELOG.md missing v0.5.3 entry")
                all_passed = False
            for protect in (
                "不接 Seedance",
                "不接任何真实视频生成 API",
                "不生成",
                "Prompt Mode",
            ):
                if protect not in changelog_src:
                    print(f"  [FAIL] CHANGELOG.md missing protection clause: {protect}")
                    all_passed = False
            if all(p in changelog_src for p in ("不接 Seedance", "不接任何真实视频生成 API")):
                print("  [OK] CHANGELOG.md states no Seedance / no real video API")
        except Exception as e:
            print(f"  [FAIL] Could not inspect CHANGELOG.md: {e}")
            all_passed = False

        # 18. No real provider file may be introduced in v0.5.3.
        forbidden_provider_files = [
            "web/video_providers/seedance_provider.py",
            "web/video_providers/runway_provider.py",
            "web/video_providers/pika_provider.py",
            "web/video_providers/luma_provider.py",
        ]
        for path in forbidden_provider_files:
            if os.path.exists(path):
                print(f"  [FAIL] forbidden real provider file present: {path}")
                all_passed = False
        print("  [OK] no real video provider implementation files introduced")

        # 19. No video_review table introduced anywhere.
        try:
            review_table_clean = True
            for src_path in ("web/db/video_models.py", "web/db/video_job_repository.py", "web/app.py"):
                if not os.path.exists(src_path):
                    continue
                with open(src_path, "r", encoding="utf-8") as f:
                    src = f.read()
                if "video_reviews" in src or '"video_review"' in src or "'video_review'" in src:
                    print(f"  [FAIL] {src_path} introduces video_review table (forbidden in v0.5.3)")
                    all_passed = False
                    review_table_clean = False
            if review_table_clean:
                print("  [OK] no video_review table introduced in v0.5.3 surface")
        except Exception as e:
            print(f"  [FAIL] Could not audit for video_review table: {e}")
            all_passed = False

        if all_passed:
            print(f"\n[OK] {STABILITY_CHECKS_VERSION} fix sanity checks passed")
            self.checks_passed += 1
        else:
            print(f"\n[FAIL] {STABILITY_CHECKS_VERSION} fix sanity checks failed")
            self.checks_failed += 1

    def check_v054_fixes(self):
        """v0.5.4-specific source-level checks (read-only).

        Audits the Video Content Asset Pipeline added in v0.5.4. No service
        start, no LLM call, no DB write.
        """
        print("\n" + "="*80)
        print("v0.5.4 Fix Sanity Checks")
        print("="*80)

        all_passed = True

        # 1. Pipeline module exists with the v0.5.4 entry points.
        try:
            with open("web/video_asset_pipeline.py", "r", encoding="utf-8") as f:
                pipe_src = f.read()
            for marker in (
                "def build_video_content_assets(",
                'VIDEO_ASSETS_SCHEMA_VERSION = "video_assets_v0.5.4"',
                "def _call_llm(",
                "def _validate_and_normalize(",
                "def _save_assets(",
                "topic_analysis.json",
                "reasoning.md",
                "video_script.md",
                "storyboard.json",
                "provider_prompt.txt",
                "provider_request_preview.json",
                "generation_manifest.json",
                "AI_VIDEO_LLM_API_KEY",
                "AI_VIDEO_LLM_MODEL",
            ):
                if marker in pipe_src:
                    print(f"  [OK] video_asset_pipeline.py has {marker}")
                else:
                    print(f"  [FAIL] video_asset_pipeline.py missing {marker}")
                    all_passed = False
            # API key safety: must not log/print key contents.
            if "self.api_key" in pipe_src or "print(api_key)" in pipe_src:
                print("  [FAIL] video_asset_pipeline.py appears to log/print API key")
                all_passed = False
            else:
                print("  [OK] video_asset_pipeline.py does not log/print API key")
        except FileNotFoundError:
            print("  [FAIL] web/video_asset_pipeline.py is missing")
            all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect video_asset_pipeline.py: {e}")
            all_passed = False

        # 2. Template file exists with the v0.5.4 required keys.
        try:
            with open("templates/video_asset_prompt_template.md", "r", encoding="utf-8") as f:
                tmpl_src = f.read()
            for marker in (
                "topic_analysis",
                "reasoning",
                "storyboard",
                "provider_prompt",
                "web_copy_placeholder",
                "single narrator",
                "monologue",
                "no dialogue",
                "no interview",
                "no podcast",
                "{{TOPIC}}",
                "{{LANGUAGE}}",
            ):
                if marker in tmpl_src:
                    print(f"  [OK] template has {marker}")
                else:
                    print(f"  [FAIL] template missing {marker}")
                    all_passed = False
        except FileNotFoundError:
            print("  [FAIL] templates/video_asset_prompt_template.md is missing")
            all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect template: {e}")
            all_passed = False

        # 3. web/app.py wires the pipeline into generate + regenerate +
        #    Download All, and uses the v0.5.4 export_schema_version.
        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                app_src = f.read()
            for marker in (
                "from web.video_asset_pipeline import",
                "build_video_content_assets",
                "VIDEO_ASSETS_SCHEMA_VERSION",
                '"export_schema_version": "video_v0.5.4"',
                '"video_assets_schema_version"',
                '"provider_status": "provider_not_configured"',
                '"real_video_generated": False',
                "Real video provider is not connected in v0.5.4",
                "video_assets/",
            ):
                if marker in app_src:
                    print(f"  [OK] app.py has {marker}")
                else:
                    print(f"  [FAIL] app.py missing {marker}")
                    all_passed = False
            # Both generate and regenerate must call the pipeline.
            call_count = app_src.count("build_video_content_assets(")
            if call_count >= 2:
                print(f"  [OK] app.py calls build_video_content_assets >= 2 times ({call_count})")
            else:
                print(f"  [FAIL] app.py calls build_video_content_assets only {call_count} time(s)")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect web/app.py: {e}")
            all_passed = False

        # 4. Frontend main.js: 9-step list with v0.5.4 keys.
        try:
            with open("web/static/main.js", "r", encoding="utf-8") as f:
                main_js = f.read()
            for key in (
                "'analyzing_topic'",
                "'verifying_answer'",
                "'writing_video_script'",
                "'building_storyboard'",
                "'creating_provider_prompt'",
                "'preparing_provider_request'",
                "'creating_mock_video_job'",
                "'saving_assets'",
                "'completed'",
            ):
                if key in main_js:
                    print(f"  [OK] main.js VIDEO_GENERATION_STEPS has {key}")
                else:
                    print(f"  [FAIL] main.js VIDEO_GENERATION_STEPS missing {key}")
                    all_passed = False
            if "Real video provider is not connected in v0.5.4" in main_js:
                print("  [OK] main.js uses v0.5.4 provider message")
            else:
                print("  [FAIL] main.js missing v0.5.4 provider message")
                all_passed = False
            if "is not connected in v0.5.3" in main_js:
                print("  [FAIL] main.js still references 'is not connected in v0.5.3'")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect web/static/main.js: {e}")
            all_passed = False

        # 5. CHANGELOG has a v0.5.4 entry with protection clauses.
        try:
            with open("CHANGELOG.md", "r", encoding="utf-8") as f:
                changelog_src = f.read()
            if "v0.5.4 - Video Content Asset Pipeline" in changelog_src:
                print("  [OK] CHANGELOG.md has v0.5.4 entry")
            else:
                print("  [FAIL] CHANGELOG.md missing v0.5.4 entry")
                all_passed = False
            for protect in (
                "不接 Seedance",
                "不接",
                "不生成",
                "不打印",
                "Prompt Mode",
            ):
                if protect not in changelog_src:
                    print(f"  [FAIL] CHANGELOG.md missing protection clause: {protect}")
                    all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect CHANGELOG.md: {e}")
            all_passed = False

        # 6. v0.5.4 doc exists.
        if os.path.exists("docs/v0.5.4_video_content_asset_pipeline.md"):
            print("  [OK] docs/v0.5.4_video_content_asset_pipeline.md present")
        else:
            print("  [FAIL] docs/v0.5.4_video_content_asset_pipeline.md missing")
            all_passed = False

        # 7. No real provider implementation files introduced.
        forbidden = [
            "web/video_providers/seedance_provider.py",
            "web/video_providers/runway_provider.py",
            "web/video_providers/pika_provider.py",
            "web/video_providers/luma_provider.py",
        ]
        for path in forbidden:
            if os.path.exists(path):
                print(f"  [FAIL] forbidden real provider file present: {path}")
                all_passed = False
        print("  [OK] no real video provider implementation files in v0.5.4")

        # 7b. v0.5.4 structural-fix audits.
        # 7b.i: Pipeline must read AI_VIDEO_LLM_API_KEY as primary source
        #       (and not surface "OPENAI_API_KEY configured" as a
        #       conclusion). OPENAI_API_KEY may appear only as a fallback.
        try:
            with open("web/video_asset_pipeline.py", "r", encoding="utf-8") as f:
                pipe_src2 = f.read()
            if "AI_VIDEO_LLM_API_KEY" in pipe_src2:
                print("  [OK] pipeline uses AI_VIDEO_LLM_API_KEY as primary config")
            else:
                print("  [FAIL] pipeline does not reference AI_VIDEO_LLM_API_KEY")
                all_passed = False
            if "AI_VIDEO_LLM_BASE_URL" in pipe_src2:
                print("  [OK] pipeline reads AI_VIDEO_LLM_BASE_URL")
            else:
                print("  [FAIL] pipeline does not read AI_VIDEO_LLM_BASE_URL")
                all_passed = False
            if "_load_dotenv_for_cli" in pipe_src2:
                print("  [OK] pipeline CLI loads .env on standalone run")
            else:
                print("  [FAIL] pipeline CLI does not load .env on standalone run")
                all_passed = False
            # The misleading "OPENAI_API_KEY configured" CLI banner from the
            # earlier draft must be gone.
            if "`OPENAI_API_KEY` configured" in pipe_src2:
                print("  [FAIL] pipeline still prints 'OPENAI_API_KEY configured' banner")
                all_passed = False
            else:
                print("  [OK] pipeline no longer prints misleading OPENAI_API_KEY banner")
        except Exception as e:
            print(f"  [FAIL] Could not re-inspect video_asset_pipeline.py: {e}")
            all_passed = False

        # 7b.ii: app.py must NOT call build_video_content_assets with
        #        history_id=None in the production paths. Both call sites
        #        should pass a real record.id.
        try:
            with open("web/app.py", "r", encoding="utf-8") as f:
                app_src2 = f.read()
            if "history_id=record.id" in app_src2 and "history_id=new_record.id" in app_src2:
                print("  [OK] app.py passes real history_id into the asset pipeline")
            else:
                print("  [FAIL] app.py does not pass real history_id into the asset pipeline")
                all_passed = False
            # generate path must call create_history_record before
            # build_video_content_assets so the manifest gets a real id.
            cre_idx = app_src2.find("create_history_record(")
            pipe_idx = app_src2.find("build_video_content_assets(")
            if cre_idx != -1 and pipe_idx != -1 and cre_idx < pipe_idx:
                print("  [OK] generate creates VideoHistory before calling pipeline")
            else:
                print("  [FAIL] generate must create VideoHistory record before calling pipeline")
                all_passed = False
            if "update_asset_pipeline_result" in app_src2:
                print("  [OK] app.py writes pipeline result back to record")
            else:
                print("  [FAIL] app.py does not write pipeline result back to record")
                all_passed = False
            # metadata_json + preview_text + overview_cn write-back
            for marker in ("preview_text=pipeline_preview_text", "overview_cn=pipeline_overview_cn", "metadata_json=asset_metadata_json"):
                if marker in app_src2:
                    print(f"  [OK] app.py write-back has {marker}")
                else:
                    print(f"  [FAIL] app.py write-back missing {marker}")
                    all_passed = False
            # download_all metadata must include the asset list.
            if '"asset_list"' in app_src2:
                print("  [OK] download_all metadata includes asset_list")
            else:
                print("  [FAIL] download_all metadata missing asset_list")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not re-inspect web/app.py: {e}")
            all_passed = False

        # 7b.iii: Repository must expose update_asset_pipeline_result.
        try:
            with open("web/db/video_repository.py", "r", encoding="utf-8") as f:
                repo_src = f.read()
            if "def update_asset_pipeline_result(" in repo_src:
                print("  [OK] VideoHistoryRepository.update_asset_pipeline_result exists")
            else:
                print("  [FAIL] VideoHistoryRepository.update_asset_pipeline_result missing")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] Could not inspect web/db/video_repository.py: {e}")
            all_passed = False

        # 7b.iv: docs / README must say the report uses AI_VIDEO_LLM_API_KEY
        #        configured rather than OPENAI_API_KEY configured. (Soft
        #        check — only fails if the doc is present and contradicts.)
        try:
            doc_path = "docs/v0.5.4_video_content_asset_pipeline.md"
            if os.path.exists(doc_path):
                with open(doc_path, "r", encoding="utf-8") as f:
                    doc_src = f.read()
                if "AI_VIDEO_LLM_API_KEY" in doc_src:
                    print("  [OK] v0.5.4 doc references AI_VIDEO_LLM_API_KEY")
                else:
                    print("  [FAIL] v0.5.4 doc does not reference AI_VIDEO_LLM_API_KEY")
                    all_passed = False
        except Exception as e:
            print(f"  [WARN] Could not inspect v0.5.4 doc: {e}")

        # 8. No video_review table introduced anywhere in v0.5.4 surface.
        review_table_clean = True
        for src_path in ("web/db/video_models.py", "web/video_asset_pipeline.py", "web/app.py"):
            if not os.path.exists(src_path):
                continue
            try:
                with open(src_path, "r", encoding="utf-8") as f:
                    src = f.read()
            except Exception:
                continue
            if "video_reviews" in src or '"video_review"' in src or "'video_review'" in src:
                print(f"  [FAIL] {src_path} introduces video_review table (forbidden in v0.5.4)")
                all_passed = False
                review_table_clean = False
        if review_table_clean:
            print("  [OK] no video_review table introduced in v0.5.4 surface")

        if all_passed:
            print(f"\n[OK] {STABILITY_CHECKS_VERSION} fix sanity checks passed")
            self.checks_passed += 1
        else:
            print(f"\n[FAIL] {STABILITY_CHECKS_VERSION} fix sanity checks failed")
            self.checks_failed += 1

    def check_git_status_hygiene(self):
        """Read-only audit of ``git status --porcelain``.

        v0.5.4 second polish: catch two failure modes that have happened
        before during pre-commit reviews:

        1. Old ``docs/v0.4.*`` Chinese-named files showing up as deleted
           (often from an encoding-sensitive zip round-trip).
        2. Garbled ``docs/v0.4.*`` files showing up as untracked (the
           encoding-broken counterparts of the deletions above).

        Also FAILs on accidental commits-in-waiting for ``.env``,
        ``data/*.db``, ``outputs/``, ``__MACOSX``, ``.DS_Store``.

        This check NEVER modifies any file — it only reads
        ``git status --porcelain`` via subprocess.
        """
        import subprocess

        print("\n" + "="*80)
        print("Git Status Hygiene (read-only)")
        print("="*80)

        try:
            res = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            print("  [WARN] git not available; skipping git status audit")
            self.warnings += 1
            return
        except Exception as e:
            print(f"  [WARN] git status failed: {e}")
            self.warnings += 1
            return

        if res.returncode != 0:
            print(f"  [WARN] git status returned {res.returncode}; skipping")
            self.warnings += 1
            return

        lines = [ln for ln in res.stdout.splitlines() if ln.strip()]

        all_passed = True
        deleted_old_docs: list = []
        garbled_docs: list = []
        forbidden_paths: list = []

        # Allow-list of v0.5.4 surface untracked files that are EXPECTED.
        allowed_untracked = {
            "docs/v0.5.4_video_content_asset_pipeline.md",
            "templates/video_asset_prompt_template.md",
            "web/video_asset_pipeline.py",
        }

        def _looks_garbled(name: str) -> bool:
            """Heuristic for filenames that have been UTF-8 → Latin-1 mangled.

            Triggers when:
            - The filename contains escaped octal byte sequences
              (``"\\xxx"`` style emitted by core.quotepath=true).
            - The filename contains stray Latin-1 high bytes that are not
              valid CJK (\\u00c0-\\u00ff range mixed in a path that looks
              like UTF-8 mojibake — e.g. è¯, ç¬¬, ä¸).
            """
            if "\\3" in name or "\\2" in name:
                return True
            # Mojibake markers: a Latin-1 capital letter accented char
            # immediately followed by two more accented bytes is a strong
            # signal for double-decoded UTF-8 (CJK -> latin-1 -> latin-1).
            mojibake_markers = ("è¯", "ç¬", "ä¸", "Ã¥", "Ã©", "â\x80")
            return any(m in name for m in mojibake_markers)

        for ln in lines:
            # Format: "XY path" with X = index, Y = work-tree status; for
            # untracked it's "?? path"; for deleted-from-work-tree it's
            # " D path".
            if len(ln) < 4:
                continue
            code = ln[:2]
            path = ln[3:].strip()
            # Quoted paths from core.quotepath=true: strip surrounding
            # quotes for matching but keep raw form for diagnostics.
            raw = path
            if path.startswith('"') and path.endswith('"'):
                path = path[1:-1]

            # 1) Deleted old docs.
            if (code == " D" or code == "D ") and path.startswith("docs/v0.4."):
                deleted_old_docs.append(raw)
                all_passed = False

            # 2) Untracked garbled docs in the v0.4.x range.
            if code == "??" and (path.startswith("docs/v0.4.") or path.startswith("docs/\"v0.4")) and _looks_garbled(raw):
                garbled_docs.append(raw)
                all_passed = False

            # 3) Forbidden paths in any tracked or untracked state.
            forbidden_prefixes = (
                ".env",
                "data/prompt_history.db",
                "data/video_history.db",
                "outputs/",
                "__MACOSX",
                ".DS_Store",
            )
            if any(path == fp or path.startswith(fp + "/") or path.endswith("/" + fp) for fp in forbidden_prefixes):
                forbidden_paths.append(raw)
                all_passed = False

            # 4) data/*.db catch-all.
            if path.startswith("data/") and path.endswith(".db"):
                forbidden_paths.append(raw)
                all_passed = False

        if deleted_old_docs:
            print("  [FAIL] old docs/v0.4.* files appear deleted in git status:")
            for p in deleted_old_docs:
                print(f"         {p}")
        else:
            print("  [OK] no old docs/v0.4.* files deleted")

        if garbled_docs:
            print("  [FAIL] garbled docs/v0.4.* files appear untracked:")
            for p in garbled_docs:
                print(f"         {p}")
        else:
            print("  [OK] no garbled docs/v0.4.* untracked files")

        if forbidden_paths:
            print("  [FAIL] forbidden paths present in git status:")
            for p in sorted(set(forbidden_paths)):
                print(f"         {p}")
        else:
            print("  [OK] no .env / data/*.db / outputs/ / __MACOSX / .DS_Store in git status")

        # Surface the v0.5.4 expected untracked files — informational only.
        for ln in lines:
            if ln.startswith("?? "):
                p = ln[3:].strip()
                if p.startswith('"') and p.endswith('"'):
                    p = p[1:-1]
                if p in allowed_untracked:
                    print(f"  [INFO] expected v0.5.4 untracked: {p}")

        if all_passed:
            print("\n[OK] git status hygiene check passed")
            self.checks_passed += 1
        else:
            print("\n[FAIL] git status hygiene check failed")
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
    print(f"Prompt Mode + Video Mode Stability Checks - {STABILITY_CHECKS_VERSION}")
    print("="*80)

    checker = StabilityChecker()

    try:
        checker.check_required_files()
        checker.check_python_compile()
        checker.check_js_syntax()
        checker.check_v049_fixes()
        checker.check_v0410_fixes()
        checker.check_v051_fixes()
        checker.check_v0512_fixes()
        checker.check_v0512_ui_hotfix()
        checker.check_v053_fixes()
        checker.check_v054_fixes()
        checker.check_git_status_hygiene()
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
