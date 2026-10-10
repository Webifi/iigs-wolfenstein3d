# Building

Run the commands below from the project root. The build reads extracted DOS
data, converts the assets and music, assembles the engine, and packs bootable
images. It does not run the DOS game or its installer.

There are two ways to build:

- **Standard build.** Builds the game images from the original data and the
  audio intermediaries in `audio-source/`. It needs Python and Calypsi only.
  This is what most people want; the sections up to "Listening and preview
  pages" describe it.
- **Full build.** Also regenerates the audio intermediaries from scratch with
  a Roland SC-55 emulator and DOSBox-X. See [Full build](#full-build-regenerate-the-audio-intermediaries).

## Tools

| Tool | Version or requirement |
| --- | --- |
| Python | 3.9 or newer; 3.9/3.10 use the bundled Tomli 2.2.1 reader |
| Calypsi for 65816 | `as65816` and `ln65816` from [Calypsi](https://www.calypsi.cc); these builds use version 5.18 |
| NumPy | 1.24 or newer |
| Pillow | 9.1 or newer |
| Host C compiler | Optional C99 compiler for faster conversion; Python fallback is available |

Install the Python packages with:

```sh
python3 -m pip install -r requirements.txt
```

Pass the directory containing the Calypsi executables to `--calypsi`. The
source-build path invokes those tools directly; it does not require Make.
The examples use `python3` and a POSIX shell. The shared cache uses POSIX file
locking, so a native Windows build is not covered by these commands.

Ordinary builds use the prepared samples and editable recipes under
`audio-source/shareware/`, `audio-source/wolf3d/` and `audio-source/spear/`.
All three Spear missions use the Spear package. These folders need their
`intermediate.toml` and referenced resources. Rebuilding that material does
not require an external synthesizer. `--audio-source PATH` selects a different
prepared package.

## Original game data

The shareware data files are included in `game-data/shareware/`, so the
shareware edition builds without anything else. For the other editions, copy
the eight data files you own into the edition's folder:

| Selection | Folder | Extension |
| --- | --- | --- |
| `shareware` | `game-data/shareware/` | `.WL1` |
| `wolf3d` | `game-data/wolf3d/` | `.WL6` |
| `spear` | `game-data/spear/` | `.SOD` |

The eight stems are `MAPHEAD`, `GAMEMAPS`, `VSWAP`, `VGADICT`, `VGAHEAD`,
`VGAGRAPH`, `AUDIOHED` and `AUDIOT`.

For Return to Danger, put `MAPHEAD.SD2`, `GAMEMAPS.SD2` and `VSWAP.SD2` in
`game-data/spear-mission2/`. For Ultimate Challenge, put the corresponding
`.SD3` files in `game-data/spear-mission3/`. Both missions also need the five
shared `.SOD` graphics and audio files: `VGADICT`, `VGAHEAD`, `VGAGRAPH`,
`AUDIOHED` and `AUDIOT`. Keep those in `game-data/spear/` or beside each
mission's files.

A combined Spear installation may stay together in `game-data/spear/`.
Mission installations using `.SOD` filenames may stay in their own mission
folders without renaming. Discovery checks file contents; folder names do
not override the detected edition. Filenames are case-insensitive. Extract
archives and install DOS distributions before copying the resulting files.

Check the supplied games without building images:

```sh
python3 build.py --all --inspect-only
```

The result is `dist/output/build-report.json`, with a `campaign.json` for
each validated campaign. Empty folders are skipped; an incomplete set or an
explicitly requested but absent game is reported.

## Build hard disk images

Choose any of these commands, substituting your Calypsi directory. Every
source build needs Calypsi (`--from-source --calypsi`); the prebuilt engine
bundles are not included in the source tree.

```sh
python3 build.py --game shareware --from-source --calypsi /path/to/calypsi/bin
python3 build_wolf3d.py --from-source --calypsi /path/to/calypsi/bin
python3 build.py --game spear --from-source --calypsi /path/to/calypsi/bin
python3 build.py --game spear-mission2 --from-source --calypsi /path/to/calypsi/bin
python3 build.py --game spear-mission3 --from-source --calypsi /path/to/calypsi/bin
```

`build_wolf3d.py` supplies `--game wolf3d`; it uses the same builder.
`--all` builds every detected edition. `--data PATH` changes the input root
and `--out PATH` changes the output root. Explicit relative paths resolve
from the current directory; defaults resolve from the project directory.

Each edition writes `dist/output/<game>/wolf-hd.po`. Keep every `.po` volume
listed in its `native-build.json`; a second hard disk volume, when needed,
is named `wolf-hd2.po`. Add `--scsi` to create `wolf-scsi.hdv` and any numbered
companion volume with Apple partition maps.

A build also renders a music listening page (see below). Add
`--no-audio-preview` for a faster build without it.

The same output folder contains `build.log`, `native-build.json`,
`media-audio.json`, asset reports and `engine-bundle/`. The build report at
the output root records success or failure for every requested campaign.
`native-build.json` records the work directory, commands and image hashes.
The work directory holds `build/wolf.elf`, objects, generated files and assets.

## Build 800K floppy sets

All editions use the same engine recipe and select hard disk output by default.
For a shareware or registered floppy set, first build its store using the
floppy compression policy:

```sh
WOLF_STORE_MEDIUM=floppy python3 build.py --game shareware --from-source --calypsi /path/to/calypsi/bin --out dist/floppy-output
WOLF_STORE_MEDIUM=floppy python3 build_wolf3d.py --from-source --calypsi /path/to/calypsi/bin --out dist/floppy-output
```

Then pack the disks from that completed build:

```sh
python3 tools/pack_floppies.py dist/floppy-output/wolf3d
```

This writes `dist/floppy-output/wolf3d/floppies/disk1.po` and the remaining
disks. Use `dist/floppy-output/shareware` for shareware. `--out DIR` changes
the folder. The packer reuses the build's recorded work directory, so pack
before you delete it.

Floppy sets are made for shareware and registered Wolfenstein 3D. Spear of
Destiny and its missions are hard disk images only in this release.

The packer checks capacity and the floor routes, and fails if they cannot fit
within eight disks. Use the complete numbered set from one build. Disk 1 is
the boot disk; the home disk holds settings and saves. Do not combine disks
from separate builds.

## Run the images

The images boot on a real Apple IIgs (ROM 01 or ROM 3, 4 MB memory card) from
a hard disk device or an 800K drive, and in MAME. A MAME example for a ROM 01
machine with 4 MB plus its 256 KB:

```sh
mame apple2gsr1 -ramsize 4352K -sl7 cffa3000 -hard1 dist/output/wolf3d/wolf-hd.po
mame apple2gsr1 -ramsize 4352K -flop3 dist/floppy-output/wolf3d/floppies/disk1.po
```

MAME needs the Apple IIgs ROM files in its ROM path. With one floppy drive,
swap disks from MAME's media menu when the game asks for one.

## Build cache and clean rebuilds

Set a shared cache directory to reuse conversion results across builds:

```sh
export WOLF_SHARED_CACHE="$PWD/.build-cache"
export WOLF_JOBS=3
```

`WOLF_JOBS` limits build processes. `--audio-jobs N` sets the audio compiler
and music preview processes; it defaults to `WOLF_JOBS`, or to the detected CPU
count (at most 16). Without `WOLF_JOBS`, the builder uses the detected CPU count. The ordinary entry point creates a fresh `.build-*`
work directory inside each edition's output folder. The shared cache supplies
unchanged results to it. Step records, input hashes and output hashes are
checked before reuse.

For a cold rebuild, use a new output folder and disable both caches:

```sh
WOLF_SHARED_CACHE=0 WOLF_STEP_CACHE=0 WOLF_JOBS=3 python3 build_wolf3d.py --from-source --calypsi /path/to/calypsi/bin --out dist/cold-output
```

This repeats conversion, assembly and packing. Prepared audio samples and
recipes remain build inputs; a cold build does not recapture the synthesizer.
After keeping the images, reports and previews you need, completed work
directories can be removed. The shared cache can be removed when no build is
using it. See [cache details](docs/BUILD_CACHE.md).

## Listening and preview pages

Without renderer settings, a successful build creates a DOC listening page at
`dist/output/<game>/comparisons/preview/index.html`. It renders the compiled
music with the Python DOC model and checks its association with the packaged
game. `--no-audio-preview` skips these WAVs and marks the page unavailable;
audio conversion and packaged-audio checks still run. These are offline music
previews, not recordings of a running IIgs.

For Roland and AdLib references on the same page, provide the renderer
configuration with `--audio-preview-settings`. It uses the `[synthesis]` and
`[adlib]` settings from `profiles/audio/complete.example.toml`. This needs the
ordinary Nuked-SC55 renderer, its ROMs and DOSBox-X; it uses the prepared
arrangements without recapturing instrument samples. All five campaigns
use this preview path. Set `[comparison].jobs` in that configuration to
control reference rendering; it takes precedence over `--audio-jobs`.

```sh
python3 build.py --game spear --from-source --calypsi /path/to/calypsi/bin --audio-preview-settings /path/to/complete.toml
```

`WOLF_AUDIO_SETTINGS` supplies the same settings path when the option is
omitted. If neither is set, a `complete.toml` in the project root is used
when present. References are cached by song and renderer inputs under the
output root's `comparisons/` folder; changing the native work directory
alone does not require rerendering unchanged audio.

To rebuild only a prepared audio package:

```sh
python3 build.py --game wolf3d --audio-only --data game-data/wolf3d --bundle dist/output/wolf3d/engine-bundle --out dist/audio-wolf3d
```

This writes `dist/audio-wolf3d/audio/` and
`dist/audio-wolf3d/comparisons/preview/index.html`. A listening preview needs
a matching engine bundle; pass `--bundle dist/output/wolf3d/engine-bundle`
from a source build. Prebuilt engine bundles are not included in the source tree.
Add `--audio-song GETTHEM` to rebuild one required song. That command does
not produce game images.

## Full build: regenerate the audio intermediaries

The standard build never needs this. Use it to change an arrangement or to
recapture instrument samples. The `build_audio.py` entry point re-renders each
song on an emulated Roland SC-55, captures the instrument samples, renders the
AdLib original for comparison, rebuilds the intermediaries and makes the
AdLib/Roland/DOC comparison pages. The same workflow supports shareware,
registered Wolfenstein 3D and all three Spear missions. It also renders the
AdLib source effects with the bundled Nuked-OPL3 code; digitized effects come
from the selected mission's VSWAP.

### Tools

| Tool | Use | Source |
| --- | --- | --- |
| Nuked-SC55 headless renderer | Roland SC-55 renders | [jcmoyer/Nuked-SC55](https://github.com/jcmoyer/Nuked-SC55) |
| Track capture renderer | Complete-track instrument captures | Built from Nuked-SC55 with `tools/build_track_renderer.py`; see [the capture renderer instructions](tools/sc55/README.md) |
| DOSBox-X | AdLib reference renders | [dosbox-x.com](https://dosbox-x.com) |
| C++23 compiler (Clang or GCC), with a C compiler | Building the capture renderer and bundled OPL2 effect renderer | Your platform's toolchain |
| Calypsi | The game build inside this workflow | As above |

### Files you must supply

These are not part of this project.

- **Roland SC-55 firmware ROM set**, model mk1, revision 1.21. The renderer
  settings name it as `romset = "mk1-v1.21"`; the files go in the folder you set
  as `rom_directory`. Another revision gives different samples.
- **SC-55 SoundFont** `sc55_v12b.sf2`, SHA-256
  `e6c6f2d82ebd0c0fb4c2f4851ad34ca6a2a5988ad737c4922470c59822dbf520`. The
  workflow checks this hash.
- **The original DOS data** for each edition you rebuild (see "Original game
  data" above).
- **Apple IIgs system ROM** for MAME, only if you test the images in MAME.

### Settings and command

Copy `profiles/audio/complete.example.toml` and
`profiles/audio/renderer.example.toml` to local files and fill in the paths:
the renderer, the capture renderer, the ROM folder, the SoundFont, DOSBox-X,
and Calypsi. Effect samples are regenerated automatically; `effect_samples`
is no longer required. Set `CC` if your C compiler is not named `cc`. DOSBox-X
must have its executable SHA-256 pinned; pins for the Roland renderers are optional.

```sh
python3 build_audio.py --profile wolf3d --data game-data/wolf3d --settings /path/to/complete.toml --out dist/audio-comparison --jobs 3
```

Use `--profile shareware --data game-data/shareware` for shareware, or
`--profile spear --data game-data/spear` for Spear. Missions 2 and 3 use
`spear-mission2` and `spear-mission3`, with their own data folders containing
the shared `.SOD` audio/graphics files and the mission's maps and VSWAP.

Without `--recipes`, the build restores editable recipes into `OUT/recipes`
from the shipped score edits and the licensed AdLib sources. This preserves
Spear's selected instruments, capture settings and saved level calibration.
It regenerates samples with the configured rig; it does not reuse the shipped
capture WAVs or SoundFont sample extracts. Original complete MIDI files and
private preparation scripts are not needed. Existing editable recipes are
preserved. Pass `--recipes PATH` to use your edited recipes, or `--midi-dir PATH`
to generate arrangements from a supplied MIDI collection as before.

The page is `OUT/comparisons/preview/index.html`. `OUT/complete.json` records
the generated images and intermediary folder. Pass that folder to the standard
build with `--audio-source PATH`. Repeating the full build verifies its cached
inputs and outputs and regenerates only changed or missing stages. Complete
score files and full-track recordings stay in the developer output; only
source-relative score edits, settings and individual samples go into the
portable intermediary package.
