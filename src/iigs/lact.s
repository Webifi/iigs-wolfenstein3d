;;; Door and pushwall state, area connectivity, static items, and enemy
;;; movement/combat. LogicFrame advances these systems using V_tics;
;;; renderer-visible tile and actor changes are published through the marks.
#include "memmap.inc"
#include "picture_config.inc"
#include "logic.inc"
#include "logic_dp.inc"
#include "logic_sounds.inc"
              .section logiccode, text, root, noreorder
              .public MoveDoors, MovePWalls, PushWall, OperateDoor, OpenDoor, CloseDoor
              .public ConnectAreas, PlaceItemType, StoreLogicTile, MarkActorCell, MarkActorCellTail
              .public T_Stand, T_Path, T_Chase, T_DogChase, T_Shoot, T_Bite, A_DeathScream, speedTickTest
              .public DamageActor, KillActor, FirstSighting, SightPlayer, TryWalk
              .public emptyMarkWord, openDoorWord
              .public MoveObj, SelectPathDir
              .extern Rnd, NewState, CellOfX, LogicSound, TakeDamage, GivePoints
              .extern LineCellChange
              .extern CheckLine, InRange64K
              .extern AddStaticIndex, RemoveStaticIndex
              .extern doorPosition, pwallPosition, wallDirty, MarkStaticCellL

              .extern ClassFirst, ClassPain, ClassKill, ClassScream, ClassShoot, RegisteredReaction
              .public firstSpeed, killed, sightDelay, sightDelayCurrent
              .public speedMove, moveFits, snapToTile, tileDistance
              .public SelectDodgeDir, SelectChaseDir, chaseAttempt
              .extern GhostContact, RegisteredShotSound
PLAYER        .equ OBJLIST
MINDIST       .equ 0x5800
FL_SHOOTABLE  .equ 1
FL_VISABLE    .equ 8
FL_ATTACKMODE .equ 16
FL_FIRSTATTACK .equ 32
FL_AMBUSH     .equ 64
FL_NONMARK    .equ 128
DR_OPEN       .equ 0
DR_CLOSED     .equ 1
DR_OPENING    .equ 2
DR_CLOSING    .equ 3
EAST          .equ 0
NORTHEAST     .equ 1
NORTH         .equ 2
NORTHWEST     .equ 3
WEST          .equ 4
SOUTHWEST     .equ 5
SOUTH         .equ 6
SOUTHEAST     .equ 7
NODIR         .equ 8
INERTOBJ      .equ 2
GUARDOBJ      .equ 3
SSOBJ         .equ 5
DOGOBJ        .equ 6
BOSSOBJ       .equ 7
EV_STATUS     .equ 1
RUNSPEED      .equ 6000

#if WOLF_PREPARED
              .extern RefreshWallRuns
#endif

;;; ------------------------------------------------------------- tiles
;;; StoreLogicTile: X = cell (x*64+y), A = the new tilemap byte. The
;;; renderer's map holds the wall without the door-side bit.
StoreLogicTile:
              jsr abs:.word0 (LineCellChange)
              sep #0x20
              sta abs:TILEMAP,x
              rep #0x20
              and ##255
              beq renderEmpty
              bit ##0x80
              bne renderSpecial
              and ##63
              bra renderTile
renderSpecial:bit ##0x40
              beq renderTile              ; a door keeps its number
              and ##63
              ora ##0xc0
renderTile:   sep #0x20
              sta long:MAP,x
              rep #0x20
              phx
              pha
              txa
              asl a
              tax
              pla
              sta long:TILE_MIRROR,x
              plx
              bra tileStored
renderEmpty:  sep #0x20
              sta long:MAP,x
              lda long:OBJECT_MARKERS,x         ; an object marker keeps rays stamping
              rep #0x20
              and ##255
              beq noPersistentMarker
emptyMarkWord:lda ##0x8000
noPersistentMarker:
              phx
              pha
              txa
              asl a
              tax
              pla
              sta long:TILE_MIRROR,x
              plx
tileStored:
#if WOLF_PREPARED
              jsl long:RefreshWallRuns
#endif
              lda ##1
              sta dp:L_VISDIRTY
              sta long:wallDirty
              rts

;;; MarkActorCell: X = object; the renderer's sprite visibility cell follows
;;; its position. Y and X are kept.
MarkActorCell:lda abs:O_X+2,x
;;; World batches supply the final X tile after playing all safe movement tics.
MarkActorCellTail:
              xba
              lsr a
              lsr a
              ora abs:O_Y+2,x
              sta abs:O_MARKED,x
cellKept:     rts

;;; ------------------------------------------------------------- doors
;;; OpenDoor: A = door.
OpenDoor:     asl a
              tax
              lda abs:DOORACT,x
              bne doorNotOpen
              stz abs:DOORTICS,x          ; reset the open time
              rts
doorNotOpen:  cmp ##DR_CLOSED
              bne doorAlreadyActive
              jsr abs:.word0 (AddActiveDoor)
doorAlreadyActive:
              lda ##DR_OPENING
              sta abs:DOORACT,x
              rts

;;; Preserve source door order when several doors finish or make sounds together.
AddActiveDoor:
              phx
              phy
              txa
              ldx ##0
activeDoorFind:
              cmp long:ACTIVE_DOORS,x
              bcc activeDoorInsert
              beq activeDoorAdded
              inx
              inx
              bra activeDoorFind
activeDoorInsert:
              pha
              lda long:ACTIVE_DOORS,x
              tay
              pla
              sta long:ACTIVE_DOORS,x
              tya
              inx
              inx
              cmp ##0xffff
              bne activeDoorInsert
              sta long:ACTIVE_DOORS,x
activeDoorAdded:
              ply
              plx
              rts

RemoveActiveDoor:
              ldx dp:L_DCUR
activeDoorShift:
              lda long:ACTIVE_DOORS+2,x
              sta long:ACTIVE_DOORS,x
              inx
              inx
              cmp ##0xffff
              bne activeDoorShift
              dec dp:L_DCUR             ; doorNext must visit the shifted successor
              dec dp:L_DCUR
              rts

;;; CloseDoor: A = door.
CloseDoor:    sta dp:L_DOOR
              asl a
              tax
              lda abs:DOORTILE,x
              sta dp:L_SPOT
              asl a
              tay
              lda abs:ACTORAT,y
              beq closeEmpty
              rts
closeEmpty:   lda dp:L_SPOT
              and ##63
              sta dp:L_Y                  ; tiley
              lda dp:L_SPOT
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:L_X                  ; tilex
              cmp abs:PLAYER+O_TILEX
              bne playerOff
              lda dp:L_Y
              cmp abs:PLAYER+O_TILEY
              bne playerOff
              rts
playerOff:    lda abs:DOORVERT,x
              beq closeHorizontal
              lda abs:PLAYER+O_TILEY
              cmp dp:L_Y
              bne vertNeighbors
              lda abs:PLAYER+O_X
              clc
              adc ##MINDIST
              lda abs:PLAYER+O_X+2
              adc ##0
              cmp dp:L_X
              beq closeBlocked
              lda abs:PLAYER+O_X
              sec
              sbc ##MINDIST
              lda abs:PLAYER+O_X+2
              sbc ##0
              cmp dp:L_X
              beq closeBlocked
vertNeighbors:lda dp:L_SPOT
              sec
              sbc ##64
              asl a
              tay
              lda abs:ACTORAT,y
              cmp ##256
              bcc vertRight
              tay
              lda abs:O_X,y
              clc
              adc ##MINDIST
              lda abs:O_X+2,y
              adc ##0
              cmp dp:L_X
              beq closeBlocked
vertRight:    lda dp:L_SPOT
              clc
              adc ##64
              asl a
              tay
              lda abs:ACTORAT,y
              cmp ##256
              bcc closeAllowed
              tay
              lda abs:O_X,y
              sec
              sbc ##MINDIST
              lda abs:O_X+2,y
              sbc ##0
              cmp dp:L_X
              beq closeBlocked
              bra closeAllowed
closeBlocked: rts
closeHorizontal:
              lda abs:PLAYER+O_TILEX
              cmp dp:L_X
              bne horizNeighbors
              lda abs:PLAYER+O_Y
              clc
              adc ##MINDIST
              lda abs:PLAYER+O_Y+2
              adc ##0
              cmp dp:L_Y
              beq closeBlocked
              lda abs:PLAYER+O_Y
              sec
              sbc ##MINDIST
              lda abs:PLAYER+O_Y+2
              sbc ##0
              cmp dp:L_Y
              beq closeBlocked
horizNeighbors:
              lda dp:L_SPOT
              dec a
              asl a
              tay
              lda abs:ACTORAT,y
              cmp ##256
              bcc horizBelow
              tay
              lda abs:O_Y,y
              clc
              adc ##MINDIST
              lda abs:O_Y+2,y
              adc ##0
              cmp dp:L_Y
              beq closeBlocked
