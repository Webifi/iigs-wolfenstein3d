#include "progress.inc"
;;; Initialize game state and reconstruct a floor from its raw map planes.
;;; Restarts and demos share the same object spawning and difficulty rules.
#include "logic.inc"
#ifdef WOLF_SPEAR
#include "campaign.inc"
#endif
#include "logic_dp.inc"
#include "sprite_ids.inc"
              .section registeredlogic, text, root, noreorder
              .extern ClassHitPoints, RegisteredInfo
              .public SpawnNewObj, SpawnStand, SpawnPatrol
              .public LogicNewGame, LogicSetupLevel, LogicMarkObjects, LogicMarkActorRays
              .extern InitLineRegions
              .extern ResetLogicTimers
              .extern ClearStaticIndex, AddStaticIndex, ratioTable
              .extern Rnd, InitActorList, GetNewActor, CellOfX, Thrust, MarkRayCellL, MarkStaticCellL
              .extern gsCapture
              .public StaticSpriteVariant

PLAYER        .equ OBJLIST
FL_SHOOTABLE  .equ 1
FL_BONUS      .equ 2
FL_NEVERMARK  .equ 4
FL_AMBUSH     .equ 64
PLAYEROBJ     .equ 1
INERTOBJ      .equ 2
GUARDOBJ      .equ 3
BOSSOBJ       .equ 7
NODIR         .equ 8
SOUTH         .equ 6
SPDPATROL     .equ 512
SPDDOG        .equ 1500

;;; JSL. A = difficulty (gd_baby 0 .. gd_hard 3), X = mapon.
LogicNewGame: php
              rep #0x30
              phb
              phd
              pha
              phx
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              plx
              pla
              sta abs:V_difficulty
              stx abs:V_mapon
              phx
              lda ##0
#ifdef WOLF_SPEAR
              ldx ##CAMPAIGN_RATIO_BYTES-2
#else
              ldx ##62
#endif
clearRatios:  sta long:ratioTable,x
              dex
              dex
              bpl clearRatios
              plx
              stz abs:V_score
              stz abs:V_score_hi
              lda ##40000
              sta abs:V_nextextra
              stz abs:V_nextextra_hi
              lda ##3
              sta abs:V_lives
              lda ##100
              sta abs:V_health
              lda ##8
              sta abs:V_ammo
              stz abs:V_keys
              lda ##1
              sta abs:V_weapon
              sta abs:V_bestweapon
              sta abs:V_chosenweapon
              stz abs:V_faceframe
              stz abs:V_attackframe
              stz abs:V_attackcount
              stz abs:V_weaponframe
              stz abs:V_victoryflag
#ifdef WOLF_SPEAR
              stz abs:V_spearflag
#endif
              stz abs:V_playstate
              stz abs:V_deathcam_phase
              stz abs:V_deathcam_actor
              stz abs:V_pwallstate
              stz abs:V_pwallpos
              pld
              plb
              plp
              rtl

;;; JSL. A = the starting rndindex (0 for a demo). The raw planes of the
;;; floor are in RAW0/RAW1.
LogicSetupLevel:
              php
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
              and ##255
              sta abs:V_rndindex
              jsr abs:.word0 (InitLineRegions)
              lda abs:V_score
              sta abs:V_oldscore
              lda abs:V_score_hi
              sta abs:V_oldscore_hi
              stz abs:V_secrettotal
              stz abs:V_killtotal
              stz abs:V_treasuretotal
              stz abs:V_secretcount
              stz abs:V_killcount
              stz abs:V_treasurecount
              stz abs:V_playstate
              stz abs:V_deathcam_phase
              stz abs:V_deathcam_actor
              stz abs:V_anglefrac
              stz abs:V_facecount
#ifdef WOLF_SPEAR
              stz abs:V_ouchface
#endif
              stz abs:V_bonuscount
              stz abs:V_damagecount
              stz abs:V_damageflash
              stz abs:V_gatling
              jsl long:ResetLogicTimers
              stz abs:V_thrustspeed
              stz abs:V_thrustspeed_hi
              stz abs:V_madenoise
              stz abs:V_events
              stz abs:V_spotstamp
              lda ##1
              sta dp:L_VISDIRTY
              ldx ##30
