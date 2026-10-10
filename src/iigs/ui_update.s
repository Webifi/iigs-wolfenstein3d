#include "memmap.inc"
#include "frontend.inc"
              .section uifastcode, text, root, noreorder
              .public BeginUpdate, BeginRecolor, EndUpdate, recolorActive
              .extern screenBlack, MenuReveal, titleTargetSCB
              .extern GrayRect, WaitBlank
              .extern doubleWrite0, doubleWrite1
              .extern solidRead0, solidRead2, solidWrite0, solidWrite1, solidWrite2
              .extern alphaRead0, alphaRead2, alphaWrite0, alphaWrite2, alphaMerge0, alphaMerge2
              .extern wordProgramBank, wordTargetBank, wordTargetPlain, wordTargetMapped, wordTargetRead, wordTargetMerge, steelTargetHigh, steelTargetLow, steelTargetStore, fillTargetByte, fillTargetWord, rectPut0, rectPut1, rectPut2, rectPut3, rectPut4, rectPut5, rectPut6, rectPut7, rectPut8, rectPut9

;;; A rectangle up to 64 rows, with X and W multiples of four pixels.
;;; Compose at absolute coordinates in the paused $3C frame. Bank $01 is
;;; available for other data; the live display remains in bank $E1.
BeginRecolor: lda ##1
              sta long:recolorActive
              sep #0x20
              lda #0
              sta long:steelRecolor+1
              rep #0x20
              rtl
recolorActive: .word 0
              .extern steelRecolor
              .public BeginOpaqueUpdate
BeginOpaqueUpdate:
              jsr abs:.word0 (UpdateSetup)
              rtl
BeginUpdate:  jsr abs:.word0 (UpdateSetup)
              lda long:framePending
              bne updateBackgroundReady
              jsl long:GrayRect
updateBackgroundReady:
              rtl

              .extern projectionCold
UpdateSetup:  lda ##1
              sta long:projectionCold
              sta long:composing
              sta long:screenBlack
              lda ##0
              sta long:updatePalette
              ldx dp:U_Y
              lda dp:U_Y
              clc
              adc dp:U_H
              sta dp:UC_BOTTOM
              sep #0x20
updateScbInit: lda long:pagePainting
              beq updateScbKeep
              lda #15
              bra updateScbStore
updateScbKeep: lda long:framePending
              beq updateLiveRow
              lda long:updateSCB,x
              bra updateScbStore
updateLiveRow: lda long:SHR_SCB,x
updateScbStore: sta long:updateSCB,x
              inx
              cpx dp:UC_BOTTOM
              bcc updateScbInit
              rep #0x20
              lda dp:U_Y
              sta dp:UC_Y
              clc
              adc dp:U_H
              sta dp:UC_BOTTOM
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
              sta dp:UD_ROW
              sta dp:UC_FIRST
              lda dp:UC_BOTTOM
              asl a
              asl a
              clc
              adc dp:UC_BOTTOM
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:UC_END
              lda dp:U_X
              lsr a
              sta dp:UD_X
              clc
              adc dp:UD_ROW
              sta dp:UD_ROW
              lda dp:U_W
              lsr a
              sta dp:UD_W
              lda dp:U_H
              sta dp:UD_H
              stz dp:UD_BASE
              lda ##0
              ldx ##0x3c
              jsr abs:.word0 (UpdateTarget)
              rts

;;; Compare words first, then store only their differing bytes to SHR. No clearing is visible to the beam.
EndUpdate:    lda long:recolorActive
              beq updateComposed
              lda ##0
              sta long:recolorActive
              sep #0x20
              lda #6
              sta long:steelRecolor+1
              rep #0x20
              rtl
updateComposed: lda long:framePending
              beq updateVisible
              jsr abs:.word0 (FrameClipAll)
              rtl
updateVisible: lda ##0x2000
              ldx ##0xe1
              jsr abs:.word0 (UpdateTarget)
              lda dp:UD_ROW
              sta dp:UD_BUF
              lda dp:UD_H
              sta dp:UD_N
              phb
              sep #0x20
              lda #0x3c
              pha
              plb
              rep #0x20
updateRow:    lda long:pagePainting
              beq updateRowCopy
              lda dp:UD_ROW
              cmp long:pageSkipStart
              bcc updateRowCopy
              cmp long:pageSkipEnd
              bcs updateRowCopy
              jmp abs:.word0 (updateNextRow)
