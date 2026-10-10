;;; ROM 00/01 compatibility keyboard. Menus always accept it; gameplay is
;;; opt-in. C000/C010 provide character/any-key-down, not an 80-key bitmap.
;;; Only a matching MCU firmware fingerprint permits partial-release reads.
;;; Captured transitions enter the timestamped input ring with source tag 2.
;;; DOC interrupts sample registers; DATA interrupts retire private replies.
;;; A short-lived DOC alarm sends parameters while the CPU does other work.
;;; Controller service never installs a hook in the renderer.
#include "memmap.inc"
#include "frontend.inc"
#include "game.inc"
              .section inputcode, text, root, noreorder
              .public J13Init, J13Prime, J13Menu, J13Game, J13Benchmark, J13Stop
              .public J13Poll, J13Frame, J13EscapeFrame, J13Reset, J13Toggle
              .public J13SettingsLoad, J13SettingsStore
              .public j13Enabled, j13Available, j13Mode, j13Matrix, j13MenuSeen, j13Manual
              .public j13Owner, j13State, j13Timeouts, j13Samples, j13Events, j13Timer
              .public j13Keys, j13Mods, J13Sample, J13Pump
              .public J13SendIRQ, J13SendWake, j13SendTimer
              .extern I_GetTime, inputHead, inputTail, inputRing, inputDropped
              .extern CaptureInput, keyTalk, keyPending, keyReply, captureStatusMask, captureTalk, withoutRawKeys
              .extern J13FrameSite, J13AdbSite, fastAlarmHandled, noDocAlarm
              .extern musicActive, uiGameOn, keyHeld, UiResetInput, attractActive
AKD           .equ KBDSTRB
MODIFIERS     .equ KEYMODREG
ADBDATA       .equ DATAREG
ADBSTATUS     .equ KMSTATUS
NONE          .equ 255

;;; Before StartKeys owns ADB. Save firmware buffering/repeat policy, then
;;; validate the private row layout. Failure leaves only ASCII/all-up input.
J13Init:      php
              sei
              rep #0x30
              phb
              phk
              plb
              sep #0x20
              lda long:ROMVER
              cmp #2
              bcs initDone
              lda #1
              sta abs:.word0 (j13Available)
              ldy ##256
initDrain:    lda long:ADBSTATUS
              and #0x20
              beq initModes
              lda long:ADBDATA
              dey
              bne initDrain
              bra initDone
initModes:    lda #0x0a
              jsr abs:.word0 (sendBounded)
              bcs initDone
              jsr abs:.word0 (readBounded)
              bcs initDone
              sta abs:.word0 (savedModes)
              lda #1
              sta abs:.word0 (modesValid)
              jsr abs:.word0 (probeADB)
              jsr abs:.word0 (bufferKeyboard)
              ldx ##0
initSignature:phx
              rep #0x20
              txa
              cpx ##32
              bcs initSecond
              clc
              adc ##0x18ac
              bra initAddress
initSecond:   clc
              adc ##(0x1a10-32)
initAddress:  tax
              sep #0x20
              jsr abs:.word0 (readMCU)
              plx
              bcs initDone
              cmp long:matrixROM,x
              bne initDone
              inx
              cpx ##64
              bcc initSignature
              lda #1
              sta abs:.word0 (j13Matrix)
initDone:     rep #0x30
              plb
              plp
              rtl

J13Prime:     php
              sei
              rep #0x30
              phb
              phk
              plb
              lda abs:.word0 (j13Available)
              beq primeDone
              sep #0x20
              lda #3
              jsr abs:.word0 (sendBounded)
              lda long:AKD
              lda long:KBD
              and #127
              sta abs:.word0 (j13LastAscii)
              rep #0x20
              lda ##1
              sta abs:.word0 (j13Mode)
primeDone:    plb
              plp
              rtl

;;; Mode transitions happen outside timed frames. Finish an owned command
;;; before changing its IRQ mask; no game binding may remain held by J13.
J13Menu:      lda ##1
              bra setMode
J13Benchmark: lda ##0
              bra setMode
J13Game:      lda long:j13Enabled
              beq gameOff
              lda ##2
              bra setMode
gameOff:      lda ##0
setMode:      php
              sei
              rep #0x30
              pha
              phx
              phy
              phb
              phk
              plb
              lda abs:.word0 (j13Available)
              bne modeAvailable
              brl modeDone
modeAvailable:
              lda 6,s                     ; requested A below B,Y,X
              sta abs:.word0 (j13NextMode)
              jsr abs:.word0 (finishOwner)
              jsr abs:.word0 (removeOwnerIRQ)
              jsr abs:.word0 (stopSendTimer)
              jsr abs:.word0 (stopTimer)
              ; Restore the original IRQ exit and frame-time call first.
              lda ##0x20c2                 ; REP #$20
              sta long:fastAlarmHandled
              sep #0x20
              lda #0x4c                    ; JMP noDocAlarm
              sta long:fastAlarmHandled+2
              rep #0x20
              lda ##.word0 (noDocAlarm)
              sta long:fastAlarmHandled+3
              lda ##.word0 (I_GetTime)
              sta long:J13FrameSite+1
              sep #0x20
              lda #.byte2 I_GetTime
              sta long:J13FrameSite+3
              rep #0x20
              jsr abs:.word0 (clearHeld)
              lda abs:.word0 (j13NextMode)
              sta abs:.word0 (j13Mode)
              cmp ##2
              beq installGame
              cmp ##1
              beq modeDone
              lda ##.word0 (J13EscapeFrame)
              bra installFrame
installGame:  jsr abs:.word0 (initSendTimer)
              sep #0x20
              lda #0x5c
              sta long:fastAlarmHandled
              rep #0x20
              lda ##.word0 (j13Irq)
              sta long:fastAlarmHandled+1
              sep #0x20
              lda #.byte2 j13Irq
              sta long:fastAlarmHandled+3
              rep #0x20
              jsr abs:.word0 (ensureTimer)
              lda ##.word0 (J13Frame)
