# DOS source profiles

These TOML files describe the source assets. They are ordinary UTF-8 text with
comments, named fields and lists. Python reads them directly; there is no
compiled configuration or executable code inside a profile.

| Profile | Source maps and VSWAP | Shared graphics and audio | Floors |
|---|---|---|---:|
| `shareware.toml` | `.WL1` | `.WL1` | 10 |
| `wolf3d.toml` | `.WL6` | `.WL6` | 60 |
| `spear.toml` | `.SOD` | `.SOD` | 21 |
| `spear-mission2.toml` | `.SD2` | `.SOD` from original Spear | 21 |
| `spear-mission3.toml` | `.SD3` | `.SOD` from original Spear | 21 |

The mission files retain their original names. The advanced `inspect` command
accepts `--shared-data` when Spear's common files live in another folder, and
requires an explicit profile when a directory contains several games.
`build.py` discovers games and shared Spear files within its input tree.
Conflicting copies of a required shared file cause an error.

The consumer entry point discovers every complete recognized campaign under
`game-data`, including shared Spear files and extracted combined installations.
The checked-in folders contain filename guides; actual game files and generated
outputs are local and Git-ignored. From the checkout root, run
`python3 build.py --inspect-only` (`py -3 build.py
--inspect-only` on Windows). Reports go to `dist/output/<game>`; positional input or
`--data` and `--out` override these locations. Defaults remain relative to the
project even when the command runs from another working directory. `--all` is
the default and skips empty folders. `--game wolf3d`, for example, selects only
that detected campaign; repeat `--game` to select several. Explicitly selected
missing games and incomplete data sets report errors.

`python3 tools/wolf_image.py discover --data game-data` produces a source
inventory without requiring a profile. `detection/layouts.toml` describes
installed filename layouts; `detection/editions.toml` supplies map/art hashes
to identify campaigns even when installers rename mission files to `.SOD`.
The decoder then checks every container. Matching file names or map counts
alone do not prove an official edition. Modified/unknown maps require an
explicit custom profile instead of silently receiving official routes.
The advanced `inspect` command still expects one selected campaign.

Users extract archives or install floppy/CD distributions themselves, then
supply the resulting DOS data files. The consumer entry point identifies
packages supplied without extracted data and explains this requirement.
It does not run installers or import disk images.

From the repository directory, on macOS or Linux:

```sh
python3 tools/wolf_image.py profiles
python3 tools/wolf_image.py inspect --profile wolf3d --data "/path/to/Wolf3D"
python3 tools/wolf_image.py inspect --profile spear-mission2 --data "/path/to/Mission2" --shared-data "/path/to/Spear"
```

On Windows use `py -3` in place of `python3`; quote paths containing spaces.
Python 3.9 or newer is supported. The bundled TOML reader supports 3.9/3.10;
Python 3.11 and newer use their standard library. These commands need no
assembler, emulator, DOS program, network access or extra package installation.

The inspection commands validate source assets. `build.py` generates native
shareware and full Wolf images using the checked engine bundle and prepared
audio inputs. Spear and both mission packs use the same source engine and
registered store recipe; see [Spear source builds](../docs/SPEAR_BUILD.md). See the
[build instructions](../docs/NATIVE_BUILD.md) for resource requirements and
[implementation status](../docs/REGISTERED_GAME.md) for runtime validation.

## Adapting a source

1. Copy the closest game profile and give it a distinct `id` and `title`.
2. Edit `[files]` to name the eight containers in your source folder. Names
   are case-insensitive; they do not include directory paths. Directories
   belong in command-line arguments, so a profile works on every host.
3. Set the map count and episode count. This decoder accepts 64×64 maps using
   Carmack/RLEW compression. Source object numbers remain 16-bit, including
   mutant placements above 255. Changing a profile cannot add new engine logic.
4. Describe each accepted graphics layout in `[[graphics.layouts]]`. A chunk
   is one entry in `VGAHEAD`; chunk numbers start at zero. `pictures` is the
   number of width/height pairs in chunk zero, `first_picture` is currently 3,
   and `tile8_count` describes the following unprefixed 8×8 tile chunk.
   `demo_count` recordings begin at `roles.demo_first`; the native Wolf loop
   requires four. Each recording keeps its source floor and input packets.
   Both chunk count and picture count must match one layout. Use descriptive
   names under `roles` for the relevant chunk numbers; these document the
   asset mapping and are validated even where native integration is unfinished.
5. Set the audio sound-bank count and IMF song count. `song_names` lists names
   in the source's music-ID order; `floor_songs` selects one name per map, and
   `[audio.events]` names the title/menu/ending selections. These also define
   required prepared-music coverage. The decoder checks the combined directory
   size and every offset. Do not alter counts merely to suppress a mismatch;
   inspect the source format first. These mappings do not add native game logic.
6. Leave `publication = "user-supplied"` for custom/full-game inputs. Shareware
   remains the public game-data build. This label is build metadata, not a
   grant of redistribution rights.
