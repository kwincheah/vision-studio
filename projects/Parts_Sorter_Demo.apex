<?xml version='1.0' encoding='utf-8'?>
<ApexSolution version="4.3" name="Parts_Sorter_Demo" active_flow="Parts_Sorter" trigger_flow="Parts_Sorter">
  <GlobalVariables>
    <Variable name="g_CountOK" type="int" runtime="true">3</Variable>
    <Variable name="g_CountNG" type="int" runtime="true">0</Variable>
    <Variable name="g_LotNumber" type="str">LOT-2026-A1</Variable>
    <Variable name="g_TriggerEnable" type="bool">true</Variable>
    <Variable name="g_SmallMax" type="int">2000</Variable>
    <Variable name="g_LargeMin" type="int">8000</Variable>
    <Variable name="g_MinArea" type="int">500</Variable>
    <Variable name="g_RejectElongated" type="bool">true</Variable>
    <Variable name="g_History" type="str" runtime="true">6,6,6</Variable>
    <Variable name="g_Total" type="int" runtime="true">3</Variable>
    <Variable name="g_LastCount" type="int" runtime="true">6</Variable>
    <Variable name="g_LastVerdict" type="str" runtime="true">OK</Variable>
  </GlobalVariables>
  <Flows>
    <ApexFlow version="4.3" name="Parts_Sorter">
      <Properties>
        <Property name="enabled" type="bool">true</Property>
        <Property name="run_interval_ms" type="float">50.0</Property>
        <Property name="stop_on_ng" type="bool">false</Property>
        <Property name="flow_timeout_ms" type="float">5000.0</Property>
        <Property name="execution_count" type="int">3</Property>
      </Properties>
      <Nodes>
        <Node instance_id="node_cam" tool_name="Image Source" name="01_Camera" category="Acquisition" enabled="true">
          <Parameters>
            <Parameter name="source_type" type="str">File</Parameter>
            <Parameter name="file_path" type="str">apex_vision/samples/parts/parts_good.png</Parameter>
            <Parameter name="pattern_type" type="str">Circles &amp; Holes</Parameter>
            <Parameter name="color_mode" type="str">BGR</Parameter>
            <Parameter name="camera_device" type="str">webcam_0</Parameter>
            <Parameter name="camera_index" type="int">0</Parameter>
            <Parameter name="auto_exposure" type="bool">true</Parameter>
            <Parameter name="exposure_time_us" type="float">20000.0</Parameter>
            <Parameter name="gain" type="float">1.0</Parameter>
            <Parameter name="trigger_mode" type="str">Continuous</Parameter>
            <Parameter name="mvs_config_file" type="str" />
            <Parameter name="mvs_trigger_source" type="str">Software</Parameter>
            <Parameter name="stream_url" type="str">rtsp://192.168.1.64:554/ch1/main</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_light" tool_name="Intensity Measure" name="02_Brightness" category="Measurement" enabled="true">
          <Parameters>
            <Parameter name="roi" type="json">[0, 0, 0, 0]</Parameter>
            <Parameter name="min_mean" type="float">20.0</Parameter>
            <Parameter name="max_mean" type="float">240.0</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_smooth" tool_name="Image Filter" name="03_Smooth" category="Image Processing" enabled="true">
          <Parameters>
            <Parameter name="filter_type" type="str">Gaussian</Parameter>
            <Parameter name="kernel_size" type="int">5</Parameter>
            <Parameter name="sigma" type="float">1.5</Parameter>
            <Parameter name="edge_low" type="int">40</Parameter>
            <Parameter name="edge_high" type="int">120</Parameter>
            <Parameter name="roi" type="json">[0, 0, 0, 0]</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_bin" tool_name="Image Binarization" name="04_Binarize" category="Image Processing" enabled="true">
          <Parameters>
            <Parameter name="method" type="str">Otsu</Parameter>
            <Parameter name="threshold" type="int">128</Parameter>
            <Parameter name="invert" type="bool">false</Parameter>
            <Parameter name="adaptive_block_size" type="int">11</Parameter>
            <Parameter name="adaptive_c" type="int">2</Parameter>
            <Parameter name="low_threshold" type="int">100</Parameter>
            <Parameter name="high_threshold" type="int">255</Parameter>
            <Parameter name="kernel_width" type="int">15</Parameter>
            <Parameter name="kernel_height" type="int">15</Parameter>
            <Parameter name="gaussian_sigma" type="float">0.0</Parameter>
            <Parameter name="comparison" type="str">Greater or Equal</Parameter>
            <Parameter name="threshold_offset" type="float">0.0</Parameter>
            <Parameter name="roi" type="json">[0, 0, 0, 0]</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_blobs" tool_name="BLOB Analysis" name="05_BlobCount" category="Location" enabled="true">
          <Parameters>
            <Parameter name="roi" type="json">[0, 0, 0, 0]</Parameter>
            <Parameter name="threshold_mode" type="str">Single Threshold</Parameter>
            <Parameter name="threshold" type="int">128</Parameter>
            <Parameter name="high_threshold" type="int">255</Parameter>
            <Parameter name="invert" type="bool">false</Parameter>
            <Parameter name="min_area" type="int">500</Parameter>
            <Parameter name="max_area" type="int">50000</Parameter>
            <Parameter name="min_circularity" type="float">0.0</Parameter>
            <Parameter name="max_circularity" type="float">1.0</Parameter>
            <Parameter name="min_rectangularity" type="float">0.0</Parameter>
            <Parameter name="max_rectangularity" type="float">1.0</Parameter>
            <Parameter name="min_axis_ratio" type="float">0.0</Parameter>
            <Parameter name="max_axis_ratio" type="float">1.0</Parameter>
            <Parameter name="min_perimeter" type="int">0</Parameter>
            <Parameter name="max_perimeter" type="int">1000000</Parameter>
            <Parameter name="min_rect_width" type="int">0</Parameter>
            <Parameter name="max_rect_width" type="int">1000000</Parameter>
            <Parameter name="min_rect_height" type="int">0</Parameter>
            <Parameter name="max_rect_height" type="int">1000000</Parameter>
            <Parameter name="min_major_axis" type="int">0</Parameter>
            <Parameter name="max_major_axis" type="int">1000000</Parameter>
            <Parameter name="min_minor_axis" type="int">0</Parameter>
            <Parameter name="max_minor_axis" type="int">1000000</Parameter>
            <Parameter name="max_barycenter_offset" type="int">1000000</Parameter>
            <Parameter name="min_hole_area" type="int">0</Parameter>
            <Parameter name="max_blobs" type="int">500</Parameter>
            <Parameter name="connectivity" type="str">8-connected</Parameter>
            <Parameter name="sort_feature" type="str">Area</Parameter>
            <Parameter name="sort_type" type="str">No Sorting</Parameter>
            <Parameter name="contour_output" type="bool">false</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_classify" tool_name="Script" name="06_Classify" category="Logic Tools" enabled="true">
          <Parameters>
            <Parameter name="code" type="str"># CLASSIFY: sort every object by size and shape, draw a label on it, and reject odd ones.
