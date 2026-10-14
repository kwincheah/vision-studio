"""Tests for the headless command-line runner.

The runner must produce the same result as the GUI path, because it drives the same
execution engine.  These tests check the subcommands end to end, the exit statuses, and
the failure reporting that makes the runner scriptable.
"""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vm_clone.cli import build_parser, main  # noqa: E402


@pytest.fixture()
def dataset_dir(tmp_path):
    """A small labelled dataset on disk."""
    from vm_clone.samples.pcb_defect_dataset import build_dataset

    build_dataset(str(tmp_path / "ds"), count=6, seed=4242)
    return str(tmp_path / "ds" / "annotations.json")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def test_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_verbose_and_quiet_are_accepted_after_the_subcommand():
    """They live on the subcommands, not the parent.

    Declaring them on both would lose the parent's value, because argparse stores the
    parent's flag and then the subparser's default overwrites it - so only one position
    can work, and this asserts which one does.
    """
    parser = build_parser()
    assert parser.parse_args(["list", "--store", "x", "--verbose"]).verbose
    assert parser.parse_args(["list", "--store", "x", "--quiet"]).quiet
    assert not parser.parse_args(["list", "--store", "x"]).verbose


@pytest.mark.parametrize("argv", [
    ["run", "--workflow", "w", "--input", "i"],
    ["evaluate", "--dataset", "d"],
    ["compare", "--store", "s"],
    ["list", "--store", "s"],
    ["dataset", "--out", "o"],
    ["demo"],
])
def test_every_subcommand_parses(argv):
    args = build_parser().parse_args(argv)
    assert callable(args.func)


# ---------------------------------------------------------------------------
# dataset
# ---------------------------------------------------------------------------
def test_dataset_command_builds_a_loadable_dataset(tmp_path, capsys):
    out = tmp_path / "made"
    code = main(["dataset", "--out", str(out), "--count", "5", "--quiet"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["images"] == 5
    assert payload["split"] == "test"
    assert set(payload["classes"]) <= {"scratch", "void", "missing_paste", "missing_cu"}

    from vm_clone.evaluation import Dataset

    ds = Dataset.load(str(out / "annotations.json"))
    assert len(ds) == 5


def test_dataset_command_refuses_to_overwrite(tmp_path):
    out = tmp_path / "made"
    assert main(["dataset", "--out", str(out), "--count", "4", "--quiet"]) == 0
    assert main(["dataset", "--out", str(out), "--count", "4", "--quiet"]) == 1
    assert main(["dataset", "--out", str(out), "--count", "4", "--force",
                 "--quiet"]) == 0


def test_dataset_split_is_recorded(tmp_path, capsys):
    out = tmp_path / "train"
    main(["dataset", "--out", str(out), "--count", "4", "--split", "train", "--quiet"])
    capsys.readouterr()
    from vm_clone.evaluation import Dataset

    assert Dataset.load(str(out / "annotations.json")).meta["split"] == "train"


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------
def test_evaluate_writes_json_and_reports_metrics(dataset_dir, tmp_path, capsys):
    out_json = tmp_path / "result.json"
    code = main(["evaluate", "--dataset", dataset_dir, "--detector", "reference",
                 "--out-json", str(out_json), "--quiet"])
    assert code == 0
    capsys.readouterr()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["images_evaluated"] == 6
    assert payload["iou_threshold"] == pytest.approx(0.5)
    # the metric definitions must travel with the numbers
    assert "matching" in payload["metric_definitions"]
    assert isinstance(payload["tp"], int)


def test_evaluate_confidence_threshold_changes_predictions(dataset_dir, tmp_path):
    from vm_clone.evaluation import Experiment

    low = tmp_path / "low.json"
    high = tmp_path / "high.json"
    main(["evaluate", "--dataset", dataset_dir, "--confidence", "0.0",
          "--out-json", str(low), "--quiet"])
    main(["evaluate", "--dataset", dataset_dir, "--confidence", "0.95",
          "--out-json", str(high), "--quiet"])
    a = json.loads(low.read_text(encoding="utf-8"))
    b = json.loads(high.read_text(encoding="utf-8"))
    assert a["tp"] >= b["tp"], "a stricter threshold must not find more true positives"


def test_evaluate_saves_an_experiment(dataset_dir, tmp_path, capsys):
    store = tmp_path / "exp"
    code = main(["evaluate", "--dataset", dataset_dir, "--detector", "reference",
                 "--save-experiment", str(store), "--name", "cli run", "--quiet"])
    assert code == 0
    capsys.readouterr()
    from vm_clone.evaluation import ExperimentStore

    records = ExperimentStore(str(store)).load_all()
    assert len(records) == 1
    assert records[0].name == "cli run"
    assert records[0].dataset_name
    assert records[0].environment["software"]["python"]


def test_evaluate_missing_dataset_fails(dataset_dir, tmp_path):
    assert main(["evaluate", "--dataset", str(tmp_path / "nope.json"),
                 "--quiet"]) == 1


def test_evaluate_unloadable_dataset_fails(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["evaluate", "--dataset", str(bad), "--quiet"]) == 1


def test_evaluate_empty_dataset_fails(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"name": "e", "images": []}), encoding="utf-8")
    assert main(["evaluate", "--dataset", str(empty), "--quiet"]) == 1


