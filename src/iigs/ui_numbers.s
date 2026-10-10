;;; Conversion keeps DBR=$3F for its tables and result, freeing menu code space.
#include "frontend.inc"
              .section gamecode, text, root, noreorder
              .public NumToStrCore, Num32ToStrCore
              .extern power10, power32, numBuf

NumToStrCore:     sta dp:U_T0
              ldx ##0                     ; output index
              ldy ##0                     ; power of ten
              stz dp:U_T2                 ; digits started
numPower:     stz dp:U_T3
numSub:       lda dp:U_T0
              cmp abs:.word0 (power10),y
              bcc numDigit
              sbc abs:.word0 (power10),y
              sta dp:U_T0
              inc dp:U_T3
              bra numSub
numDigit:     lda dp:U_T3
              ora dp:U_T2
              beq numNext                 ; no leading zero
              lda dp:U_T3
              clc
              adc ##'0'
              sep #0x20
              sta abs:.word0 (numBuf),x
              rep #0x20
              inx
              lda ##1
              sta dp:U_T2
numNext:      iny
              iny
              cpy ##8
              bcc numPower
              lda dp:U_T0                 ; the ones digit always shows
              clc
              adc ##'0'
              sep #0x20
              sta abs:.word0 (numBuf),x
              inx
              lda #0
              sta abs:.word0 (numBuf),x
              rep #0x20
              lda ##.word0 numBuf
              sta dp:U_STR
              rtl

;;; The 32-bit value in U_T0 (low) and U_T1 (high) as decimal in numBuf.
Num32ToStrCore:   ldx ##0
              ldy ##0                     ; index into power32
              stz dp:U_T2
num32Power:   stz dp:U_T3
num32Sub:     lda dp:U_T0
              sec
              sbc abs:.word0 (power32),y
              sta dp:U_T4
              lda dp:U_T1
              sbc abs:.word0 (power32 + 2),y
              bcc num32Digit
              sta dp:U_T1
              lda dp:U_T4
              sta dp:U_T0
              inc dp:U_T3
              bra num32Sub
num32Digit:   lda dp:U_T3
              ora dp:U_T2
              beq num32Next
              lda dp:U_T3
              clc
              adc ##'0'
              sep #0x20
              sta abs:.word0 (numBuf),x
              rep #0x20
              inx
              lda ##1
              sta dp:U_T2
num32Next:    iny
              iny
              iny
              iny
              cpy ##32
              bcc num32Power
              lda dp:U_T0
              clc
              adc ##'0'
              sep #0x20
              sta abs:.word0 (numBuf),x
              inx
              lda #0
              sta abs:.word0 (numBuf),x
              rep #0x20
              lda ##.word0 numBuf
              sta dp:U_STR
              rtl
