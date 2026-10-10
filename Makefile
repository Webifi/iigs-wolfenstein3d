CALYPSI ?=
AS := $(if $(CALYPSI),$(CALYPSI)/)as65816
LD := $(if $(CALYPSI),$(CALYPSI)/)ln65816
PYTHON := python3
GAME ?= shareware
DOS_DATA ?= game-data/shareware
DOS_SHARED_DATA ?=
AUTO_MUSIC := $(if $(filter undefined,$(origin MUSIC_PACK)),1,0)
MUSIC_PACK ?= build/audio/music
AUDIO_SOURCE ?= audio-source/$(GAME)
EFFECT_SAMPLES ?= $(AUDIO_SOURCE)/effects/ym3812
export WOLF_EFFECT_SAMPLES := $(EFFECT_SAMPLES)
WOLF_LINKER := src/iigs/wolf.scm
MEDIA_TARGET := build/wolf-hd.po
MEDIA_EXTRA := --hd-only --menu build/assets/menu-disk.bin
STORE_ADDRESS := VIRTUAL_STORE
MEDIA_CHECK := $(shell $(PYTHON) tools/check_media_outputs.py build/wolf-hd.po --make)
build/wolf-hd.po: $(MEDIA_CHECK)
export WOLF_PROFILE := $(GAME)
export WOLF_DOS_DATA := $(DOS_DATA)
export WOLF_SHARED_DATA := $(DOS_SHARED_DATA)
export WOLF_MUSIC_PACK := $(MUSIC_PACK)
PROFILE_FILES := tools/game_profile.py tools/dos_data.py tools/wolfdata.py $(wildcard profiles/*.toml profiles/*/*.toml)
.PHONY: check-source-profile
build/gen/campaign.inc: build/gen/source-profile.json tools/build_campaign.py
	$(PYTHON) tools/build_campaign.py
build/obj/%.o: build/gen/campaign.inc
build/obj/ui_overlays.o: build/gen/overlay_groups.inc
build/gen/overlay_groups.inc: build/gen/campaign.inc tools/registered_loads.py
	$(PYTHON) -c "import sys; sys.path.insert(0,'tools'); from registered_loads import include; include()"
build/assets/menu-stamp: build/gen/campaign.inc
.PHONY: force-boot-picture
build/assets/menu-stamp: force-boot-picture tools/make_boot_picture.py tools/memmap.py $(wildcard data/boot-picture*.png)
build/assets/sprite-stamp: build/sound/shared-stamp tools/registered_art.py tools/build_registered_sprites.py
build/assets/load-list.txt: build/assets/menu-cache-stamp build/assets/ui-words-stamp tools/registered_loads.py
build/assets/episode-stamp: build/assets/menu-cache-stamp build/gen/weapon_drawers.inc tools/registered_loads.py tools/build_registered_episode.py tools/shared_art.py tools/lz16.py tools/storage_codec.py profiles/storage/stock.toml
build/gen/weapon_drawers.inc: tools/registered_views.py
build/assets/ray-table-stamp: tools/registered_views.py

build/gen/source-profile.json: check-source-profile tools/prepare_profile.py tools/write_generated.py $(PROFILE_FILES)
	$(PYTHON) tools/prepare_profile.py
build/palettes/stamp build/assets/stamp build/assets/menu-stamp build/sound/stamp: build/gen/source-profile.json $(PROFILE_FILES)
.PHONY: check-audio-input
build/gen/audio-input.json: check-audio-input build/gen/source-profile.json tools/prepare_audio.py tools/music_pack.py
	$(PYTHON) tools/ensure_music.py --profile "$(GAME)" --data "$(DOS_DATA)" --source "$(AUDIO_SOURCE)" --out "$(MUSIC_PACK)" $(if $(filter 0,$(AUTO_MUSIC)),--import-only)
	$(PYTHON) tools/prepare_audio.py
build/sound/stamp: build/gen/audio-input.json tools/music_pack.py tools/effect_sources.py tools/effect_closure.py
build/gen/music_floors.inc: build/gen/audio-input.json
	$(PYTHON) tools/prepare_audio.py
build/obj/music_flow.o: build/gen/music_floors.inc
.PHONY: inspect-data
inspect-data:
	$(PYTHON) tools/wolf_image.py inspect --profile "$(GAME)" --data "$(DOS_DATA)" $(if $(DOS_SHARED_DATA),--shared-data "$(DOS_SHARED_DATA)")