clearButtons: stz abs:V_buttonstate,x
              dex
              dex
              bpl clearButtons
              lda ##0xffff
              sta abs:V_weaponchoice
              ldx ##4094
copyPlanes:
              lda long:RAW0_ADDRESS,x
              sta abs:MAP0,x
              lda long:RAW1_ADDRESS,x
              sta abs:MAP1,x
              dex
              dex
              bpl copyPlanes
;;; tilemap and actorat: walls below AREATILE, floors empty.
              stz dp:L_SY
wallsRow:     stz dp:L_SX
wallsCell:    jsr abs:.word0 (planeIndex)
              lda abs:MAP0,y
              and ##255
              cmp ##107
              bcc wallTile
              lda ##0
wallTile:     pha
              jsr abs:.word0 (cellIndex)
              pla
              sep #0x20
              sta abs:TILEMAP,x
              rep #0x20
              pha
              txa
              asl a
              tax
              pla
              sta abs:ACTORAT,x
              jsr abs:.word0 (nextCell)
              bcc wallsCell
              jsr abs:.word0 (InitActorList)
;;; InitDoorList and InitStaticList.
              stz abs:V_doornum
              ldx ##1368
clearConnect: stz abs:AREACONNECT,x
              dex
              dex
              bpl clearConnect
              ldx ##62
clearAreaRow: stz abs:AREABYPLAYER,x
              dex
              dex
              bpl clearAreaRow
              lda ##STATICS
              sta abs:V_laststat
;;; Doors, in the source's scan order.
              stz dp:L_SY
doorsRow:     stz dp:L_SX
doorsCell:    jsr abs:.word0 (planeIndex)
              lda abs:MAP0,y
              and ##255
              cmp ##90
              bcc noDoorHere
              cmp ##102
              bcs noDoorHere
              jsr abs:.word0 (SpawnDoor)
noDoorHere:   jsr abs:.word0 (nextCell)
              bcc doorsCell
#ifdef WOLF_SPEAR
              jsr abs:.word0 (spearAmbushAreas)
#endif
;;; ScanInfoPlane.
              stz dp:L_SY
infoRow:      stz dp:L_SX
infoCell:     jsr abs:.word0 (planeIndex)
              lda abs:MAP1,y
              and ##255
              beq infoNext
              jsr abs:.word0 (spawnInfo)
infoNext:     jsr abs:.word0 (nextCell)
              bcc infoCell
;;; Take out the ambush markers.
              stz dp:L_SY
ambushRow:    stz dp:L_SX
ambushCell:   jsr abs:.word0 (planeIndex)
#ifdef WOLF_SPEAR
              tyx
              lda long:RAW0_ADDRESS,x
#else
              lda abs:MAP0,y
#endif
              and ##255
              cmp ##106
              bne ambushNext
              jsr abs:.word0 (cellIndex)
              sep #0x20
              lda #0
              sta abs:TILEMAP,x
              rep #0x20
              txa
              asl a
              tax
              lda abs:ACTORAT,x
              cmp ##106
              bne ambushArea
              stz abs:ACTORAT,x
ambushArea:
#ifndef WOLF_SPEAR
              lda ##106
              jsr abs:.word0 (ambushNeighbors)
              sep #0x20
              sta abs:MAP0,y
              rep #0x20
#endif
ambushNext:   jsr abs:.word0 (nextCell)
              bcc ambushCell
#ifdef WOLF_SPEAR
              jsr abs:.word0 (spearDoorAreas)
#endif
              jsr abs:.word0 (gsSnapLevel)
              pld
              plb
              plp
              rtl

;;; The fresh floor is already in bank $28. Record the words a save
;;; cannot rebuild from the raw planes into $010000. A list that does not
;;; fit leaves gsBaseOk clear, and the floor cannot be saved; on the 60
;;; floors they fit (tools/check_save_bound.py).
gsSnapLevel:  jsl long:gsCapture
              rts