def test_evaluate_records_the_requested_split(dataset_dir, tmp_path, capsys):
    out = tmp_path / "r.json"
    main(["evaluate", "--dataset", dataset_dir, "--split", "val",
          "--out-json", str(out), "--quiet"])
    capsys.readouterr()
    assert json.loads(out.read_text(encoding="utf-8"))["split"] == "val"


def test_evaluate_working_size_is_recorded(dataset_dir, tmp_path, capsys):
    out = tmp_path / "r.json"
    main(["evaluate", "--dataset", dataset_dir, "--working-size", "320", "240",
          "--out-json", str(out), "--quiet"])
    capsys.readouterr()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["meta"]["config"]["working_size"] == [320, 240]


def test_evaluate_without_layout_scores_worse(dataset_dir, tmp_path, capsys):
    """The layout input is load-bearing; if it stopped mattering the claim is wrong."""
    with_layout = tmp_path / "with.json"
    without = tmp_path / "without.json"
    main(["evaluate", "--dataset", dataset_dir, "--detector", "reference",
          "--out-json", str(with_layout), "--quiet"])
    main(["evaluate", "--dataset", dataset_dir, "--detector", "reference",
          "--no-layout", "--out-json", str(without), "--quiet"])
    capsys.readouterr()
    a = json.loads(with_layout.read_text(encoding="utf-8"))
    b = json.loads(without.read_text(encoding="utf-8"))
    assert b["fp"] > a["fp"]


# ---------------------------------------------------------------------------
# compare and list
# ---------------------------------------------------------------------------
def _populate_store(store, dataset_dir, tmp_path):
    """Two saved experiments, writing evaluate's own output to files.

    `--out-json` is passed so the evaluate commands print nothing to stdout; otherwise a
    later `capsys.readouterr()` would also capture their summary output and the JSON
    assertion in the test would see two concatenated documents.
    """
    for variant in ("reference", "conservative"):
        main(["evaluate", "--dataset", dataset_dir, "--detector", variant,
              "--save-experiment", str(store), "--name", variant,
              "--out-json", str(tmp_path / f"{variant}.json"), "--quiet"])


def test_list_shows_saved_experiments(dataset_dir, tmp_path, capsys):
    store = tmp_path / "exp"
    _populate_store(store, dataset_dir, tmp_path)
    code = main(["list", "--store", str(store), "--quiet"])
    assert code == 0
    out = capsys.readouterr().out
    assert "reference" in out and "conservative" in out
    # the table carries the metric columns (abbreviated) and the dataset name
    assert "pcb_defect_synth" in out
    for header in ("P", "R", "F1", "FP", "FN"):
        assert header in out
    # and a metric value actually rendered rather than a blank column
    assert any(ch.isdigit() for ch in out.splitlines()[-1])


