# Spear of Destiny

Copy the extracted base-game data files here:

```text
AUDIOHED.SOD
AUDIOT.SOD
GAMEMAPS.SOD
MAPHEAD.SOD
VGADICT.SOD
VGAGRAPH.SOD
VGAHEAD.SOD
VSWAP.SOD
```

The five audio/graphics files are also used by missions 2 and 3. The builder
finds them here when mission maps and VSWAP files are in the neighboring
mission folders.

For a combined three-mission installation, keep its `.SOD`, `.SD2` and `.SD3`
files together here. All three missions are detected by `python3 build.py
--all`. Original names, including extra `.SD1` files, may be kept.

To select only the base campaign, run `python3 build.py --game spear` from
the project root. Use `py -3` on Windows. Add `--inspect-only` for source
validation. See the [input guide](../README.md) for current image-build
availability.

For native hard disk images, follow [Spear source builds](../../docs/SPEAR_BUILD.md).