ASFLAGS := --code-model=large --data-model=medium -I build/gen -I src/iigs
RAYS ?= sixteenth
FLOOR ?= 1
COLORS ?= four
PIXELS ?= pair
SHADING ?= 0
SCALER ?= rows
TICSTEP ?= 2
MAXTICS ?= 64
-include build/gen/tics-mode.mk
ifneq ($(BUILT_TICS),$(TICSTEP)-$(MAXTICS))
.PHONY: build/gen/tics.inc
endif
build/gen/tics.inc: Makefile tools/gen_tics.py tools/write_generated.py
	@mkdir -p build/gen
	@$(PYTHON) tools/gen_tics.py $(TICSTEP) $(MAXTICS)
build/obj/wolf.o build/obj/keys.o build/obj/tics.o build/obj/lplay.o: build/gen/tics.inc
-include build/gen/picture-config.mk
ifneq ($(BUILT_PICTURE),$(FLOOR)-$(COLORS)-$(PIXELS)-$(SHADING)-$(SCALER))
.PHONY: build/gen/picture_config.inc
endif
build/gen/picture_config.inc: Makefile tools/gen_config.py tools/write_generated.py
	@mkdir -p build/gen
	@$(PYTHON) tools/gen_config.py $(FLOOR) $(COLORS) $(PIXELS) $(SHADING) $(SCALER)
