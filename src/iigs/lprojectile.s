;;; Wolf and Spear missiles. Aim is calculated at launch; movement uses
;;; the sign-magnitude sine table and the word-product tables.
#include "logic.inc"
#include "logic_dp.inc"
#include "logic_sounds.inc"
              .section registeredlogic, text, root, noreorder
              .public T_Projectile, A_Smoke
#ifndef WOLF_SPEAR
              .public T_SchabbThrow, T_GiftThrow, T_FakeFire
#endif
              .public ProjectileAim, ProjectileFraction
              .extern GetNewActor, Rnd, LogicSound, TakeDamage
              .extern Mul16, MulHigh16, speedMove
PLAYER        .equ OBJLIST

;;; X = shooter. Return A = floor(atan2(shooter.y-player.y,
;;; player.x-shooter.x)*360/tau), wrapped into 0..359. Coordinates are 16.16.
;;; Only launches use the 32-step fractional divide, never movement or drawing.
ProjectileAim:
              stz dp:L_SIGN
              lda abs:PLAYER+O_X
              sec
              sbc abs:O_X,x
              sta dp:L_PB
              lda abs:PLAYER+O_X+2
              sbc abs:O_X+2,x
              sta dp:L_PB+2
              bpl aimXPositive
              inc dp:L_SIGN
              lda ##0
              sec
              sbc dp:L_PB
              sta dp:L_PB
              lda ##0
              sbc dp:L_PB+2
              sta dp:L_PB+2
aimXPositive: lda abs:O_Y,x
              sec
              sbc abs:PLAYER+O_Y
              sta dp:L_PA
              lda abs:O_Y+2,x
              sbc abs:PLAYER+O_Y+2
              sta dp:L_PA+2
              bpl aimYPositive
              lda ##2
              tsb dp:L_SIGN
              lda ##0
              sec
              sbc dp:L_PA
              sta dp:L_PA
              lda ##0
              sbc dp:L_PA+2
              sta dp:L_PA+2
aimYPositive: stz dp:L_FRAC
              lda dp:L_PA
              cmp dp:L_PB
              lda dp:L_PA+2
              sbc dp:L_PB+2
              bcc aimOrdered
              lda dp:L_PA
              eor dp:L_PB
              sta dp:L_T
              lda dp:L_PA+2
              eor dp:L_PB+2
              ora dp:L_T
              bne aimSwap
              lda dp:L_PA
              ora dp:L_PA+2
              beq aimZero
              lda ##45
              jmp abs:.word0 (aimQuadrant)
aimSwap:      lda dp:L_PA
              ldy dp:L_PB
              sta dp:L_PB
              sty dp:L_PA
              lda dp:L_PA+2
              ldy dp:L_PB+2
              sta dp:L_PB+2
              sty dp:L_PA+2
              lda ##4
              tsb dp:L_SIGN
aimOrdered:   lda dp:L_PA
              ora dp:L_PA+2
              bne aimDivide
aimZero:      lda ##0
              jmp abs:.word0 (aimOctant)
aimDivide:    inc dp:L_FRAC              ; non-axial, non-diagonal angle has a fraction
              stz dp:L_PC
              stz dp:L_PC+2
              ldy ##32
aimDivideBit: asl dp:L_PC
              rol dp:L_PC+2
              asl dp:L_PA
              rol dp:L_PA+2
              lda dp:L_PA
              cmp dp:L_PB
              lda dp:L_PA+2
              sbc dp:L_PB+2
              bcc aimDivideNext
              sta dp:L_PA+2
              lda dp:L_PA
              sec
              sbc dp:L_PB
              sta dp:L_PA
              inc dp:L_PC
aimDivideNext:dey
              bne aimDivideBit
              stz dp:L_T                  ; lower bound, degrees
              lda ##45
              sta dp:L_U                  ; exclusive upper bound
aimSearch:    lda dp:L_T
              inc a
              cmp dp:L_U
              bcs aimFound
              lda dp:L_T
              clc
              adc dp:L_U
              lsr a
              sta dp:L_V
              asl a
              asl a
              tay
              lda dp:L_PC
              cmp abs:PROJECTILE_TANGENTS,y
              lda dp:L_PC+2
              sbc abs:PROJECTILE_TANGENTS+2,y
              bcc aimLess
              lda dp:L_V
              sta dp:L_T
              bra aimSearch
aimLess:      lda dp:L_V
              sta dp:L_U
              bra aimSearch
aimFound:     lda dp:L_T
aimOctant:    sta dp:L_T
              lda dp:L_SIGN
              bit ##4
              beq aimUnswapped
              lda ##90
              sec
              sbc dp:L_T
              sec
              sbc dp:L_FRAC
              bra aimQuadrant
