"""Turn a PyTorch YOLO model (.pt) into ONNX so the application's own engine can run it.

Used two ways: imported by ``dl_engine.convert_pt_to_onnx`` where PyTorch is installed, and as the entry point of the optional
``ApexModelConverter`` program (the only piece that carries PyTorch):  ``ApexModelConverter model.pt model.onnx 640``.
A .pt file is a Python pickle - loading one runs whatever code it contains - so only convert models you trust.
"""
import os
import shutil
import sys
import tempfile


def convert(pt_path: str, onnx_path: str, imgsz: int = 640) -> None:
    from ultralytics import YOLO                                   # PyTorch is imported here, never by the main program
    with tempfile.TemporaryDirectory(prefix="apex_pt_") as tmp:
        work = os.path.join(tmp, "model.pt")
        shutil.copyfile(pt_path, work)                              # the export writes beside the weights: keep the user's folder clean
        out = YOLO(work).export(format="onnx", imgsz=int(imgsz), opset=12, simplify=False)
        os.makedirs(os.path.dirname(os.path.abspath(onnx_path)), exist_ok=True)
        shutil.copyfile(str(out), onnx_path)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: ApexModelConverter <model.pt> <model.onnx> [image size]", file=sys.stderr)
        return 2
    try:
        convert(args[0], args[1], int(args[2]) if len(args) > 2 else 640)
    except Exception as exc:                                        # the caller shows this text to the user
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
