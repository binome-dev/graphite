"""Run the provider-free subprocess examples in normal pytest CI as well."""

from pathlib import Path

import pytest

from tests_integration.async_execution.run_async_execution import run_scripts

EXAMPLE_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "tests_integration/async_execution"
)
EXAMPLES = sorted(path.name for path in EXAMPLE_DIRECTORY.glob("*_example.py"))


@pytest.fixture(scope="module")
def example_results() -> list[dict[str, str]]:
    results = run_scripts(collect=True)
    assert isinstance(results, list)
    return results


def test_all_execution_examples_are_discovered(
    example_results: list[dict[str, str]],
) -> None:
    discovered = {result["name"] for result in example_results}
    assert discovered == set(EXAMPLES)
    assert discovered


@pytest.mark.parametrize("name", EXAMPLES)
def test_execution_example(name: str, example_results: list[dict[str, str]]) -> None:
    result = next(result for result in example_results if result["name"] == name)
    assert result["status"] == "passed", result["output"] + result["error"]
