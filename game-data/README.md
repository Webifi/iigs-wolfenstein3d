# Your DOS game files

Extract or install your copy of each game, then copy its actual DOS data files
into the matching folder. Each folder has a list of the required filenames.
Game files stay local and are ignored by Git; the folder guides ship with the
project. Leave folders for games you do not own empty.

```text
game-data/
  shareware/        Wolfenstein 3D shareware (.WL1)
  wolf3d/           Full Wolfenstein 3D (.WL6)
  spear/            Spear of Destiny (.SOD), or the combined mission set
  spear-mission2/   Return to Danger (.SD2)
  spear-mission3/   Ultimate Challenge (.SD3)
```

Missions 2 and 3 also use the five shared `.SOD` audio/graphics files listed in
their guides. Keep those in `spear/` or beside the mission files. A combined
Spear installation can stay together in `spear/`; all three campaigns will be
detected there. Mission copies installed with `.SOD` filenames may stay in
their own mission folders without renaming.

Files beside a mission take precedence for that mission. Missing shared files
come from the identified base Spear installation or a folder containing only
shared files. Conflicting base copies are reported. Files from separate Wolf
editions are kept together, so an incomplete edition cannot borrow another's
graphics or audio silently.

From the project root:

```sh
python3 build.py --all
python3 build.py --game wolf3d
python3 build.py --game spear --game spear-mission2 --game spear-mission3
```

On Windows, use `py -3` instead of `python3`. With no selection, `build.py`
processes every detected game, just like `--all`. Empty folders are skipped.
An incomplete set is reported with its missing files. Requesting an absent
game with `--game` is an error. Outputs are grouped under
`dist/output/<game>/`; different editions of one game get separate subfolders.
Identical copies are processed once.

`--data PATH` (or a positional input folder) and `--out PATH` override the
defaults. Folder names help organize files; identification uses the files'
contents. Source files are never renamed or changed.

This entry point accepts extracted game data. Extract archives and install
disk/CD distributions yourself before copying the resulting data files here.
The tool does not run DOS installers or import disk images.

**Current status:** `--inspect-only` validates these source sets now. Producing
game images still requires the pending current-engine adapter and complete
prepared resource bundles. See [build instructions](../docs/NATIVE_BUILD.md).
