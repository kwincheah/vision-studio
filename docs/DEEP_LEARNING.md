# Deep learning in Apex Vision Studio

Use your own trained neural network to classify parts, outline defects, spot anything that does not look like a good part, or
find and box objects. The app **runs** models; you **train** them with the built-in command below or with any tool that can export
**ONNX**. Running a model needs no GPU, no PyTorch and no internet.

## Try it in one minute

1. Open `DeepLearning_Demo.apex` from the **Start page** (or File > Open Solution; it is in the app's `projects` folder).
2. Press **Run** repeatedly. The source makes a synthetic metal part, alternating good, scratched, good, blotched...
3. Three modules inspect every part with three different small models that ship with the app:

| Module | Question it answers | What you see for a bad part |
|---|---|---|
| **DL Classify** | What is this: good, scratch or blotch? | the label and confidence, FAIL unless it says *good* |
| **DL Segment** | Which pixels are defective? | the defect tinted red, its area, a box |
| **DL Anomaly** | How unlike a good part is it? | a heat map, a score, a box where it differs |

The demo models only understand the synthetic parts. They exist to show how the modules behave. Train your own for real parts.

## The modules

All are in the toolbox under **Deep Learning** (Object Detection moved there).

| Module | Model type | Main outputs |
|---|---|---|
| **DL Classify** | image classifier | `Class`, `Confidence`, `Scores`, `Status` |
| **DL Segment** | segmentation net (U-Net and similar) | `Mask`, `Defect_Area`, `Defect_Ratio`, `Defect_Count`, `Boxes`, `Status` |
| **DL Anomaly** | autoencoder, or any model that outputs an anomaly map | `Heatmap`, `Anomaly_Score`, `Defect_Count`, `Boxes`, `Status` |
| **Object Detection** | YOLO (v5, v8, v11, v10 and later end-to-end) | `Count`, `Boxes`, `Classes`, `Scores`, `Status` |
| **Defect Detection** | the original contrast check, **or** any of the above | `Defect_Count`, `Max_Defect_Area`, `Boxes`, `Classes`, `Scores` |

**Defect Detection** is the one general module: set its **Method** to *Deep learning (ONNX model)*, pick the model and set
**Model task** to *Segmentation*, *Anomaly* or *Detection*. Its outputs stay the same whichever method you use, so a flow keeps
working when you switch from the classical check to a trained model. In deep-learning mode *Max defect area* is not used.

### Settings every deep-learning module shares

| Setting | Meaning |
|---|---|
| **Model path** | the `.onnx` file. A bare name such as `mine.onnx` is looked up in `~/.apex_vision/models` and the demo models folder |
| **Backend** | *Auto* uses ONNX Runtime and falls back to OpenCV DNN. Both give the same results |
| **Device** | `cpu`, or `cuda` when a GPU build of onnxruntime is installed |
| **Labels** | `good, scratch, dent` or a text file (one per line). Blank = the names stored with the model |
| **Input width / height** | blank (0) = what the model expects. A model with a fixed size always uses that size |
| **Resize** | *Stretch* squeezes the picture to the model size; *Letterbox* keeps its shape and pads. *Auto* = what the model's `.json` says |
| **Normalize** | how pixel values are scaled before the model sees them (*0 to 1*, *ImageNet (mean/std)*, *-1 to 1*, *0 to 255*). *Auto* = the `.json` |
| **RGB input** | on for models trained on RGB pictures (nearly all of them) |
| **ROI** | a region to inspect. All zero = the whole image. Drag a rectangle on the image to set it |

Module-specific settings:

- **DL Classify**: *OK labels* (the labels that pass, for example `good`), *Min confidence*, *Top K*.
- **DL Segment**: *Defect classes* (names or numbers; blank = everything that is not background), *Threshold*, *Min area*,
  *Max defect count* (default 0: any defect fails), *Max defect ratio* (% of the image).
- **DL Anomaly**: *Output type* (*Auto* reads the model's `.json`), *Map threshold* (0 = use the model's own suggested value),
  *Smoothing*, *Min area*, *Max defect count*.

## Train a model from your own pictures

Needs `pip install torch onnx` (the packaged app does not train). The networks are small and train in minutes on a CPU. They suit
controlled factory images (fixed camera and light); for harder jobs train a larger model elsewhere and export it (next section).

```bash
python main.py train classify --data parts/  --out models/parts.onnx     # parts/good/*.png  parts/scratch/*.png  parts/dent/*.png
python main.py train segment  --data seg/    --out models/seg.onnx       # seg/images/a.png  seg/masks/a.png  (0 = background, 1 = defect)
python main.py train anomaly  --data good/   --out models/anomaly.onnx   # good/*.png : pictures of GOOD parts only
python main.py train detect   --data data.yaml --out models/detect.onnx  # a YOLO dataset; needs `pip install ultralytics`
python main.py model-info models/parts.onnx                              # what a model expects and returns
```

Each command writes `name.onnx` and `name.json` next to it (labels, input size, normalisation, a suggested anomaly threshold).
Then put the `.onnx` path in the module's **Model path**. Useful options: `--epochs`, `--size` (network input in pixels; bigger sees
finer defects but is slower), `--arch resnet18 --pretrained` for classification (starts from ImageNet weights; downloads them).

