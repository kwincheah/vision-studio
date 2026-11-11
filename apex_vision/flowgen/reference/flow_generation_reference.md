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
- **A rectangle that is `[0, 0, 0, 0]` means the whole image**, and that is the default almost everywhere (many
  modules, such as filters, thresholding and OCR, also take an optional `roi`). Set a rectangle only when the
  user names a region or the task needs one; never invent coordinates for an unknown picture.
  A few modules need a drawn region and report "draw the region first" while it is empty: `Template Match`
  (`template_roi`, the part to look for), `Affine Transformation`, `Inverse Affine Transformation`.
- Lines and points (`line_p1`, `start_pt`) are `[x, y]` in pixels.
- Text parameters with a listed set of choices must use one of those values exactly (case and spaces).
  Text parameters without choices keep their default unless the user asks for something specific.
- The synthetic test image is 800 x 600 pixels; coordinates should lie inside the real image.

## Building a good flow

1. Start from an acquisition module (`Image Source`). Use `source_type` `Synthetic` unless the user names
   a file or camera. `File` needs `file_path`; `Camera` is a webcam and lets the camera set exposure and gain
   itself (`auto_exposure` true): set `exposure_time_us` and `gain` only together with `auto_exposure` false.
   Industrial GigE / USB3 and Hikrobot MVS cameras always use the exposure and gain values. A new flow made in the
   application starts with an empty `File` source; it brings no sample picture.
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
- Leaving `OCR Recognition.expected_pattern` at its default `SN-*`: any text that does not start with `SN-` is
  judged NG even when it was read correctly. Set it to `""` (any text) or to the format the user gives.
- Wiring a list output (`Blobs`, `Areas`, `Centers`) into an `Image` input: ANY ports connect, but a list is not
  an image, so the receiving module reports NG. Link `Image` outputs to `Image` inputs.
- Choosing a PyTorch `.pt` model for `Object Detection`: it needs the optional converter add-on. The default,
  `yolo11n.onnx`, runs everywhere; other deep-learning modules take `.onnx` files only.

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

### Recipe: Surface defect check with pass-fail verdict
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
    "pattern_type": "Part with Defects"
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
    "pattern_type": "Part with Defects"
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
### 2D Array Correction
*Category:* Division and Combination. When parts sit in a regular grid but the locator missed some or put some in the wrong place, this rebuilds the full grid: it fits a line through each row and each column of the found centres and places every box where the lines cross.
- Inputs: `Boxes` (ANY)
- Outputs: `Boxes` (ANY), `Count` (VALUE), `Centers` (ANY)
- Parameters:
  - `array_rows` (int), default 2; range 2 to 100
  - `array_columns` (int), default 3; range 2 to 100

### 2D BCR Recognition
*Category:* Recognition. Decodes 2D DataMatrix and QR codes with polarity and error correction.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Code_Text` (STRING), `Code_Type` (STRING)
- Parameters:
  - `mode` (enum), default "QR Code"; choices: QR Code | DataMatrix
  - `polarity` (enum), default "Any"; choices: Any | Dark on White | White on Dark
  - `roi` (rect), default [0, 0, 0, 0]

### Affine Transformation
*Category:* Image Processing. Cuts a (turned) rectangle out of the picture and resizes it. Set the region, its angle, the scale and the aspect ratio.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Width` (VALUE), `Height` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `roi_angle` (float), default 0.0; range -360 to 360 deg
  - `scale` (float), default 1.0; range 0.01 to 20
  - `aspect_ratio` (float), default 1.0; range 0.05 to 20
  - `interpolation` (enum), default "Bilinear"; choices: Nearest Neighbor | Bilinear
  - `fill_mode` (enum), default "Constant"; choices: Constant | Copy Nearby
  - `fill_value` (int), default 0; range 0 to 255

### Angle Measure
*Category:* Measurement. The angle at a vertex between two other points (A - Vertex - C), from 0 to 180 degrees.
- Inputs: `Point_A` (POINT), `Vertex` (POINT), `Point_C` (POINT)
- Outputs: `Angle_Deg` (VALUE)
- Parameters:
  - `default_a` (point), default [300, 200]
  - `default_vertex` (point), default [200, 200]
  - `default_c` (point), default [200, 100]
  - `min_angle` (float), default 0.0; range 0 to 180 deg
  - `max_angle` (float), default 180.0; range 0 to 180 deg

