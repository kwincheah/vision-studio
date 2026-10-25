# Flow generation reference

This file is the reference the AI flow generator reads. The tool catalogue and the recipes are generated
from the application (`python scripts/gen_flow_reference.py`); do not edit between the markers.

## How flows work

A **flow** is a directed acyclic graph of **modules**. Each module is one instance of a **tool** (for
example `Image Source`, `Caliper`). A module has named **input ports** and **output ports**, each with a
data type, and **parameters** with defaults. A **link** connects one output port to one input port.
When a flow runs, modules execute in dependency order and each module receives the values of the ports
linked to its inputs.

Rules the engine enforces:

- An input port accepts **exactly one** link. An output port may feed any number of inputs.
- A link is allowed only when the types are compatible (see *Port types*).
- Links must not form a cycle.
- A module whose input has no link works on no data. Only acquisition-style modules have no inputs.
- Parameters not listed in a module keep the tool's default. Only set what the task needs.

## Port types

| Type | Meaning |
|---|---|
| IMAGE | an image (almost every vision tool takes and often passes one on) |
| VALUE | a number |
| BOOLEAN | true / false; **VALUE and BOOLEAN connect to each other** |
| STRING | text |
| POINT | an (x, y) point |
| LINE | a line |
| CIRCLE | a circle |
| REGION | a rectangle (x, y, width, height) |
| ANY | anything; an ANY port connects to and from every type |

Two ports of the same type always connect. Anything else is rejected (for example IMAGE -> VALUE).
Typical bridges: a measuring tool's `VALUE` output feeds `Condition Branch.Val_In`; `Caliper.Edge1` and
`Edge2` are POINTs for `P2P Measure`.

## Parameter conventions

- Numbers: ints stay ints, floats are floats. Booleans are `true` / `false`.
- Rectangles (`roi`, `template_roi`) are `[x, y, width, height]` in pixels of the source image.
- Lines and points (`line_p1`, `start_pt`) are `[x, y]` in pixels.
- Text parameters with a listed set of choices must use one of those values exactly (case and spaces).
  Text parameters without choices keep their default unless the user asks for something specific.
- The synthetic test image is 800 x 600 pixels; coordinates should lie inside the real image.

## Building a good flow

1. Start from an acquisition module (`Image Source`). Use `source_type` `Synthetic` unless the user names
   a file or camera.
2. Put pre-processing (filter, binarise, morphology) before measuring or detecting tools when the task
   mentions noise or a threshold.
3. Add the measuring / detecting module, then a judging module (`Condition Branch`) when the user wants a
   pass / fail decision. `Condition Branch` operators: `>=`, `<=`, `>`, `<`, `==`, `!=`, `Between`
   (`Between` uses `threshold_low` and `threshold_high`; the others use `threshold_low`).
4. Add communication or output modules (`TCP Send`, `Image Output`, `Camera IO`, `Script`) only when the
   user asks. They have side effects: mention them so the user can review their settings.
5. Name modules with a two-digit order prefix, for example `02_FindHole`, or omit `name` and let the
   builder number them.
6. Keep flows as small as the task allows. Do not add modules the user did not ask for.

## Common mistakes

- Using a tool name that does not exist: copy names exactly from the catalogue.
- Linking `Image` to a `Val_In` or `Image` to `Point1`: check the port types.
- Feeding one input from two sources: an input takes one link.
- Forgetting the `Image Source` link: most tools need `Image` linked.
- Putting a parameter on the wrong tool, or inventing a parameter name: use only the listed parameters.
- Writing XML by hand: write the spec, the builder produces valid XML.

## Flow specification (what you write)

```json
{"name": "Flow1",
 "modules": [{"id": "src", "tool": "Image Source", "params": {"source_type": "Synthetic"}},
             {"id": "blur", "tool": "Image Filter", "params": {"filter_type": "Gaussian", "kernel_size": 5}}],
 "links":   [{"from": "src", "from_port": "Image", "to": "blur", "to_port": "Image"}]}
```

`id` is a short identifier used by links. `name` is optional. `params` lists only values that differ from
the defaults. The builder turns a valid spec into the application's solution XML.

## Solution XML (what the application stores)

```xml
<ApexSolution version="4.3" name="Demo" active_flow="Flow1" trigger_flow="Flow1">
  <Flows>
    <ApexFlow version="4.3" name="Flow1">
      <Nodes>
        <Node instance_id="src" tool_name="Image Source" name="01_ImageSource" category="Acquisition" enabled="true">
          <Parameters><Parameter name="source_type" type="str">Synthetic</Parameter></Parameters>
        </Node>
      </Nodes>
      <Connections>
        <Connection from_node="src" from_port="Image" to_node="blur" to_port="Image"/>
      </Connections>
      <Layout><Position node="src" x="50.0" y="50.0"/></Layout>
    </ApexFlow>
  </Flows>
</ApexSolution>
```