7. Run `inspect --profile "/path/to/my-profile.toml" --data ...`. Its JSON report
   lists every floor, object code, input hash and detected layout. Successful
   decoding does not establish that a custom actor or rule works in the engine.

`conversion` names a second TOML file, relative to the profile (or an absolute
path). Copy `conversion/stock.toml` alongside a custom profile to make an
independent quality preset. The supplied presets use the same quality settings.
Changing a filename/layout never selects a cheaper conversion algorithm.

## Campaign routes and resource requirements

Each source profile references `campaigns/*.toml` and a
`map-semantics/*.toml` catalog. These editable source files are separate from
local `game-data` payloads and `dist/output` reports/images.

Campaigns contain one `[[episodes]]`, `[[floors]]`, `[[routes]]` or `[[endings]]`
record at a time. IDs are stable keys; titles are display text. Source and
compiled floor indices start at zero. Displayed episode/floor numbers start
at one. `floor_id` identifies a map across reordered source and compiled
directories. The generated manifest explicitly maps the two directories.

Routes specify a source floor, named trigger and explicit destination. A
secret floor's ordinary elevator has a `normal_exit` route with its own return
destination. No destination is derived from ten-floor arithmetic or the
previous map. `show_tally` states whether a transition shows a tally;
`par_seconds` is an integer and appears only for `par_ratios` tallies.
Spear's `spear_pickup` route preserves player pose on arrival. A boss placement
is a resource reference, not an automatic ending. Unknown named behaviors and
explicit cross-episode routes become required native capabilities.

Map semantics retain all 16 bits of each source word. Named actor/resources
include dependencies such as dropped pickups, projectiles, explosions and
Mecha-Hitler's second form. `*-sprites.toml` maps source sprite names to VSWAP
indices; these numbers are not native frame offsets. Resource closure checks
every referenced source page. The report keeps unknown words and coordinates,
and reports native support, allocation and runtime verification separately.
Sound/state dispatch coverage and RAM fitting remain native integration work.

```sh
python3 tools/wolf_image.py inspect-campaign --profile wolf3d --data game-data/wolf3d --out dist/output/wolf3d/campaign.json
```

Optional `--native-capabilities PATH --require-supported` checks an
engine-owned TOML manifest and fails on missing behaviors, capacity limits or
unclassified words. The JSON report is still written on that failure. Source
decoding never authorizes truncation, dropping actors or changing palettes.
`save_content_sha256` hashes decoded map planes, stable gameplay IDs/rules and
semantic mappings. Pair it with the engine save ABI. Titles, physical media
placement and executable build IDs do not define save compatibility.

## Quality settings

`conversion/stock.toml` contains the existing conversion settings, now consumed
by `wolfpics.py`, `art_pages.py` and `build_colors.py`:

- `artwork`: color-distance metric and chroma weight. Alignment is a soft
  permutation of already-fitted colors, with matching pixel remapping. It
  cannot replace artwork colors with common grays or reserve extra gray slots.
- `page`: palette-search rounds/restarts and error diffusion. More search
  attempts cost build time. `dither_candidates` limits candidate shades;
  `dither_amount` controls diffusion strength. `flat_snap` keeps sufficiently
  flat source areas stable. These retain their previous numerical defaults.
- `hallway_title`: title-specific diffusion and weighted face rectangles.
  Coordinates are `[left, top, right, bottom, weight]`, with right/bottom
  excluded. These protected regions avoid diffusion. A different composition
  should use its own rectangles, not the hallway's face positions.
- `other_title`: the existing search/diffusion settings for other full pages.
- `world`: the four stored distance-light gains and color/error weights. Gains must
  increase and end at full light. This changes build-time fitting, not a live
  per-frame lighting calculation. `palette_fit_gains` selects the light samples
  used to fit each floor palette. Keeping those anchors while adding a stored
  intermediate light preserves the established color fit.
  `python3 tools/build_colors.py --remap-lights` regenerates the light mappings
  from already fitted palettes without replacing their colors or slot order.

All recognized settings are checked for type and range. Unknown fields are
errors, so a misspelled quality setting cannot be silently ignored. Keep a
before/after image and inspect it when tuning: a smaller numerical error alone
does not establish that the picture looks better.

Container/codec changes belong in the short Python modules `dos_data.py` and
`game_profile.py`. Sprite runs retain their original command order: the official
mission packs contain descending runs. Converters must not assume ascending
runs or discard a valid command. `check_dos_profiles.py` exercises custom
profiles and malformed inputs using synthetic data that can be shared publicly.

Prepared music is optional input to the inspector and selectable in the existing
shareware developer build. It requires no synthesizer installation; see
[audio inputs and pack manifests](../docs/AUDIO_INPUTS.md). `check_music_packs.py`
checks coverage, corrupted streams, memory limits and portable pack paths using
synthetic songs.
