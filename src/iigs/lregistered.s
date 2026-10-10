;;; Wolf and Spear class transitions and spawns. Helpers share the program
;;; bank, data bank and direct page of the actor routines that call them.
#include "logic.inc"
#include "logic_dp.inc"
#include "logic_sounds.inc"
              .section registeredlogic, text, root, noreorder
              .public ClassRow, ClassHitPoints, RegisteredInfo
              .public ClassFirst, ClassPain, ClassKill, ClassScream, ClassShoot
              .public RegisteredReaction
              .extern SpawnNewObj, SpawnStand, SpawnPatrol
              .extern Rnd, NewState, LogicSound, GivePoints, PlaceItemType
              .extern firstSpeed, killed, sightDelay, sightDelayCurrent

;;; A = class ID. X survives. Y = its 32-byte class record offset.
ClassRow:     asl a
              asl a
              asl a
              asl a
              asl a
              tay
              rts

;;; X = actor; class is installed. The four hit points are source values.
ClassHitPoints:
              lda abs:O_CLASS,x
              jsr abs:.word0 (ClassRow)
              tya
              pha
              lda abs:V_difficulty
              asl a
              clc
              adc 1,s
              tay
              pla
              lda abs:CLASS_DATA+C_HP,y
              sta abs:O_HP,x
              rts

;;; A = map object word. Carry set means it was handled, including a
;;; difficulty skip. Otherwise return A unchanged for the ordinary decoder.
RegisteredInfo:
              cmp ##5
              bcs infoWide
              cmp ##1
              bcc infoOrdinary
              clc
              adc ##255                 ; native 1..4 restore source 256..259
infoWide:     cmp ##216
              bcc infoBossCheck
              cmp ##260
              bcs infoOrdinary
              cmp ##224
              bcc mutantCode
              cmp ##228
              bcs infoAfterGhost
#ifdef WOLF_SPEAR
              bra infoOrdinary
#else
              jmp abs:.word0 (ghostCode)
#endif
infoAfterGhost:
              cmp ##234
              bcc infoOrdinary
mutantCode:   sec
              sbc ##216
              ldy ##0
              cmp ##36
              bcc mutantMedium
              sbc ##36
              ldy ##3
              bra mutantLevel
mutantMedium: cmp ##18
              bcc mutantLevel
              sbc ##18
              ldy ##2
mutantLevel:  cpy abs:V_difficulty
              bcc mutantAllowed
              beq mutantAllowed
infoHandled:  sec
              rts
mutantAllowed:
              cmp ##8
              bcs infoHandled
              pha
              and ##3
              sta dp:L_ARG
              pla
              cmp ##4
              lda ##8                    ; en_mutant; class is guardobj+8
              bcc mutantStand
              jsr abs:.word0 (SpawnPatrol)
              bra infoHandled
mutantStand:  jsr abs:.word0 (SpawnStand)
              bra infoHandled
infoOrdinary: clc
              rts

infoBossCheck:
#ifdef WOLF_SPEAR
              ldy ##21
              cmp ##106
              beq spawnClassBoss
              ldy ##22
              cmp ##107
              beq spawnClassBoss
              ldy ##23
              cmp ##125
              beq spawnClassBoss
              ldy ##24
              cmp ##142
              beq spawnClassBoss
              ldy ##25
              cmp ##143
              beq spawnClassBoss
              ldy ##26
              cmp ##161
              bne infoOrdinary
#else
              ldy ##17
              cmp ##197
              beq spawnClassBoss
              ldy ##8
              cmp ##196
              beq spawnClassBoss
              ldy ##9
              cmp ##160
              beq spawnClassBoss
              ldy ##10
              cmp ##178
              beq spawnClassBoss
              ldy ##18
              cmp ##215
              beq spawnClassBoss
              ldy ##19
              cmp ##179
              bne infoOrdinary
#endif
spawnClassBoss:
              sty dp:L_W
              tya
              jsr abs:.word0 (ClassRow)
              lda abs:CLASS_DATA+C_STAND,y
              jsr abs:.word0 (SpawnNewObj)
              lda dp:L_W
              sta abs:O_CLASS,x
              jsr abs:.word0 (ClassHitPoints)
              lda ##512
              sta abs:O_SPEED,x
#ifdef WOLF_SPEAR
              lda ##8                    ; SpawnNewObj leaves Spear bosses at nodir
#else
              lda ##6                    ; DOS spawn facing; three bosses face north
              ldy dp:L_W
              cpy ##9
              beq bossNorth
              cpy ##17
              beq bossNorth
              cpy ##18
              bne bossFaces
