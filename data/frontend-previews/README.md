# Menu pictures

Every source build renders a start view for every floor of the selected campaign with the linked 65816 engine. `tools/build_floor_previews.py` runs floor setup, visibility, wall casting, sprite projection and painting in `emu816`. It uses the campaign's converted assets, medium difficulty and view 214. It omits the weapon and HUD. No MAME installation or ROM is needed.

The 214 by 107 RGB12 captures become 106 by 53 menu pictures. Area averaging combines the native color pairs before fitting two menu palettes; the preview fit adds no dither. Each floor and difficulty picture has a 4096-byte slot, including its two gray-conversion records, in the title-only `FLOOR_PREVIEWS` art overlay. The title loads the pool from the home disk. Selection changes read no disk. Floor loading restores the art covered by the pool; the in-game pause does not use it.

`shareware/floor-*.json` contains redistributable engine captures with source and renderer hashes. The build uses a capture only when its inputs match; otherwise it renders it again. To refresh these assets after a shareware source build, run `python3 tools/build_floor_previews.py --export-shareware` in the build stage. Registered and Spear captures stay under ignored `build/assets/floor-previews/` and are generated from the owner's data. The export option rejects those profiles.

Difficulty portraits come from the selected graphics layout's `difficulty_first` role in the original VGAGRAPH data. The converter removes only the connected backdrop and scales each face to 36 by 48. Episode illustrations retain their original 48 by 24 packed pixels and draw at 96 by 48. Palette rows double with the pixels, so enlarging an episode illustration adds no image bytes.

The runtime pictures share black and the backdrop shades $333, $222 and $111 at aligned slots 0, 13, 14 and 15. Composition keeps those indices in the gray background. It builds the complete changed rectangle in the menu frame, then publishes its pixels with the matching palettes and scan-line selectors. `tools/frontend/check_preview_records.py` checks every floor, face and episode picture through the linked compositor, including intermediate screen writes and background preservation.

The older `floor-*.bin`, `difficulty-*.bin` and `source/` captures are not inputs to the New Game pictures. `difficulty-title.json` and `floors-title.json` provide the menu heading ink. Font A is Black Ops One; its OFL notices are under `tools/frontend/lettering/` and `fonts/`.
