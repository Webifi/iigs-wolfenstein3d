#include "memmap.inc"
#include "frontend.inc"
#include "logic.inc"
              .section uifastcode, text, root, noreorder
              .public TryWord, wordReturn, DrawWordBlock, InitWords
              .extern steelBright, steelMuted, composing, recolorActive
              .extern pauseWordsHere

InitWords:    lda long:wordsReady
              bne wordsKept
              phb
              ldx ##0
              ldy ##0x2000
              lda ##31999
              .byte 0x54, 0xe0, 0x41
              plb
              lda ##1
              sta long:wordsReady
wordsKept:    rtl
wordsReady:   .word 0

;;; A cached word keeps the same U_STR/U_X contract as DrawStr. A parity
;;; mismatch or dynamic text takes the original glyph path without mutation.
TryWord:      lda long:recolorActive
              bne wordMiss
              lda dp:U_FONT
              cmp ##1
              beq wordSearch
wordMiss:     clc
              rtl
wordSearch:   lda dp:U_C
              cmp ##C_GRAY
              bne wordMiss
              lda ##0x41
              sta dp:W_PTR+2
              ldx ##.word0 (wordDirectory)
wordFind:     lda long:UI_BANK,x
              beq wordMiss
              cmp (U_STR)
              beq wordCandidate
wordNext:     txa
              clc
              adc ##10
              tax
              bra wordFind
wordCandidate:
              lda long:SNAP_PIX+0x2,x
              sta dp:W_PTR
              ldy ##0
              sep #0x20
wordCompare:  lda [W_PTR],y
              cmp (U_STR),y
              bne wordMismatch
              cmp #0
              beq wordFound
              iny
              bra wordCompare
wordMismatch: rep #0x20
              bra wordNext
wordFound:    rep #0x20
              lda long:SNAP_PIX+0x4,x
              sta dp:W_PTR
              lda long:SNAP_PIX+0x6,x
              sep #0x20
              sta dp:W_PTR+2
              rep #0x20
              bit ##0x00ff                   ; bank 0: the in-game pause window, only
              bne wordResident               ; while the main page's words are in it
              pha
              lda long:pauseWordsHere
              beq wordAway
              pla
wordResident:
              xba
              and ##255
              sta dp:W_LEN
              lda long:SNAP_PIX+0x8,x
              sta dp:W_ADV
              lda dp:U_X
              dec a
              and ##1
              asl a
              tay
              lda [W_PTR],y
              cmp ##0xffff
              beq wordMiss
              clc
              adc dp:W_PTR
              tax
wordStateReady:
              lda dp:U_X
              dec a
              lsr a
              sta dp:W_BASE
              lda dp:U_Y
              dec a
              sta dp:W_Y
              asl a
              asl a
              clc
              adc dp:W_Y
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc dp:W_BASE
              sta dp:W_BASE
              lda dp:W_ADV
              pha
              lda dp:W_LEN
              pha
              jsl long:DrawWordBlock
              pla
              sta dp:W_LEN
              pla
              sta dp:W_ADV
              lda dp:U_X
              clc
              adc dp:W_ADV
              sta dp:U_X
              lda dp:U_STR
              clc
              adc dp:W_LEN
              inc a
              sta dp:U_STR
wordReturn:   sec
              rtl
wordAway:     pla
              jmp abs:.word0 (wordMiss)

;;; W_PTR bank / X address is an opaque-run and masked-word block.
;;; W_BASE is its screen byte offset, U_C selects normal/bright/muted ink.
DrawWordBlock:
              sep #0x20
              lda dp:W_PTR+2
              sta long:wordCodeRead+3
              sta long:wordCodeCount+3
              sta long:wordCodeCall+3
              sta long:wordRead+3
              sta long:wordCount+3
              sta long:wordSkipRun+3
              sta long:wordMaskRead+3
              sta long:wordInkRead+3
              sta long:wordPlainPair+3
              sta long:wordMapped+3
              rep #0x20
              stz dp:W_STATE
              lda dp:U_C
              cmp ##C_WHITE
              beq wordBright
              cmp ##C_DKRED
              bne wordBank
              lda ##.word0 (steelMuted)
              bra wordShade
wordBright:   lda ##.word0 (steelBright)
wordShade:    sta long:wordColor+1
              sta long:wordLow+1
              sta long:wordHigh+1
              inc dp:W_STATE
wordBank:     phb
              sep #0x20
wordTargetBank:
              lda #0xe1
              pha
              plb
              rep #0x20
wordRun:
wordRead:     lda long:UI_BANK,x
              inx
              inx
              cmp ##0xffff
              bne wordRecord
              plb
              rtl