build/assets/stamp: build/gen/picture_config.inc build/palettes/stamp
build/palettes/stamp: tools/build_colors.py tools/wood_lighting.py tools/sourceview.py tools/native_map_format.py tools/viewcolor.py tools/gscolor.py $(wildcard $(DOS_DATA)/*.WL1)
	$(PYTHON) tools/build_colors.py
	touch $@
build/gen/scalers.s: build/gen/picture_config.inc
build/obj/wolf.o: build/gen/picture_config.inc
.DEFAULT_GOAL := all
ifeq ($(filter $(RAYS),half exact quarter eighth sixteenth),)
$(error RAYS must be half, exact, quarter, eighth or sixteenth)
endif
-include build/gen/ray-mode.mk
ifneq ($(BUILT_RAYS),$(RAYS))
.PHONY: build/gen/ray_mode.inc
endif

.PHONY: all assets disks
build/gen/ray_mode.inc: Makefile
	@mkdir -p build/gen
	@$(PYTHON) -c 'from pathlib import Path; Path("build/gen/ray_mode.inc").write_text("#define WOLF_EXACT_RAYS " + str(int("$(RAYS)" == "exact")) + "\n#define WOLF_QUARTER_RAYS " + str(int("$(RAYS)" in ("quarter","eighth","sixteenth"))) + "\n#define WOLF_RAY_STRIDE " + str(16 if "$(RAYS)" == "sixteenth" else 8 if "$(RAYS)" == "eighth" else 4) + "\n"); Path("build/gen/ray-mode.mk").write_text("BUILT_RAYS := $(RAYS)\n")'
build/obj/sound.o build/obj/music.o build/obj/music_flow.o build/obj/music_compact.o build/obj/music_blocks.o build/obj/audio_settings.o build/obj/audio_disk.o: build/sound/stamp
build/obj/wolf.o: build/gen/ray_mode.inc
build/gen/memmap.inc build/gen/memmap.scm: tools/memmap.py
	@mkdir -p build/gen
	@$(PYTHON) tools/memmap.py build/gen
build/obj/leveldirectory.o build/obj/ui_loading.o: build/gen/memmap.inc
build/obj/ui_loading.o: src/iigs/loading_sign.inc src/iigs/frontend.inc
all: disks
assets: build/assets/menu-stamp build/assets/episode-stamp build/assets/stamp build/assets/sprite-stamp build/assets/world-stamp build/assets/ui-stamp build/assets/weapon-mask.bin build/gen/scalers.s build/gen/views.inc build/assets/view-height.bin build/gen/shading.inc build/gen/tints.inc build/assets/load-list.txt
build/assets/ray-table-stamp: tools/gen_ray_tables.py tools/gen_ray_height.py tools/gen_ray_weights.py tools/viewgeometry.py tools/wolfsim.py tools/memmap.py
	$(PYTHON) tools/gen_ray_tables.py
	$(PYTHON) tools/gen_ray_height.py
	touch $@
build/assets/weapon-mask.bin: build/assets/sprite-stamp build/gen/scalers.s tools/build_weapon_masks.py tools/viewgeometry.py
	$(PYTHON) tools/build_weapon_masks.py
build/gen/weapon_drawers.inc: build/assets/weapon-mask.bin build/assets/menu-stamp tools/build_weapon_drawers.py
	$(PYTHON) tools/build_weapon_drawers.py
build/obj/wolf.o: build/gen/weapon_drawers.inc
build/assets/stamp: tools/shared_gray.py tools/memmap.py tools/native_map_format.py tools/build_assets.py tools/wolfdata.py tools/wolf_source.py tools/wolfcolor.py tools/buildconfig.py tools/assetspace.py $(wildcard $(DOS_DATA)/*.WL1)
	$(PYTHON) tools/build_assets.py
	touch $@
build/assets/world-stamp: build/assets/stamp tools/build_world.py tools/wolf_source.py
	$(PYTHON) tools/build_world.py
	touch $@
build/assets/logic-stamp: build/assets/world-stamp tools/build_logic.py tools/native_actors.py tools/native_map_format.py tools/line_regions.py tools/wolfsim.py tools/build_demos.py
	$(PYTHON) tools/build_logic.py
	$(PYTHON) tools/build_demos.py
	touch $@
build/assets/episode-stamp: build/boot/fixed_gen.raw build/boot/weapon_comp.raw build/boot/sight_gen.raw build/sound/stamp build/assets/stamp build/assets/world-stamp build/assets/logic-stamp build/assets/sprite-stamp build/wolf.elf tools/build_episode.py tools/episode_directory.py tools/b1.py tools/build_floor_previews.py tools/frontend/floor_previews.py tools/frontend/preview_art.py
	$(PYTHON) tools/build_floor_previews.py
	$(PYTHON) tools/build_episode.py
	touch $@
build/assets/sprite-stamp: build/assets/stamp build/gen/scalers.s tools/build_sprites.py tools/sprite_banks.py tools/pool_cover.py tools/build_colors.py tools/check_art_coverage.py tools/wolf_source.py tools/wolfcolor.py tools/assetspace.py
	$(PYTHON) tools/build_sprites.py
	$(PYTHON) tools/check_art_coverage.py > build/art-coverage.log
	touch $@
build/obj/debug.o build/obj/debug_aux.o: build/assets/ui-stamp

build/assets/ui-stamp: build/assets/stamp tools/build_ui.py tools/art_status.py tools/shared_gray.py tools/wolfpics.py tools/gscolor.py
	$(PYTHON) tools/build_ui.py
	touch $@
UI_DEFS := $(if $(wildcard src/iigs/sound.s),-D UI_SOUND=1,-D UI_SOUND=0) $(if $(wildcard src/iigs/lglue.s),-D UI_DEMOS=1 -D UI_LOGIC=1,-D UI_DEMOS=0 -D UI_LOGIC=0)
build/obj/ui_sound.o build/obj/ui_hooks.o build/obj/ui_demo.o build/obj/ui_save.o: build/obj/%.o: src/iigs/%.s $(wildcard src/iigs/*.inc) build/assets/menu-stamp build/assets/logic-stamp Makefile $(wildcard src/iigs/sound.s)
	mkdir -p build/obj
	$(AS) $(ASFLAGS) $(UI_DEFS) -o $@ $<
build/assets/menu-cache-stamp: build/assets/menu-stamp build/sound/stamp tools/build_menu_cache.py tools/frontend/native_assets.py tools/b1.py
	$(PYTHON) tools/build_menu_cache.py
	touch $@
build/obj/ui_cache.o: build/assets/menu-cache-stamp
build/assets/menu-stamp: build/gen/tints.inc build/palettes/stamp build/assets/stamp tools/build_menu.py tools/endtext.py tools/fade_palette.py tools/build_frontend.py tools/psyched_picture.py tools/frontend/titlecolor.py tools/attract_assets.py tools/shared_gray.py tools/frontend/build_words.py tools/frontend/gray_catalog.py tools/frontend/gray_pair.py tools/frontend/episode_previews.py tools/frontend/preview_art.py tools/frontend/gray_local.py $(wildcard data/frontend-previews/*) $(wildcard tools/frontend/lettering/*.py tools/frontend/lettering/*.swift tools/frontend/lettering/fonts/*.ttf) tools/page_text.py tools/bench_route.py tools/gscolor.py tools/viewcolor.py tools/art_pages.py tools/art_lumps.py tools/wolfpics.py
	$(PYTHON) tools/build_menu.py
	touch $@
$(patsubst %,build/obj/%.o,ui_main ui_draw ui_dim ui_dimstub ui_palette ui_numbers ui_disk ui_data ui_bridge ui_hooks ui_save ui_write ui_options ui_controls ui_bench ui_title ui_demo ui_scores ui_quit ui_quitrom viewdef ui_loading): build/assets/menu-stamp
build/gen/shading.inc: build/assets/stamp tools/gen_shading.py
	$(PYTHON) tools/gen_shading.py
build/gen/tints.inc: build/assets/stamp build/assets/ui-stamp tools/gen_tints.py
	$(PYTHON) tools/gen_tints.py
build/obj/flash.o: build/gen/tints.inc
build/assets/load-list.txt: build/assets/stamp build/assets/sprite-stamp build/assets/weapon-mask.bin build/gen/weapon_drawers.inc build/gen/scalers.s build/gen/shading.inc build/gen/tints.inc build/assets/ray-table-stamp build/sound/stamp build/assets/menu-stamp tools/build_loads.py
	$(PYTHON) tools/build_loads.py
build/gen/scalers.s: tools/gen_scalers.py tools/pool_cover.py tools/viewgeometry.py
	$(PYTHON) tools/gen_scalers.py
build/gen/views.inc: tools/gen_views.py tools/viewgeometry.py build/assets/stamp
	$(PYTHON) tools/gen_views.py
build/assets/view-height.bin: build/gen/views.inc
	$(PYTHON) tools/gen_views.py
build/assets/mouse.bin: tools/gen_controls.py
	$(PYTHON) tools/gen_controls.py
build/gen/death.inc: tools/gen_death.py
	$(PYTHON) tools/gen_death.py
build/gen/loader_api.inc: build/boot/loader.raw tools/gen_loader_api.py
	$(PYTHON) tools/gen_loader_api.py
build/obj/levelio.o: build/gen/loader_api.inc
build/obj/level.o: build/gen/death.inc
build/assets/ui-words-stamp: build/assets/menu-cache-stamp tools/frontend/build_words.py tools/frontend/gray_curve.py $(wildcard src/iigs/ui_*.s) build/assets/menu-stamp
	$(PYTHON) tools/frontend/build_words.py
	touch $@
build/obj/ui_words.o: build/assets/ui-words-stamp
build/obj/ui_gray.o build/obj/ui_dim.o: build/assets/menu-stamp
build/obj/ui_slotmeta.o build/obj/ui_extra.o: build/assets/menu-stamp
build/obj/ending.o: build/assets/menu-cache-stamp
build/obj/victory.o build/obj/tally.o build/obj/tally_art.o: build/assets/menu-stamp
build/obj/sprites.o: build/assets/weapon-mask.bin
build/obj/%.o: src/iigs/%.s $(wildcard src/iigs/*.inc) build/assets/stamp build/assets/sprite-stamp build/assets/world-stamp build/assets/logic-stamp build/assets/ui-stamp build/gen/scalers.s build/gen/views.inc build/gen/shading.inc
	mkdir -p build/obj
	$(AS) $(ASFLAGS) -o $@ $<
build/obj/scalers.o: build/gen/scalers.s
	mkdir -p build/obj
	$(AS) $(ASFLAGS) -o $@ $<
build/gen/ray_programs.s: tools/gen_ray_programs.py tools/viewgeometry.py src/iigs/ray_program.inc build/gen/ray_mode.inc build/gen/picture_config.inc
	$(PYTHON) tools/gen_ray_programs.py
build/obj/ray_programs.o: build/gen/ray_programs.s
	mkdir -p build/obj
	$(AS) $(ASFLAGS) -o $@ $<
build/wolf.elf: build/obj/wolf.o build/obj/tics.o build/obj/ray_programs.o build/obj/raypages.o build/obj/ui_death.o build/obj/doc.o build/obj/sound.o build/obj/sound_cache.o build/obj/music.o build/obj/music_flow.o build/obj/music_compact.o build/obj/music_blocks.o build/obj/audio_settings.o build/obj/audio_disk.o build/obj/scalers.o build/obj/sprites.o build/obj/hud.o build/obj/level.o build/obj/keys.o build/obj/mouse.o build/obj/j13.o build/obj/cpu_info.o build/obj/irq.o build/obj/truepixels.o build/obj/flash.o build/obj/lglue.o build/obj/lplay.o build/obj/lagent.o build/obj/lact.o build/obj/lsight.o build/obj/lsetup.o build/obj/lregistered.o build/obj/lboss.o build/obj/lprojectile.o build/obj/ldeathcam.o build/obj/ui_deathcam.o build/obj/ui_bossnotice.o build/obj/ui_overlays.o build/obj/levelio.o build/obj/ui_main.o build/obj/ui_draw.o build/obj/ui_update.o build/obj/ui_rowcache.o build/obj/ui_dim.o build/obj/ui_gray.o build/obj/ui_dimstub.o build/obj/ui_palette.o build/obj/ui_numbers.o build/obj/ui_disk.o build/obj/ui_cache.o build/obj/ui_data.o build/obj/ui_bridge.o build/obj/ui_hooks.o build/obj/ui_save.o build/obj/ui_nameedit.o build/obj/ui_write.o build/obj/ui_sound.o build/obj/ui_options.o build/obj/ui_controls.o build/obj/ui_bench.o build/obj/ui_benchmath.o build/obj/ui_title.o build/obj/ui_attract.o build/obj/ui_attract_data.o build/obj/ui_demo.o build/obj/ui_scores.o build/obj/ui_quit.o build/obj/ui_quitrom.o build/obj/flow.o build/obj/continue.o build/obj/tally.o build/obj/tally_art.o build/obj/victory.o build/obj/ending.o build/obj/gamesave.o build/obj/gamesave_menu.o build/obj/ui_words.o build/obj/ui_steel.o build/obj/ui_frontend.o build/obj/ui_slotmeta.o build/obj/ui_extra.o build/obj/ui_progress.o build/obj/ui_lettering.o build/obj/viewdef.o build/obj/lights.o build/obj/leveldirectory.o build/obj/ui_loading.o build/obj/debug.o build/obj/debug_aux.o build/obj/debug_logic.o $(WOLF_LINKER)
	$(LD) -o $@ $(WOLF_LINKER) build/obj/wolf.o build/obj/tics.o build/obj/ray_programs.o build/obj/raypages.o build/obj/ui_death.o build/obj/doc.o build/obj/sound.o build/obj/sound_cache.o build/obj/music.o build/obj/music_flow.o build/obj/music_compact.o build/obj/music_blocks.o build/obj/audio_settings.o build/obj/audio_disk.o build/obj/scalers.o build/obj/sprites.o build/obj/hud.o build/obj/level.o build/obj/keys.o build/obj/mouse.o build/obj/j13.o build/obj/cpu_info.o build/obj/irq.o build/obj/truepixels.o build/obj/flash.o build/obj/lglue.o build/obj/lplay.o build/obj/lagent.o build/obj/lact.o build/obj/lsight.o build/obj/lsetup.o build/obj/lregistered.o build/obj/lboss.o build/obj/lprojectile.o build/obj/ldeathcam.o build/obj/ui_deathcam.o build/obj/ui_bossnotice.o build/obj/ui_overlays.o build/obj/levelio.o build/obj/ui_main.o build/obj/ui_draw.o build/obj/ui_update.o build/obj/ui_rowcache.o build/obj/ui_dim.o build/obj/ui_gray.o build/obj/ui_dimstub.o build/obj/ui_palette.o build/obj/ui_numbers.o build/obj/ui_disk.o build/obj/ui_cache.o build/obj/ui_data.o build/obj/ui_bridge.o build/obj/ui_hooks.o build/obj/ui_save.o build/obj/ui_nameedit.o build/obj/ui_write.o build/obj/ui_sound.o build/obj/ui_options.o build/obj/ui_controls.o build/obj/ui_bench.o build/obj/ui_benchmath.o build/obj/ui_title.o build/obj/ui_attract.o build/obj/ui_attract_data.o build/obj/ui_demo.o build/obj/ui_scores.o build/obj/ui_quit.o build/obj/ui_quitrom.o build/obj/flow.o build/obj/continue.o build/obj/tally.o build/obj/tally_art.o build/obj/victory.o build/obj/ending.o build/obj/gamesave.o build/obj/gamesave_menu.o build/obj/ui_words.o build/obj/ui_steel.o build/obj/ui_frontend.o build/obj/ui_slotmeta.o build/obj/ui_extra.o build/obj/ui_progress.o build/obj/ui_lettering.o build/obj/viewdef.o build/obj/lights.o build/obj/leveldirectory.o build/obj/ui_loading.o build/obj/debug.o build/obj/debug_aux.o build/obj/debug_logic.o --hosted --list-file build/wolf.lst
build/boot/boot.raw: src/iigs/boot.s src/iigs/boot.scm build/gen/memmap.inc build/gen/memmap.scm
	mkdir -p build/boot
	$(AS) -I build/gen -o build/boot/boot.o src/iigs/boot.s
	$(LD) -o build/boot/boot.elf src/iigs/boot.scm build/boot/boot.o --output-format raw
build/boot/loader.raw: src/iigs/loader.s src/iigs/loader.scm src/iigs/loadbar.inc src/iigs/loader_copy.inc src/iigs/bootbar_font.inc build/assets/stamp
	mkdir -p build/boot
	$(AS) $(ASFLAGS) -o build/boot/loader.o src/iigs/loader.s
	$(LD) -o build/boot/loader.elf src/iigs/loader.scm build/boot/loader.o --output-format raw
disks: $(MEDIA_TARGET)
	$(PYTHON) tools/check_media_audio.py build/wolf-hd.po --out build/media-audio.json
$(MEDIA_TARGET): build/assets/menu-cache-stamp build/assets/menu-stamp build/assets/logic-stamp build/assets/load-list.txt build/assets/episode-stamp build/assets/weapon-mask.bin build/assets/view-height.bin build/wolf.elf build/boot/boot.raw build/boot/loader.raw build/assets/stamp build/sound/stamp tools/mkdisk.py tools/check_depth_memory.py tools/memmap.py
	$(PYTHON) tools/check_depth_memory.py
	$(PYTHON) tools/mkdisk.py --boot build/boot/boot.raw --loader build/boot/loader.raw --elf build/wolf.elf --entry SEG_CODE --data build/assets/ui.bin@UI --data build/assets/view-height.bin@VIEW_HEIGHT --data build/assets/weapon-mask.bin@WEAPON_RUNS --data build/assets/map.bin@MAP --data build/assets/clips.bin@CLIPS --data-list build/assets/load-list.txt --data build/assets/tables.bin@TABLES --data build/assets/logic.bin@LOGIC_BASE --data build/assets/demos.bin@DEMOS --data-list build/assets/menu-boot-loads.txt --data-list build/assets/ui-word-loads.txt --data-list build/assets/root-loads.txt --picture-file build/assets/boot-shared.shr@MENU_CACHE_0 --compress --b1cache build/b1cache --store build/assets/episode.bin@$(STORE_ADDRESS) --hd build/wolf-hd.po $(MEDIA_EXTRA) --out build/disk

build/sound/stamp: $(wildcard $(MUSIC_PACK)/* $(EFFECT_SAMPLES)/*) data/sound/levels.json tools/build_sound.py tools/effect_size.py tools/wolfsim.py tools/doc_song.py tools/wolfaudio.py tools/adlib_render.py $(wildcard $(DOS_DATA)/*) $(if $(DOS_SHARED_DATA),$(wildcard $(DOS_SHARED_DATA)/*))
	$(PYTHON) tools/build_sound.py $(if $(EFFECT_SAMPLES),--effect-samples "$(EFFECT_SAMPLES)")
	touch $@

build/obj/gamesave.o: build/assets/logic-stamp build/assets/menu-stamp
build/obj/ui_words.o build/obj/ui_steel.o build/obj/ui_frontend.o build/obj/ui_slotmeta.o build/obj/ui_extra.o build/obj/ui_progress.o build/obj/ui_lettering.o: build/assets/menu-stamp

build/gen/mouse.inc: tools/gen_mouse.py
	$(PYTHON) tools/gen_mouse.py
build/obj/mouse.o: build/gen/mouse.inc

# Sight proofs are generated with the floor loads and share their restore lifetime.
build/obj/lsight.o: src/iigs/line_proofs.inc
build/assets/load-list.txt build/assets/episode-stamp: tools/line_proofs.py

build/sound/shared-stamp: build/sound/stamp tools/share_effects.py
	$(PYTHON) tools/share_effects.py
	touch $@

build/boot/%.raw: src/iigs/%.s src/iigs/%.scm build/gen/memmap.inc build/gen/memmap.scm
	mkdir -p build/boot
	$(AS) $(ASFLAGS) -o build/boot/$*.o src/iigs/$*.s
	$(LD) -o $@ src/iigs/$*.scm build/boot/$*.o --output-format raw

build/assets/menu-stamp: $(wildcard data/frontend-lettering/*.json)
