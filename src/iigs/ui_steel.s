#include "memmap.inc"
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public DrawGlyphCore
              .public steelOverlay
              .extern steelWidths, steelOffsets, steelBanks, steelBright, steelMuted

DrawGlyphCore:
steelGlyph:   ldx dp:U_K
              ldy dp:U_K
              sep #0x20
              lda (U_FW),y
              rep #0x20
              and ##255
              sta dp:SF_ADV
              cpx ##0
              bne steelInk
              jmp abs:.word0 (steelDone)
steelInk:     sep #0x20
              lda #.byte0 (steelShadeDone-steelShade-2)
              sta long:steelShade+1
              lda long:steelOverlay
              beq steelMenuInk
              rep #0x20
              lda ##0x0600
              sta long:steelMapLoad+1
              sep #0x20
              lda #0x3b
              bra steelMapBank
steelMenuInk:
              lda dp:U_C
              cmp #C_WHITE
              beq steelMapped
              cmp #C_DKRED
              bne steelSource
steelMapped:  cmp #C_WHITE
              bne steelChooseMuted
              rep #0x20
              lda ##.word0 (steelBright)
              bra steelChooseMap
steelChooseMuted: rep #0x20
              lda ##.word0 (steelMuted)
steelChooseMap: sta long:steelMapLoad+1
              sep #0x20
              lda #0x3f
steelMapBank: sta long:steelMapLoad+3
              lda #0
              sta long:steelShade+1
steelSource:
              lda (U_FG),y
              sta dp:SF_PTR+2
              rep #0x20
              txa
              asl a
              tay
              lda (U_FO),y
              sta dp:SF_PTR
              ldy ##0
              lda [SF_PTR],y
              and ##255
              sta dp:SF_WIDTH
              iny
              lda [SF_PTR],y
              and ##255
              sta dp:SF_ROWS
              iny
              lda [SF_PTR],y
              and ##255
              iny
              clc
              adc dp:U_Y
              dec a
              sta dp:SF_ROW
              asl a
              asl a
              clc
              adc dp:SF_ROW
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:SF_ROW
              lda dp:U_X
              dec a
              and ##1
              sta dp:SF_X
              lda dp:U_X
              dec a
              lsr a
              clc
              adc dp:SF_ROW
              sta dp:SF_ROW
              lda dp:SF_WIDTH
              inc a
              lsr a
              sta dp:SF_WIDTH
steelRow:     lda dp:SF_ROW
              cmp dp:UC_FIRST
              bcc steelClip
              cmp dp:UC_END
              bcc steelVisible
steelClip:    tya
              clc
              adc dp:SF_WIDTH
              tay
              jmp abs:.word0 (steelNext)
steelVisible: ldx dp:SF_ROW
              lda dp:SF_WIDTH
              sta dp:SF_COL
              sep #0x20
              lda #STEEL_TRANSPARENT*16
              sta dp:SF_BYTE
steelByte:    lda [SF_PTR],y
              iny
steelShade:   bra steelShadeDone
              phx
              rep #0x20
              and ##255
              tax
              sep #0x20
steelMapLoad: lda long:steelBright,x
steelShadePop: plx
steelShadeDone: sta dp:U_BITS
              lda dp:SF_X
              beq steelEven
              lda dp:U_BITS
              lsr a
              lsr a
              lsr a
              lsr a
              ora dp:SF_BYTE
              pha
              lda dp:U_BITS
              asl a
              asl a
              asl a
              asl a
              sta dp:SF_BYTE
              pla
              bra steelPut
steelEven:    lda dp:U_BITS
steelPut:     jsr abs:.word0 (steelPair)
              dec dp:SF_COL
              bne steelByte
              lda dp:SF_X
              beq steelNext
              lda dp:SF_BYTE
              ora #STEEL_TRANSPARENT
              jsr abs:.word0 (steelPair)
steelNext:    rep #0x20
              lda dp:SF_ROW
              clc
              adc ##160
              sta dp:SF_ROW
              dec dp:SF_ROWS
              beq steelDone
              jmp abs:.word0 (steelRow)
steelDone:    lda dp:U_X
              clc
              adc dp:SF_ADV
              sta dp:U_X
              rtl

;;; Transparency follows the font encoding; outline 0 remains opaque.
steelPair:    cmp #STEEL_TRANSPARENT*17
              beq steelSkip
              sta dp:U_BITS
              and #15
              cmp #STEEL_TRANSPARENT
              beq steelHigh
              lda dp:U_BITS
              and #0xf0
              cmp #STEEL_TRANSPARENT*16
              beq steelLow
              lda dp:U_BITS
              bra steelStore
steelTargetHigh:
steelHigh:    lda long:SHR,x
              and #15
              sta dp:U_C4
              lda dp:U_BITS
              and #0xf0
              ora dp:U_C4
              bra steelStore
steelTargetLow:
steelLow:     lda long:SHR,x
              and #0xf0
              sta dp:U_C4
              lda dp:U_BITS
              and #15
              ora dp:U_C4
steelStore:
steelRecolor: bra steelFinal
              cmp long:SHR,x
              beq steelSkip
steelTargetStore:
steelFinal:   sta long:SHR,x
steelSkip:    inx
              rts

              .public steelTargetHigh, steelTargetLow, steelTargetStore, steelRecolor
steelOverlay: .word 0
