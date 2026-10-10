#include "memmap.inc"
#include "progress.inc"
#include "sound_ids.inc"
;;; Floor-load cache and the DOC page upload. A separate object, so the
;;; sound bank can hold the player. Callers enter with DBR $3d.
              .rtmodel version, "1"
              .rtmodel core, "*"
              .section gamecode, text, root, noreorder
              .public CacheFloorEffects, primePointer, uploadSound, claimOwners
              .extern copyPointer, levelIndex
              .extern pinMask, poolLo, planIndex, planCount, pinId, pinPage, pinPages
              .extern docPage, copyLength, copyCount, effectDesc, soundAt, pageOwner

CTL .equ SOUNDCTL
DATA .equ SOUNDDATA
ADR .equ SOUNDADRL
ADRH .equ SOUNDADRH
FX .equ SFX_BASE
PLAN .equ SFX_PLAN

;;; The floor load calls this under the LOADING sign, before the song starts.
CacheFloorEffects:
              php
              rep #0x30
              phx
              phy
              phb
              sep #0x20
              lda #0x3d
              pha
              plb
              rep #0x20
              lda long:levelIndex
              cmp ##SFX_FLOORS
              bcs cacheOut
              sep #0x20
              ldx ##0
clearMask:    stz abs:.word0 (pinMask),x
              inx
              cpx ##64
              bcc clearMask
              rep #0x20
              jsr abs:.word0 (loadPlan)
cacheOut:     plb
              ply
              plx
              plp
              rtl

loadPlan:
              lda ##0                     ; this floor carries one plan at the fixed ABI offset
              sta abs:.word0 (planIndex)
              tax
              sep #0x20
              lda long:PLAN,x
              sta abs:.word0 (poolLo)
              inx
              lda long:PLAN,x
              sta abs:.word0 (planCount)
              rep #0x20
              lda abs:.word0 (planCount)
              and ##255
              sta abs:.word0 (planCount)
              ldy ##0
pinLoop:      cpy abs:.word0 (planCount)
              bcs pinDone
              tya
              asl a
              clc
              adc abs:.word0 (planIndex)
              tax
              sep #0x20
              lda long:PLAN+2,x
              sta abs:.word0 (pinId)
              lda long:PLAN+3,x
              sta abs:.word0 (pinPage)
              rep #0x20
              lda abs:.word0 (pinId)
              and ##255
              sta abs:.word0 (pinId)
              lda abs:.word0 (pinPage)
              and ##255
              sta abs:.word0 (pinPage)
              jsr abs:.word0 (pinOne)
              jsl long:Progress2
              iny
              jmp abs:.word0 (pinLoop)
pinDone:      rts

pinOne:       lda abs:.word0 (pinId)
              asl a
              asl a
              asl a
              asl a
              tax
              stx abs:.word0 (effectDesc)
              sep #0x20
              lda long:FX+11,x
              sta abs:.word0 (pinPages)
              rep #0x20
              lda abs:.word0 (pinPages)
              and ##255
              sta abs:.word0 (pinPages)
              beq pinSkip
              lda abs:.word0 (pinId)
              asl a
              tax
              lda abs:.word0 (pinPage)
              cmp abs:.word0 (soundAt),x
              beq pinClaim
              sta abs:.word0 (docPage)
              jsl long:primePointer
              jsl long:uploadSound
pinClaim:     jsl long:claimOwners
              jsr abs:.word0 (markPins)
pinSkip:      rts

markPins:     ldx abs:.word0 (pinPage)
markLoop:     sep #0x20
              lda #1
              sta abs:.word0 (pinMask),x
              rep #0x20
              inx
              txa
              sec
              sbc abs:.word0 (pinPage)
              cmp abs:.word0 (pinPages)
              bcc markLoop
              rts

;;; Forget this id, then own pinPage for pinPages. A displaced id leaves DOC.
;;; Y is the floor plan's pair index, so it has to survive.
claimOwners:  phy
              ldx ##0
