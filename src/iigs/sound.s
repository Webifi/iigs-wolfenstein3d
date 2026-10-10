#include "memmap.inc"
#include "sound_ids.inc"
#include "game.inc"
              .rtmodel version, "1"
              .rtmodel core, "*"
              .section soundcode, text, root, noreorder
              .public InitSound, PlaySound, PlaySoundEvent, StopEffects, SetSoundVolume
              .public EffectBufferEnd, EffectRefill, effectsActive
              .public PollEffects
              .extern sfxEvent, LoadAudioSettings, DrainDocInterrupts, copyPointer, levelIndex
              .extern primePointer, uploadSound, claimOwners

CTL .equ SOUNDCTL
DATA .equ SOUNDDATA
ADR .equ SOUNDADRL
ADRH .equ SOUNDADRH
FX .equ SFX_BASE
;;; 87 descriptors, then one 64-byte plan record per floor. tools/effect_size.py.
PLAN .equ SFX_PLAN

;;; The legacy effect interrupt callbacks remain no-ops for linked callers.
;;; One-shots halt on a 0 byte and need no refill/buffer interrupts. Oscillator
;;; 28 belongs to the input controller and is not stopped with effects.
EffectBufferEnd: rtl
EffectRefill: rtl

InitSound:    php
              sei
              rep #0x30
              pha
              phx
              phy
              phb
              sep #0x20
              lda #0x3d
              pha
              plb
              rep #0x20
              lda ##65535
              ldx ##0
initAt:       sta abs:.word0 (soundAt),x
              inx
              inx
              cpx ##174
              bcc initAt
              ldx ##0
initOwner:    sta abs:.word0 (pageOwner),x
              inx
              inx
              cpx ##128
              bcc initOwner
              sta abs:.word0 (chId)
              sta abs:.word0 (chId+2)
              ldx ##0
initAge:      stz abs:.word0 (soundAge),x
              inx
              inx
              cpx ##174
              bcc initAge
              sep #0x20
              ldx ##0
initPin:      stz abs:.word0 (pinMask),x
              inx
              cpx ##64
              bcc initPin
              rep #0x20
              stz abs:.word0 (chPri)
              stz abs:.word0 (chPri+2)
              stz abs:.word0 (chRun)
              stz abs:.word0 (chRun+2)
              stz abs:.word0 (fxActive)
              stz abs:.word0 (fxActive+2)
              stz abs:.word0 (fxPending)
              stz abs:.word0 (fxPending+2)
              stz abs:.word0 (effectsActive)
              stz abs:.word0 (effectId)
              ldy ##0
              jsr abs:.word0 (haltChannel)
              ldy ##2
              jsr abs:.word0 (haltChannel)
              jsl long:LoadAudioSettings
              plb
              ply
              plx
              pla
              plp
              rtl

;;; Preserve the event hook's registers and flags, including inside a pickup
;;; projection. No polling or sound call is added to the frame loop.
PlaySoundEvent:
              php
              rep #0x30
              pha
              phx
              phy
              phb
              sta long:sfxEvent
              tax
              lda long:soundVolume
              bne eventAudible
              jmp abs:.word0 (effectReturn)
eventAudible: txa
              cmp ##15
              bcc validEvent
              jmp abs:.word0 (effectReturn)
validEvent:
              asl a
              tax
              lda long:legacySound,x
              bra effectEnter
PlaySound:    php
              rep #0x30
              pha
              phx
              phy
              phb
effectEnter:  tax
              sep #0x20
              lda #0x3d
              pha
              plb
              rep #0x20
              txa
              jsr abs:.word0 (playEffect)
effectReturn: plb
              ply
              plx
              pla
              plp
              rtl

