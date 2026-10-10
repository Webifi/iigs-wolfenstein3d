#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public ProgressAdd, ProgressPlan, ProgressRemaining, ProgressFinish, ProgressPixels, ProgressRatio
              .public progressTotal, progressDone, progressExtra
              .extern busyShown, busyKind, busyProgress

;;; Work units are 1/128 second, calibrated outside the timed game loop.
;;; Callbacks preserve the caller's complete state and never touch its DP or DOC.
ProgressPlan: php
              rep #0x30
              pha
              phb
              phk
              plb
              clc
              adc abs:.word0 (progressExtra)
              sta abs:.word0 (progressTotal)
              phy
              sta abs:.word0 (progressStep)
              stz abs:.word0 (progressPixel)
              lda ##BUSY_BAR_W
              sta abs:.word0 (progressSpan)
              jsr abs:.word0 (ProgressDivide)
              lda abs:.word0 (progressStep)
              sta abs:.word0 (progressNext)
              ply
              plb
              pla
              plp
              rtl
;;; A newly read save header reveals the remaining work. Keep the drawn
;;; prefix and distribute that work over its remaining pixels, without a jump.
ProgressRemaining:
              php
              rep #0x30
              pha
              phy
              phb
              phk
              plb
              sta abs:.word0 (progressStep)
              clc
              adc abs:.word0 (progressDone)
              sta abs:.word0 (progressTotal)
              lda ##BUSY_BAR_W
              sec
              sbc abs:.word0 (progressPixel)
              beq remainingOut
              sta abs:.word0 (progressSpan)
              jsr abs:.word0 (ProgressDivide)
              lda abs:.word0 (progressDone)
              clc
              adc abs:.word0 (progressStep)
              sta abs:.word0 (progressNext)
remainingOut: plb
              ply
              pla
              plp
              rtl
ProgressDivide:
              stz abs:.word0 (progressRemainder)
              ldy ##16
remainingBit: asl abs:.word0 (progressStep)
              rol abs:.word0 (progressRemainder)
              lda abs:.word0 (progressRemainder)
              cmp abs:.word0 (progressSpan)
              bcc remainingKeep
              sbc abs:.word0 (progressSpan)
              sta abs:.word0 (progressRemainder)
              inc abs:.word0 (progressStep)
remainingKeep:dey
              bne remainingBit
              lda abs:.word0 (progressRemainder)
              sta abs:.word0 (progressError)
              rts
ProgressFinish:
              php
              rep #0x30
              pha
              lda long:progressTotal
              beq finishOut
              sta long:progressDone
              lda ##0
              jsl long:ProgressAdd
finishOut:    pla
              plp
              rtl
              .public Progress1, Progress2, Progress3, Progress4, Progress6, Progress7, Progress16, Progress20, Progress22, Progress26
Progress1: php
              rep #0x30
              pha
              lda ##1
              bra progressValue
Progress2: php
              rep #0x30
              pha
              lda ##2
              bra progressValue
Progress3: php
              rep #0x30
              pha
              lda ##3
              bra progressValue
Progress4: php
              rep #0x30
              pha
              lda ##4
              bra progressValue
Progress6: php
              rep #0x30
              pha
              lda ##6
              bra progressValue
Progress7: php
              rep #0x30
              pha
              lda ##7
              bra progressValue
Progress16: php
              rep #0x30
              pha
              lda ##16
              bra progressValue
Progress20: php
              rep #0x30
              pha
              lda ##20
              bra progressValue
Progress22: php
              rep #0x30
              pha
              lda ##22
              bra progressValue
Progress26: php
              rep #0x30
              pha
              lda ##26
              bra progressValue
ProgressAdd:  php
              rep #0x30
              pha
progressValue:phb
              phk
              plb
              clc
              adc abs:.word0 (progressDone)
              sta abs:.word0 (progressDone)
              lda abs:.word0 (progressTotal)
              beq progressOut
              lda abs:.word0 (progressDone)
              cmp abs:.word0 (progressNext)
              bcc progressDrawCheck
progressAdvance:
              lda abs:.word0 (progressPixel)
              cmp ##BUSY_BAR_W
              beq progressDrawCheck
              inc abs:.word0 (progressPixel)
              lda abs:.word0 (progressError)
              clc
              adc abs:.word0 (progressRemainder)
              cmp abs:.word0 (progressSpan)
              bcc progressNoCarry
              sbc abs:.word0 (progressSpan)
