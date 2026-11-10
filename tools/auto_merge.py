import subprocess
import sys
from pathlib import Path
import json

# -------------------------------
# Default Portable Rules
# -------------------------------

DEFAULT_SAFE_FILES = {
    "CHANGELOG.md",
    "VERSION",
}

DEFAULT_CRITICAL_KEYWORDS = [
    "models",
    "services",
    "core",
    "logic",
]


# -------------------------------
# Optional Config Loader
# -------------------------------

def load_config():
    """
    Load optional config from:
    .auto_merge.json (if exists)

    Example:
    {
        "safe_files": ["CHANGELOG.md"],
        "critical_paths": ["apps/", "core/"]
    }
    """
    config_path = Path(".auto_merge.json")

    if not config_path.exists():
        return {
            "safe_files": DEFAULT_SAFE_FILES,
            "critical_paths": []
        }

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return {
            "safe_files": set(data.get("safe_files", DEFAULT_SAFE_FILES)),
            "critical_paths": data.get("critical_paths", [])
        }
    except Exception:
        print("⚠️ Invalid .auto_merge.json — using defaults")
        return {
            "safe_files": DEFAULT_SAFE_FILES,
            "critical_paths": []
        }


# -------------------------------
# Git Helpers
# -------------------------------

def get_conflicted_files():
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            check=True
        )
        return [f for f in result.stdout.splitlines() if f.strip()]
    except subprocess.CalledProcessError:
        print("❌ Failed to detect conflicts.")
        sys.exit(1)


def resolve_file(file_path, strategy):
    try:
        subprocess.run(
            ["git", "checkout", f"--{strategy}", file_path],
            check=True
        )
        subprocess.run(["git", "add", file_path], check=True)
        print(f"✅ Resolved: {file_path}")
        return True
    except subprocess.CalledProcessError:
        print(f"❌ Failed: {file_path}")
        return False


# -------------------------------
# Rule Engine
# -------------------------------

def is_critical(file_path, critical_paths):
    return any(file_path.startswith(p) for p in critical_paths)


def looks_sensitive(file_path):
    return any(keyword in file_path.lower() for keyword in DEFAULT_CRITICAL_KEYWORDS)


def auto_merge(strategy="theirs", unsafe=False):
    config = load_config()

    safe_files = config["safe_files"]
    critical_paths = config["critical_paths"]

    files = get_conflicted_files()

    if not files:
        print("✅ No conflicts detected.")
        return

    print(f"⚠️ {len(files)} conflicted file(s)\n")

    resolved = []
    skipped = []

    for f in files:
        # Rule 1: explicit critical paths
        if is_critical(f, critical_paths):
            print(f"🛑 CRITICAL (config): {f}")
            skipped.append(f)
            continue

        # Rule 2: heuristic protection
        if not unsafe and looks_sensitive(f):
            print(f"🧠 Sensitive (heuristic skip): {f}")
            skipped.append(f)
            continue

        # Rule 3: safe files always allowed
        if not unsafe and f not in safe_files:
            print(f"⏭️ Skipped (not safe): {f}")
            skipped.append(f)
            continue

        if resolve_file(f, strategy):
            resolved.append(f)

    # Commit
    if resolved:
        try:
            subprocess.run(
                ["git", "commit", "-m", "Auto-resolved safe conflicts"],
                check=True
            )
            print("\n🚀 Auto-merge commit created.")
        except subprocess.CalledProcessError:
            print("❌ Commit failed.")

    # Summary
    print("\n--- SUMMARY ---")
    print(f"Resolved: {len(resolved)}")
    print(f"Skipped: {len(skipped)}")

    if skipped:
        print("\n⚠️ Manual review needed:")
        for f in skipped:
            print(f" - {f}")


# -------------------------------
# CLI
# -------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Portable auto-merge tool for Git conflicts"
    )

    parser.add_argument(
        "--strategy",
        choices=["theirs", "ours"],
        default="theirs",
        help="Resolution strategy"
    )

    parser.add_argument(
        "--unsafe",
        action="store_true",
        help="Resolve ALL conflicts (dangerous)"
    )

    args = parser.parse_args()

    auto_merge(
        strategy=args.strategy,
        unsafe=args.unsafe
    )