### Arc Edge Defect Detection
*Category:* Defect Detection. Checks a circular edge for pits, bumps and breaks: calipers are laid round the arc, the best-fit circle is drawn through the edge, and every stretch that strays beyond the minimum distance or has no edge is a defect, with its size, depth and box.
- Inputs: `Image` (IMAGE), `Circle` (CIRCLE), `Angle_Start` (VALUE), `Angle_Range` (VALUE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Defects` (ANY), `Defect_Boxes` (ANY), `Max_Depth` (VALUE), `Max_Size` (VALUE), `Max_Area` (VALUE), `Edge_Points` (ANY), `Edge_Count` (VALUE), `Fit_Residual` (VALUE), `Fit_Line` (LINE), `Fit_Circle` (CIRCLE)
- Parameters:
  - `input_mode` (enum), default "By Parameter"; choices: By Circle | By Parameter
  - `circle_x` (float), default 320.0; range -1e+06 to 1e+06 px
  - `circle_y` (float), default 240.0; range -1e+06 to 1e+06 px
  - `radius` (float), default 150.0; range 2 to 1e+06 px
  - `angle_start` (float), default 0.0; range -720 to 720 deg
  - `angle_range` (float), default 360.0; range -720 to 720 deg
  - `roi_mode` (enum), default "Draw"; choices: Draw | Inherit
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Both"; choices: Both | Dark to Light | Light to Dark
  - `filter_size` (int), default 3; range 1 to 50
  - `contrast_threshold` (int), default 20; range 0 to 255
  - `caliper_height` (int), default 5; range 1 to 500 px
  - `caliper_length` (int), default 40; range 4 to 2000 px
  - `caliper_spacing` (int), default 6; range 1 to 1000 px
  - `defect_polarity` (enum), default "Both Defects"; choices: Both Defects | Left Defect | Right Defect
  - `rough_min_distance` (float), default 3.0; range 0 to 1000 px
  - `size_enable` (bool), default false
  - `rough_min_size` (float), default 5.0; range 0 to 100000 px
  - `area_enable` (bool), default false
  - `rough_min_area` (float), default 10.0; range 0 to 1e+09 px2
  - `fracture_enable` (bool), default true
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Arc-Pair Defect Detection
*Category:* Defect Detection. Checks the ring between two circular edges: at each position round the arc a pair of edges is found and its width measured; where the width is outside the eligible range or no pair is found, that stretch is a defect.
- Inputs: `Image` (IMAGE), `Circle` (CIRCLE), `Angle_Start` (VALUE), `Angle_Range` (VALUE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Defects` (ANY), `Defect_Boxes` (ANY), `Max_Depth` (VALUE), `Max_Size` (VALUE), `Max_Area` (VALUE), `Widths` (ANY), `Pair_Count` (VALUE), `Min_Width` (VALUE), `Max_Width` (VALUE), `Mean_Width` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Parameter"; choices: By Circle | By Parameter
  - `circle_x` (float), default 320.0; range -1e+06 to 1e+06 px
  - `circle_y` (float), default 240.0; range -1e+06 to 1e+06 px
  - `radius` (float), default 150.0; range 2 to 1e+06 px
  - `angle_start` (float), default 0.0; range -720 to 720 deg
  - `angle_range` (float), default 360.0; range -720 to 720 deg
  - `roi_mode` (enum), default "Draw"; choices: Draw | Inherit
  - `edge_search_type` (enum), default "Widest Edge Pair"; choices: Widest Edge Pair | Nearest Edge Pair | Strongest & Nearest Edge Pair
  - `edge0_polarity` (enum), default "Dark to Light"; choices: Both | Dark to Light | Light to Dark
  - `edge1_polarity` (enum), default "Light to Dark"; choices: Both | Dark to Light | Light to Dark
  - `filter_size` (int), default 3; range 1 to 50
  - `contrast_threshold` (int), default 20; range 0 to 255
  - `ideal_width` (float), default 20.0; range 0 to 100000 px
  - `caliper_height` (int), default 5; range 1 to 500 px
  - `caliper_length` (int), default 60; range 4 to 4000 px
  - `caliper_spacing` (int), default 5; range 1 to 1000 px
  - `width_min` (float), default 15.0; range 0 to 100000 px
  - `width_max` (float), default 25.0; range 0 to 100000 px
  - `size_enable` (bool), default false
  - `rough_min_size` (float), default 5.0; range 0 to 100000 px
  - `area_enable` (bool), default false
  - `rough_min_area` (float), default 10.0; range 0 to 1e+09 px2
  - `fracture_enable` (bool), default true
  - `track_tolerance` (float), default 0.0; range 0 to 10000 px

### BCR Recognition
*Category:* Recognition. Decodes 1D Barcodes (Code128, EAN13, Code39) with angle tolerance.
- Inputs: `Image` (IMAGE)
- Outputs: `Barcode_Text` (STRING), `Format` (STRING)
- Parameters:
  - `window_size` (int), default 4; range 1 to 64
  - `symbology` (enum), default "Auto"; choices: Auto | Code128 | EAN13 | Code39
  - `expected_length` (int), default 0; range 0 to 128
  - `roi` (rect), default [0, 0, 0, 0]

### BLOB Analysis
*Category:* Location. Finds connected regions (blobs) of a binary or thresholded picture and measures each: area, perimeter, centre, box and its angle, major / minor axis, circularity, rectangularity and more. Choose how the picture is thresholded, which blobs to keep (by any measure), and how to sort them.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Binary` (IMAGE), `Count` (VALUE), `Total_Area` (VALUE), `Blobs` (ANY), `Areas` (ANY), `Centers` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `threshold_mode` (enum), default "Single Threshold"; choices: Single Threshold | Double Threshold | Auto Threshold | Soft Threshold (Fixed) | Soft Threshold (Relative) | None (already binary)
  - `threshold` (int), default 128; range 0 to 255
  - `high_threshold` (int), default 255; range 0 to 255
  - `invert` (bool), default false
  - `min_area` (int), default 50; range 0 to 1e+08 px
  - `max_area` (int), default 50000; range 0 to 1e+08 px
  - `min_circularity` (float), default 0.0; range 0 to 1
  - `max_circularity` (float), default 1.0; range 0 to 1
  - `min_rectangularity` (float), default 0.0; range 0 to 1
  - `max_rectangularity` (float), default 1.0; range 0 to 1
  - `min_axis_ratio` (float), default 0.0; range 0 to 1
  - `max_axis_ratio` (float), default 1.0; range 0 to 1
  - `min_perimeter` (int), default 0; range 0 to 1e+07 px
  - `max_perimeter` (int), default 1000000; range 0 to 1e+07 px
  - `min_rect_width` (int), default 0; range 0 to 1e+07 px
  - `max_rect_width` (int), default 1000000; range 0 to 1e+07 px
  - `min_rect_height` (int), default 0; range 0 to 1e+07 px
  - `max_rect_height` (int), default 1000000; range 0 to 1e+07 px
  - `min_major_axis` (int), default 0; range 0 to 1e+07 px
  - `max_major_axis` (int), default 1000000; range 0 to 1e+07 px
  - `min_minor_axis` (int), default 0; range 0 to 1e+07 px
  - `max_minor_axis` (int), default 1000000; range 0 to 1e+07 px
  - `max_barycenter_offset` (int), default 1000000; range 0 to 1e+07 px
  - `min_hole_area` (int), default 0; range 0 to 1e+07 px
  - `max_blobs` (int), default 500; range 1 to 100000
  - `connectivity` (enum), default "8-connected"; choices: 8-connected | 4-connected
  - `sort_feature` (enum), default "Area"; choices: Area | Perimeter | Circularity | Rectangularity | Center X | Center Y | Box Angle | Box Width | Box Height | Box Left | Box Top | Second-order Center Distance | Principal Axis Angle | Axis Ratio
  - `sort_type` (enum), default "No Sorting"; choices: No Sorting | Ascending | Descending
  - `contour_output` (bool), default false

### BLOB Label Analysis
*Category:* Location. BLOB analysis for a picture whose pixel values are class numbers (for example the output of deep-learning segmentation): finds the connected regions of each class and reports each with its class name, size and shape. Filter by size per class or overall, and sort.
- Inputs: `Image` (IMAGE), `Label_Names` (ANY), `Gray_Values` (ANY)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Blobs` (ANY), `Labels` (ANY), `Label_Values` (ANY), `Areas` (ANY), `Centers` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `label_names` (text), default ""
  - `gray_values` (text), default ""
  - `label_level_area` (bool), default false
  - `label_min_area` (int), default 20; range 0 to 1e+09 px
  - `label_max_area` (int), default 1000000; range 0 to 1e+09 px
  - `global_area` (bool), default true
  - `global_min_area` (int), default 20; range 0 to 1e+09 px
  - `global_max_area` (int), default 10000000; range 0 to 1e+09 px
  - `invert_area_filter` (bool), default false
  - `max_blobs` (int), default 100; range 1 to 100000
  - `connectivity` (enum), default "8-connected"; choices: 4-connected | 8-connected
  - `min_axis_ratio` (float), default 0.0; range 0 to 1
  - `max_axis_ratio` (float), default 1.0; range 0 to 1
  - `sort_feature` (enum), default "Area"; choices: Area | Perimeter | Circularity | Rectangularity | Center X | Center Y | Box Angle | Box Width | Box Height | Box Left | Box Top | Second-order Center Distance | Principal Axis Angle | Axis Ratio
  - `sort_type` (enum), default "Descending"; choices: Ascending | Descending | No Sorting
  - `min_overlap_rate` (float), default 0.0; range 0 to 100 %

### Box Filtering
*Category:* Division and Combination. Keeps only the boxes that are at least partly white in a mask picture: it counts the 255-valued pixels inside each box and drops boxes where that share is below the minimum.
- Inputs: `Image` (IMAGE), `Boxes` (ANY)
- Outputs: `Boxes` (ANY), `Removed` (ANY), `Count` (VALUE)
- Parameters:
  - `min_overlap` (float), default 0.1; range 0 to 1

### Box Merge
*Category:* Division and Combination. Joins boxes that overlap into one box. 'Flaw Priority' keeps the most important label of the group, 'Box Label' only joins boxes with the same label, 'No Box Label' joins any boxes that overlap.
- Inputs: `Boxes` (ANY), `Labels` (ANY)
- Outputs: `Boxes` (ANY), `Labels` (ANY), `Count` (VALUE)
- Parameters:
  - `overlap_rate` (float), default 0.3; range 0 to 1
  - `merge_type` (enum), default "Merge Type Flaw Priority"; choices: Merge Type Flaw Priority | Merge Type Box Label | Merge Type No Box Label
  - `flaw_priority` (text), default "scratch,dent,stain"
  - `split_char` (text), default ","
  - `priority_sort` (enum), default "Grade Down"; choices: Grade Up | Grade Down

### Box Overlap
*Category:* Division and Combination. How much two boxes overlap: the overlapped area divided by the area of the smaller box. 0 = apart, 1 = one is inside the other.
- Inputs: `Box1` (ANY), `Box2` (ANY)
- Outputs: `Overlap_Rate` (VALUE), `Overlap_Box` (ANY)
- Parameters:
  - `box1` (rect), default [0, 0, 0, 0]
  - `box2` (rect), default [0, 0, 0, 0]

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

### Brightness Contrast
*Category:* Image Processing. Brightens or darkens the image: manual brightness and contrast, gamma, automatic brightening to a target level, histogram equalisation, or local contrast (CLAHE).
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Mean_Before` (VALUE), `Mean_After` (VALUE)
- Parameters:
  - `mode` (enum), default "Auto Brighten"; choices: Manual | Auto Brighten | Gamma | Equalize | CLAHE
  - `brightness` (int), default 40; range -255 to 255
  - `contrast` (float), default 1.0; range 0.1 to 5 x
  - `gamma` (float), default 0.6; range 0.1 to 5
  - `target_mean` (int), default 120; range 1 to 254
  - `clip_limit` (float), default 3.0; range 0.5 to 40
  - `roi` (rect), default [0, 0, 0, 0]

### C2C Measure
*Category:* Measurement. Measures between two circles: the distance between their centres, the shortest gap between the outlines (0 where they cross, and for one inside the other the gap between them), the largest span, the angle of the line through both centres, the two closest points, and where the circles cross.
- Inputs: `Circle` (CIRCLE), `Circle2` (CIRCLE)
- Outputs: `Distance` (VALUE), `Center_Distance` (VALUE), `Max_Distance` (VALUE), `Radius_Diff` (VALUE), `Angle_Deg` (VALUE), `Point1` (POINT), `Point2` (POINT), `Cross_Points` (ANY), `Cross_Count` (VALUE), `Relation` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Circle | By Coordinate
  - `circle_x` (float), default 300.0; range -1e+06 to 1e+06 px
  - `circle_y` (float), default 200.0; range -1e+06 to 1e+06 px
  - `circle_r` (float), default 60.0; range 0.01 to 1e+06 px
  - `circle2_x` (float), default 500.0; range -1e+06 to 1e+06 px
  - `circle2_y` (float), default 200.0; range -1e+06 to 1e+06 px
  - `circle2_r` (float), default 40.0; range 0.01 to 1e+06 px
  - `angle_range` (enum), default "-180 to 180"; choices: -180 to 180 | -90 to 90
  - `scale_factor` (float), default 1.0; range 1e-06 to 1e+06

### Calculate Parallel Lines
*Category:* Location. Makes a line parallel to another: either through a point that is not on it, or a pair at a set distance either side of it.
- Inputs: `Line1` (LINE), `Point1_Start` (POINT), `Point1_End` (POINT), `Point` (POINT)
- Outputs: `Line_A` (LINE), `Line_B` (LINE), `Distance` (VALUE)
- Parameters:
  - `method` (enum), default "A Point Outside the Line"; choices: A Point Outside the Line | A Distance from the Line
  - `input_mode` (enum), default "By Coordinate"; choices: By Line | By Point | By Coordinate
  - `line1` (line), default [100, 200, 300, 160]
  - `point` (point), default [200, 120]
  - `distance` (float), default 30.0; range 0 to 100000 px

### Calculate Rotation
*Category:* Calculation. Turns a point or a line about a centre point by an angle (counterclockwise or clockwise as seen on the picture) and gives the point or line after the turn.
- Inputs: `Point` (POINT), `Line` (LINE), `Center` (POINT), `Angle` (VALUE)
- Outputs: `Point` (POINT), `X` (VALUE), `Y` (VALUE), `Line` (LINE), `Line_Angle` (VALUE)
- Parameters:
  - `input_method` (enum), default "By Point"; choices: By Point | By Line
  - `input_mode` (enum), default "By Coordinate"; choices: By Port | By Coordinate
  - `x` (float), default 200.0; range -1e+09 to 1e+09 px
  - `y` (float), default 100.0; range -1e+09 to 1e+09 px
  - `line` (line), default [100, 100, 300, 100]
  - `center_x` (float), default 100.0; range -1e+09 to 1e+09 px
  - `center_y` (float), default 100.0; range -1e+09 to 1e+09 px
  - `angle` (float), default 30.0; range -360 to 360 deg
  - `direction` (enum), default "Counterclockwise"; choices: Counterclockwise | Clockwise

### CalibBoard Calibration
*Category:* Calibration. Calibrates the camera from a picture of a calibration board (checkerboard or circle grid) of known size: finds the corners or dot centres, and builds the matrix that turns picture coordinates into millimetres. Gives the calibration error, scale and pixel size, and writes a calibration file for Calibration Transformation.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Status` (VALUE), `Calibration_Error` (VALUE), `Point_Count` (VALUE), `Calibration` (DICT), `Matrix` (ANY), `Scale` (VALUE), `Pixel_Accuracy` (VALUE), `Translation_X` (VALUE), `Translation_Y` (VALUE), `Rotation` (VALUE), `Skew` (VALUE), `Aspect_Ratio` (VALUE)
- Parameters:
  - `board_type` (enum), default "Checkerboard"; choices: Checkerboard | Circle Grid
  - `columns` (int), default 9; range 2 to 100
  - `rows` (int), default 6; range 2 to 100
  - `physical_size` (float), default 10.0; range 0.0001 to 100000 mm
  - `origin_x` (int), default 0; range 0 to 99
  - `origin_y` (int), default 0; range 0 to 99
  - `rotation_angle` (float), default 0.0; range -360 to 360 deg
  - `coordinate_system` (enum), default "Right-handed"; choices: Right-handed | Left-handed
  - `dot_type` (enum), default "Dark on Light"; choices: Dark on Light | Light on Dark
  - `gray_contrast` (float), default 0.0; range 0 to 255
  - `median_filter` (bool), default false
  - `subpixel_window` (int), default 0; range 0 to 15
  - `dof` (enum), default "Affine (adds aspect ratio and skew)"; choices: Similarity (scale, rotation, translation) | Affine (adds aspect ratio and skew) | Perspective (adds projection)
  - `weighting` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey | RANSAC
  - `weight_coeff` (float), default 0.0; range 0 to 100
  - `distance_threshold` (float), default 3.0; range 0.0001 to 100000
  - `sampling_rate` (float), default 0.8; range 0.1 to 1
  - `save_path` (path), default ""
  - `update_file` (bool), default false

### Calibration Transformation
*Category:* Calculation. Turns picture coordinates into physical ones (or the other way) with a calibration: a point, its angle, or a list of points. Also gives the calibration's pixel size, scale, shift, rotation, skew and aspect ratio.
- Inputs: `Point` (POINT), `Angle` (VALUE), `Points` (ANY), `Calibration` (DICT), `Refresh` (VALUE)
- Outputs: `X` (VALUE), `Y` (VALUE), `Point` (POINT), `Angle` (VALUE), `Points` (ANY), `Calibration` (DICT), `Matrix` (ANY), `Scale` (VALUE), `Pixel_Accuracy` (VALUE), `Translation_X` (VALUE), `Translation_Y` (VALUE), `Rotation` (VALUE), `Skew` (VALUE), `Aspect_Ratio` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `x` (float), default 100.0; range -1e+09 to 1e+09 px
  - `y` (float), default 100.0; range -1e+09 to 1e+09 px
  - `angle` (float), default 0.0; range -360 to 360 deg
  - `coordinate_type` (enum), default "Image to Physical"; choices: Image to Physical | Physical to Image
  - `calibration_file` (path), default ""

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

### Camera Mapping
*Category:* Calibration. Finds how two camera pictures relate: from the same features seen by both cameras (2 to 8 pairs of points) it builds the matrix that turns the running camera's coordinates into the demonstration camera's, and reports scale, shift, rotation, skew and aspect.
- Inputs: `Points_Demo` (ANY), `Points_Run` (ANY)
- Outputs: `Status` (VALUE), `Calibration_Error` (VALUE), `Calibration` (DICT), `Matrix` (ANY), `Scale` (VALUE), `Pixel_Accuracy` (VALUE), `Translation_X` (VALUE), `Translation_Y` (VALUE), `Rotation` (VALUE), `Skew` (VALUE), `Aspect_Ratio` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `demo_points` (points), default [[100, 100], [400, 100], [400, 300], [100, 300]]
  - `run_points` (points), default [[110, 105], [412, 99], [405, 302], [103, 309]]
  - `dof` (enum), default "Affine (adds aspect ratio and skew)"; choices: Similarity (scale, rotation, translation) | Affine (adds aspect ratio and skew) | Perspective (adds projection)
  - `weighting` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey | RANSAC
  - `weight_coeff` (float), default 0.0; range 0 to 100
  - `distance_threshold` (float), default 3.0; range 0.0001 to 100000
  - `sampling_rate` (float), default 0.8; range 0.1 to 1
  - `save_path` (path), default ""
  - `update_file` (bool), default false

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
*Category:* Image Generation. Fits a circle (3+ points), an ellipse (5+ points) or a line (2+ points) through a set of coordinates. Ellipse results: Center_X / Center_Y, Axis_A (long) and Axis_B (short) lengths, and Angle_Deg of the long axis.
- Inputs: `Point_Set` (ANY)
- Outputs: `Center_X` (VALUE), `Center_Y` (VALUE), `Radius` (VALUE), `Angle_Deg` (VALUE), `Axis_A` (VALUE), `Axis_B` (VALUE), `Circle` (CIRCLE), `Line` (LINE)
- Parameters:
  - `fit_type` (enum), default "Circle Fit"; choices: Circle Fit | Ellipse Fit | Line Fit
  - `default_points` (points), default [[100, 200], [200, 100], [300, 200], [200, 300]]

### Classification Registration
*Category:* Deep Learning. Finds which registered category a picture belongs to. Register example pictures under category names (whole pictures or a part of them, one at a time or a whole folder), then search: it returns the most similar categories and how similar. No training is needed - register more pictures to teach it more.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Class` (STRING), `Similarity` (VALUE), `Top` (ANY), `Categories` (ANY)
- Parameters:
  - `mode` (enum), default "Search"; choices: Search | Register Image | Register Folder | Delete Category | Clear Gallery
  - `roi` (rect), default [0, 0, 0, 0]
  - `category` (text), default ""
  - `register_folder` (dir), default ""
  - `gallery_file` (path), default ""
  - `top_k` (int), default 3; range 1 to 10
  - `min_similarity` (float), default 0.5; range 0 to 1
  - `gallery` (hidden), default {}

### Color Convert
*Category:* Image Processing. Converts to grayscale, HSV or Lab, or extracts one colour channel (red, green, blue, hue, saturation, value).
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `mode` (enum), default "Grayscale"; choices: Grayscale | Red channel | Green channel | Blue channel | Hue | Saturation | Value | HSV | Lab | Gray: Average | Gray: Minimum | Gray: Maximum | Gray: User-defined | HSI Channel 1 | HSI Channel 2 | HSI Channel 3 | YUV Channel 1 | YUV Channel 2 | YUV Channel 3
  - `coeff_r` (float), default 0.299; range -10 to 10
  - `coeff_g` (float), default 0.587; range -10 to 10
  - `coeff_b` (float), default 0.114; range -10 to 10
  - `roi` (rect), default [0, 0, 0, 0]

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
  - `roi` (rect), default [0, 0, 0, 0]

### Color Measurement
*Category:* Color Processing. Measures mean RGB and HSV channels and color similarity inside ROI.
- Inputs: `Image` (IMAGE)
- Outputs: `Mean_R` (VALUE), `Mean_G` (VALUE), `Mean_B` (VALUE), `Mean_H` (VALUE), `Mean_S` (VALUE), `Mean_V` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `target_rgb` (rgb), default [0, 150, 0]
  - `max_color_distance` (float), default 80.0; range 0 to 442

### Color Recognition
*Category:* Color Processing. Names the colour of a region by comparing it with samples you taught it (for example 'red', 'green', 'blue' caps). Learn samples with Mode = Learn, then recognise with Mode = Recognize. K nearest neighbours decide the class.
- Inputs: `Image` (IMAGE)
- Outputs: `Class` (STRING), `Score` (VALUE), `Scores` (ANY), `Samples` (ANY)
- Parameters:
  - `mode` (enum), default "Recognize"; choices: Recognize | Learn | Clear Samples
  - `learn_label` (text), default ""
  - `roi` (rect), default [0, 0, 0, 0]
  - `sensitivity_mode` (enum), default "Medium Sensitivity"; choices: Low Sensitivity | Medium Sensitivity | High Sensitivity
  - `feature_type` (enum), default "Feature Histogram"; choices: Feature Spectrum | Feature Histogram
  - `use_intensity` (bool), default true
  - `k_value` (int), default 3; range 1 to 50
  - `knn_distance` (enum), default "Intersection Distance"; choices: Euclidean Distance | Manhattan Distance | Intersection Distance
  - `min_score` (float), default 0.0; range 0 to 1
  - `samples` (json), default {}

### Condition Branch
*Category:* Logic Tools. Evaluates comparison conditions (>, <, ==, !=) to trigger pass/fail or branch output.
- Inputs: `Val_In` (VALUE)
- Outputs: `Branch_Result` (BOOLEAN), `Status` (STRING)
- Parameters:
  - `operator` (enum), default ">="; choices: >= | <= | > | < | == | != | Between
  - `threshold_low` (float), default 50.0
  - `threshold_high` (float), default 150.0

### Condition Detection
*Category:* Logic Tools. Checks whether values are inside their allowed ranges. Judge All means every value must pass, Any means one is enough. Each value comes from a connected module or is typed; the result is OK or NG and the verdict of every value is listed.
- Inputs: `Value1` (VALUE), `Value2` (VALUE), `Value3` (VALUE), `Value4` (VALUE), `Values` (ANY)
- Outputs: `Result` (VALUE), `Results` (ANY), `Passed` (VALUE)
- Parameters:
  - `judge_method` (enum), default "All"; choices: All | Any
  - `condition_type` (enum), default "Float"; choices: Int | Float
  - `values` (text), default ""
  - `ranges` (text), default "0,100"

### Coordinate Transformation
*Category:* Calculation. Finds where a point in a cut-out piece lies in the original big picture, given the piece's centre in the big picture and its size (use with Image Division). With the conversion off, points pass through unchanged.
- Inputs: `Center` (POINT), `Point` (POINT), `Points` (ANY)
- Outputs: `X` (VALUE), `Y` (VALUE), `Point` (POINT), `Points` (ANY)
- Parameters:
  - `enable` (bool), default true
  - `center_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `center_x` (float), default 320.0; range -1e+09 to 1e+09 px
  - `center_y` (float), default 240.0; range -1e+09 to 1e+09 px
  - `piece_width` (int), default 200; range 1 to 1e+06 px
  - `piece_height` (int), default 200; range 1 to 1e+06 px
  - `point_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `point_x` (float), default 100.0; range -1e+09 to 1e+09 px
  - `point_y` (float), default 100.0; range -1e+09 to 1e+09 px

### Copy Fill
*Category:* Image Processing. Fill: paints inside and outside a region with fixed grey values. Copy: keeps the region and spreads its own edge pixels over the rest of its bounding rectangle, so a round region can be processed as a clean rectangle.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `process_type` (enum), default "Fill"; choices: Fill | Copy
  - `roi` (rect), default [0, 0, 0, 0]
  - `roi_shape` (enum), default "Rectangle"; choices: Rectangle | Ellipse
  - `fill_outside` (int), default 0; range 0 to 255
  - `fill_inside` (int), default 255; range 0 to 255

### DL Anomaly
*Category:* Deep Learning. Finds anything that does not look like a good part, using an anomaly model (ONNX) trained on good images only: an autoencoder, or any model that outputs an anomaly map. Gives a heat map, a score, and a box around each anomaly.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Heatmap` (IMAGE), `Mask` (IMAGE), `Anomaly_Score` (VALUE), `Defect_Count` (VALUE), `Boxes` (ANY), `Detections` (ANY), `Status` (STRING)
- Parameters:
  - `model_path` (path), default ""
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `device` (enum), default "cpu"; choices: cpu | cuda
  - `input_width` (int), default 0; range 0 to 8192 px
  - `input_height` (int), default 0; range 0 to 8192 px
  - `resize` (enum), default "Auto"; choices: Auto | Stretch | Letterbox
  - `normalize` (enum), default "Auto"; choices: Auto | 0 to 1 | ImageNet (mean/std) | -1 to 1 | 0 to 255
  - `rgb_input` (bool), default true
  - `roi` (rect), default [0, 0, 0, 0]
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}
  - `output_type` (enum), default "Auto (from the model)"; choices: Auto (from the model) | Anomaly map | Reconstruction (autoencoder)
  - `map_threshold` (float), default 0.0; range 0 to 1e+06
  - `smoothing` (float), default 2.0; range 0 to 50
  - `min_area` (int), default 20; range 1 to 1e+08 px
  - `max_defect_count` (int), default 0; range 0 to 100000