installFrame: sta long:J13FrameSite+1
              sep #0x20
              lda #.byte2 J13Frame
              sta long:J13FrameSite+3
              rep #0x20
modeDone:     plb
              ply
              plx
              pla
              plp
              rtl

;;; Menu recognition is once per program run, so explicitly selecting Off
;;; with J13 is not undone by the following Escape. Saving remains explicit.
J13Toggle:    lda long:j13Enabled
              eor ##1
              sta long:j13Enabled
              lda ##2
              sta long:j13Manual
              lda ##1
              sta long:j13MenuSeen
              rtl

;;; Bit 1 remembers an explicit choice, including saved Off. An untouched
;;; default remains eligible for automatic enable on the first menu use.
J13SettingsLoad:
              lda long:SETTINGS_IN + S_J13
              and ##1
              and long:j13Available
              sta long:j13Enabled
              lda long:SETTINGS_IN + S_J13
              and ##2
              sta long:j13Manual
              sta long:j13MenuSeen
              rtl
J13SettingsStore:
              lda long:j13Enabled
              ora long:j13Manual
              sep #0x20
              sta long:SETTINGS_IN + S_J13
              rep #0x20
              rtl

;;; Called by PollKey in menus and attract playback. Benchmark mode only
;;; checks Escape; it does not run gameplay capture or MCU row scans.
J13Poll:      php
              sei
              rep #0x30
              phb
              phk
              plb
              lda abs:.word0 (j13Available)
              beq pollDone
              lda abs:.word0 (j13Mode)
              beq pollEscape
              cmp ##2
              bne pollSample
              jsr abs:.word0 (readControllerClock)
pollSample:
              jsr abs:.word0 (J13Sample)
              jsr abs:.word0 (scheduleRow)
              jsr abs:.word0 (J13Pump)
              bra pollDone
pollEscape:   jsr abs:.word0 (escapeSample)
pollDone:     plb
              plp
              rtl

J13Frame:     php
              sei
              phb
              phk
              plb
              jsr abs:.word0 (readControllerClock)
              jsr abs:.word0 (J13Sample)
              jsr abs:.word0 (ensureTimer)
              jsr abs:.word0 (scheduleRow)
              jsr abs:.word0 (serviceController)
              lda abs:.word0 (controllerTime)
              ldx abs:.word0 (controllerTime+2)
              plb
              plp
              rtl
readControllerClock:
              phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              jsl long:I_GetTime
              plb
              sta abs:.word0 (controllerTime)
              stx abs:.word0 (controllerTime+2)
              rts
J13EscapeFrame:
              php
              sei
              phb
              phk
              plb
              jsr abs:.word0 (escapeSample)
              plb
              plp
              jmp long:I_GetTime
escapeSample: sep #0x20
              lda long:KBD
              bpl escapeDone
              pha
              lda long:AKD
              pla
              cmp #0x9b
              bne escapeDone
              rep #0x20
              jsr abs:.word0 (queueRoom)
              bcc escapeDone
              jsr abs:.word0 (menuUsed)
              stz abs:.word0 (sampleTimed)
              lda ##0x35
              jsr abs:.word0 (queue)
              lda ##0xb5
              jsr abs:.word0 (queue)
escapeDone:   rep #0x20
              rts

;;; The DOC IRQ entry already saved every register and DBR. Private replies
;;; belong to the DATA interrupt; sampling never issues a controller command.
j13Irq:       rep #0x30
              phk
              plb
              jsr abs:.word0 (J13Sample)
irqCaptureDone:
              jmp long:noDocAlarm

;;; Caller masks IRQs, DBR=code bank, A/X/Y16. Reserve room before touching C010.
;;; At most five modifiers, three releases and a repress pair can be queued.
J13Sample:    jsr abs:.word0 (queueRoom)
              bcs sampleRoom
              rts
sampleRoom:   inc abs:.word0 (j13Samples)
              sep #0x20
              lda long:KBD
              ; Recover a character whose strobe raced the previous C010.
              bmi sampleFresh
              cmp abs:.word0 (j13LastAscii)
              beq sampleUnchanged
              ora #128
sampleFresh:  sta abs:.word0 (sampleAscii)
              and #127
              sta abs:.word0 (j13LastAscii)
              ; Snapshot character modifiers before acknowledging C010.
              lda long:MODIFIERS
              sta abs:.word0 (sampleMods)
              lda long:AKD
              sta abs:.word0 (sampleAKD)
              jsr abs:.word0 (readModifiers)
              stz abs:.word0 (sampleTimed)
              bra sampleModifiers
sampleUnchanged:
              sta abs:.word0 (sampleAscii)
              lda long:AKD
              sta abs:.word0 (sampleAKD)
              ; With an ordinary key held, P3 replies already publish live
              ; modifiers. No new character means no translation work here.
              bpl sampleIdleModifiers
              rep #0x20
              lda abs:.word0 (j13Mode)
              cmp ##2
              bne sampleLive8
              lda abs:.word0 (physicalValid)
              beq sampleLive8
              rts
sampleLive8:  sep #0x20
sampleIdleModifiers:
              lda long:MODIFIERS
              ; AKD can clear before C025 stops describing the old character.
              ; Bit 5 identifies an independent modifier-latch update.
              bit #0x20
              bne sampleIdleReady
              rep #0x20
              jmp abs:.word0 (sampleRelease)
sampleIdleReady:
              stz abs:.word0 (physicalValid)
              sta abs:.word0 (sampleMods)
              jsr abs:.word0 (readModifiers)
              cmp abs:.word0 (j13Mods)
              beq sampleNoModifierChange
              stz abs:.word0 (sampleTimed)
              jsr abs:.word0 (updateModifiers)
sampleNoModifierChange:
              jmp abs:.word0 (sampleRelease)
readModifiers:
              lda abs:.word0 (sampleMods)
              and #0xc7
              sta abs:.word0 (nextMods)
              lda long:BUTN0
              bpl sampleApple1
              lda abs:.word0 (nextMods)
              ora #128
              sta abs:.word0 (nextMods)