Parameter `type` is one of `str`, `int`, `float`, `bool`, `json` (lists and dictionaries), `null`.
`<Layout>` is optional presentation data. Files are loaded by the application with DTDs rejected.

## Recipes

Worked, validated specs for common tasks. Adapt them rather than starting from nothing.

<!-- BEGIN RECIPES -->
### Recipe: Clean the image and count objects
Use when: The user wants to count parts / particles: smooth, binarise, remove noise, then analyse connected regions.
```json
{
 "name": "Blob_Count",
 "modules": [
  {
   "id": "src",
   "tool": "Image Source"
  },
  {
   "id": "blur",
   "tool": "Image Filter",
   "params": {
    "filter_type": "Gaussian",
    "kernel_size": 5
   }
  },
  {
   "id": "bin",
   "tool": "Image Binarization",
   "params": {
    "method": "Otsu"
   }
  },
  {
   "id": "open",
   "tool": "Image Morphology",
   "params": {
    "operation": "Open",
    "kernel_size": 3
   }
  },
  {
   "id": "blobs",
   "tool": "BLOB Analysis",
   "params": {
    "min_area": 100
   }
  },
  {
   "id": "judge",
   "tool": "Condition Branch",
   "params": {
    "operator": "Between",
    "threshold_low": 1.0,
    "threshold_high": 10.0
   }
  }
 ],
 "links": [
  {
   "from": "src",
   "from_port": "Image",
   "to": "blur",
   "to_port": "Image"
  },
  {
   "from": "blur",
   "from_port": "Image",
   "to": "bin",
   "to_port": "Image"
  },
  {
   "from": "bin",
   "from_port": "Image",
   "to": "open",
   "to_port": "Image"
  },
  {
   "from": "open",
   "from_port": "Image",
   "to": "blobs",
   "to_port": "Image"
  },
  {
   "from": "blobs",
   "from_port": "Count",
   "to": "judge",
   "to_port": "Val_In"
  }
 ]
}
```

### Recipe: Colour presence check
Use when: The user wants to verify that a colour (green, red, blue, yellow or a custom HSV range) covers enough of the image.
```json
{
 "name": "Colour_Check",
 "modules": [
  {
   "id": "src",
   "tool": "Image Source"
  },
  {
   "id": "col",
   "tool": "Color Extraction",
   "params": {
    "preset_color": "Green",
    "min_ratio": 5.0
   }
  },
  {
   "id": "judge",
   "tool": "Condition Branch",
   "params": {
    "operator": ">=",
    "threshold_low": 5.0
   }
  }
 ],
 "links": [
  {
   "from": "src",
   "from_port": "Image",
   "to": "col",
   "to_port": "Image"
  },
  {
   "from": "col",
   "from_port": "Color_Ratio",
   "to": "judge",
   "to_port": "Val_In"
  }
 ]
}
```

### Recipe: Surface / PCB defect check with pass-fail verdict
Use when: The user wants to find scratches, dirt or other anomalies in a region and decide OK/NG by the number of defects.
```json
{
 "name": "Defect_Check",
 "modules": [
  {
   "id": "src",
   "tool": "Image Source",
   "params": {
    "source_type": "Synthetic",
    "pattern_type": "PCB Inspection"
   }
  },
  {
   "id": "defect",
   "tool": "Defect Detection",
   "params": {
    "roi": [
     260,
     240,
     180,
     120
    ],
    "sensitivity": 30
   }
  },
  {
   "id": "judge",
   "tool": "Condition Branch",
   "params": {
    "operator": "==",
    "threshold_low": 0.0
   }
  }
 ],
 "links": [
  {
   "from": "src",
   "from_port": "Image",
   "to": "defect",
   "to_port": "Image"
  },
  {
   "from": "defect",
   "from_port": "Defect_Count",
   "to": "judge",
   "to_port": "Val_In"
  }
 ]
}
```

### Recipe: Detect objects with a neural network and check the count
Use when: The user wants to find and count objects of known classes (needs the ultralytics package and a model file).
```json
{
 "name": "Detect_Objects",
 "modules": [
  {
   "id": "src",
   "tool": "Image Source"
  },
  {
   "id": "det",
   "tool": "Object Detection",
   "params": {
    "confidence": 0.25
   }
  },
  {
   "id": "count",
   "tool": "Condition Branch",
   "params": {
    "operator": ">=",
    "threshold_low": 1.0
   }
  }
 ],
 "links": [
  {
   "from": "src",
   "from_port": "Image",
   "to": "det",
   "to_port": "Image"
  },
  {
   "from": "det",
   "from_port": "Count",
   "to": "count",
   "to_port": "Val_In"
  }
 ]
}
```