### DL Character Location
*Category:* Recognition. Finds where each character is, as boxes, even on a busy background and where the print moves about. With a detection model (ONNX) it finds what the model was trained on; without one it finds dark or light characters by thresholding the region.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Boxes` (ANY), `Centers` (ANY), `Scores` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `model_file` (path), default ""
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `polarity` (enum), default "Auto"; choices: Auto | Dark on Light | Light on Dark
  - `max_number` (int), default 1; range 1 to 100
  - `min_confidence` (float), default 0.3; range 0 to 1
  - `overlap_threshold` (float), default 0.3; range 0 to 1
  - `sort_object` (enum), default "Center X"; choices: Center X | Center Y | Confidence
  - `edge_filter_enable` (bool), default false
  - `min_edge_score` (float), default 0.5; range 0 to 1
  - `width_enable` (bool), default false
  - `min_width` (int), default 5; range 1 to 10000 px
  - `max_width` (int), default 200; range 1 to 10000 px
  - `height_enable` (bool), default false
  - `min_height` (int), default 5; range 1 to 10000 px
  - `max_height` (int), default 200; range 1 to 10000 px
  - `min_area` (int), default 8; range 1 to 100000 px

### DL Character Recognition
*Category:* Recognition. Reads the text in a region. With a text model (ONNX, CTC) it reads the line directly; without one it finds each character and names it by comparing with letters, digits and symbols in several fonts (good for clean printed characters). The character filter limits what each character may be, which settles O / 0 and I / 1 doubts.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Text` (STRING), `Characters` (ANY), `Min_Score` (VALUE), `Count` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `model_file` (path), default ""
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `polarity` (enum), default "Auto"; choices: Auto | Dark on Light | Light on Dark
  - `max_number` (int), default 100; range 1 to 100
  - `min_confidence` (float), default 0.5; range 0 to 1
  - `overlap_threshold` (float), default 0.3; range 0 to 1
  - `sort_object` (enum), default "Center X"; choices: Center X | Center Y | Confidence
  - `edge_filter_enable` (bool), default false
  - `min_edge_score` (float), default 0.5; range 0 to 1
  - `width_enable` (bool), default false
  - `min_width` (int), default 5; range 1 to 10000 px
  - `max_width` (int), default 200; range 1 to 10000 px
  - `height_enable` (bool), default false
  - `min_height` (int), default 5; range 1 to 10000 px
  - `max_height` (int), default 200; range 1 to 10000 px
  - `min_area` (int), default 8; range 1 to 100000 px
  - `filter_enable` (bool), default false
  - `character_filter` (enum), default "All"; choices: All | Numbers | Uppercase Letters | Lowercase Letters | Letters | Numbers and Uppercase Letters | Numbers and Letters | Special Characters | Custom
  - `custom_characters` (text), default ""
  - `include_spaces` (bool), default true

### DL Classify
*Category:* Deep Learning. Gives the image (or a region of it) one label with a deep-learning classification model (ONNX), for example good / scratch / dent. Pass when the label is one of the 'OK labels' and the confidence is high enough.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Class` (STRING), `Class_Id` (VALUE), `Confidence` (VALUE), `Scores` (ANY), `Status` (STRING)
- Parameters:
  - `model_path` (path), default ""
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `device` (enum), default "cpu"; choices: cpu | cuda
  - `labels` (text), default ""
  - `input_width` (int), default 0; range 0 to 8192 px
  - `input_height` (int), default 0; range 0 to 8192 px
  - `resize` (enum), default "Auto"; choices: Auto | Stretch | Letterbox
  - `normalize` (enum), default "Auto"; choices: Auto | 0 to 1 | ImageNet (mean/std) | -1 to 1 | 0 to 255
  - `rgb_input` (bool), default true
  - `roi` (rect), default [0, 0, 0, 0]
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}
  - `top_k` (int), default 3; range 1 to 20
  - `ok_labels` (text), default ""
  - `min_confidence` (float), default 0.5; range 0 to 1

### DL Code Reading
*Category:* Recognition. Reads the bar codes and 2D codes (QR) in a region, as many as it can find: gives each code's text, type and outline. Tries both polarities and mirrored pictures when asked, stops after the time limit, and can grade each code's print contrast A to F.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Text` (STRING), `Codes` (ANY), `Count` (VALUE), `Texts` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `code_kind` (enum), default "1D and 2D"; choices: 1D and 2D | 1D only | 2D only
  - `polarity` (enum), default "Any"; choices: Any | Dark on White | White on Dark
  - `mirror` (enum), default "Any"; choices: Any | Not Mirrored | Mirrored
  - `time_limit_ms` (int), default 0; range 0 to 600000 ms
  - `max_codes` (int), default 20; range 1 to 200
  - `grade_enable` (bool), default false
  - `expected_text` (text), default ""

### DL Image Defect Prediction
*Category:* Deep Learning. Predicts where the defects are on a picture from a model trained on normal pictures only (ONNX): the answer is a probability map - a grey picture where 0 means no defect and brighter means more likely a defect. Threshold it and use BLOB Analysis, or read the highest probability.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Probability_Map` (IMAGE), `Max_Probability` (VALUE), `Defect_Count` (VALUE), `Boxes` (ANY)
- Parameters:
  - `model_file` (path), default ""
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}
  - `roi` (rect), default [0, 0, 0, 0]
  - `output_type` (enum), default "Probability map"; choices: Probability map | Reconstruction (autoencoder)
  - `probability_threshold` (float), default 0.5; range 0 to 1
  - `smoothing` (float), default 1.0; range 0 to 20
  - `min_area` (int), default 20; range 1 to 1e+06 px
  - `max_defects` (int), default 0; range 0 to 10000

### DL Image Retrieval
*Category:* Deep Learning. Searches a gallery of pictures for the categories most like a picture, using a deep-learning feature model (ONNX) to describe each picture. Register pictures into the gallery with the same model (one by one, or a whole folder), keep the gallery in a file, and search with the top-K and minimum similarity you want.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Class` (STRING), `Similarity` (VALUE), `Top` (ANY), `Categories` (ANY)
- Parameters:
  - `mode` (enum), default "Search"; choices: Search | Register Image | Register Folder | Delete Category | Clear Gallery
  - `roi` (rect), default [0, 0, 0, 0]
  - `category` (text), default ""
  - `register_folder` (dir), default ""
  - `gallery_file` (path), default ""
  - `top_k` (int), default 3; range 1 to 10
  - `min_similarity` (float), default 0.5; range 0 to 1
  - `gallery` (hidden), default {}
  - `model_file` (path), default ""
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}

### DL Instance Segment
*Category:* Deep Learning. Finds each object in the picture and outlines it with its own mask, using an instance segmentation model (ONNX, YOLO-seg style). Gives every object's box, class, score and mask; masks that overlap too much are dropped (the weaker one), and the result can be drawn in colour.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Boxes` (ANY), `Classes` (ANY), `Scores` (ANY), `Mask_Image` (IMAGE), `Masks` (ANY), `Detections` (ANY)
- Parameters:
  - `model_file` (path), default ""
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}
  - `labels` (text), default ""
  - `roi` (rect), default [0, 0, 0, 0]
  - `max_number` (int), default 20; range 1 to 1000
  - `min_confidence` (float), default 0.3; range 0 to 1
  - `overlap_threshold` (float), default 0.5; range 0 to 1
  - `mask_threshold` (float), default 0.5; range 0 to 1
  - `max_mask_overlap` (float), default 0.8; range 0 to 1
  - `edge_filter_enable` (bool), default false
  - `min_edge_score` (float), default 0.3; range 0 to 1
  - `render` (bool), default true

### DL Segment
*Category:* Deep Learning. Marks the defective pixels with a deep-learning segmentation model (ONNX, for example a U-Net). Reports the defect area, how many separate defects there are, and a box for each. Fails when there are too many or too much.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Mask` (IMAGE), `Defect_Area` (VALUE), `Defect_Ratio` (VALUE), `Defect_Count` (VALUE), `Boxes` (ANY), `Classes` (ANY), `Scores` (ANY), `Detections` (ANY), `Status` (STRING)
- Parameters:
  - `model_path` (path), default ""
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `device` (enum), default "cpu"; choices: cpu | cuda
  - `labels` (text), default ""
  - `input_width` (int), default 0; range 0 to 8192 px
  - `input_height` (int), default 0; range 0 to 8192 px
  - `resize` (enum), default "Auto"; choices: Auto | Stretch | Letterbox
  - `normalize` (enum), default "Auto"; choices: Auto | 0 to 1 | ImageNet (mean/std) | -1 to 1 | 0 to 255
  - `rgb_input` (bool), default true
  - `roi` (rect), default [0, 0, 0, 0]
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}
  - `defect_classes` (text), default ""
  - `background_class` (int), default 0; range 0 to 255
  - `threshold` (float), default 0.5; range 0 to 1
  - `min_area` (int), default 20; range 1 to 1e+08 px
  - `max_defect_count` (int), default 0; range 0 to 100000
  - `max_defect_ratio` (float), default 100.0; range 0 to 100 %

### DL Single Character Recognition
*Category:* Recognition. Finds each character and names it in one step - best for several lines of text or characters spread over a part. With a detection model (ONNX) each detection's class is the character; without one, the built-in reader is used. Characters come out in the order you choose.
- Inputs: `Image` (IMAGE), `Boxes` (ANY)
- Outputs: `Image` (IMAGE), `Text` (STRING), `Characters` (ANY), `Min_Score` (VALUE), `Count` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `model_file` (path), default ""
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}
  - `backend` (enum), default "Auto"; choices: Auto | ONNX Runtime | OpenCV DNN
  - `polarity` (enum), default "Auto"; choices: Auto | Dark on Light | Light on Dark
  - `max_number` (int), default 100; range 1 to 100
  - `min_confidence` (float), default 0.5; range 0 to 1
  - `overlap_threshold` (float), default 0.5; range 0 to 1
  - `sort_object` (enum), default "Center X"; choices: Center X | Center Y | Confidence
  - `edge_filter_enable` (bool), default false
  - `min_edge_score` (float), default 0.5; range 0 to 1
  - `width_enable` (bool), default false
  - `min_width` (int), default 5; range 1 to 10000 px
  - `max_width` (int), default 200; range 1 to 10000 px
  - `height_enable` (bool), default false
  - `min_height` (int), default 5; range 1 to 10000 px
  - `max_height` (int), default 200; range 1 to 10000 px
  - `min_area` (int), default 8; range 1 to 100000 px
  - `filter_enable` (bool), default false
  - `character_filter` (enum), default "All"; choices: All | Numbers | Uppercase Letters | Lowercase Letters | Letters | Numbers and Uppercase Letters | Numbers and Letters | Special Characters | Custom
  - `custom_characters` (text), default ""
  - `include_spaces` (bool), default true

### Data Log
*Category:* Communication. Appends one row per run to a CSV file (time plus the values you connect), ready for Excel.
- Inputs: `Data` (ANY), `Trigger` (BOOLEAN)
- Outputs: `Rows_Written` (VALUE), `File_Path` (STRING)
- Parameters:
  - `file_path` (path), default "./results/apex_log.csv"
  - `add_timestamp` (bool), default true

### Data Set
*Category:* Logic Tools. Collects the value made on each pass of a loop into one list. The clear signal decides what comes out: empty or none - the whole cycle, cleared when the next cycle starts; 0 - the whole cycle, never cleared; any other value - only the last pass.
- Inputs: `Value` (ANY), `Clear` (ANY), `Cycle` (VALUE)
- Outputs: `Data` (ANY), `Count` (VALUE), `Last` (ANY)
- Parameters:
  - `name` (text), default "data"
  - `value_type` (enum), default "Float"; choices: Int | Float | String

### Defect Contrast
*Category:* Defect Detection. Learns good and bad examples of a region and judges new ones: teach it up to 20 OK and 20 NG pictures of the region, then it scores how much a picture looks like the OK ones. A score under the threshold is NG. With OK examples only it scores the likeness to them.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Score` (VALUE), `Result` (VALUE), `OK_Samples` (VALUE), `NG_Samples` (VALUE)
- Parameters:
  - `mode` (enum), default "Detect"; choices: Detect | Learn OK | Learn NG | Clear Model
  - `roi` (rect), default [0, 0, 0, 0]
  - `score_threshold` (float), default 0.6; range 0 to 1
  - `samples` (json), default {"ok": [], "ng": []}

### Defect Detection
*Category:* Defect Detection. Finds defects such as scratches, burrs, dirt and cracks. Method 'Classical' compares each spot with its surroundings; 'Deep learning' uses your own ONNX model (segmentation, anomaly or detection) trained on your parts.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Max_Defect_Area` (VALUE), `Boxes` (ANY), `Classes` (ANY), `Scores` (ANY), `Detections` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `method` (enum), default "Classical (contrast)"; choices: Classical (contrast) | Deep learning (ONNX model)
  - `defect_type` (combo), default "Dark / Scratch"; choices: Dark / Scratch | Bright / Burr | Dirt / Stain | Crack / Break
  - `sensitivity` (int), default 35; range 1 to 255
  - `min_defect_area` (int), default 10; range 0 to 1e+07 px
  - `max_defect_area` (int), default 500; range 0 to 1e+07 px
  - `model_path` (path), default ""
  - `model_task` (enum), default "Segmentation"; choices: Segmentation | Anomaly | Detection
  - `dl_threshold` (float), default 0.0; range 0 to 1000

### Distortion Correction
*Category:* Image Processing. Corrects lens and perspective distortion with a calibration file (radial, perspective, or both).
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `calibration_file` (path), default ""
  - `refresh_signal` (int), default 0; range 0 to 1e+06
  - `correction_mode` (enum), default "Radial Distortion"; choices: Perspective Distortion | Radial Distortion | Radial Perspective Distortion

### Edge Detection
*Category:* Image Processing. Finds edges over the whole image with Canny, Sobel, Scharr or Laplacian. Output is a white-on-black edge map.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Edge_Pixels` (VALUE), `Edge_Ratio` (VALUE)
- Parameters:
  - `method` (enum), default "Canny"; choices: Canny | Sobel | Scharr | Laplacian
  - `low_threshold` (int), default 50; range 0 to 1000
  - `high_threshold` (int), default 150; range 0 to 1000
  - `blur_size` (int), default 3; range 1 to 31
  - `roi` (rect), default [0, 0, 0, 0]

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

