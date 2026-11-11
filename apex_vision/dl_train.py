"""Train and export the deep-learning models the DL modules use.  Needs PyTorch (``pip install torch onnx``); the packaged app does not.

    python main.py train classify --data parts/    --out models/parts.onnx      # parts/good/*.png  parts/scratch/*.png ...
    python main.py train segment  --data seg/      --out models/seg.onnx        # seg/images/*.png  seg/masks/*.png (0 = background)
    python main.py train anomaly  --data good/     --out models/anomaly.onnx    # good/*.png (good parts only)
    python main.py train detect   --data data.yaml --out models/detect.onnx     # YOLO dataset (needs ultralytics)
    python main.py model-info models/parts.onnx

Every command writes ``<out>.onnx`` and ``<out>.json`` (labels, input size, normalisation, suggested threshold), so a module only
needs the .onnx path. The networks are small on purpose: they train in minutes on a CPU and suit controlled factory images. For
harder problems train anything you like elsewhere (a larger network, anomalib, YOLO) and export it to ONNX.
"""
import glob
import json
import os
import random
import shutil
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


class TrainError(Exception):
    """A problem with the data or the environment, in plain words."""


def _torch():
    try:
        import torch
        import torch.nn as nn
        return torch, nn
    except ImportError as exc:
        raise TrainError("Training needs PyTorch: pip install torch onnx   (the packaged app only runs models, it does not train them)") from exc


def _need_onnx() -> None:
    try:
        import onnx  # noqa: F401
    except ImportError as exc:
        raise TrainError("Exporting needs the 'onnx' package: pip install onnx") from exc


def list_images(folder: str) -> List[str]:
    out = []
    for ext in IMAGE_EXT:
        out += glob.glob(os.path.join(folder, "*" + ext)) + glob.glob(os.path.join(folder, "*" + ext.upper()))
    return sorted(set(out))


def load_image(path: str, size: Tuple[int, int], gray: bool = False) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if img is None:
        raise TrainError(f"Could not read the image {path}")
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA)


def _seed(seed: int) -> None:
    torch, _ = _torch()
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _write_sidecar(out_path: str, meta: Dict[str, Any]) -> str:
    sc = os.path.splitext(out_path)[0] + ".json"
    with open(sc, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return sc


def _export(model, example, out_path: str, input_names, output_names, dynamic=True) -> None:
    torch, _ = _torch()
    _need_onnx()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    model.eval()
    axes = {n: {0: "batch"} for n in list(input_names) + list(output_names)} if dynamic else None
    with torch.no_grad():
        torch.onnx.export(model, example, out_path, input_names=input_names, output_names=output_names,
                          opset_version=13, dynamic_axes=axes, dynamo=False)


def _batches(n: int, size: int, shuffle: bool = True):
    idx = list(range(n))
    if shuffle:
        random.shuffle(idx)
    for i in range(0, n, size):
        yield idx[i:i + size]


def _to_tensor(arr: np.ndarray, normalize: str = "0 to 1"):
    """HWC uint8 BGR images (N, H, W, 3) -> float NCHW RGB."""
    torch, _ = _torch()
    x = torch.from_numpy(np.ascontiguousarray(arr[..., ::-1])).float().permute(0, 3, 1, 2) / 255.0
    if normalize == "ImageNet (mean/std)":
        mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
        x = (x - mean) / std
    return x


# ---------------------------------------------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------------------------------------------
def _small_cnn(num_classes: int):
    _, nn = _torch()

    def block(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True), nn.MaxPool2d(2))
    return nn.Sequential(block(3, 16), block(16, 32), block(32, 64), block(64, 96), nn.AdaptiveAvgPool2d(1), nn.Flatten(),
                         nn.Dropout(0.2), nn.Linear(96, num_classes))


