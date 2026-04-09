import subprocess
import re
import sys
from datetime import datetime
from pathlib import Path
from colorama import Fore, Style, init
import argparse

init(autoreset=True)

VERSION_FILE = Path("VERSION")
CHANGELOG_FILE = Path("CHANGELOG.md")
# 1. Configuration for files that need version replacement
VERSIONED_FILES = [
    Path("setup.py"),  # Common for Python packages
    Path("src/__init__.py"), # Example for an internal file
]
# Define valid changelog categories and their emojis/headers
CHANGELOG_CATEGORIES = {
    "feature": "✨ Added",
    "fix": "🐞 Fixed",
    "refactor": "🔨 Refactor",
    "chore": "🧹 Chore",
    "docs": "📝 Docs",
}


# -------------------------------
# Utilities
# -------------------------------

def get_current_version():
    """Read current version or create default."""
    if not VERSION_FILE.exists():
        VERSION_FILE.write_text("0.0.0", encoding="utf-8")
        print(Fore.YELLOW + "🪄 VERSION file not found — created default 0.0.0")

    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
        parts = version.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError
        return version
    except Exception:
        print(Fore.RED + "⚠️ Invalid VERSION format — resetting to 0.0.0")
        VERSION_FILE.write_text("0.0.0", encoding="utf-8")
        return "0.0.0"


def bump_version(current_version, bump_type):
    """Increment version based on bump type."""
    major, minor, patch = map(int, current_version.split("."))

    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1

    new_version = f"{major}.{minor}.{patch}"
    print(f"{Fore.CYAN}🔧 Bumping version {current_version} → {new_version}")
    return new_version