### Edge Group Defect Detection
*Category:* Defect Detection. Runs several edge defect detections (Linear Edge and Arc Edge Defect Detection) on one picture and combines their defects. List each detection with its settings in items; the group is NG if any of them finds a defect.
- Inputs: `Image` (IMAGE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Defects` (ANY), `Defect_Boxes` (ANY), `Max_Depth` (VALUE), `Max_Size` (VALUE), `Max_Area` (VALUE), `Items_Failed` (VALUE)
- Parameters:
  - `items` (json), default [{"tool": "Linear Edge Defect Detection", "params": {"line1": [80, 150, 560, 150]}}, {"tool": "Linear Edge Defect Detection", "params": {"line1": [80, 330, 560, 330]}}]

### Edge Intersection
*Category:* Location. Finds the corner where two edges meet. Use one region (an edge in each of two directions) or two regions (one edge in each); the corner is where the two fitted lines cross, even if they do not quite touch.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Intersection_X` (VALUE), `Intersection_Y` (VALUE), `Line_0` (LINE), `Line_1` (LINE), `Line_0_Angle` (VALUE), `Line_1_Angle` (VALUE)
- Parameters:
  - `roi_count` (int), default 1; range 1 to 2
  - `roi1` (rect), default [0, 0, 0, 0]
  - `roi2` (rect), default [0, 0, 0, 0]
  - `direction1` (enum), default "Left to Right"; choices: Left to Right | Right to Left | Top to Bottom | Bottom to Top
  - `direction2` (enum), default "Top to Bottom"; choices: Left to Right | Right to Left | Top to Bottom | Bottom to Top
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_threshold` (int), default 20; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `caliper_number` (int), default 16; range 2 to 500
  - `projection_width` (int), default 5; range 1 to 500 px
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Edge Model Defect Detection
*Category:* Defect Detection. Compares an edge with a trained model of it. Train the model on a good part (the edge is found along the path you draw and remembered), then detect: an edge position that differs from the model by more than the location deviation, a missing stretch (fracture), and a sawtooth of steps (hierarchical) are defects.
- Inputs: `Image` (IMAGE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Status_Code` (VALUE), `Trained` (VALUE), `Defect_Count` (VALUE), `Defects` (ANY), `Defect_Boxes` (ANY), `Max_Depth` (VALUE), `Max_Size` (VALUE), `Max_Area` (VALUE)
- Parameters:
  - `mode` (enum), default "Detect"; choices: Detect | Train Model | Clear Model
  - `path_points` (points), default [[80, 200], [560, 200]]
  - `reference_point` (point), default [0, 0]
  - `model` (hidden), default {}
  - `model_file` (path), default ""
  - `roi_mode` (enum), default "Draw"; choices: Draw | Inherit
  - `filter_size` (int), default 3; range 1 to 50
  - `contrast_threshold` (int), default 20; range 0 to 255
  - `caliper_height` (int), default 5; range 1 to 500 px
  - `caliper_length` (int), default 40; range 4 to 4000 px
  - `caliper_spacing` (int), default 5; range 1 to 1000 px
  - `location_deviation` (float), default 3.0; range 0 to 1000 px
  - `fracture_enable` (bool), default true
  - `hierarchical_enable` (bool), default true
  - `hierarchical_height` (float), default 2.0; range 0 to 1000 px
  - `hierarchical_min_length` (int), default 3; range 2 to 1000
  - `gray_assist` (bool), default false
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Both"; choices: Both | Dark to Light | Light to Dark

### Edge Pair Group Defect Detection
*Category:* Defect Detection. Runs several edge-pair defect detections (Line-Pair and Arc-Pair Defect Detection) on one picture and combines their defects. List each detection with its settings in items; the group is NG if any of them finds a defect.
- Inputs: `Image` (IMAGE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Defects` (ANY), `Defect_Boxes` (ANY), `Max_Depth` (VALUE), `Max_Size` (VALUE), `Max_Area` (VALUE), `Items_Failed` (VALUE)
- Parameters:
  - `items` (json), default [{"tool": "Line-Pair Defect Detection", "params": {"line1": [80, 200, 560, 200]}}]

### Edge Pair Model Defect Detection
*Category:* Defect Detection. Compares an edge pair (a strip) with a trained model: both edges are checked as in Edge Model Defect Detection, and bubble defects are found where the gray level between the edges differs from the model's or changes abruptly.
- Inputs: `Image` (IMAGE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Status_Code` (VALUE), `Trained` (VALUE), `Defect_Count` (VALUE), `Defects` (ANY), `Defect_Boxes` (ANY), `Max_Depth` (VALUE), `Max_Size` (VALUE), `Max_Area` (VALUE)
- Parameters:
  - `mode` (enum), default "Detect"; choices: Detect | Train Model | Clear Model
  - `path_points` (points), default [[80, 200], [560, 200]]
  - `reference_point` (point), default [0, 0]
  - `model` (hidden), default {}
  - `model_file` (path), default ""
  - `roi_mode` (enum), default "Draw"; choices: Draw | Inherit
  - `filter_size` (int), default 3; range 1 to 50
  - `contrast_threshold` (int), default 20; range 0 to 255
  - `caliper_height` (int), default 5; range 1 to 500 px
  - `caliper_length` (int), default 40; range 4 to 4000 px
  - `caliper_spacing` (int), default 5; range 1 to 1000 px
  - `location_deviation` (float), default 3.0; range 0 to 1000 px
  - `fracture_enable` (bool), default true
  - `hierarchical_enable` (bool), default true
  - `hierarchical_height` (float), default 2.0; range 0 to 1000 px
  - `hierarchical_min_length` (int), default 3; range 2 to 1000
  - `gray_assist` (bool), default false
  - `edge_search_type` (enum), default "Widest Edge Pair"; choices: Widest Edge Pair | Nearest Edge Pair | Strongest & Nearest Edge Pair
  - `edge0_polarity` (enum), default "Dark to Light"; choices: Both | Dark to Light | Light to Dark
  - `edge1_polarity` (enum), default "Light to Dark"; choices: Both | Dark to Light | Light to Dark
  - `ideal_width` (float), default 20.0; range 0 to 100000 px
  - `bubble_enable` (bool), default true
  - `grayscale_acceptance` (float), default 30.0; range 0 to 255
  - `grayscale_change` (float), default 25.0; range 0 to 255
  - `bubble_length` (int), default 2; range 1 to 1000
  - `max_mutations` (int), default 2; range 0 to 1000

### Edge Pair Trend Analysis
*Category:* Defect Detection. Studies a strip across a region: a row of calipers finds one edge pair each and measures its width. Pairs whose width fits the thresholds are kept, and the widest, narrowest and mean widths and their pairs are reported.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Max_Distance` (VALUE), `Min_Distance` (VALUE), `Mean_Distance` (VALUE), `Max_Point` (POINT), `Min_Point` (POINT), `Points` (ANY), `Distances` (ANY), `Found` (VALUE), `Pairs` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `search_direction` (enum), default "Top to Bottom"; choices: Top to Bottom | Left to Right
  - `caliper_number` (int), default 20; range 2 to 500
  - `caliper_width` (int), default 5; range 1 to 500 px
  - `filter_size` (int), default 3; range 1 to 50
  - `edge_threshold` (int), default 20; range 0 to 255
  - `distance_low` (float), default 0.0; range 0 to 1e+06 px
  - `distance_high` (float), default 1000.0; range 0 to 1e+06 px
  - `high_threshold_enable` (bool), default false
  - `edge_type` (enum), default "Widest Edge Pair"; choices: Widest Edge Pair | Narrowest Edge Pair | Strongest Edge Pair | Weakest Edge Pair | First Edge Pair | Last Edge Pair | Nearest Edge Pair | Farthest Edge Pair
  - `edge0_polarity` (enum), default "Dark to Light"; choices: Both | Dark to Light | Light to Dark
  - `edge1_polarity` (enum), default "Light to Dark"; choices: Both | Dark to Light | Light to Dark
  - `ideal_width` (float), default 20.0; range 0 to 100000 px

### Edge Position Trend Analysis
*Category:* Defect Detection. Studies how an edge sits across a region: a row of calipers finds one edge point each, and the distance of every point from the region's start side (top or left) is measured. Points whose distance fits the thresholds are kept, and the largest, smallest and mean distances and their points are reported.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Max_Distance` (VALUE), `Min_Distance` (VALUE), `Mean_Distance` (VALUE), `Max_Point` (POINT), `Min_Point` (POINT), `Points` (ANY), `Distances` (ANY), `Found` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `search_direction` (enum), default "Top to Bottom"; choices: Top to Bottom | Left to Right
  - `caliper_number` (int), default 20; range 2 to 500
  - `caliper_width` (int), default 5; range 1 to 500 px
  - `filter_size` (int), default 3; range 1 to 50
  - `edge_threshold` (int), default 20; range 0 to 255
  - `distance_low` (float), default 0.0; range 0 to 1e+06 px
  - `distance_high` (float), default 1000.0; range 0 to 1e+06 px
  - `high_threshold_enable` (bool), default false
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Both"; choices: Both | Dark to Light | Light to Dark

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

### Ellipse Search
*Category:* Location. Finds one ellipse: calipers run from an inner to an outer ellipse (both scaled from the region you draw) and the edge points are fitted to an ellipse. Gives its centre, the two axis lengths and its angle.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Center_X` (VALUE), `Center_Y` (VALUE), `Axis_A` (VALUE), `Axis_B` (VALUE), `Angle_Deg` (VALUE), `Ellipse` (DICT)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `inner_scale` (float), default 0.5; range 0.05 to 1
  - `outer_scale` (float), default 1.1; range 0.2 to 3
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_threshold` (int), default 20; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `caliper_number` (int), default 36; range 2 to 500
  - `projection_width` (int), default 5; range 1 to 500 px
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 6.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Find Angle Bisector
*Category:* Location. The line that splits the angle between two lines in half. It passes through the point where the lines cross and points between them; the other bisector (at a right angle to it) is given as well.
- Inputs: `Line1` (LINE), `Line2` (LINE), `Point1_Start` (POINT), `Point1_End` (POINT), `Point2_Start` (POINT), `Point2_End` (POINT)
- Outputs: `Bisector` (LINE), `Bisector_2` (LINE), `Intersection` (POINT), `Angle_Deg` (VALUE), `Bisector_Angle` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Line | By Point | By Coordinate
  - `line1` (line), default [100, 200, 300, 160]
  - `line2` (line), default [100, 100, 300, 160]

### Find Median Line
*Category:* Location. Joins the middle of the two lines' start points to the middle of their end points: the line half-way between two lines.
- Inputs: `Line1` (LINE), `Line2` (LINE), `Point1_Start` (POINT), `Point1_End` (POINT), `Point2_Start` (POINT), `Point2_End` (POINT)
- Outputs: `Median_Line` (LINE), `Start_Midpoint` (POINT), `End_Midpoint` (POINT), `Angle_Deg` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Line | By Point | By Coordinate
  - `line1` (line), default [100, 200, 300, 160]
  - `line2` (line), default [100, 100, 300, 160]

### Find Vertical Line
*Category:* Location. Makes a line at a right angle to another: through a given point (and where it meets the line), or the perpendicular bisector that stands in the middle of the line segment.
- Inputs: `Line1` (LINE), `Point1_Start` (POINT), `Point1_End` (POINT), `Point` (POINT)
- Outputs: `Vertical_Line` (LINE), `Foot` (POINT), `Distance` (VALUE)
- Parameters:
  - `method` (enum), default "Point Perpendicular"; choices: Point Perpendicular | Perpendicular Bisector
  - `input_mode` (enum), default "By Coordinate"; choices: By Line | By Point | By Coordinate
  - `line1` (line), default [100, 200, 300, 160]
  - `point` (point), default [200, 120]

### Focus Measure
*Category:* Measurement. Measures how sharp (in focus) the image or a region is. Higher is sharper. Fails below a minimum.
- Inputs: `Image` (IMAGE)
- Outputs: `Sharpness` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `min_sharpness` (float), default 0.0; range 0 to 1e+09
  - `assess_mode` (enum), default "Laplacian Variance"; choices: Laplacian Variance | Auto Correlation | Gradient Squared
  - `noise_level` (int), default 0; range 0 to 255

### Format Module
*Category:* Logic Tools. Builds one line of text from your own wording and the results of other modules, ready to send to a PLC or robot. Write the text and put {Data1} to {Data8} where the values go ({Data1:.2f} sets the decimals); lists are joined with the split symbol.
- Inputs: `Data1` (ANY), `Data2` (ANY), `Data3` (ANY), `Data4` (ANY), `Data5` (ANY), `Data6` (ANY), `Data7` (ANY), `Data8` (ANY)
- Outputs: `Text` (STRING), `Length` (VALUE)
- Parameters:
  - `format` (text), default "{Data1},{Data2}"
  - `split_symbol` (text), default ","
  - `array_delimiter` (text), default ";"
  - `end_char` (text), default "\\r\\n"
  - `decimals` (int), default -1; range -1 to 12

### Frame Mean
*Category:* Image Processing. Averages the same region over many pictures (up to 100) to cut noise. Each run adds one picture; 'Ignore' skips it and 'Clear' starts over.
- Inputs: `Image` (IMAGE), `Ignore` (BOOLEAN), `Clear` (BOOLEAN)
- Outputs: `Image` (IMAGE), `Count` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `max_frames` (int), default 10; range 1 to 100

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

### Graphic Collection
*Category:* Logic Tools. Draws results from several modules on one picture: points, lines, rectangles, ring sectors and text. Drawn in the OK colour when the status is OK and the NG colour otherwise; the transparency fills rectangles with a see-through tint.
- Inputs: `Image` (IMAGE), `Points` (ANY), `Lines` (ANY), `Rects` (ANY), `Sectors` (ANY), `Text` (STRING), `Status` (ANY)
- Outputs: `Image` (IMAGE), `Count` (VALUE)
- Parameters:
  - `ok_color` (enum), default "Green"; choices: Green | Red | Yellow | Blue | White | Cyan | Magenta | Orange
  - `ng_color` (enum), default "Red"; choices: Green | Red | Yellow | Blue | White | Cyan | Magenta | Orange
  - `transparency` (int), default 0; range 0 to 100 %
  - `text_x` (int), default 10; range 0 to 100000
  - `text_y` (int), default 30; range 0 to 100000

### Group
*Category:* Logic Tools. Keeps modules together so a busy flow stays readable, and repeats them in a loop when asked. Put modules inside with right-click, Add to group. With the loop on they run once for every number from the start value up to (not including) the end value; the loop number is on the Cycle output. A break condition stops the loop early when Base compares to Target as chosen.
- Inputs: `Base` (ANY), `Target` (ANY)
- Outputs: `Cycle` (VALUE), `Loops` (VALUE), `Broke` (VALUE)
- Parameters:
  - `loop_enable` (bool), default false
  - `loop_start` (int), default 0; range -1e+06 to 1e+06
  - `loop_end` (int), default 3; range -1e+06 to 1e+06
  - `interval_ms` (int), default 0; range 0 to 3.6e+06 ms
  - `break_enable` (bool), default false
  - `compare_type` (enum), default "Int"; choices: Int | Float | String
  - `break_when` (enum), default "=="; choices: == | != | > | >= | < | <=
  - `base_value` (text), default "0"
  - `target_value` (text), default "0"

### Histogram
*Category:* Measurement. Statistical analysis of grayscale distribution (Mean, Median, Peak, StdDev, Contrast, Min, Max).
- Inputs: `Image` (IMAGE)
- Outputs: `Mean` (VALUE), `Median` (VALUE), `Peak` (VALUE), `StdDev` (VALUE), `Contrast` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]

### Hough Detect
*Category:* Location. Finds circles or straight line segments in a region of the image. Use it when you do not know where the feature is. The strongest circle / longest line is passed on as 'Circle' / 'Line'.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Circle` (CIRCLE), `Line` (LINE), `Items` (ANY)
- Parameters:
  - `mode` (enum), default "Circles"; choices: Circles | Lines
  - `roi` (rect), default [0, 0, 0, 0]
  - `min_radius` (int), default 10; range 0 to 5000 px
  - `max_radius` (int), default 200; range 1 to 5000 px
  - `min_distance` (int), default 20; range 1 to 5000 px
  - `sensitivity` (int), default 30; range 1 to 200
  - `line_threshold` (int), default 50; range 1 to 1000
  - `min_line_length` (int), default 40; range 1 to 10000 px
  - `max_line_gap` (int), default 10; range 0 to 1000 px
  - `min_count` (int), default 1; range 0 to 1000

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
  - `method` (enum), default "Otsu"; choices: Otsu | Adaptive | Manual | Hard Threshold | Mean | Gaussian | Auto
  - `threshold` (int), default 128; range 0 to 255
  - `invert` (bool), default false
  - `adaptive_block_size` (int), default 11; range 3 to 99
  - `adaptive_c` (int), default 2; range -50 to 50
  - `low_threshold` (int), default 100; range 0 to 255
  - `high_threshold` (int), default 255; range 0 to 255
  - `kernel_width` (int), default 15; range 1 to 255 px
  - `kernel_height` (int), default 15; range 1 to 255 px
  - `gaussian_sigma` (float), default 0.0; range 0 to 100
  - `comparison` (enum), default "Greater or Equal"; choices: Greater or Equal | Less or Equal | Equal | Not Equal
  - `threshold_offset` (float), default 0.0; range -255 to 255
  - `roi` (rect), default [0, 0, 0, 0]

### Image Buffer
*Category:* Acquisition. Circular FIFO image buffer for defect review and solution traceability.
- Inputs: `Image` (IMAGE)
- Outputs: `Buffer_Count` (VALUE), `Latest_Image` (IMAGE)
- Parameters:
  - `buffer_capacity` (int), default 30; range 1 to 1000
  - `buffer_condition` (enum), default "All Images"; choices: All Images | NG Only

### Image Calculate
*Category:* Image Processing. Combines two images pixel by pixel: add, subtract, absolute difference (compare with a good sample), multiply, average, AND / OR / XOR, brightest or darkest of the two.
- Inputs: `Image` (IMAGE), `Image_B` (IMAGE)
- Outputs: `Image` (IMAGE), `Mean` (VALUE)
- Parameters:
  - `operation` (enum), default "Absolute Difference"; choices: Absolute Difference | Subtract (A - B) | Add | Multiply | Average | Maximum | Minimum | Bitwise AND | Bitwise OR | Bitwise XOR | k1*A + k2*B + c | k1*A + c | A + c
  - `image_weight1` (float), default 1.0; range 0 to 10
  - `image_weight2` (float), default 1.0; range 0 to 10
  - `calc_weight1` (float), default 1.0; range -10 to 10
  - `calc_weight2` (float), default 1.0; range -10 to 10
  - `image_offset` (float), default 0.0; range -255 to 255

### Image Combination
*Category:* Image Processing. Runs several image processing steps in one module: morphology, binarization, filter, enhancement and shade correction. Switch each step on or off and set the order.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `order` (text), default "Morphology,Binarization,Filter,Enhancement,Shade Correction"
  - `enable_morphology` (bool), default false
  - `morph_type` (enum), default "Opening"; choices: Dilation | Erosion | Opening | Closing
  - `morph_element` (enum), default "Rect"; choices: Rect | Ellipse | Cross
  - `morph_width` (int), default 3; range 1 to 255
  - `morph_height` (int), default 3; range 1 to 255
  - `morph_iterations` (int), default 1; range 1 to 50
  - `enable_binarization` (bool), default false
  - `bin_type` (enum), default "Auto"; choices: Hard Threshold | Mean | Gaussian | Auto
  - `bin_low` (int), default 100; range 0 to 255
  - `bin_high` (int), default 255; range 0 to 255
  - `enable_filter` (bool), default false
  - `filter_type` (enum), default "Gaussian"; choices: Gaussian | Median | Mean | Inverse | Edge Extraction
  - `filter_kernel` (int), default 5; range 1 to 99
  - `enable_enhancement` (bool), default false
  - `enh_contrast` (int), default 100; range 0 to 1000
  - `enh_gamma` (float), default 1.0; range 0.05 to 8
  - `enh_gain` (int), default 0; range 0 to 100
  - `enh_offset` (int), default 0; range -255 to 255
  - `enh_sharpen` (float), default 0.0; range 0 to 20
  - `enable_shade` (bool), default false
  - `shade_kernel` (int), default 15; range 1 to 50
  - `shade_gain` (float), default 10.0; range 0 to 100
  - `shade_compensation` (int), default 128; range 0 to 255

### Image Correction
*Category:* Image Processing. Straightens barrel (bulging) or pincushion (pinched) lens distortion. A positive expansion corrects barrel distortion, a negative one corrects pincushion; the scaling amount zooms the result.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `expansion_amount` (float), default 10.0; range -100 to 100
  - `scaling_amount` (float), default 0.0; range -90 to 500 %
  - `roi` (rect), default [0, 0, 0, 0]

### Image Crop
*Category:* Image Processing. Cuts a rectangular region out of the image. Draw the region on the image or type X, Y, W, H.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Width` (VALUE), `Height` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]

