;;; A compact loading box, drawn into the existing paused update strip.
;;; Its 180 by 34 saved rectangle uses 3060 bytes of the 3200-byte busy buffer.
              .public BusyPanel, BusySaveRows, BusyRestoreRows, BusyBegin, BusyEndDraw, BusyReveal
              .public BusyHoldPal, BusyReleasePal
              .extern busyKind, busyDark, busyShown
              .extern palHold, FlashQuiet
              .extern steelOverlay
BUSY_SCB_SAVE .equ UI_BOXBUF+BOX_W/2*BOX_H
;;; Only the first sign acquires ownership; nested disk/song prompts retain it.
BusyHoldPal:  lda long:palHold
              sta long:busyPalHold
              lda ##1
              sta long:palHold             ; new floor colors wait for the new picture
              jsl long:FlashQuiet           ; keep the displayed background's current tint
              rtl
BusyReleasePal:
              lda long:busyShown
              beq busyPalReleased
              lda long:busyPalHold
              sta long:palHold
busyPalReleased: rtl
busyPalHold:  .word 0

BusySaveRows: ldx ##0
              sep #0x20
busySaveScb:  lda long:SHR_SCB+BOX_Y,x
              sta long:BUSY_SCB_SAVE,x
              inx
              cpx ##BOX_H
              bcc busySaveScb
              rep #0x20
              rtl
BusyRestoreRows:
              ldx ##0
              sep #0x20
busyRestoreScb:
              lda long:BUSY_SCB_SAVE,x
              sta long:SHR_SCB+BOX_Y,x
              inx
              cpx ##BOX_H
              bcc busyRestoreScb
              rep #0x20
              rtl
BusyPanel:    lda long:busyKind
              cmp ##3
              beq busyPanelDone           ; name entry keeps its own layout
              lda ##BUSY_EDGE_INK
              sta dp:U_C
              jsl long:FillRectCore
              lda ##BOX_X+2
              sta dp:U_X
              lda ##BOX_Y+2
              sta dp:U_Y
              lda ##BOX_W-4
              sta dp:U_W
              lda ##BOX_H-4
              sta dp:U_H
              stz dp:U_C
              jsl long:FillRectCore
              lda long:busyKind
              bne busyPanelDone
              lda ##BUSY_BAR_X-2
              sta dp:U_X
              lda ##BUSY_BAR_Y-2
              sta dp:U_Y
              lda ##BUSY_BAR_W+4
              sta dp:U_W
              lda ##BUSY_BAR_H+4
              sta dp:U_H
              lda ##BUSY_EDGE_INK
              sta dp:U_C
              jsl long:FillRectCore
              lda ##BUSY_BAR_X
              sta dp:U_X
              lda ##BUSY_BAR_Y
              sta dp:U_Y
              lda ##BUSY_BAR_W
              sta dp:U_W
              lda ##BUSY_BAR_H
              sta dp:U_H
              stz dp:U_C
              jsl long:FillRectCore
busyPanelDone: rtl

;;; Draw the fixed aligned ink slots in the strip. Each picture keeps its
;;; existing colors and row selectors; alignment supplies approximate roles.
BusyBegin:    lda long:menuDim
              sta long:busyDrawingDim
              lda ##0
              sta long:steelOverlay
              lda long:busyKind
              cmp ##3
              beq busyNameBackground
              lda ##1
              sta long:steelOverlay
              lda ##0
              sta long:menuDim
              jsl long:BeginOpaqueUpdate
              rtl
busyNameBackground:
              lda ##1
              sta long:menuDim
              jsl long:BeginUpdate
              rtl

BusyEndDraw:  lda long:busyDark
              beq busyDrawDone
              ldx ##BOX_Y
              sep #0x20
              lda #15
busyBlankRows:sta long:updateSCB,x
              inx
              cpx ##BOX_Y+BOX_H
              bcc busyBlankRows
              rep #0x20
busyDrawDone: lda long:busyDrawingDim
              sta long:menuDim
              lda ##0
              sta long:steelOverlay
              rtl

;;; Clear an already-black scene before revealing its completed sign.
;;; Only the sign's rows select its palette; no old image can reappear.
BusyReveal:   lda long:busyDark
              beq busyRevealDone
              jsl long:WaitBlank
              ldx ##30
busyBlankInk: lda long:menuSteel,x
              sta long:SHR_PAL+480,x
              dex
              dex
              bpl busyBlankInk
busyRevealDone:
              rtl
busyDrawingDim: .word 0