updateRowCopy: lda dp:UD_W
              cmp ##32
              bcc updateNarrow
              dec a
              sta dp:UD_X
              lda dp:UD_ROW
              clc
              adc ##0x2000
              tay
              ldx dp:UD_BUF
              lda dp:UD_X
              phb
              .byte 0x54, 0xe1, 0x3c
              plb
              jmp abs:.word0 (updateNextRow)
updateNarrow: ldx dp:UD_ROW
              ldy dp:UD_BUF
              lda dp:UD_W
              sta dp:UD_X
              lda dp:UD_X
              and ##0xfff0
              bne updateFullWords
              jmp abs:.word0 (updateTailStart)
updateFullWords: sta dp:UD_X
updateBulk:
              lda abs:0,y
              eor long:SHR+0,x
              beq updateSame0
              bit ##0x00ff
              beq updateHigh0
              bit ##0xff00
              beq updateLow0
              lda abs:0,y
              sta long:SHR+0,x
              bra updateSame0
updateHigh0: sep #0x20
              lda abs:1,y
              sta long:SHR+1,x
              bra updateByteDone0
updateLow0: sep #0x20
              lda abs:0,y
              sta long:SHR+0,x
updateByteDone0: rep #0x20
updateSame0:
              lda abs:2,y
              eor long:SHR+2,x
              beq updateSame1
              bit ##0x00ff
              beq updateHigh1
              bit ##0xff00
              beq updateLow1
              lda abs:2,y
              sta long:SHR+2,x
              bra updateSame1
updateHigh1: sep #0x20
              lda abs:3,y
              sta long:SHR+3,x
              bra updateByteDone1
updateLow1: sep #0x20
              lda abs:2,y
              sta long:SHR+2,x
updateByteDone1: rep #0x20
updateSame1:
              lda abs:4,y
              eor long:SHR+4,x
              beq updateSame2
              bit ##0x00ff
              beq updateHigh2
              bit ##0xff00
              beq updateLow2
              lda abs:4,y
              sta long:SHR+4,x
              bra updateSame2
updateHigh2: sep #0x20
              lda abs:5,y
              sta long:SHR+5,x
              bra updateByteDone2
updateLow2: sep #0x20
              lda abs:4,y
              sta long:SHR+4,x
updateByteDone2: rep #0x20
updateSame2:
              lda abs:6,y
              eor long:SHR+6,x
              beq updateSame3
              bit ##0x00ff
              beq updateHigh3
              bit ##0xff00
              beq updateLow3
              lda abs:6,y
              sta long:SHR+6,x
              bra updateSame3
updateHigh3: sep #0x20
              lda abs:7,y
              sta long:SHR+7,x
              bra updateByteDone3
updateLow3: sep #0x20
              lda abs:6,y
              sta long:SHR+6,x
updateByteDone3: rep #0x20
updateSame3:
              lda abs:8,y
              eor long:SHR+8,x
              beq updateSame4
              bit ##0x00ff
              beq updateHigh4
              bit ##0xff00
              beq updateLow4
              lda abs:8,y
              sta long:SHR+8,x
              bra updateSame4
updateHigh4: sep #0x20
              lda abs:9,y
              sta long:SHR+9,x
              bra updateByteDone4
updateLow4: sep #0x20
              lda abs:8,y
              sta long:SHR+8,x
updateByteDone4: rep #0x20
updateSame4:
              lda abs:10,y
              eor long:SHR+10,x
              beq updateSame5
              bit ##0x00ff
              beq updateHigh5
              bit ##0xff00
              beq updateLow5
              lda abs:10,y
              sta long:SHR+10,x
              bra updateSame5
updateHigh5: sep #0x20
              lda abs:11,y
              sta long:SHR+11,x
              bra updateByteDone5
updateLow5: sep #0x20
              lda abs:10,y
              sta long:SHR+10,x
updateByteDone5: rep #0x20
updateSame5:
              lda abs:12,y
              eor long:SHR+12,x
              beq updateSame6
              bit ##0x00ff
              beq updateHigh6
              bit ##0xff00
              beq updateLow6
              lda abs:12,y
              sta long:SHR+12,x
              bra updateSame6
updateHigh6: sep #0x20
              lda abs:13,y
              sta long:SHR+13,x
              bra updateByteDone6
