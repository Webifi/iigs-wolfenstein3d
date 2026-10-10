# Full Wolfenstein 3D

Copy the eight extracted data files from the same registered installation:

```text
AUDIOHED.WL6
AUDIOT.WL6
GAMEMAPS.WL6
MAPHEAD.WL6
VGADICT.WL6
VGAGRAPH.WL6
VGAHEAD.WL6
VSWAP.WL6
```

From the project root: `python3 build.py --game wolf3d`.
Use `py -3` on Windows. Add `--inspect-only` for source validation.
Recognized Apogee and GT editions may use separate subfolders here; keep each
installation's files together. See the [input guide](../README.md) for current
image-build availability.
