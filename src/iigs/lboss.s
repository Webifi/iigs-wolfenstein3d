;;; Movement and actions for Wolf and Spear bosses. Ordinary guards,
;;; dogs, SS and Hans use the shared chase loop in lact.s.
#include "logic.inc"
#include "logic_dp.inc"
#include "logic_sounds.inc"
              .section registeredlogic, text, root, noreorder
              .public T_Fake, T_Fat, T_Ghosts, T_Gift, T_Schabb, SelectRunDir
              .public A_Slurpie, GhostContact, RegisteredShotSound
#ifndef WOLF_SPEAR
              .public A_HitlerMorph, A_MechaSound
#endif
              .extern Rnd, CheckLine, TakeDamage, LogicSound, SpawnNewObj, ClassHitPoints
              .extern speedMove, moveFits, snapToTile, tileDistance, OpenDoor, MoveObj
              .extern SelectDodgeDir, SelectChaseDir, chaseAttempt, ClassShoot
PLAYER        .equ OBJLIST

#ifdef WOLF_SPEAR
              .public T_Will
T_Will:
#endif
T_Schabb:
T_Gift:
T_Fat:        stz dp:L_DODGE
              ldx dp:L_OB
              jsr abs:.word0 (tileDistance)
              jsr abs:.word0 (CheckLine)
              bcc bossChooseInitial
              lda abs:V_tics
              asl a
              asl a
              asl a
              sta dp:L_CHANCE
              jsr abs:.word0 (Rnd)
              cmp dp:L_CHANCE
              bcs bossDodge
bossShoot:    ldx dp:L_OB
              lda abs:O_CLASS,x
              jmp abs:.word0 (ClassShoot)
bossDodge:    inc dp:L_DODGE
bossChooseInitial:
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##8
              bne bossHasDirection
              jsr abs:.word0 (bossChoose)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##8
              bne bossHasDirection
              rts
bossHasDirection:
              jsr abs:.word0 (speedMove)
bossMoveLoop: lda dp:L_MOVE
              ora dp:L_MOVE+2
              beq bossDone
              ldx dp:L_OB
              lda abs:O_DIST+2,x
              bpl bossNoDoor
              lda abs:O_DIST,x
              eor ##0xffff
              sta dp:L_DOOR
              jsr abs:.word0 (OpenDoor)
              lda dp:L_DOOR
              asl a
              tax
              lda abs:DOORACT,x
              bne bossDone
              ldx dp:L_OB
              stz abs:O_DIST,x
              lda ##1
              sta abs:O_DIST+2,x
bossNoDoor:   jsr abs:.word0 (moveFits)
              bcc bossReached
              jmp abs:.word0 (MoveObj)
bossReached:  jsr abs:.word0 (snapToTile)
              lda dp:L_DIST
              cmp ##4
              bcs bossChooseAgain
              jsr abs:.word0 (SelectRunDir)
              bra bossChosen
bossChooseAgain:
              jsr abs:.word0 (bossChoose)
bossChosen:   ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##8
              bne bossMoveLoop
bossDone:     rts
bossChoose:   ldx dp:L_OB
              lda dp:L_DODGE
              beq chooseChase
              jmp abs:.word0 (SelectDodgeDir)
chooseChase:  jmp abs:.word0 (SelectChaseDir)

T_Fake:       ldx dp:L_OB
              jsr abs:.word0 (CheckLine)
              bcc fakeMove
              lda abs:V_tics
              asl a
              sta dp:L_CHANCE
              jsr abs:.word0 (Rnd)
              cmp dp:L_CHANCE
              bcs fakeMove
              jmp abs:.word0 (bossShoot)
fakeMove:     lda ##1
              bra simpleMove
T_Ghosts:     lda ##0
simpleMove:   sta dp:L_DODGE
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##8
              bne simpleHasDirection
              jsr abs:.word0 (bossChoose)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##8
              bne simpleHasDirection
              rts
simpleHasDirection:
              jsr abs:.word0 (speedMove)
simpleMoveLoop:
              lda dp:L_MOVE
              ora dp:L_MOVE+2
              beq simpleDone
              ldx dp:L_OB
              jsr abs:.word0 (moveFits)
              bcc simpleReached
              jmp abs:.word0 (MoveObj)
simpleReached:
              jsr abs:.word0 (snapToTile)
              jsr abs:.word0 (bossChoose)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##8
              bne simpleMoveLoop
simpleDone:   rts

;;; Try the axes away from the player, preferring the greater tile distance.
;;; If both fail, one random byte chooses the traversal order of the fixed
;;; north/northwest/west fallback. Its order affects subsequent actor state.
SelectRunDir: ldx dp:L_OB
              lda abs:PLAYER+O_TILEX
              sec
              sbc abs:O_TILEX,x
              sta dp:L_T
              bmi runXEast
              ldy ##4
              bra runX