updateLow6: sep #0x20
              lda abs:12,y
              sta long:SHR+12,x
updateByteDone6: rep #0x20
updateSame6:
              lda abs:14,y
              eor long:SHR+14,x
              beq updateSame7
              bit ##0x00ff
              beq updateHigh7
              bit ##0xff00
              beq updateLow7
              lda abs:14,y
              sta long:SHR+14,x
              bra updateSame7
updateHigh7: sep #0x20
              lda abs:15,y
              sta long:SHR+15,x
              bra updateByteDone7
updateLow7: sep #0x20
              lda abs:14,y
              sta long:SHR+14,x
updateByteDone7: rep #0x20
updateSame7:
              txa
              clc
              adc ##16
              tax
              tya
              clc
              adc ##16
              tay
              lda dp:UD_X
              sec
              sbc ##16
              sta dp:UD_X
              beq updateTailStart
              jmp abs:.word0 (updateBulk)
updateTailStart: lda dp:UD_W
              and ##15
              beq updateNextRow
              sta dp:UD_X
updateWord:   lda abs:0,y
              eor long:SHR,x
              beq updateSame
              bit ##0x00ff
              beq updateHigh
              bit ##0xff00
              beq updateLow
              lda abs:0,y
              sta long:SHR,x
              bra updateSame
updateHigh: sep #0x20
              lda abs:1,y
              sta long:SHR+1,x
              bra updateByteDone
updateLow: sep #0x20
              lda abs:0,y
              sta long:SHR,x
updateByteDone: rep #0x20
updateSame:   inx
              inx
              iny
              iny
              dec dp:UD_X
              dec dp:UD_X
              bne updateWord
updateNextRow:
              lda dp:UD_ROW
              clc
              adc ##160
              sta dp:UD_ROW
              lda dp:UD_BUF
              clc
              adc ##160
              sta dp:UD_BUF
              dec dp:UD_N
              beq updatePixelsDone
              jmp abs:.word0 (updateRow)
updatePixelsDone: plb
              lda long:updatePalette
              beq updateScbCommit
              jsl long:MenuReveal
updateScbCommit: ldx dp:UC_Y
              sep #0x20
updateScbWord: lda long:pagePainting
              beq updateScbPaint
              txa
              cmp long:pageSkipY
              bcc updateScbPaint
              cmp long:pageSkipBottom
              bcc updateScbSame
updateScbPaint: lda long:updateSCB,x
              cmp long:SHR_SCB,x
              beq updateScbSame
              sta long:SHR_SCB,x
updateScbSame: inx
              cpx dp:UC_BOTTOM
              bcc updateScbWord
              rep #0x20
              .public UpdateFinish
UpdateFinish: lda ##0
              sta long:screenBlack
              sta long:composing
              stz dp:UC_FIRST
              stz dp:UC_Y
              lda ##32000
              sta dp:UC_END
              lda ##200
              sta dp:UC_BOTTOM
              rtl

              .public UpdateTarget
UpdateTarget:
              pha
              ; Compiled rows use a completed 16-bit Y address. They need the
              ; original target bank, before long-indexed base adjustment.
              sep #0x20
              txa
              sta long:wordProgramBank+1
              rep #0x20
              cpx ##0xe1
              beq updateLiveSCB
              lda ##.word0 (updateSCB)
              ldy ##0x41
              bra updateSCBTarget
updateLiveSCB: lda ##0x9d00
              ldy ##0xe1
updateSCBTarget: sta long:titleTargetSCB+1
              tya
              sep #0x20
              sta long:titleTargetSCB+3
              rep #0x20
              pla
              pha
              sta long:doubleWrite0+1
              clc
              adc ##160
              sta long:doubleWrite1+1
              sec
              sbc ##160
              sta long:solidRead0+1
              sta long:solidRead2+1
              sta long:solidWrite0+1
              sta long:solidWrite1+1
              sta long:solidWrite2+1
              sta long:alphaRead0+1
              sta long:alphaWrite0+1
              sta long:alphaMerge0+1
              clc
              adc ##2
              sta long:alphaRead2+1
              sta long:alphaWrite2+1
              sta long:alphaMerge2+1
              pla
              sta long:wordTargetPlain+1
              sta long:wordTargetMapped+1
              sta long:wordTargetRead+1
              sta long:wordTargetMerge+1
              sta long:steelTargetHigh+1
              sta long:steelTargetLow+1
              sta long:steelTargetStore+1
              sta long:fillTargetByte+1
              sta long:fillTargetWord+1
              pha
              sta long:rectPut0+1
              sta long:rectPut8+1
              sta long:rectPut9+1
              clc
              adc ##2
              sta long:rectPut1+1
              clc
              adc ##2
              sta long:rectPut2+1
              clc
              adc ##2
              sta long:rectPut3+1
              clc
              adc ##2
              sta long:rectPut4+1
              clc
              adc ##2
              sta long:rectPut5+1
              clc
              adc ##2
              sta long:rectPut6+1
              clc
              adc ##2
              sta long:rectPut7+1
              pla
              bit ##0x8000
              beq targetBankReady
              dex