### Recipe: Distance between two measured points
Use when: The user wants the distance between two features; points come from a Caliper (Edge1 / Edge2) or similar POINT outputs.
```json
{
 "name": "Point_Distance",
 "modules": [
  {
   "id": "src",
   "tool": "Image Source"
  },
  {
   "id": "cal",
   "tool": "Caliper",
   "params": {
    "line_p1": [
     100,
     300
    ],
    "line_p2": [
     500,
     300
    ]
   }
  },
  {
   "id": "p2p",
   "tool": "P2P Measure",
   "params": {
    "scale_factor": 1.0
   }
  },
  {
   "id": "tol",
   "tool": "Condition Branch",
   "params": {
    "operator": "<=",
    "threshold_low": 400.0
   }
  }
 ],
 "links": [
  {
   "from": "src",
   "from_port": "Image",
   "to": "cal",
   "to_port": "Image"
  },
  {
   "from": "cal",
   "from_port": "Edge1",
   "to": "p2p",
   "to_port": "Point1"
  },
  {
   "from": "cal",
   "from_port": "Edge2",
   "to": "p2p",
   "to_port": "Point2"
  },
  {
   "from": "p2p",
   "from_port": "Distance",
   "to": "tol",
   "to_port": "Val_In"
  }
 ]
}
```

### Recipe: Read text and check it against a pattern
Use when: The user wants to read a printed label / serial number and verify its content.
```json
{
 "name": "Read_Label",
 "modules": [
  {
   "id": "src",
   "tool": "Image Source"
  },
  {
   "id": "ocr",
   "tool": "OCR Recognition",
   "params": {
    "roi": [
     80,
     490,
     300,
     60
    ],
    "expected_pattern": "SN-*"
   }
  },
  {
   "id": "match",
   "tool": "Branch String",
   "params": {
    "target_text": "SN-",
    "match_mode": "Contains"
   }
  }
 ],
 "links": [
  {
   "from": "src",
   "from_port": "Image",
   "to": "ocr",
   "to_port": "Image"
  },
  {
   "from": "ocr",
   "from_port": "Text",
   "to": "match",
   "to_port": "Input_Text"
  }
 ]
}
```

### Recipe: Measure a width between two edges and check tolerance
Use when: The user wants a dimension (width, gap, thickness) in pixels and a tolerance check.
```json
{
 "name": "Width_Check",
 "modules": [
  {
   "id": "src",
   "tool": "Image Source",
   "params": {
    "source_type": "Synthetic",
    "pattern_type": "PCB Inspection"
   }
  },
  {
   "id": "cal",
   "tool": "Caliper",
   "params": {
    "line_p1": [
     50,
     150
    ],
    "line_p2": [
     450,
     150
    ],
    "caliper_mode": "Edge Pair"
   }
  },
  {
   "id": "tol",
   "tool": "Condition Branch",
   "params": {
    "operator": "Between",
    "threshold_low": 100.0,
    "threshold_high": 300.0
   }
  }
 ],
 "links": [
  {
   "from": "src",
   "from_port": "Image",
   "to": "cal",
   "to_port": "Image"
  },
  {
   "from": "cal",
   "from_port": "Distance",
   "to": "tol",
   "to_port": "Val_In"
  }
 ]
}
```

<!-- END RECIPES -->

## Tool catalogue

One section per tool: description, ports with types, parameters with defaults and allowed values.

<!-- BEGIN CATALOG -->
### 2D BCR Recognition
*Category:* Recognition. Decodes 2D DataMatrix and QR codes with polarity and error correction.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Code_Text` (STRING), `Code_Type` (STRING)
- Parameters:
  - `mode` (enum), default "QR Code"; choices: QR Code | DataMatrix
  - `polarity` (enum), default "Any"; choices: Any | Dark on White | White on Dark

### BCR Recognition
*Category:* Recognition. Decodes 1D Barcodes (Code128, EAN13, Code39) with angle tolerance.
- Inputs: `Image` (IMAGE)
- Outputs: `Barcode_Text` (STRING), `Format` (STRING)
- Parameters:
  - `window_size` (int), default 4; range 1 to 64
  - `symbology` (enum), default "Auto"; choices: Auto | Code128 | EAN13 | Code39
  - `expected_length` (int), default 0; range 0 to 128

### BLOB Analysis
*Category:* Location. Extracts connected binary regions, filters by area/circularity, and finds centroids.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Blobs` (ANY)
- Parameters:
  - `threshold` (int), default 128; range 0 to 255
  - `invert` (bool), default false
  - `min_area` (int), default 50; range 0 to 1e+08 px
  - `max_area` (int), default 50000; range 0 to 1e+08 px
  - `min_circularity` (float), default 0.0; range 0 to 1