horizBelow:   lda dp:L_SPOT
              inc a
              asl a
              tay
              lda abs:ACTORAT,y
              cmp ##256
              bcc closeAllowed
              tay
              lda abs:O_Y,y
              sec
              sbc ##MINDIST
              lda abs:O_Y+2,y
              sbc ##0
              cmp dp:L_Y
              beq closeBlocked
closeAllowed: ldx dp:L_SPOT
              jsr abs:.word0 (areaOfCell)
              tay
              lda abs:AREABYPLAYER,y
              and ##255
              beq closeQuiet
              lda ##CLOSEDOORSND
              jsr abs:.word0 (LogicSound)
closeQuiet:   lda dp:L_DOOR
              asl a
              tax
              lda ##DR_CLOSING
              sta abs:DOORACT,x
              lda dp:L_SPOT
              asl a
              tay
              lda dp:L_DOOR
              ora ##0x80
              sta abs:ACTORAT,y
              phx
              tyx
              sta long:TILE_MIRROR,x
              plx
              rts

;;; A = map0[cell] - AREATILE for X = x*64+y (the area plane is y*64+x).
areaOfCell:   txa
              and ##63
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:L_T
              txa
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              ora dp:L_T
              tax
              lda abs:MAP0,x
              sec
              sbc ##107
              and ##255
              rts

;;; OperateDoor: A = door.
OperateDoor:  sta dp:L_DOOR
              asl a
              tax
              lda abs:DOORLOCK,x
              beq doorUnlocked
              cmp ##5
              bcs doorUnlocked
              dec a
              tay
              lda ##1
lockBit:      dey
              bmi lockReady
              asl a
              bra lockBit
lockReady:    and abs:V_keys
              bne doorUnlocked
              lda ##NOWAYSND
              jmp abs:.word0 (LogicSound)
doorUnlocked: lda abs:DOORACT,x
              cmp ##DR_CLOSED
              beq operateOpen
              cmp ##DR_CLOSING
              beq operateOpen
              lda dp:L_DOOR
              jmp abs:.word0 (CloseDoor)
operateOpen:  lda dp:L_DOOR
              jmp abs:.word0 (OpenDoor)

MoveDoors:    lda abs:V_victoryflag
              beq doorsRun
              rts
doorsRun:     stz dp:L_DCUR
doorLoop:     ldx dp:L_DCUR
              lda long:ACTIVE_DOORS,x
              cmp ##0xffff
              bne doorStep
              rts
doorStep:     tax
              lsr a
              sta dp:L_I
              lda abs:DOORACT,x
              beq doorOpenTick
              cmp ##DR_OPENING
              beq doorOpening
              cmp ##DR_CLOSING
              bne doorNext
              jmp abs:.word0 (doorClosing)
doorNext:     inc dp:L_DCUR
              inc dp:L_DCUR
              bra doorLoop
doorOpenTick: lda abs:DOORTICS,x
              clc
              adc abs:V_tics
              sta abs:DOORTICS,x
              cmp ##300
              bcc doorNext
              lda dp:L_I
              jsr abs:.word0 (CloseDoor)
              bra doorNext
doorOpening:  lda abs:DOORPOS,x
              bne doorSlideOpen
              jsr abs:.word0 (doorAreas)  ; just starting: connect the areas
              jsr abs:.word0 (connectPair)
              inc a
              jsr abs:.word0 (setPair)
              jsr abs:.word0 (ConnectAreas)
              ldy dp:L_U
              lda abs:AREABYPLAYER,y
              and ##255
              beq doorOpenQuiet
              lda ##OPENDOORSND
              jsr abs:.word0 (LogicSound)
doorOpenQuiet:lda dp:L_I
              asl a
              tax
doorSlideOpen:lda abs:V_tics
              xba
              asl a
              asl a                       ; tics<<10
              clc
              adc abs:DOORPOS,x
              bcs doorFullyOpen
              cmp ##0xffff
              bcc doorStorePos
doorFullyOpen:lda ##DR_OPEN
              sta abs:DOORACT,x
              stz abs:DOORTICS,x
              lda abs:DOORTILE,x
              asl a
              tay
              lda ##0
              sta abs:ACTORAT,y
              phx
              tyx
openDoorWord: lda ##0x8000              ; fully open: stamp visibility, skip door math
              sta long:TILE_MIRROR,x
              plx
              lda ##0xffff
doorStorePos: sta abs:DOORPOS,x
              inc dp:L_VISDIRTY
              xba
              and ##255
              sta long:doorPosition,x     ; the renderer's 0..255 scale
              lda abs:DOORTILE,x
              asl a
              tax
              lda long:VIS_STAMPS,x
              cmp long:GAME_DP+0x5a           ; cached renderer view's VISSTAMP
              bne doorUnseen
              lda ##1
              sta long:wallDirty
doorUnseen:  jmp abs:.word0 (doorNext)
doorClosing:  lda abs:DOORTILE,x
              sta dp:L_SPOT
              asl a
              tay
              lda dp:L_I
              ora ##0x80
              cmp abs:ACTORAT,y
              bne doorReopen
              lda dp:L_SPOT
              and ##63
              cmp abs:PLAYER+O_TILEY
              bne doorSlideShut
              lda dp:L_SPOT
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              cmp abs:PLAYER+O_TILEX
              bne doorSlideShut
doorReopen:   lda dp:L_I
              jsr abs:.word0 (OpenDoor)
              jmp abs:.word0 (doorNext)
doorSlideShut:lda abs:V_tics
              xba
              asl a
              asl a
              sta dp:L_T
              lda abs:DOORPOS,x
              sec
              sbc dp:L_T
              beq doorShut
              bcs doorStorePos
doorShut:     lda ##DR_CLOSED
              sta abs:DOORACT,x
              jsr abs:.word0 (RemoveActiveDoor)
              jsr abs:.word0 (doorAreas)
              jsr abs:.word0 (connectPair)
              dec a
              jsr abs:.word0 (setPair)
              jsr abs:.word0 (ConnectAreas)
              lda dp:L_I
              asl a
              tax
              lda ##0
              jmp abs:.word0 (doorStorePos)

;;; L_U, L_V = area1, area2 of door L_I (vertical: east then west).
doorAreas:    lda dp:L_I
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
              sta dp:L_W
              lda dp:L_T
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              ora dp:L_W                  ; y*64+x
              tay
              lda abs:DOORVERT,x
              beq horizontalAreas
              lda abs:MAP0+1,y
              jsr abs:.word0 (areaByte)
              sta dp:L_U
              lda abs:MAP0-1,y
              jsr abs:.word0 (areaByte)
              sta dp:L_V
#ifdef WOLF_SPEAR
              bra spearDoorPair
#else
              rts
#endif
horizontalAreas:
              lda abs:MAP0-64,y
              jsr abs:.word0 (areaByte)
              sta dp:L_U
              lda abs:MAP0+64,y
              jsr abs:.word0 (areaByte)
              sta dp:L_V
#ifdef WOLF_SPEAR
;;; A wall or unmoved pushwall is not an area. Such a door connects its
;;; valid side to itself until the wall moves; never index beyond 37 areas.
spearDoorPair:lda dp:L_U
              cmp ##37
              bcc spearDoorFirstValid
              lda dp:L_V
              cmp ##37
              bcc spearDoorFirstFromSecond
              lda ##0
              sta dp:L_V
spearDoorFirstFromSecond:
              sta dp:L_U
spearDoorFirstValid:
              lda dp:L_V
              cmp ##37
              bcc spearDoorPairDone
              lda dp:L_U
              sta dp:L_V
spearDoorPairDone:
#endif
              rts
areaByte:     sec
              sbc ##107
              and ##255
              rts
;;; A = areaconnect[area1][area2]; Y = its offset.
connectPair:  lda dp:L_U
              jsr abs:.word0 (times37)
              clc
              adc dp:L_V
              tay
              lda abs:AREACONNECT,y
              and ##255
              rts
;;; Store A in both directions.
setPair:      sep #0x20
              sta abs:AREACONNECT,y
              rep #0x20
              pha
              lda dp:L_V
              jsr abs:.word0 (times37)
              clc
              adc dp:L_U
              tay
              pla
              sep #0x20
              sta abs:AREACONNECT,y
              rep #0x20
              rts
times37:      sta dp:L_W
              asl a
              asl a
              sta dp:L_T
              asl a
              asl a
              asl a
              clc
              adc dp:L_T
              adc dp:L_W                  ; 32a + 4a + a
              rts

;;; ConnectAreas: mark every area that reaches the player's area.
ConnectAreas: ldx ##36
              sep #0x20
              lda #0
clearAreas:   sta abs:AREABYPLAYER,x
              dex
              bpl clearAreas
              rep #0x20
              lda abs:PLAYER+O_AREA
              cmp ##37
              bcc connectStart
              brk                         ; areabyplayer outside its table