wordRecord:   cmp ##0xfffd
              bne wordBitmap
              jmp abs:.word0 (wordCode)
wordBitmap:   cmp ##0xfffa
              bne wordSolidCheck
              jmp abs:.word0 (wordDouble)
wordSolidCheck: cmp ##0xfffb
              bne wordAlphaCheck
              jmp abs:.word0 (wordSolid)
wordAlphaCheck: cmp ##0xfffc
              bne wordSparse
              jmp abs:.word0 (wordAlpha)
wordSparse:   bit ##0x8000
              beq wordUnmasked
              jmp abs:.word0 (wordMasked)
wordUnmasked:
              clc
              adc dp:W_BASE
              cmp dp:UC_FIRST
              bcc wordSkipRun
              cmp dp:UC_END
              bcs wordSkipRun
              tay
wordCount:    lda long:UI_BANK,x
              inx
              inx
              sta dp:W_END
              txa
              clc
              adc dp:W_END
              sta dp:W_END
              lda dp:W_STATE
              bne wordMapStart
wordPlain:    lda dp:W_END
              stx dp:W_LEN
              sec
              sbc dp:W_LEN
              bit ##1
              bne wordPlainPairJump
              cmp ##16
              bcs wordPlainWide
wordPlainPairJump: jmp abs:.word0 (wordPlainPair)
wordPlainWide: dec a
              sta dp:W_LEN
              tya
              clc
              adc long:wordTargetPlain+1
              tay
              sep #0x20
              lda long:wordRead+3
              sta long:wordPlainMvn+1
              phb
              pla
              sta long:wordPlainMvn
              rep #0x20
              lda long:wordPlainMvn
              bne wordPlainMove
              lda dp:W_LEN
              inc a
              jsr abs:.word0 (PeiSlam)
              jmp abs:.word0 (wordRun)
wordPlainMove: lda dp:W_LEN
              phb
              .byte 0x54
wordPlainMvn: .byte 0xe1, 0x41
              plb
              jmp abs:.word0 (wordRun)
wordPlainPair: lda long:UI_BANK,x
wordTargetPlain:
              sta abs:.word0 (SHR),y
              inx
              inx
              iny
              iny
              cpx dp:W_END
              bcc wordPlainPair
              jmp abs:.word0 (wordRun)
wordSkipRun:  lda long:UI_BANK,x
              clc
              adc ##2
              sta dp:W_END
              txa
              clc
              adc dp:W_END
              tax
              jmp abs:.word0 (wordRun)
wordMapStart: lda ##0
              sep #0x20
wordMapped:   lda long:UI_BANK,x
              phx
              tax
wordColor:    lda long:steelBright,x
              plx
wordTargetMapped:
              sta abs:.word0 (SHR),y
              inx
              iny
              cpx dp:W_END
              bcc wordMapped
              rep #0x20
              jmp abs:.word0 (wordRun)
wordMasked:   and ##0x7fff
              clc
              adc dp:W_BASE
              cmp dp:UC_FIRST
              bcc wordSkipMask
              cmp dp:UC_END
              bcs wordSkipMask
              tay
wordMaskRead: lda long:UI_BANK,x
              sta dp:W_MASK
wordInkRead:  lda long:SNAP_PIX+0x2,x
              inx
              inx
              inx
              inx
              sta dp:W_INK
              lda dp:W_STATE
              beq wordMerge
              phx
              lda dp:W_INK
              and ##255
              tax
              sep #0x20
wordLow:      lda long:steelBright,x
              sta dp:W_INK
              rep #0x20
              lda dp:W_INK
              xba
              and ##255
              tax
              sep #0x20
wordHigh:     lda long:steelBright,x
              sta dp:W_INK+1
              rep #0x20
              plx
wordTargetRead:
wordMerge:    lda abs:.word0 (SHR),y
              and dp:W_MASK
              ora dp:W_INK
wordTargetMerge:
              sta abs:.word0 (SHR),y
              jmp abs:.word0 (wordRun)

wordSkipMask: inx
              inx
              inx
              inx
              jmp abs:.word0 (wordRun)

;;; Cached row programs use Y as their target base; the paused target is
;;; selected by the same patched base/bank as the ordinary word blitter.
;;; Y has the final 16-bit target address, so its addition carry must not
;;; be counted again by the ordinary indexed-address bank adjustment.
              .public wordProgramBank
wordCode:     sep #0x20
wordProgramBank:
              lda #0xe1
              pha
              plb
              rep #0x20