### Image Division Tool
*Category:* Division and Combination. Cuts the region of interest into a grid of equal pieces (with an overlap if you like) so each piece can be processed on its own, for example by Copy Fill or Group. Gives the pieces' boxes and their pictures.
- Inputs: `Image` (IMAGE)
- Outputs: `Boxes` (ANY), `Count` (VALUE), `Images` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `divisions_x` (int), default 2; range 1 to 50
  - `divisions_y` (int), default 2; range 1 to 50
  - `overlap_x` (float), default 10.0; range 0 to 90 %
  - `overlap_y` (float), default 10.0; range 0 to 90 %

### Image Enhancement
*Category:* Image Processing. Sharpens, adjusts contrast and gamma, and corrects brightness: sharpening (intensity and kernel size), a contrast coefficient (100 = no change), gamma (1 = no change; under 1 brightens the dark parts, over 1 darkens them) and brightness as offset + pixel * gain. All the steps are applied in that order, and each is skipped at its neutral setting.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `sharpen_intensity` (float), default 0.0; range 0 to 20
  - `sharpen_kernel` (int), default 5; range 1 to 51
  - `contrast` (float), default 100.0; range 0 to 1000
  - `gamma` (float), default 1.0; range 0.05 to 4
  - `gain` (float), default 0.0; range 0 to 100
  - `compensation` (float), default 0.0; range -255 to 255
  - `roi` (rect), default [0, 0, 0, 0]

### Image Filter
*Category:* Image Processing. Spatial filtering: Gaussian, Box and Median blur, Bilateral, Sharpen, or Unsharp Mask.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `filter_type` (enum), default "Gaussian"; choices: Gaussian | Box | Median | Sharpen | Unsharp Mask | Bilateral | Mean | Inverse | Edge Extraction
  - `kernel_size` (int), default 5; range 1 to 31
  - `sigma` (float), default 1.5; range 0 to 50
  - `edge_low` (int), default 40; range 0 to 2000
  - `edge_high` (int), default 120; range 0 to 2000
  - `roi` (rect), default [0, 0, 0, 0]