connectStart: tax
              sep #0x20
              lda #1
              sta abs:AREABYPLAYER,x
              txa
              sta abs:AREAQUEUE
              rep #0x20
              lda ##1
              sta dp:L_QHEAD
              stz dp:L_QUEUE
floodNext:    ldx dp:L_QUEUE
              cpx dp:L_QHEAD
              bcc floodArea
              rts
floodArea:    lda abs:AREAQUEUE,x
              and ##255
              inc dp:L_QUEUE
              jsr abs:.word0 (times37)
              tay
              ldx ##0
floodScan:    lda abs:AREACONNECT,y
              and ##255
              beq floodSkip
              lda abs:AREABYPLAYER,x
              and ##255
              bne floodSkip
              sep #0x20
              lda #1
              sta abs:AREABYPLAYER,x
              txa
              phx
              ldx dp:L_QHEAD
              sta abs:AREAQUEUE,x
              plx
              rep #0x20
              inc dp:L_QHEAD
floodSkip:    iny
              inx
              cpx ##37
              bcc floodScan
              bra floodNext

;;; ------------------------------------------------------------- push walls
;;; PushWall: L_X, L_Y = the tile, L_ARG = di_north/east/south/west.
PushWall:     lda abs:V_pwallstate
              beq pushFree
              rts
pushFree:     lda dp:L_X
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora dp:L_Y
              sta dp:L_SPOT
              tax
              lda abs:TILEMAP,x
              and ##255
              bne pushTile
              rts
pushTile:     sta dp:L_W                  ; oldtile
              lda dp:L_ARG
              asl a
              tax
              lda dp:L_SPOT
              clc
              adc long:pushSteps,x
              sta dp:L_T                  ; the destination cell
              asl a
              tax
              lda abs:ACTORAT,x
              beq pushOpen
              lda ##NOWAYSND
              jmp abs:.word0 (LogicSound)
pushOpen:     lda dp:L_W
              sta abs:ACTORAT,x
              ldx dp:L_T
              jsr abs:.word0 (StoreLogicTile)
              inc abs:V_secretcount
              lda dp:L_X
              sta abs:V_pwallx
              lda dp:L_Y
              sta abs:V_pwally
              lda dp:L_ARG
              sta abs:V_pwalldir
              lda ##1
              sta abs:V_pwallstate
              stz abs:V_pwallpos
              lda ##0
              sta long:pwallPosition
              ldx dp:L_SPOT
              lda abs:TILEMAP,x
              ora ##0xc0
              jsr abs:.word0 (StoreLogicTile)
              lda dp:L_Y
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora dp:L_X
              tax
              sep #0x20
              lda #0
              sta abs:MAP1,x
              rep #0x20
              lda ##EV_STATUS
              tsb abs:V_events
              lda ##PUSHWALLSND
              jmp abs:.word0 (LogicSound)
pushSteps:    .word 0xffff, 64, 1, 0xffc0    ; north, east, south, west in cells

MovePWalls:   lda abs:V_pwallstate
              bne pwallMoving
              rts
pwallMoving:  and ##0xff80
              sta dp:L_T                  ; oldblock*128
              lda abs:V_pwallstate
              clc
              adc abs:V_tics
              sta abs:V_pwallstate
              and ##0xff80
              cmp dp:L_T
              bne pwallBlock
              jmp abs:.word0 (pwallFraction)
pwallBlock:   lda abs:V_pwallx
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:V_pwally
              sta dp:L_SPOT
              tax
              lda abs:TILEMAP,x
              and ##63
              sta dp:L_W                  ; oldtile
              lda ##0
              jsr abs:.word0 (StoreLogicTile)
              lda dp:L_SPOT
              asl a
              tax
              stz abs:ACTORAT,x
              lda abs:V_pwally
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:V_pwallx
              tax
              lda abs:PLAYER+O_AREA
              clc
              adc ##107
              sep #0x20
              sta abs:MAP0,x
              rep #0x20
              lda abs:V_pwallstate
              cmp ##257
              bcc pwallFarther
              stz abs:V_pwallstate
              rts
pwallFarther: lda abs:V_pwalldir
              asl a
              sta dp:L_U
              tax
              lda dp:L_SPOT
              clc
              adc long:pushSteps,x
              sta dp:L_SPOT               ; the wall's new cell
              tax
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta abs:V_pwallx
              txa
              and ##63
              sta abs:V_pwally
              ldx dp:L_U
              lda dp:L_SPOT
              clc
              adc long:pushSteps,x
              sta dp:L_T                  ; and the cell beyond
              asl a
              tax
              lda abs:ACTORAT,x
              beq pwallGoes
              stz abs:V_pwallstate
              rts
pwallGoes:    lda dp:L_W
              sta abs:ACTORAT,x
              ldx dp:L_T
              jsr abs:.word0 (StoreLogicTile)
              lda dp:L_W
              ora ##0xc0
              ldx dp:L_SPOT
              jsr abs:.word0 (StoreLogicTile)
pwallFraction:lda abs:V_pwallstate
              lsr a
              and ##63
              sta abs:V_pwallpos
              asl a
              asl a
              sta long:pwallPosition      ; the renderer's 0..252 scale
              lda ##1
              sta dp:L_VISDIRTY
              sta long:wallDirty
              rts

;;; ------------------------------------------------------------- statics
;;; PlaceItemType: A = item type, L_X/L_Y = tile.
PlaceItemType:
              sta dp:L_T
              ldx ##0
findInfo:     lda abs:STATINFO+2,x
              cmp dp:L_T
              beq infoFound
              inx
              inx
              inx
              inx
#ifdef WOLF_SPEAR
              cpx ##SPEAR_STATIC_COUNT*4
#else
              cpx ##49*4
#endif
              bcc findInfo
              brk                         ; PlaceItemType: couldn't find type
infoFound:    lda abs:STATINFO,x
              sta dp:L_U                  ; shapenum
              ldx ##STATICS
findSpot:     cpx abs:V_laststat
              bcc spotTest
              cpx ##STATICS+8*MAXSTATS
              bcc spotAppend
              rts                         ; no free spots
spotAppend:   txa
              clc
              adc ##8
              sta abs:V_laststat
              bra spotPlace
spotTest:     lda abs:2,x
              cmp ##0xffff
              bne spotNext
              jsr abs:.word0 (RemoveStaticIndex)
              bra spotPlace
spotNext:     txa
              clc
              adc ##8
              tax
              bra findSpot
spotPlace:    lda dp:L_X
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora dp:L_Y
              sta abs:0,x
              lda dp:L_U
              sta abs:2,x
              lda ##2                     ; FL_BONUS
              sta abs:4,x
              lda dp:L_T
              sta abs:6,x
              jsr abs:.word0 (AddStaticIndex)
              lda abs:0,x
              jsr abs:.word0 (MarkStaticCellL)
              lda ##1
              sta abs:V_mapdirty
              rts

;;; ------------------------------------------------------------- actors
;;; TryWalk: X = object (L_OB). Carry set when the move starts.
TryWalk:      lda ##0xffff
              sta dp:L_DOOR
              ldx dp:L_OB
              lda abs:O_CLASS,x
              cmp ##INERTOBJ
              bne walkActor
              brk                         ; inert actors never walk on E1
walkActor:    lda abs:O_TILEX,x
              sta dp:L_X
              lda abs:O_TILEY,x
              sta dp:L_Y
              lda abs:O_DIR,x
              asl a
              tax
              .byte 0x7c                  ; JMP (walkDispatch,X)
              .word .word0 (walkDispatch)
walkDispatch: .word .word0 (walkEast), .word0 (walkNE), .word0 (walkNorth), .word0 (walkNW)
              .word .word0 (walkWest), .word0 (walkSW), .word0 (walkSouth), .word0 (walkSE)
              .word .word0 (walkNone)
walkNone:     clc
              rts
walkNorth:    lda ##0
              ldy ##0xffff
              jsr abs:.word0 (walkStraight)
              bcs lact_far829
              jmp abs:.word0 (walkBlocked)
lact_far829:
              ldx dp:L_OB
              dec abs:O_TILEY,x
              jmp abs:.word0 (walkDone)
walkSouth:    lda ##0
              ldy ##1
              jsr abs:.word0 (walkStraight)
              bcc walkBlocked
              ldx dp:L_OB
              inc abs:O_TILEY,x
              bra walkDone
walkEast:     lda ##1
              ldy ##0
              jsr abs:.word0 (walkStraight)
              bcc walkBlocked
              ldx dp:L_OB
              inc abs:O_TILEX,x
              bra walkDone
walkWest:     lda ##0xffff
              ldy ##0
              jsr abs:.word0 (walkStraight)
              bcc walkBlocked
              ldx dp:L_OB
              dec abs:O_TILEX,x
              bra walkDone