sampleApple1: lda long:BUTN1
              bpl sampleModifierBits
              lda abs:.word0 (nextMods)
              ora #64
              sta abs:.word0 (nextMods)
sampleModifierBits:
              rep #0x20
              lda abs:.word0 (nextMods)
              rts
sampleModifiers:
              lda abs:.word0 (j13Mode)
              cmp ##2
              bne sampleUpdateMods
              ; A fresh character is newer than the cached P3 reply. Repeat
              ; modifier bits can be mistranslated, so retain live state there.
              lda abs:.word0 (sampleMods)
              bit ##8
              beq sampleUpdateMods
              lda abs:.word0 (physicalValid)
              beq sampleRepeatMods
              lda abs:.word0 (physicalMods)
              bra sampleKeepMods
sampleRepeatMods:
              lda abs:.word0 (j13Mods)
sampleKeepMods:
              sta abs:.word0 (nextMods)
sampleUpdateMods:
              jsr abs:.word0 (updateModifiers)
              bra sampleCharacter
updateModifiers:
              lda abs:.word0 (nextMods)
              cmp abs:.word0 (j13Mods)
              bne modifiersChanged
              rts
modifiersChanged:
              ldx ##0
sampleModifier:
              lda abs:.word0 (nextMods)
              eor abs:.word0 (j13Mods)
              and long:modifierMasks,x
              and ##255
              beq sampleNextModifier
              lda abs:.word0 (nextMods)
              and long:modifierMasks,x
              and ##255
              beq sampleModifierUp
              lda long:modifierKeys,x
              and ##255
              bra sampleModifierQueue
sampleModifierUp:
              lda long:modifierKeys,x
              and ##255
              ora ##128
sampleModifierQueue:
              jsr abs:.word0 (queue)
sampleNextModifier:
              inx
              cpx ##5
              bcc sampleModifier
              lda abs:.word0 (nextMods)
              sta abs:.word0 (j13Mods)
              rts
sampleCharacter:
              lda abs:.word0 (sampleAscii)
              bit ##128
              beq sampleRelease
              lda abs:.word0 (sampleMods)
              bit ##8                       ; firmware repeat is not a fresh down
              bne sampleRelease
              lda abs:.word0 (sampleAscii)
              and ##127
              tax
              lda long:asciiKeys,x
              and ##255
              cmp ##NONE
              beq sampleRelease
              sta abs:.word0 (newKey)
              lda abs:.word0 (j13Mode)
              cmp ##1
              bne sampleOrdinary
              lda abs:.word0 (j13MenuSeen)
              bne sampleOrdinary
              ; Ignored title/demo keys do not opt gameplay in.
              lda long:attractActive
              bne sampleAttractKey
              lda long:UI_SCREEN
              and ##255
              cmp ##13
              bne sampleMenuUsed
sampleAttractKey:
              lda abs:.word0 (newKey)
              cmp ##0x35
              bne sampleOrdinary
sampleMenuUsed:
              jsr abs:.word0 (menuUsed)
sampleOrdinary:
              jsr abs:.word0 (ordinaryDown)
sampleRelease:lda abs:.word0 (sampleAKD)
              bit ##128
              bne sampleDone
              lda abs:.word0 (knownCount)
              beq sampleDone
              stz abs:.word0 (sampleTimed)
              jsr abs:.word0 (releaseOrdinary)
sampleDone:   rts

menuUsed:     lda abs:.word0 (j13MenuSeen)
              bne menuUseDone
              lda ##1
              sta abs:.word0 (j13MenuSeen)
              sta abs:.word0 (j13Enabled)
menuUseDone:  rts

ordinaryDown: inc abs:.word0 (j13Generation)
              ldx ##0
ordinaryFind: lda abs:.word0 (j13Keys),x
              cmp abs:.word0 (newKey)
              beq ordinaryRepress
              inx
              inx
              cpx ##6
              bcc ordinaryFind
              lda abs:.word0 (j13Mode)
              cmp ##2
              bne ordinarySingle
              lda abs:.word0 (j13Matrix)
              beq ordinarySingle
              ldx abs:.word0 (newKey)
              cpx ##64
              bcs ordinarySingle
              lda long:pumpMasks,x
              and ##255
              beq ordinarySingle
              ldx ##0
ordinarySlot: lda abs:.word0 (j13Keys),x
              cmp ##NONE
              beq ordinaryInstall
              inx
              inx
              cpx ##6
              bcc ordinarySlot
              rts                            ; three ordinary identities maximum
ordinarySingle:
              jsr abs:.word0 (releaseOrdinary)
              ldx ##0
ordinaryInstall:
              lda abs:.word0 (newKey)
              sta abs:.word0 (j13Keys),x
              inc abs:.word0 (knownCount)
              jmp abs:.word0 (queue)
ordinaryRepress:
              ora ##128
              jsr abs:.word0 (queue)
              lda abs:.word0 (newKey)
              jmp abs:.word0 (queue)
releaseOrdinary:
              ldx ##0
releaseKey:   lda abs:.word0 (j13Keys),x
              cmp ##NONE
              beq releaseNext
              ora ##128
              jsr abs:.word0 (queue)
              lda ##NONE
              sta abs:.word0 (j13Keys),x
releaseNext:  inx
              inx
              cpx ##6
              bcc releaseKey
              stz abs:.word0 (knownCount)
              rts

queueRoom:    lda long:inputTail
              sec
              sbc long:inputHead
              dec a
              and ##1023
              cmp ##(10*8)
              rts
;;; Preserve X/Y. Timestamp once for all transitions from one sample.
queue:        phx
              phy
              pha
              lda abs:.word0 (sampleTimed)
              bne queueTimed
              phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              jsl long:I_GetTime
              plb
              sta abs:.word0 (sampleTime)
              inc abs:.word0 (sampleTimed)