;;; Effects use oscillators 0 and 2. Muted, invalid or empty effects are dropped;
;;; playback also requires a selected channel and a resident or loadable sample.
playEffect:   ldx abs:.word0 (soundVolume)
              beq effectDrop
              cmp ##87
              bcs effectDrop
              sta abs:.word0 (effectId)
              asl a
              asl a
              asl a
              asl a
              tax
              stx abs:.word0 (effectDesc)
              lda long:FX+2,x
              beq effectDrop
              lda long:FX+4,x
              beq effectDrop
              php
              sei
              jsr abs:.word0 (pollChannels)
              jsr abs:.word0 (pickChannel)
              plp
              cpy ##4
              bcs effectDrop
              jsr abs:.word0 (ensureSound)
              bcs effectDrop
              php
              sei
              jsr abs:.word0 (startOsc)
              plp
effectDrop:   rts

;;; Prefer the channel already holding this effect ID, then an idle channel.
;;; Otherwise replace the lower-priority effect if the new priority is at least
;;; as high. Return Y = 0 or 2 for the selected channel, or 4 to drop the effect.
pickChannel:  ldy ##0
sameLoop:     lda abs:.word0 (chId),y
              cmp abs:.word0 (effectId)
              beq pickHave
              iny
              iny
              cpy ##4
              bcc sameLoop
              ldy ##0
freeLoop:     lda abs:.word0 (chRun),y
              beq pickHave
              iny
              iny
              cpy ##4
              bcc freeLoop
              lda abs:.word0 (chPri)
              cmp abs:.word0 (chPri+2)
              bcc lowerIs0
              ldy ##2
              bra lowerHave
lowerIs0:     ldy ##0
lowerHave:    ldx abs:.word0 (effectDesc)
              lda long:FX+8,x
              cmp abs:.word0 (chPri),y
              bcs pickHave
              ldy ##4
pickHave:     rts

ensureSound:  phy
              lda abs:.word0 (effectId)
              asl a
              tax
              lda abs:.word0 (soundAt),x
              cmp ##65535
              bne ensureHeld
              jsr abs:.word0 (placeSound)
              bcs ensureMiss
ensureHeld:   ply
              clc
              rts
ensureMiss:   ply
              sec
              rts

;;; The aligned pool slot whose newest sound is the oldest. A free slot wins
;;; at once. Pinned pages and a sound that is playing now are left alone.
placeSound:   ldx abs:.word0 (effectDesc)
              sep #0x20
              lda long:FX+11,x
              sta abs:.word0 (slotPages)
              rep #0x20
              lda abs:.word0 (slotPages)
              and ##255
              sta abs:.word0 (slotPages)
              beq placeFail
              stz abs:.word0 (slotStart)
              lda ##65535
              sta abs:.word0 (slotBestAge)
              stz abs:.word0 (slotFound)
placeLoop:    lda abs:.word0 (slotStart)
              clc
              adc abs:.word0 (slotPages)
              cmp ##65
              bcs placeChoose
              jsr abs:.word0 (scanSlot)
              bcs placeNext
              lda abs:.word0 (slotFree)
              bne placeTake
              lda abs:.word0 (slotMaxAge)
              cmp abs:.word0 (slotBestAge)
              bcs placeNext
              sta abs:.word0 (slotBestAge)
              lda abs:.word0 (slotStart)
              sta abs:.word0 (slotBest)
              inc abs:.word0 (slotFound)
placeNext:    lda abs:.word0 (slotStart)
              clc
              adc abs:.word0 (slotPages)
              sta abs:.word0 (slotStart)
              jmp abs:.word0 (placeLoop)
placeTake:    lda abs:.word0 (slotStart)
              sta abs:.word0 (slotBest)
              bra placeUse
placeChoose:  lda abs:.word0 (slotFound)
              beq placeFail
placeUse:     lda abs:.word0 (effectId)
              sta abs:.word0 (pinId)
              lda abs:.word0 (slotBest)
              sta abs:.word0 (pinPage)
              lda abs:.word0 (slotPages)
              sta abs:.word0 (pinPages)
              lda abs:.word0 (pinPage)
              sta abs:.word0 (docPage)
              jsl long:primePointer
              jsl long:uploadSound
              jsl long:claimOwners
              clc
              rts
