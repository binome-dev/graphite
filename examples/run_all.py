import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def run_scripts_in_directory(ci_only=True, pass_local=True):
    # Path to the current Python interpreter in the active virtual environment
    python_executable = sys.executable

    openai_api_key = os.environ[
        "OPENAI_API_KEY"
    ]  # Replace with your actual OpenAI API key
    tavily_api_key = os.environ[
        "TAVILY_API_KEY"
    ]  # Replace with your actual Tavily API key

    os.environ["OPENAI_API_KEY"] = openai_api_key
    os.environ["TAVILY_API_KEY"] = tavily_api_key

    # Get the directory of the current script
    current_directory = Path(__file__).parent

    # Find all Python example files in subdirectories
    file_list = []
    for root, subdir, _ in os.walk(current_directory):
        for folder in subdir:
            for _, _, files in os.walk(current_directory / folder):
                for file in files:
                    if file.endswith("_example.py"):
                        # Store the relative path to maintain proper execution context
                        rel_path = current_directory / folder / file
                        file_list.append(rel_path)

    passed_scripts = []
    failed_scripts = {}

    # Run each script
    for file in file_list:
        if "ollama" in str(file) and pass_local:
            continue

        file_path = os.path.join(current_directory, file)
        try:
            print(f"Running {file} with {python_executable}...")
            result = subprocess.run(
                [python_executable, file_path],
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"Output of {file}:\n{result.stdout}")
            passed_scripts.append(file)
        except subprocess.CalledProcessError as e:
            print(f"Error running {file}:\n{e.stderr}")
            failed_scripts[file] = e.stderr

    # Summary of execution
    print("\nSummary of execution:")
    print("Passed scripts:")
    for script in passed_scripts:
        print(f" - {script}")

    if failed_scripts:
        print("\nFailed scripts:")
        for script, error in failed_scripts.items():
            print(f" - {script}")  #: {error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run scripts with specified flags.")

    # By default, pass_local=True. If user provides --no-pass-local, it sets it to False.
    parser.add_argument(
        "--no-pass-local",
        dest="pass_local",
        action="store_false",
        help="Disable pass_local. Default is True.",
    )

    # Set the defaults here so if the user doesn't provide the flags,
    # ci_only and pass_local remain True
    parser.set_defaults(ci_only=True, pass_local=True)

    args = parser.parse_args()

    # Now pass those values to your function
    run_scripts_in_directory(ci_only=args.ci_only, pass_local=args.pass_local)
