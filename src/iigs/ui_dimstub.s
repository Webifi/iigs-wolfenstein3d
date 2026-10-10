;;; MenuScreen falls through into DrawList, so these stubs stay in bank $3F.
;;; The gray copy is bank 2 (ui_dim.s). Two text sections in one object are
;;; placed in the first section's memory, which filled the menu bank.
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public MenuScreen, MenuFinish, pageList
              .extern menuPaletteDirty, listFont, listPictures, previewLast
              .extern DrawList, menuDim, MenuPrepare, MenuReveal, listClean, FramePresent
MenuScreen:   lda ##0xffff
              sta abs:.word0 (previewLast)
              stz abs:.word0 (listPictures)
              stz abs:.word0 (listFont)
              stx abs:.word0 (pageList)
              lda ##1
              sta abs:.word0 (listClean)
              jsl long:MenuPrepare
              rts
MenuFinish:   jsl long:FramePresent
              lda long:menuPaletteDirty
              beq finishOff
              jsl long:MenuReveal
finishOff:    rts

              .section menudata, data, root
pageList: .word 0

              .section menucode, text, root, noreorder
              .public PageCall, DrawPageList, DeriveFlashSlots
              .extern pageCallback
PageCall:     lda long:pageCallback
              sta long:pageCallNear+1
              jsr abs:.word0 (pageCallNear)
              rtl
pageCallNear: jsr abs:0
              rts
DrawPageList: ldx abs:.word0 (pageList)
              jmp abs:.word0 (DrawList)

;;; The playing view's slots 0-12 are the floor tint flashWrite last published.
;;; Esc has paused the game, so the menu derives that once from the level,
;;; the tint offset, and the flash state. A held picture keeps its own record,
;;; and a title picture is not a playing view.
              .extern uiGameOn, palHold, levelIndex, tintFloorOffsets
              .extern flashSource, flashStatus, BindTintBlock, BindHeldTint
DeriveFlashSlots:
              php
              rep #0x30
              lda long:uiGameOn
              beq deriveHeld
              lda long:palHold
              bne deriveHeld
              lda long:flashStatus
              cmp ##0x9000
              bcc deriveHeld
              lda long:levelIndex
              asl a
              tax
              lda long:tintFloorOffsets,x
              clc
              adc long:flashSource
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              pha
              lda long:flashStatus
              sec
              sbc ##0x9000
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              tax
              pla
              jsl long:BindTintBlock
              jsl long:BindHeldTint
deriveHeld:   plp
              rtl