targetBankReady: txa
              sep #0x20
              sta long:wordTargetBank+1
              sta long:steelTargetHigh+3
              sta long:steelTargetLow+3
              sta long:steelTargetStore+3
              sta long:fillTargetByte+3
              sta long:fillTargetWord+3
              sta long:rectPut0+3
              sta long:rectPut1+3
              sta long:rectPut2+3
              sta long:rectPut3+3
              sta long:rectPut4+3
              sta long:rectPut5+3
              sta long:rectPut6+3
              sta long:rectPut7+3
              sta long:rectPut8+3
              sta long:rectPut9+3
              rep #0x20
              rts

              .public ListPage
              .extern ListPageItem, ListPageCursor, ListPageDraw, floorColumns
              .extern ConvertRange, GrayCopyRows
              .extern rowCacheValid
;;; Compose the whole list in the paused frame. Preview hooks finish that same
;;; frame before MenuFinish publishes it. The visible page stays intact.
ListPage:     jsr abs:.word0 (PageBounds)
              lda ##1
              sta long:framePending
              sta long:listClean
              lda ##0
              sta long:rowCacheValid
              lda long:menuFresh
              beq pageCompose
              lda ##0
              sta long:menuFresh
              jsl long:ConvertRange
              lda ##1
              sta long:menuDim
pageCompose:  jsr abs:.word0 (FrameBegin)
              jsl long:ListPageDraw
              lda dp:UL_TOP
              sta long:pageItem
pageRow:      lda long:pageItem
              cmp dp:UL_COUNT
              bcs pageCursor
              sec
              sbc dp:UL_TOP
              cmp dp:UL_VISIBLE
              bcs pageCursor
              lda long:pageItem
              sta dp:U_ITEM
              jsl long:ListPageItem
              lda long:pageItem
              inc a
              sta long:pageItem
              bra pageRow
pageCursor:   jsl long:ListPageCursor
pageDone:     rtl
;;; $03E6 counts finished menu paints. The open page is 1; each later cursor
;;; or page paint advances it. GetKey draws nothing while it stays put.
MenuMark:     sep #0x20
              lda long:0x3e6
              inc a
              sta long:0x3e6
              lda long:0x3ef
              cmp #1
              bne markKeep
              lda #2
              sta long:0x3ef
markKeep:     rep #0x20
              rts
;;; Only the union of the old and new page owns background work. Title rows
;;; span the display because their row palettes remap even untouched grays.
PageBounds:   lda long:menuFresh
              beq pageBoundsKeep
              lda ##320
              sta long:oldLeft
              lda ##0
              sta long:oldRight
              sta long:oldBottom
pageBoundsKeep: lda dp:UL_CX
              and ##0xfffc
              pha
              cmp long:oldLeft
              bcc pageBoundsLeft
              lda long:oldLeft
pageBoundsLeft: sta long:pageLeft
              pla
              sta long:oldLeft
              lda dp:UL_X
              clc
              adc dp:UL_WIDTH
              adc ##7
              and ##0xfffc
              ldx dp:UL_VALHOOK
              beq pageBoundsColumns
              lda ##312
pageBoundsColumns: pha
              lda long:floorColumns
              tax
              pla
              cpx ##0
              beq pageBoundsRight
              lda ##320
pageBoundsRight: cmp ##320
              bcc pageBoundsRightKeep
              lda ##320
pageBoundsRightKeep: pha
              cmp long:oldRight
              bcs pageBoundsRightMax
              lda long:oldRight
