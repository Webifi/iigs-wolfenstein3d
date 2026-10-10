;;; ADB interrupts timestamp raw keys and mouse reports with the DOC clock.
;;; Movement drains each held interval, rather than assigning a whole frame
;;; to whichever key happens to be down at its end.
              .section gamecode, text, root, noreorder
              .public StartKeys, ReadKeys, CaptureInput, inputDropped
              .public inputSerial, keyHeld, keyAction, inputCursor, inputUntil, inputTimed, inputLimit
              .public mouseWalk, boundKeys, boundBits, keyChars
              .public mouseSensitivity, inputHead, inputTail, inputRing
              .public keyCommand, heldCommand, keyLatch, mouseCountX, mouseCountY
              .extern I_GetTime, inputIrq, InitFlash, J13Init, J13Prime, j13AdbPresent
              .public J13AdbSite
              .public keyTalk, keyPending, keyReply, captureStatusMask, captureTalk, withoutRawKeys
#include "memmap.inc"
#include "game.inc"
#include "tics.inc"

StartKeys:    sei
              jsl long:J13Init
              sep #0x20
drainKeys:    lda long:KMSTATUS
              and #0x20
              beq modesKeys
              lda long:DATAREG
              bra drainKeys
modesKeys:    lda long:j13AdbPresent
              beq compatibilityKeys
              lda #4
              jsr abs:.word0 (sendKeyCommand)
              lda #1                     ; raw keyboard; mouse polling stays on
              jsr abs:.word0 (sendKeyCommand)
              lda #0x52
              jsr abs:.word0 (sendKeyCommand)
              bra keysReady
;;; Without a raw ADB keyboard, retain firmware keyboard polling for the
;;; compatibility reader. The mouse and shared interrupt setup stay active.
compatibilityKeys:
              lda #5                     ; ClearModes
              jsr abs:.word0 (sendKeyCommand)
              lda #1                     ; clear keyboard-autopoll inhibition
              jsr abs:.word0 (sendKeyCommand)
keysReady:
              rep #0x20
              stz abs:.word0 (inputTimed)
              stz abs:.word0 (keyCommand)
              stz abs:.word0 (heldCommand)
              stz abs:.word0 (keyLatch)
              stz abs:.word0 (mouseCountX)
              stz abs:.word0 (mouseCountY)
              stz abs:.word0 (inputHead)
              stz abs:.word0 (inputTail)
              stz abs:.word0 (inputDropped)
              stz abs:.word0 (keyReply)
              stz abs:.word0 (keyTalk)
              stz abs:.word0 (keyPending)
              stz abs:.word0 (keyAction)
              lda ##0xc0
              sta abs:.word0 (mouseUp)
              ldx ##126
clearHeld:    stz abs:.word0 (keyHeld),x
              dex
              dex
              bpl clearHeld
              jsl long:I_GetTime
              sta abs:.word0 (inputCursor)
              sta dp:LASTTIC
              jsl long:InitFlash
              lda ##.word0 (inputIrq)
              sta long:IRQ_VECTOR
              sep #0x20
              lda #0
              pha
              lda #9
              sta long:SCCAREG           ; SCC master interrupts off
              pla
              sta long:SCCAREG
              sta long:INTEN           ; only ADB interrupts belong to input
              sta long:VGCINT
              sta long:SCANINT
              sta long:CLRVBLINT
flushOldMouse:
              lda long:KMSTATUS
              bpl inputEnables
              lda long:MOUSEDATA           ; firmware's pending startup report
              bra flushOldMouse
inputEnables:
              lda #0x50                  ; data and mouse, ASCII interrupts off
              sta long:KMSTATUS
              rep #0x20
              jsl long:CaptureInput       ; drain a byte predating the enables
              jsl long:J13Prime
              cli
              rts

sendKeyCommand:
              pha
              ldy ##4096
keyCommandWait:
              lda long:KMSTATUS
              lsr a
              bcc sendKeyReady
              dey
              bne keyCommandWait
              pla
              rts
sendKeyReady: pla
              sta long:DATAREG
              rts

;;; Called with DBR=2 and registers saved by the bank-0 IRQ entry. A partial
;;; Talk reply stays pending; its next byte generates another interrupt.
CaptureInput: sep #0x20
captureByte:
J13AdbSite:   lda long:KMSTATUS
captureStatusMask: and #0x20
              beq captureMouse
              lda long:DATAREG
              ldx abs:.word0 (keyReply)
              beq captureHeader
              cmp #255
              beq capturedKey
              sta abs:.word0 (irqValue)
              lda #0
              sta abs:.word0 (irqValue+1)
              rep #0x20
              stz abs:.word0 (irqType)
              stz abs:.word0 (irqAux)
              jsr abs:.word0 (queueInput)
              sep #0x20
capturedKey:  dec abs:.word0 (keyReply)
              bne captureByte
              stz abs:.word0 (keyTalk)
              bra captureByte
