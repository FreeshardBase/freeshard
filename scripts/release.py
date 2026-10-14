#!/usr/bin/env python3
"""Cut a release: bump the version on a branch, push it, create the GitHub release.

Usage: release.py {major,minor,patch} [branch] [--dry-run] [--yes]

The previous version is the latest GitHub release. The version commit is made by
`just set-version`, pushed to the branch, and the release is created on exactly
that commit with auto-generated notes.
"""

import argparse
import re
import subprocess
import sys


def run(*cmd: str, capture: bool = True) -> str:
    result = subprocess.run(cmd, text=True, capture_output=capture)
    if result.returncode != 0:
        if capture:
            sys.stderr.write(result.stderr)
        sys.exit(f"release: command failed: {' '.join(cmd)}")
    return result.stdout.strip() if capture else ""


def succeeds(*cmd: str) -> bool:
    return subprocess.run(cmd, capture_output=True).returncode == 0


def bump(version: str, part: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        sys.exit(f"release: latest release tag {version!r} is not X.Y.Z")
    major, minor, patch = map(int, match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("part", choices=["major", "minor", "patch"])
    parser.add_argument("branch", nargs="?", default="main")
    parser.add_argument("--dry-run", action="store_true", help="show the preview and stop")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # keep the preview ahead of git/gh output when piped
    branch = args.branch

    if run("git", "status", "--porcelain"):
        sys.exit("release: working tree is not clean")

    run("git", "fetch", "origin", "--tags")
    previous = run("gh", "release", "view", "--json", "tagName", "--jq", ".tagName")
    new = bump(previous, args.part)
    if succeeds("git", "rev-parse", "--verify", "--quiet", f"refs/tags/{new}"):
        sys.exit(f"release: tag {new} already exists")

    # A branch that only exists locally (e.g. fresh cherry-picks) is released as is.
    on_origin = succeeds("git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
    base_ref = f"origin/{branch}" if on_origin else branch
    if not succeeds("git", "rev-parse", "--verify", "--quiet", base_ref):
        sys.exit(f"release: branch {branch} exists neither locally nor on origin")
    base_sha = run("git", "rev-parse", base_ref)

    changes = run("git", "log", "--oneline", "--first-parent", f"{previous}..{base_sha}")
    print(f"Branch:  {branch} ({base_sha[:9]}){'' if on_origin else ' [local only]'}")
    print(f"Version: {previous} -> {new}")
    print(f"Changes since {previous}:")
    print(changes or "  (none)")
    if not changes:
        sys.exit("release: nothing to release")
    if args.dry_run:
        return
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("release: no terminal to confirm on, pass --yes")
        if input(f"Release {new}? [y/N] ").strip().lower() != "y":
            sys.exit("release: aborted")

    run("git", "switch", branch)
    if on_origin:
        run("git", "merge", "--ff-only", base_ref)
    if run("git", "rev-parse", "HEAD") != base_sha:
        sys.exit(f"release: local {branch} differs from {base_ref}, push or reset it first")

    run("just", "set-version", new, capture=False)
    release_sha = run("git", "rev-parse", "HEAD")
    run("git", "push", "origin", f"HEAD:refs/heads/{branch}", capture=False)
    run("gh", "release", "create", new, "--target", release_sha, "--title", new,
        "--generate-notes", capture=False)


if __name__ == "__main__":
    main()
