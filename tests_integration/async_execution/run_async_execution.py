"""Run provider-free ASYNC-01 examples, including from run_all.py."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def collect_results() -> list[dict[str, str]]:
    """Run all provider-free examples and return their results."""
    directory = Path(__file__).resolve().parent
    env = os.environ.copy()
    root = str(directory.parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (root, env.get("PYTHONPATH"))))
    env["PYTHONASYNCIODEBUG"] = "1"
    results = []
    for script in sorted(directory.glob("*_example.py")):
        command = [
            sys.executable,
            "-B",
            "-W",
            "error::RuntimeWarning",
            "-W",
            "error::ResourceWarning",
            str(script),
        ]
        try:
            result = subprocess.run(
                command,
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            results.append(
                {
                    "name": script.name,
                    "status": "passed" if result.returncode == 0 else "failed",
                    "output": result.stdout,
                    "error": result.stderr if result.returncode else "",
                }
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "name": script.name,
                    "status": "failed",
                    "output": "",
                    "error": "Example exceeded its 20-second failure bound",
                }
            )
    return results


def report_results(results: list[dict[str, str]]) -> int:
    """Print results and return a process exit code."""
    for result in results:
        print(f"{result['status']}: {result['name']}")
        print(result["output"] if result["status"] == "passed" else result["error"])
    return int(any(result["status"] != "passed" for result in results))


def run_scripts(
    pass_local: bool = True, collect: bool = False
) -> list[dict[str, str]] | int:
    """Run examples; pass_local is retained for run_all.py's interface only."""
    results = collect_results()
    return results if collect else report_results(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Accept the shared runner flag; these examples use no local services.
    parser.add_argument("--no-pass-local", dest="pass_local", action="store_false")
    parser.parse_args()
    return report_results(collect_results())


if __name__ == "__main__":
    sys.exit(main())