### Branch
*Category:* Logic Tools. Branches execution using Index by Value or Index by Bit.
- Inputs: `Condition_In` (VALUE)
- Outputs: `Branch_Index` (VALUE), `Status` (STRING)
- Parameters:
  - `mode` (enum), default "Index by Value"; choices: Index by Value | Index by Bit
  - `target_value` (int), default 1; range -1e+06 to 1e+06
  - `bit_index` (int), default 0; range 0 to 31
  - `target_branches` (text), default ""

### Branch String
*Category:* Logic Tools. Text pattern matching for string branch selection.
- Inputs: `Input_Text` (STRING)
- Outputs: `Branch_Result` (BOOLEAN), `Status` (STRING)
- Parameters:
  - `target_text` (text), default "PASS"
  - `match_mode` (enum), default "Exact"; choices: Exact | Contains | Prefix
  - `debug_mode` (bool), default false

### Caliper
*Category:* Location. 1D subpixel edge profile caliper for single edge or edge pair distance & width measurement.
- Inputs: `Image` (IMAGE)
- Outputs: `Distance` (VALUE), `Edge1` (POINT), `Edge2` (POINT)
- Parameters:
  - `line_p1` (point), default [100, 300]
  - `line_p2` (point), default [500, 300]
  - `edge_threshold` (float), default 25.0; range 0 to 255
  - `polarity` (enum), default "Any"; choices: Any | Dark to light | Light to dark
  - `caliper_mode` (enum), default "Edge Pair"; choices: Single Edge | Edge Pair

### Camera IO
*Category:* Communication. Controls industrial camera Opto-isolated Digital Output pins (Strobe, OK Line, NG Line).  
**Has side effects** (network, files, hardware or user code): mention it to the user.
- Inputs: `Status_In` (STRING)
- Outputs: `Line0_Strobe` (BOOLEAN), `Line1_OK` (BOOLEAN), `Line2_NG` (BOOLEAN)
- Parameters:
  - `pulse_duration_ms` (int), default 20; range 1 to 10000 ms
  - `strobe_active_high` (bool), default true
  - `invert_logic` (bool), default false

### Circle Search
*Category:* Location. Searches circular holes and features using multi-ray calipers and circle fitting.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Center_X` (VALUE), `Center_Y` (VALUE), `Radius` (VALUE), `Circle` (CIRCLE)
- Parameters:
  - `center_x` (int), default 680; range 0 to 100000 px
  - `center_y` (int), default 480; range 0 to 100000 px
  - `min_radius` (int), default 20; range 1 to 5000 px
  - `max_radius` (int), default 75; range 1 to 5000 px
  - `caliper_rays` (int), default 32; range 8 to 360
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to light | Light to dark
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_threshold` (float), default 25.0; range 0 to 255

### Circle/Line Fit
*Category:* Image Generation. Fits circle or line on the basis of 3 or more coordinate feature points.
- Inputs: `Point_Set` (ANY)
- Outputs: `Center_X` (VALUE), `Center_Y` (VALUE), `Radius` (VALUE), `Angle_Deg` (VALUE)
- Parameters:
  - `fit_type` (enum), default "Circle Fit"; choices: Circle Fit | Line Fit
  - `default_points` (points), default [[100, 200], [200, 100], [300, 200], [200, 300]]