queueTimed:   lda long:inputHead
              tax
              lda abs:.word0 (sampleTime)
              sta long:inputRing,x
              lda ##2
              sta long:inputRing+2,x
              pla
              sta long:inputRing+4,x
              lda ##0
              sta long:inputRing+6,x
              txa
              clc
              adc ##8
              and ##1023
              sta long:inputHead
              inc abs:.word0 (j13Events)
              ply
              plx
              rts

;;; Read live modifiers, then one of at most three held rows, per two tics.
;;; Frame input starts the command; the short DOC alarm sends parameters.
;;; The reply arrives through DATA IRQ, independently of picture duration.
;;; One ordinary key needs only P3: AKD gives that key's release.
scheduleRow:  lda abs:.word0 (j13Mode)
              cmp ##2
              beq scheduleGame
              rts
scheduleGame: lda abs:.word0 (j13State)
              beq j13Long1
              brl scheduleDone
j13Long1:
              lda abs:.word0 (j13Matrix)
              bne j13Long2
              brl scheduleDone
j13Long2:
              lda abs:.word0 (knownCount)
              cmp ##1
              bcs scheduleHasKeys
              rts
scheduleHasKeys:
              lda abs:.word0 (controllerTime)
              sec
              sbc abs:.word0 (lastRowTime)
              cmp ##2
              bcc scheduleDone
              clc
              adc abs:.word0 (lastRowTime)
              sta abs:.word0 (lastRowTime)
              lda ##0xe8                  ; live P3 modifiers while a key is held
              sta abs:.word0 (rowAddress)
              bra scheduleReady
scheduleHeldRow:
              lda abs:.word0 (knownCount)
              cmp ##2
              bcs scheduleTwoKeys
              rts
scheduleTwoKeys:
              ldx abs:.word0 (rowNext)
schedulePick: inx
              inx
              cpx ##6
              bcc scheduleIndex
              ldx ##0
scheduleIndex:lda abs:.word0 (j13Keys),x
              cmp ##NONE
              beq schedulePick
              stx abs:.word0 (rowNext)
              tax
              lda long:pumpRows,x
              and ##255
              sta abs:.word0 (rowAddress)
              stz abs:.word0 (rowExpected)
              ldy ##0
scheduleMask: lda abs:.word0 (j13Keys),y
              cmp ##64
              bcs scheduleMaskNext
              tax
              lda long:pumpRows,x
              and ##255
              cmp abs:.word0 (rowAddress)
              bne scheduleMaskNext
              lda long:pumpMasks,x
              and ##255
              ora abs:.word0 (rowExpected)
              sta abs:.word0 (rowExpected)
scheduleMaskNext:
              iny
              iny
              cpy ##6
              bcc scheduleMask
scheduleReady:lda abs:.word0 (lastRowTime)
              clc
              adc ##70
              sta abs:.word0 (rowDeadline)
              lda ##1
              sta abs:.word0 (j13State)
scheduleDone: rts

;;; One status sample per call. Pending ADB Talk, DATA or mouse wins before
;;; acquisition. While owned, only DATA IRQ/parsing is masked; mouse runs.
J13Pump:      lda abs:.word0 (j13State)
              bne pumpActive
              rts
pumpActive:   sep #0x20
              lda long:ADBSTATUS
              sta abs:.word0 (rowStatus)
              lda abs:.word0 (j13State)
              cmp #1
              bne pumpOwned
              lda long:keyTalk
              ora long:keyPending
              beq j13Long3
              brl pumpDone
j13Long3:
              lda abs:.word0 (rowStatus)
              and #0xa1
              beq j13Long4
              brl pumpDone
j13Long4:
              lda abs:.word0 (rowStatus)
              and #0x50
              sta abs:.word0 (rowEnables)
              lda abs:.word0 (rowStatus)
              and #0x40
              sta long:ADBSTATUS
              lda #0
              sta long:captureStatusMask+1
              lda #1
              sta abs:.word0 (j13Owner)
              sta long:keyTalk
              jsr abs:.word0 (installOwnerIRQ)
              lda #9
              sta long:ADBDATA
              sta long:ZIPCANCEL
              lda #2
              sta abs:.word0 (j13State)
              rep #0x20
              lda abs:.word0 (j13Generation)
              sta abs:.word0 (rowGeneration)
              jsr abs:.word0 (startSendTimer)
              rts
pumpOwned:    lda abs:.word0 (rowStatus)
              bit #0x20
              bne pumpData
              lda abs:.word0 (j13State)
              cmp #4
              bne pumpSend
              brl pumpDone
pumpSend:
              lda abs:.word0 (rowStatus)
              and #1
              beq j13Long5
              brl pumpDone
j13Long5:
              lda abs:.word0 (j13State)
              cmp #2
              bne pumpHigh
              lda abs:.word0 (rowAddress)
              sta long:ADBDATA
              sta long:ZIPCANCEL
              lda #3
              sta abs:.word0 (j13State)
              brl pumpDone
pumpHigh:     lda #0
              sta long:ADBDATA
              sta long:ZIPCANCEL
              lda #4
              sta abs:.word0 (j13State)
              lda abs:.word0 (rowEnables)
              sta long:ADBSTATUS
              rep #0x20
              jsr abs:.word0 (stopSendTimer)
              brl pumpDone
pumpData:     lda long:ADBDATA
              sta abs:.word0 (rowValue)
              lda abs:.word0 (j13State)
              cmp #4
              bne pumpStatusByte
              lda abs:.word0 (rowAddress)
              cmp #0xe8
              bne pumpMatrixReply
              lda abs:.word0 (rowValue)
              cmp #8                      ; keyboard SRQ
              beq pumpStatusByte
              cmp #0x20                   ; Escape notification
              beq pumpStatusByte
              cmp #0x40                   ; controller error
              beq pumpStatusByte
              rep #0x20
              brl pumpPhysicalReply
pumpMatrixReply:
              lda abs:.word0 (rowValue)
              eor #255
              ora abs:.word0 (rowExpected)
              cmp abs:.word0 (rowExpected)
              beq pumpValidReply
              ; Status notifications may precede the single-byte row reply.
              lda abs:.word0 (rowValue)
              and #0x87
              beq pumpStatusByte
              rep #0x20
              jsr abs:.word0 (releaseOwner)
              brl pumpDone                  ; ambiguous row: no inferred releases