# Image = the black/white picture from Image Binarization, Val1 = brightness of the camera picture.
mask = context.get("Image")
light = context.get("Val1", 128)
small_max = get_global("g_SmallMax", 2000)       # area (pixels) up to this is Small
large_min = get_global("g_LargeMin", 8000)       # area from this is Large
min_area = get_global("g_MinArea", 500)          # smaller specks are ignored
reject_long = get_global("g_RejectElongated", True)

if mask.ndim == 3:
    mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
_, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
h, w = mask.shape
contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

sizes = {"Small": 0, "Medium": 0, "Large": 0}
shapes = {"Round": 0, "Elongated": 0, "Odd": 0}
rejected = 0
for c in contours:
    area = cv2.contourArea(c)
    x, y, bw, bh = cv2.boundingRect(c)
    if area &lt; min_area or (bw &gt; 0.9 * w and bh &gt; 0.9 * h):    # a speck, or the background itself
        continue
    perimeter = cv2.arcLength(c, True)
    circularity = 4 * np.pi * area / (perimeter * perimeter) if perimeter else 0
    (_, _), (rw, rh), _ = cv2.minAreaRect(c)
    aspect = max(rw, rh) / max(1.0, min(rw, rh))

    size = "Small" if area &lt;= small_max else "Large" if area &gt;= large_min else "Medium"
    shape = "Round" if circularity &gt; 0.75 else "Elongated" if aspect &gt; 2.5 else "Odd"
    sizes[size] += 1
    shapes[shape] += 1

    bad = (shape == "Elongated" and reject_long) or size == "Large"
    rejected += bad
    colour = (60, 60, 255) if bad else (80, 220, 80)          # red = reject, green = fine
    overlays.append({"type": "rect", "box": (x, y, bw, bh), "color": colour,
                     "label": f"{size[0]}-{shape} {int(area)}"})

count = sum(sizes.values())
dark = light &lt; 40 or light &gt; 220
verdict = "OK" if (rejected == 0 and not dark) else "NG"
set_global("g_LastCount", count)
set_global("g_LastVerdict", verdict)
overlays.append({"type": "text", "pt": (10, 24), "color": (255, 200, 0),
                 "text": f"S{sizes['Small']} M{sizes['Medium']} L{sizes['Large']}   reject {rejected}"})