### Color Extraction
*Category:* Color Processing. Extracts target colors in HSV space (Red, Green, Blue, Yellow, Custom) and masks non-target pixels.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Mask` (IMAGE), `Color_Ratio` (VALUE), `Pixel_Count` (VALUE)
- Parameters:
  - `preset_color` (enum), default "Green"; choices: Green | Red | Blue | Yellow | Custom
  - `h_min` (int), default 35; range 0 to 179
  - `h_max` (int), default 85; range 0 to 179
  - `s_min` (int), default 40; range 0 to 255
  - `s_max` (int), default 255; range 0 to 255
  - `v_min` (int), default 40; range 0 to 255
  - `v_max` (int), default 255; range 0 to 255
  - `min_ratio` (float), default 5.0; range 0 to 100 %
  - `max_ratio` (float), default 100.0; range 0 to 100 %
  - `mask_output` (enum), default "Color Keep"; choices: Color Keep | Binary Mask | Inverse

### Color Measurement
*Category:* Color Processing. Measures mean RGB and HSV channels and color similarity inside ROI.
- Inputs: `Image` (IMAGE)
- Outputs: `Mean_R` (VALUE), `Mean_G` (VALUE), `Mean_B` (VALUE), `Mean_H` (VALUE), `Mean_S` (VALUE), `Mean_V` (VALUE)
- Parameters:
  - `roi` (rect), default [100, 100, 200, 200]
  - `target_rgb` (rgb), default [0, 150, 0]
  - `max_color_distance` (float), default 80.0; range 0 to 442

### Condition Branch
*Category:* Logic Tools. Evaluates comparison conditions (>, <, ==, !=) to trigger pass/fail or branch output.
- Inputs: `Val_In` (VALUE)
- Outputs: `Branch_Result` (BOOLEAN), `Status` (STRING)
- Parameters:
  - `operator` (enum), default ">="; choices: >= | <= | > | < | == | != | Between
  - `threshold_low` (float), default 50.0
  - `threshold_high` (float), default 150.0

### Defect Detection
*Category:* Defect Detection. Inspects surfaces for scratches, burrs, dirt, cracks, or surface anomalies.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Max_Defect_Area` (VALUE), `Boxes` (ANY), `Classes` (ANY), `Scores` (ANY), `Detections` (ANY)
- Parameters:
  - `roi` (rect), default [260, 240, 180, 120]
  - `defect_type` (combo), default "Dark / Scratch"; choices: Dark / Scratch | Bright / Burr | Dirt / Stain | Crack / Break
  - `sensitivity` (int), default 35; range 1 to 255
  - `min_defect_area` (int), default 10; range 0 to 1e+07 px
  - `max_defect_area` (int), default 500; range 0 to 1e+07 px

### Edge Distance
*Category:* Measurement. Measures distance between two feature edges along scan projection axis.
- Inputs: `Image` (IMAGE)
- Outputs: `Distance` (VALUE)
- Parameters:
  - `start_pt` (point), default [100, 300]
  - `end_pt` (point), default [500, 300]
  - `min_distance` (float), default 10.0; range 0 to 100000 px
  - `max_distance` (float), default 1000.0; range 0 to 100000 px
  - `edge_threshold` (float), default 25.0; range 0 to 255

### Edge Search
*Category:* Location. Searches feature edge transition along projection ray (First, Last, Strongest Edge).
- Inputs: `Image` (IMAGE)
- Outputs: `Edge_X` (VALUE), `Edge_Y` (VALUE), `Strength` (VALUE)
- Parameters:
  - `start_pt` (point), default [100, 250]
  - `end_pt` (point), default [500, 250]
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `polarity` (enum), default "Any"; choices: Any | Dark to light | Light to dark
  - `edge_threshold` (float), default 25.0; range 0 to 255

### Geometry Generation
*Category:* Image Generation. Generates synthetic auxiliary geometric fixtures (Datum lines, Crosshairs, Circles).
- Inputs: none
- Outputs: `Line` (LINE), `Circle` (CIRCLE), `Point` (POINT)
- Parameters:
  - `geom_type` (enum), default "Datum Cross"; choices: Datum Cross | Reference Line | Pitch Circle
  - `center_x` (float), default 400.0; range 0 to 100000 px
  - `center_y` (float), default 300.0; range 0 to 100000 px
  - `radius` (float), default 50.0; range 0 to 100000 px
  - `line_p1` (point), default [100.0, 300.0]
  - `line_p2` (point), default [700.0, 300.0]

### Histogram
*Category:* Measurement. Statistical analysis of grayscale distribution (Mean, Median, Peak, StdDev, Contrast, Min, Max).
- Inputs: `Image` (IMAGE)
- Outputs: `Mean` (VALUE), `Median` (VALUE), `Peak` (VALUE), `StdDev` (VALUE), `Contrast` (VALUE)
- Parameters:
  - `roi` (rect), default [50, 50, 400, 300]

### If Module
*Category:* Logic Tools. Condition detection with All/Any judge method against valid numeric range.
- Inputs: `Val_In` (VALUE)
- Outputs: `Result` (BOOLEAN), `Status` (STRING)
- Parameters:
  - `judge_method` (enum), default "All"; choices: All | Any
  - `min_val` (float), default 0.0
  - `max_val` (float), default 100.0
  - `condition_type` (enum), default "Float"; choices: Float | Integer

### Image Binarization
*Category:* Image Processing. Converts grayscale/color image to binary using Manual, Otsu, or Adaptive thresholding.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `method` (enum), default "Otsu"; choices: Otsu | Adaptive | Manual
  - `threshold` (int), default 128; range 0 to 255
  - `invert` (bool), default false
  - `adaptive_block_size` (int), default 11; range 3 to 99
  - `adaptive_c` (int), default 2; range -50 to 50