walkNE:       lda ##1
              ldy ##0xffff
              jsr abs:.word0 (walkDiagonal)
              bcc walkBlocked
              ldx dp:L_OB
              inc abs:O_TILEX,x
              dec abs:O_TILEY,x
              bra walkDone
walkSE:       lda ##1
              ldy ##1
              jsr abs:.word0 (walkDiagonal)
              bcc walkBlocked
              ldx dp:L_OB
              inc abs:O_TILEX,x
              inc abs:O_TILEY,x
              bra walkDone
walkSW:       lda ##0xffff
              ldy ##1
              jsr abs:.word0 (walkDiagonal)
              bcc walkBlocked
              ldx dp:L_OB
              dec abs:O_TILEX,x
              inc abs:O_TILEY,x
              bra walkDone
walkNW:       lda ##0xffff
              ldy ##0xffff
              jsr abs:.word0 (walkDiagonal)
              bcc walkBlocked
              ldx dp:L_OB
              dec abs:O_TILEX,x
              dec abs:O_TILEY,x
              bra walkDone
walkBlocked:  clc
              rts
walkDone:     lda dp:L_DOOR
              bmi walkArea
              jsr abs:.word0 (OpenDoor)
              ldx dp:L_OB
              lda dp:L_DOOR               ; distance = -doornum-1
              eor ##0xffff
              sta abs:O_DIST,x
              lda ##0xffff
              sta abs:O_DIST+2,x
              sec
              rts
walkArea:     lda abs:O_TILEY,x
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:O_TILEX,x
              tay
              lda abs:MAP0,y
              sec
              sbc ##107
              and ##255
              sta abs:O_AREA,x
              stz abs:O_DIST,x
              lda ##1
              sta abs:O_DIST+2,x          ; TILEGLOBAL
              sec
              rts

;;; A = dx, Y = dy of a cardinal step. Dogs test as a diagonal neighbor.
walkStraight: sta dp:L_T
              sty dp:L_U
              ldx dp:L_OB
              lda abs:O_CLASS,x
              cmp ##DOGOBJ
              beq walkNoDoor
#ifdef WOLF_SPEAR
              cmp ##21                    ; spectres do not operate doors
#else
              cmp ##15                    ; ghosts do not operate doors
#endif
              bne walkSide
walkNoDoor:
              lda dp:L_T
              ldy dp:L_U
              jmp abs:.word0 (checkDiag)
walkSide:     jsr abs:.word0 (neighbor)
              beq sideClear
              cmp ##128
              bcc sideBlocked
              cmp ##256
              bcs sideActor
              and ##63
              sta dp:L_DOOR
sideClear:    sec
              rts
sideActor:    tay
              lda abs:O_FLAGS,y
              bit ##FL_SHOOTABLE
              bne sideBlocked
              sec
              rts
sideBlocked:  clc
              rts

;;; A = dx, Y = dy: CHECKDIAG on (x+dx,y+dy), (x+dx,y), (x,y+dy).
walkDiagonal: sta dp:L_T
              sty dp:L_U
              jsr abs:.word0 (checkDiag)
              bcc diagBlocked
              lda dp:L_U
              pha
              stz dp:L_U
              lda dp:L_T
              ldy ##0
              jsr abs:.word0 (checkDiag)
              pla
              sta dp:L_U
              bcc diagBlocked
              lda ##0
              ldy dp:L_U
              jmp abs:.word0 (checkDiag)
diagBlocked:  rts
;;; A = dx, Y = dy: carry clear when actorat there blocks a diagonal move.
checkDiag:    sta dp:L_T
              sty dp:L_U
              jsr abs:.word0 (neighbor)
              beq diagClear
              cmp ##256
              bcc diagWall
              tay
              lda abs:O_FLAGS,y
              bit ##FL_SHOOTABLE
              bne diagWall
diagClear:    sec
              rts
diagWall:     clc
              rts
;;; A = actorat[L_X+L_T][L_Y+L_U], Z from A. X is kept.
neighbor:     lda dp:L_X
              clc
              adc dp:L_T
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:L_W
              lda dp:L_Y
              clc
              adc dp:L_U
              ora dp:L_W
              asl a
              tay
              lda abs:ACTORAT,y
              rts

;;; Callers clip runs below TILEGLOBAL; BJ jumps are at most 680*64.
;;; L_MOVE+2 is zero, direction is checked, X is the object.
MoveObjShort:
MoveObj:      lda abs:O_DIR,x
              asl a
              tax
              .byte 0x7c                  ; JMP (advanceDirection,X)
              .word .word0 (advanceDirection)
advanceDirection:.word .word0 (advanceE), .word0 (advanceNE), .word0 (advanceN), .word0 (advanceNW)
              .word .word0 (advanceW), .word0 (advanceSW), .word0 (advanceS), .word0 (advanceSE)
advanceE:     ldx dp:L_OB
              lda abs:O_X,x
              clc
              adc dp:L_MOVE
              sta abs:O_X,x
              bcc moveHighDone1
              inc abs:O_X+2,x
moveHighDone1:
              jmp abs:.word0 (moveCheck)
advanceNE:    ldx dp:L_OB
              lda abs:O_X,x
              clc
              adc dp:L_MOVE
              sta abs:O_X,x
              bcc moveHighDone2
              inc abs:O_X+2,x
moveHighDone2:
              lda abs:O_Y,x
              sec
              sbc dp:L_MOVE
              sta abs:O_Y,x
              bcs moveHighDone3
              dec abs:O_Y+2,x
moveHighDone3:
              jmp abs:.word0 (moveCheck)
advanceN:     ldx dp:L_OB
              lda abs:O_Y,x
              sec
              sbc dp:L_MOVE
              sta abs:O_Y,x
              bcs moveHighDone4
              dec abs:O_Y+2,x
moveHighDone4:
              jmp abs:.word0 (moveCheck)
advanceNW:    ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc dp:L_MOVE
              sta abs:O_X,x
              bcs moveHighDone5
              dec abs:O_X+2,x
moveHighDone5:
              lda abs:O_Y,x
              sec
              sbc dp:L_MOVE
              sta abs:O_Y,x
              bcs moveHighDone6
              dec abs:O_Y+2,x
moveHighDone6:
              jmp abs:.word0 (moveCheck)
advanceW:     ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc dp:L_MOVE
              sta abs:O_X,x
              bcs moveHighDone7
              dec abs:O_X+2,x
moveHighDone7:
              jmp abs:.word0 (moveCheck)
advanceSW:    ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc dp:L_MOVE
              sta abs:O_X,x
              bcs moveHighDone8
              dec abs:O_X+2,x
moveHighDone8:
              lda abs:O_Y,x
              clc
              adc dp:L_MOVE
              sta abs:O_Y,x
              bcc moveHighDone9
              inc abs:O_Y+2,x
moveHighDone9:
              jmp abs:.word0 (moveCheck)
advanceS:     ldx dp:L_OB
              lda abs:O_Y,x
              clc
              adc dp:L_MOVE
              sta abs:O_Y,x
              bcc moveHighDone10
              inc abs:O_Y+2,x
moveHighDone10:
              jmp abs:.word0 (moveCheck)
advanceSE:    ldx dp:L_OB
              lda abs:O_X,x
              clc
              adc dp:L_MOVE
              sta abs:O_X,x
              bcc moveHighDone11
              inc abs:O_X+2,x
moveHighDone11:
              lda abs:O_Y,x
              clc
              adc dp:L_MOVE
              sta abs:O_Y,x
              bcc moveHighDone12
              inc abs:O_Y+2,x
moveHighDone12:
              jmp abs:.word0 (moveCheck)

moveCheck:    ldy abs:O_AREA,x
              lda abs:AREABYPLAYER,y
              and ##255
              beq moveOk
              lda abs:O_X,x
              cmp abs:PLAYER+O_X
              lda abs:O_X+2,x
              sbc abs:PLAYER+O_X+2
              inc a
              cmp ##2
              bcc guardNearX
              bne moveOk
              lda abs:O_X,x
              cmp abs:PLAYER+O_X
              bne moveOk
guardNearX:
              lda abs:O_Y,x
              cmp abs:PLAYER+O_Y
              lda abs:O_Y+2,x
              sbc abs:PLAYER+O_Y+2
              inc a
              cmp ##2
              bcc guardNearY
              bne moveOk
              lda abs:O_Y,x
              cmp abs:PLAYER+O_Y
              bne moveOk
guardNearY:
              lda abs:O_CLASS,x
#ifdef WOLF_SPEAR
              cmp ##21
#else
              cmp ##15
#endif
              bne moveBack
              jsr abs:.word0 (GhostContact)
moveBack:
              lda abs:O_DIR,x             ; back up
              eor ##4
              asl a
              tax
              jmp abs:.word0 (applyMove)