pumpStatusByte:
              lda abs:.word0 (rowValue)
              and #0x87
              bne pumpStatusDone
              lda abs:.word0 (rowValue)
              and #8
              ora abs:.word0 (rowDeferred)
              sta abs:.word0 (rowDeferred)
pumpStatusDone:
              rep #0x20
              rts
pumpValidReply:
              rep #0x20
              jsr abs:.word0 (releaseOwner)
              jsr abs:.word0 (queueRoom)
              bcs pumpHaveRoom
              brl pumpDone
pumpHaveRoom: lda abs:.word0 (rowGeneration)
              cmp abs:.word0 (j13Generation)
              beq pumpCurrentGeneration
              brl pumpDone                  ; reply predates a newly pressed key
pumpCurrentGeneration:
              stz abs:.word0 (sampleTimed)
              ldy ##0
rowRelease:   lda abs:.word0 (j13Keys),y
              cmp ##64
              bcs rowReleaseNext
              tax
              lda long:pumpRows,x
              and ##255
              cmp abs:.word0 (rowAddress)
              bne rowReleaseNext
              lda long:pumpMasks,x
              and abs:.word0 (rowValue)
              and ##255
              beq rowReleaseNext
              txa
              ora ##128
              jsr abs:.word0 (queue)
              lda ##NONE
              sta abs:.word0 (j13Keys),y
              dec abs:.word0 (knownCount)
rowReleaseNext:
              iny
              iny
              cpy ##6
              bcc rowRelease
pumpDone:     rep #0x20
              rts

;;; C025 stays at its character's modifier state while ordinary keys remain
;;; down. Firmware P3 ($E8) supplies live independent switches; bits 0..2 are
;;; active low and Apple bits 6/7 active high. P3 is read only on validated ROM.
pumpPhysicalReply:
              jsr abs:.word0 (releaseOwner)
              ; An intervening character/all-up transition owns newer state.
              lda abs:.word0 (knownCount)
              beq physicalDone
              lda abs:.word0 (rowGeneration)
              cmp abs:.word0 (j13Generation)
              bne physicalDone
              lda abs:.word0 (rowValue)
              eor ##7
              and ##0xc7
              sta abs:.word0 (physicalMods)
              sta abs:.word0 (nextMods)
              lda ##1
              sta abs:.word0 (physicalValid)
              jsr abs:.word0 (queueRoom)
              bcc physicalNoRoom
              stz abs:.word0 (sampleTimed)
              jsr abs:.word0 (updateModifiers)
physicalNoRoom:
              lda abs:.word0 (knownCount)
              cmp ##2
              bcc physicalDone
              jmp abs:.word0 (scheduleHeldRow)
physicalDone: rts

 ; One foreground service step. The parameter alarm and DATA IRQ complete
 ; owned commands asynchronously; a busy raw ADB transaction defers capture.
serviceController:
              jsr abs:.word0 (J13Pump)
              lda abs:.word0 (j13State)
              cmp ##4
              bcc serviceDone
              bra serviceDeadline
serviceTimeout:
              inc abs:.word0 (j13Timeouts)
              stz abs:.word0 (j13Matrix)
              jmp abs:.word0 (releaseOwner)
serviceDeadline:
              lda abs:.word0 (controllerTime)
              sec
              sbc abs:.word0 (rowDeadline)
              bpl serviceTimeout
serviceDone:  rts

releaseOwner: sep #0x20
              lda #0x20
              sta long:captureStatusMask+1
              lda #0
              sta long:keyTalk
              sta abs:.word0 (j13Owner)
              lda abs:.word0 (rowDeferred)
              beq releaseNoPending
              lda #1
              sta long:keyPending
releaseNoPending:
              stz abs:.word0 (rowDeferred)
              lda abs:.word0 (rowEnables)
              sta long:ADBSTATUS
              rep #0x20
              stz abs:.word0 (j13State)
              jsr abs:.word0 (removeOwnerIRQ)
              jsr abs:.word0 (stopSendTimer)
              rts
;;; Transition cleanup may wait. Never abandon a partially sent $09 command
;;; and let the ADB parser consume its reply. A timeout disables future rows
;;; after allowing the validated firmware to finish its bounded receive wait.
finishOwner:  lda abs:.word0 (j13Owner)
              beq finishIdle
              ldy ##16384
finishWait:   phy
              jsr abs:.word0 (J13Pump)
              ply
              lda abs:.word0 (j13Owner)
              beq finishIdle
              dey
              bne finishWait
              inc abs:.word0 (j13Timeouts)
              stz abs:.word0 (j13Matrix)
              jmp abs:.word0 (releaseOwner)
finishIdle:   stz abs:.word0 (j13State)
              rts

 ; Private command replies use the existing ADB interrupt. Its parser
 ; remains displaced only while this owner holds C026; mouse service follows
 ; normally and pending raw keyboard SRQs are replayed when ownership ends.
 ; Caller masks IRQs and has A8. Restore the original LDA long instruction.
installOwnerIRQ:
              lda #0x5c
              sta long:J13AdbSite
              rep #0x20
              lda ##.word0 (ownerDataIRQ)
              sta long:J13AdbSite+1
              sep #0x20
              lda #.byte2 ownerDataIRQ
              sta long:J13AdbSite+3
              rts
removeOwnerIRQ:
              lda ##0x27af
              sta long:J13AdbSite
              lda ##0xe0c0
              sta long:J13AdbSite+2
              rts
ownerDataIRQ:
              phb
              phk
              plb
              rep #0x20
              jsr abs:.word0 (J13Pump)
              plb
              sep #0x20
              lda long:ADBSTATUS
              jmp long:J13AdbSite+4

