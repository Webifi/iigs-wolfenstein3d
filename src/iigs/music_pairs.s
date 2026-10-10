;;; Handwritten 65816 handlers for prepared stereo register pairs.
;;; Assembled into each WDM2 hot bank; no DOC transfer without BUSY.
;;; A=8, X/Y=16, B=0, DBR/PBR=$3E; Y is the original stream cursor.
#include "memmap.inc"
              .section threadbody, text, root, noreorder
              .public ThreadNext, ThreadGeneric, ThreadEnd, ThreadLoop
STREAM .equ 0x600
LEVEL .equ 0x500
VSCALE .equ 0x480
TMP .equ 0x24
READY .macro
1$:           lda long:SOUNDCTL
              bmi 1$
              .endm
SPACING .macro
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              .endm
ThreadNext:   lda abs:STREAM,y
              iny
              tax
              jmp (0x100,x)
ThreadEnd:    rtl
ThreadLoop:   ldy ##0
              rtl
ThreadGeneric:
              lda abs:STREAM,y
              iny
              sta abs:TMP
              and #0xe0
              cmp #0x40
              beq genericVolume
              lda abs:STREAM,y
              iny
              tax
              READY
              lda abs:TMP
              sta long:SOUNDADRL
registerNext: lda abs:STREAM,y
              iny
              sta long:SOUNDDATA
              dex
              beq registerDone
              READY
              bra registerNext
registerDone: lda abs:TMP
              and #0xe0
              cmp #0xa0
              bne genericDone
ThreadSpacing:SPACING
genericDone:  jmp abs:.word0 (ThreadNext)
genericVolume:
              lda abs:STREAM,y
              iny
              sta abs:TMP+1
              lda abs:TMP
              and #31
              tax
              READY
              lda abs:TMP
              sta long:SOUNDADRL
volumeNext:   lda abs:STREAM,y
              iny
              sta abs:LEVEL,x
              phx
              tax
              lda abs:VSCALE,x
              plx
              sta long:SOUNDDATA
              inx
              dec abs:TMP+1
              beq genericDone
              READY
              bra volumeNext

;;; These macros are instantiated with constant DOC addresses at build time.
PAIR .macro reg, finish
              READY
              lda #\reg
              sta long:SOUNDADRL
              lda abs:STREAM,y
              iny
              sta long:SOUNDDATA
              READY
              lda abs:STREAM,y
              iny
              sta long:SOUNDDATA
              jmp abs:.word0 (\finish)
              .endm
VPAIR .macro reg
              READY
              lda #\reg
              sta long:SOUNDADRL
              lda abs:STREAM,y
              iny
              sta abs:(LEVEL+(\reg & 31))
              tax
              lda abs:VSCALE,x
              sta long:SOUNDDATA
              READY
              lda abs:STREAM,y
              iny
              sta abs:(LEVEL+(\reg & 31)+1)
              tax
              lda abs:VSCALE,x
              sta long:SOUNDDATA
              jmp abs:.word0 (ThreadNext)
              .endm
CONSTANT .macro reg, left, right, finish
              READY
              lda #\reg
              sta long:SOUNDADRL
              lda #\left
              sta long:SOUNDDATA
              READY
              lda #\right
              sta long:SOUNDDATA
              jmp abs:.word0 (\finish)
              .endm