moveOk:       lda abs:O_DIST,x
              sec
              sbc dp:L_MOVE
              sta abs:O_DIST,x
              bcs moveHighDone13
              dec abs:O_DIST+2,x
moveHighDone13:
              jmp abs:.word0 (MarkActorCell)
;;; X = opposite dir*2; undo movement after finding the player in its way.
applyMove:    .byte 0x7c                  ; JMP (moveDirection,X)
              .word .word0 (moveDirection)
moveDirection:.word .word0 (moveE), .word0 (moveNE), .word0 (moveN), .word0 (moveNW)
              .word .word0 (moveW), .word0 (moveSW), .word0 (moveS), .word0 (moveSE)
moveE:        ldx dp:L_OB
              lda abs:O_X,x
              clc
              adc dp:L_MOVE
              sta abs:O_X,x
              bcc moveHighDone14
              inc abs:O_X+2,x
moveHighDone14:
              rts
moveNE:       ldx dp:L_OB
              lda abs:O_X,x
              clc
              adc dp:L_MOVE
              sta abs:O_X,x
              bcc moveHighDone15
              inc abs:O_X+2,x
moveHighDone15:
              lda abs:O_Y,x
              sec
              sbc dp:L_MOVE
              sta abs:O_Y,x
              bcs moveHighDone16
              dec abs:O_Y+2,x
moveHighDone16:
              rts
moveN:        ldx dp:L_OB
              lda abs:O_Y,x
              sec
              sbc dp:L_MOVE
              sta abs:O_Y,x
              bcs moveHighDone17
              dec abs:O_Y+2,x
moveHighDone17:
              rts
moveNW:       ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc dp:L_MOVE
              sta abs:O_X,x
              bcs moveHighDone18
              dec abs:O_X+2,x
moveHighDone18:
              lda abs:O_Y,x
              sec
              sbc dp:L_MOVE
              sta abs:O_Y,x
              bcs moveHighDone19
              dec abs:O_Y+2,x
moveHighDone19:
              rts
moveW:        ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc dp:L_MOVE
              sta abs:O_X,x
              bcs moveHighDone20
              dec abs:O_X+2,x
moveHighDone20:
              rts
moveSW:       ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc dp:L_MOVE
              sta abs:O_X,x
              bcs moveHighDone21
              dec abs:O_X+2,x
moveHighDone21:
              lda abs:O_Y,x
              clc
              adc dp:L_MOVE
              sta abs:O_Y,x
              bcc moveHighDone22
              inc abs:O_Y+2,x
moveHighDone22:
              rts
moveS:        ldx dp:L_OB
              lda abs:O_Y,x
              clc
              adc dp:L_MOVE
              sta abs:O_Y,x
              bcc moveHighDone23
              inc abs:O_Y+2,x
moveHighDone23:
              rts
moveSE:       ldx dp:L_OB
              lda abs:O_X,x
              clc
              adc dp:L_MOVE
              sta abs:O_X,x
              bcc moveHighDone24
              inc abs:O_X+2,x
moveHighDone24:
              lda abs:O_Y,x
              clc
              adc dp:L_MOVE
              sta abs:O_Y,x
              bcc moveHighDone25
              inc abs:O_Y+2,x
moveHighDone25:
              rts

;;; SelectDodgeDir: X = object.
SelectDodgeDir:
              lda abs:O_FLAGS,x
              bit ##FL_FIRSTATTACK
              beq dodgeTurnaround
              and ##0xffff-FL_FIRSTATTACK
              sta abs:O_FLAGS,x
              lda ##NODIR
              bra dodgeTurnSet
dodgeTurnaround:
              lda abs:O_DIR,x
              eor ##4                     ; opposite of the eight directions
              cmp ##12
              bne dodgeTurnSet
              lda ##NODIR
dodgeTurnSet: sta dp:L_TURN
              lda abs:PLAYER+O_TILEX
              sec
              sbc abs:O_TILEX,x
              sta dp:L_T                  ; deltax
              lda abs:PLAYER+O_TILEY
              sec
              sbc abs:O_TILEY,x
              sta dp:L_U                  ; deltay
              lda dp:L_T
              beq dodgeWest
              bmi dodgeWest
              lda ##EAST
              ldy ##WEST
              bra dodgeX
dodgeWest:    lda ##WEST
              ldy ##EAST
dodgeX:       sta dp:L_TRY+2
              sty dp:L_TRY+6
              lda dp:L_U
              beq dodgeNorth
              bmi dodgeNorth
              lda ##SOUTH
              ldy ##NORTH
              bra dodgeY
dodgeNorth:   lda ##NORTH
              ldy ##SOUTH
dodgeY:       sta dp:L_TRY+4
              sty dp:L_TRY+8
              lda dp:L_T
              bpl dodgeAbsX
              eor ##0xffff
              inc a
dodgeAbsX:    sta dp:L_V
              lda dp:L_U
              bpl dodgeAbsY
              eor ##0xffff
              inc a
dodgeAbsY:    cmp dp:L_V
              bcs dodgeKeep               ; absdx > absdy swaps
              jsr abs:.word0 (swapTries)
dodgeKeep:    jsr abs:.word0 (Rnd)
              cmp ##128
              bcs dodgeNoSwap
              jsr abs:.word0 (swapTries)
dodgeNoSwap:  lda dp:L_TRY+2
              asl a
              asl a
              asl a
              clc
              adc dp:L_TRY+2
              adc dp:L_TRY+4
              tax
              lda long:diagonalTable,x
              and ##255
              sta dp:L_TRY
              stz dp:L_I
dodgeTry:     ldx dp:L_I
              lda dp:L_TRY,x
              cmp ##NODIR
              beq dodgeNext
              cmp dp:L_TURN
              beq dodgeNext
              ldx dp:L_OB
              sta abs:O_DIR,x
              jsr abs:.word0 (TryWalk)
              bcs dodgeDone
dodgeNext:    inc dp:L_I
              inc dp:L_I
              lda dp:L_I
              cmp ##10
              bcc dodgeTry
              ldx dp:L_OB
              lda dp:L_TURN
              cmp ##NODIR
              beq dodgeStuck
              sta abs:O_DIR,x
              jsr abs:.word0 (TryWalk)
              bcs dodgeDone
dodgeStuck:   ldx dp:L_OB
              lda ##NODIR
              sta abs:O_DIR,x
dodgeDone:    rts
swapTries:    lda dp:L_TRY+2
              ldy dp:L_TRY+4
              sta dp:L_TRY+4
              sty dp:L_TRY+2
              lda dp:L_TRY+6
              ldy dp:L_TRY+8
              sta dp:L_TRY+8
              sty dp:L_TRY+6
              rts
;;; diagonal[d1][d2], 9x9 bytes.
diagonalTable:.byte 8,8,1,8,8,8,7,8,8
              .byte 8,8,8,8,8,8,8,8,8
              .byte 1,8,8,8,3,8,8,8,8
              .byte 8,8,8,8,8,8,8,8,8
              .byte 8,8,3,8,8,8,5,8,8
              .byte 8,8,8,8,8,8,8,8,8
              .byte 7,8,8,8,5,8,8,8,8
              .byte 8,8,8,8,8,8,8,8,8
              .byte 8,8,8,8,8,8,8,8,8

;;; SelectChaseDir: X = object.
SelectChaseDir:
              lda abs:O_DIR,x
              sta dp:L_OLDDIR
              eor ##4
              cmp ##12
              bne chaseTurnSet
              lda ##NODIR
chaseTurnSet: sta dp:L_TURN
              lda abs:PLAYER+O_TILEX
              sec
              sbc abs:O_TILEX,x
              sta dp:L_T
              lda abs:PLAYER+O_TILEY
              sec
              sbc abs:O_TILEY,x
              sta dp:L_U
              lda ##NODIR
              sta dp:L_TRY+2
              sta dp:L_TRY+4
              lda dp:L_T
              beq chaseNoX
              bmi chaseXWest
              lda ##EAST
              bra chaseXSet
chaseXWest:   lda ##WEST
chaseXSet:    sta dp:L_TRY+2
chaseNoX:     lda dp:L_U
              beq chaseNoY
              bmi chaseYNorth
              lda ##SOUTH
              bra chaseYSet
chaseYNorth:  lda ##NORTH
chaseYSet:    sta dp:L_TRY+4
chaseNoY:     lda dp:L_T
              bpl chaseAbsX
              eor ##0xffff
              inc a
chaseAbsX:    sta dp:L_V
              lda dp:L_U
              bpl chaseAbsY
              eor ##0xffff
              inc a
chaseAbsY:    cmp dp:L_V
              beq chaseOrdered
              bcc chaseOrdered
              lda dp:L_TRY+2
              ldy dp:L_TRY+4
              sta dp:L_TRY+4
              sty dp:L_TRY+2
