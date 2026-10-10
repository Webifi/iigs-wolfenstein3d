;;; Load-time sight unit (tools/fixed_units.py op_sight and op_matrix are the model).
;;;
;;; A shared unit loaded raw at SIGHT_GEN in the floor-disk part of a
;;; floor load. Before it come one unit with the sight parameters and the rooms
;;; (SIGHT_PARAMS, SIGHT_ROOMS) and the lower matrix half at its rows. The loader
;;; calls SightUnit (JSL) once when this unit is in (load_fast.inc GenHook). It
;;; builds the sight tables at BLOCK_DIR from the rooms and copies every set bit
;;; (i, j), j < i, of the matrix to (j, i), then returns carry clear.
;;;
;;; This unit belongs to the floor-disk part so that it works in either load
;;; order. The episode-disk part can overwrite the art generator's effect RAM
;;; before this part loads. Later units of this part replace SightUnit and its
;;; parameters; RunEnds clears the remaining LOGIC_ZERO after the last unit.
;;;
;;; Direct page $B0-$DF of page 0 (unused by the floor loader), as the generator.
;;; Its state lives in its own bank (SIGHT_GEN).

#include "memmap.inc"

              .section sightgen, text, root, noreorder
              .public SightUnit
;;; JSL with any register widths. Carry clear: done.
SightUnit:    php
              rep #0x30
              phb
              phd
              lda ##0
              tcd
              sep #0x20
              lda #.byte2 SIGHT_GEN
              pha
              plb
              rep #0x20
              lda long:SIGHT_PARAMS
              sta abs:.word0 (sightRows)
              lda long:SIGHT_PARAMS+2
              and ##255
              sta abs:.word0 (sightRows+2)
              lda long:SIGHT_PARAMS+3
              sta abs:.word0 (sightStride)
              jsr abs:.word0 (sightTables)
              jsr abs:.word0 (buildMatrix)
              pld
              plb
              plp
              clc
              rtl

;;; ----------------------------------------------------------- sight step
;;; Rooms (u16 per cell) at ROOMS. Tables at $32:0000 in the engine's
;;; format: row address per cell, then byte offset and bit mask.
sightTables:  ldx ##0                     ; X = cell * 2
sightCell:    lda abs:ROOMS,x             ; room k
              sta dp:G_T0
              phx
              ldx abs:.word0 (sightStride)
              jsr abs:.word0 (multiply)   ; k * stride
              plx
              clc
              adc abs:.word0 (sightRows)
              sta dp:G_T2                 ; row address, low word
              lda abs:.word0 (sightRows+2)
              adc ##0
              sta dp:G_X                  ; bank (with carry)
              txa
              asl a
              tay                         ; Y = cell * 4
              phx
              tyx
              lda dp:G_T2
              sta long:BLOCK_DIR,x
              lda dp:G_X
              sta long:BLOCK_DIR+0x2,x
              plx
              lda dp:G_T0
              lsr a
              lsr a
              lsr a
              sta long:BLOCK_OFFSETS,x
              lda dp:G_T0
              beq sightNoMask
              and ##7
              tay
              lda abs:.word0 (bitMask),y
              and ##255
sightNoMask:  sta long:BLOCK_MASKS,x
              inx
              inx
              cpx ##8192
              bcc sightCell
              rts

;;; ---------------------------------------------------------- matrix step
;;; The matrix at its rows holds bits j <= i of row i. Copy each to (j, i)
;;; by 8 x 8 bit blocks: source block (rows 8C.., byte R) -> its transpose
;;; at (rows 8R.., byte C), R < C; a diagonal block ORs its own transpose.
;;; G_PTR = row 8C + R, G_DST = row 8R + C. Rows past the last room read
;;; as zero and are not written.
buildMatrix:  lda long:SIGHT_PARAMS+5
              lsr a
              lsr a
              lsr a
              sta abs:.word0 (mLast)
              lda long:SIGHT_PARAMS+5
              and ##7
              inc a
              sta abs:.word0 (mLastRows)
              lda ##0
              tax
mOffsets:     sta abs:.word0 (mOff),x
              clc
              adc abs:.word0 (sightStride)
              inx
              inx
              cpx ##16
              bcc mOffsets
              sta abs:.word0 (mStep)
              lda abs:.word0 (sightRows)
              sta dp:G_PTR
              lda abs:.word0 (sightRows+2)
              sta dp:G_PTR+2
              stz abs:.word0 (mC)
mColumn:      lda dp:G_PTR
              sta abs:.word0 (mRowC)
              lda dp:G_PTR+2
              sta abs:.word0 (mRowC+2)
              lda abs:.word0 (sightRows)
              clc
              adc abs:.word0 (mC)
              sta dp:G_DST
              lda abs:.word0 (sightRows+2)
              adc ##0
              sta dp:G_DST+2
              lda ##8
              ldx abs:.word0 (mC)
              cpx abs:.word0 (mLast)
              bne mRowsSet
              lda abs:.word0 (mLastRows)
mRowsSet:     sta abs:.word0 (mRows)
              stz abs:.word0 (mR)