wordCodeCount: lda long:UI_BANK,x
              sta dp:W_ROWS
              inx
              inx
              stx dp:W_CODE
              lda dp:W_BASE
              sta dp:W_ROW
wordCodeRow:  lda dp:W_ROW
              cmp dp:UC_FIRST
              bcc wordCodeNext
              cmp dp:UC_END
              bcs wordCodeNext
              ldx dp:W_CODE
wordCodeRead: lda long:UI_BANK,x
              clc
              adc dp:W_CODE
              sta long:wordCodeCall+1
              lda dp:W_ROW
              clc
              adc long:wordTargetPlain+1
              tay
wordCodeCall: jsl long:UI_BANK
wordCodeNext: inc dp:W_CODE
              inc dp:W_CODE
              lda dp:W_ROW
              clc
              adc ##160
              sta dp:W_ROW
              dec dp:W_ROWS
              bne wordCodeRow
              plb
              rtl


#include "ui-words.inc"

              .public wordTargetBank, wordTargetPlain, wordTargetMapped, wordTargetRead, wordTargetMerge


;;; Native eight-pixel groups: one transparency byte followed by two SHR words.
;;; Source bytes, positions and ink are prepared by the builder.
wordAlpha:    stx dp:W_PTR
              ldy ##0
              lda [W_PTR],y
              sta dp:W_ADV
              iny
              iny
              lda [W_PTR],y
              sta dp:W_Y
              lda ##4
              sta dp:W_LEN
alphaRow:     lda dp:W_BASE
              cmp dp:UC_FIRST
              bcc alphaClip
              cmp dp:UC_END
              bcc alphaVisible
alphaClip:    jmp abs:.word0 (alphaNextRow)
alphaVisible: tax
              ldy dp:W_LEN
              lda [W_PTR],y
              clc
              adc ##4
              tay
              lda dp:W_ADV
              sta dp:W_END
alphaGroup:   lda [W_PTR],y
              and ##255
              sta dp:W_MASK
              iny
              cmp ##255
              beq alphaEmpty
              cmp ##0
              bne alphaMasked
              lda [W_PTR],y
alphaWrite0:  sta abs:.word0 (SHR),x
              iny
              iny
              lda [W_PTR],y
alphaWrite2:  sta abs:.word0 (SHR+2),x
              iny
              iny
              bra alphaNextGroup
alphaEmpty:   bra alphaNextGroup
alphaMasked:  phy
              and ##15
              asl a
              txy
              tax
              lda long:alphaMasks,x
              tyx
              ply
alphaRead0:   and abs:.word0 (SHR),x
              ora [W_PTR],y
alphaMerge0:  sta abs:.word0 (SHR),x
              iny
              iny
              lda dp:W_MASK
              lsr a
              lsr a
              lsr a
              lsr a
              asl a
              phy
              txy
              tax
              lda long:alphaMasks,x
              tyx
              ply
alphaRead2:   and abs:.word0 (SHR+2),x
              ora [W_PTR],y
alphaMerge2:  sta abs:.word0 (SHR+2),x
              iny
              iny
alphaNextGroup: inx
              inx
              inx
              inx
              dec dp:W_END
              beq alphaNextRow
              jmp abs:.word0 (alphaGroup)
alphaNextRow: inc dp:W_LEN
              inc dp:W_LEN
              lda dp:W_BASE
              clc
              adc ##160
              sta dp:W_BASE
              dec dp:W_Y
              beq alphaDone
              jmp abs:.word0 (alphaRow)
alphaDone:    plb
              rtl
              .public alphaRead0, alphaRead2, alphaWrite0, alphaWrite2, alphaMerge0, alphaMerge2
alphaMasks:
              .word 0x0,0xf0,0xf,0xff,0xf000,0xf0f0,0xf00f,0xf0ff,0xf00,0xff0,0xf0f,0xfff,0xff00,0xfff0,0xff0f,0xffff

;;; Episode pictures retain their original packed pixels. Each source pixel
;;; becomes a 2 by 2 square in the offscreen update frame.
wordDouble:   stx dp:W_PTR
              ldy ##0
              lda [W_PTR],y
              sta dp:W_ADV
              iny
              iny
              lda [W_PTR],y
              sta dp:W_Y
              iny
              iny
doubleRow:    stz dp:W_END
              lda dp:W_BASE
              cmp dp:UC_FIRST
              bcc doubleSecond
              cmp dp:UC_END
              bcs doubleSecond
              inc dp:W_END
doubleSecond: lda dp:W_BASE
              clc
              adc ##160
              cmp dp:UC_FIRST
              bcc doubleVisible
              cmp dp:UC_END
              bcs doubleVisible
              lda dp:W_END
              ora ##2
              sta dp:W_END