placeFail:    sec
              rts

scanSlot:     lda ##1
              sta abs:.word0 (slotFree)
              stz abs:.word0 (slotMaxAge)
              lda abs:.word0 (slotStart)
              sta abs:.word0 (scanPage)
scanNext:     lda abs:.word0 (scanPage)
              sec
              sbc abs:.word0 (slotStart)
              cmp abs:.word0 (slotPages)
              bcs scanOk
;;; The subtract leaves the offset. pageBlocked needs the page.
              lda abs:.word0 (scanPage)
              jsr abs:.word0 (pageBlocked)
              bcs scanBad
              inc abs:.word0 (scanPage)
              jmp abs:.word0 (scanNext)
scanBad:      sec
              rts
scanOk:       clc
              rts

;;; Carry set: this page is pinned, or its sound is playing.
pageBlocked:  tax
              sep #0x20
              lda abs:.word0 (pinMask),x
              rep #0x20
              bne pageBad
              txa
              asl a
              tax
              lda abs:.word0 (pageOwner),x
              cmp ##65535
              beq pageOpen
              stz abs:.word0 (slotFree)
              sta abs:.word0 (oldId)
              cmp abs:.word0 (chId)
              bne pageNot0
              lda abs:.word0 (chRun)
              bne pageBad
pageNot0:     lda abs:.word0 (oldId)
              cmp abs:.word0 (chId+2)
              bne pageAge
              lda abs:.word0 (chRun+2)
              bne pageBad
pageAge:      lda abs:.word0 (oldId)
              asl a
              tax
              lda abs:.word0 (soundAge),x
              cmp abs:.word0 (slotMaxAge)
              bcc pageOpen
              sta abs:.word0 (slotMaxAge)
pageOpen:     clc
              rts
pageBad:      sec
              rts

;;; Y is the channel, and the oscillator. Its partner Y+1 plays the same table at
;;; the same frequency on DOC channel 1, so a stereo card gets the effect centred
;;; and a mono output adds both oscillators (+6 dB). Both are programmed halted and
;;; started by the last two writes, back to back, so they begin in the same scan.
;;; The table is stored at full 8-bit scale: its descriptor's level byte (FX+12) is
;;; the volume register at effects volume 15, see effectRegister.
startOsc:     lda abs:.word0 (effectId)
              sta abs:.word0 (chId),y
              ldx abs:.word0 (effectDesc)
              lda long:FX+8,x
              sta abs:.word0 (chPri),y
              lda ##1
              sta abs:.word0 (chRun),y
              sta abs:.word0 (fxActive),y
              jsr abs:.word0 (updateEffectsActive)
              lda abs:.word0 (effectId)
              asl a
              tax
              inc abs:.word0 (soundAge),x
              jsr abs:.word0 (haltChannel)
              rep #0x20
              ldx abs:.word0 (effectDesc)
              lda long:FX+6,x
              sta abs:.word0 (freqTemp)
              sep #0x20
              lda long:FX+10,x
              sta abs:.word0 (oldId)
              rep #0x20
              lda long:FX+12,x
              and ##255
              jsr abs:.word0 (effectRegister)
              sta abs:.word0 (regTemp)
              lda abs:.word0 (effectId)
              asl a
              tax
              lda abs:.word0 (soundAt),x
              sta abs:.word0 (docPage)
              sep #0x20
              tya
              tax
              lda abs:.word0 (freqTemp)
              jsr abs:.word0 (setRegister)
              inx
              lda abs:.word0 (freqTemp)
              jsr abs:.word0 (setRegister)
              tya
              ora #0x20
              tax
              lda abs:.word0 (freqTemp+1)
              jsr abs:.word0 (setRegister)
              inx
              lda abs:.word0 (freqTemp+1)
              jsr abs:.word0 (setRegister)
              tya
              ora #0x40
              tax
              lda abs:.word0 (regTemp)
              jsr abs:.word0 (setRegister)
              inx
              lda abs:.word0 (regTemp)
              jsr abs:.word0 (setRegister)
              tya
              ora #0x80
              tax
              lda abs:.word0 (docPage)
              jsr abs:.word0 (setRegister)
              inx
              lda abs:.word0 (docPage)
              jsr abs:.word0 (setRegister)
              tya
              ora #0xc0
              tax
              lda abs:.word0 (oldId)
              jsr abs:.word0 (setRegister)
              inx
              lda abs:.word0 (oldId)
              jsr abs:.word0 (setRegister)
              tya
              ora #0xa0
              tax
              lda #2
              jsr abs:.word0 (setRegister)
              inx
              lda #0x12
              jsr abs:.word0 (setRegister)
              rep #0x20
              rts