chaseOrdered: lda dp:L_TRY+2
              cmp dp:L_TURN
              bne chaseD1Kept
              lda ##NODIR
              sta dp:L_TRY+2
chaseD1Kept:  lda dp:L_TRY+4
              cmp dp:L_TURN
              bne chaseD2Kept
              lda ##NODIR
              sta dp:L_TRY+4
chaseD2Kept:  lda dp:L_TRY+2
              jsr abs:.word0 (chaseAttempt)
              bcs chaseDone
              lda dp:L_TRY+4
              jsr abs:.word0 (chaseAttempt)
              bcs chaseDone
              lda dp:L_OLDDIR
              jsr abs:.word0 (chaseAttempt)
              bcs chaseDone
              jsr abs:.word0 (Rnd)
              cmp ##129
              bcc chaseBackward           ; US_RndT()>128 searches north first
              lda ##NORTH
              jsr abs:.word0 (chaseSearch)
              bcs chaseDone
              lda ##NORTHWEST
              jsr abs:.word0 (chaseSearch)
              bcs chaseDone
              lda ##WEST
              jsr abs:.word0 (chaseSearch)
              bcs chaseDone
              bra chaseTurnaround
chaseBackward:lda ##WEST
              jsr abs:.word0 (chaseSearch)
              bcs chaseDone
              lda ##NORTHWEST
              jsr abs:.word0 (chaseSearch)
              bcs chaseDone
              lda ##NORTH
              jsr abs:.word0 (chaseSearch)
              bcs chaseDone
chaseTurnaround:
              lda dp:L_TURN
              jsr abs:.word0 (chaseAttempt)
              bcs chaseDone
              ldx dp:L_OB
              lda ##NODIR
              sta abs:O_DIR,x
chaseDone:    rts
;;; Try direction A unless it is nodir. Carry set on success.
chaseAttempt: cmp ##NODIR
              beq chaseFail
              ldx dp:L_OB
              sta abs:O_DIR,x
              jmp abs:.word0 (TryWalk)
chaseFail:    clc
              rts
;;; The search loop skips only the turnaround.
chaseSearch:  cmp dp:L_TURN
              beq chaseFail
              ldx dp:L_OB
              sta abs:O_DIR,x
              jmp abs:.word0 (TryWalk)

;;; ------------------------------------------------------------- thinks
T_Stand:      ldx dp:L_OB
              jmp abs:.word0 (SightPlayer)

;;; T_Chase: X = L_OB.
T_Chase:      lda abs:V_victoryflag
              beq chaseAlive
              rts
chaseAlive:   stz dp:L_DODGE
              ldx dp:L_OB
              jsr abs:.word0 (CheckLine)
              bcc chaseMoveStart
              ldx dp:L_OB
              jsr abs:.word0 (tileDistance)
              beq chanceSure
              cmp ##1
              bne chanceByDist
              lda abs:O_DIST+2,x          ; distance < 0x4000 (signed)
              bmi chanceSure
              bne chanceByDist
              lda abs:O_DIST,x
              cmp ##0x4000
              bcc chanceSure
chanceByDist: lda abs:V_tics
              cmp ##1
              beq chanceOneTic
              cmp ##4
              bne chanceDivide
              ldx dp:L_DIST
              lda long:SHOOT_CHANCE_4,x
              and ##255
              bra chanceSet
chanceOneTic: ldx dp:L_DIST
              lda long:SHOOT_CHANCE_1,x
              and ##255
              bra chanceSet
chanceDivide:
              asl a
              asl a
              asl a
              asl a
              jsr abs:.word0 (divideByDist)
              bra chanceSet
chanceSure:   lda ##300
chanceSet:    sta dp:L_CHANCE
              jsr abs:.word0 (Rnd)
              cmp dp:L_CHANCE
              bcs chanceMissed
              ldx dp:L_OB
              lda abs:O_CLASS,x
              jmp abs:.word0 (ClassShoot)
chanceMissed: lda ##1
              sta dp:L_DODGE
chaseMoveStart:
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne chaseHasDir
              jsr abs:.word0 (chaseSelect)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne chaseHasDir
              rts
chaseHasDir:  jsr abs:.word0 (speedMove)
chaseMoveLoop:lda dp:L_MOVE
              ora dp:L_MOVE+2
              bne chaseMoving
              rts
chaseMoving:  ldx dp:L_OB
              lda abs:O_DIST+2,x
              bpl chaseNoDoor
              lda abs:O_DIST,x            ; waiting for door -distance-1
              eor ##0xffff
              sta dp:L_DOOR
              jsr abs:.word0 (OpenDoor)
              ldx dp:L_DOOR
              txa
              asl a
              tax
              lda abs:DOORACT,x
              beq chaseDoorOpen
              rts
chaseDoorOpen:ldx dp:L_OB
              stz abs:O_DIST,x
              lda ##1
              sta abs:O_DIST+2,x
chaseNoDoor:  jsr abs:.word0 (moveFits)
              bcc chaseReached
              jmp abs:.word0 (MoveObj)
chaseReached: jsr abs:.word0 (snapToTile)
              jsr abs:.word0 (chaseSelect)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne chaseMoveLoop
              rts
chaseSelect:  ldx dp:L_OB
              lda dp:L_DODGE
              beq chaseNoDodge
              jmp abs:.word0 (SelectDodgeDir)
chaseNoDodge: jmp abs:.word0 (SelectChaseDir)

;;; X is the checked actor. L_MOVE = speed*tics (long).
speedMove:    lda abs:O_SPEED,x
              sta dp:L_MOVE
              stz dp:L_MOVE+2
speedTickTest:ldy abs:V_tics
              dey
              beq speedMoveDone
              cpy ##3
              beq speedMoveFour
              iny
              jmp abs:.word0 (mulSmall)
speedMoveFour:asl a
              rol dp:L_MOVE+2
              asl a
              rol dp:L_MOVE+2
              sta dp:L_MOVE
speedMoveDone:rts
;;; L_MOVE = A * Y (Y < 256).
mulSmall:     sta dp:L_T
              stz dp:L_MOVE
              stz dp:L_MOVE+2
              tya
              beq mulDone
mulAdd:       lda dp:L_MOVE
              clc
              adc dp:L_T
              sta dp:L_MOVE
              bcc mulNext
              inc dp:L_MOVE+2
mulNext:      dey
              bne mulAdd
mulDone:      rts
;;; Carry set when move < ob->distance (signed longs). X = L_OB.
moveFits:     lda dp:L_MOVE
              cmp abs:O_DIST,x
              lda dp:L_MOVE+2
              sbc abs:O_DIST+2,x
              bvc fitsSigned
              eor ##0x8000
fitsSigned:   bmi fitsYes
              clc
              rts
fitsYes:      sec
              rts
;;; Reached the goal tile: x/y to its center, move -= distance.
snapToTile:   lda dp:L_MOVE
              sec
              sbc abs:O_DIST,x
              sta dp:L_MOVE
              lda dp:L_MOVE+2
              sbc abs:O_DIST+2,x
              sta dp:L_MOVE+2
              lda ##0x8000
              sta abs:O_X,x
              sta abs:O_Y,x
              lda abs:O_TILEX,x
              sta abs:O_X+2,x
              lda abs:O_TILEY,x
              sta abs:O_Y+2,x
              jmp abs:.word0 (MarkActorCell)

;;; A = max(|tilex - player tilex|, |tiley - player tiley|). X = object.
tileDistance: lda abs:O_TILEX,x
              sec
              sbc abs:PLAYER+O_TILEX
              bpl tdx
              eor ##0xffff
              inc a
tdx:          sta dp:L_T
              lda abs:O_TILEY,x
              sec
              sbc abs:PLAYER+O_TILEY
              bpl tdy
              eor ##0xffff
              inc a
tdy:          cmp dp:L_T
              bcs tdDone
              lda dp:L_T
tdDone:       sta dp:L_DIST
              lda dp:L_DIST
              rts
;;; A = A / L_DIST (unsigned, small values).
divideByDist: ldy ##0
divideLoop:   cmp dp:L_DIST
              bcc divideDone
              sbc dp:L_DIST
              iny
              bra divideLoop
divideDone:   tya
              rts

T_DogChase:   ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne dogHasDir
              jsr abs:.word0 (SelectDodgeDir)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne dogHasDir
              rts
dogHasDir:    jsr abs:.word0 (speedMove)
dogLoop:      lda dp:L_MOVE
              ora dp:L_MOVE+2
              bne dogMoving
              rts
dogMoving:    ldx dp:L_OB
              lda abs:PLAYER+O_X
              sec
              sbc abs:O_X,x
              sta dp:L_PA
              lda abs:PLAYER+O_X+2
              sbc abs:O_X+2,x
              jsr abs:.word0 (absMinusMove)
              bcc dogNoJump
              ldx dp:L_OB
              lda abs:PLAYER+O_Y
              sec
              sbc abs:O_Y,x
              sta dp:L_PA
              lda abs:PLAYER+O_Y+2
              sbc abs:O_Y+2,x
              jsr abs:.word0 (absMinusMove)
              bcc dogNoJump
              ldx dp:L_OB
              ldy ##s_dogjump1
              jmp abs:.word0 (NewState)
