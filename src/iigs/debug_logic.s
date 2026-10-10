;;; Cheats use the ordinary inventory and damage routines in their native context.
#include "memmap.inc"
#include "logic.inc"
#include "logic_dp.inc"
              .section logictail, text, root, noreorder
              .public DebugLogic, DebugTryMove
              .extern GivePoints, HealSelf, GiveWeapon, TakeDamage, TryMove
DebugLogic:   php
              rep #0x30
              phb
              phd
              pha
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              pla
              cmp ##1
              beq debugMLI
              cmp ##'H'
              beq debugHurt
              cmp ##'I'
              beq debugItems
              lda ##1
              sta abs:V_playstate
              bra debugLogicDone
debugHurt:    ldx ##0
              lda ##16
              jsr abs:.word0 (TakeDamage)
              bra debugLogicDone
debugMLI:     lda ##100
              sta abs:V_health
              lda ##99
              sta abs:V_ammo
              lda ##3
              sta abs:V_keys
              jsr abs:.word0 (GiveWeapon)
              stz abs:V_score
              stz abs:V_score_hi
              bra debugLogicDone
debugItems:   lda ##50000
              jsr abs:.word0 (GivePoints)
              lda ##50000
              jsr abs:.word0 (GivePoints)
              lda ##99
              jsr abs:.word0 (HealSelf)
              lda abs:V_bestweapon
              cmp ##3
              bcs debugAmmo
              inc a
              jsr abs:.word0 (GiveWeapon)
debugAmmo:    lda abs:V_ammo
              clc
              adc ##50
              cmp ##100
              bcc debugAmmoReady
              lda ##99
debugAmmoReady:
              sta abs:V_ammo
debugLogicDone:
              lda ##3
              tsb abs:V_events
              pld
              plb
              plp
              rtl

;;; Only the first collision test is redirected when Spear noclip is enabled.
;;; Retain the DOS guard at two tiles from the top/left and one at bottom/right.
DebugTryMove: jsr abs:.word0 (TryMove)
              bcs debugMoveDone
              lda abs:OBJLIST+O_X
              cmp ##1
              lda abs:OBJLIST+O_X+2
              sbc ##2
              bcc debugMoveBlocked
              lda abs:OBJLIST+O_X+2
              cmp ##63
              bcs debugMoveBlocked
              lda abs:OBJLIST+O_Y
              cmp ##1
              lda abs:OBJLIST+O_Y+2
              sbc ##2
              bcc debugMoveBlocked
              lda abs:OBJLIST+O_Y+2
              cmp ##63
              bcs debugMoveBlocked
              sec
              rts
debugMoveBlocked:
              clc
debugMoveDone:rts