;;; A = an effect's level byte (0-255, 16-bit A). Returns A = level x (17 v + 1) / 256
;;; for the effects volume v (0-15): v 15 gives the level itself, v 0 gives 0. X is
;;; clobbered. Shift-and-add; no hardware multiply.
effectRegister:
              xba
              sta abs:.word0 (mulLevel)
              lda abs:.word0 (soundVolume)
              and ##15
              beq mulZero
              sta abs:.word0 (mulFactor)
              asl a
              asl a
              asl a
              asl a
              clc
              adc abs:.word0 (mulFactor)
              inc a
              sta abs:.word0 (mulFactor)
              ldx ##8
              lda ##0
mulLoop:      asl a
              asl abs:.word0 (mulLevel)
              bcc mulSkip
              clc
              adc abs:.word0 (mulFactor)
mulSkip:      dex
              bne mulLoop
              xba
              and ##255
              rts
mulZero:      lda ##0
              rts

;;; CacheFloorEffects and the page upload live in sound_cache.s.
;;; The sound bank holds the player. Callers keep DBR at $3d.

PollEffects:  php
              sei
              rep #0x30
              pha
              phx
              phy
              phb
              sep #0x20
              lda #0x3d
              pha
              plb
              rep #0x20
              jsr abs:.word0 (pollChannels)
              plb
              ply
              plx
              pla
              plp
              rtl

;;; Halt bit set: that one-shot has reached its 0 and the channel is free.
pollChannels: sep #0x20
              ldx ##0xa0
              jsr abs:.word0 (readRegister)
              and #1
              bne ch0free
              rep #0x20
              lda ##1
              sta abs:.word0 (chRun)
              sta abs:.word0 (fxActive)
              bra ch0done
ch0free:      rep #0x20
              lda ##65535
              sta abs:.word0 (chId)
              stz abs:.word0 (chRun)
              stz abs:.word0 (fxActive)
ch0done:      sep #0x20
              ldx ##0xa2
              jsr abs:.word0 (readRegister)
              and #1
              bne ch1free
              rep #0x20
              lda ##1
              sta abs:.word0 (chRun+2)
              sta abs:.word0 (fxActive+2)
              bra ch1done
ch1free:      rep #0x20
              lda ##65535
              sta abs:.word0 (chId+2)
              stz abs:.word0 (chRun+2)
              stz abs:.word0 (fxActive+2)
ch1done:      jsr abs:.word0 (updateEffectsActive)
              rts

haltChannel:  sep #0x20
              tya
              ora #0xa0
              tax
              lda #3
              jsr abs:.word0 (setRegister)
              inx
              lda #3
              jsr abs:.word0 (setRegister)
              rep #0x20
              rts

updateEffectsActive:
              lda abs:.word0 (fxActive)
              ora abs:.word0 (fxActive+2)
              sta abs:.word0 (effectsActive)
              rts

;;; A and X are bytes; callers exclude interrupts for every GLU sequence.
setRegister:  pha
waitSet:      lda long:CTL
              bmi waitSet
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x20
              sta long:CTL
              txa
              sta long:ADR
              pla
waitWrite:    pha
pollWrite:    lda long:CTL
              bmi pollWrite
              pla
              sta long:DATA
              rts
readRegister: lda long:CTL
              bmi readRegister
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x20
              sta long:CTL
              txa
              sta long:ADR
