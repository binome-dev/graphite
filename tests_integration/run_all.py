#!/usr/bin/env python
"""Run all integration tests by executing run_*.py scripts in each subfolder."""

import argparse
import importlib.util
import io
import sys
from pathlib import Path
from textwrap import indent


try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", write_through=True
    )


def _load_runner_module(script: Path):
    """Load a run_*.py file as a module so we can call run_scripts directly."""
    module_name = f"tests_integration.{script.parent.name}.{script.stem}_runner"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load spec for {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    repo_root = current_directory.parent

    # Find all run_*.py scripts in subdirectories
    run_scripts = sorted(current_directory.glob("*/run_*.py"))

    passed_examples = []
    failed_examples = {}
    skipped_examples = []

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

        try:
            runner_module = _load_runner_module(script)
            runner_results = runner_module.run_scripts(
                pass_local=pass_local, collect=True
            )
        except Exception as exc:  # noqa: BLE001
            example_rel = script.relative_to(repo_root)
            error_message = f"Runner failed before executing examples: {exc}"
            print(f"  ✗ {example_rel}")
            print(f"    Error: {error_message}")
            failed_examples[example_rel] = {
                "error": error_message,
                "output": "",
                "rerun_cmd": f"{python_executable} {example_rel}",
            }
            continue

        if not isinstance(runner_results, list):
            example_rel = script.relative_to(repo_root)
            error_message = "Runner did not return result details."
            print(f"  ✗ {example_rel}")
            print(f"    Error: {error_message}")
            failed_examples[example_rel] = {
                "error": error_message,
                "output": "",
                "rerun_cmd": f"{python_executable} {example_rel}",
            }
            continue

        for result in runner_results:
            example_rel = (script.parent / result["name"]).relative_to(repo_root)
            status = result.get("status", "unknown")
            output = result.get("output", "").rstrip()
            error = result.get("error", "").rstrip()

            if status == "passed":
                print(f"  ✓ {example_rel}")
                if output:
                    print(indent(output, "    "))
                passed_examples.append(example_rel)
            elif status == "failed":
                print(f"  ✗ {example_rel}")
                if output:
                    print("    Output:")
                    print(indent(output, "      "))
                if error:
                    print("    Error:")
                    print(indent(error, "      "))
                rerun_cmd = f"{python_executable} {example_rel}"
                print(f"    Rerun with: {rerun_cmd}")
                failed_examples[example_rel] = {
                    "error": error,
                    "output": output,
                    "rerun_cmd": rerun_cmd,
                }
            else:
                print(f"  - {example_rel} (skipped)")
                if error:
                    print(f"    Reason: {error}")
                skipped_examples.append(example_rel)

    # Summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"\nPassed examples: {len(passed_examples)}")
    for example in passed_examples:
        print(f"  ✓ {example}")

    if skipped_examples:
        print(f"\nSkipped examples: {len(skipped_examples)}")
        for example in skipped_examples:
            print(f"  - {example}")

    if failed_examples:
        print(f"\nFailed examples: {len(failed_examples)}")
        for example, data in failed_examples.items():
            print(f"  ✗ {example}")
            if data.get("rerun_cmd"):
                print(f"    Rerun with: {data['rerun_cmd']}")
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