runXEast:     ldy ##0
runX:         sty dp:L_TRY+2
              lda abs:PLAYER+O_TILEY
              sec
              sbc abs:O_TILEY,x
              sta dp:L_U
              bmi runYSouth
              ldy ##2
              bra runY
runYSouth:    ldy ##6
runY:         sty dp:L_TRY+4
              lda dp:L_T
              bpl runAbsX
              eor ##0xffff
              inc a
runAbsX:      sta dp:L_V
              lda dp:L_U
              bpl runAbsY
              eor ##0xffff
              inc a
runAbsY:      cmp dp:L_V
              bcc runOrdered
              beq runOrdered
              lda dp:L_TRY+2
              ldy dp:L_TRY+4
              sta dp:L_TRY+4
              sty dp:L_TRY+2
runOrdered:   lda dp:L_TRY+2
              jsr abs:.word0 (chaseAttempt)
              bcs runDone
              lda dp:L_TRY+4
              jsr abs:.word0 (chaseAttempt)
              bcs runDone
              jsr abs:.word0 (Rnd)
              cmp ##129
              bcc runBackward
              lda ##2
              jsr abs:.word0 (chaseAttempt)
              bcs runDone
              lda ##3
              jsr abs:.word0 (chaseAttempt)
              bcs runDone
              lda ##4
              bra runLast
runBackward:  lda ##4
              jsr abs:.word0 (chaseAttempt)
              bcs runDone
              lda ##3
              jsr abs:.word0 (chaseAttempt)
              bcs runDone
              lda ##2
runLast:      jsr abs:.word0 (chaseAttempt)
              bcs runDone
              ldx dp:L_OB
              lda ##8
              sta abs:O_DIR,x
runDone:      rts

GhostContact: lda abs:V_tics
              asl a
              jmp abs:.word0 (TakeDamage)

#ifndef WOLF_SPEAR
A_HitlerMorph:
              ldx dp:L_OB
              lda abs:O_TILEX,x
              sta dp:L_SX
              lda abs:O_TILEY,x
              sta dp:L_SY
              lda ##s_hitlerchase1
              jsr abs:.word0 (SpawnNewObj)
              lda ##2560
              sta abs:O_SPEED,x
              lda ##16
              sta abs:O_CLASS,x
              jsr abs:.word0 (ClassHitPoints)
              ldy dp:L_OB
              lda abs:O_X,y
              sta abs:O_X,x
              lda abs:O_X+2,y
              sta abs:O_X+2,x
              lda abs:O_Y,y
              sta abs:O_Y,x
              lda abs:O_Y+2,y
              sta abs:O_Y+2,x
              lda abs:O_DIST,y
              sta abs:O_DIST,x
              lda abs:O_DIST+2,y
              sta abs:O_DIST+2,x
              lda abs:O_DIR,y
              sta abs:O_DIR,x
              lda abs:O_FLAGS,y
              ora ##1
              sta abs:O_FLAGS,x
              rts
A_MechaSound: ldx dp:L_OB
              ldy abs:O_AREA,x
              lda abs:AREABYPLAYER,y
              and ##255
              beq mechaQuiet
              lda ##MECHSTEPSND
              jmp abs:.word0 (LogicSound)
mechaQuiet:   rts
#endif
A_Slurpie:    lda ##SLURPIESND
              jmp abs:.word0 (LogicSound)

;;; A = class. Called only after the SS fast case.
RegisteredShotSound:
#ifdef WOLF_SPEAR
              cmp ##23
              beq soundBoss
              cmp ##24
              beq soundBoss
              cmp ##25
              beq soundBoss
              cmp ##26
              beq soundBoss
              lda ##NAZIFIRESND
              jmp abs:.word0 (LogicSound)
soundBoss:    lda ##BOSSFIRESND
              jmp abs:.word0 (LogicSound)
#else
              cmp ##7
              beq soundBoss
              cmp ##10
              beq soundBoss
              cmp ##16
              beq soundBoss
              cmp ##18
              beq soundRocket
              cmp ##19
              beq soundRocket
              cmp ##8
              beq soundNeedle
              cmp ##9
              beq soundFlame
              lda ##NAZIFIRESND
              jmp abs:.word0 (LogicSound)
soundBoss:    lda ##BOSSFIRESND
              jmp abs:.word0 (LogicSound)
soundRocket:  lda ##MISSILEFIRESND
              jmp abs:.word0 (LogicSound)
soundNeedle:  lda ##SCHABBSTHROWSND
              jmp abs:.word0 (LogicSound)
soundFlame:   lda ##FLAMETHROWERSND
              jmp abs:.word0 (LogicSound)
#endif
#ifdef WOLF_SPEAR
#include "lspear.inc"
#endif