forgetLoop:   txa
              asl a
              tay
              lda abs:.word0 (pageOwner),y
              cmp abs:.word0 (pinId)
              bne forgetNext
              lda ##65535
              sta abs:.word0 (pageOwner),y
forgetNext:   inx
              cpx ##64
              bcc forgetLoop
              ldx abs:.word0 (pinPage)
claimLoop:    phx
              txa
              asl a
              tax
              lda abs:.word0 (pageOwner),x
              cmp ##65535
              beq claimPut
              cmp abs:.word0 (pinId)
              beq claimPut
              asl a
              tay
              lda ##65535
              sta abs:.word0 (soundAt),y
claimPut:     lda abs:.word0 (pinId)
              sta abs:.word0 (pageOwner),x
              plx
              inx
              txa
              sec
              sbc abs:.word0 (pinPage)
              cmp abs:.word0 (pinPages)
              bcc claimLoop
              lda abs:.word0 (pinId)
              asl a
              tax
              lda abs:.word0 (pinPage)
              sta abs:.word0 (soundAt),x
              ply
              rtl

primePointer: ldx abs:.word0 (effectDesc)
              lda long:FX,x
              sta long:copyPointer
              lda long:FX+2,x
              sep #0x20
              sta long:copyPointer+2
              rep #0x20
              lda long:FX+4,x
              sta abs:.word0 (copyLength)
              rtl

;;; copyPointer, copyLength and docPage are set. One page, then interrupts.
uploadSound:  rep #0x30
upMore:       lda abs:.word0 (copyLength)
              beq upDone
              cmp ##256
              bcc upShort
              lda ##256
upShort:      sta abs:.word0 (copyCount)
              jsr abs:.word0 (uploadPage)
              rep #0x30
              lda abs:.word0 (copyLength)
              sec
              sbc abs:.word0 (copyCount)
              sta abs:.word0 (copyLength)
              lda long:copyPointer
              clc
              adc abs:.word0 (copyCount)
              sta long:copyPointer
              bcc upBank
              sep #0x20
              lda long:copyPointer+2
              inc a
              sta long:copyPointer+2
              rep #0x20
upBank:       inc abs:.word0 (docPage)
              jmp abs:.word0 (upMore)
upDone:       rtl

;;; GLU auto-increment, one busy poll, then the page. The source load and
;;; index increment keep consecutive data writes beyond the 1.54 us GLU busy
;;; maximum on the stock CPU. Restore register mode and ADRH before allowing
;;; interrupts, since the IRQ also uses the GLU.
;;; copyPointer addresses copyCount bytes (1..256); docPage selects their
;;; DOC page. Preserve X, Y, D, register widths and the interrupt mask.
;;; A, N and Z are clobbered. DBR must address the sound state.
uploadPage:   phx
              phy
              php
              sei
              phd
              sep #0x20
pageWait:     lda long:CTL
              bmi pageWait
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x60
              sta long:CTL
              lda #0
              sta long:ADR
              lda abs:.word0 (docPage)
              sta long:ADRH
              rep #0x20
              lda ##.word0 (copyPointer)
              tcd
              sep #0x30
              ldy #0
              lda abs:.word0 (copyCount+1)
              bne pageFull
pagePart:     lda [0],y
              sta long:DATA
              iny
              cpy abs:.word0 (copyCount)
              bne pagePart
              bra pageRelease
;;; Y is eight-bit: eight copies per iteration wrap it after exactly one
;;; 256-byte page. Partial pages use the explicit count comparison above.
pageFull:     lda [0],y
              sta long:DATA
              iny
              lda [0],y
              sta long:DATA
              iny
              lda [0],y
              sta long:DATA
              iny
              lda [0],y
              sta long:DATA
              iny
              lda [0],y
              sta long:DATA
              iny
              lda [0],y
              sta long:DATA
              iny
              lda [0],y
              sta long:DATA
              iny
              lda [0],y
              sta long:DATA
              iny
              bne pageFull
pageRelease:  lda long:CTL
              bmi pageRelease
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x20
              sta long:CTL
              lda #0
              sta long:ADRH
              rep #0x30
              pld
              plp
              ply
              plx
              rts

