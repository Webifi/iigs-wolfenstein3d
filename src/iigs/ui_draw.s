;;; Menu drawing: rectangles, pictures, proportional text and display lists.
;;; Runs in bank $3F with DBR = $3F, A and X/Y 16 bits. Pictures are two
;;; 4-bit pixels a byte in palette slots; fonts are resident 1-bit glyphs.
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public DrawList, FillRect, DrawStr, StrWidth, RowOffset
              .public SaveBox, RestoreBox, NumToStr, Num32ToStr, DrawStrRight, DrawStrCenter
              .public numBuf
              .extern DrawGlyphCore, DrawTitleCore
              .extern TryWord, listInk
              .extern fontInfo, menuDim, RemapSlot, RemapByte, fadeBase

;;; A = row * 160
RowOffset:    sta dp:U_T7
              asl a
              asl a
              clc
              adc dp:U_T7
              asl a
              asl a
              asl a
              asl a
              asl a
              rts

;;; U_DST = screen byte offset of pixel (U_X, U_Y)
PlaceXY:      lda dp:U_Y
              jsr abs:.word0 (RowOffset)
              sta dp:U_DST
              lda dp:U_X
              lsr a
              clc
              adc dp:U_DST
              sta dp:U_DST
              rts

;;; Fill U_W by U_H pixels at (U_X, U_Y) with slot U_C. X and W are even.
;;; Over the gray menu the slot is remapped, and U_C itself is put back.
              .extern FillRectCore
FillRect:     jsl long:FillRectCore
              rts

;;; Save or restore U_H rows of U_WB bytes at (U_X, U_Y) to or from UI_BOXBUF.
SaveBox:      jsr abs:.word0 (PlaceXY)
              lda ##160
              sec
              sbc dp:U_WB
              sta dp:U_T0
              lda dp:U_DST
              clc
              adc ##0x2000
              tax
              ldy ##.word0 UI_BOXBUF
saveRow:      lda dp:U_WB
              dec a
              .byte 0x54, 0x3f, 0xe1       ; MVN: the screen to bank $3F
              phk
              plb
              txa
              clc
              adc dp:U_T0
              tax
              dec dp:U_H
              bne saveRow
              rts

RestoreBox:   jsr abs:.word0 (PlaceXY)
              lda ##160
              sec
              sbc dp:U_WB
              sta dp:U_T0
              ldx ##.word0 UI_BOXBUF
              lda dp:U_DST
              clc
              adc ##0x2000
              tay
restoreRow:   lda dp:U_WB
              dec a
              .byte 0x54, 0xe1, 0x3f
              phk
              plb
              tya
              clc
              adc dp:U_T0
              tay
              dec dp:U_H
              bne restoreRow
              rts

;;; Select font U_FONT: U_FH, U_FW, U_FO, U_FG
SetFont:      lda dp:U_FONT
              asl a
              asl a
              asl a
              tax
              lda abs:.word0 (fontInfo),x
              sta dp:U_FH
              lda abs:.word0 (fontInfo + 2),x
              sta dp:U_FW
              lda abs:.word0 (fontInfo + 4),x
              sta dp:U_FO
              lda abs:.word0 (fontInfo + 6),x
              sta dp:U_FG
              rts

;;; Width in pixels of the string at U_STR in font U_FONT; A = width.
StrWidth:     jsr abs:.word0 (SetFont)
              ldy ##0
              ldx ##0
widthNext:    sep #0x20
              lda (U_STR),y
              rep #0x20
              and ##255
              beq widthDone
              iny
              sec
              sbc ##32
              cmp ##95
              bcs widthNext
              phy
              tay
              sep #0x20
              lda (U_FW),y
              rep #0x20
              and ##255
              stx dp:U_T0
              clc
              adc dp:U_T0
              tax
              ply
              bra widthNext
widthDone:    txa
              rts

;;; Draw the string at U_STR with its right end at U_X.
DrawStrRight: jsr abs:.word0 (StrWidth)
              sta dp:U_T6
              lda dp:U_X
              sec
              sbc dp:U_T6
              sta dp:U_X
              bra DrawStr

;;; Draw the string at U_STR centered on U_X.
DrawStrCenter:
              jsr abs:.word0 (StrWidth)
              lsr a
              sta dp:U_T6
              lda dp:U_X
              sec
              sbc dp:U_T6
              sta dp:U_X

;;; Draw the zero-terminated string at U_STR with its top left at (U_X, U_Y),
;;; font U_FONT, slot U_C. Characters outside 32-126 are skipped. U_STR
;;; ends after the zero and U_X after the last glyph.
DrawStr:      lda abs:.word0 (listInk)
              beq strInkReady
              lda dp:U_C
              cmp ##C_WHITE
              bne strInkReady
              lda ##C_GRAY
              sta dp:U_C
strInkReady:      jsl long:TryWord
              bcs cachedWord
              jsr abs:.word0 (SetFont)
              lda dp:U_C
              asl a
              asl a
              asl a
              asl a
              sta dp:U_C4
strNext:      sep #0x20
              lda (U_STR)
              rep #0x20
              and ##255
              beq strDone
              inc dp:U_STR
              sec
              sbc ##32
              cmp ##95
              bcs strNext
              sta dp:U_K
              jsr abs:.word0 (DrawGlyph)
              bra strNext
strDone:      inc dp:U_STR
cachedWord:   rts
;;; Glyph U_K at (U_X, U_Y); U_X moves on by its width.
DrawGlyph:    jsl long:DrawGlyphCore
              rts

;;; Display list at X: 3 text, 4 resident heading, 0 end.
DrawList:     lda abs:0,x
              beq listDone


              cmp ##3
              bne dispatch3
              jmp abs:.word0 (listText)
dispatch3:
              cmp ##4
              bne dispatch4
              jmp abs:.word0 (listTitle)
dispatch4:
listDone:     rts
listTitle:    lda abs:2,x
              clc
              adc ##.word0 UI_STAGE
              sta dp:U_SRC
              lda abs:4,x
              sta dp:U_Y
              phx
              jsl long:DrawTitleCore
              plx
              txa
              clc
              adc ##6
              tax
              jmp abs:.word0 (DrawList)
listText:     lda abs:2,x
              sta dp:U_X
              lda abs:4,x
              sta dp:U_Y
              lda abs:6,x
              sta dp:U_FONT
              lda abs:8,x
              sta dp:U_C
              txa
              clc
              adc ##10
              sta dp:U_STR
              jsr abs:.word0 (DrawStr)
              ldx dp:U_STR
              jmp abs:.word0 (DrawList)

;;; A = 0..65535 as decimal in numBuf; U_STR points at it.
              .extern NumToStrCore, Num32ToStrCore
NumToStr:     jsl long:NumToStrCore
              rts
Num32ToStr:   jsl long:Num32ToStrCore
              rts

              .section menudata, data, root
              .public power10, power32, numBuf
power10:      .word 10000, 1000, 100, 10
power32:      .word 0xe100, 0x05f5          ; 100000000
              .word 0x9680, 0x0098          ; 10000000
              .word 0x4240, 0x000f          ; 1000000
              .word 0x86a0, 0x0001          ; 100000
              .word 10000, 0
              .word 1000, 0
              .word 100, 0
              .word 10, 0
numBuf:       .space 12
