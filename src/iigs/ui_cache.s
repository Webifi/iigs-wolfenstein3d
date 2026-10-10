;;; Pictures use the renderer's dead bank-0 span buffer only while play is paused.
;;; Every call decodes its first chunk again: a game frame may have reused it.
#include "frontend.inc"
#include "logic.inc"
#include "campaign.inc"
              .extern EnsureUIAssets
              .section menucopycode, text, root, noreorder
              .public CopyMenuBlocks, menuCopyDone

MC_BITS       .equ U_T0
MC_OFF        .equ U_T1
MC_INP        .equ U_T2
MC_CNT        .equ U_T3

;;; File block U_BLK, count U_CNT, destination U_DBNK:U_DOFF. DBR survives.
CopyMenuBlocks:
              jsl long:EnsureUIAssets
              phb
              phk
              plb
              lda ##0xffff
              sta abs:.word0 (menuChunk)
menuCopyNext: lda dp:U_CNT
              bne menuCopyBlock
              jmp abs:.word0 (menuCopyDone)
menuCopyBlock:
              lda dp:U_BLK
              lsr a
              lsr a
              lsr a
              sta dp:MC_INP
              asl a
              asl a
              tax
              lda long:menuCacheDirectory+2,x
              bit ##0x8000
              beq menuPacked
              jmp abs:.word0 (menuRaw)
menuPacked:
              ora long:menuCacheDirectory,x
              bne menuResident
              jsl long:ReadColdMenuBlocks
              plb
              rtl
menuResident:
              lda dp:MC_INP
              cmp abs:.word0 (menuChunk)
              beq menuChunkReady
              sta abs:.word0 (menuChunk)
              asl a
              asl a
              tax
              lda long:menuCacheDirectory,x
              tay
              sep #0x20
              lda long:menuCacheDirectory+2,x
              tyx
menuSource:
              sta abs:.word0 (menuLiteral+2)
              sta abs:.word0 (menuReadByte+3)
              sta abs:.word0 (menuReadWord+3)
              rep #0x20
              lda ##0x8000
              sta dp:MC_BITS
              lda ##1
              sta dp:MC_OFF
              ldy ##0x2000
              jsr abs:.word0 (menuLiterals)
              phk
              plb
menuChunkReady:
              sep #0x20
              lda dp:U_DBNK
              sta abs:.word0 (menuBlock+1)
              rep #0x20
              lda dp:U_BLK
              and ##7
              xba
              asl a
              clc
              adc ##0x2000
              tax
              ldy dp:U_DOFF
              lda ##511
menuBlock:    .byte 0x54, 0x00, 0x00
menuBlockCopied: phk
              plb
              sty dp:U_DOFF
              inc dp:U_BLK
              dec dp:U_CNT
              jmp abs:.word0 (menuCopyNext)
menuRaw:      sep #0x20
              sta abs:.word0 (menuRawMove+2)
              lda dp:U_DBNK
              sta abs:.word0 (menuRawMove+1)
              rep #0x20
              lda long:menuCacheDirectory,x
              sta dp:MC_INP
              lda dp:U_BLK
              and ##7
              xba
              asl a
              clc
              adc dp:MC_INP
              tax
              ldy dp:U_DOFF
              lda ##511
menuRawMove:  .byte 0x54, 0x3f, 0x0a
              jmp abs:.word0 (menuBlockCopied)
menuCopyDone: plb
              clc
              rtl

;;; The loader's B1 decoder, with a fixed 4 KB output window and IRQs enabled.
menuLiterals: jsr abs:.word0 (menuGamma)
              dec a
menuLiteral:  .byte 0x54, 0x00, 0x00
              cpy ##0x3000
              beq menuDecoded
              asl dp:MC_BITS
              bne menuLiteralBit
              jsr abs:.word0 (menuRefill)
menuLiteralBit:
              bcs menuNewOffset
              jsr abs:.word0 (menuGamma)
              bra menuMatch
menuNewOffset:
              jsr abs:.word0 (menuGamma)
              dec a
              xba
              sep #0x20
menuReadByte: lda long:0x000000,x
              rep #0x20
              inx
              lsr a
              inc a
              sta dp:MC_OFF
              jsr abs:.word0 (menuGammaCarry)
              inc a
menuMatch:    dec a
              sta dp:MC_CNT
              stx dp:MC_INP
              tya
              sec
              sbc dp:MC_OFF
              tax
              lda dp:MC_CNT
              .byte 0x54, 0x00, 0x00
              ldx dp:MC_INP
              cpy ##0x3000
              beq menuDecoded
              asl dp:MC_BITS
              bne menuMatchBit
              jsr abs:.word0 (menuRefill)
menuMatchBit: bcc menuLiterals
              bra menuNewOffset
menuDecoded:  rts

menuGamma:    lda ##1
menuGamma0:   asl dp:MC_BITS
              bne menuGamma1
              jsr abs:.word0 (menuRefill)
menuGamma1:   bcs menuGamma3
              asl dp:MC_BITS
              bne menuGamma2
              jsr abs:.word0 (menuRefill)
menuGamma2:   rol a
              bra menuGamma0
menuGamma3:   rts
menuGammaCarry:
              lda ##1
              bra menuGamma1
menuRefill:   pha
menuReadWord: lda long:0x000000,x
              inx
              inx
              sec
              rol a
              sta dp:MC_BITS
              pla
              rts

              .section menucopydata, data, root
menuChunk:    .word 0
              .section uiextra, text, root, noreorder
#include "menu-cache.inc"

#include "menu-native.inc"

              .extern ReadColdMenuBlocks
