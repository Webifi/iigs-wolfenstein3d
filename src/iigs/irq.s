;;; Save the renderer's full registers and DBR; direct page is untouched.
#include "memmap.inc"
              .section irqcode, text, root, noreorder
              .public inputIrq, inputIrqEnd, DrainDocInterrupts, gsFast, gsSkip
              .public fastAlarmHandled, noDocAlarm
              .extern CaptureInput, FlashTick, MusicWake, EffectBufferEnd
              .extern J13SendIRQ, J13SendWake
              .extern damageCount, bonusCount, musicActive, effectsActive
              .extern blkCmd, blkBuf, blkNum, blkDriver, UiFwPut, UiFwKeep
inputIrq:     rep #0x30
              pha
              phx
              phy
              phb
              cld
;;; A stopped owner's last hardware alarm may still be pending.
              jmp abs:.word0 (docInterrupt)
inputOnly:    sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              jsl long:CaptureInput
noDocAlarm:   plb
              ply
              plx
              pla
inputIrqEnd:  rti

;;; IRQ-only entry returns directly to the saved-register frame.
;;; Foreground draining below keeps its ordinary subroutine return.
docInterrupt:
              sep #0x20
fastIrqReady:     lda long:SOUNDCTL
              bmi fastIrqReady
              lda #0xe0
              sta long:SOUNDADRL
              lda long:SOUNDDATA
fastIrqLatch:     lda long:SOUNDCTL
              bmi fastIrqLatch
              lda long:SOUNDDATA
              bmi fastAlarmsDone
              and #0x3e
              cmp #0x3a
              beq fastMusicAlarm
              cmp #0x38
              beq fastParameterAlarm
              cmp #8
              bcc fastEffectBufferAlarm
              cmp #0x3c
              bne fastAlarmHandled
              rep #0x20
              lda long:damageCount
              ora long:bonusCount
              beq fastAlarmHandled
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              jsl long:FlashTick
              bra fastAlarmHandled
fastParameterAlarm:
              jmp long:J13SendIRQ
fastEffectBufferAlarm:
              lsr a
              jsl long:EffectBufferEnd
              bra fastAlarmHandled
fastMusicAlarm:   jsl long:MusicWake
fastAlarmHandled: rep #0x20
              jmp abs:.word0 (noDocAlarm)
fastAlarmsDone:   jmp abs:.word0 (inputOnly)


;;; Mainline stop/reset must drain a pending alarm without stealing the
;;; other owner's alarm. Call after clearing only the stopped owner's flag.
DrainDocInterrupts:
              php
              sei
              rep #0x30
              pha
              phx
              phy
              phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              jsr abs:.word0 (servicePending)
              plb
              ply
              plx
              pla
              plp
              rtl

servicePending:
              jsr abs:.word0 (serviceOne)
              bcs servicePending
              rts
;;; Every GLU owner restores incrementing register mode before allowing interrupts. The
;;; latch's second read fetches $E1, acknowledging only one pending source.
serviceOne:
              sep #0x20
irqReady:     lda long:SOUNDCTL
              bmi irqReady
              lda #0xe0
              sta long:SOUNDADRL
              lda long:SOUNDDATA
irqLatch:     lda long:SOUNDCTL
              bmi irqLatch
              lda long:SOUNDDATA
              bmi alarmsDone
              and #0x3e
              cmp #0x3a
              beq musicAlarm
              cmp #0x38
              beq parameterAlarm
              cmp #8
              bcc effectBufferAlarm
              cmp #0x3c
              bne alarmHandled
              rep #0x20
              lda long:damageCount
              ora long:bonusCount
              beq alarmHandled
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              jsl long:FlashTick
              bra alarmHandled
parameterAlarm:
              jsl long:J13SendWake
              bra alarmHandled
effectBufferAlarm:
              lsr a
              jsl long:EffectBufferEnd
              bra alarmHandled
musicAlarm:   lda long:musicActive
              beq alarmHandled
              jsl long:MusicWake
alarmHandled: rep #0x20
              sec
              rts
alarmsDone:   rep #0x20
              clc
              rts

;;; One block. The slot driver returns with an emulation RTS, so this has to
;;; live in bank 0 with the rest of the firmware calls. Bit 0 of gsSkip skips
;;; the firmware check; bit 1 skips the copy back. JSL. A is the error byte,
;;; carry set on an error.
gsFast:       php
              sei
              rep #0x30
              phb
              phd
              lda long:gsSkip
              and ##1
              bne gsNoPut
              jsl long:UiFwPut
gsNoPut:      lda ##0
              tcd
              sep #0x20
              lda #0
              pha
              plb
              lda long:SHADOW
              sta abs:.word0 (gsSh)
              and #0xbf
              sta long:SHADOW
              rep #0x20
              lda dp:PD_CMD
              sta abs:.word0 (gsS42)
              lda dp:PD_BUF
              sta abs:.word0 (gsS44)
              lda dp:PD_BLOCK
              sta abs:.word0 (gsS46)
              lda abs:.word0 (blkCmd)
              sta dp:PD_CMD
              lda abs:.word0 (blkBuf)
              sta dp:PD_BUF
              lda abs:.word0 (blkNum)
              sta dp:PD_BLOCK
              tsx
              stx abs:.word0 (gsNstk)
              sep #0x30
              sec
              xce
              jsr abs:.word0 (gsDrv)
              sta abs:.word0 (gsE)
              lda #0
              rol a
              sta abs:.word0 (gsC)
              clc
              xce
              rep #0x30
              ldx abs:.word0 (gsNstk)
              txs
              lda abs:.word0 (gsS42)
              sta dp:PD_CMD
              lda abs:.word0 (gsS44)
              sta dp:PD_BUF
              lda abs:.word0 (gsS46)
              sta dp:PD_BLOCK
              sep #0x20
              lda abs:.word0 (gsSh)
              sta long:SHADOW
              rep #0x30
              lda abs:.word0 (gsSkip)
              and ##2
              bne gsNoKeep
              jsl long:UiFwKeep
gsNoKeep:     pld
              plb
              plp
              lda long:gsC
              lsr a
              lda long:gsE
              and ##255
              rtl
gsDrv:        jmp (abs:.word0 (blkDriver))

gsSkip:       .word 0
gsS42:        .word 0
gsS44:        .word 0
gsS46:        .word 0
gsNstk:       .word 0
gsE:          .byte 0
gsC:          .word 0
gsSh:         .byte 0
