              .section uifastcode, text, root, noreorder
              .public PsychedPrepare, PsychedNewGame, PsychedShow, PsychedForget
              .extern CopyMenuBlocks, SignUpLong, BusyForgetLong, UiStartGame
              .extern diffCur, chosenFloor, menuResult, uiGameOn, benchFresh
              .extern busyShown, busyKind, busyDark
              .extern ProgressFinish, DrawTitleBanked

;;; Decode before the difficulty choice. The title cache was loaded on the
;;; home disk; menu drawing uses the preceding 4 KB decode window only.
PsychedPrepare:
              lda ##PSYCHED_BLOCK
              sta dp:U_BLK
              lda ##PSYCHED_BLOCKS
              sta dp:U_CNT
              lda ##.word0 NEWGAME_PIC
              sta dp:U_DOFF
              stz dp:U_DBNK
              jsl long:CopyMenuBlocks
              rtl

;;; Only the confirmed New Game owns this plate. Other loads use BusyShow's
;;; normal sign, and the first gameplay frame releases the temporary pixels.
PsychedNewGame:
              lda ##1
              sta long:psychedActive
              jsl long:SignUpLong
              lda long:chosenFloor
              tax
              lda long:diffCur
              jsl long:UiStartGame
              bcs psychedFailed
              jsl long:ProgressFinish
              lda ##1
              sta long:menuResult
              sta long:uiGameOn
              lda ##0
              sta long:benchFresh
              rtl
psychedFailed:
              jsl long:BusyForgetLong
              rtl

;;; Carry set replaces the ordinary sign. The plate includes its frame and
;;; the usual progress trough. The heading renderer owns palettes 0..2;
;;; floor palette writes remain held until the game picture replaces it.
PsychedShow:  lda long:psychedActive
              beq psychedOrdinary
              lda long:busyKind
              bne psychedOrdinary
              lda long:busyShown
              bne psychedCopy
              jsl long:BusyHoldPal
              lda ##0
              sta long:busyDark
;;; A scan-line palette spans the whole screen. Restore just the two exposed
;;; side strips from the gray copy before the band replaces their selectors.
              stz dp:U_X
              lda ##PSYCHED_Y+3
              sta dp:U_Y
              lda ##PSYCHED_X
              sta dp:U_W
              lda ##PSYCHED_ROWS-14
              sta dp:U_H
              jsl long:GrayRect
              lda ##PSYCHED_X+PSYCHED_WB*2
              sta dp:U_X
              jsl long:GrayRect
psychedCopy:
;;; The backdrop pixels use the band's shared slots. Publish its colors
;;; before copying any lettering, so each new pixel has its final palette.
              lda ##.word0 (NEWGAME_PIC+PSYCHED_RECORD)
              sta dp:U_SRC
              stz dp:W_PTR+2
              lda ##PSYCHED_Y+3
              sta dp:U_Y
              lda ##0xffff
              sta dp:U_X
              jsl long:DrawTitleBanked
              phb
              ldx ##.word0 NEWGAME_PIC
              ldy ##.word0 SHR+PSYCHED_Y*160+PSYCHED_X/2
              lda ##PSYCHED_ROWS
              sta dp:U_T6
psychedRow:   lda ##PSYCHED_WB-1
              .byte 0x54, .byte2 (SHR), .byte2 (NEWGAME_PIC)
              tya
              clc
              adc ##160-PSYCHED_WB
              tay
              dec dp:U_T6
              bne psychedRow
              plb
              lda ##0
              sta long:busyProgress
              lda ##1
              sta long:busyShown
              sec
              rtl
psychedOrdinary:
              clc
              rtl
PsychedForget:
              lda ##0
              sta long:psychedActive
              rtl
psychedActive: .word 0