pageBoundsRightMax: sec
              sbc long:pageLeft
              sta long:pageWidth
              pla
              sta long:oldRight
              lda dp:UL_COUNT
              cmp dp:UL_VISIBLE
              bcc pageBoundsRows
              lda dp:UL_VISIBLE
pageBoundsRows: pha
              lda long:floorColumns
              tax
              pla
              cpx ##0
              beq pageBoundsCount
              lda ##4
pageBoundsCount: tax
              lda dp:UL_Y
pageBoundsHeight: clc
              adc dp:UL_STEP
              dex
              bne pageBoundsHeight
              cmp ##200
              bcc pageBoundsBottom
              lda ##200
pageBoundsBottom: pha
              cmp long:oldBottom
              bcs pageBoundsMax
              lda long:oldBottom
pageBoundsMax: sta long:pageBottom
              pla
              sta long:oldBottom
              rts
PageWidth:    lda long:pageLeft
              sta dp:U_X
              lda long:pageWidth
              sta dp:U_W
              rts
oldLeft: .word 0
oldRight: .word 320
oldBottom: .word 200
pageLeft: .word 0
pageWidth: .word 320
pageBottom: .word 200
pageItem:     .word 0
pageY:        .word 0
pageSkipY: .word 0
pageAdvance: .word 0
pageSkipBottom: .word 0
pageSkipStart: .word 0
pageSkipEnd: .word 0
pictureTop: .word 0,44,40,94
pictureBottom: .word 0,96,96,158
pictureStart: .word 0,7040,6400,15040
pictureEnd: .word 0,15360,15360,25280

              .public TitleGray
;;; Shared gray slots survive title palettes without a second pixel remap.
;;; The legacy record map remains readable for the existing title format.
TitleGray:    rtl
              lda ##1
              sta long:updatePalette
              phy
              phb
              sty dp:U_T4
              ldy dp:HT_PTR
              lda abs:0,y
              and ##255
              clc
              adc dp:HT_Y
              cmp dp:UC_Y
              bcs titleTopReady
              lda dp:UC_Y
titleTopReady: sta dp:U_T0
              lda abs:1,y
              and ##255
              clc
              adc dp:HT_Y
              cmp dp:UC_BOTTOM
              bcc titleBottomReady
              lda dp:UC_BOTTOM
titleBottomReady: sec
              sbc dp:U_T0
              beq titleOutside
              bpl titleInside
titleOutside: plb
              ply
              rtl
titleInside:  sta dp:U_T1
              lda dp:U_T0
              asl a
              asl a
              clc
              adc dp:U_T0
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc dp:UD_BASE
              sta dp:U_T0
              ldy dp:U_T4
              lda abs:0,y
              sta dp:U_T5
              lda abs:2,y
              sta dp:U_T6
              lda abs:4,y
              sta dp:U_T7
              tya
              clc
              adc ##6
              tay
              ldx ##0
mapTitleByte: lda abs:0,y
              and ##255
              sta dp:U_T2
              xba
              ora dp:U_T2
              sta dp:U_T2
              ora dp:U_T5
              sta long:titleGrayTable+0,x
              lda dp:U_T2
              ora dp:U_T6
              sta long:titleGrayTable+2,x
              lda dp:U_T2
              ora dp:U_T7
              sta long:titleGrayTable+4,x
              iny
              txa
              clc
              adc ##16
              tax
              cpx ##96
              bcc mapTitleByte
              sep #0x20
              lda long:composing
              beq titleLiveBank
              lda #0x3c
              bra titleChosenBank
titleLiveBank: lda #0xe1
titleChosenBank: pha
              plb
              rep #0x20
              lda ##.word0 (titleGrayTable)
              sta dp:U_T4
              lda ##0x41
              sta dp:U_T4+2
              ldx dp:U_T0
              lda dp:U_T1
              asl a
              asl a
              clc
              adc dp:U_T1
              asl a
              asl a
              asl a
              asl a
              sta dp:U_T3
              stz dp:U_T0
shadeTitleWord:
              lda abs:0,x
              beq shadeTitleNext0
              cmp dp:U_T0
              beq shadeTitleRepeat0
              sta dp:U_T0
              and ##255
              tay
              sep #0x20
              lda [U_T4],y
              sta dp:U_T7
              lda dp:U_T0+1
              tay
              lda [U_T4],y
              sta dp:U_T7+1
              rep #0x20
              ldy dp:U_T7
shadeTitleRepeat0: tya
              sta abs:0,x
