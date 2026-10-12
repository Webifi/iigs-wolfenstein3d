;;; Cold asset transitions. No entry point belongs in the normal frame loop.
#include "memmap.inc"
#include "logic.inc"
#include "overlay_groups.inc"
#include "campaign.inc"
#include "gray.inc"
#include "frontend.inc"
              .section registeredmenu, text, root, noreorder
              .public BuildRayPartial
;;; Boot: the ray partial rows ($34:0000, tools/gen_ray_tables.py), built
;;; instead of loaded. Row k at $34:0000 + 512k holds (step * f) >> 8 for
;;; f = 0..255: per word, add the step's high byte and the carry of its
;;; low byte into the fraction. Then the other boot tables (boot_tables.inc).
;;; JSL; registers kept.
BuildRayPartial:
              php
              rep #0x30
              phb
              phk
              plb
              phx
              phy
              pha
              ldy ##0                     ; 2 * row
rpRow:        cpy ##RAY_PARTIAL_ROWS*2
              bcs rpDone
              tya
              xba
              and ##255
              clc
              adc ##0x34                  ; rows 128 and up are in bank $35
              sep #0x20
              sta abs:.word0 (rpStore+3)
              rep #0x20
              tya
              and ##0xfe
              xba
              tax                         ; (row & 127) * 512
              lda abs:.word0 (rayPartialSteps),y
              xba
              and ##0xff00
              sta abs:.word0 (rpLow)      ; the low byte, as a fraction
              lda abs:.word0 (rayPartialSteps),y
              xba
              and ##255
              sta abs:.word0 (rpHigh)
              stz abs:.word0 (rpFraction)
              phy
              ldy ##256
              lda ##0
rpStore:      sta long:RAY_PARTIAL,x
              inx
              inx
              pha
              lda abs:.word0 (rpFraction)
              clc
              adc abs:.word0 (rpLow)
              sta abs:.word0 (rpFraction)
              pla
              adc abs:.word0 (rpHigh)
              dey
              bne rpStore
              ply
              iny
              iny
              bra rpRow
rpDone:       jsr abs:.word0 (BuildBootTables)
              pla
              ply
              plx
              plb
              plp
              rtl
#include "ray_partial.inc"
rpLow:        .word 0
rpHigh:       .word 0
rpFraction:   .word 0
#include "boot_tables.inc"

              .public EnsureUIAssets, EnsureGameplayAssets, EnsureViewAssets
              .public OverlayTitleClobbered
              .public RestoreTitleArt
              .public OverlayFloorChanging, OverlayB1Clobbered
              .public LoadDemoAssets, ProbeDemoAssets
              .public overlayUICold, overlayGameCold, overlayWeightView, overlayWeaponKey
              .public overlayFailedGroup, OverlayHalted
              .public PauseModeSet, PauseDimOpen, PauseClose, PauseLump, PauseWords
              .public PlayCacheFill, PlayCacheLeave, LoadTallyAssets
              .public pauseMode, snapTaken, pauseWordsHere
              .extern LoadAuxData, ProbeFloorData, UiFwKeep, levelIndex, weaponViewIndex
              .extern uiGameOn, floorReady, nativeRecord, nativeBank, wordDirectory
              .extern PlayGrayTables, GraySnapBank
              .extern playValid, homeDisk
              .extern PrepareMusic, floorSong

;;; Public entries preserve A/X/Y, DBR, D and P, except ProbeDemoAssets
;;; returns availability in carry (clear when present). Native mode only.
OVERLAY_ENTER .macro
              php
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              cld
              .endm
OVERLAY_LEAVE .macro
              pld
              plb
              ply
              plx
              pla
              plp
              rtl
              .endm

;;; The boot loads no UI payload: the first call (MenuBoot) reads the UI group
;;; from the store on disk 1. A cold restore must finish before a snapshot is
;;; captured; repeated calls inside a menu perform no disk I/O.
;;; Slow word/lettering payloads and their linked directories stay resident.
;;; The in-game pause loads nothing here (PauseLump). Elsewhere the UI group,
;;; the colour snapshot and the menu stages cover art RAM. A hard disk store
;;; has exact restores for that art; its floor stays resident with floorReady 2.
;;; Other stores discard it and the next game start loads the whole floor.
EnsureUIAssets:
              OVERLAY_ENTER
              lda long:pauseMode
              bne uiReady
              jsl long:OverlayTitleClobbered

              lda long:overlayUICold
              beq uiFill
              lda ##AUX_UI
              jsr abs:.word0 (ReadOverlay)
              lda ##0
              sta long:overlayUICold
              lda ##1
              sta long:overlayGameCold
