;;; Resolve each nibble independently, then write its byte once. Each screen
;;; column finishes before the next; no store scheduling or cache is assumed.
#include "memmap.inc"
#include "game.inc"
#include "picture_config.inc"
#if WOLF_TRUE_PIXELS
              .section gamecode, text, root, noreorder
              .public PaintTrueFrame
              .extern ComposeAndPaint, viewWidth, viewTop, viewBottom, viewLeft
              .extern heightIndex, sourceAddr, sourceBank, oldHeight, oldSource
              .extern oldBank, spanBuffer, screenRows, rowTexBase, flatNonempty
              .extern texturedSpan

PaintTrueFrame:
              stz dp:COL
truePair:     jsr abs:.word0 (truePairDirty)
              bcs changedTruePair
              jmp abs:.word0 (nextTruePair)
changedTruePair:
              lda dp:COL
              asl a
              sta dp:SCAN
              tax
              lda abs:.word0 (heightIndex),x
              sta dp:HEIGHT
              jsr abs:.word0 (ComposeAndPaint)
              lda dp:SP_FPOS
              dec a
              ldx ##.word0 (spanBuffer)
              ldy ##.word0 (trueLeftSpans)
              .byte 0x54,0x02,0x02      ; only metadata, both sides in fast RAM
              inc dp:COL
              lda dp:COL
              asl a
              sta dp:SCAN
              tax
              lda abs:.word0 (heightIndex),x
              sta dp:HEIGHT
              jsr abs:.word0 (ComposeAndPaint)
              dec dp:COL
              jsr abs:.word0 (paintTruePair)
              lda dp:COL
              asl a
              tax
              lda abs:.word0 (heightIndex),x
              sta abs:.word0 (oldHeight),x
              lda abs:.word0 (heightIndex+2),x
              sta abs:.word0 (oldHeight+2),x
              lda abs:.word0 (sourceAddr),x
              sta abs:.word0 (oldSource),x
              lda abs:.word0 (sourceAddr+2),x
              sta abs:.word0 (oldSource+2),x
              ldx dp:COL
              lda abs:.word0 (sourceBank),x
              sta abs:.word0 (oldBank),x
nextTruePair: inc dp:COL
              inc dp:COL
              lda dp:COL
              cmp abs:.word0 (viewWidth)
              bcs trueFrameDone
              jmp abs:.word0 (truePair)
trueFrameDone:
              stz dp:FIRST
              rts

;;; Invalidation covers old and new silhouettes. This optional mode avoids
;;; allocating a second 200 KB set of final-span caches for physical pixels.
truePairDirty:
              lda dp:FIRST
              bne trueDirty
              ldx dp:COL
              lda long:EXTRA_MASKS,x
              and ##0x0101
              bne trueDirty
              lda abs:.word0 (sourceBank),x
              cmp abs:.word0 (oldBank),x
              bne trueDirty
              txa
              asl a
              tax
              lda abs:.word0 (heightIndex),x
              cmp abs:.word0 (oldHeight),x
              bne trueDirty
              lda abs:.word0 (heightIndex+2),x
              cmp abs:.word0 (oldHeight+2),x
              bne trueDirty
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne trueDirty
              lda abs:.word0 (sourceAddr+2),x
              cmp abs:.word0 (oldSource+2),x
              bne trueDirty
              clc
              rts
trueDirty:    sec
              rts

paintTruePair:
              stz dp:SP_OLD
              stz dp:SP_SCAN
              lda abs:.word0 (viewTop)
              sta dp:SP_ROW
              sta dp:SP_END
              sta dp:SP_LIMIT
              jsr abs:.word0 (trueDestination)
trueRow:     lda dp:SP_ROW
              cmp dp:SP_END
              bcc leftOwnerReady
              jsr abs:.word0 (trueLeftOwner)
leftOwnerReady:
              lda dp:SP_ROW
              cmp dp:SP_LIMIT
              bcc rightOwnerReady
              jsr abs:.word0 (trueRightOwner)
rightOwnerReady:
              lda dp:ENTRY+2
              ora dp:EXITP+2
              bne trueTexturedRow
              jsr abs:.word0 (trueFlatRun)
              bra nextTrueRow
trueTexturedRow:
              lda dp:ENTRY+2
              beq trueSampleRow
              lda dp:EXITP+2
              beq trueSampleRow
              lda abs:.word0 (trueLeftHeight)
              cmp abs:.word0 (trueRightHeight)
              bne trueSampleRow
              jsr abs:.word0 (trueMatchedRun)
              bra nextTrueRow
trueSampleRow:
              lda dp:ENTRY+2
              beq trueLeftFlat
              lda dp:TP_LBASE
              clc
              adc dp:SP_ROW
              tax
              lda long:NP_TRUE_ROWTEX,x
              and ##255
              asl a
              ora dp:TP_PARITY
              tay
              sep #0x20
              lda [ENTRY],y
              bra trueLeftNibble
trueLeftFlat:
              sep #0x20
              lda dp:ENTRY
trueLeftNibble:
              and #0xf0
              sta dp:TP_PIXEL
              rep #0x20
              lda dp:EXITP+2
              beq trueRightFlat
              lda dp:TP_RBASE
              clc
              adc dp:SP_ROW
              tax
              lda long:NP_TRUE_ROWTEX,x
              and ##255
              asl a
              ora dp:TP_PARITY
              tay
              sep #0x20
              lda [EXITP],y
              bra trueRightNibble
trueRightFlat:
              sep #0x20
              lda dp:EXITP
