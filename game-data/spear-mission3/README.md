# Spear mission 3: Ultimate Challenge

Copy these extracted mission files here:

```text
GAMEMAPS.SD3
MAPHEAD.SD3
VSWAP.SD3
```

Also supply `AUDIOHED.SOD`, `AUDIOT.SOD`, `VGADICT.SOD`, `VGAGRAPH.SOD` and
`VGAHEAD.SOD` from the matching Spear installation. They may stay in `../spear/`
or be copied alongside these files.

If your installed mission uses `.SOD` names for its maps and VSWAP, keep that
complete set together here. The mission is identified from its contents;
renaming is unnecessary. Combined installations may instead remain together
in `../spear/`.

From the project root: `python3 build.py --game spear-mission3`.
Use `py -3` on Windows. Add `--inspect-only` for source validation.
See the [input guide](../README.md) for current image-build availability.
