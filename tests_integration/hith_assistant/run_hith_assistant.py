#!/usr/bin/env python
"""Run integration tests for hith_assistant (Human-In-The-Loop)."""

import io
import subprocess
import sys
from pathlib import Path


try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", write_through=True
    )


def run_scripts(pass_local: bool = True, collect: bool = False):
    """Run all example scripts in this directory.

    Args:
        pass_local: If True, skip tests with 'ollama' or 'local' in their name.
        collect: If True, return per-script results without printing.

    Returns:
        List of per-script results if collect is True, otherwise exit code (0 for success, 1 for failure).
    """
    python_executable = sys.executable
    current_directory = Path(__file__).parent

    # Find all example files
    example_files = sorted(current_directory.glob("*_example.py"))

    results = []

    for file in example_files:
        filename = file.name
        if pass_local and ("ollama" in filename or "_local" in filename):
            message = f"Skipping {filename} (local test)"
            if not collect:
                print(message)
            results.append(
                {
                    "name": filename,
                    "status": "skipped",
                    "output": "",
                    "error": message,
                }
            )
            continue

        if not collect:
            print(f"Running {filename}...")
        try:
            result = subprocess.run(
                [python_executable, str(file)],
                capture_output=True,
                text=True,
                check=True,
                cwd=current_directory,
            )
            if not collect:
                print(f"Output of {filename}:\n{result.stdout}")
            results.append(
                {
                    "name": filename,
                    "status": "passed",
                    "output": result.stdout,
                    "error": "",
                }
            )
        except subprocess.CalledProcessError as e:
            if not collect:
                print(f"Error running {filename}:\n{e.stderr}")
            results.append(
                {
                    "name": filename,
                    "status": "failed",
                    "output": e.stdout,
                    "error": e.stderr,
                }
            )

    if collect:
        return results

    passed_scripts = [r for r in results if r["status"] == "passed"]
    failed_scripts = [r for r in results if r["status"] == "failed"]

    print("\n" + "=" * 50)
    print("Summary:")
    print(f"Passed: {len(passed_scripts)}")
    for script in passed_scripts:
        print(f"  ✓ {script['name']}")

    if failed_scripts:
        print(f"\nFailed: {len(failed_scripts)}")
        for script in failed_scripts:
            print(f"  ✗ {script['name']}")
        return 1

    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run hith_assistant integration tests."
    )
    parser.add_argument(
        "--no-pass-local",
        dest="pass_local",
        action="store_false",
        help="Include local/ollama tests (default: skip them).",
    )
    parser.set_defaults(pass_local=True)
    args = parser.parse_args()

    sys.exit(run_scripts(pass_local=args.pass_local))