dogNoJump:    jsr abs:.word0 (moveFits)
              bcc dogReached
              jmp abs:.word0 (MoveObj)
dogReached:   jsr abs:.word0 (snapToTile)
              ldx dp:L_OB
              jsr abs:.word0 (SelectDodgeDir)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne dogLoop
              rts
;;; A:L_PA = d. Carry set when |d| - L_MOVE <= MINACTORDIST (signed longs).
absMinusMove: sta dp:L_PA+2
              bpl absKept
              lda ##0
              sec
              sbc dp:L_PA
              sta dp:L_PA
              lda ##0
              sbc dp:L_PA+2
              sta dp:L_PA+2
absKept:      lda dp:L_PA
              sec
              sbc dp:L_MOVE
              sta dp:L_PA
              lda dp:L_PA+2
              sbc dp:L_MOVE+2
              bmi nearEnough              ; negative is below 0x10000
              cmp ##1
              bcc nearEnough
              bne notNear
              lda dp:L_PA
              bne notNear
nearEnough:   sec
              rts
notNear:      clc
              rts

T_Path:       ldx dp:L_OB
              jsr abs:.word0 (SightPlayer)
              bcc pathWalk
              rts
pathWalk:     ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne pathHasDir
              jsr abs:.word0 (SelectPathDir)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne pathHasDir
              rts
pathHasDir:   jsr abs:.word0 (speedMove)
pathLoop:     lda dp:L_MOVE
              ora dp:L_MOVE+2
              bne pathMoving
              rts
pathMoving:   ldx dp:L_OB
              lda abs:O_DIST+2,x
              bpl pathNoDoor
              lda abs:O_DIST,x
              eor ##0xffff
              sta dp:L_DOOR
              jsr abs:.word0 (OpenDoor)
              lda dp:L_DOOR
              asl a
              tax
              lda abs:DOORACT,x
              beq pathDoorOpen
              rts
pathDoorOpen: ldx dp:L_OB
              stz abs:O_DIST,x
              lda ##1
              sta abs:O_DIST+2,x
pathNoDoor:   jsr abs:.word0 (moveFits)
              bcc pathReached
              jmp abs:.word0 (MoveObj)
pathReached:  ldx dp:L_OB
              lda abs:O_TILEX,x
              cmp ##65
              bcs pathWall
              lda abs:O_TILEY,x
              cmp ##65
              bcc pathSnap
pathWall:     brk                         ; T_Path hit a wall
pathSnap:     jsr abs:.word0 (snapToTile)
              ldx dp:L_OB
              jsr abs:.word0 (SelectPathDir)
              ldx dp:L_OB
              lda abs:O_DIR,x
              cmp ##NODIR
              bne pathLoop
              rts

SelectPathDir:lda abs:O_TILEY,x
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:O_TILEX,x
              tay
              lda abs:MAP1,y
              and ##255
              sec
              sbc ##90
              cmp ##8
              bcs pathKeepDir
              sta abs:O_DIR,x
pathKeepDir:  stz abs:O_DIST,x
              lda ##1
              sta abs:O_DIST+2,x
              jsr abs:.word0 (TryWalk)
              bcs pathSelected
              ldx dp:L_OB
              lda ##NODIR
              sta abs:O_DIR,x
pathSelected: rts

;;; ------------------------------------------------------------- sight
;;; SightPlayer: X = L_OB. Carry set when FirstSighting ran.
SightPlayer:
sightActorCurrent:
              lda abs:O_TEMP2,x
              beq sightSearch
              sec
              sbc abs:V_tics
              sta abs:O_TEMP2,x
              beq sightReact
              bpl sightNot
sightReact:   stz abs:O_TEMP2,x
              jsr abs:.word0 (FirstSighting)
              sec
              rts
sightNot:     clc
              rts
sightSearch:  ldy abs:O_AREA,x
              lda abs:AREABYPLAYER,y
              and ##255
              beq sightNot
              lda abs:O_FLAGS,x
              bit ##FL_AMBUSH
              beq sightNoAmbush
              jsr abs:.word0 (CheckSight)
              bcc sightNot
              ldx dp:L_OB
              lda abs:O_FLAGS,x
              and ##0xffff-FL_AMBUSH
              sta abs:O_FLAGS,x
              bra sightReactionReady
sightNoAmbush:lda abs:V_madenoise
              bne sightReactionReady
              jsr abs:.word0 (CheckSight)
              bcc sightNot
sightReaction:ldx dp:L_OB
sightReactionReady:
              lda abs:O_CLASS,x
              cmp ##GUARDOBJ
              bne sightNotGuard
              jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              bra sightDelay
sightNotGuard:cmp ##SSOBJ
              bne sightNotSS
              jsr abs:.word0 (Rnd)
              tay
              lda abs:DIV6,y
              and ##255
              bra sightDelay
sightNotSS:   cmp ##DOGOBJ
              bne sightBoss
              jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              lsr a
              bra sightDelay
sightBoss:
              jmp abs:.word0 (RegisteredReaction)
;;; Rnd preserves X throughout each class-specific reaction calculation.
sightDelay:   inc a
sightDelayCurrent:
              sta abs:O_TEMP2,x
              clc
              rts

;;; SightPlayer checked the actor's connected area before either call.
;;; X = object. Carry set when the player is seen.
CheckSight:
connectedSight:
sightConnected:
              lda abs:PLAYER+O_X
              sec
              sbc abs:O_X,x
              sta dp:L_PA
              lda abs:PLAYER+O_X+2
              sbc abs:O_X+2,x
              sta dp:L_PA+2
              lda abs:PLAYER+O_Y
              sec
              sbc abs:O_Y,x
              sta dp:L_PB
              lda abs:PLAYER+O_Y+2
              sbc abs:O_Y+2,x
              sta dp:L_PB+2
              lda dp:L_PA+2
              ldy dp:L_PA
              jsr abs:.word0 (withinSight)
              bcc sightFacing
              lda dp:L_PB+2
              ldy dp:L_PB
              jsr abs:.word0 (withinSight)
              bcc sightFacing
              sec
              rts
sightFacing:  lda abs:O_DIR,x
              cmp ##NORTH
              bne facingEast
              lda dp:L_PB+2               ; deltay > 0 hides
              bmi sightTrace
              ora dp:L_PB
              beq sightTrace
              clc
              rts
facingEast:   cmp ##EAST
              bne facingSouth
              lda dp:L_PA+2               ; deltax < 0 hides
              bpl sightTrace
              clc
              rts
facingSouth:  cmp ##SOUTH
              bne facingWest
              lda dp:L_PB+2
              bpl sightTrace
              clc
              rts
facingWest:   cmp ##WEST
              bne sightTrace
              lda dp:L_PA+2
              bmi sightTrace
              ora dp:L_PA
              beq sightTrace
              clc
              rts
sightTrace:   jmp abs:.word0 (CheckLine)
;;; A:Y = d. Carry set when -MINSIGHT < d < MINSIGHT (0x18000).
withinSight:  cmp ##0
              beq sightIn
              cmp ##1
              bne sightNegative
              cpy ##0x8000
              bcc sightIn
              clc
              rts
sightNegative:cmp ##0xffff
              beq sightIn
              cmp ##0xfffe
              bne sightOut
              cpy ##0x8001
              bcs sightIn
sightOut:     clc
              rts
sightIn:      sec
              rts

;;; FirstSighting: X = object.
FirstSighting:lda abs:O_CLASS,x
              cmp ##GUARDOBJ
              bne firstNotGuard
              lda ##HALTSND
              jsr abs:.word0 (LogicSound)
              ldy ##s_grdchase1
              jsr abs:.word0 (NewState)
              lda abs:O_SPEED,x
              asl a
              adc abs:O_SPEED,x
              bra firstSpeed
firstNotGuard:cmp ##SSOBJ
              bne firstNotSS
              lda ##SCHUTZADSND
              jsr abs:.word0 (LogicSound)
              ldy ##s_sschase1
              jsr abs:.word0 (NewState)
              lda abs:O_SPEED,x
              asl a
              asl a
              bra firstSpeed
firstNotSS:   cmp ##DOGOBJ
              bne firstBoss
              lda ##DOGBARKSND
              jsr abs:.word0 (LogicSound)
              ldy ##s_dogchase1
              jsr abs:.word0 (NewState)
              lda abs:O_SPEED,x
              asl a
              bra firstSpeed
firstBoss:
              jmp abs:.word0 (ClassFirst)