;;; One-shot effects use oscillators 0..3 and no refill alarm. Oscillator 28
;;; is reserved here for parameter delivery. Its 1 ms period advances only
;;; an owned exchange and stops as soon as both address bytes are sent.
;;; It never runs while Off, in menus, or while waiting for the DATA reply.
;;; The IRQ entry has saved all registers. Do not sample keys on this alarm.
J13SendIRQ:   rep #0x30
              phk
              plb
              jsr abs:.word0 (sendAlarm)
              jmp long:noDocAlarm
;;; Foreground DOC draining must also advance an owned parameter exchange.
J13SendWake:  rep #0x30
              phb
              phk
              plb
              jsr abs:.word0 (sendAlarm)
              plb
              rtl
sendAlarm:
              lda abs:.word0 (j13SendTimer)
              beq sendIRQDone
              dec abs:.word0 (sendBudget)
              beq sendIRQTimeout
              jsr abs:.word0 (J13Pump)
sendIRQDone:  rts
sendIRQTimeout:
              jmp abs:.word0 (serviceTimeout)

initSendTimer:
              sep #0x20
              ldx ##0xbc
              lda #1
              jsr abs:.word0 (docRegister)
              ldx ##0x1c
              lda #0x88                   ; frequency 5000: approximately 1 ms
              jsr abs:.word0 (docRegister)
              ldx ##0x3c
              lda #0x13
              jsr abs:.word0 (docRegister)
              ldx ##0x5c
              lda #0
              jsr abs:.word0 (docRegister)
              ldx ##0xdc
              jsr abs:.word0 (docRegister)
              ldx ##0x9c
              lda #255
              jsr abs:.word0 (docRegister)
              rep #0x20
              rts
startSendTimer:
              lda ##32
              sta abs:.word0 (sendBudget)
              lda ##1
              sta abs:.word0 (j13SendTimer)
              sep #0x20
              ldx ##0xbc
              lda #8
              jsr abs:.word0 (docRegister)
              rep #0x20
              rts
stopSendTimer:
              lda abs:.word0 (j13SendTimer)
              beq sendTimerStopped
              stz abs:.word0 (j13SendTimer)
              sep #0x20
              ldx ##0xbc
              lda #1
              jsr abs:.word0 (docRegister)
              rep #0x20
sendTimerStopped:
              rts

;;; Reuse stopped music's silent alarm 29; never add a timer to a playing
;;; song. The free-running 256-byte ramp gives about 32 ms at frequency 155.
ensureTimer:  lda long:musicActive
              beq timerNeeded
              stz abs:.word0 (j13Timer)
              rts
timerNeeded:  lda abs:.word0 (j13Timer)
              bne timerDone
              sep #0x20
              ldx ##0xbd
              lda #1
              jsr abs:.word0 (docRegister)
              ldx ##0x1d
              lda #155
              jsr abs:.word0 (docRegister)
              ldx ##0x3d
              lda #0
              jsr abs:.word0 (docRegister)
              ldx ##0x5d
              jsr abs:.word0 (docRegister)
              ldx ##0x9d
              lda #255
              jsr abs:.word0 (docRegister)
              ldx ##0xdd
              lda #0
              jsr abs:.word0 (docRegister)
              ldx ##0xbd
              lda #8
              jsr abs:.word0 (docRegister)
              rep #0x20
              lda ##1
              sta abs:.word0 (j13Timer)
timerDone:    rts
stopTimer:    lda abs:.word0 (j13Timer)
              beq timerDone
              stz abs:.word0 (j13Timer)
              lda long:musicActive
              bne timerDone
              sep #0x20
              ldx ##0xbd
              lda #1
              jsr abs:.word0 (docRegister)
              rep #0x20
              rts
docRegister:  pha
docReady:     lda long:SOUNDCTL
              bmi docReady
              lda long:SYSTEM_VOLUME
              and #15
              ora #0x20
              sta long:SOUNDCTL
              txa
              sta long:SOUNDADRL
              pla
              sta long:SOUNDDATA
              rts

J13Reset:     php
              sei
              rep #0x30
              phb
              phk
              plb
              jsr abs:.word0 (finishOwner)
              jsr abs:.word0 (removeOwnerIRQ)
              jsr abs:.word0 (clearHeld)
              plb
              plp
              rtl
clearHeld:    lda ##NONE
              sta abs:.word0 (j13Keys)
              sta abs:.word0 (j13Keys+2)
              sta abs:.word0 (j13Keys+4)
              stz abs:.word0 (j13Mods)
              stz abs:.word0 (knownCount)
              stz abs:.word0 (physicalValid)
              inc abs:.word0 (j13Generation)
              ; Remove only J13's held bit from the merged consumer state.
              ldx ##127
              sep #0x20
clearSource:  lda long:keyHeld,x
              and #1
              sta long:keyHeld,x
              dex
              bpl clearSource
              lda long:AKD
              lda long:KBD
              and #127
              sta abs:.word0 (j13LastAscii)
              rep #0x20
              rts

J13Stop:      jsl long:J13Benchmark
              php
              sei
              rep #0x30
              phb
              phk
              plb
              ; Finish outstanding raw Talk before sending firmware commands.
              ldy ##16384
stopTalk:     phy
              phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              jsl long:CaptureInput
              plb
              ply
              lda long:keyTalk
              beq stopRestore
              dey
              bne stopTalk
              bra stopDone
stopRestore:  sep #0x20
              jsr abs:.word0 (restoreFirmwareRepeat)
              lda abs:.word0 (modesValid)
              beq stopDone
              lda #5
              jsr abs:.word0 (sendBounded)
              bcs stopDone
              lda #0x11
              jsr abs:.word0 (sendBounded)
              bcs stopDone
              lda #4
              jsr abs:.word0 (sendBounded)
              bcs stopDone
              lda abs:.word0 (savedModes)
              and #0x11
              jsr abs:.word0 (sendBounded)
stopDone:     rep #0x20
              plb
              plp
              rtl

j13Enabled:   .word 0
              .public j13AdbPresent