;;; View weights and compiled weapons have separate RAM. Their keys stay valid.
;;; The play cache: at the boot it takes the image the boot loaded (the floppies) or reads
;;; its slots (the hard disk). Later the game has refilled it before it left a floor whose
;;; art took slots (PlayCacheLeave): nothing to read.
uiFill:       jsl long:PlayCacheFill
uiReady:      OVERLAY_LEAVE

;;; Title writes cover art on a resident floor. Only stores with exact restore
;;; records may keep it; a floor already discarded stays discarded.
OverlayTitleClobbered:
              php
              rep #0x20
              pha
              lda long:floorReady
              beq titleFloorDone
              lda long:STORE_ROOT+STORE_TITLE_RESTORE_OFFSET
              cmp ##1
              bne titleFloorDiscard
              lda ##2
              bra titleFloorMark
titleFloorDiscard:
              lda ##0
titleFloorMark:
              sta long:floorReady
titleFloorDone:
              pla
              plp
              rtl

;;; A same-floor restart after the title. Prepare the floor song before the
;;; restore, since its packed read also uses the art decode stage.
RestoreTitleArt:
              OVERLAY_ENTER
              lda long:floorSong
              jsl long:PrepareMusic
              lda long:levelIndex
              clc
              adc ##AUX_GAME_BASE
              ora ##LOAD_TITLE_FLAG
              jsr abs:.word0 (ReadOverlay)
              lda ##0
              sta long:overlayGameCold
              lda ##1
              sta long:floorReady
              OVERLAY_LEAVE

;;; The play cache (leveldirectory.s playLookup): read the slots that do not hold their
;;; store blocks (from playValid up) with the fill group that starts at or below playValid
;;; (tools/build_registered_episode.py play_cache), from the disk in the drive. The first
;;; call (EnsureUIAssets, at the boot) finds every slot full when the boot loaded the image
;;; from disk 1 (the floppies: BI_HOME_DISK bit 7, tools/mkdisk.py), else reads the slots
;;; (the hard disk). Then PlayCacheLeave when the game leaves a floor whose art took slots,
;;; with that floor's episode 6 disk in the drive, and a floor load (lglue.s
;;; LoadFloorAssets), which then finds every slot full. Not while the floor in RAM keeps art
;;; in the top slots. The game never asks for disk 1 after the boot.
PLAY_TABLE    .equ STORE_ROOT+512
PLAY_IMAGE    .equ 0x80                   ; BI_HOME_DISK: the boot loaded PLAY_CACHE (tools/mkdisk.py)
PlayCacheFill:
              OVERLAY_ENTER
              lda long:PLAY_TABLE
              cmp ##0x4350                ; "PC": the store has a play table
              bne fillDone
              lda long:playBooted
              bne fillBooted
              inc a
              sta long:playBooted
              lda long:BI_HOME_DISK
              and ##PLAY_IMAGE
              beq fillBooted
              lda long:PLAY_TABLE+6       ; the boot loaded the slots from disk 1
              sta long:playValid
fillBooted:   lda long:floorReady
              beq fillFree
              lda long:levelIndex
              asl a
              adc long:PLAY_TABLE+8       ; the floor limits
              tax
              lda long:PLAY_TABLE,x
              cmp long:PLAY_TABLE+6       ; the cached slots
              bcc fillDone                ; the floor in RAM keeps art in the top slots
fillFree:     lda long:playValid
              cmp long:PLAY_TABLE+6
              bcs fillDone                ; every slot holds its block
              lda long:PLAY_TABLE+4       ; the fill groups, by first slot, the first one 0
              asl a
              asl a
              adc long:PLAY_TABLE+10
              tax
fillFind:     dex
              dex
              dex
              dex
              lda long:PLAY_TABLE,x
              cmp long:playValid
              beq fillGroup
              bcs fillFind
