;;; Mouse counts retain their sub-control-unit fraction between tics. Turning
;;; is calibrated independently of movement and does not depend on frame rate.
#include "game.inc"
#include "frontend.inc"
              .section inputcode, text, root, noreorder
              .public MouseControls, MouseReset, MouseSettingsLoad, MouseSettingsStore
              .public mouseFracX, mouseFracY, mouseTurnProducts, MouseProduct
              .extern mouseCountX, mouseCountY, mouseWalk, mouseSensitivity

MouseControls: lda long:mouseCountX
              ora long:mouseCountY
              bne mouseMotion
              ldx ##0
              ldy ##0
              rtl
mouseMotion:  phb
              phk
              plb
              lda long:mouseSensitivity
              asl a
              asl a
              asl a
              asl a
              asl a
              sta abs:.word0 (mouseStep)
              lda dp:COMMAND
              and ##64
              cmp abs:.word0 (mouseStrafe)
              beq mouseSameMode
              sta abs:.word0 (mouseStrafe)
              stz abs:.word0 (mouseFracX)
mouseSameMode:lda long:mouseCountX
              pha
              lda ##0
              sta long:mouseCountX
              pla
              ldx ##0
              ldy abs:.word0 (mouseStrafe)
              beq mouseXScale
              ldx ##512
mouseXScale:  jsr abs:.word0 (MouseProduct)
              sta abs:.word0 (mouseInteger)
              tya
              clc
              adc abs:.word0 (mouseFracX)
              jsr abs:.word0 (mouseWhole)
              sty abs:.word0 (mouseFracX)
              pha
              lda long:mouseCountY
              pha
              lda ##0
              sta long:mouseCountY
              lda long:mouseWalk
              bne mouseYOn
              pla
              stz abs:.word0 (mouseFracY)
              lda ##0
              bra mouseYReady
mouseYOn:     pla
              ldx ##512
              jsr abs:.word0 (MouseProduct)
              asl a
              sta abs:.word0 (mouseInteger)
              tya
              asl a
              clc
              adc abs:.word0 (mouseFracY)
              jsr abs:.word0 (mouseWhole)
              sty abs:.word0 (mouseFracY)
mouseYReady:  tay
              plx
              plb
              rtl

;;; A signed count, X table offset. Returns whole units in A and a signed
;;; Q8 fraction in Y. Three nibble lookups multiply up to +/-2047 counts.
;;; Zero reports do no multiplication. Scratch is private to the consumer.
MouseProduct: stx abs:.word0 (mouseTable)
              sta abs:.word0 (mouseSign)
              cmp ##0
              bne mouseNonzero
              ldy ##0
              rts
mouseNonzero:
              bpl mouseMagnitude
              eor ##0xffff
              inc a
mouseMagnitude:
              cmp ##2048
              bcc mouseMagnitudeOk
              lda ##2047
mouseMagnitudeOk:
              sta abs:.word0 (mouseN)
              stz abs:.word0 (mouseLo)
              stz abs:.word0 (mouseHi)
              ldy ##3
mouseNibble:  asl abs:.word0 (mouseLo)
              rol abs:.word0 (mouseHi)
              asl abs:.word0 (mouseLo)
              rol abs:.word0 (mouseHi)
              asl abs:.word0 (mouseLo)
              rol abs:.word0 (mouseHi)
              asl abs:.word0 (mouseLo)
              rol abs:.word0 (mouseHi)
              lda abs:.word0 (mouseN)
              xba
              and ##15
              asl a
              clc
              adc abs:.word0 (mouseStep)
              adc abs:.word0 (mouseTable)
              tax
              lda abs:.word0 (mouseTurnProducts),x
              clc
              adc abs:.word0 (mouseLo)
              sta abs:.word0 (mouseLo)
              bcc mouseNibbleReady
              inc abs:.word0 (mouseHi)
mouseNibbleReady:
              asl abs:.word0 (mouseN)
              asl abs:.word0 (mouseN)
              asl abs:.word0 (mouseN)
              asl abs:.word0 (mouseN)
              dey
              bne mouseNibble
              lda abs:.word0 (mouseLo)
              and ##255
              tay
              lda abs:.word0 (mouseLo)
              xba
              and ##255
              sta abs:.word0 (mouseLo)
              lda abs:.word0 (mouseHi)
              xba
              ora abs:.word0 (mouseLo)
              ldx abs:.word0 (mouseSign)
              bpl mouseProductDone
              eor ##0xffff
              inc a
              pha
              tya
              eor ##0xffff
              inc a
              tay
              pla
mouseProductDone:
              rts

;;; A is the sum of old and new signed fractions; carry whole units into
;;; mouseInteger. Splitting a gesture across reports gives the same total.
mouseWhole:   cmp ##0
              bmi mouseFractionNegative
mouseFractionPositive:
              cmp ##256
              bcc mouseFractionReady
              sec
              sbc ##256
              inc abs:.word0 (mouseInteger)
              bra mouseFractionPositive
mouseFractionNegative:
              cmp ##0xff01
              bcs mouseFractionReady
              clc
              adc ##256
              dec abs:.word0 (mouseInteger)
              bra mouseWhole
mouseFractionReady:
              tay
              lda abs:.word0 (mouseInteger)
              rts

MouseReset:   lda ##0
              sta long:mouseFracX
              sta long:mouseFracY
              rtl

MouseSettingsLoad:
              lda long:SETTINGS_IN + S_MSPEED
              and ##255
              cmp ##16
              bcc mouseSettingReady
mouseDefault: lda ##4
mouseSettingReady:
              sta long:mouseSensitivity
              jmp long:MouseReset
MouseSettingsStore:
              sep #0x20
              lda long:mouseSensitivity
              sta long:SETTINGS_IN + S_MSPEED
              rep #0x20
              rtl

mouseStep:    .word 0
mouseTable:   .word 0
mouseN:       .word 0
mouseLo:      .word 0
mouseHi:      .word 0
mouseSign:    .word 0
mouseInteger: .word 0
mouseFracX:   .word 0
mouseFracY:   .word 0
mouseStrafe:  .word 0
#include "mouse.inc"

;;; Large flicks exceed the small DIV20 table used by normal keyboard turns.
;;; Binary division keeps that exceptional path bounded at sixteen steps.
              .public MouseAngleDivide
MouseAngleDivide:
              phb
              phk
              plb
              sta abs:.word0 (mouseN)
              stz abs:.word0 (mouseLo)
              ldy ##16
mouseDivideBit:
              asl abs:.word0 (mouseN)
              rol abs:.word0 (mouseLo)
              lda abs:.word0 (mouseLo)
              cmp ##20
              bcc mouseDivideNext
              sbc ##20
              sta abs:.word0 (mouseLo)
              inc abs:.word0 (mouseN)
mouseDivideNext:
              dey
              bne mouseDivideBit
              lda abs:.word0 (mouseN)
              plb
              rtl
