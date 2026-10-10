#include "frontend.inc"
#include "campaign.inc"
              .extern campaignLocal
              .section registeredmenu, text, root, noreorder
              .public InitLettering, FloorSelect, chosenFloor, visitMask, bootComplete, MarkFloorVisited, floorColumns
              .extern listFont, listPictures, listHookVec, LoadLump, ListRun, MenuScreen, dlFloors, levelIndex, demoMode, timeDemo

InitLettering: lda abs:.word0 (fontReady)
              bne letteringReady
              phb
              ldx ##0x8000
              ldy ##0xa100
              lda ##STEEL_COLD_BYTES-1
              .byte 0x54, 0xe0, 0x41
              plb
              lda ##1
              sta abs:.word0 (fontReady)
letteringReady: rts
fontReady: .word 0

FloorSelect:  lda ##CAMPAIGN_EPISODES
              cmp ##2
              bcc floorEpisodeReady
              jsr abs:.word0 (EpisodeSelect)
              bcc floorEpisodeReady
              rts
floorEpisodeReady:
              lda ##LUMP_FLOORS
              jsr abs:.word0 (LoadLump)
              bcc floorLumpReady
              sec
              rts
floorLumpReady:
              ldx ##.word0 (dlFloors)
              jsr abs:.word0 (MenuScreen)
              lda abs:.word0 (selectedEpisode)
              asl a
              tax
              lda abs:.word0 (episodeFloorPointers),x
              sta abs:.word0 (selectedFloorList)
              sta dp:U_T6
              lda abs:.word0 (campaignEpisodeLength),x
              sta abs:.word0 (selectedFloorCount)
              ldx ##0
floorFlags:   txa
              asl a
              tay
              phx
              lda (U_T6),y
              jsr abs:.word0 (FloorMask)
              and abs:.word0 (visitMask),x
              beq floorUnseen
              lda ##1
floorUnseen:  plx
              cpx ##0
              bne floorFlagReady
              lda ##1
floorFlagReady:
              sep #0x20
              sta abs:.word0 (floorActive),x
              rep #0x20
              inx
              cpx abs:.word0 (selectedFloorCount)
              bcc floorFlags
              lda ##.word0 (floorItems)
              sta dp:UL_ITEMS
              lda abs:.word0 (selectedFloorCount)
              sta dp:UL_COUNT
              lda ##50
              sta dp:UL_X
              lda ##104
              sta dp:UL_Y
              lda ##14
              sta dp:UL_STEP
              lda ##26
              sta dp:UL_CX
              lda ##.word0 (floorActive)
              sta dp:UL_ACT
              lda abs:.word0 (chosenFloor)
              asl a
              tax
              lda long:campaignLocal,x
              dec a
              sta dp:UL_CUR
              lda ##68
              sta dp:UL_WIDTH
              lda ##2
              sta abs:.word0 (listPictures)
              sta abs:.word0 (listFont)
              lda ##.word0 (PreviewHook)
              sta abs:.word0 (listHookVec)
              sta dp:UL_HOOK
              stz dp:UL_VALHOOK
              stz dp:UL_LRHOOK
              SCREEN_ID 15
#ifdef CAMPAIGN_SPEAR
              stz abs:.word0 (floorColumns)
#else
              lda ##1
              sta abs:.word0 (floorColumns)
#endif
              jsr abs:.word0 (ListRun)
              stz abs:.word0 (floorColumns)
              cmp ##0xffff
              beq floorCancel
              asl a
              tay
              lda abs:.word0 (selectedFloorList)
              sta dp:U_T6
              lda (U_T6),y
              sta abs:.word0 (chosenFloor)
              clc
              rts
floorCancel:  sec
              rts

;;; Called only when a player floor is accepted, never from a play frame.
MarkFloorVisited:
              php
              rep #0x30
              pha
              phx
              phy
              lda long:demoMode
              ora long:timeDemo
              bne visitDone
              lda long:levelIndex
              cmp ##CAMPAIGN_FLOORS
              bcs visitDone
              jsr abs:.word0 (FloorMask)
              ora long:visitMask,x
              sta long:visitMask,x
visitDone:    ply
              plx
              pla
              plp
              rtl

;;; A = source floor; return its bit in A and bitmap word offset in X.
FloorMask:    pha
              lsr a
              lsr a
              lsr a
              lsr a
              asl a
              tay
              pla
              and ##15
              tax
              lda ##1
floorShift:   cpx ##0
              beq floorMaskDone
              asl a
              dex
              bra floorShift
floorMaskDone: tyx
              rts

              .public LoadVisitedFloors, StoreVisitedFloors
;;; JSL, preserve X/P. Settings checksums cover the version and all mask words.
;;; Existing settings retain their ten visited floors; unrecorded floors clear.
LoadVisitedFloors:
              php
              rep #0x30
              phx
              ldx ##6
visitClearHigh:
              lda ##0
              sta long:visitMask,x
              dex
              dex
              bne visitClearHigh
              lda long:SETTINGS_IN + S_VISITED
              and ##0x03ff
              ora ##1
              sta long:visitMask
              lda long:SETTINGS_IN + S_VISIT_VERSION
              and ##255
              cmp ##1
              bne visitLoadDone
              ldx ##6
visitLoadHigh:
              lda long:SETTINGS_IN + S_VISITED_HI-2,x
              sta long:visitMask,x
              dex
              dex
              bne visitLoadHigh
              lda long:SETTINGS_IN + S_VISITED
              ora ##1
              sta long:visitMask
