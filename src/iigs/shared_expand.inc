;;; Reconstruct four shade words from one shared source index. Bank $1D
;;; holds 16-bit palette offsets at $8000 and the decoded plan at $4000.
;;; Each 18-byte placement record contains a source offset, four 24-bit
;;; destination biases, an entry index, a reserved byte and a loop count.
;;; Two pixels per loop avoid a branch per output word. Missing shades use
;;; the now-unused compressed-input scratch; the live $1D art restores last.
#include "memmap.inc"
              .public ExpandSharedArt
ExpandSharedArt:
              rep #0x30
              lda ##0x4804
              sta dp:SHARED_REC
              lda long:SHARED_PLAN+0x800
              sta dp:SHARED_RECS
              lda long:SHARED_PLAN+0x802
              sta dp:SHARED_LEFT
              sep #0x20
              lda #0x1d
              pha
              plb
sharedRecord:
              rep #0x20
              ldx dp:SHARED_REC
              lda abs:0,x
              pha
              lda abs:2,x
              sta long:sharedStore00+1
              sta long:sharedStore10+1
              lda abs:5,x
              sta long:sharedStore01+1
              sta long:sharedStore11+1
              lda abs:8,x
              sta long:sharedStore02+1
              sta long:sharedStore12+1
              lda abs:11,x
              sta long:sharedStore03+1
              sta long:sharedStore13+1
              sep #0x20
              lda abs:4,x
              sta long:sharedStore00+3
              sta long:sharedStore10+3
              lda abs:7,x
              sta long:sharedStore01+3
              sta long:sharedStore11+3
              lda abs:10,x
              sta long:sharedStore02+3
              sta long:sharedStore12+3
              lda abs:13,x
              sta long:sharedStore03+3
              sta long:sharedStore13+3
              rep #0x20
              lda abs:16,x
              sta dp:SHARED_LOOP
              lda abs:14,x
              asl a
              tay
              txa
              clc
              adc ##18
              sta dp:SHARED_REC
              tyx
              lda long:sharedEntries,x
              sta long:sharedJump+1
              pla
              tax
sharedJump:   jmp abs:sharedCopy0
sharedCopy0:  ldy abs:0,x
              lda abs:.word0 (SHARED_PLAN),y
sharedStore00:sta long:0x000000,x
              lda abs:.word0 (SHARED_PLAN+0x200),y
sharedStore01:sta long:0x000000,x
              lda abs:.word0 (SHARED_PLAN+0x400),y
sharedStore02:sta long:0x000000,x
              lda abs:.word0 (SHARED_PLAN+0x600),y
sharedStore03:sta long:0x000000,x
              inx
              inx
sharedCopy1:  ldy abs:0,x
              lda abs:.word0 (SHARED_PLAN),y
sharedStore10:sta long:0x000000,x
              lda abs:.word0 (SHARED_PLAN+0x200),y
sharedStore11:sta long:0x000000,x
              lda abs:.word0 (SHARED_PLAN+0x400),y
sharedStore12:sta long:0x000000,x
              lda abs:.word0 (SHARED_PLAN+0x600),y
sharedStore13:sta long:0x000000,x
              inx
              inx
              dec dp:SHARED_LOOP
              bne sharedCopy0
              dec dp:SHARED_RECS
              beq sharedProgress
              jmp abs:sharedRecord
sharedProgress:
              lda dp:SHARED_LEFT
              beq sharedFinished
              cmp ##128
              bcc sharedCredit
              lda ##128
sharedCredit: sta dp:SHARED_CHUNK
              xba
              asl a
              tay
              stz dp:BOOT_SEGADDR
              stz dp:LOADER_TMP
              jsr abs:BOOT_b1Progress
              lda dp:SHARED_LEFT
              sec
              sbc dp:SHARED_CHUNK
              sta dp:SHARED_LEFT
              bra sharedProgress
sharedFinished:
              phk
              plb
              rts
sharedEntries:
              .word sharedCopy0,sharedCopy1
