#include "memmap.inc"
#include "frontend.inc"
              .section graycode, text, root, noreorder
              .public DrawBusyText
              .extern DrawWordBlock, busyKind
;;; Center the small face at even U_X and row U_Y. Its body, contour and
;;; antialiased edges use aligned slots 1, 0, 13 and 14 in the current palette.
;;; INSERT DISK draws a shared prefix and one digit. Other signs are one block.
DrawBusyText: lda dp:U_Y
              dec a
              sta dp:W_BASE
              asl a
              asl a
              clc
              adc dp:W_BASE
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:W_BASE
              lda dp:U_X
              lsr a
              clc
              adc dp:W_BASE
              sta dp:W_BASE
              lda long:busyKind
              asl a
              tax
              lda long:busyWordLengths,x
              sta dp:U_T5
              cpx ##4
              beq busyDigit
              lda long:busyWordWidths,x
              sta dp:U_T4
              lda long:busyWordOffsets,x
              clc
              adc dp:W_BASE
              sta dp:W_BASE
              lda long:busyWordPtrs,x
              tax
              jsr abs:.word0 (busyDrawWord)
              bra busyTextEnd
busyDigit:    ldy ##12
              lda (U_STR),y
              and ##255
              sec
              sbc ##'1'
              cmp ##9
              bcc busyDigitValid
              lda ##0
busyDigitValid:
              asl a
              tax
              stx dp:U_T0
              lda long:busyDigitWidths,x
              sta dp:U_T4
              lda long:busyDigitOffsets,x
              clc
              adc dp:W_BASE
              sta dp:W_BASE
              sta dp:U_T2
              lda long:busyPrefixPtrs,x
              tax
              lda ##.byte2 (busyPrefix0)
              sta dp:W_PTR+2
              jsl long:DrawWordBlock
              lda dp:U_T2
              clc
              adc ##BUSY_PREFIX_BYTES
              sta dp:W_BASE
              ldx dp:U_T0
              lda long:busyDigitPtrs,x
              tax
              lda ##.byte2 (busyDigit1)
              sta dp:W_PTR+2
              jsl long:DrawWordBlock
busyTextEnd:  lda dp:U_T4
              lsr a
              eor ##0xffff
              inc a
              clc
              adc dp:U_T4
              clc
              adc dp:U_X
              sta dp:U_X
              lda dp:U_STR
              clc
              adc dp:U_T5
              sta dp:U_STR
              rtl
busyDrawWord: lda ##.byte2 (loadingWord)
              sta dp:W_PTR+2
              jsl long:DrawWordBlock
              rts

#include "busy_signs.inc"