captureHeader:
              sta abs:.word0 (keyHeaderByte)
              bit #8
              beq noKeyRequest
              ldx ##1
              stx abs:.word0 (keyPending)
noKeyRequest: lda abs:.word0 (keyHeaderByte)
              bpl captureByte
              and #7
              beq emptyKeyReply
              inc a
              sta abs:.word0 (keyReply)
              bra captureByte
emptyKeyReply:
              stz abs:.word0 (keyTalk)
              bra captureByte
captureMouse: lda long:KMSTATUS
              bpl captureTalk
              bit #2
              beq mouseXY
              lda long:MOUSEDATA           ; discard an orphan Y, not a pair
              bra captureTalk
mouseXY:      lda long:MOUSEDATA
              sta abs:.word0 (irqValue)
              lda long:MOUSEDATA
              sta abs:.word0 (irqAux)
              rep #0x20
              lda ##1
              sta abs:.word0 (irqType)
              jsr abs:.word0 (queueInput)
              sep #0x20
              inc abs:.word0 (mouseTalkCount)
              ldx abs:.word0 (mouseTalkCount)
              cpx ##4
              bcc captureTalk
              ldx ##1                    ; keys may request service mid-motion
              stx abs:.word0 (keyPending)
captureTalk:  ldx abs:.word0 (keyPending)
              beq inputCaptured
              ldx abs:.word0 (keyTalk)
              bne inputCaptured
              lda long:KMSTATUS
              lsr a
              bcs inputCaptured
              lda #0xc2
              sta long:DATAREG
              ldx ##1
              stx abs:.word0 (keyTalk)
              stz abs:.word0 (keyPending)
              stz abs:.word0 (mouseTalkCount)
withoutRawKeys:
              stz abs:.word0 (keyPending)
inputCaptured:
              rep #0x20
              rtl

queueInput:   jsl long:I_GetTime
              ldx abs:.word0 (inputHead)
              sta abs:.word0 (inputRing),x
              lda abs:.word0 (irqType)
              sta abs:.word0 (inputRing+2),x
              lda abs:.word0 (irqValue)
              sta abs:.word0 (inputRing+4),x
              lda abs:.word0 (irqAux)
              sta abs:.word0 (inputRing+6),x
              txa
              clc
              adc ##8
              and ##1023
              cmp abs:.word0 (inputTail)
              beq inputOverflow
              sta abs:.word0 (inputHead)   ; publish only the complete event
              rts
inputOverflow:
              inc abs:.word0 (inputDropped)
              rts

;;; Drain the ADB events. keyCommand holds the bound keys down now plus any
;;; pressed since the last poll, so a tap shorter than a frame still acts.
;;; Mouse counts accumulate until the frame takes them. A (8 bits) = the
;;; character of the last action key, or 0.
ReadKeys:     rep #0x20
drainInput:   ldx abs:.word0 (inputTail)
              lda abs:.word0 (inputTimed)
              beq readCurrentHead
              cpx abs:.word0 (inputLimit)
              bra headCompared
readCurrentHead:
              cpx abs:.word0 (inputHead)
headCompared: bne inputQueued
              jmp abs:.word0 (inputCaughtUp)
inputQueued:  lda abs:.word0 (inputTimed)
              beq inputDue
              lda abs:.word0 (inputUntil)
              sec
              sbc abs:.word0 (inputRing),x
              bpl inputDue
              jmp abs:.word0 (inputCaughtUp)
inputDue:     lda abs:.word0 (inputRing+2),x
              cmp ##1
              beq applyMouseEvent
              lsr a
              inc a
              sta abs:.word0 (keySource)
              lda abs:.word0 (inputRing+4),x
              sep #0x20
              jsr abs:.word0 (applyRawKey)
              rep #0x20
              brl inputConsumed
applyMouseEvent:
              lda ##1
              sta abs:.word0 (keySource)
              lda abs:.word0 (inputRing+4),x
              and ##127
              cmp ##64
              bcc mouseXSigned
              ora ##0xff80
mouseXSigned: clc
              adc abs:.word0 (mouseCountX)
              sta abs:.word0 (mouseCountX)
              lda abs:.word0 (inputRing+6),x
              and ##127
              cmp ##64
              bcc mouseYSigned
              ora ##0xff80
mouseYSigned: clc
              adc abs:.word0 (mouseCountY)
              sta abs:.word0 (mouseCountY)
              lda abs:.word0 (inputRing+4),x
              and ##128
              lsr a
              sta abs:.word0 (mouseButtons)
              lda abs:.word0 (inputRing+6),x
              and ##128
              ora abs:.word0 (mouseButtons)
              sta abs:.word0 (mouseButtons)
              eor abs:.word0 (mouseUp)
              sta abs:.word0 (mouseChanges)
              lda abs:.word0 (mouseButtons)
              sta abs:.word0 (mouseUp)
              lda abs:.word0 (mouseChanges)
              bit ##128
              beq mouseStrafeButton
              lda abs:.word0 (mouseUp)
              and ##128
              ora ##0x7e
              sep #0x20
              jsr abs:.word0 (applyRawKey)
              rep #0x20
