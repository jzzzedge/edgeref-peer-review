# EdgeRef Deployment Health-Check Module
# Run with: EDGEREF_DEBUG=true to see results in the app.
# This module checks file structure and configuration; it NEVER
# reads, displays, or logs API keys, access codes, or provider info.

import os

_HEALTH_CHECKS = []


def _check(name, passed, detail, severity=None):
    _HEALTH_CHECKS.append({
        "name": name,
        "passed": bool(passed),
        "detail": str(detail),
        "severity": severity or ("info" if passed else "warning"),
    })


def _get_project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_health_check():
    """Run deployment health checks and return results.

    Returns:
        dict with keys: status, checks, warnings, suggested_actions
    """
    global _HEALTH_CHECKS
    _HEALTH_CHECKS = []
    root = _get_project_root()

    # 1. app.py exists
    app_py = os.path.join(root, "app.py")
    _check("app.py exists", os.path.isfile(app_py),
           f"app.py {'found' if os.path.isfile(app_py) else 'MISSING'} at {app_py}")

    # 2. requirements.txt exists
    req_txt = os.path.join(root, "requirements.txt")
    _check("requirements.txt exists", os.path.isfile(req_txt),
           f"requirements.txt {'found' if os.path.isfile(req_txt) else 'MISSING'} at {req_txt}")

    # 3. Journal catalog master exists
    catalog_dir = os.path.join(root, "data", "journal_catalogs")
    master_csv = os.path.join(catalog_dir, "journal_catalog_master.csv")
    catalog_found = os.path.isfile(master_csv)
    if catalog_found:
        try:
            row_count = sum(1 for line in open(master_csv, "r", encoding="utf-8-sig", errors="replace") if line.strip()) - 1
            detail = f"Found with ~{max(0, row_count):,} records"
        except Exception:
            detail = "Found but could not read row count"
    else:
        csv_files = [f for f in os.listdir(catalog_dir) if f.lower().endswith(".csv")] if os.path.isdir(catalog_dir) else []
        detail = f"MISSING (found {len(csv_files)} other CSV files in catalog dir)" if csv_files else "MISSING and catalog dir is empty"
    _check("journal_catalog_master.csv", catalog_found, detail)

    # 4. .gitignore contains .streamlit/secrets.toml
    gitignore = os.path.join(root, ".gitignore")
    gitignore_ok = False
    if os.path.isfile(gitignore):
        try:
            content = open(gitignore, "r", encoding="utf-8").read()
            gitignore_ok = ".streamlit/secrets.toml" in content
        except Exception:
            pass
    _check(".gitignore includes .streamlit/secrets.toml", gitignore_ok,
           "Found and configured" if gitignore_ok else "MISSING or not configured in .gitignore")

    # 5. Check if local secrets.toml exists (DO NOT read content)
    secrets_toml = os.path.join(root, ".streamlit", "secrets.toml")
    local_secrets = os.path.isfile(secrets_toml)
    _check("Local .streamlit/secrets.toml", local_secrets,
           "Present (local development). NOT included in package." if local_secrets else "Not present (expected on a fresh clone/Cloud deploy).",
           severity="info")

    # 6. Check secrets.example.toml exists
    example_toml = os.path.join(root, ".streamlit", "secrets.example.toml")
    _check(".streamlit/secrets.example.toml exists", os.path.isfile(example_toml),
           "Found" if os.path.isfile(example_toml) else "MISSING")

    # Determine overall status
    checks = list(_HEALTH_CHECKS)
    failures = [c for c in checks if not c["passed"] and c["severity"] != "info"]
    warnings = [c for c in checks if not c["passed"]]
    status = "Pass" if not failures else "Warning"

    suggested = []
    if not os.path.isfile(app_py):
        suggested.append("Restore app.py from the project archive.")
    if not catalog_found:
        suggested.append("Place journal_catalog_master.csv in data/journal_catalogs/")
    if not gitignore_ok:
        suggested.append("Add '.streamlit/secrets.toml' to .gitignore")
    if not os.path.isfile(example_toml):
        suggested.append("Create .streamlit/secrets.example.toml for deployment guidance")
    if local_secrets:
        suggested.append("Local .streamlit/secrets.toml is present -- verify it is not committed to Git.")

    return {
        "status": status,
        "checks": checks,
        "warnings": [c["detail"] for c in warnings],
        "suggested_actions": suggested,
    }