def build_changelog_entry(new_version, message, category="feature"):
    """Build changelog text for display or write with categorization."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    header = CHANGELOG_CATEGORIES.get(category.lower(), "✨ Added")

    # Format message for list or blockquote if multi-line
    if "\n" in message:
        entry_content = message.strip()
    else:
        entry_content = f"- {message.strip()}"

    return f"## [{new_version}] - {date_str}\n### {header}\n{entry_content}\n\n"


def update_version_in_files(old_version, new_version, dry_run=False):
    """Update version string in secondary files (e.g., setup.py)."""
    updated_files = []
    # Regex to find version strings like version='X.Y.Z' or __version__ = 'X.Y.Z'
    pattern = re.compile(r"version\s*=\s*['\"]" + re.escape(old_version) + r"['\"]|__version__\s*=\s*['\"]" + re.escape(old_version) + r"['\"]")
    replacement = r"\g<0>".replace(old_version, new_version) # Preserve quotes/spacing

    for file_path in VERSIONED_FILES:
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
                new_content, count = re.subn(pattern, replacement, content)

                if count > 0:
                    if not dry_run:
                        file_path.write_text(new_content, encoding="utf-8")
                        updated_files.append(str(file_path))
                        print(Fore.GREEN + f"  → Updated version in {file_path}")
                    else:
                        print(Fore.MAGENTA + f"  → Would update version in {file_path}")
                
            except Exception as e:
                print(Fore.RED + f"⚠️ Failed to process {file_path}: {e}")

    return updated_files


def update_files(new_version, message, category, dry_run=False):
    """Safely update version and changelog with UTF-8 encoding."""
    changelog_entry = build_changelog_entry(new_version, message, category)
    files_to_add = ["VERSION", "CHANGELOG.md"]

    if dry_run:
        print(Style.BRIGHT + Fore.MAGENTA + "\n🚀 Dry Run Preview (no files written):\n")
        print(Fore.CYAN + f"📦 VERSION would become:\n{new_version}\n")
        print(Fore.CYAN + "📝 CHANGELOG entry would be:\n" + Fore.RESET + changelog_entry)
        update_version_in_files(get_current_version(), new_version, dry_run=True) # Run secondary file update in dry-run
        print(Fore.GREEN + "✅ Nothing written. Use without --dry-run to apply changes.\n")
        return

    # --- Actual file write flow ---
    VERSION_FILE.write_text(new_version.strip(), encoding="utf-8")

    # Read or create changelog (logic simplified for brevity, kept original insert method)
    if CHANGELOG_FILE.exists():
        content = CHANGELOG_FILE.read_text(encoding="utf-8").strip()
    else:
        content = "# Changelog\n\n"
        print(Fore.YELLOW + "🪄 CHANGELOG.md not found — created fresh one")

    if not content.startswith("# Changelog"):
        content = "# Changelog\n\n" + content
    
    # Attempt to insert new entry right after the main heading
    try:
        insert_index = content.find('\n', content.find('# Changelog') + len('# Changelog'))
        new_content = content[:insert_index] + "\n" + changelog_entry + content[insert_index:].strip()
    except Exception:
        new_content = content + "\n" + changelog_entry
        print(Fore.YELLOW + "⚠️ Failed to insert at top, appending to end.")

    CHANGELOG_FILE.write_text(new_content.strip() + "\n", encoding="utf-8")

    # Update secondary files and track them for git add
    updated_secondary_files = update_version_in_files(get_current_version(), new_version, dry_run=False)
    files_to_add.extend(updated_secondary_files)
    
    print(Fore.GREEN + f"✅ Updated VERSION and CHANGELOG.md → v{new_version}")

    return files_to_add


# -------------------------------
# Git Operations
# -------------------------------

def is_working_dir_clean():
    """Check if the git working directory is clean."""
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        return not result.stdout.strip()
    except subprocess.CalledProcessError:
        print(Fore.RED + "⚠️ Git command failed. Is this a Git repository?")
        sys.exit(1)
    except FileNotFoundError:
        print(Fore.RED + "⚠️ Git not found. Is it installed and in PATH?")
        sys.exit(1)


def git_commit_and_tag(new_version, message, files_to_add, dry_run=False):
    """Commit, tag, and push new version in git."""
    if dry_run:
        print(Fore.MAGENTA + "💡 Skipping git commit, tag, and push (dry-run mode)\n")
        return
    try:
        # Commit
        subprocess.run(["git", "add"] + files_to_add, check=True)
        subprocess.run(["git", "commit", "-m", f"Release: {message} (v{new_version})"], check=True)
        print(Fore.GREEN + f"✅ Git commit created for v{new_version}")

        # Tag
        subprocess.run(["git", "tag", f"v{new_version}"], check=True)
        print(Fore.GREEN + f"✅ Git tag created for v{new_version}")

        # Push
        subprocess.run(["git", "push"], check=True)
        subprocess.run(["git", "push", "--tags"], check=True)
        print(Fore.GREEN + f"✅ Git push completed (commit and tags sent to remote)")

    except subprocess.CalledProcessError as e:
        print(Fore.RED + f"⚠️ Git operation failed: {e}")
        print(Fore.YELLOW + "You may need to manually resolve and push.")


# -------------------------------
# Main CLI logic (Using argparse)
# -------------------------------

def parse_args():
    """Parse command line arguments using argparse."""
    parser = argparse.ArgumentParser(
        description="Automated version management, changelog update, and Git release process.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "message",
        type=str,
        help="The commit message/changelog entry. Use quotes for single-line, or triple-quotes for multi-line messages."
    )

    parser.add_argument(
        "bump",
        choices=["patch", "minor", "major"],
        nargs="?",
        default="patch",
        help="The segment of the version to increment (default: patch)."
    )

    parser.add_argument(
        "-c", "--category",
        choices=list(CHANGELOG_CATEGORIES.keys()),
        default="feature",
        help=f"The changelog category/header (default: feature).\nChoices: {', '.join(CHANGELOG_CATEGORIES.keys())}"
    )

    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        help="Simulate the entire process without writing files or running git commands."
    )

    return parser.parse_args()


def main():
    args = parse_args()
    
    # 2. Check for uncommitted changes first
    if not args.dry_run and not is_working_dir_clean():
        print(Fore.RED + "❌ Working directory is not clean. Commit or stash changes before releasing.")
        sys.exit(1)
        
    raw_message = args.message
    # Remove surrounding quotes from the message
    if raw_message.startswith(('"""', "'''")) and raw_message.endswith(('"""', "'''")):
        message = raw_message.strip().strip('"').strip("'")
    else:
        message = raw_message.strip('"').strip("'")
    
    if not message.strip():
        print(Fore.RED + "❌ Commit message cannot be empty.")
        sys.exit(1)

    current_version = get_current_version()
    new_version = bump_version(current_version, args.bump)
    
    # Update files returns the list of files to be added to git
    files_to_add = update_files(new_version, message, args.category, dry_run=args.dry_run)
    
    # Perform git operations
    git_commit_and_tag(new_version, message, files_to_add, dry_run=args.dry_run)

    print(Style.BRIGHT + Fore.GREEN + f"\n🎉 Done! {'(Preview only)' if args.dry_run else ''} Released version v{new_version}\n")


if __name__ == "__main__":
    main()