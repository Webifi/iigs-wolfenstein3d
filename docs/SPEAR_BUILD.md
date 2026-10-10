# Spear hard disk builds

All three Spear missions use the shared Wolf engine and registered store recipe.
Each image targets a stock ROM01 Apple IIgs at 2.8 MHz with a 4 MiB expansion
(4352 KiB total). No accelerator is required.

Copy the original DOS files into the [game-data folders](../game-data/README.md).
Missions 2 and 3 use their own MAPHEAD, GAMEMAPS and VSWAP files, plus the five
shared `.SOD` graphics and audio files. The prepared audio package belongs in
`audio-source/spear/`; it contains editable recipes and samples, not native banks.
The build checks the original music and effect hashes before converting them.

With Python 3.9 or newer and the Calypsi 65816 tools already installed:

```sh
python3 build.py --game spear --from-source --calypsi /path/to/calypsi/bin
python3 build.py --game spear-mission2 --from-source --calypsi /path/to/calypsi/bin
python3 build.py --game spear-mission3 --from-source --calypsi /path/to/calypsi/bin
```

On Windows use `py -3` instead of `python3`. Quote paths containing spaces.
`--data` and `--out` override the input and output folders. Each campaign writes
`dist/output/<game>/wolf-hd.po`. `--no-audio-preview` skips listening WAVs while
retaining music conversion and byte checks. MAME is used for runtime testing;
it is not needed to build the images.

The native profiles choose `data/boot-picture-spear.png`,
`data/boot-picture-spear-mission2.png`, and
`data/boot-picture-spear-mission3.png`. The build dithers the selected PNG.
The title and ending pictures come from the licensed graphics files.

Spear has a 21-floor menu, both secret-floor routes, the Spear pickup and final
floor transition, its bosses and projectiles, spectre revival, ten ending pages,
and a larger save format for all 14 ratio records. Each mission keeps its own
hard disk image and save files. Spear wall rendering shares the two most distant
light bands to fit its larger art set in stock memory; actor light bands and
Wolf rendering are unchanged.

Mission 3 contains editor data in sealed map cells. Source words are preserved.
The importer rejects these cells if they contain objects or become reachable
from a player or actor start through open space, doors or pushwalls.
