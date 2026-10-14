"""Verify that a VisionPipeline built in the editor can be evaluated.

This is the load-bearing integration for the platform: the evaluation layer must measure
the *same* workflow the user builds visually, through the pipeline's own execution
engine.  If the image does not reach the source node, or the detector's outputs cannot be
read, every metric is meaningless - so this checks the path end to end, and shows what
the design-layout input is actually worth.

Run:  python scripts/audit_pipeline_evaluation.py
"""
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import vm_clone.tools  # noqa: E402,F401
from vm_clone.core.pipeline import VisionPipeline  # noqa: E402
from vm_clone.core.registry import create_tool_instance  # noqa: E402
from vm_clone.evaluation import (  # noqa: E402
    RunConfig, pipeline_predictor, run_dataset,
)
from vm_clone.samples.pcb_defect_dataset import build_dataset  # noqa: E402


def build_pipeline(with_layout: bool = True) -> VisionPipeline:
    """The workflow a user would draw.

    With the layout branch:

        image source -> PCB Defect Detection
        board layout -> PCB Defect Detection   (design context)

    The layout node supplies pad and trace geometry, which the detector uses to tell a
    pad defect from missing copper in the plane.  Without it the detector still runs, but
    has no way to make that distinction and reports many more false positives - measured
    below, because a claim like that should be a number.
    """
    pipe = VisionPipeline(name="PCB_Defect_Inspection")
    source = create_tool_instance("Image Source", "src")
    detector = create_tool_instance("PCB Defect Detection", "det")
    pipe.add_node(source)
    pipe.add_node(detector)
    pipe.connect("src", "Image", "det", "Image")
    if with_layout:
        layout = create_tool_instance("PCB Board Layout", "lay")
        pipe.add_node(layout)
        pipe.connect("lay", "Pad Layout", "det", "Pad Layout")
        pipe.connect("lay", "Trace Layout", "det", "Trace Layout")
    return pipe


def report(label: str, outcome) -> None:
    r = outcome.result
    print(f"{label:<26} images={r.images_evaluated:>3} errors={len(r.errors):>2} "
          f"TP={r.tp:>3} FP={r.fp:>3} FN={r.fn:>3} "
          f"P={_fmt(r.precision)} R={_fmt(r.recall)} F1={_fmt(r.f1)}")


def _fmt(value) -> str:
    return " n/a" if value is None else f"{value:.4f}"


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="vm_pipe_eval_")
    ds = build_dataset(tmp, count=12)
    print(f"dataset: {ds.counts()}\n")

    seeds = {r.image_path: int(r.meta.get("seed", 0)) for r in ds.records}

    # ---- with the layout branch ------------------------------------------
    pipe = build_pipeline(with_layout=True)
    print(f"pipeline : {pipe.name}")
    for conn in pipe.connections:
        print(f"   {conn.from_node}.{conn.from_port} -> {conn.to_node}.{conn.to_port}")
    validation = pipe.validate_flow()
    blocking = [v for v in validation if v.get("severity") not in (None, "warning")]
    print(f"validate_flow: {len(validation)} message(s), {len(blocking)} blocking\n")

    layout_node = pipe.nodes["lay"]

    def supply_board_design(record):
        # Each board has its own design seed, so the layout node is told which board is
        # being inspected.  This is per-record context, not pixel data.
        layout_node.set_param("board_seed", seeds.get(record.image_path, 0))

    outcome = run_dataset(
        ds, pipeline_predictor(pipe),
        RunConfig(dataset_name=ds.name, model_id="pcb_reference",
                  predictor_kind="pipeline", detector_variant="reference"),
        before_image=supply_board_design)
    report("WITH layout input", outcome)

    # ---- without the layout branch ---------------------------------------
    plain = build_pipeline(with_layout=False)
    outcome_plain = run_dataset(
        ds, pipeline_predictor(plain),
        RunConfig(dataset_name=ds.name, model_id="pcb_reference",
                  predictor_kind="pipeline", detector_variant="reference"))
    report("WITHOUT layout input", outcome_plain)

    # ---- the conservative operating point, same workflow -----------------
    pipe.nodes["det"].set_param("variant", "conservative")
    outcome_cons = run_dataset(
        ds, pipeline_predictor(pipe),
        RunConfig(dataset_name=ds.name, model_id="pcb_reference",
                  predictor_kind="pipeline", detector_variant="conservative"),
        before_image=supply_board_design)
    report("WITH layout, conservative", outcome_cons)

    result = outcome.result
    print(f"\ninference mean : "
          f"{result.latency._summary(result.latency.inference_ms)['mean']} ms")
    produced = sum(len(v) for v in outcome.predictions.values())
    print(f"total detections from the pipeline: {produced}")

    if result.errors:
        print("\nerrors:")
        for e in result.errors[:5]:
            print("   ", e)

    print()
    if produced == 0:
        print("FAIL: the pipeline produced no detections - the image did not reach the "
              "detector, or its outputs were not read.")
        return 1
    if result.tp == 0:
        print("FAIL: detections were produced but none matched ground truth.")
        return 1
    if outcome_plain.result.fp <= result.fp:
        print("NOTE: the layout input did not reduce false positives as expected "
              f"({outcome_plain.result.fp} vs {result.fp}); the claim that it matters "
              f"is not supported by this run.")
    else:
        print(f"OK: the layout input reduced false positives from "
              f"{outcome_plain.result.fp} to {result.fp}.")
    print("OK: the pipeline was evaluated through its own execution engine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
