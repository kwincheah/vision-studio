"""Capture the inspection platform at work, screen by screen.

Drives the real `VisionMasterMainWindow` and its real `InspectionPanel` through the
milestone workflow and saves a screenshot of each surface, so the demonstration is
evidence rather than a claim.

Run:  python scripts/capture_inspection_screens.py [--count N]
"""
import argparse
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "docs", "screenshots", "inspection")


def pump(app, n=24):
    for _ in range(n):
        app.processEvents()


def run_and_wait(app, panel, timeout_ms: int = 900_000) -> bool:
    """Start the panel's evaluation and block until the worker thread finishes.

    `pump()` alone is not enough: `processEvents()` returns immediately when there is no
    pending event, so a spin loop can burn through thousands of iterations while the
    worker is still running.  `QThread.wait` blocks on the thread itself, which is what
    an offscreen capture script actually needs.
    """
    panel.on_run()
    if panel._thread is None:
        return False
    deadline = 0
    while panel._thread is not None and deadline < timeout_ms:
        app.processEvents()
        if panel._thread is not None and panel._thread.wait(50):
            # the thread finished; let the queued finished/failed signals be delivered
            for _ in range(40):
                app.processEvents()
            break
        deadline += 50
    pump(app, 20)
    return panel.controller.outcome is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20230510)
    ap.add_argument("--workdir", default="")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)

    from PyQt6.QtWidgets import QApplication

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    from vm_clone.samples.pcb_defect_dataset import build_dataset
    from vm_clone.ui.main_window import VisionMasterMainWindow

    workdir = args.workdir or tempfile.mkdtemp(prefix="apex_inspection_")
    data_dir = os.path.join(workdir, "dataset")
    annotations = os.path.join(data_dir, "annotations.json")
    if not os.path.exists(annotations):
        print(f"generating {args.count} boards in {data_dir}")
        build_dataset(data_dir, count=args.count, seed=args.seed)
    print(f"workdir: {workdir}")

    win = VisionMasterMainWindow()
    win.resize(1440, 980)
    win.show()
    pump(app, 30)

    store = os.path.join(workdir, "experiments")
    win.inspection_panel.set_store_directory(store)
    pump(app, 6)

    # ---- 1. the evaluation tab with a dataset loaded ---------------------
    win.show_inspection_panel(0)
    pump(app, 12)
    if not win.inspection_panel.load_dataset_path(annotations):
        print("FAIL: could not load the dataset")
        return 1
    pump(app, 14)
    win.inspection_dock.setMinimumHeight(430)
    win.resize(1440, 1020)
    pump(app, 12)
    win.grab().save(os.path.join(OUT, "J0_evaluate_dataset_loaded.png"))
    print("saved J0_evaluate_dataset_loaded.png")

    panel = win.inspection_panel

    # ---- 2. run the reference detector ----------------------------------
    panel.combo_source.setCurrentIndex(0)
    panel.combo_variant.setCurrentIndex(0)
    panel.edit_name.setText("reference detector")
    if not run_and_wait(app, panel):
        print('FAIL: the reference evaluation did not complete')
        return 1
    result = panel.controller.outcome.result
    print(f"run: images={result.images_evaluated} TP={result.tp} FP={result.fp} "
          f"FN={result.fn} P={result.precision} R={result.recall}")

    # ---- 3. the results tab ---------------------------------------------
    panel.tabs.setCurrentIndex(1)
    pump(app, 16)
    win.grab().save(os.path.join(OUT, "J1_evaluation_results.png"))
    print("saved J1_evaluation_results.png")

    # ---- 4. failure analysis --------------------------------------------
    panel.tabs.setCurrentIndex(2)
    pump(app, 16)
    print("  failure tab shown", flush=True)
    panel.failure_list.select_case(0)
    print("  case 0 selected", flush=True)
    pump(app, 14)
    win.grab().save(os.path.join(OUT, "J2_failure_analysis.png"))
    print("saved J2_failure_analysis.png", flush=True)

    # ---- 5. a missed defect, which needs ground truth visible -----------
    from vm_clone.evaluation.matching import FN
    visible = panel._visible_failures()
    fn_index = next((i for i, c in enumerate(visible) if c.kind == FN), None)
    print(f"  {len(visible)} visible failures, first missed defect at {fn_index}",
          flush=True)
    if fn_index is not None:
        panel.failure_list.select_case(fn_index)
        print("  missed defect selected", flush=True)
        pump(app, 16)
        win.grab().save(os.path.join(OUT, "J3_missed_defect.png"))
        print("saved J3_missed_defect.png", flush=True)
    else:
        print("  (no missed defect; J3 skipped)", flush=True)

    # ---- 6. save the experiment, then run a second operating point ------
    print(f"  store={panel.controller.store_directory!r} "
          f"headless={os.environ.get('APEX_HEADLESS_UI')!r}", flush=True)
    print("  saving experiment 1...", flush=True)
    panel.on_save_experiment()
    print("  experiment 1 saved", flush=True)
    pump(app, 10)

    panel.tabs.setCurrentIndex(0)
    panel.combo_variant.setCurrentIndex(1)
    panel.edit_name.setText("conservative detector")
    print("  starting the conservative run...", flush=True)
    if not run_and_wait(app, panel):
        print('FAIL: the conservative evaluation did not complete', flush=True)
        return 1
    print("  conservative run done; saving experiment 2...", flush=True)
    panel.on_save_experiment()
    print("  experiment 2 saved", flush=True)
    pump(app, 10)
    print(f"experiments saved: {len(panel.controller.list_experiments())}", flush=True)

    # ---- 7. the experiments tab -----------------------------------------
    panel.tabs.setCurrentIndex(3)
    pump(app, 18)
    if panel.table_experiments.rowCount():
        panel.table_experiments.selectRow(0)
    pump(app, 14)
    win.grab().save(os.path.join(OUT, "J4_experiments.png"))
    print("saved J4_experiments.png")

    # ---- 8. the comparison ----------------------------------------------
    panel.tabs.setCurrentIndex(4)
    pump(app, 12)
    panel.on_compare()
    pump(app, 20)
    win.grab().save(os.path.join(OUT, "J5_comparison.png"))
    print("saved J5_comparison.png")

    # ---- 9. evaluating the workspace's own workflow ----------------------
    # The default workspace flow is a full AOI solution whose `Defect Detection` node
    # inspects a fixed ROI, so on these boards it finds little - which is a true and
    # useful result, and the reason the platform exists.  To show a workflow that can
    # actually be evaluated well, a detection flow is built in the workspace first.
    print("  building an inspectable workflow in the workspace...", flush=True)
    from vm_clone.core.pipeline import VisionPipeline
    from vm_clone.core.registry import create_tool_instance

    flow = VisionPipeline(name="PCB_Defect_Flow")
    flow.add_node(create_tool_instance("Image Source", "src"))
    flow.add_node(create_tool_instance("PCB Board Layout", "lay"))
    flow.add_node(create_tool_instance("PCB Defect Detection", "det"))
    flow.connect("src", "Image", "det", "Image")
    flow.connect("lay", "Pad Layout", "det", "Pad Layout")
    flow.connect("lay", "Trace Layout", "det", "Trace Layout")
    win.solution.flows["PCB_Defect_Flow"] = flow
    win.solution.active_flow_name = "PCB_Defect_Flow"
    win._refresh_flow_tabs()
    win.flow_scene.build_from_pipeline()
    pump(app, 20)

    panel.tabs.setCurrentIndex(0)
    panel.combo_source.setCurrentIndex(1)
    panel.combo_variant.setCurrentIndex(0)
    panel.edit_name.setText("active workflow")
    pump(app, 8)
    print("  running the workflow evaluation...", flush=True)
    if not run_and_wait(app, panel):
        print('NOTE: the workflow evaluation did not complete', flush=True)
    pump(app, 16)
    if panel.controller.outcome is not None:
        r = panel.controller.outcome.result
        print(f"workflow run: images={r.images_evaluated} TP={r.tp} FP={r.fp} "
              f"FN={r.fn} P={r.precision} R={r.recall}", flush=True)
    win.grab().save(os.path.join(OUT, "J6_workflow_evaluation.png"))
    print("saved J6_workflow_evaluation.png", flush=True)

    panel.tabs.setCurrentIndex(2)
    pump(app, 14)
    win.grab().save(os.path.join(OUT, "J7_workflow_failures.png"))
    print("saved J7_workflow_failures.png", flush=True)

    # ---- 10. and the same workflow against its own design geometry ------
    win.close()
    print(f"\nworkdir for reproduction: {workdir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
