;;; Original indices can be dimmed through their own palettes immediately.
;;; Pixel conversion and page composition happen offscreen; source palettes
;;; need not contain identical dark shades.
#include "memmap.inc"
#include "frontend.inc"
#include "logic.inc"
#include "gray.inc"
;;; The bank $3F entry points that fall into DrawList are ui_dimstub.s.
              .extern EnsureUIAssets, PauseModeSet, PauseDimOpen, PauseClose, snapTaken, pauseMode
              .section uifastcode, text, root, noreorder
              .public MenuDimOpen, MenuDimClose, MenuCapture, MenuPrepare, MenuReveal
              .public GrayRect, PalBlack, BlackPixels, RemapSlot, RestoreRows
              .public WaitBlank, RevealPal, ConvertRange, ConvertHidden
              .extern BuildMenuPal, menuFresh, menuPaletteDirty, tallyCacheValid
              .extern FlashQuiet, UiKeepView, screenBlack, viewPal, palHold, fadeBase, uiGameOn
              .extern composing, GatherPreviews, GrayRow, GrayRowHold, GrayCopyRows, CloseRestore
              .extern ClearGrayRows, BindHeldTint, BindInit, PublishGrayRow, DeriveFlashSlots
              .extern framePending, frameEntry, NormalizeGray

MENU_PAL      .equ 15
cvLo:         .word 0
cvHi:         .word 0

;;; ---------------------------------------------------------------------------
;;; Blank and palette timing
;;; ---------------------------------------------------------------------------

