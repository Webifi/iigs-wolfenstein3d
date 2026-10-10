;;; Floor-specific blocked-sight proofs occupy otherwise unused art banks.
;;; $30FFFC supplies the metadata bank; $30FFFE enables the table only after
;;; its loads have completed. Unknown pairs use the original live map walk.
#include "memmap.inc"
              .section registeredlogic, text, root
BLOCK_LAST:   .word 65535
InitLineRegionProbe:
              lda ##65535
              sta long:BLOCK_LAST
              lda ##.word0 (lineOriginal)
              sta long:CheckLine+1
              lda abs:ROOMRECTS+1022
              cmp ##0xab04
              bne lineProbeReady
              sep #0x20
              lda abs:ROOMRECTS+1020
              sta long:lineDirectoryLow+3
              sta long:lineDirectoryBank+3
              sta long:lineMask+3
              sta long:lineOffset+3
              rep #0x20
              lda ##.word0 (lineFastProbe)
              sta long:CheckLine+1
lineProbeReady:rts
;;; Cache only the player's tile lookup, never a visibility result. Door and
;;; moving-wall state remains authoritative in the exact fallback.
lineFastProbe:
              stx dp:L_Y
              lda abs:OBJLIST+O_TILEX
              xba
              lsr a
              lsr a
              ora abs:OBJLIST+O_TILEY
              cmp long:BLOCK_LAST
              beq linePlayerReady
              sta long:BLOCK_LAST
              phx
              tax
              sep #0x20
              lda long:LINEIDS,x
              sta long:linePlayerRegion+1
              rep #0x20
              txa
              asl a
              asl a
              tax
lineDirectoryLow:
              lda long:BLOCK_DIR,x
              sta long:regionLookup+1
              sep #0x20
lineDirectoryBank:
              lda long:BLOCK_DIR+2,x
              sta long:regionLookup+3
              rep #0x20
              plx
linePlayerReady:
              lda abs:O_X+2,x
              xba
              lsr a
              lsr a
              ora abs:O_Y+2,x
              tax
              stx dp:L_X
              sep #0x20
              lda long:LINEIDS,x
              beq lineFineFromByte
linePlayerRegion:
              cmp #0
              rep #0x20
              bne lineFine
              and ##255
              asl a
              tax
              lda long:LINECOUNTS,x
              bne lineFine
              sec
              rts
lineFineFromByte:
              rep #0x20
lineFine:
              ldx dp:L_X
              txa
              asl a
              tax
lineMask:     lda long:BLOCK_MASKS,x
              sta dp:L_T
lineOffset:   lda long:BLOCK_OFFSETS,x
              tax
regionLookup: lda long:ART_FULL+0x30000,x
              bit dp:L_T
              beq lineExact
              clc
              rts
lineExact:
              ldx dp:L_Y
              lda abs:O_X+1,x
              sta dp:L_X1
              lda abs:O_Y+1,x
              sta dp:L_Y1
              lda abs:O_X+2,x
              sta dp:L_XT1
              lda abs:O_Y+2,x
              sta dp:L_YT1
              lda abs:V_plux
              sta dp:L_X2
              lda abs:V_pluy
              sta dp:L_Y2
              lda abs:PLAYER+O_TILEX
              sta dp:L_XT2
              lda abs:PLAYER+O_TILEY
              sta dp:L_YT2
              jmp abs:.word0 (lineRegionFallback)