def train_classifier(data_dir: str, out_path: str, epochs: int = 20, size: int = 64, arch: str = "small", pretrained: bool = False,
                     batch: int = 16, lr: float = 2e-3, val_split: float = 0.2, seed: int = 0,
                     log: Callable[[str], None] = print) -> Dict[str, Any]:
    torch, nn = _torch()
    _seed(seed)
    classes = sorted(d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d)))
    if len(classes) < 2:
        raise TrainError(f"Put one folder per class inside {data_dir} (for example good/ and scratch/), each with images.")
    xs, ys = [], []
    for ci, c in enumerate(classes):
        files = list_images(os.path.join(data_dir, c))
        if not files:
            raise TrainError(f"The class folder '{c}' has no images")
        for f in files:
            xs.append(load_image(f, (size, size)))
            ys.append(ci)
    xs, ys = np.stack(xs), np.array(ys)
    order = np.random.permutation(len(xs))
    n_val = max(len(classes), int(len(xs) * val_split))
    val_idx, tr_idx = order[:n_val], order[n_val:]
    log(f"{len(xs)} images, {len(classes)} classes {classes}; {len(tr_idx)} for training, {len(val_idx)} for checking")

    normalize = "0 to 1"
    if arch == "resnet18":
        import torchvision
        net = torchvision.models.resnet18(weights="DEFAULT" if pretrained else None)
        net.fc = nn.Linear(net.fc.in_features, len(classes))
        normalize = "ImageNet (mean/std)"
    else:
        net = _small_cnn(len(classes))
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=max(1, epochs * ((len(tr_idx) + batch - 1) // batch)))
    lossf = nn.CrossEntropyLoss()
    xt, yt = _to_tensor(xs, normalize), torch.from_numpy(ys).long()
    acc = 0.0
    for ep in range(epochs):
        net.train()
        for b in _batches(len(tr_idx), batch):
            ids = tr_idx[b]
            x = xt[ids]
            if random.random() < 0.5:
                x = torch.flip(x, dims=[3])
            x = x * (1 + 0.1 * (random.random() - 0.5))
            opt.zero_grad()
            lossf(net(x), yt[ids]).backward()
            opt.step()
            sched.step()
        net.eval()
        with torch.no_grad():
            acc = float((net(xt[val_idx]).argmax(1) == yt[val_idx]).float().mean())
        if ep % max(1, epochs // 5) == 0 or ep == epochs - 1:
            log(f"  epoch {ep + 1}/{epochs}: accuracy on the checking images {acc:.1%}")
    _export(net, torch.zeros(1, 3, size, size), out_path, ["input"], ["logits"])
    meta = {"task": "classify", "labels": classes, "input_size": [size, size], "normalize": normalize, "resize": "Stretch",
            "rgb": True, "validation_accuracy": round(acc, 4)}
    _write_sidecar(out_path, meta)
    log(f"saved {out_path}  (checking accuracy {acc:.1%})")
    return meta


# ---------------------------------------------------------------------------------------------------------------
# segmentation (small U-Net)
# ---------------------------------------------------------------------------------------------------------------
def _unet(num_classes: int):
    torch, nn = _torch()

    def cb(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                             nn.Conv2d(o, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True))

    class UNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.e1, self.e2, self.e3 = cb(3, 16), cb(16, 32), cb(32, 64)
            self.pool = nn.MaxPool2d(2)
            self.u2 = nn.ConvTranspose2d(64, 32, 2, stride=2)
            self.d2 = cb(64, 32)
            self.u1 = nn.ConvTranspose2d(32, 16, 2, stride=2)
            self.d1 = cb(32, 16)
            self.head = nn.Conv2d(16, num_classes, 1)

        def forward(self, x):
            a = self.e1(x)
            b = self.e2(self.pool(a))
            c = self.e3(self.pool(b))
            d = self.d2(torch.cat([self.u2(c), b], 1))
            e = self.d1(torch.cat([self.u1(d), a], 1))
            return self.head(e)
    return UNet()


def train_segmenter(data_dir: str, out_path: str, epochs: int = 30, size: int = 128, labels: Optional[List[str]] = None, batch: int = 8,
                    lr: float = 3e-3, val_split: float = 0.2, seed: int = 0, log: Callable[[str], None] = print) -> Dict[str, Any]:
    torch, nn = _torch()
    _seed(seed)
    img_dir, mask_dir = os.path.join(data_dir, "images"), os.path.join(data_dir, "masks")
    files = list_images(img_dir)
    if not files:
        raise TrainError(f"Put the pictures in {img_dir} and a mask with the same file name in {mask_dir} (pixel value = class number, 0 = background).")
    xs, ms = [], []
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        mp = next((m for m in list_images(mask_dir) if os.path.splitext(os.path.basename(m))[0] == stem), None)
        if mp is None:
            raise TrainError(f"No mask for {os.path.basename(f)} in {mask_dir}")
        xs.append(load_image(f, (size, size)))
        m = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
        if m is None:
            raise TrainError(f"Could not read the mask {mp}")
        ms.append(cv2.resize(m, (size, size), interpolation=cv2.INTER_NEAREST))
    xs, ms = np.stack(xs), np.stack(ms)
    if ms.max() > 1 and ms.max() == 255 and len(np.unique(ms)) <= 2:
        ms = (ms > 127).astype(np.uint8)                                  # a 0/255 mask means one defect class
    nc = int(ms.max()) + 1
    if nc < 2:
        raise TrainError("The masks contain no defect pixels (every pixel is 0)")
    labels = labels or (["background", "defect"] if nc == 2 else ["background"] + [f"defect_{i}" for i in range(1, nc)])
    order = np.random.permutation(len(xs))
    n_val = max(1, int(len(xs) * val_split))
    val_idx, tr_idx = order[:n_val], order[n_val:]
    log(f"{len(xs)} images, {nc} classes; {len(tr_idx)} for training, {len(val_idx)} for checking")
    net = _unet(nc)
    weights = torch.tensor([1.0] + [max(1.0, float((ms == 0).sum() / max(1, (ms == c).sum())) ** 0.5) for c in range(1, nc)])
    lossf = nn.CrossEntropyLoss(weight=weights)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=max(1, epochs * ((len(tr_idx) + batch - 1) // batch)))
    xt, mt = _to_tensor(xs), torch.from_numpy(ms).long()
    iou = 0.0
    for ep in range(epochs):
        net.train()
        for b in _batches(len(tr_idx), batch):
            ids = tr_idx[b]
            x, m = xt[ids], mt[ids]
            if random.random() < 0.5:
                x, m = torch.flip(x, dims=[3]), torch.flip(m, dims=[2])
            opt.zero_grad()
            lossf(net(x), m).backward()
            opt.step()
            sched.step()
        net.eval()
        with torch.no_grad():
            pred = net(xt[val_idx]).argmax(1)
            truth = mt[val_idx]
            inter = float(((pred > 0) & (truth > 0)).sum())
            union = float(((pred > 0) | (truth > 0)).sum())
            iou = inter / union if union else 1.0
        if ep % max(1, epochs // 5) == 0 or ep == epochs - 1:
            log(f"  epoch {ep + 1}/{epochs}: defect overlap (IoU) on the checking images {iou:.1%}")
    _export(net, torch.zeros(1, 3, size, size), out_path, ["input"], ["logits"])
    meta = {"task": "segment", "labels": labels, "input_size": [size, size], "normalize": "0 to 1", "resize": "Stretch", "rgb": True,
            "validation_iou": round(iou, 4)}
    _write_sidecar(out_path, meta)
    log(f"saved {out_path}  (checking IoU {iou:.1%})")
    return meta


# ---------------------------------------------------------------------------------------------------------------
# anomaly detection (convolutional autoencoder trained on good parts only)
# ---------------------------------------------------------------------------------------------------------------
def _autoencoder():
    _, nn = _torch()

    def down(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 4, stride=2, padding=1), nn.BatchNorm2d(o), nn.LeakyReLU(0.1, inplace=True))

    def up(i, o):
        return nn.Sequential(nn.ConvTranspose2d(i, o, 4, stride=2, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True))
    return nn.Sequential(down(3, 16), down(16, 32), down(32, 64), down(64, 8),          # a narrow code: only "good" can be rebuilt
                         up(8, 64), up(64, 32), up(32, 16), nn.ConvTranspose2d(16, 3, 4, stride=2, padding=1), nn.Sigmoid())


def train_anomaly(data_dir: str, out_path: str, epochs: int = 60, size: int = 128, batch: int = 8, lr: float = 3e-3,
                  seed: int = 0, margin: float = 1.25, log: Callable[[str], None] = print) -> Dict[str, Any]:
    torch, nn = _torch()
    _seed(seed)
    files = list_images(data_dir)
    if len(files) < 4:
        raise TrainError(f"Anomaly training needs several pictures of GOOD parts in {data_dir} (found {len(files)}).")
    xs = np.stack([load_image(f, (size, size)) for f in files])
    order = np.random.permutation(len(xs))
    n_val = max(2, len(xs) // 5)
    val_idx, tr_idx = order[:n_val], order[n_val:]
    log(f"{len(xs)} good images; {len(tr_idx)} for training, {len(val_idx)} to set the threshold")
    net = _autoencoder()
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-5)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=max(1, epochs * ((len(tr_idx) + batch - 1) // batch)))
    xt = _to_tensor(xs)
    loss = torch.tensor(0.0)
    for ep in range(epochs):
        net.train()
        for b in _batches(len(tr_idx), batch):
            x = xt[tr_idx[b]]
            if random.random() < 0.5:
                x = torch.flip(x, dims=[3])
            opt.zero_grad()
            loss = nn.functional.mse_loss(net(x + 0.02 * torch.randn_like(x)), x)
            loss.backward()
            opt.step()
            sched.step()
        if ep % max(1, epochs // 5) == 0 or ep == epochs - 1:
            log(f"  epoch {ep + 1}/{epochs}: rebuilding error {float(loss.detach()):.5f}")
    net.eval()
    with torch.no_grad():
        err = (xt[val_idx] - net(xt[val_idx])).abs().mean(1).numpy()
    peaks = [float(cv2.GaussianBlur(e, (0, 0), 2.0).max()) for e in err]
    threshold = float(max(peaks) * margin)
    _export(net, torch.zeros(1, 3, size, size), out_path, ["input"], ["reconstruction"])
    meta = {"task": "anomaly", "output_type": "Reconstruction (autoencoder)", "input_size": [size, size], "normalize": "0 to 1",
            "resize": "Stretch", "rgb": True, "threshold": round(threshold, 5), "good_images": len(xs)}
    _write_sidecar(out_path, meta)
    log(f"saved {out_path}  (threshold {threshold:.4f} = {margin:g} x the worst error on {n_val} good images)")
    return meta


# ---------------------------------------------------------------------------------------------------------------
# detection (YOLO through ultralytics)
# ---------------------------------------------------------------------------------------------------------------
def train_detector(data_yaml: str, out_path: str, epochs: int = 50, size: int = 640, base: str = "yolo11n.pt", batch: int = 16,
                   log: Callable[[str], None] = print) -> Dict[str, Any]:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise TrainError("Detection training uses Ultralytics YOLO: pip install ultralytics") from exc
    if not os.path.isfile(data_yaml):
        raise TrainError(f"Dataset description not found: {data_yaml}  (a YOLO data.yaml listing the images and class names)")
    _need_onnx()
    model = YOLO(base)
    res = model.train(data=data_yaml, epochs=epochs, imgsz=size, batch=batch, verbose=False)
    best = os.path.join(str(res.save_dir), "weights", "best.pt") if hasattr(res, "save_dir") else base
    exported = YOLO(best).export(format="onnx", imgsz=size, opset=13, simplify=False)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    shutil.copyfile(exported, out_path)
    names = YOLO(best).names
    meta = {"task": "detect", "labels": [str(names[k]) for k in sorted(names)], "input_size": [size, size], "normalize": "0 to 1",
            "resize": "Letterbox", "rgb": True}
    _write_sidecar(out_path, meta)
    log(f"saved {out_path}")
    return meta


def model_info(path: str) -> str:
    from apex_vision.core import dl_engine as dl
    m = dl.load_model(path)
    lines = [m.describe()]
    for k in ("task", "labels", "input_size", "normalize", "resize", "threshold", "validation_accuracy", "validation_iou"):
        if k in m.meta:
            lines.append(f"  {k}: {m.meta[k]}")
    lines.append("  backends here: " + ", ".join(dl.available_backends()))
    return "\n".join(lines)
