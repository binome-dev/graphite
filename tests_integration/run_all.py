#!/usr/bin/env python
"""Run all integration tests by executing run_*.py scripts in each subfolder."""

import argparse
import io
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def run_all_scripts(pass_local: bool = True) -> int:
    """Run all run_*.py scripts in subdirectories.

    Args:
        pass_local: If True, pass --no-pass-local flag is NOT used (skip local tests).
                   If False, include local/ollama tests.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    python_executable = sys.executable
    current_directory = Path(__file__).parent

    # Find all run_*.py scripts in subdirectories
    run_scripts = sorted(current_directory.glob("*/run_*.py"))

    passed_folders = []
    failed_folders = {}

    print(f"Found {len(run_scripts)} test runners:")
    for script in run_scripts:
        print(f"  - {script.parent.name}/{script.name}")
    print()

    # Run each script
    for script in run_scripts:
        folder_name = script.parent.name
        print(f"{'=' * 60}")
        print(f"Running tests in: {folder_name}")
        print(f"{'=' * 60}")

        cmd = [python_executable, str(script)]
        if not pass_local:
            cmd.append("--no-pass-local")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=script.parent,
            )
            print(result.stdout)
            passed_folders.append(folder_name)
        except subprocess.CalledProcessError as e:
            print(f"Output:\n{e.stdout}")
            print(f"Error:\n{e.stderr}")
            failed_folders[folder_name] = e.stderr

    # Summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"\nPassed folders: {len(passed_folders)}")
    for folder in passed_folders:
        print(f"  ✓ {folder}")

    if failed_folders:
        print(f"\nFailed folders: {len(failed_folders)}")
        for folder in failed_folders:
            print(f"  ✗ {folder}")
        return 1

    print("\nAll integration tests passed!")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all integration tests.")
    parser.add_argument(
        "--no-pass-local",
        dest="pass_local",
        action="store_false",
        help="Include local/ollama tests (default: skip them).",
    )
    parser.set_defaults(pass_local=True)
    args = parser.parse_args()

    sys.exit(run_all_scripts(pass_local=args.pass_local))
