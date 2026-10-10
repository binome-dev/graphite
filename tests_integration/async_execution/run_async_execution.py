"""Run provider-free ASYNC-01 examples, including from run_all.py."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run_scripts(
    pass_local: bool = True, collect: bool = False
) -> list[dict[str, str]] | int:
    """Run all examples; pass_local preserves the run_all.py runner interface.

    These examples require no providers or local services, so both settings run
    the same scenarios.
    """
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
    if collect:
        return results
    for result in results:
        print(f"{result['status']}: {result['name']}")
        print(result["output"] if result["status"] == "passed" else result["error"])
    return int(any(result["status"] != "passed" for result in results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-pass-local", dest="pass_local", action="store_false")
    sys.exit(run_scripts(pass_local=parser.parse_args().pass_local))