shadeTitleNext0:
              lda abs:2,x
              beq shadeTitleNext1
              cmp dp:U_T0
              beq shadeTitleRepeat1
              sta dp:U_T0
              and ##255
              tay
              sep #0x20
              lda [U_T4],y
              sta dp:U_T7
              lda dp:U_T0+1
              tay
              lda [U_T4],y
              sta dp:U_T7+1
              rep #0x20
              ldy dp:U_T7
shadeTitleRepeat1: tya
              sta abs:2,x
shadeTitleNext1:
              lda abs:4,x
              beq shadeTitleNext2
              cmp dp:U_T0
              beq shadeTitleRepeat2
              sta dp:U_T0
              and ##255
              tay
              sep #0x20
              lda [U_T4],y
              sta dp:U_T7
              lda dp:U_T0+1
              tay
              lda [U_T4],y
              sta dp:U_T7+1
              rep #0x20
              ldy dp:U_T7
shadeTitleRepeat2: tya
              sta abs:4,x
shadeTitleNext2:
              lda abs:6,x
              beq shadeTitleNext3
              cmp dp:U_T0
              beq shadeTitleRepeat3
              sta dp:U_T0
              and ##255
              tay
              sep #0x20
              lda [U_T4],y
              sta dp:U_T7
              lda dp:U_T0+1
              tay
              lda [U_T4],y
              sta dp:U_T7+1
              rep #0x20
              ldy dp:U_T7
shadeTitleRepeat3: tya
              sta abs:6,x
shadeTitleNext3:
              lda abs:8,x
              beq shadeTitleNext4
              cmp dp:U_T0
              beq shadeTitleRepeat4
              sta dp:U_T0
              and ##255
              tay
              sep #0x20
              lda [U_T4],y
              sta dp:U_T7
              lda dp:U_T0+1
              tay
              lda [U_T4],y
              sta dp:U_T7+1
              rep #0x20
              ldy dp:U_T7
shadeTitleRepeat4: tya
              sta abs:8,x
shadeTitleNext4:
              lda abs:10,x
              beq shadeTitleNext5
              cmp dp:U_T0
              beq shadeTitleRepeat5
              sta dp:U_T0
              and ##255
              tay
              sep #0x20
              lda [U_T4],y
              sta dp:U_T7
              lda dp:U_T0+1
              tay
              lda [U_T4],y
              sta dp:U_T7+1
              rep #0x20
              ldy dp:U_T7
shadeTitleRepeat5: tya
              sta abs:10,x
shadeTitleNext5:
              lda abs:12,x
              beq shadeTitleNext6
              cmp dp:U_T0
              beq shadeTitleRepeat6
              sta dp:U_T0
              and ##255
              tay
              sep #0x20
              lda [U_T4],y
              sta dp:U_T7
              lda dp:U_T0+1
              tay
              lda [U_T4],y
              sta dp:U_T7+1
              rep #0x20
              ldy dp:U_T7
shadeTitleRepeat6: tya
              sta abs:12,x
shadeTitleNext6:
              lda abs:14,x
              beq shadeTitleNext7
              cmp dp:U_T0
              beq shadeTitleRepeat7
              sta dp:U_T0
              and ##255
              tay
              sep #0x20
              lda [U_T4],y
              sta dp:U_T7
              lda dp:U_T0+1
              tay
              lda [U_T4],y
              sta dp:U_T7+1
              rep #0x20
              ldy dp:U_T7
shadeTitleRepeat7: tya
              sta abs:14,x
shadeTitleNext7:
              txa
              clc
              adc ##16
              tax
              lda dp:U_T3
              sec
              sbc ##8
              sta dp:U_T3
              beq shadeTitleDone
              jmp abs:.word0 (shadeTitleWord)
shadeTitleDone:
              plb
              ply
              rtl
titleGrayTable: .space 256

              .extern menuDim, RemapSlot
              .public FillRectCore, fillTargetByte, fillTargetWord
FillRectCore:     lda abs:.word0 (menuDim)
              bne fillMapped
              jsr abs:.word0 (fillBody)
              rtl
fillMapped:
              lda dp:U_C
              pha
              jsl long:RemapSlot
              sta dp:U_C
              jsr abs:.word0 (fillBody)
              pla
              sta dp:U_C
              rtl