j13AdbPresent:.word 1
j13Available: .word 0
j13Matrix:    .word 0
j13Mode:      .word 0
j13NextMode:  .word 0
j13MenuSeen:  .word 0
j13Manual:    .word 0                      ; saved bit 1: explicit On/Off
j13Owner:     .word 0
j13State:     .word 0
j13Timeouts:  .word 0
j13Samples:   .word 0
j13Events:    .word 0
j13Timer:     .word 0
j13SendTimer: .word 0
sendBudget:   .word 0
j13Keys:      .word NONE,NONE,NONE
j13Mods:      .word 0
knownCount:   .word 0
controllerTime:.word 0,0
physicalMods: .word 0
physicalValid:.word 0
rowDeadline:  .word 0
nextMods:     .word 0
newKey:       .word 0
j13Generation:.word 0
rowGeneration:.word 0
rowNext:      .word 0
rowAddress:   .word 0
rowExpected:  .word 0
rowValue:     .word 0
rowEnables:   .word 0
rowStatus:    .word 0
rowDeferred:  .word 0
lastRowTime:  .word 0
sampleAscii:  .word 0
sampleMods:   .word 0
sampleAKD:    .word 0
j13LastAscii: .word 0
sampleTime:   .word 0
sampleTimed:  .word 0
savedModes:   .byte 0
modesValid:   .byte 0

sendBounded:  pha
              ldy     ##16384
1$:           lda     long:ADBSTATUS
              and     #1
              beq     2$
              dey
              bne     1$
              pla
              sec
              rts
2$:           pla
              sta     long:ADBDATA
              sta     long:ZIPCANCEL
              clc
              rts
readBounded:  ldy     ##16384
1$:           lda     long:ADBSTATUS
              and     #0x20
              bne     2$
              dey
              bne     1$
              sec
              rts
2$:           lda     long:ADBDATA
              clc
              rts


modifierMasks: .byte 0x01, 0x02, 0x04, 0x80, 0x40
modifierKeys:  .byte 0x38, 0x36, 0x39, 0x37, 0x3a, 0

;;; Translate the low seven ASCII bits to synthetic ADB identities.
;;; Navigation aliases take precedence (Ctrl-H becomes Left); shifted
;;; punctuation maps to its unshifted US key. This mapping cannot distinguish
;;; keys that produce the same character. A NONE entry would be ignored by
;;; the caller; release information comes from AKD or a validated row.
asciiKeys:
              .byte   0x31, 0x00, 0x0b, 0x08, 0x02, 0x0e, 0x03, 0x05, 0x3b, 0x30, 0x3d, 0x3e, 0x25, 0x24, 0x2d, 0x1f ; $00-$0F
              .byte   0x23, 0x0c, 0x0f, 0x01, 0x11, 0x3c, 0x09, 0x0d, 0x07, 0x10, 0x06, 0x35, 0x2a, 0x1e, 0x16, 0x1b ; $10-$1F
              .byte   0x31, 0x12, 0x27, 0x14, 0x15, 0x17, 0x1a, 0x27, 0x19, 0x1d, 0x1c, 0x18, 0x2b, 0x1b, 0x2f, 0x2c ; $20-$2F
              .byte   0x1d, 0x12, 0x13, 0x14, 0x15, 0x17, 0x16, 0x1a, 0x1c, 0x19, 0x29, 0x29, 0x2b, 0x18, 0x2f, 0x2c ; $30-$3F
              .byte   0x13, 0x00, 0x0b, 0x08, 0x02, 0x0e, 0x03, 0x05, 0x04, 0x22, 0x26, 0x28, 0x25, 0x2e, 0x2d, 0x1f ; $40-$4F
              .byte   0x23, 0x0c, 0x0f, 0x01, 0x11, 0x20, 0x09, 0x0d, 0x07, 0x10, 0x06, 0x21, 0x2a, 0x1e, 0x16, 0x1b ; $50-$5F
              .byte   0x32, 0x00, 0x0b, 0x08, 0x02, 0x0e, 0x03, 0x05, 0x04, 0x22, 0x26, 0x28, 0x25, 0x2e, 0x2d, 0x1f ; $60-$6F
              .byte   0x23, 0x0c, 0x0f, 0x01, 0x11, 0x20, 0x09, 0x0d, 0x07, 0x10, 0x06, 0x21, 0x2a, 0x1e, 0x32, 0x33 ; $70-$7F


readMCU:      lda     #9
              jsr     abs:.word0 sendBounded
              bcs     readMCUDone
              txa
              jsr     abs:.word0 sendBounded
              bcs     readMCUDone
              rep     #0x20
              txa
              xba
              sep     #0x20
              jsr     abs:.word0 sendBounded
              bcs     readMCUDone
              jsr     abs:.word0 readBounded
readMCUDone:  rts


;;; Scanner bytes followed by row-update bytes, in identifyLoop read order.
matrixROM:
              .byte 0x3c, 0xff, 0xe4, 0xa2, 0x09, 0x22, 0x59, 0x3c, 0x0a, 0x48, 0xc6, 0x48, 0x30, 0x5b, 0xa5, 0x48, 0xaa, 0x8b, 0x85, 0xe4, 0xb5, 0x31, 0x45, 0xe2, 0x3c, 0xff, 0xe4, 0xf0, 0xed, 0xa0, 0x08, 0x88
              .byte 0x22, 0xb4, 0xf7, 0x4c, 0x05, 0x15, 0x31, 0x95, 0x31, 0x60, 0x8f, 0x0a, 0xe7, 0x0f, 0x06, 0x49, 0xff, 0x35, 0x31, 0x95, 0x31, 0x22, 0xc5, 0x33, 0x1c, 0xf3, 0x1a, 0xa6, 0x4c, 0xe0, 0x37, 0xf0

