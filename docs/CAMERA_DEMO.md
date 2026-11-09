# Webcam demo flow

A four-module flow that reads a live webcam, checks that the picture is neither too dark nor blown out, and counts bright
objects (a lamp, a sheet of white paper, a screen).

```text
Webcam Image Source ─┬─▶ Intensity Measure   (FAIL if mean brightness < 25 or > 235)
                     └─▶ Image Filter (Gaussian 5) ─▶ BLOB Analysis (threshold 200, min area 400)
```

## Build it

1. **New Project**, then drag an **Image Source** onto the canvas. Set **Source type** to **Camera** and **Camera device**
   to `webcam_0` (try `webcam_1` if you have several cameras).
2. Add **Intensity Measure** and link `Image` from the source. Set *min_mean* 25 and *max_mean* 235.
3. Add **Image Filter** (filter type *Gaussian*, kernel size 5) and link `Image` from the source.
4. Add **BLOB Analysis**, link the filter's `Image`, and set *threshold* 200 and *min_area* 400.
5. Press **Run**. Press it again to grab a new frame.

Use the **Result** tab above the image for a one-line summary of every module, and **History** for one line per run.

## What to expect

- A normal room gives **PASS**: brightness is inside the limits and the blob count is the number of bright objects.
- Covering the lens gives **FAIL** at the brightness module (mean below 25). This is the expected behaviour, not an error.
- The first frames from a webcam are often dark while auto-exposure settles; run twice.
- If the camera does not open, close other programs using it and check Windows camera privacy. See the
  [User guide](USER_GUIDE.md#5-using-a-camera).

## Run it headless

Because the flow uses the camera as its own image source, you can run it from a script or call it through the
[HTTP API](API.md) with no image attached: the server then uses the flow's own Image Source (the webcam).