firstSpeed:   sta abs:O_SPEED,x
              lda abs:O_DIST+2,x
              bpl firstDistance
              stz abs:O_DIST,x
              stz abs:O_DIST+2,x
firstDistance:lda abs:O_FLAGS,x
              ora ##FL_ATTACKMODE|FL_FIRSTATTACK
              sta abs:O_FLAGS,x
              rts

;;; ------------------------------------------------------------- combat
;;; T_Shoot: X = L_OB (an action).
T_Shoot:      ldx dp:L_OB
              ldy abs:O_AREA,x
              lda abs:AREABYPLAYER,y
              and ##255
              bne shootConnected
              rts
shootConnected:
              jsr abs:.word0 (CheckLine)
              bcs shootSeen
              rts
shootSeen:    ldx dp:L_OB
              jsr abs:.word0 (tileDistance)
              lda abs:O_CLASS,x
              cmp ##SSOBJ
              beq betterShot
              cmp ##BOSSOBJ
              bne shotDistance
betterShot:   lda dp:L_DIST
              asl a
              asl a
              tay
              lda abs:DIV6,y              ; dist*2/3
              and ##255
              sta dp:L_DIST
shotDistance: lda abs:O_FLAGS,x
              and ##FL_VISABLE
              beq shotHidden
              lda dp:L_DIST
              asl a
              asl a
              asl a
              asl a
              bra shotScaled
shotHidden:   lda dp:L_DIST
              asl a
              asl a
              asl a
shotScaled:   sta dp:L_T
              lda abs:V_thrustspeed_hi
              bne shotRunning
              lda abs:V_thrustspeed
              cmp ##RUNSPEED
              bcc shotWalking
shotRunning:  lda ##160
              bra shotChance
shotWalking:  lda ##256
shotChance:   sec
              sbc dp:L_T
              sta dp:L_CHANCE
              jsr abs:.word0 (Rnd)
              sec                         ; US_RndT() < hitchance, signed
              sbc dp:L_CHANCE
              bvc shotCompare
              eor ##0x8000
shotCompare:  bpl shotSound
              lda dp:L_DIST
              cmp ##2
              bcs shotFar
              jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              bra shotHit
shotFar:      cmp ##4
              bcs shotFarther
              jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              lsr a
              bra shotHit
shotFarther:  jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              lsr a
              lsr a
shotHit:      ldx dp:L_OB
              jsr abs:.word0 (TakeDamage)
shotSound:    ldx dp:L_OB
              lda abs:O_CLASS,x
              cmp ##SSOBJ
              bne shotNotSS
              lda ##SSFIRESND
              jmp abs:.word0 (LogicSound)
shotNotSS:
              jmp abs:.word0 (RegisteredShotSound)

T_Bite:       lda ##DOGATTACKSND
              jsr abs:.word0 (LogicSound)
              ldx dp:L_OB
              lda abs:PLAYER+O_X
              sec
              sbc abs:O_X,x
              sta dp:L_PA
              lda abs:PLAYER+O_X+2
              sbc abs:O_X+2,x
              jsr abs:.word0 (absMinusTile)
              bcc biteMissed
              ldx dp:L_OB
              lda abs:PLAYER+O_Y
              sec
              sbc abs:O_Y,x
              sta dp:L_PA
              lda abs:PLAYER+O_Y+2
              sbc abs:O_Y+2,x
              jsr abs:.word0 (absMinusTile)
              bcc biteMissed
              jsr abs:.word0 (Rnd)
              cmp ##180
              bcs biteMissed
              jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              lsr a
              lsr a
              ldx dp:L_OB
              jmp abs:.word0 (TakeDamage)
biteMissed:   rts
;;; A:L_PA = d. Carry set when |d| - TILEGLOBAL <= MINACTORDIST.
absMinusTile: stz dp:L_MOVE
              ldy ##1
              sty dp:L_MOVE+2
              jmp abs:.word0 (absMinusMove)

A_DeathScream:ldx dp:L_OB
              lda abs:V_mapon
#ifdef WOLF_SPEAR
              cmp ##18
              beq screamSecret
              cmp ##19
              bne screamClass
screamSecret:
              jsr abs:.word0 (Rnd)
              cmp ##0
              bne screamClass
              lda abs:O_CLASS,x
              cmp ##GUARDOBJ
              beq screamRare
              cmp ##SSOBJ
              beq screamRare
              cmp ##DOGOBJ
              beq screamRare
              cmp ##4
              beq screamRare
              cmp ##11
              bne screamClass
screamRare:
#else
              cmp ##9
              bne screamClass
              jsr abs:.word0 (Rnd)
              cmp ##0
              bne screamClass
#endif
              lda ##DEATHSCREAM6SND
              jmp abs:.word0 (LogicSound)
screamClass:  ldx dp:L_OB
              lda abs:O_CLASS,x
              cmp ##GUARDOBJ
              bne screamOther
              jsr abs:.word0 (Rnd)
              and ##7
              asl a
              tax
              lda long:guardScreams,x
              jmp abs:.word0 (LogicSound)
screamOther:  cmp ##SSOBJ
              bne screamDog
              lda ##LEBENSND
              jmp abs:.word0 (LogicSound)
screamDog:    cmp ##DOGOBJ
              bne screamBoss
              lda ##DOGDEATHSND
              jmp abs:.word0 (LogicSound)
screamBoss:
              jmp abs:.word0 (ClassScream)
guardScreams: .word DEATHSCREAM1SND, DEATHSCREAM2SND, DEATHSCREAM3SND, DEATHSCREAM4SND
              .word DEATHSCREAM5SND, DEATHSCREAM7SND, DEATHSCREAM8SND, DEATHSCREAM9SND

;;; DamageActor: X = object, A = damage.
DamageActor:  stx dp:L_ARG
              sta dp:L_DAMAGE
              lda ##1
              sta abs:V_madenoise
              lda abs:O_FLAGS,x
              bit ##FL_ATTACKMODE
              bne damageNormal
              asl dp:L_DAMAGE
damageNormal: lda abs:O_HP,x
              sec
              sbc dp:L_DAMAGE
              sta abs:O_HP,x
              beq damageKills
              bpl damagePain
damageKills:  jmp abs:.word0 (KillActor)
damagePain:   lda abs:O_FLAGS,x
              bit ##FL_ATTACKMODE
              bne damageState
              jsr abs:.word0 (FirstSighting)
              ldx dp:L_ARG
damageState:  lda abs:O_CLASS,x
              cmp ##GUARDOBJ
              bne damageNotGuard
              ldy ##s_grdpain
              lda abs:O_HP,x
              lsr a
              bcs damageSetPain
              ldy ##s_grdpain1
damageSetPain:jmp abs:.word0 (NewState)
damageNotGuard:
              cmp ##SSOBJ
              bne damageDone
              ldy ##s_sspain
              lda abs:O_HP,x
              lsr a
              bcs damageSetPain
              ldy ##s_sspain1
              bra damageSetPain
damageDone:
              jmp abs:.word0 (ClassPain)

;;; KillActor: X = object.
KillActor:    stx dp:L_ARG
              lda abs:O_X+2,x
              sta abs:O_TILEX,x
              sta dp:L_X
              lda abs:O_Y+2,x
              sta abs:O_TILEY,x
              sta dp:L_Y
              lda abs:O_CLASS,x
              cmp ##GUARDOBJ
              bne killNotGuard
              lda ##100
              jsr abs:.word0 (GivePoints)
              ldx dp:L_ARG
              ldy ##s_grddie1
              jsr abs:.word0 (NewState)
              lda ##14                    ; bo_clip2
              jsr abs:.word0 (PlaceItemType)
              bra killed
killNotGuard: cmp ##SSOBJ
              bne killNotSS
              lda ##500
              jsr abs:.word0 (GivePoints)
              ldx dp:L_ARG
              ldy ##s_ssdie1
              jsr abs:.word0 (NewState)
              lda abs:V_bestweapon
              cmp ##2
              bcs ssClip
              lda ##15                    ; bo_machinegun
              bra ssDrop
ssClip:       lda ##14
ssDrop:       jsr abs:.word0 (PlaceItemType)
              bra killed
killNotSS:    cmp ##DOGOBJ
              bne killBoss
              lda ##200
              jsr abs:.word0 (GivePoints)
              ldx dp:L_ARG
              ldy ##s_dogdie1
              jsr abs:.word0 (NewState)
              bra killed
killBoss:
              jmp abs:.word0 (ClassKill)
killed:       inc abs:V_killcount
              ldx dp:L_ARG
              lda abs:O_FLAGS,x
              and ##0xffff-FL_SHOOTABLE
              ora ##FL_NONMARK
              sta abs:O_FLAGS,x
              jsr abs:.word0 (CellOfX)
              lda ##0
              sta abs:ACTORAT,y
              lda ##EV_STATUS
              tsb abs:V_events
              rts