### Image Buffer
*Category:* Acquisition. Circular FIFO image buffer for defect review and solution traceability.
- Inputs: `Image` (IMAGE)
- Outputs: `Buffer_Count` (VALUE), `Latest_Image` (IMAGE)
- Parameters:
  - `buffer_capacity` (int), default 30; range 1 to 1000
  - `buffer_condition` (enum), default "All Images"; choices: All Images | NG Only

### Image Filter
*Category:* Image Processing. Spatial filtering: Gaussian blur, Median filter, Bilateral, or Sharpening.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `filter_type` (enum), default "Gaussian"; choices: Gaussian | Median | Sharpen | Bilateral
  - `kernel_size` (int), default 5; range 1 to 31
  - `sigma` (float), default 1.5; range 0 to 50

### Image Morphology
*Category:* Image Processing. Morphological operations: Dilate, Erode, Open, Close, Gradient.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `operation` (enum), default "Open"; choices: Open | Close | Dilate | Erode | Gradient
  - `kernel_size` (int), default 3; range 1 to 51
  - `iterations` (int), default 1; range 1 to 50

### Image Output
*Category:* Acquisition. Saves acquired or processed images to disk with date/time formatting and quality options.  
**Has side effects** (network, files, hardware or user code): mention it to the user.
- Inputs: `Image` (IMAGE), `Trigger` (BOOLEAN)
- Outputs: `File_Path` (STRING)
- Parameters:
  - `save_directory` (dir), default "./saved_images"
  - `file_format` (enum), default "PNG"; choices: PNG | JPEG | BMP
  - `save_mode` (enum), default "Always Save"; choices: Always Save | Only on NG | Only on OK
  - `image_quality` (int), default 95; range 1 to 100 %

### Image Source
*Category:* Acquisition. Load image from local disk, camera, or synthetic test pattern.
- Inputs: none
- Outputs: `Image` (IMAGE), `Width` (VALUE), `Height` (VALUE)
- Parameters:
  - `source_type` (enum), default "Synthetic"; choices: Synthetic | File | Camera | Industrial GigE | Industrial USB3 | IP Stream
  - `file_path` (path), default "<app>/apex_vision/samples/pcb_sample.png"
  - `pattern_type` (enum), default "PCB Inspection"; choices: PCB Inspection | Calibration Grid | Circles & Holes | Barcode Sample
  - `color_mode` (enum), default "BGR"; choices: BGR | Grayscale
  - `camera_device` (device), default "mvs_gige_0"
  - `camera_index` (int), default 0; range 0 to 16
  - `exposure_time_us` (float), default 20000.0; range 10 to 1e+07 us
  - `gain` (float), default 1.0; range 0 to 48 x
  - `trigger_mode` (enum), default "Continuous"; choices: Continuous | Software Trigger | Hardware Trigger (Line0) | Hardware Trigger (Line1)
  - `mvs_config_file` (path), default ""
  - `mvs_trigger_source` (enum), default "Software"; choices: Software | Line0 | Line1
  - `stream_url` (text), default "rtsp://192.168.1.64:554/ch1/main"

### Intensity Measure
*Category:* Measurement. Measures mean, min, max, and std deviation of gray intensity inside ROI.
- Inputs: `Image` (IMAGE)
- Outputs: `Mean` (VALUE), `StdDev` (VALUE), `Min` (VALUE), `Max` (VALUE)
- Parameters:
  - `roi` (rect), default [200, 200, 200, 150]
  - `min_mean` (float), default 20.0; range 0 to 255
  - `max_mean` (float), default 240.0; range 0 to 255

### L2L Measure
*Category:* Measurement. Line to Line Distance and Angle measurement.
- Inputs: `Line1` (LINE), `Line2` (LINE)
- Outputs: `Distance` (VALUE), `Angle_Diff` (VALUE)
- Parameters:
  - `scale_factor` (float), default 1.0; range 1e-06 to 1e+06
  - `min_distance` (float), default 0.0; range 0 to 1e+09
  - `max_distance` (float), default 1000.0; range 0 to 1e+09
  - `default_l1` (line), default [50, 150, 450, 150]
  - `default_l2` (line), default [80, 400, 600, 400]

### Lens Distortion Calibration
*Category:* Calibration. Rectifies camera lens optical distortion (barrel/pincushion) using calibrated camera matrix and coefficients.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `RMS_Error` (VALUE), `Focal_Length_X` (VALUE), `Focal_Length_Y` (VALUE), `Principal_X` (VALUE), `Principal_Y` (VALUE), `Dist_K1` (VALUE), `Dist_K2` (VALUE)
- Parameters:
  - `mode` (enum), default "Manual Coefficients"; choices: Profile File | Manual Coefficients | Live Chessboard
  - `calibration_file` (path), default ""
  - `alpha` (float), default 0.0; range 0 to 1
  - `manual_fx` (float), default 650.0; range 1 to 100000
  - `manual_fy` (float), default 650.0; range 1 to 100000
  - `manual_cx` (float), default 400.0; range 0 to 100000
  - `manual_cy` (float), default 300.0; range 0 to 100000
  - `manual_k1` (float), default -0.2
  - `manual_k2` (float), default 0.05
  - `manual_p1` (float), default 0.0
  - `manual_p2` (float), default 0.0
  - `show_overlay` (bool), default true