readFirst:    lda long:CTL
              bmi readFirst
              lda long:DATA
readSecond:   lda long:CTL
              bmi readSecond
              lda long:DATA
              rts

StopEffects:  php
              sei
              rep #0x30
              pha
              phx
              phy
              lda ##65535
              sta long:chId
              sta long:chId+2
              lda ##0
              sta long:chRun
              sta long:chRun+2
              sta long:chPri
              sta long:chPri+2
              sta long:fxActive
              sta long:fxActive+2
              sta long:fxPending
              sta long:fxPending+2
              sta long:effectsActive
              ldy ##0
              jsr abs:.word0 (haltChannel)
              ldy ##2
              jsr abs:.word0 (haltChannel)
              jsl long:DrainDocInterrupts
              rep #0x20
              ply
              plx
              pla
              plp
              rtl

SetSoundVolume:
              php
              sei
              rep #0x30
              pha
              phx
              and ##15
              cmp long:soundVolume
              beq soundVolumeDone
              sta long:soundVolume
              cmp ##0
              bne soundVolumeOn
              jsl long:StopEffects
              bra soundVolumeDone
soundVolumeOn:
              phy
              phb
              sep #0x20
              lda #0x3d
              pha
              plb
              rep #0x20
              ldy ##0
volumeChannel:
              lda abs:.word0 (chRun),y
              beq volumeNext
              lda abs:.word0 (chId),y
              asl a
              asl a
              asl a
              asl a
              tax
              lda long:FX+12,x
              and ##255
              jsr abs:.word0 (effectRegister)
              sta abs:.word0 (regTemp)
              sep #0x20
              tya
              ora #0x40
              tax
              lda abs:.word0 (regTemp)
              jsr abs:.word0 (setRegister)
              inx
              lda abs:.word0 (regTemp)
              jsr abs:.word0 (setRegister)
              rep #0x20
volumeNext:   iny
              iny
              cpy ##4
              bcc volumeChannel
              plb
              ply
soundVolumeDone:
              rep #0x30
              plx
              pla
              plp
              rtl

;;; Tally calls ids 11-14. Ids 0-14 index this table. The actor pool is not read.
legacySound:  .word ATKKNIFESND,ATKPISTOLSND,ATKMACHINEGUNSND,ATKGATLINGSND
              .word DEATHSCREAM1SND,GETAMMOSND,HALTSND,NAZIFIRESND,NOWAYSND,PUSHWALLSND
              .word LEVELDONESND,ENDBONUS1SND,ENDBONUS2SND,NOBONUSSND,PERCENT100SND

              .section sounddata, data, root
              .public soundVolume, musicVolume, musicActive, musicLoaded
              .public pinMask, poolLo, planIndex, planCount, pinId, pinPage, pinPages
              .public docPage, copyLength, copyCount, effectDesc, soundAt, pageOwner
soundVolume:  .word 15
musicVolume:  .word 15
musicActive:  .word 0
musicLoaded:  .word 0
effectId:     .word 0
effectDesc:   .word 0
fxPending:    .word 0,0
fxActive:     .word 0,0
effectsActive:.word 0
chId:         .word 65535,65535
chPri:        .word 0,0
chRun:        .word 0,0
poolLo:       .word 0
planIndex:    .word 0
planCount:    .word 0
pinId:        .word 0
pinPage:      .word 0
pinPages:     .word 0
docPage:      .word 0
copyLength:   .word 0
copyCount:    .word 0
freqTemp:     .word 0
regTemp:      .word 0
mulLevel:     .word 0
mulFactor:    .word 0
slotStart:    .word 0
slotBest:     .word 0
slotBestAge:  .word 0
slotFound:    .word 0
slotFree:     .word 0
slotMaxAge:   .word 0
slotPages:    .word 0
scanPage:     .word 0
oldId:        .word 0
soundAt:      .space 174
pageOwner:    .space 128
soundAge:     .space 174
pinMask:      .space 64