progressNoCarry:
              sta abs:.word0 (progressError)
              lda abs:.word0 (progressNext)
              adc abs:.word0 (progressStep)
              sta abs:.word0 (progressNext)
              lda abs:.word0 (progressDone)
              cmp abs:.word0 (progressNext)
              bcs progressAdvance
progressDrawCheck:
              lda abs:.word0 (busyShown)
              beq progressOut
              lda abs:.word0 (busyKind)
              bne progressOut
              lda abs:.word0 (progressPixel)
              cmp long:busyProgress
              beq progressOut
              phx
              phy
              jsr abs:.word0 (ProgressPixels)
              ply
              plx
progressOut:  plb
              pla
              plp
              rtl

;;; A/X -> 0..BUSY_BAR_W. Eight fraction bits avoid overflow; rounding is downward.
ProgressRatio:
              cpx ##0
              beq ratioZero
              stx abs:.word0 (progressDivisor)
              cmp abs:.word0 (progressDivisor)
              bcc ratioFraction
              lda ##BUSY_BAR_W
              rts
ratioFraction:stz abs:.word0 (progressQuotient)
              ldy ##8
ratioBit:     asl a
              bcs ratioSubtract
              cmp abs:.word0 (progressDivisor)
              bcc ratioKeep
ratioSubtract:sbc abs:.word0 (progressDivisor)
              sec
ratioKeep:    rol abs:.word0 (progressQuotient)
              dey
              bne ratioBit
              lda abs:.word0 (progressQuotient)
              asl a
              asl a
              clc
              adc abs:.word0 (progressQuotient)
              lsr a
              lsr a
              lsr a
              rts
ratioZero:    lda ##0
              rts

;;; Only newly filled pixels are stored; the other nibble retains its final value.
ProgressPixels:
              cmp long:busyProgress
              beq pixelsOut
              bcc pixelsOut
              sta abs:.word0 (progressEnd)
              lda long:busyProgress
              tay
pixelNext:    tya
              lsr a
              tax
              sep #0x20
              bcs pixelLow
              lda long:SHR+(BUSY_BAR_Y+0)*160+BUSY_BAR_X/2,x
              and #0x0f
              ora #BUSY_BAR_INK*16
              sta long:SHR+(BUSY_BAR_Y+0)*160+BUSY_BAR_X/2,x
              lda long:SHR+(BUSY_BAR_Y+1)*160+BUSY_BAR_X/2,x
              and #0x0f
              ora #BUSY_BAR_INK*16
              sta long:SHR+(BUSY_BAR_Y+1)*160+BUSY_BAR_X/2,x
              lda long:SHR+(BUSY_BAR_Y+2)*160+BUSY_BAR_X/2,x
              and #0x0f
              ora #BUSY_BAR_INK*16
              sta long:SHR+(BUSY_BAR_Y+2)*160+BUSY_BAR_X/2,x
              bra pixelLast
pixelLow:
              lda long:SHR+(BUSY_BAR_Y+0)*160+BUSY_BAR_X/2,x
              and #0xf0
              ora #BUSY_BAR_INK
              sta long:SHR+(BUSY_BAR_Y+0)*160+BUSY_BAR_X/2,x
              lda long:SHR+(BUSY_BAR_Y+1)*160+BUSY_BAR_X/2,x
              and #0xf0
              ora #BUSY_BAR_INK
              sta long:SHR+(BUSY_BAR_Y+1)*160+BUSY_BAR_X/2,x
              lda long:SHR+(BUSY_BAR_Y+2)*160+BUSY_BAR_X/2,x
              and #0xf0
              ora #BUSY_BAR_INK
              sta long:SHR+(BUSY_BAR_Y+2)*160+BUSY_BAR_X/2,x
pixelLast:
              rep #0x20
              iny
              cpy abs:.word0 (progressEnd)
              bcc pixelNext
              tya
              sta long:busyProgress
pixelsOut:    rts
              .section menudata, data, root
progressTotal:.word 0
progressDone: .word 0
progressExtra:.word 0
progressDivisor:.word 0
progressQuotient:.word 0
progressEnd:  .word 0
progressNext: .word 0
progressStep: .word 0
progressRemainder:.word 0
progressError:.word 0
progressPixel:.word 0
progressSpan: .word BUSY_BAR_W