### Line Search
*Category:* Location. Searches straight edges using perpendicular caliper rakes and M-estimator line fitting.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Angle_Deg` (VALUE), `Line` (LINE)
- Parameters:
  - `start_pt` (point), default [50, 150]
  - `end_pt` (point), default [450, 150]
  - `caliper_rake_width` (int), default 40; range 1 to 1000 px
  - `caliper_count` (int), default 25; range 3 to 200
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to light | Light to dark
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_threshold` (float), default 25.0; range 0 to 255

### Linear Edge Defect
*Category:* Defect Detection. Detects burrs, notches, and irregularities along a feature edge.
- Inputs: `Image` (IMAGE)
- Outputs: `Burr_Count` (VALUE), `Max_Deviation` (VALUE)
- Parameters:
  - `start_pt` (point), default [80, 400]
  - `end_pt` (point), default [600, 400]
  - `max_allowed_deviation` (float), default 3.0; range 0 to 10000 px

### N-Point Calibration
*Category:* Calibration. Calibrates camera pixel coordinates to real-world/robot coordinates (mm) using N-Point pairs.
- Inputs: `Pixel_X` (VALUE), `Pixel_Y` (VALUE)
- Outputs: `World_X` (VALUE), `World_Y` (VALUE), `Scale_X` (VALUE), `Scale_Y` (VALUE)
- Parameters:
  - `calibration_mode` (enum), default "9-Point Affine"; choices: 9-Point Affine | 4-Point Homography | 2-Point Scaling
  - `pixel_points` (points), default [[100, 100], [400, 100], [700, 100], [100, 300], [400, 300], [700, 300], [100, 500], [400, 500], [700, 500]]
  - `world_points` (points), default [[10.0, 10.0], [40.0, 10.0], [70.0, 10.0], [10.0, 30.0], [40.0, 30.0], [70.0, 30.0], [10.0, 50.0], [40.0, 50.0], [70.0, 50.0]]

### OCR Recognition
*Category:* Recognition. Optical Character Recognition for reading label text, lot numbers, and serial codes.
- Inputs: `Image` (IMAGE)
- Outputs: `Text` (STRING), `Confidence` (VALUE)
- Parameters:
  - `roi` (rect), default [80, 490, 300, 60]
  - `char_polarity` (enum), default "White on Dark"; choices: White on Dark | Dark on White
  - `min_confidence` (float), default 75.0; range 0 to 100 %
  - `expected_pattern` (text), default "SN-*"

### Object Detection
*Category:* Recognition. Object detection inference powered by Ultralytics YOLO (YOLOv11 default).
- Inputs: `Image` (IMAGE), `ROI` (REGION)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Boxes` (ANY), `Classes` (ANY), `Scores` (ANY), `Status` (STRING), `Detections` (ANY)
- Parameters:
  - `model_path` (path), default "yolo11n.pt"
  - `confidence` (float), default 0.25; range 0 to 1
  - `iou` (float), default 0.45; range 0 to 1
  - `classes` (text), default "all"
  - `device` (enum), default "cpu"; choices: cpu | cuda | auto
  - `max_detections` (int), default 100; range 1 to 1000

### P2P Measure
*Category:* Measurement. Point to Point Euclidean and axis distance measurement.
- Inputs: `Point1` (POINT), `Point2` (POINT)
- Outputs: `Distance` (VALUE), `Delta_X` (VALUE), `Delta_Y` (VALUE)
- Parameters:
  - `scale_factor` (float), default 1.0; range 1e-06 to 1e+06
  - `default_p1` (point), default [150, 150]
  - `default_p2` (point), default [350, 150]
  - `min_distance` (float), default 0.0; range 0 to 1e+09
  - `max_distance` (float), default 1000.0; range 0 to 1e+09

### PCB Board Layout
*Category:* Acquisition. Board design geometry (pad and trace rectangles) for a synthetic PCB, supplied to the defect detector as inspection context.
- Inputs: `Trigger` (BOOLEAN)
- Outputs: `Pad Layout` (ANY), `Trace Layout` (ANY)
- Parameters:
  - `board_seed` (int), default 20230510; range 0 to 2.14748e+09
  - `image_width` (int), default 640; range 64 to 8192 px
  - `image_height` (int), default 480; range 64 to 8192 px

### PCB Defect Detection
*Category:* Recognition. Deterministic classical PCB defect detector: finds scratches, voids, missing paste and missing copper, and emits structured detections for evaluation and failure analysis.
- Inputs: `Image` (IMAGE), `Pad Layout` (ANY), `Trace Layout` (ANY)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Boxes` (ANY), `Classes` (ANY), `Scores` (ANY), `Detections` (ANY), `Status` (STRING)
- Parameters:
  - `variant` (enum), default "reference"; choices: reference
  - `confidence_threshold` (float), default 0.0; range 0 to 1
  - `min_area` (int), default 60; range 0 to 1e+06 px
  - `dark_floor` (int), default 30; range 0 to 255
  - `max_detections` (int), default 40; range 1 to 1000

