;;; DOC alarms run only while a flash is alive. A hit need not wait for the
;;; renderer; palette stores occur in the IRQ and only when its tint changes.
              .section irqcode, text, root, noreorder
              .public InitFlash, FlashQuiet, StartDamageFlash, StartBonusFlash, FlashTick, RefreshFlash
              .extern I_GetTime, IIGS_Alarm, IIGS_AlarmOff, DrainDocInterrupts, rowShading
              .public tintFloorOffsets
              .extern levelIndex, palHold

InitFlash:    php
              sei
              jsl long:IIGS_AlarmOff
              stz abs:.word0 (damageCount)
              stz abs:.word0 (bonusCount)
              jsl long:DrainDocInterrupts
              lda ##0
              sta abs:.word0 (flashTint)
              jsl long:I_GetTime
              sta abs:.word0 (flashTime)
              jsr abs:.word0 (flashWrite)
              plp
              rtl

;;; The menu is about to copy the colors on the screen. Stop a tint from
;;; writing over them, and do not write a palette of its own. The counts
;;; live in bank 2; the caller still has DBR = $3F.
FlashQuiet:   php
              sei
              phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x30
              jsl long:IIGS_AlarmOff
              stz abs:.word0 (damageCount)
              stz abs:.word0 (bonusCount)
              jsl long:DrainDocInterrupts
              lda ##0
              sta abs:.word0 (flashTint)
              plb
              plp
              rtl

RefreshFlash: php
              sei
              lda abs:.word0 (damageCount)
              ora abs:.word0 (bonusCount)
              beq refreshDone
              lda ##65535
              sta abs:.word0 (flashTint)
              jsl long:FlashTick           ; palette changes only on a UI event
refreshDone:  plp
              rtl

StartDamageFlash:
              php
              sei
              pha
              jsr abs:.word0 (flashSync)
              pla
              clc
              adc abs:.word0 (damageCount)
              cmp ##256
              bcc flashDamageReady
              lda ##255
flashDamageReady:
              sta abs:.word0 (damageCount)
              jsl long:IIGS_Alarm
              plp
              rtl

StartBonusFlash:
              php
              sei
              jsr abs:.word0 (flashSync)
              lda ##18                    ; NUMWHITESHIFTS * WHITETICS
              sta abs:.word0 (bonusCount)
              jsl long:IIGS_Alarm
              plp
              rtl

flashSync:    jsl long:I_GetTime
              pha
              sec
              sbc abs:.word0 (flashTime)
              sta abs:.word0 (flashElapsed)
              pla
              sta abs:.word0 (flashTime)
              lda abs:.word0 (damageCount)
              sec
              sbc abs:.word0 (flashElapsed)
              bcs flashDamageLeft
              lda ##0
flashDamageLeft:
              sta abs:.word0 (damageCount)
              lda abs:.word0 (bonusCount)
              sec
              sbc abs:.word0 (flashElapsed)
              bcs flashBonusLeft
              lda ##0
flashBonusLeft:
              sta abs:.word0 (bonusCount)
              rts

FlashTick:    jsr abs:.word0 (flashSync)
              ldx abs:.word0 (damageCount)
              beq flashWhite
              lda abs:.word0 (damageTint),x
              bra flashDecided
flashWhite:   ldx abs:.word0 (bonusCount)
              lda abs:.word0 (bonusTint),x
flashDecided: and ##255
              cmp abs:.word0 (flashTint)
              beq flashNext
              sta abs:.word0 (flashTint)
              jsr abs:.word0 (flashWrite)
flashNext:    lda abs:.word0 (damageCount)
              ora abs:.word0 (bonusCount)
              beq flashDone
              jsl long:IIGS_Alarm
flashDone:    rtl

flashWrite:   lda abs:.word0 (flashTint)
              asl a
              tax
              lda abs:.word0 (tintStatusSource),x
              sta abs:.word0 (flashStatus)
              lda abs:.word0 (flashTint)
              asl a
              asl a
              asl a
              asl a
              asl a
              sta abs:.word0 (flashSource)
              lda abs:.word0 (levelIndex)
              asl a
              tax
              lda abs:.word0 (tintFloorOffsets),x
              clc
              adc abs:.word0 (flashSource)
              adc ##0x9000
              tax
              lda abs:.word0 (palHold)
              bne flashBuf
              ldy ##0x9e00
              phb
              lda ##31                    ; palette 0, then the 12 status palettes: palette RAM is always slow
              .byte 0x54,0xe1,0x00         ; MVN
              plb
              ldx abs:.word0 (flashStatus)
              ldy ##0x9e20
              phb
              lda ##383
              .byte 0x54,0xe1,0x00
              plb
              rts
flashBuf:     ldy ##0xb000                ; the hidden picture keeps the tint
              phb
              lda ##31
              .byte 0x54,0xe0,0x00
              plb
              ldx abs:.word0 (flashStatus)
              ldy ##0xb020
              phb
              lda ##383
              .byte 0x54,0xe0,0x00
              plb
              rts

              .section gamedata, data, root
              .public damageCount, bonusCount, flashTint, flashSource, flashStatus
damageCount:  .word 0
bonusCount:   .word 0
flashTint:    .word 65535
flashTime:    .word 0
flashElapsed: .word 0
flashSource:  .word 0
flashStatus:  .word 0
#include "tints.inc"
