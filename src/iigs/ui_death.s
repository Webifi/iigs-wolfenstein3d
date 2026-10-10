;;; Death and restart palette transitions, timed by the DOC counter.
;;; DeathFadeStart captures the palettes; DeathFadeStep blends the view to
;;; red over 70 tics while retaining its pixels. Restart paints the first
;;; frame under red, then reveals its colors over 35 tics. View palette 0
;;; changes; status-bar palettes 1..12 remain intact.
#include "memmap.inc"
              .section gamecode, text, root, noreorder
              .public DeathFadeStart, DeathFadeStep, DeathSettle, DeathReveal, DeathLoading, deathLevel, deathFaded, deathSettled
              .extern InitFlash, I_GetTime, castFrame, PrepareSprites, paintFrame, UiLoadSign, UiLoadDone
              .public paintSiteDeath
              .extern UpdateHUD, hudDirty, viewTop, viewBottom, viewLeft, viewBytes, WaitBlank

SHR_PIX       .equ SHR
RED           .equ 10                       ; the red nibble: 42 of 63 is 170 of 255, 10 of 15
RED_WORD      .equ 0x0a00

;;; Clear any damage/bonus flash before capturing all 16 source palettes.
DeathFadeStart:
              jsl long:InitFlash
              ldx ##0x9e00
              ldy ##.word0 (deathSave)
              lda ##511
              .byte 0x54, 0x02, 0xe1        ; MVN: from bank $E1 to here
              stz abs:.word0 (deathLevel)
              lda ##1
              sta abs:.word0 (deathFaded)
              rts

;;; A = the tics since the fade began. The palettes follow that time; carry set from tic 70 on.
DeathFadeStep:
              sta abs:.word0 (dbTime)
              cmp ##71
              bcc stepTime
              lda ##70
stepTime:     tax
              lda abs:.word0 (deathLevels),x
              and ##255
              cmp abs:.word0 (deathLevel)
              beq stepDone
              sta abs:.word0 (deathLevel)
              jsr abs:.word0 (deathBlend)
stepDone:     lda abs:.word0 (dbTime)
              cmp ##70
              rts

;;; The palettes at level A of 16 on the way from the saved ones to the red: each nibble is the
;;; saved one at 16 - A sixteenths, and the red nibble has the red at A sixteenths added.
deathBlend:   asl a
              asl a
              asl a
              asl a
              sta abs:.word0 (dbRow)        ; the row of deathFadeTab for the red
              tax
              lda abs:.word0 (deathFadeTab + 10),x
              and ##255
              sta abs:.word0 (dbRed)
              lda ##256
              sec
              sbc abs:.word0 (dbRow)
              sta abs:.word0 (dbRow)        ; and for the saved colors
              ldx ##510
blendWord:    cpx ##414
              bne blendColor
              ldx ##30                      ; palettes 1 to 12 are skipped
blendColor:   lda abs:.word0 (deathSave),x
              sta abs:.word0 (dbWord)
              and ##15                      ; blue
              clc
              adc abs:.word0 (dbRow)
              tay
              lda abs:.word0 (deathFadeTab),y
              and ##255
              sta abs:.word0 (dbOut)
              lda abs:.word0 (dbWord)
              lsr a
              lsr a
              lsr a
              lsr a
              and ##15                      ; green
              clc
              adc abs:.word0 (dbRow)
              tay
              lda abs:.word0 (deathFadeTab),y
              and ##255
              asl a
              asl a
              asl a
              asl a
              ora abs:.word0 (dbOut)
              sta abs:.word0 (dbOut)
              lda abs:.word0 (dbWord)
              xba
              and ##15                      ; red
              clc
              adc abs:.word0 (dbRow)
              tay
              lda abs:.word0 (deathFadeTab),y
              and ##255
              clc
              adc abs:.word0 (dbRed)
              xba
              ora abs:.word0 (dbOut)
              sta long:PALBUF,x
              dex
              dex
              bpl blendWord
;;; Publish only after the complete step is ready. The two short copies
;;; fit in blanking; palette calculation never touches the visible colors.
              jsl long:WaitBlank
              phb
              ldx ##.word0 (PALBUF)
              ldy ##0x9e00
              lda ##31
              .byte 0x54, 0xe1, 0xe0
              ldx ##0xb1a0
              ldy ##0x9fa0
              lda ##95
              .byte 0x54, 0xe1, 0xe0
              plb
deathBlended:
              rts

;;; The game is over. The view becomes one flat red, the color that the fade ended on, so that the
;;; text and the box for a high score show in the floor's own white and black on top of it: the
;;; saved palettes come back, with the red in slot 2 of the view's palette under the pixels.
DeathSettle:  lda abs:.word0 (viewTop)
              sta abs:.word0 (dsRow)