def test_list_json_is_machine_readable(dataset_dir, tmp_path, capsys):
    store = tmp_path / "exp"
    _populate_store(store, dataset_dir, tmp_path)
    main(["list", "--store", str(store), "--json", "--quiet"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 2
    assert "precision" in payload[0]


def test_list_on_an_empty_store_is_not_an_error(tmp_path, capsys):
    assert main(["list", "--store", str(tmp_path / "none"), "--quiet"]) == 0
    assert "no experiments" in capsys.readouterr().out


def test_compare_reports_trade_offs(dataset_dir, tmp_path, capsys):
    store = tmp_path / "exp"
    _populate_store(store, dataset_dir, tmp_path)
    code = main(["compare", "--store", str(store), "--quiet"])
    assert code == 0
    out = capsys.readouterr().out
    assert "EXPERIMENT COMPARISON" in out
    assert "trade-offs" in out
    assert "not an improvement" in out


def test_compare_needs_two_experiments(dataset_dir, tmp_path, capsys):
    store = tmp_path / "exp"
    main(["evaluate", "--dataset", dataset_dir, "--save-experiment", str(store),
          "--name", "only", "--quiet"])
    capsys.readouterr()
    assert main(["compare", "--store", str(store), "--quiet"]) == 1


def test_compare_refuses_incomparable_runs(dataset_dir, tmp_path, capsys):
    store = tmp_path / "exp"
    main(["evaluate", "--dataset", dataset_dir, "--detector", "reference", "--iou",
          "0.5", "--save-experiment", str(store), "--name", "iou50", "--quiet"])
    main(["evaluate", "--dataset", dataset_dir, "--detector", "reference", "--iou",
          "0.9", "--save-experiment", str(store), "--name", "iou90", "--quiet"])
    capsys.readouterr()
    assert main(["compare", "--store", str(store), "--quiet"]) == 1
    # and can be forced, with a warning
    assert main(["compare", "--store", str(store), "--allow-incomparable",
                 "--quiet"]) == 0
    assert "WARNINGS" in capsys.readouterr().out


def test_compare_writes_json(dataset_dir, tmp_path, capsys):
    store = tmp_path / "exp"
    _populate_store(store, dataset_dir, tmp_path)
    out = tmp_path / "cmp.json"
    main(["compare", "--store", str(store), "--out-json", str(out), "--quiet"])
    capsys.readouterr()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["rows"]) == 2
    assert payload["observations"]


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
def _save_workflow(path):
    import vm_clone.tools  # noqa: F401
    from vm_clone.core.pipeline import VisionPipeline
    from vm_clone.core.registry import create_tool_instance

    pipe = VisionPipeline(name="CLI_Flow")
    pipe.add_node(create_tool_instance("Image Source", "src"))
    pipe.add_node(create_tool_instance("PCB Defect Detection", "det"))
    pipe.connect("src", "Image", "det", "Image")
    pipe.export_to_file(str(path))
    return path


def test_run_on_a_single_image(tmp_path, capsys):
    import cv2

    from vm_clone.samples.pcb_defect_dataset import synth_board

    image, _ = synth_board(1000, allow_clean=False, force_clean=False)
    image_path = tmp_path / "board.png"
    cv2.imwrite(str(image_path), image)
    workflow = _save_workflow(tmp_path / "flow.vmflow")

    out = tmp_path / "run.json"
    code = main(["run", "--workflow", str(workflow), "--input", str(image_path),
                 "--out-json", str(out), "--quiet"])
    assert code == 0
    capsys.readouterr()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["images"] == 1
    assert payload["succeeded"] == 1
    assert payload["results"][0]["status"] == "ok"


def test_run_on_a_directory(tmp_path, capsys):
    import cv2

    from vm_clone.samples.pcb_defect_dataset import synth_board

    folder = tmp_path / "imgs"
    folder.mkdir()
    for i in range(3):
        img, _ = synth_board(2000 + i, allow_clean=False, force_clean=False)
        cv2.imwrite(str(folder / f"b{i}.png"), img)
    workflow = _save_workflow(tmp_path / "flow.vmflow")

    out = tmp_path / "run.json"
    assert main(["run", "--workflow", str(workflow), "--input", str(folder),
                 "--out-json", str(out), "--quiet"]) == 0
    capsys.readouterr()
    assert json.loads(out.read_text(encoding="utf-8"))["images"] == 3


def test_run_reports_a_missing_workflow(tmp_path):
    assert main(["run", "--workflow", str(tmp_path / "nope.vmflow"),
                 "--input", str(tmp_path), "--quiet"]) == 1


def test_run_reports_a_missing_input(tmp_path):
    workflow = _save_workflow(tmp_path / "flow.vmflow")
    assert main(["run", "--workflow", str(workflow),
                 "--input", str(tmp_path / "nope"), "--quiet"]) == 1


def test_run_reports_a_directory_with_no_images(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    workflow = _save_workflow(tmp_path / "flow.vmflow")
    assert main(["run", "--workflow", str(workflow), "--input", str(empty),
                 "--quiet"]) == 1


def test_run_fails_on_an_unreadable_image_unless_ignored(tmp_path, capsys):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"this is not a png")
    workflow = _save_workflow(tmp_path / "flow.vmflow")
    out = tmp_path / "r.json"
    assert main(["run", "--workflow", str(workflow), "--input", str(bad),
                 "--out-json", str(out), "--quiet"]) == 1
    capsys.readouterr()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["failed"] == 1
    assert payload["results"][0]["status"] == "error"
    # --ignore-errors makes it a success with a warning
    assert main(["run", "--workflow", str(workflow), "--input", str(bad),
                 "--out-json", str(out), "--ignore-errors", "--quiet"]) == 0


def test_run_reports_a_workflow_without_a_detector(tmp_path, capsys):
    workflow = _save_workflow(tmp_path / "flow.vmflow")
    # strip the detector: a flow of just a source has nothing to report
    from vm_clone.core.pipeline import VisionPipeline

    pipe = VisionPipeline.import_from_file(str(workflow))
    pipe.remove_node("det")
    pipe.export_to_file(str(workflow))

    import cv2

    from vm_clone.samples.pcb_defect_dataset import synth_board

    image, _ = synth_board(1)
    image_path = tmp_path / "b.png"
    cv2.imwrite(str(image_path), image)
    assert main(["run", "--workflow", str(workflow), "--input", str(image_path),
                 "--quiet"]) == 1


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------
def test_demo_runs_end_to_end(tmp_path, capsys):
    code = main(["demo", "--workdir", str(tmp_path / "demo"), "--count", "6",
                 "--quiet"])
    assert code == 0
    out = capsys.readouterr().out
    assert "EXPERIMENT COMPARISON" in out
    assert os.path.exists(tmp_path / "demo" / "dataset" / "annotations.json")
    assert len(os.listdir(tmp_path / "demo" / "experiments" / "records")) == 2