bossNorth:    lda ##2
#endif
bossFaces:    sta abs:O_DIR,x
              lda abs:O_FLAGS,x
              ora ##65                   ; FL_SHOOTABLE | FL_AMBUSH
              sta abs:O_FLAGS,x
              inc abs:V_killtotal
              sec
              rts

#ifndef WOLF_SPEAR
ghostCode:    sec
              sbc ##224
              asl a
              tay
              lda abs:GHOST_STATES,y
              jsr abs:.word0 (SpawnNewObj)
              lda ##15
              sta abs:O_CLASS,x
              lda ##1500
              sta abs:O_SPEED,x
              lda ##0
              sta abs:O_DIR,x
              lda abs:O_FLAGS,x
              ora ##64
              sta abs:O_FLAGS,x
              inc abs:V_killtotal
              sec
              rts

#endif
RegisteredReaction:
              cmp ##4
              bne reactionMutant
              lda ##2
              jmp abs:.word0 (sightDelayCurrent)
reactionMutant:
              cmp ##11
              bne reactionBoss
              jsr abs:.word0 (Rnd)
              tay
              lda abs:DIV6,y
              and ##255
              jmp abs:.word0 (sightDelay)
reactionBoss: lda ##0
              jmp abs:.word0 (sightDelay)

ClassShoot:   jsr abs:.word0 (ClassRow)
              lda abs:CLASS_DATA+C_SHOOT,y
              beq classNoShot
              tay
              jmp abs:.word0 (NewState)
classNoShot:  rts

ClassFirst:   jsr abs:.word0 (ClassRow)
              lda abs:CLASS_DATA+C_SIGHT,y
              bmi classSilent
              jsr abs:.word0 (LogicSound)
classSilent:  lda abs:CLASS_DATA+C_MULT,y
              sta dp:L_U
              lda abs:CLASS_DATA+C_CHASE,y
              tay
              jsr abs:.word0 (NewState)
#ifdef WOLF_SPEAR
              lda abs:O_CLASS,x
              cmp ##21
              bcc classOrdinarySpeed
              sec
              sbc ##21
              asl a
              phx
              tax
              lda long:spearChaseSpeeds,x
              plx
              jmp abs:.word0 (firstSpeed)
classOrdinarySpeed:
#endif
              lda abs:O_SPEED,x
              sta dp:L_T
              lda ##0
classSpeed:   clc
              adc dp:L_T
              dec dp:L_U
              bne classSpeed
              jmp abs:.word0 (firstSpeed)

ClassScream:  jsr abs:.word0 (ClassRow)
              lda abs:CLASS_DATA+C_SCREAM,y
              bmi classScreamDone
              jmp abs:.word0 (LogicSound)
classScreamDone:
              rts

ClassPain:    jsr abs:.word0 (ClassRow)
              lda abs:CLASS_DATA+C_PAIN,y
              beq classPainDone
              pha
              lda abs:O_HP,x
              lsr a
              bcs classPainOdd
              pla
              lda abs:CLASS_DATA+C_PAIN1,y
              bra classPainSet
classPainOdd: pla
classPainSet: tay
              jmp abs:.word0 (NewState)
classPainDone:rts

ClassKill:
#ifndef WOLF_SPEAR
              cmp ##8
              beq classSaveKill
              cmp ##16
              beq classSaveKill
              cmp ##18
              beq classSaveKill
              cmp ##19
              bne classKillRecord
classSaveKill:
              pha
              lda abs:OBJLIST+O_X
              sta abs:V_killx
              lda abs:OBJLIST+O_X+2
              sta abs:V_killx_hi
              lda abs:OBJLIST+O_Y
              sta abs:V_killy
              lda abs:OBJLIST+O_Y+2
              sta abs:V_killy_hi
              pla
#endif
classKillRecord:
              jsr abs:.word0 (ClassRow)
              phy
              lda abs:CLASS_DATA+C_POINTS,y
              jsr abs:.word0 (GivePoints)
              ply
              ldx dp:L_ARG
              phy
              lda abs:CLASS_DATA+C_DIE,y
              tay
              jsr abs:.word0 (NewState)
              ply
              lda abs:CLASS_DATA+C_DROP,y
              bmi classNoDrop
              jsr abs:.word0 (PlaceItemType)
classNoDrop:
#ifndef WOLF_SPEAR
              ldx dp:L_ARG
              lda abs:O_CLASS,x
              cmp ##8
              beq classImmediateScream
              cmp ##16
              bne classKilled
classImmediateScream:
              jsr abs:.word0 (ClassScream)
#endif
classKilled:  jmp abs:.word0 (killed)
#ifdef WOLF_SPEAR
spearChaseSpeeds: .word 800,1536,1536,3000,2048,2048
#endif