fillGroup:    lda long:PLAY_TABLE+2,x
              jsr abs:.word0 (ReadRawGroup)
              lda long:PLAY_TABLE+6
              sta long:playValid
fillDone:     OVERLAY_LEAVE
playBooted:   .word 0                     ; 1 after the first fill: the boot's image is used up

;;; The game leaves the floor in play: A = the floor that loads next, or $FFFF for the title.
;;; When that floor's art took slots (53, 58), they get their blocks back now, from the disk
;;; in the drive (that floor's episode 6 disk: tools/floppy_layout.py play_floors), before the
;;; next load asks for another disk. Then the floor's art there is gone: floorReady 0. Nothing
;;; when the next floor's own art takes those slots too. For the title, no floor is in play
;;; any more: the title's loads ask for the home disk, not the floor's (leveldirectory.s
;;; wantedDisk, homeDisk 0).
PlayCacheLeave:
              OVERLAY_ENTER
              tay
              cpy ##0xffff
              bne leaveFloor
              lda ##0
              sta long:homeDisk
leaveFloor:   lda long:PLAY_TABLE
              cmp ##0x4350                ; "PC"
              bne leaveDone
              lda long:playValid
              cmp long:PLAY_TABLE+6
              bcs leaveDone               ; every slot holds its block
              cpy ##0xffff
              beq leaveFill
              tya
              asl a
              adc long:PLAY_TABLE+8       ; the next floor's limit
              tax
              lda long:PLAY_TABLE,x
              cmp long:playValid
              beq leaveDone
              bcc leaveDone               ; its art takes those slots again
leaveFill:    lda ##0
              sta long:floorReady
              jsl long:PlayCacheFill
leaveDone:    OVERLAY_LEAVE

;;; Probe the packet group without loading it or prompting for missing disks.
;;; Automatic demos must check this even when their floor is already resident.
ProbeDemoAssets:
              OVERLAY_ENTER
              cmp ##4
              bcs demoProbeMissing
              clc
              adc ##AUX_DEMOS_BASE
              ora ##0x1000                ; auxiliary directory; ProbeFloorData adds bit 15
              jsl long:ProbeFloorData
              php
              jsl long:UiFwKeep
              plp
              bcs demoProbeMissing
              pld
              plb
              ply
              plx
              pla
              plp
              clc
              rtl
demoProbeMissing:
              pld
              plb
              ply
              plx
              pla
              plp
              sec
              rtl

;;; Only one recorded demo is active. Its original packets share a fixed
;;; buffer; all later packet reads retain the existing bank/offset format.
LoadDemoAssets:
              OVERLAY_ENTER
              cmp ##4
              bcc demoIndexReady
              lda ##65532
              jmp abs:.word0 (OverlayFailure)
demoIndexReady:
              clc
              adc ##AUX_DEMOS_BASE
              jsr abs:.word0 (ReadOverlay)
              OVERLAY_LEAVE

;;; The tally's lump into PAGE_STAGE (tally_art.s TallyStage): its own group, a play group
;;; (the play cache holds it), not the UI group, which the floppies keep on disk 1 only.
LoadTallyAssets:
              OVERLAY_ENTER
              lda ##AUX_TALLY
              jsr abs:.word0 (ReadOverlay)
              OVERLAY_LEAVE

;;; Restore the selected view as well as art before a paused game resumes.
EnsureGameplayAssets:
              OVERLAY_ENTER
              lda long:weaponViewIndex
              lsr a
              jsl long:EnsureViewAssets
              OVERLAY_LEAVE

;;; A = view 0..3. Each view group loads only when its key changes.
;;; Restore gameplay last: every packed read uses bank $1D.
;;; AUX_GAME must end with raw bank-$1D records, after all compressed records.
EnsureViewAssets:
              OVERLAY_ENTER
              cmp ##4
              bcc viewValid
              lda ##65534
              jmp abs:.word0 (OverlayFailure)
viewValid:    sta long:overlayWantedView
              cmp long:overlayWeightView
              beq weightsReady
              clc
              adc ##AUX_WEIGHTS_BASE
              jsr abs:.word0 (ReadOverlay)
              lda long:overlayWantedView
              sta long:overlayWeightView
weightsReady: lda long:levelIndex
              cmp ##CAMPAIGN_FLOORS
              bcc floorValid
              lda ##65533
              jmp abs:.word0 (OverlayFailure)
floorValid:   asl a
              asl a
              clc
              adc long:overlayWantedView
              sta long:overlayWantedWeapon
              cmp long:overlayWeaponKey
              beq weaponsReady
              clc
              adc ##AUX_WEAPONS_BASE
              jsr abs:.word0 (ReadOverlay)
              lda long:overlayWantedWeapon
              sta long:overlayWeaponKey
weaponsReady: lda long:overlayGameCold
              beq gameReady
              lda long:levelIndex
              clc
              adc ##AUX_GAME_BASE
              jsr abs:.word0 (ReadOverlay)
              lda ##0
              sta long:overlayGameCold
gameReady:    jsr abs:.word0 (ApplyTransparency)
              OVERLAY_LEAVE

;;; Call before a real floor replacement, never for a probe. Mark the UI and
;;; art overlays cold; the view and weapon keys describe separate, intact RAM.
;;; A = the floor | flags: the play cache slots that the floor in play took come back first.
OverlayFloorChanging:
              php
              rep #0x20
              pha
              and ##0x0fff
              jsl long:PlayCacheLeave
              lda ##1
              sta long:overlayUICold
              sta long:overlayGameCold
;;; View weights and compiled weapons have separate RAM. Their keys stay valid.
              pla
              plp
              rtl

;;; Call immediately before BOOT_b1Seg, including compressed music reads.
;;; Raw standalone music reads do not destroy bank $1D and need no hook.
OverlayB1Clobbered:
              php
              rep #0x20
              pha
              lda ##1
              sta long:overlayGameCold
              pla
              plp
              rtl

;;; A = auxiliary group. Firmware temporarily uses the bottom of SHR.
;;; Keep that exact display range in the reserved bank-$3F buffer. The aux
;;; manifest must exclude this buffer, the resident code and all live state.
ReadOverlay:  sta long:overlayPendingGroup
              lda ##1
              sta long:overlayUICold
              sta long:overlayGameCold
              lda long:overlayPendingGroup
;;; A = a group of raw records for the bank-0 window: nothing else changes.
              .extern J13Reset
ReadRawGroup: sta long:overlayPendingGroup
              php
              sei
              ; Finish private MCU commands before masked firmware disk I/O.
              ; J13 keeps the observed held identities across this boundary.
              jsl long:J13Reset
              phb
              phd
              ldx ##0x8200
              ldy ##0x4600
              lda ##0x1dff
              .byte 0x54, 0x3f, 0xe1
              lda long:overlayPendingGroup
              jsl long:LoadAuxData
              php
              jsl long:UiFwKeep
              ldx ##0x4600
              ldy ##0x8200
              lda ##0x1dff
              .byte 0x54, 0xe1, 0x3f
              plp
              bcs overlayReadFailed
              pld
              plb
              plp
              rts
overlayReadFailed:
              pld
              plb
              plp
              lda long:overlayPendingGroup
;;; A malformed/missing group must never return to code that draws stale
;;; data. Retain its index for diagnostics and wait for a machine reset.
OverlayFailure:
              sta long:overlayFailedGroup
OverlayHalted:bra OverlayHalted

;;; The boot image carries no UI group and only non-overlapping game pieces.
;;; The title reads the UI group; the first game/view transition restores gameplay.
overlayUICold: .word 1
overlayGameCold: .word 1
overlayWeightView: .word 65535
overlayWeaponKey: .word 65535
overlayWantedView: .word 0
overlayWantedWeapon: .word 0
overlayPendingGroup: .word 0
overlayFailedGroup: .word 65535

;;; ---------------------------------------------------------------------------
;;; The in-game pause: a menu over a game it returns to. Its gray records are made
;;; from the screen's palettes ($00:2000, ui_gray.s PlayGrayTables) and its page
;;; records come raw into the bank-0 window ($00:2000-$5FFF: the renderer's dead
;;; span buffer and deferred paint list, idle while play is paused). It takes no
;;; colour snapshot, loads no UI group and stages nothing in bank $1D, so the
;;; only art it overwrites is the $3C composition frame (registered_loads.py
;;; restore_ranges). On close the game repaints its view and status bar.
;;; ---------------------------------------------------------------------------
#include "pause-window.inc"
#include "pause-floors.inc"

;;; MenuDimOpen, first: is this menu the in-game pause?
PauseModeSet: php
              rep #0x20
              pha
              lda long:uiGameOn
              beq pauseModeSet
              lda ##1
pauseModeSet: sta long:pauseMode
              pla
              plp
              rtl

;;; MenuDimOpen, after BuildMenuPal: the gray records, the colour-snapshot
;;; stores and the word records for this kind of menu.
PauseDimOpen: php
              rep #0x30
              pha
              phx
              phy
              lda long:pauseMode
              beq dimTitle
              jsl long:PlayGrayTables
              lda ##0x3c
              jsl long:GraySnapBank
              lda ##0
              sta long:snapTaken
              sta long:pauseWordsHere
              lda ##0xffff
              sta long:pauseHeadGroup
              sta long:pausePicGroup
              ldx ##0
              jsr abs:.word0 (pauseWordsSet)
              lda long:levelIndex          ; the $3C frame's art, if any, is read again
              tax                          ; on resume (AUX_GAME_BASE + floor)
              lda long:pauseFrameArt,x
              and ##255
              beq dimSet
              lda ##1
              sta long:overlayGameCold
              bra dimSet
dimTitle:     lda ##0x40
              jsl long:GraySnapBank
              lda ##1
              sta long:snapTaken
              ldx ##4*PAUSE_WORD_ENTRIES
              jsr abs:.word0 (pauseWordsSet)
dimSet:       ply
              plx
              pla
              plp
              rtl

;;; X = 0: wordDirectory names the window copies; X = 4 * PAUSE_WORD_ENTRIES:
;;; the title copies in the UI group. Native A16/X16.
pauseWordsSet:
              txa
              sta long:pwsSource
              lda ##0
              sta long:pwsEntry
              ldy ##PAUSE_WORD_ENTRIES
pwsNext:      lda long:pwsSource
              tax
              lda long:pauseWordWindow+2,x
              pha
              lda long:pauseWordWindow,x
              pha
              lda long:pwsEntry
              tax
              pla
              sta long:wordDirectory+4,x
              pla
              sta long:wordDirectory+6,x
              lda long:pwsSource
              clc
              adc ##4
              sta long:pwsSource
              lda long:pwsEntry
              clc
              adc ##10
              sta long:pwsEntry
              dey
              bne pwsNext
              rts

;;; MenuDimClose of the in-game pause: the game's slot bindings come back.
PauseClose:   php
              rep #0x30
              pha
              phx
              phy
              phb
              ldx ##.word0 SLOT_SAVE
              ldy ##.word0 SLOT_REC
              lda ##63
              .byte 0x54, 0x41, 0x41
              plb
              lda ##0
              sta long:pauseMode
              lda long:uiGameOn
              bne closeKept
              lda ##0xffff                ; End Game: the title next
              jsl long:PlayCacheLeave
closeKept:    ply
              plx
              pla
              plp
              rtl

;;; LoadLump, A = lump: in the in-game pause a page's heading or pictures come
;;; raw into the window ($00:3200 heading, $00:4600 pictures), no sign, no
;;; stage. nativeRecord/nativeBank then name the window copy. Carry clear:
;;; done. Carry set: not a window lump; A is kept.
PauseLump:    php
              rep #0x30
              pha
              lda long:pauseMode
              beq lumpOther
              lda 1,s
              cmp ##PAUSE_LUMPS
              bcs lumpOther
              asl a
              tax
              lda long:pauseLumpGroup,x
              cmp ##0xffff
              beq lumpOther
              pha
              lda long:pauseLumpSlot,x
              bne lumpPicture
              pla
              cmp long:pauseHeadGroup
              beq lumpHere
              sta long:pauseHeadGroup
              bra lumpRead
lumpPicture:  pla
              cmp long:pausePicGroup
              beq lumpHere
              sta long:pausePicGroup
lumpRead:     phx
              clc
              adc ##AUX_PAUSE_BASE
              jsr abs:.word0 (ReadRawGroup)
              plx
              lda ##0                     ; the words shared these bytes
              sta long:pauseWordsHere
lumpHere:     lda long:pauseLumpAddr,x
              sta long:nativeRecord
              lda ##0x0100                ; bank 0; nonzero high byte: a record is set
              sta long:nativeBank
              pla
              plp
              clc
              rtl
lumpOther:    pla
              plp
              sec
              rtl

;;; MainMenu, before the main page: in the in-game pause its words come raw
;;; into the window (pauseWordsSet pointed wordDirectory there).
PauseWords:   php
              rep #0x30
              pha
              lda long:pauseMode
              beq wordsSet
              lda long:pauseWordsHere
              bne wordsSet
              lda ##AUX_PAUSE_BASE+PAUSE_GROUP_WORDS
              jsr abs:.word0 (ReadRawGroup)
              lda ##1
              sta long:pauseWordsHere
              lda ##0xffff
              sta long:pauseHeadGroup
              sta long:pausePicGroup
wordsSet:     pla
              plp
              rtl

pauseMode:    .word 0                     ; 1 while the in-game pause is open
snapTaken:    .word 1                     ; 1: $41:0000 holds the menu's colour snapshot
pauseWordsHere: .word 0                   ; 1: the main page's words are in the window
pauseHeadGroup: .word 0xffff              ; the window's heading and picture groups
pausePicGroup: .word 0xffff
pwsSource:    .word 0
pwsEntry:     .word 0

              .section registeredmenu, text, root, noreorder
              .public TransparencyToggle, TransparencyLoad, TransparencyStore
              .public ApplyTransparency, fastTransparencyOn
;;; The option selects resident headers only at a cold transition. The painter
;;; sees the same header and command formats in either mode, with no flag test.
TransparencyToggle:
              lda long:fastTransparencyOn
              eor ##1
              sta long:fastTransparencyOn
              rtl
TransparencyLoad:
              lda long:SETTINGS_IN+S_FAST_TRANSPARENCY
              bit ##2
              bne transparencyExplicit
              lda ##1
transparencyExplicit:
              and ##1
              sta long:fastTransparencyOn
              rtl
TransparencyStore:
              sep #0x20
              lda long:fastTransparencyOn
              ora #2
              sta long:SETTINGS_IN+S_FAST_TRANSPARENCY
              rep #0x20
              rtl

;;; Called inside EnsureViewAssets' saved-register frame, after any art restore.
;;; Each floor loads original headers and applied mode zero. The program holds
;;; a count, then pairs of header offset and 202 XOR bytes, all in one bank.
ApplyTransparency:
              lda long:fastTransparencyOn
              cmp long:SPRITE_QUALITY_STATE+4
              beq transparencyDone
              lda long:SPRITE_QUALITY_STATE
              sta long:transparencyCount+1
              sta long:transparencyFrame+1
              sta long:transparencyWord+1
              sep #0x20
              lda long:SPRITE_QUALITY_STATE+2
              sta long:transparencyCount+3
              sta long:transparencyFrame+3
              sta long:transparencyWord+3
              lda #.byte2 SPRITE_CMDS
              pha
              plb
              rep #0x20
transparencyCount:
              lda long:0
              sta long:transparencyLeft
              beq transparencyApplied
              ldx ##2
transparencyFrame:
              lda long:0,x
              inx
              inx
              tay
              clc
              adc ##202
              sta long:transparencyEnd+1
transparencyWord:
              lda long:0,x
              eor abs:.word0 SPRITE_CMDS,y
              sta abs:.word0 SPRITE_CMDS,y
              inx
              inx
              iny
              iny
transparencyEnd:
              cpy ##0
              bne transparencyWord
              lda long:transparencyLeft
              dec a
              sta long:transparencyLeft
              bne transparencyFrame
transparencyApplied:
              lda long:fastTransparencyOn
              sta long:SPRITE_QUALITY_STATE+4
              lda ##1                    ; unchanged projections must repaint their new opacity
              sta long:GAME_DP+FIRST
transparencyDone:
              rts
fastTransparencyOn: .word 1
transparencyLeft: .word 0