;;; Indexed by the synthetic ADB identity from asciiKeys: MCU RAM row and
;;; active-low switch mask. Row $FF/mask 0 means no supported matrix entry.
;;; Same-row keys share a read; pumpCachePair merges their expected masks.
pumpRows:
              .byte 0x31, 0x33, 0x32, 0x35, 0x34, 0x36, 0x31, 0x32, 0x33, 0x34, 0xff, 0x35, 0x32, 0x33, 0x34, 0x35
              .byte 0x36, 0x37, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x3a, 0x38, 0x3a, 0x39, 0x39, 0x3a, 0x3a
              .byte 0x38, 0x39, 0x39, 0x38, 0x37, 0x3a, 0x37, 0x3a, 0x38, 0x39, 0x37, 0x38, 0x3a, 0x36, 0x37, 0x39
              .byte 0x31, 0x39, 0x37, 0x37, 0xff, 0x31, 0xff, 0xff, 0xff, 0xff, 0xff, 0x39, 0x3a, 0x38, 0x38, 0xff
pumpMasks:
              .byte 0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x08, 0x08, 0x08, 0x08, 0x00, 0x08, 0x02, 0x02, 0x02, 0x02
              .byte 0x02, 0x02, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x10, 0x01, 0x01, 0x10, 0x01, 0x10, 0x20, 0x02
              .byte 0x02, 0x20, 0x02, 0x20, 0x40, 0x04, 0x04, 0x40, 0x04, 0x04, 0x10, 0x08, 0x08, 0x08, 0x08, 0x08
              .byte 0x02, 0x40, 0x20, 0x80, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0x80, 0x80, 0x40, 0x00



bufferRestore: .byte 0
bufferKeyboard:
              lda     #0x0a
              jsr     abs:.word0 sendBounded
              bcs     bufferDone
              jsr     abs:.word0 readBounded
              bcs     bufferDone
              and     #0x10
              bne     bufferDone
              lda     #0x10
              sta     long:bufferRestore
              lda     #0x04
              jsr     abs:.word0 sendBounded
              bcs     bufferDone
              lda     #0x10
              jsr     abs:.word0 sendBounded
bufferDone:   jsr     abs:.word0 stopFirmwareRepeat
              ldx     ##0                   ; First scanner-signature byte.
              rts


repeatRestore: .byte 0
keyboardConfig: .space 3,0
stopFirmwareRepeat:
              lda     #0x0b
              jsr     abs:.word0 sendBounded
              bcs     repeatSetupDone
              ldx     ##0
readKeyboardConfig:
              jsr     abs:.word0 readBounded
              bcs     repeatSetupDone
              sta     long:keyboardConfig,x
              inx
              cpx     ##3
              bcc     readKeyboardConfig
              lda     long:(keyboardConfig+2)
              and     #0x70
              cmp     #0x40
              beq     repeatSetupDone
              lda     #1
              sta     long:repeatRestore
              jsr     abs:.word0 sendKeyboardConfig
              bcs     repeatSetupDone
              lda     long:(keyboardConfig+2)
              and     #0x8f
              ora     #0x40
              jsr     abs:.word0 sendBounded
repeatSetupDone:
              rts

;;; Send the command and unchanged first two bytes. The caller supplies the
;;; final repeat byte. Carry reports a bounded controller timeout.
sendKeyboardConfig:
              lda     #0x06
              jsr     abs:.word0 sendBounded
              bcs     configDone
              lda     long:keyboardConfig
              jsr     abs:.word0 sendBounded
              bcs     configDone
              lda     long:(keyboardConfig+1)
              jsr     abs:.word0 sendBounded
configDone:   rts

restoreFirmwareRepeat:
              lda     long:repeatRestore
              beq     repeatRestored
              jsr     abs:.word0 sendKeyboardConfig
              bcs     repeatRestored
              lda     long:(keyboardConfig+2)
              jsr     abs:.word0 sendBounded
              bcs     repeatRestored
              lda     #0
              sta     long:repeatRestore
repeatRestored:
              rts


;;; ADB address 2 presence is separate from J13 availability. A missing raw
;;; keyboard must not create repeated empty Talks on a mouse-only ADB bus.
probeADB:     lda #0xf2
              jsr abs:.word0 (sendBounded)
              bcs noADBKeyboard
              ldx ##16
probeHeader:  jsr abs:.word0 (readBounded)
              bcs noADBKeyboard
              bit #128
              bne probeReply
              dex
              bne probeHeader
              bra noADBKeyboard
probeReply:   and #7
              beq noADBKeyboard
              rep #0x20
              and ##255
              inc a
              tax
              sep #0x20
probeBytes:   jsr abs:.word0 (readBounded)
              bcs noADBKeyboard
              dex
              bne probeBytes
              rts
noADBKeyboard:
              lda #0
              sta abs:.word0 (j13AdbPresent)
              lda #0x4c
              sta long:captureTalk
              rep #0x20
              lda ##.word0 (withoutRawKeys)
              sta long:captureTalk+1
              sep #0x20
              rts

;;; A=raw transition, X=ring offset. Menu repeats use the merged ownership
;;; too: one keyboard's release cannot stop an arrow held on the other.
              .public J13MenuKey
J13MenuKey:   phb
              phx
              phy
              phk
              plb
              sta abs:.word0 (menuRaw)
              lda long:inputRing+2,x
              lsr a
              inc a
              sta abs:.word0 (menuSource)
              lda abs:.word0 (menuRaw)
              and ##127
              tax
              lda long:keyHeld,x
              and ##255
              sta abs:.word0 (menuWas)
              lda abs:.word0 (menuRaw)
              bit ##128
              bne menuKeyUp
              lda abs:.word0 (menuWas)
              ora abs:.word0 (menuSource)
              sep #0x20
              sta long:keyHeld,x
              rep #0x20
              lda abs:.word0 (menuWas)
              bne menuKeyIgnored
              bra menuKeyReturn
menuKeyUp:    lda abs:.word0 (menuSource)
              eor ##255
              and abs:.word0 (menuWas)
              sep #0x20
              sta long:keyHeld,x
              rep #0x20
              and ##255
              bne menuKeyIgnored
menuKeyReturn:lda abs:.word0 (menuRaw)
              bra menuKeyDone
menuKeyIgnored:
              lda ##0xffff
menuKeyDone:  ply
              plx
              plb
              rtl
menuRaw:      .word 0
menuWas:      .word 0
menuSource:   .word 0