settleRow:    lda abs:.word0 (dsRow)
              cmp abs:.word0 (viewBottom)
              bcs settleColors
              asl a
              asl a
              asl a
              asl a
              asl a                         ; row * 32
              sta abs:.word0 (dsTmp)
              asl a
              asl a                         ; row * 128
              clc
              adc abs:.word0 (dsTmp)        ; row * 160
              clc
              adc abs:.word0 (viewLeft)
              tax
              lda abs:.word0 (viewBytes)
              lsr a
              tay
              lda ##0x2222
settleWord:   sta long:SHR_PIX,x
              inx
              inx
              dey
              bne settleWord
              lda abs:.word0 (viewBytes)
              lsr a
              bcc settleNext
              sep #0x20
              lda #0x22
              sta long:SHR_PIX,x
              rep #0x20
settleNext:   inc abs:.word0 (dsRow)
              bra settleRow
settleColors: ldx ##.word0 (deathSave)
              ldy ##0x9e00
              lda ##511
              phb
              .byte 0x54, 0xe1, 0x02        ; MVN: from here to bank $E1
              plb
              lda ##RED_WORD
              sta long:SHR_PAL + 4          ; slot 2 of palette 0
deathSettled: rts

;;; The same floor rebuilds in memory beneath the finished red palette.
;;; Preserve the picture until DeathReveal paints the new life. The solid
;;; pixel fill in DeathSettle belongs only to GAME OVER and score entry.
DeathLoading:
loadingSign:  lda ##0
              jsl long:UiLoadSign
              rts

;;; A restart after a death: the first picture comes up under the red, then the colors fade in
;;; over 35 tics. The time of the new life starts after it (level.s sets it later).
DeathReveal:  jsl long:UiLoadDone              ; the first picture of the new life replaces the sign
              lda abs:.word0 (deathFaded)
              bne revealGo
              rts
revealGo:     stz abs:.word0 (deathFaded)
              lda ##16
              sta abs:.word0 (deathLevel)
              jsr abs:.word0 (deathBlend)   ; all red again: after a game over the floor's colors were back
              lda ##1
              sta abs:.word0 (hudDirty)
              jsr abs:.word0 (UpdateHUD)
              jsr abs:.word0 (castFrame)
              jsr abs:.word0 (PrepareSprites)
paintSiteDeath: jsr abs:.word0 (paintFrame)
              jsl long:I_GetTime
              sta abs:.word0 (dsStart)
revealLoop:   jsl long:I_GetTime
              sec
              sbc abs:.word0 (dsStart)
              cmp ##36
              bcc revealTime
              lda ##35
revealTime:   asl a                         ; the table of the fade, at twice the speed
              tax
              lda abs:.word0 (deathLevels),x
              and ##255
              sta abs:.word0 (dsTmp)
              lda ##16
              sec
              sbc abs:.word0 (dsTmp)
              cmp abs:.word0 (deathLevel)
              beq revealSame
              sta abs:.word0 (deathLevel)
              jsr abs:.word0 (deathBlend)
revealSame:   lda abs:.word0 (deathLevel)
              bne revealLoop
              rts

deathCodeEnd:
              .public deathCodeEnd

              .section gamedata, data, root
deathLevel:   .word 0                       ; the level on the screen, 0 to 16
deathFaded:   .word 0                       ; 1 from the start of a fade until the restart shows the colors
dbTime:       .word 0
dbRow:        .word 0
dbRed:        .word 0
dbWord:       .word 0
dbOut:        .word 0
dsRow:        .word 0
dsTmp:        .word 0
dsStart:      .word 0
deathSave:    .space 512
deathLevels: .byte 0,0,0,1,1,1,1,2,2,2,2,3
              .byte 3,3,3,3,4,4,4,4,5,5,5,5
              .byte 5,6,6,6,6,7,7,7,7,8,8,8
              .byte 8,8,9,9,9,9,10,10,10,10,11,11
              .byte 11,11,11,12,12,12,12,13,13,13,13,13
              .byte 14,14,14,14,15,15,15,15,16,16,16
deathFadeTab:
              .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
              .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
              .byte 0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1
              .byte 0,0,0,0,0,0,1,1,1,1,1,2,2,2,2,2
              .byte 0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3
              .byte 0,0,0,0,1,1,1,2,2,2,3,3,3,4,4,4
              .byte 0,0,0,1,1,1,2,2,3,3,3,4,4,4,5,5
              .byte 0,0,0,1,1,2,2,3,3,3,4,4,5,5,6,6
              .byte 0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7
              .byte 0,0,1,1,2,2,3,3,4,5,5,6,6,7,7,8
              .byte 0,0,1,1,2,3,3,4,5,5,6,6,7,8,8,9
              .byte 0,0,1,2,2,3,4,4,5,6,6,7,8,8,9,10
              .byte 0,0,1,2,3,3,4,5,6,6,7,8,9,9,10,11
              .byte 0,0,1,2,3,4,4,5,6,7,8,8,9,10,11,12
              .byte 0,0,1,2,3,4,5,6,7,7,8,9,10,11,12,13
              .byte 0,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14
              .byte 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