visitLoadDone:
              plx
              plp
              rtl

StoreVisitedFloors:
              php
              rep #0x30
              phx
              lda long:visitMask
              ora ##1
              sta long:SETTINGS_IN + S_VISITED
              ldx ##6
visitStoreHigh:
              lda long:visitMask,x
              sta long:SETTINGS_IN + S_VISITED_HI-2,x
              dex
              dex
              bne visitStoreHigh
              sep #0x20
              lda #1
              sta long:SETTINGS_IN + S_VISIT_VERSION
              plx
              plp
              rtl

EpisodeSelect:
              lda ##LUMP_FLOORS
              jsr abs:.word0 (LoadLump)
              bcc episodeDraw
              sec
              rts
episodeDraw:  ldx ##.word0 (dlFloors)
              jsr abs:.word0 (MenuScreen)
              SCREEN_ID 19
              lda ##.word0 (episodeItems)
              sta dp:UL_ITEMS
              lda ##.word0 (episodeActive)
              sta dp:UL_ACT
              lda ##CAMPAIGN_EPISODES
              sta dp:UL_COUNT
              lda ##40
              sta dp:UL_X
              lda ##84
              sta dp:UL_Y
              lda ##12
              sta dp:UL_STEP
              lda ##16
              sta dp:UL_CX
              lda ##264
              sta dp:UL_WIDTH
              lda abs:.word0 (selectedEpisode)
              sta dp:UL_CUR
              lda ##2
              sta abs:.word0 (listFont)
              stz abs:.word0 (floorColumns)
              lda ##4
              sta abs:.word0 (listPictures)
              lda ##.word0 (PreviewHook)
              sta abs:.word0 (listHookVec)
              sta dp:UL_HOOK
              stz dp:UL_VALHOOK
              stz dp:UL_LRHOOK
              jsr abs:.word0 (ListRun)
              cmp ##65535
              bne episodeChosen
              sec
              rts
episodeChosen:
              cmp abs:.word0 (selectedEpisode)
              beq episodeSame
              sta abs:.word0 (selectedEpisode)
              asl a
              tax
              lda abs:.word0 (campaignEpisodeStart),x
              sta abs:.word0 (chosenFloor)
episodeSame:  clc
              rts

              .section registeredmenudata, data, root
chosenFloor:  .word 0
visitMask:    .word 1
              .space 6
selectedEpisode: .word 0
selectedFloorList: .word 0
selectedFloorCount: .word 0
bootComplete: .word 0
#ifdef CAMPAIGN_SPEAR
floorActive:  .space CAMPAIGN_FLOORS
#include "spear-floor-items.inc"
#else
floorActive:  .space 10
floorItems:   .word .word0 (floor1), .word0 (floor2), .word0 (floor3), .word0 (floor4), .word0 (floor5)
              .word .word0 (floor6), .word0 (floor7), .word0 (floor8), .word0 (floor9), .word0 (floor10)
floor1:       .asciz "Floor 1"
floor2:       .asciz "Floor 2"
floor3:       .asciz "Floor 3"
floor4:       .asciz "Floor 4"
floor5:       .asciz "Floor 5"
floor6:       .asciz "Floor 6"
floor7:       .asciz "Floor 7"
floor8:       .asciz "Floor 8"
floor9:       .asciz "Floor 9"
floor10:      .asciz "Floor 10"
#endif

              .section registeredmenu, text, root, noreorder
              .public UiReadProgress, UiDiskPrompt
              .extern BusyBar, BusyShow, BusyHide, strInsert, ProgressAdd
UiReadProgress:
              php
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              phk
              plb
              sta abs:.word0 (readProgress)
              stx abs:.word0 (readTotal)
              jsr abs:.word0 (ioPage)
              jsr abs:.word0 (ioBar)
              bra ioRestore
UiDiskPrompt: php
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              phk
              plb
              sta abs:.word0 (promptNumber)
              jsr abs:.word0 (ioPage)
              lda abs:.word0 (promptNumber)
              beq ioLoading
              clc
              adc ##'0'
              sep #0x20
              sta abs:.word0 (strInsert+12)
              rep #0x20
              lda ##2
              jsr abs:.word0 (BusyShow)
              bra ioRestore
ioLoading:    lda ##0
              jsr abs:.word0 (BusyShow)
              jsr abs:.word0 (ioBar)
ioRestore:    ldx ##.word0 (ioSave)
              ldy ##UI_DP
              lda ##95
              .byte 0x54, 0x00, 0x3f
              pld
              plb
              ply
              plx
              pla
              plp
              rtl
ioPage:       ldx ##UI_DP
              ldy ##.word0 (ioSave)
              lda ##95
              .byte 0x54, 0x3f, 0x00
              lda ##UI_DP
              tcd
              rts
ioBar:        lda ##0
              jsl long:ProgressAdd
              rts

              .section registeredmenudata, data, root
readProgress: .word 0
readTotal:    .word 0
promptNumber: .word 0
ioSave:       .space 96
floorColumns: .word 0

              .section registeredmenu, text, root, noreorder
              .public PreviewHook, LoadPreviewLump
PreviewHook:   jsl long:PreviewCore
              rts
LoadPreviewLump: jsr abs:.word0 (LoadLump)
              rtl

              .section registeredmenudata, data, root
              .public previewLast
previewLast: .word 0xffff

#include "campaign-menu.inc"

              .section registeredmenu, text, root, noreorder
#include "ui_preview_core.inc"