aimUnswapped: lda dp:L_T
aimQuadrant:  sta dp:L_ANGLE
              lda dp:L_SIGN
              and ##3
              beq aimDone
              cmp ##1
              beq aimNorthwest
              cmp ##2
              beq aimSoutheast
              lda dp:L_ANGLE
              clc
              adc ##180
              bra aimReturn
aimNorthwest: lda ##180
              bra aimReflect
aimSoutheast: lda ##360
aimReflect:   sec
              sbc dp:L_ANGLE
              sec
              sbc dp:L_FRAC
              cmp ##360
              bcc aimReturn
              lda ##0
aimReturn:    sta dp:L_ANGLE
aimDone:      lda dp:L_ANGLE
              rts

#ifndef WOLF_SPEAR
T_SchabbThrow:jsr abs:.word0 (launchMissile)
              lda ##s_needle1
              sta abs:O_STATE,x
              lda ##12
              sta abs:O_CLASS,x
              lda ##SCHABBSTHROWSND
              jmp abs:.word0 (LogicSound)
T_GiftThrow:  jsr abs:.word0 (launchMissile)
              lda ##s_rocket
              sta abs:O_STATE,x
              lda ##20
              sta abs:O_CLASS,x
              lda ##MISSILEFIRESND
              jmp abs:.word0 (LogicSound)
T_FakeFire:   jsr abs:.word0 (launchMissile)
              lda ##s_fire1
              sta abs:O_STATE,x
              lda ##13
              sta abs:O_CLASS,x
              lda ##0x1200
              sta abs:O_SPEED,x
              lda ##4
              sta abs:O_FLAGS,x
              lda ##FLAMETHROWERSND
              jmp abs:.word0 (LogicSound)
#endif
launchMissile:
              ldx dp:L_OB
              jsr abs:.word0 (ProjectileAim)
              jsr abs:.word0 (GetNewActor)
              jsr abs:.word0 (copyOrigin)
              lda ##1
              sta abs:O_TICS,x
              sta abs:O_ACTIVE,x
              lda ##8
              sta abs:O_DIR,x
              lda dp:L_ANGLE
              sta abs:O_ANGLE,x
              lda ##0x2000
              sta abs:O_SPEED,x
              lda ##128
              sta abs:O_FLAGS,x
              rts

A_Smoke:      jsr abs:.word0 (GetNewActor)
              jsr abs:.word0 (copyOrigin)
#ifdef WOLF_SPEAR
              ldy dp:L_OB
              lda abs:O_CLASS,y
              cmp ##27
              bne lightSmoke
              lda ##s_hsmoke1
              bra smokeState
lightSmoke:   lda ##s_smoke1
smokeState:
#else
              lda ##s_smoke1
#endif
              sta abs:O_STATE,x
              lda ##6
              sta abs:O_TICS,x
              lda ##2
              sta abs:O_CLASS,x
              lda ##1
              sta abs:O_ACTIVE,x
              lda ##4
              sta abs:O_FLAGS,x
              rts
copyOrigin:   ldy dp:L_OB
              lda abs:O_X,y
              sta abs:O_X,x
              lda abs:O_X+2,y
              sta abs:O_X+2,x
              lda abs:O_Y,y
              sta abs:O_Y,x
              lda abs:O_Y+2,y
              sta abs:O_Y+2,x
              lda abs:O_TILEX,y
              sta abs:O_TILEX,x
              lda abs:O_TILEY,y
              sta abs:O_TILEY,x
              rts

;;; L_PB = FixedByFrac(L_MOVE, table[Y]). The full product matters when
;;; several simulation tics run together. Y and the current actor survive.
ProjectileFraction:
              phy
              lda abs:0,y
              tay
              lda dp:L_MOVE
              jsr abs:.word0 (MulHigh16)
              sta dp:L_TEMP32
              lda dp:L_MOVE+2
              jsr abs:.word0 (Mul16)
              lda dp:L_PROD
              clc
              adc dp:L_TEMP32
              sta dp:L_PB
              lda dp:L_PROD+2
              adc ##0
              sta dp:L_PB+2
              ply
              lda abs:2,y
              bpl projectileFractionDone
              jmp abs:.word0 (negateFraction)
projectileFractionDone:
              rts
negateFraction:
              lda ##0
              sec
              sbc dp:L_PB
              sta dp:L_PB
              lda ##0
              sbc dp:L_PB+2
              sta dp:L_PB+2
              rts
clampFraction:
              lda dp:L_PB+2
              bmi projectileFractionDone
              cmp ##1
              bcc projectileFractionDone
              stz dp:L_PB
              lda ##1
              sta dp:L_PB+2
              rts