#ifdef WOLF_SPEAR
;;; Resolve connected ambush cells before actors take their area numbers.
;;; The raw plane retains the ambush flag. Door chains are resolved between
;;; passes because either kind of cell can inherit an area from the other.
spearAmbushAreas:
              jsr abs:.word0 (spearDoorAreas)
              stz dp:L_ARG
              ldy ##4095
spearAmbushCell:
              lda abs:MAP0,y
              and ##255
              cmp ##106
              bne spearAmbushNext
              jsr abs:.word0 (ambushNeighbors)
              cmp ##106
              beq spearAmbushNext
              sep #0x20
              sta abs:MAP0,y
              rep #0x20
              inc dp:L_ARG
spearAmbushNext:
              dey
              bpl spearAmbushCell
              lda dp:L_ARG
              bne spearAmbushAreas
              rts

;;; A door against a wall inherits the area on its open side. Repeated passes
;;; resolve consecutive doors; call again as ambush areas become available.
;;; Valid source areas keep their original value.
spearDoorAreas:
              lda abs:V_doornum
              bne spearDoorsPresent
              rts
spearDoorsPresent:
              sta dp:L_ARG
spearDoorsPass:
              stz dp:L_V
              stz dp:L_I
spearDoorNext:
              lda dp:L_I
              cmp abs:V_doornum
              bcs spearDoorsPassDone
              asl a
              tax
              lda abs:DOORTILE,x
              sta dp:L_T
              and ##63
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:L_U
              lda dp:L_T
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              ora dp:L_U
              tay
              lda abs:MAP0,y
              jsr abs:.word0 (spearDoorArea)
              bcc spearDoorSkip
              lda abs:DOORVERT,x
              beq spearDoorHorizontal
              lda abs:MAP0-1,y
              jsr abs:.word0 (spearDoorArea)
              bcc spearDoorStore
              lda abs:MAP0+1,y
              jsr abs:.word0 (spearDoorArea)
              bra spearDoorChecked
spearDoorHorizontal:
              lda abs:MAP0-64,y
              jsr abs:.word0 (spearDoorArea)
              bcc spearDoorStore
              lda abs:MAP0+64,y
              jsr abs:.word0 (spearDoorArea)
spearDoorChecked:
              bcs spearDoorSkip
spearDoorStore:
              clc
              adc ##107
              sep #0x20
              sta abs:MAP0,y
              rep #0x20
              inc dp:L_V
spearDoorSkip: inc dp:L_I
              bra spearDoorNext
spearDoorsPassDone:
              lda dp:L_V
              beq spearDoorsDone
              dec dp:L_ARG
              bne spearDoorsPass
spearDoorsDone:rts
;;; Return an area index and carry clear only for a valid area tile.
spearDoorArea:and ##255
              sec
              sbc ##107
              cmp ##37
              rts
#endif

;;; Y = y*64+x of (L_X, L_Y).
planeIndex:   lda dp:L_SY
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora dp:L_SX
              tay
              rts
;;; X = x*64+y of (L_X, L_Y).
cellIndex:    lda dp:L_SX
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora dp:L_SY
              tax
              rts
;;; Advance x, then y. Carry set after the last cell.
nextCell:     inc dp:L_SX
              lda dp:L_SX
              cmp ##64
              bcc cellLeft
              stz dp:L_SX
              inc dp:L_SY
              lda dp:L_SY
              and ##3
              bne setupProgressRow
              jsl long:Progress2
setupProgressRow:
              lda dp:L_SY
              cmp ##64
              rts
cellLeft:     clc
              rts

;;; The first area of (x+1), (y-1), (y+1), (x-1) with the last one winning,
;;; as SpawnStand and SetupGameLevel test them. A = the value kept when none
;;; is an area. Y = y*64+x and is kept.
ambushNeighbors:
              sta dp:L_T
              lda abs:MAP0+1,y
              jsr abs:.word0 (ambushTake)
              lda abs:MAP0-64,y
              jsr abs:.word0 (ambushTake)
              lda abs:MAP0+64,y
              jsr abs:.word0 (ambushTake)
              lda abs:MAP0-1,y
              jsr abs:.word0 (ambushTake)
              lda dp:L_T
              rts