;;; C019 rises at row 192. Allow the remaining SHR rows plus two guard lines
;;; before publishing colors (TN IIGS #39 and #40). A range test tolerates
;;; an interrupt spanning the start of blanking.
WaitVBL:      php
              sep #0x20
vblShown:     lda long:RDVBLBAR
              bmi vblShown
vblBlank:     lda long:RDVBLBAR
              bpl vblBlank
vblShrTail:   lda long:VERTCNT
              cmp #0xe5
              bcc vblShrTail
              plp
              rts

;;; Every hardware color to black, at the blank, so a later picture change
;;; cannot show under the previous colors.
PalBlack:     jsr abs:.word0 (WaitVBL)
              ldx ##510
              lda ##0
blackWord:    sta long:SHR_PAL,x
              dex
              dex
              bpl blackWord
              lda ##1
              sta long:screenBlack
              rtl

;;; The blank, for a caller in another bank.
WaitBlank:    jsr abs:.word0 (WaitVBL)
              rtl

;;; Publish the palettes screenInit stored at PALBUF. The picture is already
;;; in place, so the colors change during the blank (TN IIGS #40).
RevealPal:    jsr abs:.word0 (WaitVBL)
              ldx ##0xb000
              ldy ##0x9e00
              lda ##511
              phb
              .byte 0x54, 0xe1, 0xe0         ; MVN: PALBUF to palette RAM
              plb
              stz abs:.word0 (palHold)
              lda ##0
              sta long:screenBlack
              jsl long:BindHeldTint
              rtl

;;; Publish palette 15 at the blank. Row controls stay as the drawer left them.
MenuReveal:   jsr abs:.word0 (WaitVBL)
              lda abs:.word0 (menuDim)
              cmp ##2
              bne revealColors
              ldx ##30
revealMenuColors: lda abs:.word0 (fadeBase + 480),x
              sta long:SHR_PAL + 480,x
              dex
              dex
              bpl revealMenuColors
              bra revealDone
revealColors: phb
              ldx ##.word0 (fadeBase)
              ldy ##0x9e00
              lda ##511
              .byte 0x54, 0xe1, 0x3f
              plb
revealDone:   lda ##0
              sta long:menuPaletteDirty
              stz abs:.word0 (screenBlack)
              lda abs:.word0 (menuDim)
              cmp ##2
              beq revealKeep
              lda ##1
              sta abs:.word0 (menuDim)
revealKeep:   rtl

;;; 32000 zero bytes. Slot 0 is black once a floor palette is published.
BlackPixels:  ldx ##0x2000
              ldy ##16000
              lda ##0
blackPix:     sta long:BANK_E1,x
              inx
              inx
              dey
              bne blackPix
              rtl

;;; ---------------------------------------------------------------------------
;;; Open, close, resnap
;;; ---------------------------------------------------------------------------

;;; Snapshot metadata only. No display register changes before conversion.
;;; A menu over a game it returns to (uiGameOn) is the in-game pause: no colour
;;; snapshot, no UI group in art RAM (src/iigs/ui_overlays.s PauseModeSet).
MenuDimOpen:
              jsl long:PauseModeSet
              jsl long:EnsureUIAssets
              jsl long:BindInit
              stz dp:UC_FIRST
              stz dp:UC_Y
              lda ##32000
              sta dp:UC_END
              lda ##200
              sta dp:UC_BOTTOM
              sep #0x20
              lda #0
              sta long:MENU_SHOWN
              sta long:MENU_PHASE
              rep #0x20
              jsl long:FlashQuiet
              jsl long:DeriveFlashSlots
              jsl long:BuildMenuPal
              jsl long:ClearGrayRows
              jsl long:PauseDimOpen
              jsr abs:.word0 (SnapMeta)
              lda ##0
              sta long:framePending
              lda ##1
              sta long:frameEntry
              phb
              ldx ##0x8000
              ldy ##0x8410
              lda ##63
              .byte 0x54, 0x41, 0x41
              plb
              lda ##1
              jsr abs:.word0 (MarkPhase)
              lda ##1
              sta long:menuFresh
              lda ##2
              sta abs:.word0 (menuDim)
              rtl

;;; Benchmark capture leaves hardware palettes untouched.
MenuCapture:
              jsl long:EnsureUIAssets
              jsr abs:.word0 (CaptureBody)
              rtl
CaptureBody:  jsl long:FlashQuiet
              jsr abs:.word0 (SnapAll)
              jsl long:BuildMenuPal
              rts

;;; A = 0: put the saved picture back and keep it across the game's next
;;; setView. A = 1: a new or loaded game replaces the picture, so the saved
;;; one is thrown away and the screen stays black. The in-game pause saved no
;;; picture: its slot bindings come back and the game's setView turns the
;;; colors black, repaints the whole view and status bar and reveals them at
;;; the blank (wolf.s screenFull, ShowView). End Game goes on black.
MenuDimClose: pha
              stz abs:.word0 (menuDim)
              sep #0x20
              lda #0
              sta long:MENU_SHOWN
              rep #0x20
              pla
              bne closeFresh
              lda long:snapTaken
              beq closeGame
              jsl long:CloseRestore
              ; Only a restored live game has floor palettes that setView can
              ; reuse. Reusing a slideshow's faded palettes makes demos black.
              lda long:uiGameOn
              beq closeRestored
              jsl long:UiKeepView
closeRestored:
              rtl
;;; Back to Game: the menu stays up until UiOpen takes the view latch at once
;;; (ui_hooks.s resumeView); no game frame paints under the menu's colors.
closeGame:    jsl long:PauseClose
              lda long:uiGameOn
              beq closeFresh
              rtl
closeFresh:   jsl long:PalBlack
              jsl long:BlackPixels
              lda ##0
              sta long:pauseMode
              rtl

;;; The gray copy is already on the screen. A new page redraws its own
;;; rectangle from that copy; it does not convert the picture again.
MenuPrepare:  lda abs:.word0 (menuDim)
              beq menuPrepared
              ldx ##30
menuFadeSteel: lda long:MENU_COL,x
              sta abs:.word0 (fadeBase + 480),x
              dex
              dex
              bpl menuFadeSteel
menuPrepared: rtl

SnapAll:      jsr abs:.word0 (SnapMeta)
SnapPixels:   lda ##0
              sta long:tallyCacheValid
              phb
              ldx ##0x2000
              ldy ##0
              lda ##31999
              .byte 0x54, 0x41, 0xe1
              plb
              rts
SnapMeta:     phb
              ldx ##0x9e00
              ldy ##0x7e00
              lda ##511
              .byte 0x54, 0x41, 0xe1
              ldx ##0x9d00
              ldy ##0x7d00
              lda ##199
              .byte 0x54, 0x41, 0xe1
              plb
              rts

RestorePix:   phb
              ldx ##0
              ldy ##0x2000
              lda ##31999
              .byte 0x54, 0xe1, 0x41
              ldx ##0x7d00
              ldy ##0x9d00
              lda ##199
              .byte 0x54, 0xe1, 0x41
              plb
              rts

RestorePal:   jsr abs:.word0 (WaitVBL)
              phb
              ldx ##0x7e00
              ldy ##0x9e00
              lda ##511
              .byte 0x54, 0xe1, 0x41
              plb
              stz abs:.word0 (screenBlack)
              rts

;;; A = the phase byte. Bank and register width stay as the caller left them.
MarkPhase:    sep #0x20
              sta long:MENU_PHASE
              rep #0x20
              rts

;;; Palette 15, after conversion. Slots 12-15 keep the backdrop unchanged.
PublishMenu:  jsr abs:.word0 (WaitVBL)
PublishMenuNow: ldx ##30
publishWord:  lda long:MENU_COL,x
              sta long:SHR_PAL + 480,x
              sta abs:.word0 (fadeBase + 480),x
              dex
              dex
              bpl publishWord
              lda ##0
              sta long:menuPaletteDirty
              stz abs:.word0 (screenBlack)
              rts

;;; Dim the original indices first, then convert into the resident gray copy.
;;; No pixel with a new meaning is written under an original picture palette.
;;; A faded-out slideshow page already has black palettes. Build its gray
;;; background without revealing source colors; its complete page fades later.
ConvertHidden: php
              rep #0x30
              jsl long:EnsureUIAssets
              lda long:GRAY_STEEL_ON
              and ##255
              bne cvDone
              bra cvBuild
ConvertRange: php
              rep #0x30
              jsl long:EnsureUIAssets
              lda long:GRAY_STEEL_ON
              and ##255
              bne cvDone
              jsl long:GatherPreviews
              jsr abs:.word0 (WaitVBL)
              phb
              ldx ##0x8110
              ldy ##0x9e00
              lda ##511
              .byte 0x54, 0xe1, 0x41
              plb
cvBuild:      ldx ##0
cvLoop:       phx
              txa
              jsl long:GrayRow
              plx
              inx
              cpx ##200
              bcc cvLoop
              lda ##1
              sta long:GRAY_STEEL_ON
              lda long:framePending
              bne cvDone
              jsl long:NormalizeGray
cvDone:       plp
              rtl

;;; A = how many rows from the top to copy back from the gray picture.
;;; Nothing is converted again.
RestoreRows:  rep #0x20
              cmp ##0
              beq rrNone
              cmp ##200
              bcc rrOk
              lda ##200
rrOk:         tax
              lda ##0
              jsl long:GrayCopyRows
rrNone:       rtl

;;; The rectangle (U_X, U_Y, U_W, U_H) from the snapshot. U_W is even.
;;; Geometry and the temps a caller still needs are put back.
GrayRect:     lda abs:.word0 (menuDim)
              bne grayRectOn
              rtl
grayRectOn:   lda dp:U_X
              pha
              lda dp:U_Y
              pha
              lda dp:U_W
              pha
              lda dp:U_H
              pha
              lda dp:U_T0
              pha
              lda dp:U_T1
              pha
              lda dp:U_T2
              pha
              lda dp:U_T3
              pha
              lda dp:U_T4
              pha
              lda dp:U_T5
              pha
              lda dp:U_T7
              pha
              jsr abs:.word0 (GrayRectGo)
              pla
              sta dp:U_T7
              pla
              sta dp:U_T5
              pla
              sta dp:U_T4
              pla
              sta dp:U_T3
              pla
              sta dp:U_T2
              pla
              sta dp:U_T1
              pla
              sta dp:U_T0
              pla
              sta dp:U_H
              pla
              sta dp:U_W
              pla
              sta dp:U_Y
              pla
              sta dp:U_X
              rtl

GrayRectGo:   lda dp:U_H
              bne grayRectHasH
              rts
grayRectHasH: lda dp:U_W
              lsr a
              bne grayRectHasW
              rts
grayRectHasW: sta dp:U_T3
              lda dp:U_Y
              asl a
              asl a
              clc
              adc dp:U_Y
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:U_T4
              lda dp:U_X
              lsr a
              clc
              adc dp:U_T4
              sta dp:U_X
              lda long:composing
              bne grayCompose
              lda ##0x2000
              ldx ##0xe1
              bra grayDest
grayCompose:  lda dp:UD_BASE
              ldx ##0x3c
;;; Paused composition uses the frame's absolute coordinates; visible copies
;;; use the $2000 screen base in bank $E1.
grayDest:
grayBank:     sta long:grayCopyBase
              sep #0x20
              txa
              sta long:grayCopyMove+1
              rep #0x20
              phb
grayRow:      lda dp:U_X
              clc
              adc long:grayCopyBase
              tay
              ldx dp:U_X
              lda dp:U_T3
              dec a
grayCopyMove: .byte 0x54, 0xe1, 0x3d
              lda dp:U_X
              clc
              adc ##160
              sta dp:U_X
              inc dp:U_Y
              dec dp:U_H
              bne grayRow
              plb
grayRectLeave: rts
grayCopyBase: .word 0
;;; Legacy target hooks remain exported; the block-copy destination is set above.
grayPut:
grayPutByte:  sta long:SHR,x
rectPut0:     sta long:SHR+0,x
rectPut1:     sta long:SHR+2,x
rectPut2:     sta long:SHR+4,x
rectPut3:     sta long:SHR+6,x
rectPut4:     sta long:SHR+8,x
rectPut5:     sta long:SHR+10,x
rectPut6:     sta long:SHR+12,x
rectPut7:     sta long:SHR+14,x
rectPut8:     sta long:SHR+0,x
rectPut9:     sta long:SHR,x
              rts

;;; A = a floor slot 0..15. A = the menu slot. Does not read menuDim.
RemapSlot:    and ##15
              tax
              sep #0x20
              lda abs:.word0 (slotRemap),x
              rep #0x20
              and ##255
              rtl

              .section menudata, data, root
              .public menuDim
menuDim:      .word 0
slotRemap:
#include "steel-slots.inc"

              .public rectPut0, rectPut1, rectPut2, rectPut3, rectPut4, rectPut5, rectPut6, rectPut7, rectPut8, rectPut9