mouseStrafeButton:
              lda abs:.word0 (mouseChanges)
              bit ##64
              beq inputConsumed
              lda abs:.word0 (mouseUp)
              and ##64
              asl a
              ora ##0x70
              sep #0x20
              jsr abs:.word0 (applyRawKey)
              rep #0x20
inputConsumed:
              lda abs:.word0 (inputTail)
              clc
              adc ##8
              and ##1023
              sta abs:.word0 (inputTail)
              jmp abs:.word0 (drainInput)
inputCaughtUp:
              lda abs:.word0 (heldCommand)
              ora abs:.word0 (keyLatch)
              sta abs:.word0 (keyCommand)
              stz abs:.word0 (keyLatch)
              sep #0x20
              lda abs:.word0 (keyAction)
              stz abs:.word0 (keyAction)
              rts

;;; A (8 bits) = raw ADB key code, bit 7 set on release.
applyRawKey:  cmp #255
              beq rawKeyDone
              sta abs:.word0 (keyRaw)
              rep #0x20
              and ##127
              tax
              sep #0x20
              lda abs:.word0 (keyRaw)
              bmi rawKeyUp
              lda abs:.word0 (keyHeld),x
              pha
              ora abs:.word0 (keySource)
              sta abs:.word0 (keyHeld),x
              pla
              bne rawKeyDone
              rep #0x20
              inc abs:.word0 (inputSerial)
              sep #0x20
              .extern DebugKey
              jsl long:DebugKey
              beq remakeCommand
              sta abs:.word0 (keyAction)
              bra remakeCommand
rawKeyUp:     lda abs:.word0 (keySource)
              eor #255
              and abs:.word0 (keyHeld),x
              sta abs:.word0 (keyHeld),x
              bne rawKeyDone
remakeCommand:
              rep #0x20
              lda abs:.word0 (heldCommand)
              sta abs:.word0 (oldCommand)
              stz abs:.word0 (heldCommand)
              ldx ##BOUND_KEYS-2
bindingLoop:  lda abs:.word0 (boundKeys),x
              tay
              lda abs:.word0 (keyHeld),y
              and ##255
              beq bindingNext
              lda abs:.word0 (boundBits),x
              ora abs:.word0 (heldCommand)
              sta abs:.word0 (heldCommand)
bindingNext:  dex
              dex
              bpl bindingLoop
              lda abs:.word0 (oldCommand)  ; new presses latch for one poll
              eor ##0xffff
              and abs:.word0 (heldCommand)
              ora abs:.word0 (keyLatch)
              sta abs:.word0 (keyLatch)
              sep #0x20
rawKeyDone:   rts

              .section gamedata, data, root
inputSerial:  .word 0
keyCommand:   .word 0
heldCommand:  .word 0
oldCommand:   .word 0
keyLatch:     .word 0
mouseCountX:  .word 0
mouseCountY:  .word 0
inputHead:    .word 0
inputTail:    .word 0
inputDropped: .word 0
inputRing:    .space 1024
inputCursor:  .word 0
inputUntil:   .word 0
inputTimed:   .word 0
inputLimit:   .word 0
inputEventTime: .word 0
inputFrameTics: .word 0
inputMoveBudget: .word 0
inputWeaponBudget: .word 0
inputIntervalTics: .word 0
irqType:      .word 0
irqValue:     .word 0
irqAux:       .word 0
keyReply:     .word 0
keyTalk:      .word 0
keyPending:   .word 0
keyAction:    .word 0
keyRaw:       .word 0
keySource:    .word 1
keyHeaderByte: .word 0
keyHeld:      .space 128
mouseUp:      .word 0xc0
mouseButtons: .word 0
mouseChanges: .word 0
mouseDx:      .word 0
mouseTalkCount: .word 0
mouseSensitivity: .word 4
mouseWalk:    .word 1
boundKeys:    .word 0x0d,0x3e,0x01,0x3d,0x3b,0x3c,0x00,0x02,0x2b,0x2f
              .word 0x31,0x0e,0x03,0x36,0x7e,0x70,0x3a,0x37,0x38,0x39
BOUND_KEYS .equ 40
boundBits:    .word 1,1,2,2,4,8,256,512,256,512,16,16,32,32,32,64,64,64,128,128
keyChars: .byte 0,0,0,0,0,0,0,0,0,'V',0,'B','Q',0,0,'R','Y',0,'1','2','3','4',0,0,'=',0,0,'-',0,0,']',0,0,'[',0,'P',0,0,0,0,'K',0,0,0,0,'N','M',0,0,0,0,0,0,27,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,132,133,134,130,135,136,0,0,0,0,0,0,0,137,0,0,0,0,0,0,0,0,131,0,129,0,0,0,0,0,0,0