### Image Fixture
*Category:* Image Processing. Moves and turns the picture so a part that shifted in the field of view lands on the reference position again. Use the correction from Position Correction ('By Info'), two points and angles ('By Point'), or typed coordinates ('By Coordinate').
- Inputs: `Image` (IMAGE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Ref_Point` (POINT), `Run_Point` (POINT), `Ref_Angle` (VALUE), `Run_Angle` (VALUE)
- Outputs: `Image` (IMAGE), `Matrix` (ANY)
- Parameters:
  - `mode` (enum), default "By Info"; choices: By Info | By Point | By Coordinate
  - `ref_point` (point), default [320, 240]
  - `run_point` (point), default [320, 240]
  - `ref_angle` (float), default 0.0; range -360 to 360 deg
  - `run_angle` (float), default 0.0; range -360 to 360 deg
  - `fill_value` (int), default 0; range 0 to 255

### Image Morphology
*Category:* Image Processing. Morphological operations: Dilate, Erode, Open, Close, Gradient, Top Hat, Black Hat.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `operation` (enum), default "Open"; choices: Open | Close | Dilate | Erode | Gradient | Top Hat | Black Hat | Dilation | Erosion | Opening | Closing
  - `kernel_size` (int), default 3; range 1 to 51
  - `iterations` (int), default 1; range 1 to 50
  - `element` (enum), default "Rect"; choices: Rect | Ellipse | Cross
  - `element_width` (int), default 0; range 0 to 255 px
  - `element_height` (int), default 0; range 0 to 255 px
  - `roi` (rect), default [0, 0, 0, 0]

### Image Normalization
*Category:* Image Processing. Re-maps grey levels: histogram equalization, histogram normalization (stretch between chosen levels after trimming the ends), or standard deviation normalization (a target average and spread).
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `normalization_type` (enum), default "Histogram Equalization"; choices: Histogram Equalization | Histogram Normalization | Standard Deviation Normalization
  - `left_ratio` (float), default 1.0; range 0 to 49 %
  - `right_ratio` (float), default 1.0; range 0 to 49 %
  - `min_gray` (int), default 0; range 0 to 254
  - `max_gray` (int), default 255; range 1 to 255
  - `target_mean` (int), default 128; range 0 to 255
  - `target_std` (float), default 40.0; range 0.1 to 128
  - `roi` (rect), default [0, 0, 0, 0]

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
  - `source_type` (enum), default "Synthetic"; choices: Synthetic | File | Camera | Industrial GigE | Industrial USB3 | Hikrobot MVS | IP Stream
  - `file_path` (path), default "<app>/apex_vision/samples/pcb_sample.png"
  - `pattern_type` (enum), default "Part with Defects"; choices: Part with Defects | Metal Surface (demo) | Calibration Grid | Circles & Holes | Barcode Sample
  - `color_mode` (enum), default "BGR"; choices: BGR | Grayscale
  - `camera_device` (device), default "mvs_gige_0"
  - `camera_index` (int), default 0; range 0 to 16
  - `auto_exposure` (bool), default true
  - `exposure_time_us` (float), default 20000.0; range 10 to 1e+07 us
  - `gain` (float), default 1.0; range 0 to 48 x
  - `trigger_mode` (enum), default "Continuous"; choices: Continuous | Software Trigger | Hardware Trigger (Line0) | Hardware Trigger (Line1)
  - `mvs_config_file` (path), default ""
  - `mvs_trigger_source` (enum), default "Software"; choices: Software | Line0 | Line1
  - `stream_url` (text), default "rtsp://192.168.1.64:554/ch1/main"

### Image Stitch
*Category:* Image Processing. Joins several pictures into one. Hard stitch lays them side by side in a grid; model stitch finds where they overlap and blends them (mean, min, max or uncover). One camera moved several times, or several cameras at once.
- Inputs: `Image_0` (IMAGE), `Image_1` (IMAGE), `Image_2` (IMAGE), `Image_3` (IMAGE), `Image_4` (IMAGE), `Image_5` (IMAGE), `Image_6` (IMAGE), `Image_7` (IMAGE), `Image_8` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE)
- Parameters:
  - `input_mode` (enum), default "Multiple Source"; choices: Multiple Source | Single Source
  - `stitch_type` (enum), default "Hard Stitch"; choices: Hard Stitch | Model Stitch
  - `stitch_number` (int), default 2; range 2 to 9
  - `rows` (int), default 1; range 1 to 9
  - `columns` (int), default 2; range 1 to 9
  - `stitch_direction` (enum), default "X"; choices: X | Y
  - `merge_type` (enum), default "Merge Mean"; choices: Merge Mean | Merge Min | Merge Max | Merge Uncover
  - `cut_ratio` (int), default 0; range 0 to 25 %
  - `auto_clear` (bool), default true
  - `auto_fill` (bool), default false

### Image Transform
*Category:* Image Processing. Resize, rotate by any angle, rotate by 90 degrees or flip the image.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Width` (VALUE), `Height` (VALUE)
- Parameters:
  - `operation` (enum), default "Resize"; choices: Resize | Rotate | Rotate 90 CW | Rotate 90 CCW | Rotate 180 | Flip Horizontal | Flip Vertical | Mirror and Rotate
  - `scale` (float), default 0.5; range 0.05 to 16 x
  - `angle` (float), default 15.0; range -360 to 360 deg
  - `expand` (bool), default true
  - `mirror` (enum), default "Horizontal"; choices: None | Horizontal | Vertical | Diagonal

### Intensity Measure
*Category:* Measurement. Measures mean, min, max, and std deviation of gray intensity inside ROI.
- Inputs: `Image` (IMAGE)
- Outputs: `Mean` (VALUE), `StdDev` (VALUE), `Min` (VALUE), `Max` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `min_mean` (float), default 20.0; range 0 to 255
  - `max_mean` (float), default 240.0; range 0 to 255

### Inverse Affine Transformation
*Category:* Image Processing. Puts a picture back into a (turned) region of a base picture: the picture is scaled to the region and turned to its angle. Use it after Affine Transformation to show the result at the original place.
- Inputs: `Image` (IMAGE), `Base_Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `roi_angle` (float), default 0.0; range -360 to 360 deg
  - `base_width` (int), default 640; range 1 to 16384 px
  - `base_height` (int), default 480; range 1 to 16384 px
  - `base_fill` (int), default 0; range 0 to 255

### L2C Measure
*Category:* Measurement. Measures between a line and a circle: the distance from the circle's centre to the line and from the line to the circle's edge, the angle of the connection between the centre and the line, the closest point on the circle, the foot of the centre on the line, and where the line cuts the circle (if it does). The line comes from a Line Search, two points or typed coordinates; the circle from a Circle Search or typed values.
- Inputs: `Line` (LINE), `Circle` (CIRCLE), `Point1_Start` (POINT), `Point1_End` (POINT)
- Outputs: `Distance` (VALUE), `Center_Distance` (VALUE), `Abs_Distance` (VALUE), `Angle_Deg` (VALUE), `Nearest_Point` (POINT), `Foot` (POINT), `Cross_Points` (ANY), `Cross_Count` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Line | By Point | By Coordinate
  - `line1` (line), default [100, 100, 500, 120]
  - `circle_x` (float), default 300.0; range -1e+06 to 1e+06 px
  - `circle_y` (float), default 200.0; range -1e+06 to 1e+06 px
  - `circle_r` (float), default 60.0; range 0.01 to 1e+06 px
  - `angle_range` (enum), default "-180 to 180"; choices: -180 to 180 | -90 to 90
  - `scale_factor` (float), default 1.0; range 1e-06 to 1e+06

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

### Light Source
*Category:* Acquisition. Sets the brightness of a light source controller's channels: it builds one command per channel from your command template and sends it (over a serial port or the network, or only logs it in simulation), optionally strobing for a trigger time and then switching the channels off.
- Inputs: `Brightness` (ANY)
- Outputs: `Sent` (VALUE), `Commands` (ANY), `Levels` (ANY)
- Parameters:
  - `device` (enum), default "Simulation (Log Only)"; choices: Simulation (Log Only) | Serial Port | TCP Network
  - `port_name` (text), default "COM1"
  - `baud_rate` (int), default 9600; range 300 to 4e+06
  - `host` (text), default "192.168.0.100"
  - `tcp_port` (int), default 4001; range 1 to 65535
  - `channels` (text), default "1,2"
  - `brightness` (text), default "128,128"
  - `command_template` (text), default "SA{channel}{brightness:04d}#"
  - `trigger_time_ms` (int), default 0; range 0 to 60000 ms
  - `off_after_trigger` (bool), default false
  - `off_command_template` (text), default "SA{channel}0000#"

### Line Alignment
*Category:* Calculation. Works out the move that brings a set of object lines onto the matching target lines (in the same order): the turn from the lines' directions and the shift that puts each object line on its target. For a closed outline the lines may start at any of its sides. Use physical coordinates.
- Inputs: `Target_Lines` (ANY), `Object_Lines` (ANY)
- Outputs: `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Move` (ANY), `Error` (VALUE), `Center` (POINT), `Shift` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `alignment_shape` (enum), default "Open"; choices: Open | Closed
  - `target_lines` (json), default [[100, 100, 300, 100], [300, 100, 300, 250]]
  - `object_lines` (json), default [[102, 104, 302, 107], [301, 105, 298, 255]]

### Line Group Search
*Category:* Location. Fits one line through edge points taken from several separate stretches: list the segments where the edge should be; each is searched a band either side, and all points found are combined into a single line.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Line` (LINE), `Angle_Deg` (VALUE), `Point_Count` (VALUE), `Segment_Counts` (ANY)
- Parameters:
  - `segments` (json), default [[100, 150, 220, 152], [300, 154, 420, 156]]
  - `search_band` (float), default 15.0; range 2 to 1000 px
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_threshold` (int), default 20; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `caliper_number` (int), default 10; range 2 to 500
  - `projection_width` (int), default 5; range 1 to 500 px
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Line Intersection
*Category:* Measurement. The point where two lines cross (extended to infinity), and the angle between them. Parallel lines fail.
- Inputs: `Line1` (LINE), `Line2` (LINE)
- Outputs: `Point` (POINT), `X` (VALUE), `Y` (VALUE), `Angle_Deg` (VALUE)
- Parameters:
  - `default_l1` (line), default [100, 100, 400, 100]
  - `default_l2` (line), default [250, 50, 250, 300]

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

### Line-Pair Defect Detection
*Category:* Defect Detection. Checks the strip between two straight edges (a rim, a gap, a bar): at each position a pair of edges is found and its width measured; where the width is outside the eligible range (too narrow or too wide) or no pair is found, that stretch is a defect.
- Inputs: `Image` (IMAGE), `Line1` (LINE), `Point1_Start` (POINT), `Point1_End` (POINT), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Defects` (ANY), `Defect_Boxes` (ANY), `Max_Depth` (VALUE), `Max_Size` (VALUE), `Max_Area` (VALUE), `Widths` (ANY), `Pair_Count` (VALUE), `Min_Width` (VALUE), `Max_Width` (VALUE), `Mean_Width` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Line | By Point | By Coordinate
  - `line1` (line), default [80, 200, 560, 200]
  - `roi_mode` (enum), default "Draw"; choices: Draw | Inherit
  - `edge_search_type` (enum), default "Widest Edge Pair"; choices: Widest Edge Pair | Nearest Edge Pair | Strongest & Nearest Edge Pair
  - `edge0_polarity` (enum), default "Dark to Light"; choices: Both | Dark to Light | Light to Dark
  - `edge1_polarity` (enum), default "Light to Dark"; choices: Both | Dark to Light | Light to Dark
  - `filter_size` (int), default 3; range 1 to 50
  - `contrast_threshold` (int), default 20; range 0 to 255
  - `ideal_width` (float), default 20.0; range 0 to 100000 px
  - `caliper_height` (int), default 5; range 1 to 500 px
  - `caliper_length` (int), default 60; range 4 to 4000 px
  - `caliper_spacing` (int), default 5; range 1 to 1000 px
  - `width_min` (float), default 15.0; range 0 to 100000 px
  - `width_max` (float), default 25.0; range 0 to 100000 px
  - `size_enable` (bool), default false
  - `rough_min_size` (float), default 5.0; range 0 to 100000 px
  - `area_enable` (bool), default false
  - `rough_min_area` (float), default 10.0; range 0 to 1e+09 px2
  - `fracture_enable` (bool), default true
  - `track_tolerance` (float), default 0.0; range 0 to 10000 px

### Linear Edge Defect Detection
*Category:* Defect Detection. Checks a straight edge for bumps, notches and breaks: a row of calipers finds the edge along the line, the best-fit line is drawn through it, and every stretch that strays further than the minimum distance (on the side you choose) or has no edge is a defect, with its size, depth and box.
- Inputs: `Image` (IMAGE), `Line1` (LINE), `Point1_Start` (POINT), `Point1_End` (POINT), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Defects` (ANY), `Defect_Boxes` (ANY), `Max_Depth` (VALUE), `Max_Size` (VALUE), `Max_Area` (VALUE), `Edge_Points` (ANY), `Edge_Count` (VALUE), `Fit_Residual` (VALUE), `Fit_Line` (LINE), `Fit_Circle` (CIRCLE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Line | By Point | By Coordinate
  - `line1` (line), default [80, 200, 560, 200]
  - `roi_mode` (enum), default "Draw"; choices: Draw | Inherit
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Both"; choices: Both | Dark to Light | Light to Dark
  - `filter_size` (int), default 3; range 1 to 50
  - `contrast_threshold` (int), default 20; range 0 to 255
  - `caliper_height` (int), default 5; range 1 to 500 px
  - `caliper_length` (int), default 30; range 4 to 2000 px
  - `caliper_spacing` (int), default 5; range 1 to 1000 px
  - `defect_polarity` (enum), default "Both Defects"; choices: Both Defects | Left Defect | Right Defect
  - `rough_min_distance` (float), default 3.0; range 0 to 1000 px
  - `size_enable` (bool), default false
  - `rough_min_size` (float), default 5.0; range 0 to 100000 px
  - `area_enable` (bool), default false
  - `rough_min_area` (float), default 10.0; range 0 to 1e+09 px2
  - `fracture_enable` (bool), default true
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Load Calibration
*Category:* Calibration. Loads a calibration file written by the calibration modules and passes its calibration and numbers on. The file is read again when the refresh signal is not 0 and the file has changed; an empty or 0 signal keeps the first one read.
- Inputs: `Refresh` (VALUE)
- Outputs: `Status` (VALUE), `Kind` (VALUE), `Calibration_Error` (VALUE), `Rotation_Center_Image` (VALUE), `Rotation_Center_Physical` (VALUE), `Calibration` (DICT), `Matrix` (ANY), `Scale` (VALUE), `Pixel_Accuracy` (VALUE), `Translation_X` (VALUE), `Translation_Y` (VALUE), `Rotation` (VALUE), `Skew` (VALUE), `Aspect_Ratio` (VALUE)
- Parameters:
  - `calibration_file` (path), default ""

### ML Classification
*Category:* Recognition. Sorts pictures into classes you teach it, by classical machine learning (not a neural network): teach it samples of each class, then it names the class of a new picture from its nearest samples (shape and colour features). Best when you have few pictures; with many, use DL Classify.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Class` (STRING), `Score` (VALUE), `Scores` (ANY), `Top` (ANY), `Samples` (ANY)
- Parameters:
  - `mode` (enum), default "Classify"; choices: Classify | Learn | Clear Samples
  - `roi` (rect), default [0, 0, 0, 0]
  - `learn_label` (text), default ""
  - `neighbours` (int), default 3; range 1 to 25
  - `min_score` (float), default 0.0; range 0 to 1
  - `top_k` (int), default 3; range 1 to 10
  - `model_file` (path), default ""
  - `samples` (json), default {}

### Mapping Calibration
*Category:* Calibration. Relates two cameras that both see the same calibration board: finds the board in each picture (or takes the two cameras' calibrations) and builds the matrix that turns the current camera's picture coordinates into the target camera's.
- Inputs: `Image` (IMAGE), `Image2` (IMAGE), `Calibration` (DICT), `Calibration2` (DICT)
- Outputs: `Status` (VALUE), `Current_Points` (VALUE), `Target_Points` (VALUE), `Mapped_Points` (VALUE), `Calibration_Error` (VALUE), `Calibration` (DICT), `Matrix` (ANY), `Scale` (VALUE), `Pixel_Accuracy` (VALUE), `Translation_X` (VALUE), `Translation_Y` (VALUE), `Rotation` (VALUE), `Skew` (VALUE), `Aspect_Ratio` (VALUE)
- Parameters:
  - `use` (enum), default "Pictures"; choices: Pictures | Calibrations
  - `board_type` (enum), default "Checkerboard"; choices: Checkerboard | Circle Grid
  - `columns` (int), default 9; range 2 to 100
  - `rows` (int), default 6; range 2 to 100
  - `dot_type` (enum), default "Dark on Light"; choices: Dark on Light | Light on Dark
  - `gray_contrast` (float), default 0.0; range 0 to 255
  - `median_filter` (bool), default false
  - `subpixel_window` (int), default 0; range 0 to 15
  - `dof` (enum), default "Affine (adds aspect ratio and skew)"; choices: Similarity (scale, rotation, translation) | Affine (adds aspect ratio and skew) | Perspective (adds projection)
  - `weighting` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey | RANSAC
  - `weight_coeff` (float), default 0.0; range 0 to 100
  - `distance_threshold` (float), default 3.0; range 0.0001 to 100000
  - `sampling_rate` (float), default 0.8; range 0.1 to 1
  - `save_path` (path), default ""
  - `update_file` (bool), default false

### Mark Location
*Category:* Location. Finds crosses (solid or hollow) and rectangles, such as alignment marks: it builds the shape from the size you give and matches it over the picture at each angle in the range. Gives every match with its position, angle and score.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Matches` (ANY), `Center_X` (VALUE), `Center_Y` (VALUE), `Angle_Deg` (VALUE), `Score` (VALUE)
- Parameters:
  - `mark_type` (enum), default "Hollow Cross"; choices: Hollow Cross | Solid Cross | Rectangle | Hollow Rectangle
  - `mark_width` (int), default 40; range 4 to 2000 px
  - `mark_height` (int), default 40; range 4 to 2000 px
  - `arm_width` (int), default 8; range 1 to 500 px
  - `mark_polarity` (enum), default "Dark on Light"; choices: Dark on Light | Light on Dark
  - `match_polarity` (enum), default "Considered"; choices: Considered | Ignored
  - `min_score` (float), default 0.5; range 0 to 1
  - `max_matches` (int), default 1; range 1 to 200
  - `angle_min` (float), default -10.0; range -180 to 180 deg
  - `angle_max` (float), default 10.0; range -180 to 180 deg
  - `angle_step` (float), default 1.0; range 0.1 to 45 deg
  - `max_overlap` (int), default 50; range 0 to 100 %
  - `roi` (rect), default [0, 0, 0, 0]

### Matrix Circle Search
*Category:* Location. Finds several circles that sit in a grid (rows x columns) inside a region: it searches each cell for a circle with a ring of calipers and reports every circle with its row and column.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Circles` (ANY), `Centers` (ANY), `Radii` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `array_rows` (int), default 2; range 1 to 100
  - `array_columns` (int), default 3; range 1 to 100
  - `min_radius` (float), default 8.0; range 1 to 5000 px
  - `max_radius` (float), default 40.0; range 2 to 5000 px
  - `min_count` (int), default 1; range 0 to 10000
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_threshold` (int), default 20; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `caliper_number` (int), default 24; range 2 to 500
  - `projection_width` (int), default 5; range 1 to 500 px
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Modbus TCP Write
*Category:* Communication. Writes a result into a PLC register or coil over Modbus TCP (function 5, 6 or 16). Values are scaled to whole numbers.
- Inputs: `Data` (ANY), `Trigger` (BOOLEAN)
- Outputs: `Sent_Bytes` (VALUE), `Last_Message` (STRING)
- Parameters:
  - `mode` (enum), default "Simulation (Log Only)"; choices: Simulation (Log Only) | Modbus TCP
  - `server_ip` (text), default "127.0.0.1"
  - `server_port` (int), default 502; range 1 to 65535
  - `unit_id` (int), default 1; range 0 to 255
  - `function` (enum), default "Write Single Register"; choices: Write Single Register | Write Multiple Registers | Write Single Coil
  - `start_address` (int), default 0; range 0 to 65535
  - `value_scale` (float), default 1.0; range 0.0001 to 1e+06
  - `connect_timeout_ms` (int), default 1000; range 50 to 60000 ms

### Multi-image Acquisition
*Category:* Acquisition. Takes 3 to 8 pictures in one go - from a folder of local pictures (the next ones each time) or from a camera, changing the exposure, gain and light brightness for each - and passes them on one by one and as a list. Used for photometric stereo and multi-exposure work.
- Inputs: `Clear` (BOOLEAN)
- Outputs: `Images` (ANY), `Count` (VALUE), `Light_Commands` (ANY), `Distribution_Angle` (VALUE), `Illumination_Angle` (VALUE), `Image1` (IMAGE), `Image2` (IMAGE), `Image3` (IMAGE), `Image4` (IMAGE), `Image5` (IMAGE), `Image6` (IMAGE), `Image7` (IMAGE), `Image8` (IMAGE)
- Parameters:
  - `image_source` (enum), default "Local Images"; choices: Local Images | Camera
  - `image_path` (path), default ""
  - `fetch_quantity` (int), default 3; range 3 to 8
  - `fetch_interval_ms` (int), default 50; range 0 to 60000 ms
  - `camera_device` (text), default "mvs_gige_0"
  - `exposures` (text), default "20000"
  - `gains` (text), default "1"
  - `light_enable` (bool), default false
  - `light_device` (enum), default "Simulation (Log Only)"; choices: Simulation (Log Only) | Serial Port | TCP Network
  - `light_channel` (int), default 1; range 1 to 64
  - `light_levels` (text), default "255"
  - `light_command_template` (text), default "SA{channel}{brightness:04d}#"
  - `light_port` (text), default "COM1"
  - `light_host` (text), default "192.168.0.100"
  - `light_tcp_port` (int), default 4001; range 1 to 65535
  - `trigger_time_ms` (int), default 0; range 0 to 60000 ms
  - `distribution_angle` (float), default 0.0; range 0 to 360 deg
  - `illumination_angle` (float), default 0.0; range 0 to 360 deg

### Multi-line Search
*Category:* Location. Finds several straight edges in a region at once. Edge points are pulled from the picture's brightness gradient and lines are found one after another (strongest first), each checked for how much of its length is really covered by edge points.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Lines` (ANY), `Count` (VALUE), `Angles` (ANY)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `filter_half_width` (int), default 2; range 1 to 50
  - `projection_length` (int), default 5; range 1 to 200 px
  - `threshold_type` (enum), default "Absolute"; choices: Absolute | Relative
  - `edge_threshold` (float), default 25.0; range 0 to 255
  - `edge_polarity` (enum), default "Any"; choices: Any | Black to White | White to Black
  - `edge_angle_tolerance` (float), default 15.0; range 0 to 90 deg
  - `edge_distance_tolerance` (float), default 2.5; range 0.1 to 100 px
  - `max_lines` (int), default 5; range 1 to 100
  - `coverage_rate` (float), default 30.0; range 0 to 100 %
  - `min_line_length` (float), default 20.0; range 2 to 10000 px
  - `search_direction_angle` (float), default 90.0; range -180 to 180 deg
  - `linear_rotation_tolerance` (float), default 90.0; range 0 to 90 deg
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Multiple Images Fusion
*Category:* Image Processing. Combines pictures of one part lit from different directions (3 to 8) into a reflection (surface colour / texture) picture and a shadow (shape / relief) picture, to show dents, scratches and raised or engraved characters. Halo removal drops that many of the brightest readings per pixel (specular glare), always keeping at least two.
- Inputs: `Image_0` (IMAGE), `Image_1` (IMAGE), `Image_2` (IMAGE), `Image_3` (IMAGE), `Image_4` (IMAGE), `Image_5` (IMAGE), `Image_6` (IMAGE), `Image_7` (IMAGE)
- Outputs: `Image` (IMAGE), `Reflection` (IMAGE), `Shadow` (IMAGE)
- Parameters:
  - `output_type` (enum), default "All"; choices: All | Reflection | Shadow
  - `filter_size` (int), default 3; range 1 to 50
  - `enhancement` (bool), default false
  - `background_brightness` (int), default 128; range 0 to 255
  - `contrast_coefficient` (int), default 100; range 1 to 1000
  - `direction_enhancement` (enum), default "None"; choices: None | X Direction | Y Direction
  - `direction_grade` (int), default 5; range 0 to 10
  - `halo_removal` (int), default 3; range 1 to 8

### N-Image Calibration
*Category:* Calibration. Calibrates from several pictures of one calibration board as the robot moves it (or the camera) by known steps: every corner of every picture gives an image point and a physical point, so the matrix is well determined. The last pictures can be taken while it turns, which gives the centre of rotation. Each run adds one picture.
- Inputs: `Image` (IMAGE), `Physical_Point` (POINT), `Clear` (BOOLEAN)
- Outputs: `Image` (IMAGE), `Status` (VALUE), `Remaining` (VALUE), `Translate_Pixel_Error` (VALUE), `Translate_Real_Error` (VALUE), `Rotate_Pixel_Error` (VALUE), `Rotate_Real_Error` (VALUE), `Rotation_Center` (POINT), `Calibration` (DICT), `Matrix` (ANY), `Scale` (VALUE), `Pixel_Accuracy` (VALUE), `Translation_X` (VALUE), `Translation_Y` (VALUE), `Rotation` (VALUE), `Skew` (VALUE), `Aspect_Ratio` (VALUE)
- Parameters:
  - `board_type` (enum), default "Checkerboard"; choices: Checkerboard | Circle Grid
  - `columns` (int), default 9; range 2 to 100
  - `rows` (int), default 6; range 2 to 100
  - `physical_size` (float), default 10.0; range 0.0001 to 100000 mm
  - `dot_type` (enum), default "Dark on Light"; choices: Dark on Light | Light on Dark
  - `gray_contrast` (float), default 0.0; range 0 to 255
  - `median_filter` (bool), default false
  - `subpixel_window` (int), default 0; range 0 to 15
  - `translation_times` (int), default 9; range 3 to 64
  - `rotation_times` (int), default 0; range 0 to 16
  - `fiducial_x` (float), default 0.0; range -1e+06 to 1e+06 mm
  - `fiducial_y` (float), default 0.0; range -1e+06 to 1e+06 mm
  - `offset_x` (float), default 5.0; range -1e+06 to 1e+06 mm
  - `offset_y` (float), default 5.0; range -1e+06 to 1e+06 mm
  - `movement_first` (enum), default "X First"; choices: X First | Y First
  - `commutation_times` (int), default 3; range 0 to 100
  - `fiducial_angle` (float), default -10.0; range -360 to 360 deg
  - `angle_offset` (float), default 10.0; range -360 to 360 deg
  - `camera_movement` (bool), default false
  - `matrix_correction` (bool), default false
  - `correct_image_x` (float), default 0.0; range -1e+06 to 1e+06 px
  - `correct_image_y` (float), default 0.0; range -1e+06 to 1e+06 px
  - `correct_physical_x` (float), default 0.0; range -1e+06 to 1e+06 mm
  - `correct_physical_y` (float), default 0.0; range -1e+06 to 1e+06 mm
  - `dof` (enum), default "Affine (adds aspect ratio and skew)"; choices: Similarity (scale, rotation, translation) | Affine (adds aspect ratio and skew) | Perspective (adds projection)
  - `weighting` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey | RANSAC
  - `weight_coeff` (float), default 0.0; range 0 to 100
  - `distance_threshold` (float), default 3.0; range 0.0001 to 100000
  - `sampling_rate` (float), default 0.8; range 0.1 to 1
  - `save_path` (path), default ""
  - `update_file` (bool), default false

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
  - `roi` (rect), default [0, 0, 0, 0]
  - `char_polarity` (enum), default "White on Dark"; choices: White on Dark | Dark on White
  - `min_confidence` (float), default 75.0; range 0 to 100 %
  - `expected_pattern` (text), default "SN-*"

### OCV
*Category:* Defect Detection. Optical Character Verification: checks printed characters and marks against what good prints look like. Train it on good pictures (it learns the typical look and how much each pixel varies), then each print is found and compared: bright or dark spots beyond the limits, such as missing, extra or smeared strokes, are defects. Edge tolerance forgives small shifts of the strokes.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Defect_Count` (VALUE), `Defect_Boxes` (ANY), `Score` (VALUE), `Pose` (ANY), `Trained` (VALUE), `Max_Difference` (VALUE)
- Parameters:
  - `mode` (enum), default "Detect"; choices: Detect | Train | Clear Model
  - `roi` (rect), default [0, 0, 0, 0]
  - `search_roi` (rect), default [0, 0, 0, 0]
  - `min_score` (float), default 0.5; range 0 to 1
  - `angle_min` (float), default -10.0; range -180 to 180 deg
  - `angle_max` (float), default 10.0; range -180 to 180 deg
  - `angle_step` (float), default 2.0; range 0.25 to 45 deg
  - `scale_x_range` (float), default 0.0; range 0 to 0.5
  - `scale_y_range` (float), default 0.0; range 0 to 0.5
  - `correct_position` (bool), default true
  - `defect_type` (enum), default "Bright and Dark"; choices: Bright and Dark | Bright | Dark
  - `bright_threshold` (int), default 40; range 0 to 255
  - `dark_threshold` (int), default 40; range 0 to 255
  - `bright_scale` (float), default 3.0; range 0 to 20
  - `dark_scale` (float), default 3.0; range 0 to 20
  - `edge_tolerance` (int), default 1; range 0 to 20
  - `area_tolerance` (int), default 6; range 0 to 100000 px
  - `model` (hidden), default {}

### Object Detection
*Category:* Deep Learning. Finds and boxes objects or defects with a YOLO model. An exported .onnx model runs on its own (no PyTorch needed); a .pt model runs through Ultralytics.
- Inputs: `Image` (IMAGE), `ROI` (REGION)
- Outputs: `Image` (IMAGE), `Count` (VALUE), `Boxes` (ANY), `Classes` (ANY), `Scores` (ANY), `Status` (STRING), `Detections` (ANY)
- Parameters:
  - `model_path` (path), default "yolo11n.onnx"
  - `confidence` (float), default 0.25; range 0 to 1
  - `iou` (float), default 0.45; range 0 to 1
  - `classes` (text), default "all"
  - `device` (enum), default "cpu"; choices: cpu | cuda | auto
  - `max_detections` (int), default 100; range 1 to 1000
  - `roi` (rect), default [0, 0, 0, 0]
  - `labels` (text), default ""
  - `save_in_solution` (bool), default false
  - `model_data` (hidden), default {}

### P2C Measure
*Category:* Measurement. Measures between a point and a circle: the distance from the point to the circle's centre and to its edge (negative when the point is inside), the closest point on the circle, and the angle of the connection.
- Inputs: `Point` (POINT), `Circle` (CIRCLE)
- Outputs: `Distance` (VALUE), `Center_Distance` (VALUE), `Abs_Distance` (VALUE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Angle_Deg` (VALUE), `Nearest_Point` (POINT)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Circle | By Coordinate
  - `point_x` (float), default 100.0; range -1e+06 to 1e+06 px
  - `point_y` (float), default 100.0; range -1e+06 to 1e+06 px
  - `circle_x` (float), default 300.0; range -1e+06 to 1e+06 px
  - `circle_y` (float), default 200.0; range -1e+06 to 1e+06 px
  - `circle_r` (float), default 60.0; range 0.01 to 1e+06 px
  - `angle_range` (enum), default "-180 to 180"; choices: -180 to 180 | -90 to 90
  - `scale_factor` (float), default 1.0; range 1e-06 to 1e+06

### P2L Measure
*Category:* Measurement. Shortest (perpendicular) distance from a point to an infinite line, and the point on the line closest to it.
- Inputs: `Point` (POINT), `Line` (LINE)
- Outputs: `Distance` (VALUE), `Foot` (POINT)
- Parameters:
  - `scale_factor` (float), default 1.0; range 1e-06 to 1e+06
  - `default_point` (point), default [200, 100]
  - `default_line` (line), default [100, 200, 400, 200]
  - `min_distance` (float), default 0.0; range 0 to 1e+09
  - `max_distance` (float), default 1000.0; range 0 to 1e+09

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

### Parallel Lines Search
*Category:* Location. Finds two lines that are roughly parallel (a bar, a slot, a cable): at each caliper it takes an edge pair, fits a line through each side, checks they are parallel within the tolerance, and gives both lines, the centre line between them and their spacing.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Line_1` (LINE), `Line_2` (LINE), `Center_Line` (LINE), `Distance` (VALUE), `Angle_Deg` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `search_direction` (enum), default "Top to Bottom"; choices: Left to Right | Right to Left | Top to Bottom | Bottom to Top
  - `edge_pair_type` (enum), default "Strongest Pair"; choices: Strongest Pair | First Pair | Last Pair
  - `max_angle_tolerance` (float), default 3.0; range 0 to 90 deg
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_threshold` (int), default 15; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `caliper_number` (int), default 16; range 2 to 500
  - `projection_width` (int), default 5; range 1 to 500 px
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Path Extraction
*Category:* Location. Takes points along a path you describe (a polyline or an arc): either spaced equally along it, or moved to the real edge nearby (for gluing, welding and dispensing paths). Follows the part when you connect a Position Correction.
- Inputs: `Image` (IMAGE), `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Outputs: `Image` (IMAGE), `Points` (ANY), `Count` (VALUE), `Path_Length` (VALUE), `Arc_Center` (POINT), `Arc_Angle` (VALUE)
- Parameters:
  - `path_type` (enum), default "Polyline"; choices: Polyline | Arc
  - `path_points` (points), default [[80, 200], [200, 140], [320, 200], [440, 140]]
  - `arc_center` (point), default [250, 200]
  - `arc_radius` (float), default 100.0; range 1 to 100000 px
  - `arc_start_angle` (float), default 0.0; range -720 to 720 deg
  - `arc_end_angle` (float), default 180.0; range -720 to 720 deg
  - `extraction_method` (enum), default "Equal Interval Points"; choices: Equal Interval Points | Find Edge Points
  - `point_count` (int), default 20; range 2 to 300
  - `position_offset` (float), default 0.0; range -1000 to 1000 px
  - `reference_point` (point), default [0, 0]
  - `output_arc_params` (bool), default true
  - `caliper_height` (int), default 24; range 2 to 1000 px
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_threshold` (int), default 20; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `caliper_number` (int), default 20; range 2 to 500
  - `projection_width` (int), default 5; range 1 to 500 px
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Peak Search
*Category:* Location. Finds the tip of an object: scans across a region, takes the first edge each scan meets, and reports the edge point that lies nearest the side the scan started from (the peak), with its strength, polarity and distance from that side.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Peak_X` (VALUE), `Peak_Y` (VALUE), `Peak_Score` (VALUE), `Peak_Polarity` (STRING), `Peak_Distance` (VALUE), `Edge_Number` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `search_direction` (enum), default "Top to Bottom"; choices: Left to Right | Right to Left | Top to Bottom | Bottom to Top
  - `scan_width` (int), default 4; range 1 to 500 px
  - `edge_threshold` (int), default 20; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_type` (enum), default "First Edge"; choices: Strongest Edge | First Edge | Last Edge

### Pixel Count
*Category:* Measurement. Counts pixels matching low/high threshold range within specified ROI.
- Inputs: `Image` (IMAGE)
- Outputs: `Pixel_Count` (VALUE), `Ratio` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `low_threshold` (int), default 128; range 0 to 255
  - `high_threshold` (int), default 255; range 0 to 255
  - `min_count` (int), default 100; range 0 to 1e+09
  - `max_count` (int), default 50000; range 0 to 1e+09

### Pixel Transformation
*Category:* Division and Combination. Turns a label picture (each pixel holds a class number) into a black-and-white mask: pixels whose value is in the class list become 255, everything else 0. Used after instance segmentation to pick the classes you want.
- Inputs: `Image` (IMAGE), `Class_Index` (ANY), `Class_Count` (VALUE)
- Outputs: `Image` (IMAGE), `Pixel_Count` (VALUE)
- Parameters:
  - `class_list` (text), default "1"

### Point Set
*Category:* Logic Tools. Gathers up to 16 points into one set for later modules. Points come from a list, from the typed ones, or - with the loop on - one more each time it runs (inside a Group's loop), until you clear it.
- Inputs: `Point` (POINT), `Points` (ANY), `Clear` (BOOLEAN)
- Outputs: `Points` (ANY), `X` (ANY), `Y` (ANY), `Count` (VALUE)
- Parameters:
  - `loop` (bool), default false
  - `points` (points), default []

### Point Set Alignment
*Category:* Calculation. Works out the move that brings a set of object points onto the matching target points (2 or more pairs, in the same order): the turn about the object points' centre and the shift of that centre, plus how well they fit afterwards. Use physical coordinates.
- Inputs: `Target_Points` (ANY), `Object_Points` (ANY)
- Outputs: `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Move` (ANY), `Error` (VALUE), `Center` (POINT), `Matrix` (ANY)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `target_points` (points), default [[100, 100], [200, 100], [200, 200]]
  - `object_points` (points), default [[104, 98], [204, 99], [205, 199]]

### Position Correction
*Category:* Location. Establishes reference match point & angle to calculate position deviation for subsequent tool ROIs.
- Inputs: `Running_X` (VALUE), `Running_Y` (VALUE), `Running_Angle` (VALUE)
- Outputs: `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Affine_Matrix` (ANY)
- Parameters:
  - `fiducial_x` (float), default 350.0
  - `fiducial_y` (float), default 300.0
  - `fiducial_angle` (float), default 0.0; range -360 to 360 deg
  - `set_current_as_fiducial` (bool), default false

### Protocol Assembly
*Category:* Communication. Builds a message from values - the reverse of Protocol Parsing. Text assembly joins them with a symbol; byte assembly packs numbers of a given size into hex text; script assembly runs your assemble(values) function.
- Inputs: `Values` (ANY), `Value1` (ANY), `Value2` (ANY), `Value3` (ANY), `Value4` (ANY), `Value5` (ANY), `Value6` (ANY), `Value7` (ANY), `Value8` (ANY)
- Outputs: `Text` (STRING), `Length` (VALUE)
- Parameters:
  - `mode` (enum), default "Text"; choices: Text | Byte | Script
  - `split_symbol` (text), default ";"
  - `end_char` (text), default ""
  - `fields` (text), default "i32,i32"
  - `byte_order` (enum), default "Big-endian"; choices: Big-endian | Little-endian
  - `script` (code), default "(multi-line text)"

### Protocol Parsing
*Category:* Communication. Turns a received message into separate values. Text parsing splits at a symbol (1;123;234 becomes 1, 123 and 234); byte parsing reads numbers of a given size out of hex text (0000006400000005 with i32,i32 becomes 100 and 5); script parsing runs your parse(text) function.
- Inputs: `Text` (STRING)
- Outputs: `Values` (ANY), `Count` (VALUE), `Value1` (ANY), `Value2` (ANY), `Value3` (ANY), `Value4` (ANY), `Value5` (ANY), `Value6` (ANY), `Value7` (ANY), `Value8` (ANY)
- Parameters:
  - `mode` (enum), default "Text"; choices: Text | Byte | Script
  - `split_symbol` (text), default ";"
  - `trim` (bool), default true
  - `fields` (text), default "i32,i32"
  - `byte_order` (enum), default "Big-endian"; choices: Big-endian | Little-endian
  - `input_format` (enum), default "Hex"; choices: Hex | ASCII
  - `script` (code), default "(multi-line text)"

### Quadrilateral Search
*Category:* Location. Finds a four-sided shape of any outline: give the four corners of the region; one line is fitted along each side and the corners are where neighbouring lines meet.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Center_X` (VALUE), `Center_Y` (VALUE), `Width` (VALUE), `Height` (VALUE), `Angle_Deg` (VALUE), `Corners` (ANY), `Lines` (ANY), `Box` (DICT)
- Parameters:
  - `quad_points` (points), default [[100, 80], [340, 90], [330, 240], [95, 230]]
  - `search_margin` (float), default 20.0; range 2 to 1000 px
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_threshold` (int), default 20; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `caliper_number` (int), default 16; range 2 to 500
  - `projection_width` (int), default 5; range 1 to 500 px
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Receive Data
*Category:* Communication. Takes data from a named global variable or queue (the oldest item, or just a look at it), or from a fixed text for testing.
- Inputs: `Trigger` (ANY)
- Outputs: `Data` (ANY), `Text` (STRING), `Has_Data` (VALUE), `Queue_Length` (VALUE)
- Parameters:
  - `source` (enum), default "Global Variable"; choices: Global Variable | Data Queue | Communication Device | Test Text
  - `name` (text), default "result"
  - `take` (enum), default "Remove"; choices: Remove | Keep
  - `test_text` (text), default ""

### Rect Search
*Category:* Location. Finds a rectangle: one line is fitted along each of the four sides of the region you draw (searching a band either side of it) and the corners are where the lines meet. Gives the centre, width, height and angle.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Center_X` (VALUE), `Center_Y` (VALUE), `Width` (VALUE), `Height` (VALUE), `Angle_Deg` (VALUE), `Corners` (ANY), `Lines` (ANY), `Box` (DICT)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `roi_angle` (float), default 0.0; range -360 to 360 deg
  - `search_margin` (float), default 20.0; range 2 to 1000 px
  - `edge_type` (enum), default "Strongest Edge"; choices: Strongest Edge | First Edge | Last Edge
  - `edge_polarity` (enum), default "Any"; choices: Any | Dark to Light | Light to Dark
  - `edge_threshold` (int), default 20; range 0 to 255
  - `filter_size` (int), default 3; range 1 to 50
  - `caliper_number` (int), default 16; range 2 to 500
  - `projection_width` (int), default 5; range 1 to 500 px
  - `reject_number` (int), default 0; range 0 to 200
  - `distance_to_remove` (float), default 5.0; range 0 to 1000 px
  - `fit_mode` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey

### Ring Expansion
*Category:* Image Processing. Unrolls a ring (or a part of one) into a straight strip, for reading text printed around a circle or checking a round part.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Width` (VALUE), `Height` (VALUE)
- Parameters:
  - `center` (point), default [320, 240]
  - `inner_radius` (float), default 60.0; range 0 to 20000 px
  - `outer_radius` (float), default 140.0; range 1 to 20000 px
  - `start_angle` (float), default 0.0; range -360 to 360 deg
  - `arc_angle` (float), default 360.0; range 1 to 360 deg
  - `direction` (enum), default "Counterclockwise"; choices: Counterclockwise | Clockwise
  - `radial_direction` (enum), default "Inside to Outside"; choices: Inside to Outside | Outside to Inside
  - `output_width` (int), default 0; range 0 to 16384 px

### Rotation Calibration
*Category:* Calibration. Finds the centre a mechanism turns about: the same feature is seen after each of 3 to 16 equal turns, and a circle is fitted through the positions. Gives the centre in the picture and, with a calibration, in physical units, with the fitting errors.
- Inputs: `Point` (POINT), `Calibration` (DICT), `Clear` (BOOLEAN), `Refresh` (VALUE)
- Outputs: `Status` (VALUE), `Remaining` (VALUE), `Image_Center` (POINT), `Physical_Center` (POINT), `Pixel_Error` (VALUE), `Real_Error` (VALUE), `Angle_Error` (VALUE), `Radius` (VALUE), `Points` (ANY)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `point_x` (float), default 0.0; range -1e+06 to 1e+06 px
  - `point_y` (float), default 0.0; range -1e+06 to 1e+06 px
  - `accumulate` (bool), default true
  - `rotation_times` (int), default 3; range 3 to 16
  - `rotation_angle` (float), default 10.0; range -360 to 360 deg
  - `calibration_file` (path), default ""
  - `image_points` (points), default [[400, 300], [380, 360], [330, 395]]

### Save Text
*Category:* Logic Tools. Saves text or values to TXT or CSV files, one line each time. Choose the folder and file name, how large a file may grow, how many files to keep, and whether to stop or overwrite the oldest when that is reached. A trigger can decide when to save.
- Inputs: `Text` (ANY), `Trigger` (VALUE), `Flush` (BOOLEAN)
- Outputs: `Saved` (VALUE), `Path` (STRING), `Waiting` (VALUE)
- Parameters:
  - `data_type` (enum), default "TXT"; choices: TXT | CSV
  - `save_dir` (dir), default ""
  - `file_name` (text), default "result"
  - `trigger_value` (float), default 1.0; range -1e+09 to 1e+09
  - `file_count` (int), default 10; range 1 to 10000
  - `document_size_kb` (int), default 1024; range 1 to 1e+07 KB
  - `save_mode` (enum), default "Overwrite Oldest"; choices: Stop Saving | Overwrite Oldest
  - `timestamp` (bool), default false
  - `by_date` (bool), default false
  - `real_time` (bool), default true
  - `csv_header` (text), default ""

### Scale Transformation
*Category:* Calculation. Turns a length measured in pixels into a physical length (or back) using a calibration's pixel size.
- Inputs: `Distance` (VALUE), `Calibration` (DICT), `Refresh` (VALUE)
- Outputs: `Result` (VALUE), `Results` (ANY), `Calibration` (DICT), `Matrix` (ANY), `Scale` (VALUE), `Pixel_Accuracy` (VALUE), `Translation_X` (VALUE), `Translation_Y` (VALUE), `Rotation` (VALUE), `Skew` (VALUE), `Aspect_Ratio` (VALUE)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Port | By Coordinate
  - `distance` (float), default 100.0
  - `direction` (enum), default "Pixel to Physical"; choices: Pixel to Physical | Physical to Pixel
  - `calibration_file` (path), default ""

### Script
*Category:* Logic Tools. Runs your own Python with the image, the Val1 / Val2 inputs, OpenCV (cv2) and NumPy (np). Set outputs['Result'], outputs['Status'] ('OK' passes, anything else fails), outputs['Image'] and add overlays. get_global(name) / set_global(name, value) read and write the solution's global variables, and print() goes to the Log output. A script that runs longer than its time limit is stopped.  
**Has side effects** (network, files, hardware or user code): mention it to the user.
- Inputs: `Image` (IMAGE), `Val1` (VALUE), `Val2` (VALUE)
- Outputs: `Image` (IMAGE), `Result` (ANY), `Status` (STRING), `Log` (STRING)
- Parameters:
  - `code` (code), default "(multi-line text)"
  - `timeout_ms` (int), default 5000; range 100 to 600000 ms

### Send Data
*Category:* Communication. Puts a result where other flows or modules can pick it up: into a named global variable, or onto a named queue (first in, first out). To send to a PLC, robot or computer use TCP Send, UDP Send, Serial Send or Modbus TCP Write.
- Inputs: `Data` (ANY), `Trigger` (ANY)
- Outputs: `Sent` (VALUE), `Queue_Length` (VALUE)
- Parameters:
  - `target` (enum), default "Global Variable"; choices: Global Variable | Data Queue | Communication Device
  - `name` (text), default "result"
  - `queue_length` (int), default 1000; range 1 to 1e+06

### Serial Send
*Category:* Communication. Sends the inspection result out of a serial (COM / RS-232 / RS-485) port. Needs the 'pyserial' package for real ports.
- Inputs: `Data` (ANY), `Trigger` (BOOLEAN)
- Outputs: `Sent_Bytes` (VALUE), `Last_Message` (STRING)
- Parameters:
  - `mode` (enum), default "Simulation (Log Only)"; choices: Simulation (Log Only) | Serial Port
  - `port_name` (combo), default "COM3"; choices: COM1 | COM2 | COM3 | COM4 | COM5 | COM6 | COM7 | COM8 | COM9 | COM10 | /dev/ttyUSB0 | /dev/ttyS0
  - `baud_rate` (enum), default "9600"; choices: 1200 | 2400 | 4800 | 9600 | 19200 | 38400 | 57600 | 115200
  - `parity` (enum), default "None"; choices: None | Even | Odd
  - `prefix` (text), default "APEX_RES,"
  - `suffix` (text), default "\\r\\n"
  - `format` (enum), default "CSV"; choices: CSV | JSON | Plain Text

### Shade Correction
*Category:* Image Processing. Evens out uneven lighting: compares the picture with a smoothed copy of itself and rebuilds it around a fixed brightness.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE)
- Parameters:
  - `kernel_size` (int), default 15; range 1 to 50
  - `gain` (float), default 10.0; range 0 to 100
  - `compensation` (int), default 128; range 0 to 255
  - `noise` (int), default 0; range 0 to 255
  - `direction` (enum), default "XY"; choices: X | Y | XY
  - `roi` (rect), default [0, 0, 0, 0]

### Single Point Alignment
*Category:* Calculation. Works out the move that brings an object to a target, from the target's physical position and angle and the object's: how far to shift and how much to turn. If the object turns about a fixed centre (a rotation stage) give it, and the shift allows for the turn. Needs physical coordinates, so use it after Calibration Transformation.
- Inputs: `Target` (POINT), `Target_Angle` (VALUE), `Object` (POINT), `Object_Angle` (VALUE), `Center` (POINT)
- Outputs: `Delta_X` (VALUE), `Delta_Y` (VALUE), `Delta_Angle` (VALUE), `Move` (ANY), `Aligned_Point` (POINT)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `target_x` (float), default 100.0; range -1e+09 to 1e+09
  - `target_y` (float), default 100.0; range -1e+09 to 1e+09
  - `target_angle` (float), default 0.0; range -360 to 360 deg
  - `object_x` (float), default 95.0; range -1e+09 to 1e+09
  - `object_y` (float), default 103.0; range -1e+09 to 1e+09
  - `object_angle` (float), default 5.0; range -360 to 360 deg
  - `turn_about` (enum), default "The Object"; choices: The Object | A Fixed Centre
  - `center_x` (float), default 0.0; range -1e+09 to 1e+09
  - `center_y` (float), default 0.0; range -1e+09 to 1e+09

### Single Point Grasp
*Category:* Calculation. Works out where a grasping tool must go to pick up a part: from the part's reference position (where the tool picked it in the demonstration) and where it is now, in the picture, it gives the move relative to the demonstration and the absolute robot position. Takes a calibration; if the calibration holds a rotation centre the move allows for the tool turning about it. Press Create Reference Point (or send Set_Reference) in the demonstration run.
- Inputs: `Reference` (POINT), `Reference_Angle` (VALUE), `Run` (POINT), `Run_Angle` (VALUE), `Calibration` (DICT), `Demo_Pose` (ANY), `Set_Reference` (BOOLEAN), `Refresh` (VALUE)
- Outputs: `Status` (VALUE), `Relative_X` (VALUE), `Relative_Y` (VALUE), `Relative_R` (VALUE), `Absolute_X` (VALUE), `Absolute_Y` (VALUE), `Absolute_R` (VALUE), `Relative` (ANY), `Absolute` (ANY)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `calibration_file` (path), default ""
  - `ref_x` (float), default 320.0; range -1e+09 to 1e+09 px
  - `ref_y` (float), default 240.0; range -1e+09 to 1e+09 px
  - `ref_angle` (float), default 0.0; range -360 to 360 deg
  - `create_reference` (bool), default false
  - `run_x` (float), default 330.0; range -1e+09 to 1e+09 px
  - `run_y` (float), default 250.0; range -1e+09 to 1e+09 px
  - `run_angle` (float), default 3.0; range -360 to 360 deg
  - `demo_x` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `demo_y` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `demo_angle` (float), default 0.0; range -360 to 360 deg
  - `reference_set` (bool), default false
  - `capture_x` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `capture_y` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `run_capture_x` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `run_capture_y` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `enable_rotation_capture` (bool), default false
  - `rotation_capture_angle` (float), default 0.0; range -360 to 360 deg

### Single Point Mapping Alignment
*Category:* Calculation. Aligns a part seen by one camera to a target seen by another: the target's picture point is carried into the part camera's picture with a Mapping Calibration, then the move that brings the part onto it is worked out like Single Point Rectification.
- Inputs: `Target` (POINT), `Target_Angle` (VALUE), `Object` (POINT), `Object_Angle` (VALUE), `Mapping` (DICT), `Calibration` (DICT), `Demo_Pose` (ANY), `Refresh` (VALUE)
- Outputs: `Status` (VALUE), `Relative_X` (VALUE), `Relative_Y` (VALUE), `Relative_R` (VALUE), `Absolute_X` (VALUE), `Absolute_Y` (VALUE), `Absolute_R` (VALUE), `Relative` (ANY), `Absolute` (ANY)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `calibration_file` (path), default ""
  - `target_x` (float), default 320.0; range -1e+09 to 1e+09 px
  - `target_y` (float), default 240.0; range -1e+09 to 1e+09 px
  - `target_angle` (float), default 0.0; range -360 to 360 deg
  - `object_x` (float), default 330.0; range -1e+09 to 1e+09 px
  - `object_y` (float), default 250.0; range -1e+09 to 1e+09 px
  - `object_angle` (float), default 3.0; range -360 to 360 deg
  - `mapping_file` (path), default ""
  - `demo_x` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `demo_y` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `demo_angle` (float), default 0.0; range -360 to 360 deg

### Single Point Rectification
*Category:* Calculation. Works out how to move a part so it sits where it did in the demonstration: from its reference position and its position now in the picture it gives the shift and turn to apply (relative), and with the demonstration pose added, the absolute robot position.
- Inputs: `Reference` (POINT), `Reference_Angle` (VALUE), `Run` (POINT), `Run_Angle` (VALUE), `Calibration` (DICT), `Demo_Pose` (ANY), `Set_Reference` (BOOLEAN), `Refresh` (VALUE)
- Outputs: `Status` (VALUE), `Relative_X` (VALUE), `Relative_Y` (VALUE), `Relative_R` (VALUE), `Absolute_X` (VALUE), `Absolute_Y` (VALUE), `Absolute_R` (VALUE), `Relative` (ANY), `Absolute` (ANY)
- Parameters:
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `calibration_file` (path), default ""
  - `ref_x` (float), default 320.0; range -1e+09 to 1e+09 px
  - `ref_y` (float), default 240.0; range -1e+09 to 1e+09 px
  - `ref_angle` (float), default 0.0; range -360 to 360 deg
  - `create_reference` (bool), default false
  - `run_x` (float), default 330.0; range -1e+09 to 1e+09 px
  - `run_y` (float), default 250.0; range -1e+09 to 1e+09 px
  - `run_angle` (float), default 3.0; range -360 to 360 deg
  - `demo_x` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `demo_y` (float), default 0.0; range -1e+09 to 1e+09 mm
  - `demo_angle` (float), default 0.0; range -360 to 360 deg
  - `reference_set` (bool), default false

### String Comparison
*Category:* Logic Tools. Compares a text with up to 32 texts you list and gives the index of the one it matches, for use with Branch. Nothing matching gives NG and no index.
- Inputs: `Text` (STRING)
- Outputs: `Index` (VALUE), `Matched` (VALUE), `Text` (STRING)
- Parameters:
  - `strings` (text), default "OK;NG"
  - `indices` (text), default ""
  - `case_sensitive` (bool), default true
  - `trim` (bool), default true

### Surface Defect Filter
*Category:* Defect Detection. Brings out scratches, dents, specks and foreign matter on a plain surface: the picture is filtered with line detectors turned to several directions, so a defect gives a strong response and a clean surface gives about 0. Threshold the result and use BLOB Analysis to count the defects. Weights make some directions count more or less.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Max_Response` (VALUE), `Mean_Response` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `kernel_width` (int), default 21; range 3 to 201 px
  - `kernel_height` (int), default 9; range 3 to 201 px
  - `kernel_count` (int), default 6; range 1 to 36
  - `std_dev` (float), default 1.5; range 0.3 to 30
  - `offset` (float), default 4.0; range -255 to 255
  - `gain` (float), default 4.0; range 0.1 to 100
  - `weight_0` (int), default 0; range -10 to 10
  - `weight_30` (int), default 0; range -10 to 10
  - `weight_60` (int), default 0; range -10 to 10
  - `weight_90` (int), default 0; range -10 to 10
  - `weight_120` (int), default 0; range -10 to 10
  - `weight_150` (int), default 0; range -10 to 10

### TCP Send
*Category:* Communication. Sends inspection results, coordinates, or formatted strings to PLC/Robot via TCP/IP socket.  
**Has side effects** (network, files, hardware or user code): mention it to the user.
- Inputs: `Data` (ANY), `Trigger` (BOOLEAN)
- Outputs: `Sent_Bytes` (VALUE), `Last_Message` (STRING)
- Parameters:
  - `mode` (enum), default "Simulation (Loopback Log)"; choices: Simulation (Loopback Log) | TCP Client
  - `server_ip` (text), default "127.0.0.1"
  - `server_port` (int), default 8080; range 1 to 65535
  - `prefix` (text), default "APEX_RES,"
  - `suffix` (text), default "\\r\\n"
  - `format` (enum), default "CSV"; choices: CSV | JSON | Plain Text
  - `connect_timeout_ms` (int), default 500; range 50 to 60000 ms

### Target Tracking
*Category:* Location. Counts targets that move through the picture (for example items on a belt): it follows each detected box from picture to picture, and counts it once when it crosses the counting line in the middle of the region.
- Inputs: `Boxes` (ANY), `Clear` (BOOLEAN)
- Outputs: `Count` (VALUE), `Active` (VALUE), `Tracks` (ANY), `New_Counts` (VALUE)
- Parameters:
  - `roi` (rect), default [0, 0, 0, 0]
  - `direction` (enum), default "Left to Right"; choices: Left to Right | Right to Left | Top to Bottom | Bottom to Top
  - `track_speed_x` (float), default 1.0; range 0.1 to 10
  - `track_speed_y` (float), default 1.0; range 0.1 to 10
  - `max_lost_frames` (int), default 2; range 0 to 100
  - `track_overlap` (int), default 30; range 1 to 100 %

### Template Match
*Category:* Location. Searches for a template pattern with confidence score, subpixel translation, and rotation angle.
- Inputs: `Image` (IMAGE)
- Outputs: `Image` (IMAGE), `Score` (VALUE), `Center_X` (VALUE), `Center_Y` (VALUE), `Angle` (VALUE), `Box` (REGION)
- Parameters:
  - `min_score` (float), default 0.65; range 0 to 1
  - `template_roi` (rect), default [0, 0, 0, 0]
  - `start_angle` (float), default -15.0; range -180 to 180 deg
  - `end_angle` (float), default 15.0; range -180 to 180 deg
  - `angle_step` (float), default 2.0; range 0.1 to 90 deg
  - `max_matches` (int), default 1; range 1 to 100

### Time Consuming
*Category:* Logic Tools. Measures how long the flow has taken: since it began, or from the start of one module to the end of another (the end must come after the start). A limit turns a slow run into NG.
- Inputs: `Trigger` (ANY)
- Outputs: `Elapsed_Ms` (VALUE)
- Parameters:
  - `measure` (enum), default "Since Flow Start"; choices: Since Flow Start | Between Modules
  - `start_module` (text), default ""
  - `end_module` (text), default ""
  - `max_ms` (float), default 0.0; range 0 to 3.6e+06 ms

### Translation and Rotation Calibration
*Category:* Calibration. Calibrates a camera against a robot or stage: the robot steps through a pattern of positions (a snake over a grid) and a picture is taken at each; for a mechanism that turns about an axis away from the tool, a few more pictures are taken while it turns. Builds the image-to-physical matrix and the centre of rotation, and writes a calibration file. With trigger acquisition each run adds one picture.
- Inputs: `Point` (POINT), `Angle` (VALUE), `Physical_Point` (POINT), `Physical_Angle` (VALUE), `Clear` (BOOLEAN)
- Outputs: `Status` (VALUE), `Remaining` (VALUE), `Translate_Pixel_Error` (VALUE), `Translate_Real_Error` (VALUE), `Rotate_Pixel_Error` (VALUE), `Rotate_Real_Error` (VALUE), `Image_Center` (POINT), `Physical_Center` (POINT), `Image_Points` (ANY), `Physical_Points` (ANY), `Calibration` (DICT), `Matrix` (ANY), `Scale` (VALUE), `Pixel_Accuracy` (VALUE), `Translation_X` (VALUE), `Translation_Y` (VALUE), `Rotation` (VALUE), `Skew` (VALUE), `Aspect_Ratio` (VALUE)
- Parameters:
  - `calibration_type` (enum), default "Translation and Rotation"; choices: Translation | Translation and Rotation
  - `points_acquisition` (enum), default "Trigger"; choices: Trigger | Manual Input
  - `camera_mode` (enum), default "Static Camera Above"; choices: Static Camera Above | Static Camera Below | Dynamic Camera
  - `input_mode` (enum), default "By Coordinate"; choices: By Point | By Coordinate
  - `point_x` (float), default 0.0; range -1e+06 to 1e+06 px
  - `point_y` (float), default 0.0; range -1e+06 to 1e+06 px
  - `translation_times` (int), default 9; range 4 to 16
  - `rotation_times` (int), default 3; range 3 to 16
  - `fiducial_x` (float), default 0.0; range -1e+06 to 1e+06 mm
  - `fiducial_y` (float), default 0.0; range -1e+06 to 1e+06 mm
  - `offset_x` (float), default 5.0; range -1e+06 to 1e+06 mm
  - `offset_y` (float), default 5.0; range -1e+06 to 1e+06 mm
  - `movement_first` (enum), default "X First"; choices: X First | Y First
  - `commutation_times` (int), default 3; range 0 to 100
  - `fiducial_angle` (float), default -10.0; range -360 to 360 deg
  - `angle_offset` (float), default 10.0; range -360 to 360 deg
  - `image_points` (points), default []
  - `physical_points` (points), default []
  - `dof` (enum), default "Affine (adds aspect ratio and skew)"; choices: Similarity (scale, rotation, translation) | Affine (adds aspect ratio and skew) | Perspective (adds projection)
  - `weighting` (enum), default "Least Squares"; choices: Least Squares | Huber | Tukey | RANSAC
  - `weight_coeff` (float), default 0.0; range 0 to 100
  - `distance_threshold` (float), default 3.0; range 0.0001 to 100000
  - `sampling_rate` (float), default 0.8; range 0.1 to 1
  - `save_path` (path), default ""
  - `update_file` (bool), default false

### Trigger
*Category:* Logic Tools. Triggers execution of another flow in the solution.
- Inputs: `Trigger_Signal` (BOOLEAN)
- Outputs: `Status` (STRING)
- Parameters:
  - `target_flow` (flow), default "Flow2"
  - `require_signal_true` (bool), default true

### UDP Send
*Category:* Communication. Sends the inspection result as a UDP datagram to a PLC, robot or another computer.
- Inputs: `Data` (ANY), `Trigger` (BOOLEAN)
- Outputs: `Sent_Bytes` (VALUE), `Last_Message` (STRING)
- Parameters:
  - `mode` (enum), default "Simulation (Log Only)"; choices: Simulation (Log Only) | UDP
  - `server_ip` (text), default "127.0.0.1"
  - `server_port` (int), default 9000; range 1 to 65535
  - `prefix` (text), default "APEX_RES,"
  - `suffix` (text), default "\\r\\n"
  - `format` (enum), default "CSV"; choices: CSV | JSON | Plain Text

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