fillBody:     lda dp:U_Y
              asl a
              asl a
              clc
              adc dp:U_Y
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:U_DST
              lda dp:U_X
              lsr a
              clc
              adc dp:U_DST
              sta dp:U_DST
              lda dp:U_W
              lsr a
              sta dp:U_T0                 ; bytes in a row
              lda dp:U_C
              asl a
              asl a
              asl a
              asl a
              ora dp:U_C
              and ##255
              sta dp:U_T1
              xba
              ora dp:U_T1
              sta dp:U_T1                 ; the color byte twice
fillRow:      lda dp:U_DST
              cmp dp:UC_FIRST
              bcc fillNext
              cmp dp:UC_END
              bcs fillNext
              ldx dp:U_DST
              lda dp:U_T0
              lsr a
              sta dp:U_T2                 ; whole words
              bcc fillWords
              sep #0x20
              lda dp:U_T1
fillTargetByte:
              sta long:SHR,x
              rep #0x20
              inx
fillWords:    ldy dp:U_T2
              beq fillNext
              lda dp:U_T1
fillTargetWord:
fillWord:     sta long:SHR,x
              inx
              inx
              dey
              bne fillWord
fillNext:     lda dp:U_DST
              clc
              adc ##160
              sta dp:U_DST
              dec dp:U_H
              bne fillRow
              rts


              .public SetListHighlight
              .extern listClean, listFont, listPictures
;;; Six backdrop grays are identical in both palettes; only font ink changes.
;;; The gun is the cursor. Row palettes stay on the menu palette.
SetListHighlight:
              rtl
              lda long:listPictures
              bne highlightDone
              jsl long:WaitBlank
              lda long:listClean
              bne highlightNew
              lda long:highlightOldY
              tax
              ldy ##10
              lda long:listFont
              beq highlightResetHeight
              ldy ##17
highlightResetHeight:
              sep #0x20
              lda #15
highlightReset: sta long:SHR_SCB,x
              inx
              dey
              bne highlightReset
              rep #0x20
highlightNew: lda dp:UL_CUR
              sec
              sbc dp:UL_TOP
              tax
              lda ##0
highlightRow: cpx ##0
              beq highlightAt
              clc
              adc dp:UL_STEP
              dex
              bra highlightRow
highlightAt:  clc
              adc dp:UL_Y
              dec a
              sta long:highlightOldY
              tax
              ldy ##10
              lda long:listFont
              beq highlightSetHeight
              ldy ##17
highlightSetHeight:
              sep #0x20
              lda #14
highlightScb: sta long:SHR_SCB,x
              inx
              dey
              bne highlightScb
              rep #0x20
highlightDone: rtl

              .public RenderPage, RenderFadePage, pageCallback, pageBlack
              .extern PageCall, GrayCopyRows, ConvertRange, ConvertHidden
;;; A whole slideshow page under already-black palettes. Reuse the paused
;;; frame and normal drawing callback, then let FadeIn reveal the result.
RenderFadePage:
              txa
              sta long:pageCallback
              lda ##1
              sta long:framePending
              jsl long:ConvertHidden
              lda ##0
              sta long:menuFresh
              lda ##200
              sta long:pageBottom
              jsr abs:.word0 (FrameBegin)
              jsl long:PageCall
              jsl long:FrameFadePresent
              rtl
;;; A near bank3F painting callback, replayed with clipping in four strips.
RenderPage:   txa
              pha
              lda ##0
              sta long:oldLeft
              lda ##320
              sta long:oldRight
              lda ##200
              sta long:oldBottom
              pla
              sta long:pageCallback
              lda long:menuFresh
              beq renderCompose
              lda long:pageBlack
              bne renderCompose
              lda ##0
              sta long:menuFresh
              lda ##0
              ldx ##200
              jsl long:ConvertRange
              lda ##0x2000
              sta dp:UD_BASE
              jsl long:PageCall
              rtl
renderCompose: lda long:pageBlack
              bne renderStrips
              lda ##0
              sta long:menuFresh
              lda ##0
              ldx ##200
              jsl long:GrayCopyRows
              lda ##0x2000
              sta dp:UD_BASE
              jsl long:PageCall
              rtl
renderStrips: lda ##1
              sta long:pagePainting
              lda ##0
              sta long:renderY
              sta long:menuFresh
              sta long:pageSkipEnd
              sta long:pageSkipBottom