ambushTake:   and ##255
#ifdef WOLF_SPEAR
              cmp ##144
              bcs ambushKeep
#endif
              cmp ##107
              bcc ambushKeep
              sta dp:L_T
ambushKeep:   rts

;;; SpawnDoor: A = door tile code at (L_X, L_Y), Y = its plane index.
SpawnDoor:    sta dp:L_T
              lda abs:V_doornum
              cmp ##64
              bcc doorRoom
              brk                         ; 64+ doors on level
doorRoom:     asl a
              tax
              stz abs:DOORPOS,x
              lda ##1                     ; dr_closed
              sta abs:DOORACT,x
              stz abs:DOORTICS,x
              lda dp:L_T
              sec
              sbc ##90
              lsr a
              sta abs:DOORLOCK,x
              lda ##0
              rol a
              eor ##1                     ; even codes are vertical
              sta abs:DOORVERT,x
              phx
              jsr abs:.word0 (cellIndex)
              txa
              plx
              sta abs:DOORTILE,x
              tax
              lda abs:V_doornum
              ora ##0x80
              sep #0x20
              sta abs:TILEMAP,x
              rep #0x20
              pha
              txa
              asl a
              tax
              pla
              sta abs:ACTORAT,x
              lda abs:V_doornum
              asl a
              tax
              lda abs:DOORVERT,x
              beq doorHorizontal
              lda abs:MAP0-1,y            ; the door takes its west area
              sep #0x20
              sta abs:MAP0,y
              rep #0x20
              jsr abs:.word0 (cellIndex)
              dex
              jsr abs:.word0 (doorSide)
              inx
              inx
              jsr abs:.word0 (doorSide)
              bra doorSpawned
doorHorizontal:
              lda abs:MAP0-64,y           ; and a horizontal one its north area
              sep #0x20
              sta abs:MAP0,y
              rep #0x20
              jsr abs:.word0 (cellIndex)
              txa
              sec
              sbc ##64
              tax
              jsr abs:.word0 (doorSide)
              txa
              clc
              adc ##128
              tax
              jsr abs:.word0 (doorSide)
doorSpawned:  inc abs:V_doornum
              rts
doorSide:     sep #0x20
              lda abs:TILEMAP,x
              ora #0x40
              sta abs:TILEMAP,x
              rep #0x20
              rts

;;; ScanInfoPlane for one code A at (L_X, L_Y).
spawnInfo:
              jsr abs:.word0 (RegisteredInfo)
              bcc ordinaryInfo
              rts
ordinaryInfo:
              cmp ##19
              bcs lsetup_far350
              jmp abs:.word0 (infoDone)
lsetup_far350:
              cmp ##23
              bcs notPlayer
              sec
              sbc ##19
              jmp abs:.word0 (SpawnPlayer)
notPlayer:    cmp ##75
              bcs notStatic
              sec
              sbc ##23
              jmp abs:.word0 (SpawnStatic)
notStatic:    cmp ##98
              bne notSecret
              inc abs:V_secrettotal
              rts
notSecret:    cmp ##124
              bne notDeadGuard
              jmp abs:.word0 (SpawnDeadGuard)
notDeadGuard:
#ifndef WOLF_SPEAR
               cmp ##214
              bne enemyCodes
              jmp abs:.word0 (SpawnBoss)
#endif
enemyCodes:   sta dp:L_T
              ldx ##0
enemyGroup:   lda long:enemyBases,x
              beq infoDone
              sta dp:L_U
              lda dp:L_T                  ; hard: base+72, medium: base+36, any: base
              sec
              sbc dp:L_U
              cmp ##72
              bcc tryMedium
              sbc ##72
              cmp ##4
              bcs nextGroup
              ldy abs:V_difficulty
              cpy ##3
              bcc infoDone
              bra enemyFound
tryMedium:    cmp ##36
              bcc tryEasy
              sbc ##36
              cmp ##4
              bcs nextGroup
              ldy abs:V_difficulty
              cpy ##2
              bcc infoDone
              bra enemyFound