if dark:
    overlays.append({"type": "text", "pt": (10, 48), "color": (60, 60, 255), "text": f"lighting out of range ({light:.0f})"})
print(f"{count} objects  sizes={sizes}  shapes={shapes}  rejected={rejected}  brightness={light:.0f}")
outputs["Result"] = count
outputs["Status"] = verdict
</Parameter>
            <Parameter name="timeout_ms" type="int">5000</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_track" tool_name="Script" name="07_LotTracker" category="Logic Tools" enabled="true">
          <Parameters>
            <Parameter name="code" type="str"># LOT TRACKER: keeps a running tally in the global variables and watches for the count drifting.
# Val1 = object count from CLASSIFY, Val2 = object count from the BLOB Analysis module (a cross-check).
n = int(context.get("Val1") or 0)
blobs = int(context.get("Val2") or 0)
verdict = get_global("g_LastVerdict", "OK")

history = [int(v) for v in str(get_global("g_History", "")).split(",") if v.strip()]
earlier = history[-9:]
history = earlier + [n]
set_global("g_History", ",".join(str(v) for v in history))          # the last 10 counts, kept as text

set_global("g_Total", get_global("g_Total", 0) + 1)
key = "g_CountOK" if verdict == "OK" else "g_CountNG"
set_global(key, get_global(key, 0) + 1)

mean = sum(earlier) / len(earlier) if earlier else float(n)
drift = len(earlier) &gt;= 4 and abs(n - mean) &gt;= 2                   # needs a few pictures first
disagree = abs(n - blobs) &gt; 1                                       # the script and the module should agree

total = get_global("g_Total", 1)
yield_pct = 100.0 * get_global("g_CountOK", 0) / total
overlays.append({"type": "text", "pt": (10, 440), "color": (255, 255, 255),
                 "text": f"total {total}  OK {get_global('g_CountOK', 0)}  NG {get_global('g_CountNG', 0)}  yield {yield_pct:.0f}%"})
if drift:
    overlays.append({"type": "text", "pt": (10, 464), "color": (60, 60, 255),
                     "text": f"count drifted: {n} now, about {mean:.1f} before"})
if disagree:
    print(f"warning: script counted {n} but BLOB Analysis counted {blobs}")
print(f"cycle {total}: count {n}, average of the last {len(earlier)} = {mean:.1f}, yield {yield_pct:.0f}%")
outputs["Result"] = round(mean, 2)
outputs["Status"] = "OK" if (verdict == "OK" and not drift) else "NG"
</Parameter>
            <Parameter name="timeout_ms" type="int">5000</Parameter>
          </Parameters>
        </Node>
        <Node instance_id="node_check" tool_name="Condition Branch" name="08_Count_1_to_8" category="Logic Tools" enabled="true">
          <Parameters>
            <Parameter name="operator" type="str">Between</Parameter>
            <Parameter name="threshold_low" type="float">1.0</Parameter>
            <Parameter name="threshold_high" type="float">8.0</Parameter>
          </Parameters>
        </Node>
      </Nodes>
      <Connections>
        <Connection from_node="node_cam" from_port="Image" to_node="node_smooth" to_port="Image" />
        <Connection from_node="node_cam" from_port="Image" to_node="node_light" to_port="Image" />
        <Connection from_node="node_smooth" from_port="Image" to_node="node_bin" to_port="Image" />
        <Connection from_node="node_bin" from_port="Image" to_node="node_blobs" to_port="Image" />
        <Connection from_node="node_bin" from_port="Image" to_node="node_classify" to_port="Image" />
        <Connection from_node="node_light" from_port="Mean" to_node="node_classify" to_port="Val1" />
        <Connection from_node="node_cam" from_port="Image" to_node="node_track" to_port="Image" />
        <Connection from_node="node_classify" from_port="Result" to_node="node_track" to_port="Val1" />
        <Connection from_node="node_blobs" from_port="Count" to_node="node_track" to_port="Val2" />
        <Connection from_node="node_classify" from_port="Result" to_node="node_check" to_port="Val_In" />
      </Connections>
      <Layout>
        <Position node="node_cam" x="40.0" y="80.0" />
        <Position node="node_light" x="340.0" y="330.0" />
        <Position node="node_smooth" x="340.0" y="80.0" />
        <Position node="node_bin" x="640.0" y="80.0" />
        <Position node="node_blobs" x="940.0" y="330.0" />
        <Position node="node_classify" x="940.0" y="80.0" />
        <Position node="node_track" x="1240.0" y="80.0" />
        <Position node="node_check" x="1540.0" y="80.0" />
      </Layout>
    </ApexFlow>
  </Flows>
</ApexSolution>