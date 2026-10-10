#include "memmap.inc"
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public RowSelectInit, RowSelectMove, rowCacheValid
              .extern listPictures, ListPositionLong, ListMulLong, steelBright, framePending
;;; The selected item's normal ink bytes share the paused busy-box scratch.
;;; A new page invalidates this cache before any composition.
RowSelectInit: lda ##1
              sta abs:.word0 (rowCacheValid)
              jsr abs:.word0 (RowGeometry)
              lda dp:RC_ROW
              clc
              adc dp:UD_BASE
              sta dp:RC_SOURCE
              sta long:rowSource+1
              sta long:rowWrite+1
              lda ##0x3c
rowInitBank:  sta dp:RC_SOURCE+2
              sep #0x20
              sta long:rowSource+3
              sta long:rowWrite+3
              rep #0x20
              jsr abs:.word0 (RowSelect)
              rtl
RowSelectMove:
              jsr abs:.word0 (RowGeometrySaved)
              jsr abs:.word0 (RowLiveTarget)
              lda dp:RC_CACHE
              sta dp:RC_SOURCE
              lda ##0x3f
              sta dp:RC_SOURCE+2
              jsr abs:.word0 (RowRestore)
              lda dp:UL_CUR
              sec
              sbc dp:UL_TOP
              jsl long:ListPositionLong
              ldx dp:UL_STEP
              jsl long:ListMulLong
              clc
              adc dp:UL_Y
              sta dp:UL_ROWY
              jsr abs:.word0 (RowGeometry)
              jsr abs:.word0 (RowLiveTarget)
              lda dp:RC_ROW
              clc
              adc ##0x2000
              sta dp:RC_SOURCE
              lda ##0xe1
              sta dp:RC_SOURCE+2
              jsr abs:.word0 (RowSelect)
              rtl
RowGeometry:  lda dp:UL_ROWY
              dec a
              asl a
              asl a
              clc
              adc dp:UL_ROWY
              dec a
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:RC_ROW
              lda dp:UL_ROWX
              dec a
              and ##0xfffc
              lsr a
              clc
              adc dp:RC_ROW
              sta abs:.word0 (rowSaved)
RowGeometrySaved:
              lda abs:.word0 (rowSaved)
              sta dp:RC_ROW
              lda dp:UL_WIDTH
              clc
              adc ##7
              and ##0xfffc
              lsr a
              sta dp:RC_WIDTH
              lda ##.word0 (UI_BOXBUF)
rowCacheBase: sta dp:RC_CACHE
              lda ##0x3f
              sta dp:RC_CACHE+2
              lda ##13
              sta dp:RC_HEIGHT
              rts
RowLiveTarget: lda dp:RC_ROW
              clc
              adc ##0x2000
              sta long:rowSource+1
              sta long:rowWrite+1
              sep #0x20
              lda #0xe1
              sta long:rowSource+3
              sta long:rowWrite+3
              rep #0x20
              rts
RowSelect:    ldx ##0
              lda ##65535
              sta dp:RC_NORMAL
rowSelectRow: lda dp:RC_WIDTH
              sta dp:RC_ROW
              sep #0x20
rowSource:    lda long:SHR,x
              sta dp:RC_INK
              tay
              lda abs:.word0 (steelBright),y
              cmp dp:RC_INK
              beq rowSelectSame
              jsr abs:.word0 (rowWrite)
              rep #0x20
              txa
              sec
              sbc dp:RC_NORMAL
rowDistance:  cmp ##255
              bcc rowShortDistance
              pha
              sep #0x20
              lda #255
              sta [RC_CACHE]
              rep #0x20
              inc dp:RC_CACHE
              pla
              sec
              sbc ##254
              bra rowDistance
rowShortDistance:
              sep #0x20
              sta [RC_CACHE]
              ldy ##1
              lda dp:RC_INK
              sta [RC_CACHE],y
              rep #0x20
              stx dp:RC_NORMAL
              inc dp:RC_CACHE
              inc dp:RC_CACHE
              sep #0x20
rowSelectSame: inx
              dec dp:RC_ROW
              bne rowSource
              rep #0x20
              txa
              sec
              sbc dp:RC_WIDTH
              clc
              adc ##160
              tax
              dec dp:RC_HEIGHT
              bne rowSelectRow
              sep #0x20
              lda #0
              sta [RC_CACHE]
              rep #0x20
              rts
;;; An undo pair holds distance 1..254 and the original byte. A lone $FF
;;; advances 254 bytes without a write; zero ends the list. Sparse ink may
;;; leave more than a scanline between changes. Restore never reads SHR.
RowRestore:   ldx ##0xffff
              ldy ##0
              sep #0x20
rowUndo:      lda [RC_CACHE],y
              beq rowUndoDone
              cmp #255
              beq rowUndoSkip
              rep #0x20
              and ##255
              sta dp:RC_INK
              txa
              clc
              adc dp:RC_INK
              tax
              sep #0x20
              iny
              lda [RC_CACHE],y
              jsr abs:.word0 (rowWrite)
              iny
              bra rowUndo
rowUndoSkip:  rep #0x20
              txa
              clc
              adc ##254
              tax
              sep #0x20
              iny
              bra rowUndo
rowUndoDone:  rep #0x20
              rts
rowWrite:     sta long:SHR,x
              rts
rowSaved: .word 0
rowCacheValid: .word 0