doubleVisible: lda dp:W_BASE
              tax
              lda dp:W_ADV
              sta dp:W_LEN
doublePixel:  lda [W_PTR],y
              and ##255
              sta dp:W_MASK
              and ##0xf0
              sta dp:W_INK
              lsr a
              lsr a
              lsr a
              lsr a
              ora dp:W_INK
              pha
              lda dp:W_MASK
              and ##15
              sta dp:W_INK
              asl a
              asl a
              asl a
              asl a
              ora dp:W_INK
              xba
              ora 1,s
              sta dp:W_INK
              lda dp:W_END
              lsr a
              bcc doubleNoFirst
              lda dp:W_INK
doubleWrite0: sta abs:.word0 (SHR),x
doubleNoFirst: lda dp:W_END
              and ##2
              beq doubleNoSecond
              lda dp:W_INK
doubleWrite1: sta abs:.word0 (SHR+160),x
doubleNoSecond: pla
              inx
              inx
              iny
              dec dp:W_LEN
              bne doublePixel
              lda dp:W_BASE
              clc
              adc ##320
              sta dp:W_BASE
              dec dp:W_Y
              beq doubleDone
              jmp abs:.word0 (doubleRow)
doubleDone:   plb
              rtl
              .public doubleWrite0, doubleWrite1

;;; Opaque rectangles preserve only the partial edge pixels. Whole native
;;; words in between copy directly; source rows are tightly packed.
wordSolid:    stx dp:W_PTR
              ldy ##0
              lda [W_PTR],y
              sta dp:W_ADV
              iny
              iny
              lda [W_PTR],y
              sta dp:W_Y
              iny
              iny
              lda [W_PTR],y
              sta dp:W_MASK
              iny
              iny
              lda [W_PTR],y
              sta dp:W_INK
              iny
              iny
solidRow:     lda dp:W_BASE
              cmp dp:UC_FIRST
              bcc solidClip
              cmp dp:UC_END
              bcc solidVisible
solidClip:    tya
              clc
              adc dp:W_ADV
              tay
              bra solidNext
solidVisible: tax
              lda dp:W_MASK
solidRead0:   and abs:.word0 (SHR),x
              ora [W_PTR],y
solidWrite0:  sta abs:.word0 (SHR),x
              iny
              iny
              inx
              inx
              lda dp:W_ADV
              sec
              sbc ##4
              sta dp:W_END
solidCopy:    lda [W_PTR],y
solidWrite1:  sta abs:.word0 (SHR),x
              iny
              iny
              inx
              inx
              dec dp:W_END
              dec dp:W_END
              bne solidCopy
              lda dp:W_INK
solidRead2:   and abs:.word0 (SHR),x
              ora [W_PTR],y
solidWrite2:  sta abs:.word0 (SHR),x
              iny
              iny
solidNext:    lda dp:W_BASE
              clc
              adc ##160
              sta dp:W_BASE
              dec dp:W_Y
              bne solidRow
              plb
              rtl
              .public solidRead0, solidRead2, solidWrite0, solidWrite1, solidWrite2

#include "ui_preview.inc"

;;; Bank 0 only. The stack is bank 0 (Hardware Reference, $C068 ALTZP).
;;; SHR is $E1, so display copies stay on MVN. Count in A, even, at least 16.
;;; X is the source offset, Y the destination offset.
PeiSlam:      sta dp:W_LEN
              php
              sei
              phd
              tsc
              sta long:peiSaved
peiChunk:     lda dp:W_LEN
              cmp ##16
              bcc peiRestore
              sec
              sbc ##16
              sta dp:W_LEN
              txa
              tcd
              tya
              clc
              adc ##16
              tcs
              .byte 0xd4, 0x0e
              .byte 0xd4, 0x0c
              .byte 0xd4, 0x0a
              .byte 0xd4, 0x08
              .byte 0xd4, 0x06
              .byte 0xd4, 0x04
              .byte 0xd4, 0x02
              .byte 0xd4, 0x00
              txa
              clc
              adc ##16
              tax
              tya
              clc
              adc ##16
              tay
              lda ##UI_DP
              tcd
              bra peiChunk
peiRestore:   lda long:peiSaved
              tcs
              pld
              plp
              lda dp:W_LEN
              beq peiDone
peiTail:      lda abs:0,x
              sta abs:0,y
              inx
              inx
              iny
              iny
              dec dp:W_LEN
              dec dp:W_LEN
              bne peiTail
peiDone:      rts
peiSaved:     .word 0
              .extern nativeRecord