How much data? Roughly 50 or more pictures per class for classification, 100 or more annotated pictures for segmentation, and 50 or
more good pictures for anomaly detection. Include the lighting and part variation you will really see. Always check on pictures the
model was **not** trained on: the training log prints an accuracy / IoU on held-out pictures.

## Use a model you trained elsewhere

Anything that exports **ONNX** works. What each module expects:

| Module | Model input | Model output |
|---|---|---|
| DL Classify | image `1x3xHxW` | scores `1xC` (logits or probabilities; a single value is read as a sigmoid) |
| DL Segment | image `1x3xHxW` | `1xCxHxW` (argmax over C) or `1x1xHxW` (a sigmoid mask) |
| DL Anomaly | image `1x3xHxW` | an anomaly map `1x1xHxW` / `1xHxW`, **or** a reconstruction `1x3xHxW` (autoencoder) |
| Object Detection | image `1x3x640x640` | YOLO output `1x(4+C)xN` (v8, v11), `1xNx(5+C)` (v5), or `1xNx6` (end-to-end) |

Examples:

```python
# Ultralytics YOLO  (class names are stored in the file and picked up automatically)
from ultralytics import YOLO
YOLO("best.pt").export(format="onnx", imgsz=640, opset=13)

# a PyTorch / torchvision classifier
torch.onnx.export(model.eval(), torch.zeros(1, 3, 224, 224), "parts.onnx", input_names=["input"],
                  output_names=["logits"], opset_version=13, dynamo=False)
```

If the model needs a particular scaling, add a small `parts.json` beside it so nobody has to remember:

```json
{"task": "classify", "labels": ["good", "scratch"], "input_size": [224, 224],
 "normalize": "ImageNet (mean/std)", "resize": "Stretch", "rgb": true}
```

(`"threshold"` and `"output_type": "Reconstruction (autoencoder)"` are read by DL Anomaly.) Anything set in the module overrides the file.

## Speed

Measured on a laptop CPU with the demo models, per 1920x1080 image including resizing: DL Classify about 6 ms, DL Segment about
75 ms, DL Anomaly about 65 ms. Larger networks cost more; YOLO11n at 640x640 is roughly 50 to 100 ms on a CPU. Use a smaller **ROI**
or input size to speed up, or `cuda` with a GPU build of onnxruntime.

## When something goes wrong

| Message | What to do |
|---|---|
| *No model file chosen* | pick the `.onnx` in **Model path** |
| *Model file not found* | check the path; a bare name is searched in `~/.apex_vision/models` |
| *is not an .onnx file* | a PyTorch `.pt` file cannot run in the packaged app: export it to ONNX first (above) |
| *Could not load ... ONNX Runtime: ... OpenCV DNN: ...* | the file is damaged, or it uses an operator neither engine supports: re-export with `opset_version=13` |
| *The model could not run on this image (it expects 1xNx3x224x224...)* | the model's input does not match what the module sent: check **RGB input**, channels (1 or 3) and **Input width/height** |
| *the model's output ... does not match its input, so it is not an autoencoder* | in DL Anomaly set **Output type** to *Anomaly map* |
| every part fails, or every part passes | the model does not fit your pictures: check **Normalize** and **Resize** against how it was trained, then raise or lower the threshold |
| a classifier is wrong on new parts | it has not seen that variation: add pictures of it to the training folders and train again |

## Good practice

- A model only knows what it was trained on. Test it on a few hundred pictures it has never seen, including borderline parts, before
  trusting it on a line, and keep checking: lighting drift and a new supplier both change what the camera sees.
- Pair a deep-learning verdict with a simple safety check where you can (for example **Intensity Measure** to catch a dark or blown-out picture).
- Dataset Evaluation (Inspection menu) scores a flow against labelled pictures with the same code the line uses.