mBlock:       sep #0x20
              ldy abs:.word0 (mOff)
              lda [G_PTR],y
              sta dp:M_S
              ldy abs:.word0 (mOff+2)
              lda [G_PTR],y
              sta dp:M_S+1
              ldy abs:.word0 (mOff+4)
              lda [G_PTR],y
              sta dp:M_S+2
              ldy abs:.word0 (mOff+6)
              lda [G_PTR],y
              sta dp:M_S+3
              ldy abs:.word0 (mOff+8)
              lda [G_PTR],y
              sta dp:M_S+4
              ldy abs:.word0 (mOff+10)
              lda [G_PTR],y
              sta dp:M_S+5
              ldy abs:.word0 (mOff+12)
              lda [G_PTR],y
              sta dp:M_S+6
              ldy abs:.word0 (mOff+14)
              lda [G_PTR],y
              sta dp:M_S+7
              ldx abs:.word0 (mRows)
mTrim:        cpx ##8
              bcs mTrimmed
              stz dp:M_S,x
              inx
              bra mTrim
mTrimmed:     rep #0x20
              lda abs:.word0 (mR)
              cmp abs:.word0 (mC)
              bne mUpper
              jmp abs:.word0 (mDiagonal)
mUpper:       lda dp:M_S
              and dp:M_S+2
              and dp:M_S+4
              and dp:M_S+6
              cmp ##0xffff
              beq mOnes
              lda dp:M_S
              ora dp:M_S+2
              ora dp:M_S+4
              ora dp:M_S+6
              beq mNext                   ; the upper block is already zero
              jsr abs:.word0 (transpose)
              sep #0x20
              ldy abs:.word0 (mOff)
              lda dp:M_O
              sta [G_DST],y
              ldy abs:.word0 (mOff+2)
              lda dp:M_O+1
              sta [G_DST],y
              ldy abs:.word0 (mOff+4)
              lda dp:M_O+2
              sta [G_DST],y
              ldy abs:.word0 (mOff+6)
              lda dp:M_O+3
              sta [G_DST],y
              ldy abs:.word0 (mOff+8)
              lda dp:M_O+4
              sta [G_DST],y
              ldy abs:.word0 (mOff+10)
              lda dp:M_O+5
              sta [G_DST],y
              ldy abs:.word0 (mOff+12)
              lda dp:M_O+6
              sta [G_DST],y
              ldy abs:.word0 (mOff+14)
              lda dp:M_O+7
              sta [G_DST],y
              rep #0x20
              bra mNext
mOnes:        sep #0x20
              lda #0xff
              ldy abs:.word0 (mOff)
              sta [G_DST],y
              ldy abs:.word0 (mOff+2)
              sta [G_DST],y
              ldy abs:.word0 (mOff+4)
              sta [G_DST],y
              ldy abs:.word0 (mOff+6)
              sta [G_DST],y
              ldy abs:.word0 (mOff+8)
              sta [G_DST],y
              ldy abs:.word0 (mOff+10)
              sta [G_DST],y
              ldy abs:.word0 (mOff+12)
              sta [G_DST],y
              ldy abs:.word0 (mOff+14)
              sta [G_DST],y
              rep #0x20
mNext:        inc dp:G_PTR
              bne mPtrDone
              inc dp:G_PTR+2
mPtrDone:     lda dp:G_DST
              clc
              adc abs:.word0 (mStep)
              sta dp:G_DST
              bcc mDstDone
              inc dp:G_DST+2
mDstDone:     inc abs:.word0 (mR)
              jmp abs:.word0 (mBlock)
mDiagonal:    jsr abs:.word0 (transpose)
              ldx ##0
mDiagonalRow: txa
              asl a
              tay
              lda abs:.word0 (mOff),y
              tay
              sep #0x20
              lda dp:M_S,x
              ora dp:M_O,x
              sta [G_PTR],y
              rep #0x20
              inx
              cpx abs:.word0 (mRows)
              bcc mDiagonalRow
              lda abs:.word0 (mRowC)
              clc
              adc abs:.word0 (mStep)
              sta dp:G_PTR
              lda abs:.word0 (mRowC+2)
              adc ##0
              sta dp:G_PTR+2
              inc abs:.word0 (mC)
              lda abs:.word0 (mLast)
              cmp abs:.word0 (mC)
              bcc mDone
              jmp abs:.word0 (mColumn)
mDone:        rts

;;; M_S -> M_O: bit r of M_O+c = bit c of M_S+r. Native A16/X16 in and out.
transpose:    sep #0x20
              ldx ##7
transposeRow: lda dp:M_S,x
              lsr a
              rol dp:M_O
              lsr a
              rol dp:M_O+1
              lsr a
              rol dp:M_O+2
              lsr a
              rol dp:M_O+3
              lsr a
              rol dp:M_O+4
              lsr a
              rol dp:M_O+5
              lsr a
              rol dp:M_O+6
              lsr a
              rol dp:M_O+7
              dex
              bpl transposeRow
              rep #0x20
              rts

;;; A = A * X (16-bit result).
multiply:     sta dp:G_T1
              stx dp:G_T2
              lda ##0
mulLoop:      lsr dp:G_T2
              bcc mulSkip
              clc
              adc dp:G_T1
mulSkip:      asl dp:G_T1
              ldx dp:G_T2
              bne mulLoop
              rts

bitMask:      .byte 1, 2, 4, 8, 16, 32, 64, 128

;;; ------------------------------------------------------------- state
sightRows:    .word 0, 0
sightStride:  .word 0
mOff:         .word 0, 0, 0, 0, 0, 0, 0, 0
mStep:        .word 0
mLast:        .word 0
mLastRows:    .word 0
mRows:        .word 0
mC:           .word 0
mR:           .word 0
mRowC:        .word 0, 0