T_Projectile: ldx dp:L_OB
              jsr abs:.word0 (speedMove)
              lda abs:O_ANGLE,x
              asl a
              asl a
              clc
              adc ##SINTAB+360
              tay
              jsr abs:.word0 (ProjectileFraction)
              jsr abs:.word0 (clampFraction)
              ldx dp:L_OB
              lda abs:O_X,x
              clc
              adc dp:L_PB
              sta abs:O_X,x
              lda abs:O_X+2,x
              adc dp:L_PB+2
              sta abs:O_X+2,x
              tya
              sec
              sbc ##360
              tay
              jsr abs:.word0 (ProjectileFraction)
              jsr abs:.word0 (negateFraction)
              jsr abs:.word0 (clampFraction)
              ldx dp:L_OB
              lda abs:O_Y,x
              clc
              adc dp:L_PB
              sta abs:O_Y,x
              lda abs:O_Y+2,x
              adc dp:L_PB+2
              sta abs:O_Y+2,x
              jsr abs:.word0 (projectileTryMove)
              bcs projectilePlayer
              ldx dp:L_OB
              lda abs:O_CLASS,x
#ifdef WOLF_SPEAR
              cmp ##27
              bne lightExplosion
              lda ##MISSILEHITSND
              jsr abs:.word0 (LogicSound)
              lda ##s_hboom1
              sta abs:O_STATE,x
              rts
lightExplosion:
#endif
              cmp ##20
              bne projectileRemove
              lda ##MISSILEHITSND
              jsr abs:.word0 (LogicSound)
              lda ##s_boom1               ; source retains the running ticcount
              sta abs:O_STATE,x
              rts
projectileRemove:
              stz abs:O_STATE,x
              rts
projectilePlayer:
              ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc abs:PLAYER+O_X
              sta dp:L_T
              lda abs:O_X+2,x
              sbc abs:PLAYER+O_X+2
              jsr abs:.word0 (projectileNear)
              bcc projectileTiles
              lda abs:O_Y,x
              sec
              sbc abs:PLAYER+O_Y
              sta dp:L_T
              lda abs:O_Y+2,x
              sbc abs:PLAYER+O_Y+2
              jsr abs:.word0 (projectileNear)
              bcc projectileTiles
              jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              lsr a
              ldy abs:O_CLASS,x
              cpy ##13
              beq projectileDamage
#ifdef WOLF_SPEAR
              cpy ##28
#else
              cpy ##12
#endif
              beq projectileNeedle
              clc
              adc ##10
projectileNeedle:
              clc
              adc ##20
projectileDamage:
              jsr abs:.word0 (TakeDamage)
              bra projectileRemove
projectileTiles:
              lda abs:O_X+2,x
              sta abs:O_TILEX,x
              lda abs:O_Y+2,x
              sta abs:O_TILEY,x
              rts
;;; Carry set when abs(A:L_T) < 0xc000; X survives.
projectileNear:
              bpl projectileNearPositive
              cmp ##0xffff
              bne projectileFar
              lda dp:L_T
              cmp ##0x4001
              rts
projectileNearPositive:
              bne projectileFar
              lda ##0xbfff
              cmp dp:L_T
              rts
projectileFar:clc
              rts

projectileTryMove:
              lda abs:O_X,x
              sec
              sbc ##0x2000
              lda abs:O_X+2,x
              sbc ##0
              sta dp:L_XL
              lda abs:O_X,x
              clc
              adc ##0x2000
              lda abs:O_X+2,x
              adc ##0
              sta dp:L_XH
              lda abs:O_Y,x
              sec
              sbc ##0x2000
              lda abs:O_Y+2,x
              sbc ##0
              sta dp:L_YL
              lda abs:O_Y,x
              clc
              adc ##0x2000
              lda abs:O_Y+2,x
              adc ##0
              sta dp:L_YH
              lda dp:L_YL
              sta dp:L_Y
projectileRow:lda dp:L_XL
              sta dp:L_X
projectileCell:
              lda dp:L_X
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc dp:L_Y
              asl a
              tay
              lda abs:ACTORAT,y
              beq projectileCellClear
              cmp ##OBJLIST
              bcc projectileBlocked
projectileCellClear:
              inc dp:L_X
              lda dp:L_XH
              cmp dp:L_X
              bcs projectileCell
              inc dp:L_Y
              lda dp:L_YH
              cmp dp:L_Y
              bcs projectileRow
              sec
              rts
projectileBlocked:
              clc
              rts
#ifdef WOLF_SPEAR
#include "spear_projectile.inc"
#endif