tryEasy:      cmp ##4
              bcc enemyFound
nextGroup:    inx
              inx
              inx
              inx
              bra enemyGroup
enemyFound:   sta dp:L_ARG                ; direction 0..3
              lda long:enemyBases+2,x     ; which | 0x100 for a patrol
              bit ##0x100
              bne spawnPatrolNow
              jmp abs:.word0 (SpawnStand)
spawnPatrolNow:
              and ##255
              jmp abs:.word0 (SpawnPatrol)
infoDone:     rts
;;; Info plane bases with en_* (0x100 marks SpawnPatrol). Officers and
;;; mutants never appear on these floors.
enemyBases:   .word 108,0, 112,0x100, 126,2, 130,0x102, 134,3, 138,0x103
              .word 116,1, 120,0x101
              .word 0

;;; SpawnNewObj: L_X, L_Y, A = state. X = the new actor.
SpawnNewObj:  pha
              jsr abs:.word0 (GetNewActor)
              pla
              sta abs:O_STATE,x
              tay
              lda abs:ST_TICS,y
              beq noRoll
              cmp ##20
              beq roll20
              sta dp:L_T
              jsr abs:.word0 (Rnd)
rollGeneral:  cmp dp:L_T
              bcc noRoll
              sbc dp:L_T
              bra rollGeneral
roll20:       jsr abs:.word0 (Rnd)
              tay
              lda abs:MOD20,y
              and ##255
noRoll:       sta abs:O_TICS,x
              lda dp:L_SX
              sta abs:O_TILEX,x
              sta abs:O_X+2,x
              lda dp:L_SY
              sta abs:O_TILEY,x
              sta abs:O_Y+2,x
              lda ##0x8000
              sta abs:O_X,x
              sta abs:O_Y,x
              lda ##NODIR
              sta abs:O_DIR,x
              lda ##0xffff
              sta abs:O_MARKED,x
              jsr abs:.word0 (CellOfX)
              txa
              sta abs:ACTORAT,y
              jsr abs:.word0 (planeIndex)
              lda abs:MAP0,y
              sec
              sbc ##107
              and ##255
              sta abs:O_AREA,x
              rts

;;; SpawnStand: A = which, L_ARG = direction.
SpawnStand:   sta dp:L_W
              cmp ##3
              bcc standSpawn
              cmp ##8
              beq standSpawn
              brk                         ; SpawnStand(en_dog) spawns nothing in the source
standSpawn:   asl a
              tax
              lda long:standStates,x
              jsr abs:.word0 (SpawnNewObj)
              lda ##SPDPATROL
              sta abs:O_SPEED,x
              inc abs:V_killtotal
              jsr abs:.word0 (planeIndex)
#ifdef WOLF_SPEAR
              phx
              tyx
              lda long:RAW0_ADDRESS,x
              plx
#else
              lda abs:MAP0,y
#endif
              and ##255
              cmp ##106
              bne standKept
              phx
              jsr abs:.word0 (cellIndex)
              sep #0x20
              lda #0
              sta abs:TILEMAP,x
              rep #0x20
              plx
#ifdef WOLF_SPEAR
              lda abs:MAP0,y
              and ##255
#else
              lda ##0xffff
              jsr abs:.word0 (ambushNeighbors)
              cmp ##0xffff
              bne ambushFound
              brk                         ; an ambush tile without a floor neighbor
#endif
ambushFound:  sep #0x20
              sta abs:MAP0,y
              rep #0x20
              sec
              sbc ##107
              and ##255
              sta abs:O_AREA,x
              lda abs:O_FLAGS,x
              ora ##FL_AMBUSH
              sta abs:O_FLAGS,x
standKept:    lda dp:L_W
              jmp abs:.word0 (enemyCommon)
standStates:  .word s_grdstand, s_ofcstand, s_ssstand, 0, 0, 0, 0, 0, s_mutstand