renderStrip:  stz dp:U_X
              lda long:renderY
              sta dp:U_Y
              lda ##320
              sta dp:U_W
              lda ##50
              sta dp:U_H
              jsr abs:.word0 (UpdateSetup)
              lda long:pageBlack
              beq renderGray
              stz dp:U_C
              jsl long:FillRectCore
              bra renderPaint
renderGray:   jsl long:GrayRect
renderPaint:  jsl long:PageCall
              jsl long:EndUpdate
              lda long:renderY
              clc
              adc ##50
              sta long:renderY
              cmp ##200
              bcc renderStrip
              lda ##0
              sta long:pagePainting
              rtl
pageCallback: .word 0
pageBlack:    .word 0
renderY:      .word 0

highlightOldY: .word 0
pagePainting: .word 0
              .public updatePalette, updateSCB
updatePalette: .word 0
updateSCB: .space 200

              .public ListCursorCore
              .extern ListPositionLong, ListMulLong, cursorX, cursorY, DrawCursorCore
ListCursorCore:
cursorPlace:  lda dp:UL_CUR
              sec
              sbc dp:UL_TOP
              jsl long:ListPositionLong
              ldx dp:UL_STEP
              jsl long:ListMulLong
              clc
              adc dp:UL_Y
              sec
              sbc ##2
              sta dp:U_Y
              lda dp:UL_ROWX
              sec
              sbc dp:UL_X
              clc
              adc dp:UL_CX
              sta dp:U_X
              lda abs:.word0 (listClean)
              bne cursorNew
              lda dp:U_X
              cmp abs:.word0 (cursorX)
              bne cursorOld
              lda dp:U_Y
              cmp abs:.word0 (cursorY)
              beq cursorNew
cursorOld:    lda dp:U_X
              pha
              lda dp:U_Y
              pha
              lda abs:.word0 (cursorX)
              sta dp:U_X
              lda abs:.word0 (cursorY)
              sta dp:U_Y
              jsr abs:.word0 (CursorBounds)
              jsl long:BeginUpdate
              jsl long:EndUpdate
              pla
              sta dp:U_Y
              pla
              sta dp:U_X
cursorNew:    lda dp:U_X
              sta abs:.word0 (cursorX)
              lda dp:U_Y
              sta abs:.word0 (cursorY)
              lda abs:.word0 (listClean)
              bne cursorDirect
              jsr abs:.word0 (CursorBounds)
              jsl long:BeginUpdate
cursorDirect: lda abs:.word0 (cursorX)
              sta dp:U_X
              lda long:listFont
              cmp ##1
              beq cursorLarge
              lda ##PIC_COMMON_SMALLCURSOR1
              ldx dp:UL_FRAME
              beq cursorFrame
              lda ##PIC_COMMON_SMALLCURSOR2
              bra cursorFrame
cursorLarge:  lda ##PIC_COMMON_CURSOR1
              ldx dp:UL_FRAME
              beq cursorFrame
              lda ##PIC_COMMON_CURSOR2
cursorFrame:  clc
              adc ##.word0 UI_STAGE
              sta dp:U_SRC
              jsl long:DrawCursorCore
              lda abs:.word0 (listClean)
              bne cursorDone
              jsl long:EndUpdate
              jsr abs:.word0 (MenuMark)
cursorDone:   rtl
CursorBounds: lda dp:U_X
              and ##0xfffc
              sta dp:U_X
              lda ##24
              sta dp:U_W
              lda ##12
              sta dp:U_H
              lda long:listFont
              cmp ##1
              bne cursorBoundsDone
              lda ##28
              sta dp:U_W
              lda ##16
              sta dp:U_H
cursorBoundsDone: rts


              .public menuFresh, composing
menuFresh: .word 0
composing: .word 0

              .public menuPaletteDirty, busyProgress
menuPaletteDirty: .word 0
busyProgress: .word 0

              .public BuildMenuPal
BuildMenuPal: ldx ##30
menuColors:   lda long:menuSteel,x
              sta long:MENU_COL,x
              dex
              dex
              bpl menuColors
              rtl
;;; Menu lettering and the composed gray backdrop use this palette. Picture
;;; palettes retain their own colors in approximately aligned slot roles.
menuSteel:
#include "steel-palette.inc"

#include "ui_frame.inc"

#include "ui_busy.inc"

#include "ui_psyched.inc"