trueRightNibble:
              and #15
              ora dp:TP_PIXEL
              ldx dp:TP_DEST
              sta long:SHR,x
              rep #0x20
              lda dp:TP_DEST
              clc
              adc ##160
              sta dp:TP_DEST
              lda dp:TP_PARITY
              eor ##1
              sta dp:TP_PARITY
              inc dp:SP_ROW
nextTrueRow:  lda dp:SP_ROW
              cmp abs:.word0 (viewBottom)
              bcs truePairPainted
              jmp abs:.word0 (trueRow)
truePairPainted:
              rts

trueLeftOwner:
              ldy dp:SP_OLD
              lda abs:.word0 (trueLeftSpans),y
              xba
              and ##255
              sta dp:SP_END
              lda abs:.word0 (trueLeftSpans+2),y
              sta abs:.word0 (trueLeftHeight)
              tax
              lda abs:.word0 (rowTexBase),x
              sta dp:TP_LBASE
              lda abs:.word0 (trueLeftSpans+4),y
              sta dp:ENTRY
              lda abs:.word0 (trueLeftSpans+6),y
              and ##127
              sta dp:ENTRY+2
              tya
              clc
              adc ##8
              sta dp:SP_OLD
              rts
trueRightOwner:
              ldy dp:SP_SCAN
              lda abs:.word0 (spanBuffer),y
              xba
              and ##255
              sta dp:SP_LIMIT
              lda abs:.word0 (spanBuffer+2),y
              sta abs:.word0 (trueRightHeight)
              tax
              lda abs:.word0 (rowTexBase),x
              sta dp:TP_RBASE
              lda abs:.word0 (spanBuffer+4),y
              sta dp:EXITP
              lda abs:.word0 (spanBuffer+6),y
              and ##127
              sta dp:EXITP+2
              tya
              clc
              adc ##8
              sta dp:SP_SCAN
              rts

;;; Equal scales can share an ordinary row drawer. Form just the sampled
;;; A/B texels in 128 bytes of fast RAM, then paint this one screen column.
;;; The staging work is counted; it assumes no overlap with slow stores.
trueMatchedRun:
              lda dp:ENTRY
              pha
              lda dp:ENTRY+2
              pha
              lda dp:EXITP
              pha
              lda dp:EXITP+2
              pha
              lda dp:SP_END
              cmp dp:SP_LIMIT
              bcc trueMatchedEnd
              lda dp:SP_LIMIT
trueMatchedEnd:
              sta dp:SP_BOT
              dec a
              clc
              adc dp:TP_LBASE
              tax
              lda long:NP_TRUE_ROWTEX,x
              and ##255
              inc a
              asl a
              sta dp:TP_CAP
              lda dp:TP_LBASE
              clc
              adc dp:SP_ROW
              tax
              lda long:NP_TRUE_ROWTEX,x
              and ##255
              asl a
              tay
trueSymbol:   lda [ENTRY],y
              and ##0xf0f0
              sta dp:TP_PIXEL
              lda [EXITP],y
              and ##0x0f0f
              ora dp:TP_PIXEL
              sta abs:.word0 (trueSymbols),y
              iny
              iny
              cpy dp:TP_CAP
              bcc trueSymbol
              lda dp:SP_ROW
              sta dp:SP_TOP
              lda abs:.word0 (trueLeftHeight)
              sta dp:SP_HI
              lda ##.word0 (trueSymbols)
              sta dp:SP_SRC
              lda ##2
              sta dp:SP_BANK
              lda dp:COL
              lsr a
              clc
              adc abs:.word0 (viewLeft)
              sta dp:MULR
              jsr abs:.word0 (texturedSpan)
              pla
              sta dp:EXITP+2
              pla
              sta dp:EXITP
              pla
              sta dp:ENTRY+2
              pla
              sta dp:ENTRY
              lda dp:SP_BOT
              sta dp:SP_ROW
              jmp abs:.word0 (trueDestination)

;;; Flat runs use fixed stores. The clip routine borrows EXITP, so retain
;;; the right source pointer when its owner continues past the left run.
trueFlatRun:
              lda dp:EXITP
              pha
              lda dp:EXITP+2
              pha
              lda dp:SP_END
              cmp dp:SP_LIMIT
              bcc trueFlatEnd
              lda dp:SP_LIMIT
trueFlatEnd:  sta dp:SP_BOT
              sep #0x20
              lda dp:ENTRY
              and #0xf0
              sta dp:TP_PIXEL
              lda dp:EXITP
              and #15
              ora dp:TP_PIXEL
              sta dp:EXITBYTE
              rep #0x20
              lda dp:COL
              lsr a
              clc
              adc abs:.word0 (viewLeft)
              sta dp:MULR
              ldy dp:SP_BOT
              lda dp:SP_ROW
              jsr abs:.word0 (flatNonempty)
              pla
              sta dp:EXITP+2
              pla
              sta dp:EXITP
              lda dp:SP_BOT
              sta dp:SP_ROW
trueDestination:
              lda dp:SP_ROW
              and ##1
              sta dp:TP_PARITY
              lda dp:COL
              lsr a
              clc
              adc abs:.word0 (viewLeft)
              sta dp:TP_DEST
              lda dp:SP_ROW
              asl a
              tax
              lda abs:.word0 (screenRows),x
              clc
              adc dp:TP_DEST
              sta dp:TP_DEST
              rts

              .section gamedata, data, root
trueLeftSpans: .space 1284
trueLeftHeight: .word 0
trueRightHeight: .word 0
trueSymbols: .space 128
#endif