### Pixel Count
*Category:* Measurement. Counts pixels matching low/high threshold range within specified ROI.
- Inputs: `Image` (IMAGE)
- Outputs: `Pixel_Count` (VALUE), `Ratio` (VALUE)
- Parameters:
  - `roi` (rect), default [100, 100, 300, 200]
  - `low_threshold` (int), default 128; range 0 to 255
  - `high_threshold` (int), default 255; range 0 to 255
  - `min_count` (int), default 100; range 0 to 1e+09
  - `max_count` (int), default 50000; range 0 to 1e+09

### Position Correction
*Category:* Location. Establishes reference match point & angle to calculate position deviation for subsequent tool ROIs.
- Inputs: `Running_X` (VALUE), `Running_Y` (VALUE), `Running_Angle` (VALUE)
- Outputs: `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Parameters:
  - `fiducial_x` (float), default 350.0
  - `fiducial_y` (float), default 300.0
  - `fiducial_angle` (float), default 0.0; range -360 to 360 deg
  - `set_current_as_fiducial` (bool), default false

### Script
*Category:* Logic Tools. Executes custom Python script with access to context, OpenCV, NumPy, and outputs.  
**Has side effects** (network, files, hardware or user code): mention it to the user.
- Inputs: `Image` (IMAGE), `Val1` (VALUE), `Val2` (VALUE)
- Outputs: `Image` (IMAGE), `Result` (ANY), `Status` (STRING)
- Parameters:
  - `code` (code), default "(multi-line text)"

### TCP Send
*Category:* Communication. Sends inspection results, coordinates, or formatted strings to PLC/Robot via TCP/IP socket.  
**Has side effects** (network, files, hardware or user code): mention it to the user.
- Inputs: `Data` (ANY), `Trigger` (BOOLEAN)
- Outputs: `Sent_Bytes` (VALUE), `Last_Message` (STRING)
- Parameters:
  - `mode` (enum), default "Simulation (Loopback Log)"; choices: Simulation (Loopback Log) | TCP Client
  - `server_ip` (text), default "127.0.0.1"
  - `server_port` (int), default 8080; range 1 to 65535
  - `prefix` (text), default "VM_RES,"
  - `suffix` (text), default "\\r\\n"
  - `format` (enum), default "CSV"; choices: CSV | JSON | Plain Text
  - `connect_timeout_ms` (int), default 500; range 50 to 60000 ms

### Template Match
*Category:* Location. Searches for a template pattern with confidence score, subpixel translation, and rotation angle.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Score` (VALUE), `Center_X` (VALUE), `Center_Y` (VALUE), `Angle` (VALUE), `Box` (REGION)
- Parameters:
  - `min_score` (float), default 0.65; range 0 to 1
  - `template_roi` (rect), default [260, 240, 180, 120]
  - `start_angle` (float), default -15.0; range -180 to 180 deg
  - `end_angle` (float), default 15.0; range -180 to 180 deg
  - `angle_step` (float), default 2.0; range 0.1 to 90 deg
  - `max_matches` (int), default 1; range 1 to 100

### Trigger
*Category:* Logic Tools. Triggers execution of another flow in the solution.
- Inputs: `Trigger_Signal` (BOOLEAN)
- Outputs: `Status` (STRING)
- Parameters:
  - `target_flow` (flow), default "Flow2"
  - `require_signal_true` (bool), default true

### Variable Calculation
*Category:* Logic Tools. Performs mathematical arithmetic on input values (+, -, *, /, scale).
- Inputs: `Val_A` (VALUE), `Val_B` (VALUE)
- Outputs: `Result` (VALUE)
- Parameters:
  - `operation` (enum), default "+"; choices: + | - | * | / | Scale
  - `scale_factor` (float), default 1.0
  - `default_a` (float), default 10.0
  - `default_b` (float), default 5.0

<!-- END CATALOG -->