;;; enemyCommon: A = which, X = actor: class, hit points, direction.
enemyCommon:  sta dp:L_W
              clc
              adc ##GUARDOBJ
              sta abs:O_CLASS,x
              jsr abs:.word0 (ClassHitPoints)
              lda dp:L_ARG
              asl a
              sta abs:O_DIR,x
              lda abs:O_FLAGS,x
              ora ##FL_SHOOTABLE
              sta abs:O_FLAGS,x
              rts
;;; starthitpoints[difficulty][guard, officer, ss, dog]
startHitPoints:.word 25,50,100,1, 25,50,100,1, 25,50,100,1, 25,50,100,1

;;; SpawnPatrol: A = which, L_ARG = direction.
SpawnPatrol:  sta dp:L_W
              asl a
              tax
              lda long:patrolStates,x
              jsr abs:.word0 (SpawnNewObj)
              lda ##SPDPATROL
              ldy dp:L_W
              cpy ##3
              bne patrolSpeed
              lda ##SPDDOG
patrolSpeed:  sta abs:O_SPEED,x
              inc abs:V_killtotal
              lda dp:L_W
              jsr abs:.word0 (enemyCommon)
              stz abs:O_DIST,x
              lda ##1
              sta abs:O_DIST+2,x
              sta abs:O_ACTIVE,x
              jsr abs:.word0 (CellOfX)
              lda ##0
              sta abs:ACTORAT,y           ; don't use the original spot
              lda dp:L_ARG
              asl a
              tay
              phx
              tyx
              lda long:patrolSteps+8,x
              sta dp:L_T
              lda long:patrolSteps,x
              plx
              clc
              adc abs:O_TILEX,x
              sta abs:O_TILEX,x
              lda dp:L_T
              clc
              adc abs:O_TILEY,x
              sta abs:O_TILEY,x
              jsr abs:.word0 (CellOfX)
              txa
              sta abs:ACTORAT,y
              rts
patrolStates: .word s_grdpath1, s_ofcpath1, s_sspath1, s_dogpath1, 0, 0, 0, 0, s_mutpath1
patrolSteps:  .word 1, 0, 0xffff, 0
              .word 0, 0xffff, 0, 1

SpawnDeadGuard:
              lda ##s_grddie4
              jsr abs:.word0 (SpawnNewObj)
              lda ##INERTOBJ
              sta abs:O_CLASS,x
              rts

#ifndef WOLF_SPEAR
SpawnBoss:    lda ##s_bossstand
              jsr abs:.word0 (SpawnNewObj)
              lda ##SPDPATROL
              sta abs:O_SPEED,x
              lda ##BOSSOBJ
              sta abs:O_CLASS,x
              lda abs:V_difficulty
              asl a
              phx
              tax
              lda long:bossHitPoints,x
              plx
              sta abs:O_HP,x
              lda ##SOUTH
              sta abs:O_DIR,x
              lda abs:O_FLAGS,x
              ora ##FL_SHOOTABLE|FL_AMBUSH
              sta abs:O_FLAGS,x
              inc abs:V_killtotal
              rts
bossHitPoints:.word 850, 950, 1050, 1200

#endif
;;; SpawnPlayer: A = direction (0 north .. 3 west).
SpawnPlayer:  sta dp:L_T
              ldx ##PLAYER
              lda ##PLAYEROBJ
              sta abs:O_CLASS,x
              lda ##1
              sta abs:O_ACTIVE,x
              lda dp:L_SX
              sta abs:O_TILEX,x
              sta abs:O_X+2,x
              lda dp:L_SY
              sta abs:O_TILEY,x
              sta abs:O_Y+2,x
              jsr abs:.word0 (planeIndex)
              lda abs:MAP0,y
              and ##255
              sta abs:O_AREA,x
              lda ##0x8000
              sta abs:O_X,x
              sta abs:O_Y,x
              lda ##s_player
              sta abs:O_STATE,x
              lda ##1                     ; (1-dir)*90
              sec
              sbc dp:L_T
              tay
              lda ##0
playerAngle:  cpy ##0
              beq playerAngleSet
              bmi playerAngleLow
              clc
              adc ##90
              dey
              bra playerAngle
