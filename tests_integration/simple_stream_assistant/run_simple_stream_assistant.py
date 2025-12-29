#!/usr/bin/env python
"""Run integration tests for simple_stream_assistant."""

import io
import subprocess
import sys
from pathlib import Path


sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def run_scripts(pass_local: bool = True) -> int:
    """Run all example scripts in this directory.

    Args:
        pass_local: If True, skip tests with 'ollama' or 'local' in their name.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    python_executable = sys.executable
    current_directory = Path(__file__).parent

    # Find all example files
    example_files = sorted(current_directory.glob("*_example.py"))

    passed_scripts = []
    failed_scripts = {}

    for file in example_files:
        filename = file.name
        if pass_local and ("ollama" in filename or "_local" in filename):
            print(f"Skipping {filename} (local test)")
            continue

        print(f"Running {filename}...")
        try:
            result = subprocess.run(
                [python_executable, str(file)],
                capture_output=True,
                text=True,
                check=True,
                cwd=current_directory,
            )
            print(f"Output of {filename}:\n{result.stdout}")
            passed_scripts.append(filename)
        except subprocess.CalledProcessError as e:
            print(f"Error running {filename}:\n{e.stderr}")
            failed_scripts[filename] = e.stderr

    # Summary
    print("\n" + "=" * 50)
    print("Summary:")
    print(f"Passed: {len(passed_scripts)}")
    for script in passed_scripts:
        print(f"  ✓ {script}")

    if failed_scripts:
        print(f"\nFailed: {len(failed_scripts)}")
        for script in failed_scripts:
            print(f"  ✗ {script}")
        return 1

    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run simple_stream_assistant integration tests."
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
