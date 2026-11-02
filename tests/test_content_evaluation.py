"""Task scoring must not promote transport success or banner text into evidence."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "scripts/evaluate_content.py"
spec = spec_from_file_location("content_evaluation", path)
evaluation = module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_transport_success_and_long_content_cannot_satisfy_absent_fact():
    case = {"facts": [{"id": "allocation", "pattern": r"allocation is 7341 tonnes"}]}
    result = evaluation.score(case, {"quality": "ok", "content": "navigation furniture " * 1000})
    assert result["extraction_success"]
    assert result["supported_assertions"] == 0
    assert not result["task_assertions_complete"]
    assert result["source_completeness"] == "unknown"
    assert not result["answer_verified"]


def test_error_instruction_is_not_supporting_evidence():
    case = {"facts": [{"id": "instruction", "pattern": r"Wait a moment and try again"}]}
    result = evaluation.score(case, {"quality": "ok", "content":
        "Something went wrong. Wait a moment and try again. " + "Real text " * 100})
    assert result["pollution"] == "suspected" and result["supported_assertions"] == 0


def test_real_fact_inside_polluted_page_retains_exact_support():
    case = {"facts": [{"id": "allocation", "pattern": r"allocation is 7341 tonnes"}]}
    text = "Something went wrong. Wait a moment and try again. The allocation is 7341 tonnes."
    result = evaluation.score(case, {"quality": "suspect", "content": text})
    assert result["task_assertions_complete"]
    assert result["pollution"] == "suspected" and not result["answer_verified"]
    evidence = result["assertions"][0]["evidence"][0]
    assert text[evidence["start"]:evidence["end"]] == evidence["quote"]