playerAngleLow:
              sec
              sbc ##90
              iny
              bra playerAngle
playerAngleSet:
              cmp ##0x8000
              bcc playerAngleKept
              adc ##359                   ; carry set: +360
playerAngleKept:
              sta abs:O_ANGLE,x
              lda ##FL_NEVERMARK
              sta abs:O_FLAGS,x
              stz dp:L_SPEED
              stz dp:L_SPEED+2
              stz dp:L_ANGLE
              jsr abs:.word0 (Thrust)
              ldx ##62
clearByPlayer:stz abs:AREABYPLAYER,x
              dex
              dex
              bpl clearByPlayer
              lda abs:PLAYER+O_AREA
              tax
              sep #0x20
              lda #1
              sta abs:AREABYPLAYER,x
              rep #0x20
              rts

;;; SpawnStatic: A = statinfo type.
SpawnStatic:  sta dp:L_T
              asl a
              asl a
              tay
              ldx abs:V_laststat
              jsr abs:.word0 (cellTo)
              sta abs:0,x
              phx
              lda abs:0,x
              tax
              lda abs:STATINFO,y
              jsl long:StaticSpriteVariant
              plx
              sta abs:2,x
              stz abs:4,x
              lda abs:STATINFO+2,y
              cmp ##1                     ; block
              bne notBlock
              phx
              jsr abs:.word0 (cellIndex)
              txa
              asl a
              tax
              lda ##1
              sta abs:ACTORAT,x
              plx
              bra staticDone
notBlock:     cmp ##0
              beq staticDone
              sta abs:6,x
              lda ##FL_BONUS
              sta abs:4,x
              lda abs:6,x
              cmp ##9                     ; cross, chalice, bible, crown
              bcc staticDone
              cmp ##13
              bcc treasure
              cmp ##18                    ; full heal
              bne staticDone
treasure:     inc abs:V_treasuretotal
staticDone:   txa
              clc
              adc ##8
              sta abs:V_laststat
              cmp ##STATICS+8*MAXSTATS
              bcc staticRoom
              brk                         ; too many static objects
staticRoom:   rts
cellTo:       phx
              jsr abs:.word0 (cellIndex)
              txa
              plx
              rts

;;; JSL after the renderer's map exists: object markers for its stamps.
LogicMarkObjects:
              php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              jsr abs:.word0 (ClearStaticIndex)
              ldx ##STATICS
markStatics:  cpx abs:V_laststat
              bcs markActors
              lda abs:2,x
              cmp ##0xffff
              beq markStaticNext
              jsr abs:.word0 (AddStaticIndex)
              lda abs:0,x
              jsr abs:.word0 (MarkStaticCellL)
markStaticNext:
              txa
              clc
              adc ##8
              tax
              bra markStatics
markActors:   ldx abs:PLAYER+O_NEXT
              beq marksDone
markActor:    lda abs:O_X+2,x
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:O_Y+2,x
              sta abs:O_MARKED,x
              lda abs:O_NEXT,x
              tax
              bne markActor
marksDone:    pld
              plb
              plp
              rtl

;;; The death turn renders a stopped world, so it restores actor ray marks once.
LogicMarkActorRays:
              php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              ldx abs:PLAYER+O_NEXT
              beq marksDone
markDeathActor:
              lda abs:O_MARKED,x
              jsr abs:.word0 (MarkRayCellL)
              lda abs:O_NEXT,x
              tax
              bne markDeathActor
              jmp abs:.word0 (marksDone)

;;; A = static shape, X = cell (x*64+y); 16-bit registers. X/Y/DB kept.
;;; Coordinate parity selects a companion header only during floor setup or
;;; save reconstruction. Both headers show the original art when disabled.
StaticSpriteVariant:
              cmp ##SPR_MIRROR_SOURCE
              bne variantDone
              pha
              txa
              pha
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              eor 1,s
              and ##1
              bne variantMirror
              pla
              pla
variantDone:  rtl
variantMirror:
              pla
              pla
              lda ##SPR_MIRROR_SHAPE
              rtl
