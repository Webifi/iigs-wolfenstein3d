;;; Player movement, collision, attacks, pickups, and status bookkeeping.
;;; World positions are 16.16 longs. V_controlx/y and V_buttonstate hold
;;; the current command; V_events accumulates changes for the display/audio.
#include "memmap.inc"
#include "logic.inc"
#include "logic_dp.inc"
#include "logic_sounds.inc"
              .section logiccode, text, root, noreorder
              .public T_Player, T_Attack, Thrust, TakeDamage, GetBonus, GivePoints
              .public GiveAmmo, HealSelf, LogicSound, FracSmall, InRange64K
              .extern Rnd, Mul16, MulHigh16, CellOfX, NewState, CheckLine, DamageActor
              .extern PushWall, OperateDoor, StoreLogicTile
              .extern SpawnBJVictory, VictorySpin
              .extern playerCounts

PLAYER        .equ OBJLIST
MINDIST       .equ 0x5800
FL_SHOOTABLE  .equ 1
FL_VISABLE    .equ 8
FL_BONUS      .equ 2
BT_ATTACK     .equ 0
BT_STRAFE     .equ 2
BT_RUN        .equ 4
BT_USE        .equ 6
EX_COMPLETED  .equ 1
EX_DIED       .equ 2
EX_SECRETLEVEL .equ 9
EV_STATUS     .equ 1
EV_FACE       .equ 2
EV_DAMAGE     .equ 4
EV_BONUS      .equ 8

;;; Sound requests reach the sound module through one place. A = sound id.
LogicSound:   sta abs:V_sound
              php
              pha
              lda abs:V_gatling
              beq soundGateDone
              lda abs:V_sound
#include "logic_sound_gate.inc"
soundGateDone:pla
              plp
              rts

T_Player:     lda abs:V_victoryflag
              beq playerAlive
              jmp abs:.word0 (VictorySpin)
playerAlive:  jsr abs:.word0 (UpdateFace)
              jsr abs:.word0 (CheckWeaponChange)
              lda abs:V_buttonstate+BT_USE
              beq noUse
              jsr abs:.word0 (CmdUse)
noUse:        lda abs:V_buttonstate+BT_ATTACK
              beq noFire
              lda abs:V_buttonheld+BT_ATTACK
              bne noFire
              jsr abs:.word0 (CmdFire)
noFire:       jsr abs:.word0 (ControlMovement)
              jmp abs:.word0 (PlayerTiles)

;;; plux/pluy and the tile of the player after a move.
PlayerTiles:  lda abs:PLAYER+O_X+1
              sta abs:V_plux
              lda abs:PLAYER+O_Y+1
              sta abs:V_pluy
              lda abs:PLAYER+O_X+2
              sta abs:PLAYER+O_TILEX
              lda abs:PLAYER+O_Y+2
              sta abs:PLAYER+O_TILEY
              rts

T_Attack:     jsr abs:.word0 (UpdateFace)
              lda abs:V_victoryflag
              beq attackAlive
              jmp abs:.word0 (VictorySpin)
attackAlive:  lda abs:V_buttonstate+BT_USE
              beq useKept
              lda abs:V_buttonheld+BT_USE
              bne useKept
              stz abs:V_buttonstate+BT_USE
useKept:      lda abs:V_buttonstate+BT_ATTACK
              beq fireKept
              lda abs:V_buttonheld+BT_ATTACK
              bne fireKept
              stz abs:V_buttonstate+BT_ATTACK
fireKept:     jsr abs:.word0 (ControlMovement)
              jsr abs:.word0 (PlayerTiles)
              lda abs:V_attackcount
              sec
              sbc abs:V_tics
              sta abs:V_attackcount
              beq attackStep
              bpl attackDone
attackStep:   jsr abs:.word0 (attackEntry)
              lda abs:ATTACKINFO+2,y      ; attack
              cmp ##0xffff
              bne attackKind
              lda ##s_player
              sta abs:PLAYER+O_STATE
              lda abs:V_ammo
              bne attackAmmoLeft
              stz abs:V_weapon
              bra attackStatus
attackAmmoLeft:
              lda abs:V_weapon
              cmp abs:V_chosenweapon
              beq attackReset
              lda abs:V_chosenweapon
              sta abs:V_weapon
attackStatus: lda ##EV_STATUS
              tsb abs:V_events
attackReset:  stz abs:V_attackframe
              stz abs:V_weaponframe
attackDone:   rts
attackKind:   sty dp:L_SAVE
              cmp ##4
              bne attackNotChain
              lda abs:V_ammo
              beq attackNext
              lda abs:V_buttonstate+BT_ATTACK
              beq attackGun
              dec abs:V_attackframe
              dec abs:V_attackframe
              bra attackGun
attackNotChain:
              cmp ##1
              beq attackGun
              cmp ##2
              bne attackRepeat
              jsr abs:.word0 (KnifeAttack)
              bra attackNext
attackRepeat: cmp ##3
              bne attackNext
              lda abs:V_ammo
              beq attackNext
              lda abs:V_buttonstate+BT_ATTACK
              beq attackNext
              dec abs:V_attackframe
              dec abs:V_attackframe
              bra attackNext
attackGun:    lda abs:V_ammo
              bne attackShoot
              inc abs:V_attackframe       ; can only happen with the chain gun
              bra attackNext
attackShoot:  jsr abs:.word0 (GunAttack)
              dec abs:V_ammo
              lda ##EV_STATUS
              tsb abs:V_events
attackNext:   ldy dp:L_SAVE
              lda abs:ATTACKINFO,y        ; this entry's tics
              clc
              adc abs:V_attackcount
              sta abs:V_attackcount
              inc abs:V_attackframe
              jsr abs:.word0 (attackEntry)
              lda abs:ATTACKINFO+4,y
              sta abs:V_weaponframe
              lda abs:V_attackcount
              beq attackAgain
              bpl attackDone
attackAgain:  jmp abs:.word0 (attackStep)

;;; Y = byte offset of attackinfo[weapon][attackframe] (6 bytes each).
attackEntry:  lda abs:V_weapon
              asl a
              asl a
              clc
              adc abs:V_attackframe
              sta dp:L_T
              asl a
              clc
              adc dp:L_T
              asl a
              tay
              rts

CmdFire:      lda ##1
              sta abs:V_buttonheld+BT_ATTACK
              lda ##s_attack
              sta abs:PLAYER+O_STATE
              stz abs:V_attackframe
              jsr abs:.word0 (attackEntry)
              lda abs:ATTACKINFO,y
              sta abs:V_attackcount
              lda abs:ATTACKINFO+4,y
              sta abs:V_weaponframe
              rts

;;; UpdateFace keeps the chain-gun pickup grin until its sound timer ends.
;;; The timer uses the AdLib event duration, independent of PCM rate, output
;;; volume or dropped effect voices. LogicSound handles preemption.
UpdateFace:   lda abs:V_gatling
              bne faceDone
              lda abs:V_facecount
              clc
              adc abs:V_tics
              sta abs:V_facecount
              jsr abs:.word0 (Rnd)
              cmp abs:V_facecount
              bcs faceDone                ; facecount > US_RndT() is false
              jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              cmp ##3
              bne faceKept
              lda ##1
faceKept:     sta abs:V_faceframe
#ifdef WOLF_SPEAR
              stz abs:V_ouchface
#endif
              stz abs:V_facecount
              lda ##EV_FACE
              tsb abs:V_events
faceDone:     rts

decodedWeaponChoice:
CheckWeaponChange:
              lda abs:V_ammo
              beq weaponKept
              lda abs:V_weaponchoice
              cmp abs:V_bestweapon
              bcc weaponPicked
              bne weaponKept
weaponPicked: sta abs:V_weapon
              sta abs:V_chosenweapon
              lda ##EV_STATUS
              tsb abs:V_events
weaponKept:   rts

;;; ControlMovement: angle from controlx, thrusts from controlx/controly.
ControlMovement:
              stz abs:V_thrustspeed
              stz abs:V_thrustspeed_hi
              lda abs:V_buttonstate+BT_STRAFE
              beq turning
              lda abs:V_controlx
              bne lagent_far233
              jmp abs:.word0 (forwardBack)
lagent_far233:
              bmi strafeRight
              lda abs:PLAYER+O_ANGLE
              sec
              sbc ##90
              bpl strafeAngle
              clc
              adc ##360
              bra strafeAngle
strafeRight:  lda abs:PLAYER+O_ANGLE
              clc
              adc ##90
              cmp ##360
              bcc strafeAngle
              sbc ##360
strafeAngle:  sta dp:L_ANGLE
              lda abs:V_controlx
              bpl strafeSpeed
              eor ##0xffff
              inc a
strafeSpeed:  ldy ##150
              jsr abs:.word0 (speedThrust)
              jmp abs:.word0 (forwardBack)
              .extern MouseAngleDivide
;;; The retained angle fraction is already in -19..19 after each turn.
turning:      lda abs:V_controlx
              beq turnAngleKept
              lda abs:V_anglefrac
              clc
              adc abs:V_controlx
              sta abs:V_anglefrac
              bpl unitsPositive
              eor ##0xffff
              inc a
              jsr abs:.word0 (turnDivide)
              eor ##0xffff
              inc a
              bra unitsReady
unitsPositive:jsr abs:.word0 (turnDivide)
unitsReady:   sta dp:L_T                  ; angleunits
              asl a
              asl a
              sta dp:L_U
              asl a
              asl a
              clc
              adc dp:L_U                  ; angleunits*20
              eor ##0xffff
              sec
              adc abs:V_anglefrac
              sta abs:V_anglefrac
              lda abs:PLAYER+O_ANGLE
              sec
              sbc dp:L_T
              bmi angleLow
              cmp ##360
              bcc angleSet
angleHigh:    sbc ##360
              cmp ##360
              bcs angleHigh
              bra angleSet
angleLow:     clc
              adc ##360
              bmi angleLow
angleSet:     sta abs:PLAYER+O_ANGLE
;;; V_controlstrafe supplies lateral motion independently of turning.
;;; Recorded demo commands leave it zero.
turnAngleKept:
              lda abs:V_controlstrafe
              beq forwardBack
              bmi sideRight
              lda abs:PLAYER+O_ANGLE
              clc
              adc ##90
              cmp ##360
              bcc sideAngle
              sbc ##360
              bra sideAngle
sideRight:    lda abs:PLAYER+O_ANGLE
              sec
              sbc ##90
              bpl sideAngle
              clc
              adc ##360
sideAngle:    sta dp:L_ANGLE
              lda abs:V_controlstrafe
              bpl sideSpeed
              eor ##0xffff
              inc a
sideSpeed:    ldy ##150
              jsr abs:.word0 (speedThrust)
forwardBack:  lda abs:V_controly
              beq movementDone
              bpl backwards
              eor ##0xffff
              inc a
              ldy ##150
              tax
              lda abs:PLAYER+O_ANGLE
              sta dp:L_ANGLE
              txa
              jmp abs:.word0 (speedThrust)
backwards:    tax
              lda abs:PLAYER+O_ANGLE
              clc
              adc ##180
              cmp ##360
              bcc backAngle
              sbc ##360
backAngle:    sta dp:L_ANGLE
              txa
              ldy ##100
              jmp abs:.word0 (speedThrust)
movementDone: rts

;;; Thrust (L_ANGLE, A*Y): MOVESCALE or BACKMOVESCALE times the control.
speedThrust:  cmp ##281
              bcs speedThrustSlow
              sta dp:L_SPEED
              asl a
              tax
              lda long:THRUST_INDEX,x
              bpl thrustTable
              lda dp:L_SPEED
speedThrustSlow:
              jsr abs:.word0 (Mul16)
              lda dp:L_PROD
              sta dp:L_SPEED
              lda dp:L_PROD+2
              sta dp:L_SPEED+2
              jmp abs:.word0 (Thrust)

;;; Ten keyboard, clamped mouse and demo speeds share exact five-byte vectors.
thrustTable:  cpy ##100
              beq thrustRow
              clc
              adc ##6
thrustRow:    tax
              lda long:THRUST_ROWS,x
              sta dp:L_MPTR
              lda long:THRUST_ROWS+0x2,x
              sta dp:L_MPTR+2
              lda long:THRUST_ROWS+0x4,x
              sta dp:L_SPEED
              stz dp:L_SPEED+2
              clc
              adc abs:V_thrustspeed
              sta abs:V_thrustspeed
              lda abs:V_thrustspeed_hi
              adc ##0
              sta abs:V_thrustspeed_hi
              lda dp:L_ANGLE
              asl a
              asl a
              clc
              adc dp:L_ANGLE
              tay
              lda [L_MPTR],y
              sta dp:L_XMOVE
              iny
              iny
              lda [L_MPTR],y
              sta dp:L_YMOVE
              iny
              iny
              lda [L_MPTR],y
              and ##3
              sta dp:L_SIGN
              and ##1
              eor ##0xffff
              inc a
              sta dp:L_XMOVE+2
              lda dp:L_SIGN
              lsr a
              eor ##0xffff
              inc a
              sta dp:L_YMOVE+2
              jmp abs:.word0 (thrustVectorReady)

;;; Thrust: L_ANGLE in degrees, L_SPEED a long.
Thrust:       lda abs:V_thrustspeed
              clc
              adc dp:L_SPEED
              sta abs:V_thrustspeed
              lda abs:V_thrustspeed_hi
              adc dp:L_SPEED+2
              sta abs:V_thrustspeed_hi
              lda dp:L_SPEED+2
              bne capSpeed
              lda dp:L_SPEED
              cmp ##MINDIST*2
              bcc speedReady
capSpeed:     lda ##MINDIST*2-1
              sta dp:L_SPEED
speedReady:   lda dp:L_ANGLE
              clc
              adc ##90
              asl a
              asl a
              adc ##SINTAB
              tay
              lda dp:L_SPEED
              jsr abs:.word0 (FracSmall)
              lda dp:L_PB
              sta dp:L_XMOVE
              lda dp:L_PB+2
              sta dp:L_XMOVE+2
              lda dp:L_ANGLE
              asl a
              asl a
              adc ##SINTAB
              tay
              lda dp:L_SPEED
              jsr abs:.word0 (FracSmall)
              lda ##0
              sec
              sbc dp:L_PB
              sta dp:L_YMOVE
              lda ##0
              sbc dp:L_PB+2
              sta dp:L_YMOVE+2
thrustVectorReady:
              jsr abs:.word0 (ClipMove)
              lda abs:PLAYER+O_X+2
              sta abs:PLAYER+O_TILEX
              lda abs:PLAYER+O_Y+2
              sta abs:PLAYER+O_TILEY
              xba
              lsr a
              lsr a
              ora abs:PLAYER+O_TILEX
              tax
              lda abs:MAP0,x
              sec
              sbc ##107
              and ##255
              sta abs:PLAYER+O_AREA
#ifndef WOLF_SPEAR
              lda abs:MAP1,x
              and ##255
              cmp ##99
              bne thrustDone
              jsr abs:.word0 (SpawnBJVictory)
              lda ##1
              sta abs:V_victoryflag
#endif
thrustDone:   rts

;;; L_PB = FixedByFrac(A, [Y]) for an unsigned word A; [Y] is a sign-magnitude
;;; table long. The multiply uses only the low word of the fraction.
FracSmall:    phy
              pha
              lda abs:0,y
              tay
              pla
              jsr abs:.word0 (MulHigh16)
              ply
              sta dp:L_PB
              stz dp:L_PB+2
              lda abs:2,y
              bpl fracPositive
              lda ##0
              sec
              sbc dp:L_PB
              sta dp:L_PB
              lda ##0
              sbc dp:L_PB+2
              sta dp:L_PB+2
fracPositive: rts

ClipMove:     lda abs:PLAYER+O_X
              sta dp:L_BASEX
              lda abs:PLAYER+O_X+2
              sta dp:L_BASEX+2
              lda abs:PLAYER+O_Y
              sta dp:L_BASEY
              lda abs:PLAYER+O_Y+2
              sta dp:L_BASEY+2
              jsr abs:.word0 (movedX)
              jsr abs:.word0 (movedY)
              .public debugClipCall, TryMove
debugClipCall: jsr abs:.word0 (TryMove)
              bcs clipDone
;;; With one zero axis, retries can only repeat this failure or restore
;;; the original position. TryMove has no world side effects.
              lda dp:L_YMOVE
              ora dp:L_YMOVE+2
              bne clipHasY
              jmp abs:.word0 (baseX)
clipHasY:     lda dp:L_XMOVE
              ora dp:L_XMOVE+2
              bne clipSlide
              jmp abs:.word0 (baseY)
clipSlide:
              jsr abs:.word0 (baseY)
              jsr abs:.word0 (TryMove)
              bcs clipDone
              jsr abs:.word0 (baseX)
              jsr abs:.word0 (movedY)
              jsr abs:.word0 (TryMove)
              bcs clipDone
              jsr abs:.word0 (baseY)
clipDone:     rts
movedX:       lda dp:L_BASEX
              clc
              adc dp:L_XMOVE
              sta abs:PLAYER+O_X
              lda dp:L_BASEX+2
              adc dp:L_XMOVE+2
              sta abs:PLAYER+O_X+2
              rts
movedY:       lda dp:L_BASEY
              clc
              adc dp:L_YMOVE
              sta abs:PLAYER+O_Y
              lda dp:L_BASEY+2
              adc dp:L_YMOVE+2
              sta abs:PLAYER+O_Y+2
              rts
baseX:        lda dp:L_BASEX
              sta abs:PLAYER+O_X
              lda dp:L_BASEX+2
              sta abs:PLAYER+O_X+2
              rts
baseY:        lda dp:L_BASEY
              sta abs:PLAYER+O_Y
              lda dp:L_BASEY+2
              sta abs:PLAYER+O_Y+2
              rts

;;; TryMove(player): carry set when the move is allowed.
TryMove:      lda abs:PLAYER+O_X
              cmp ##MINDIST
              lda abs:PLAYER+O_X+2
              sbc ##0
              sta dp:L_XL
              lda abs:PLAYER+O_X
              cmp ##0x10000-MINDIST
              lda abs:PLAYER+O_X+2
              adc ##0
              sta dp:L_XH
              lda abs:PLAYER+O_Y
              cmp ##MINDIST
              lda abs:PLAYER+O_Y+2
              sbc ##0
              sta dp:L_YL
              lda abs:PLAYER+O_Y
              cmp ##0x10000-MINDIST
              lda abs:PLAYER+O_Y+2
              adc ##0
              sta dp:L_YH
;;; MINDIST < half a tile, so the box touches at most two rows and columns.
              lda dp:L_XL
              xba
              lsr a
              sta dp:L_X
              lda dp:L_YL
              asl a
              ora dp:L_X
              tay
wallCell:
              lda abs:ACTORAT,y
              beq wallFirstClear
              cmp ##OBJLIST
              bcs wallFirstClear
              clc
              rts
wallFirstClear:
              lda dp:L_YL
              cmp dp:L_YH
              beq wallColumnClear
              lda abs:ACTORAT+2,y
              beq wallColumnClear
              cmp ##OBJLIST
              bcs wallColumnClear
              clc
              rts
wallColumnClear:
              lda dp:L_XL
              cmp dp:L_XH
              beq wallsClear
              lda abs:ACTORAT+128,y
              beq wallLastColumn
              cmp ##OBJLIST
              bcs wallLastColumn
              clc
              rts
wallLastColumn:
              lda dp:L_YL
              cmp dp:L_YH
              beq wallsClear
              lda abs:ACTORAT+130,y
              beq wallsClear
              cmp ##OBJLIST
              bcs wallsClear
              clc
              rts
wallsClear:
              lda dp:L_YL
              beq ylKept
              dec dp:L_YL
ylKept:       lda dp:L_YH
              cmp ##63
              bcs yhKept
              inc dp:L_YH
yhKept:       lda dp:L_XL
              beq xlKept
              dec dp:L_XL
xlKept:       lda dp:L_XH
              cmp ##63
              bcs xhKept
              inc dp:L_XH
xhKept:       lda dp:L_XL
              asl a
              sta dp:L_X
              lda dp:L_XH
              inc a
              asl a
              sta dp:L_Y
moveActorRow: ldx dp:L_X
              lda long:SIGHT_ROWS,x
              tax
              beq moveActorRowNext
actorCell:    lda abs:O_FLAGS,x
              bit ##FL_SHOOTABLE
              beq actorNext
              lda abs:O_TILEY,x
              cmp dp:L_YL
              bcc actorNext
              cmp dp:L_YH
              bcc moveActorInBox
              bne actorNext
;;; The spatial list also contains unmarked and overlapped actors.
moveActorInBox:
              lda abs:O_CELL,x
              asl a
              tay
              txa
              cmp abs:ACTORAT,y
              bne actorNext
              lda abs:PLAYER+O_X
              cmp abs:O_X,x
              lda abs:PLAYER+O_X+2
              sbc abs:O_X+2,x
              inc a
              cmp ##2
              bcc playerNearX
              bne actorNext
              lda abs:PLAYER+O_X
              cmp abs:O_X,x
              bne actorNext
playerNearX:
              lda abs:PLAYER+O_Y
              cmp abs:O_Y,x
              lda abs:PLAYER+O_Y+2
              sbc abs:O_Y+2,x
              inc a
              cmp ##2
              bcc playerNearY
              bne actorNext
              lda abs:PLAYER+O_Y
              cmp abs:O_Y,x
              bne actorNext
playerNearY:
              clc
              rts
actorNext:    lda abs:O_SNEXT,x
              tax
              bne actorCell
moveActorRowNext:
              inc dp:L_X
              inc dp:L_X
              lda dp:L_X
              cmp dp:L_Y
              bcs moveActorsClear
              jmp abs:.word0 (moveActorRow)
moveActorsClear:
              sec
              rts

;;; Carry set when the long A:L_T lies in [-0x10000, 0x10000].
InRange64K:   cmp ##0
              beq inRange
              cmp ##0xffff
              beq inRange
              cmp ##1
              bne outRange
              lda dp:L_T
              bne outRange
inRange:      sec
              rts
outRange:     clc
              rts

;;; Cmd_Use: the cardinal tile the player faces.
CmdUse:       lda abs:PLAYER+O_ANGLE
              cmp ##45
              bcc useEast
              cmp ##316
              bcs useEast
              cmp ##135
              bcc useNorth
              cmp ##225
              bcc useWest
              lda abs:PLAYER+O_TILEX
              sta dp:L_X
              lda abs:PLAYER+O_TILEY
              inc a
              sta dp:L_Y
              lda ##2
              ldy ##0
              bra useTile
useEast:      lda abs:PLAYER+O_TILEX
              inc a
              sta dp:L_X
              lda abs:PLAYER+O_TILEY
              sta dp:L_Y
              lda ##1
              ldy ##1
              bra useTile
useNorth:     lda abs:PLAYER+O_TILEX
              sta dp:L_X
              lda abs:PLAYER+O_TILEY
              dec a
              sta dp:L_Y
              lda ##0
              ldy ##0
              bra useTile
useWest:      lda abs:PLAYER+O_TILEX
              dec a
              sta dp:L_X
              lda abs:PLAYER+O_TILEY
              sta dp:L_Y
              lda ##3
              ldy ##1
useTile:      sta dp:L_ARG                ; di_* direction
              sty dp:L_U                  ; elevatorok
              lda dp:L_Y
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora dp:L_X
              tax
              lda abs:MAP1,x
              and ##255
              cmp ##98
              bne notPushable
              jmp abs:.word0 (PushWall)   ; L_X, L_Y, L_ARG
notPushable:  lda dp:L_X
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
              sta dp:L_DOOR
              lda abs:V_buttonheld+BT_USE
              beq useEdge
              rts                         ; a held Use is one press, not a sound every tic
useEdge:      lda dp:L_DOOR
              cmp ##21
              bne notElevator
              lda dp:L_U
              beq notElevator
              lda ##1
              sta abs:V_buttonheld+BT_USE
              ldx dp:L_SPOT
              lda dp:L_DOOR
              inc a
              jsr abs:.word0 (StoreLogicTile)  ; the flipped switch
              lda abs:PLAYER+O_TILEY
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:PLAYER+O_TILEX
              tax
              lda abs:MAP0,x
              and ##255
              cmp ##107
              beq secretExit
              lda ##EX_COMPLETED
              bra levelExit
secretExit:   lda ##EX_SECRETLEVEL
levelExit:    sta abs:V_playstate
              lda ##LEVELDONESND
              jmp abs:.word0 (LogicSound)
notElevator:  lda dp:L_DOOR
              bit ##0x80
              beq useNothing
              bit ##0x40
              bne useNothing              ; a moving wall is not a door
              lda ##1
              sta abs:V_buttonheld+BT_USE
              lda dp:L_DOOR
              and ##63
              jmp abs:.word0 (OperateDoor)
useNothing:   lda ##DONOTHINGSND
              jmp abs:.word0 (LogicSound)

;;; KnifeAttack and GunAttack read the last refresh's flags and transx.
KnifeAttack:  lda ##ATKKNIFESND
              jsr abs:.word0 (LogicSound)
              lda ##0xffff
              sta dp:L_BEST
              lda ##0x7fff
              sta dp:L_BEST+2
              stz dp:L_CHECK
              jsr abs:.word0 (closestTarget)
              ldx dp:L_CHECK
              beq knifeMiss
              lda dp:L_BEST+2             ; dist > 0x18000 misses
              bmi knifeHit
              cmp ##1
              bcc knifeHit
              bne knifeMiss
              lda dp:L_BEST
              cmp ##0x8001
              bcs knifeMiss
knifeHit:     jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              lsr a
              lsr a
              ldx dp:L_CHECK
              jmp abs:.word0 (DamageActor)
knifeMiss:    rts

;;; L_CHECK = the shootable, visible, centered actor with the least transx
;;; below L_BEST; L_BEST becomes its transx. L_CHECK is kept when none is.
;;; The visible list holds exactly the actors with FL_VISABLE, in the actor
;;; list's order, so the scan visits only those.
closestTarget:
              lda long:SIGHT_VISIBLE
              tax
              beq targetsDone
targetNext:   lda abs:O_FLAGS,x
              bit ##FL_SHOOTABLE
              beq targetSkip
              lda abs:O_VIEWX,x           ; abs(viewx-centerx) < shootdelta
              beq targetSkip
              lda abs:O_TRANSX,x          ; signed long transx < L_BEST
              cmp dp:L_BEST
              lda abs:O_TRANSX+2,x
              sbc dp:L_BEST+2
              bvc targetSigned
              eor ##0x8000
targetSigned: bpl targetSkip
              lda abs:O_TRANSX,x
              sta dp:L_BEST
              lda abs:O_TRANSX+2,x
              sta dp:L_BEST+2
              stx dp:L_CHECK
targetSkip:   lda abs:O_VNEXT,x
              tax
              bne targetNext
targetsDone:  rts

GunAttack:    lda abs:V_weapon
              asl a
              tax
              lda long:gunSounds,x
              jsr abs:.word0 (LogicSound)
              lda ##1
              sta abs:V_madenoise
              lda ##0xffff
              sta dp:L_BEST
              lda ##0x7fff
              sta dp:L_BEST+2
              stz dp:L_CHECK
gunSearch:    lda dp:L_CHECK
              sta dp:L_OLDBEST
              jsr abs:.word0 (closestTarget)
              lda dp:L_CHECK
              cmp dp:L_OLDBEST
              beq gunMiss
              ldx dp:L_CHECK
              jsr abs:.word0 (CheckLine)
              bcc gunSearch
              ldx dp:L_CHECK
              lda abs:O_TILEX,x
              sec
              sbc abs:PLAYER+O_TILEX
              bpl gunDx
              eor ##0xffff
              inc a
gunDx:        sta dp:L_T
              lda abs:O_TILEY,x
              sec
              sbc abs:PLAYER+O_TILEY
              bpl gunDy
              eor ##0xffff
              inc a
gunDy:        cmp dp:L_T
              bcs gunDist
              lda dp:L_T
gunDist:      sta dp:L_DIST
              cmp ##2
              bcs gunNotClose
              jsr abs:.word0 (Rnd)
              lsr a
              lsr a
              bra gunDamage
gunNotClose:  cmp ##4
              bcs gunFar
              jsr abs:.word0 (Rnd)
              tax
              lda abs:DIV6,x
              and ##255
              bra gunDamage
gunFar:       jsr abs:.word0 (Rnd)
              tax
              lda abs:DIV12,x
              and ##255
              cmp dp:L_DIST
              bcc gunMiss
              jsr abs:.word0 (Rnd)
              tax
              lda abs:DIV6,x
              and ##255
gunDamage:    ldx dp:L_CHECK
              jmp abs:.word0 (DamageActor)
gunMiss:      rts
gunSounds:    .word 0, ATKPISTOLSND, ATKMACHINEGUNSND, ATKGATLINGSND

;;; TakeDamage: A = points, X = the attacker.
TakeDamage:   stx abs:V_lastattacker
              ldy abs:V_victoryflag
              bne damageDone
              ldy abs:V_difficulty
              bne fullDamage
              lsr a
              lsr a
fullDamage:   sta dp:L_DAMAGE
              lda abs:V_health
              sec
              .public debugDamageOp
debugDamageOp:sbc dp:L_DAMAGE
              beq playerDied
              bpl healthKept
playerDied:   lda ##EX_DIED
              sta abs:V_playstate
              stx abs:V_killerobj
              lda ##0
healthKept:   sta abs:V_health
              lda dp:L_DAMAGE
              clc
              adc abs:V_damageflash
              sta abs:V_damageflash
              stz abs:V_gotgatgun
#ifdef WOLF_SPEAR
              stz abs:V_ouchface
              lda abs:V_health
              beq spearDamageFace
              lda dp:L_DAMAGE
              .public debugOuchOp
debugOuchOp:  cmp ##31
              bcc spearDamageFace
              lda ##1
              sta abs:V_ouchface
              stz abs:V_facecount
spearDamageFace:
#endif
              lda ##EV_STATUS|EV_FACE|EV_DAMAGE
              tsb abs:V_events
damageDone:   rts

HealSelf:     clc
              adc abs:V_health
              cmp ##101
              bcc healKept
              lda ##100
healKept:     sta abs:V_health
#ifdef WOLF_SPEAR
              stz abs:V_ouchface
#endif
              stz abs:V_gotgatgun
              lda ##EV_STATUS|EV_FACE
              tsb abs:V_events
              rts

GiveExtraMan: lda abs:V_lives
              cmp ##9
              bcs extraKept
              inc abs:V_lives
extraKept:    lda ##EV_STATUS
              tsb abs:V_events
              lda ##BONUS1UPSND
              jmp abs:.word0 (LogicSound)

              .public LogicGivePoints
;;; Cross-bank points entry for the tally. Establish LOGICBANK/LOGICDP
;;; for GivePoints, then restore the caller's DBR, D and flags.
LogicGivePoints:
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
              jsr abs:.word0 (GivePoints)
              pld
              plb
              plp
              rtl

;;; GivePoints: A = points (all original awards fit a word).
GivePoints:   clc
              adc abs:V_score
              sta abs:V_score
              lda abs:V_score_hi
              adc ##0
              sta abs:V_score_hi
extraLoop:    lda abs:V_score_hi
              cmp abs:V_nextextra_hi
              bcc pointsDone
              bne extraEarned
              lda abs:V_score
              cmp abs:V_nextextra
              bcc pointsDone
extraEarned:  lda abs:V_nextextra
              clc
              adc ##40000
              sta abs:V_nextextra
              lda abs:V_nextextra_hi
              adc ##0
              sta abs:V_nextextra_hi
              jsr abs:.word0 (GiveExtraMan)
              bra extraLoop
pointsDone:   lda ##EV_STATUS
              tsb abs:V_events
              rts

GiveAmmo:     sta dp:L_T
              lda abs:V_ammo
              bne ammoAdd
              lda abs:V_attackframe
              bne ammoAdd
              lda abs:V_chosenweapon      ; the knife was out
              sta abs:V_weapon
ammoAdd:      lda abs:V_ammo
              clc
              adc dp:L_T
              cmp ##100
              bcc ammoKept
              lda ##99
ammoKept:     sta abs:V_ammo
              lda ##EV_STATUS
              tsb abs:V_events
              rts

              .public GiveWeapon
GiveWeapon:   pha
              lda ##6
              jsr abs:.word0 (GiveAmmo)
              pla
              cmp abs:V_bestweapon
              bcc weaponGiven
              beq weaponGiven
              sta abs:V_bestweapon
              sta abs:V_weapon
              sta abs:V_chosenweapon
weaponGiven:  rts

;;; GetBonus: X = static record. Returns with the static removed or kept.
GetBonus:     stx dp:L_SAVE
              lda abs:6,x                 ; itemnumber
              asl a
              tax
              .byte 0x7c                  ; JMP (bonusTable,X)
              .word .word0 (bonusTable)
bonusTable:   .word .word0 (bonusNone), .word0 (bonusNone), .word0 (bonusGibs), .word0 (bonusAlpo)
              .word .word0 (bonusFirstAid), .word0 (bonusKey), .word0 (bonusKey), .word0 (bonusKey)
              .word .word0 (bonusKey), .word0 (bonusCross), .word0 (bonusChalice), .word0 (bonusBible)
              .word .word0 (bonusCrown), .word0 (bonusClip), .word0 (bonusClip2), .word0 (bonusMachineGun)
#ifdef WOLF_SPEAR
              .word .word0 (bonusChainGun), .word0 (bonusFood), .word0 (bonusFullHeal), .word0 (bonusAmmoBox)
              .word .word0 (bonusSpear)
bonusAmmoBox: lda abs:V_ammo
              cmp ##99
              beq bonusNone
              lda ##GETAMMOBOXSND
              jsr abs:.word0 (LogicSound)
              lda ##25
              jsr abs:.word0 (GiveAmmo)
              jmp abs:.word0 (bonusTaken)
bonusSpear:   lda ##1
              sta abs:V_spearflag
              sta abs:V_playstate
              lda ##GETSPEARSND
              jsr abs:.word0 (LogicSound)
              jmp abs:.word0 (bonusTaken)
#else
              .word .word0 (bonusChainGun), .word0 (bonusFood), .word0 (bonusFullHeal), .word0 (bonusNone)
              .word .word0 (bonusNone)
#endif
bonusNone:    rts
bonusFirstAid:lda abs:V_health
              cmp ##100
              beq bonusNone
              lda ##HEALTH2SND
              jsr abs:.word0 (LogicSound)
              lda ##25
              jsr abs:.word0 (HealSelf)
              jmp abs:.word0 (bonusTaken)
bonusKey:     ldx dp:L_SAVE
              lda abs:6,x
              sec
              sbc ##5
              tax
              lda long:keyBits,x
              and ##255
              tsb abs:V_keys
              lda ##EV_STATUS
              tsb abs:V_events
              lda ##GETKEYSND
              jsr abs:.word0 (LogicSound)
              jmp abs:.word0 (bonusTaken)
bonusCross:   lda ##BONUS1SND
              ldy ##100
              bra bonusTreasure
bonusChalice: lda ##BONUS2SND
              ldy ##500
              bra bonusTreasure
bonusBible:   lda ##BONUS3SND
              ldy ##1000
              bra bonusTreasure
bonusCrown:   lda ##BONUS4SND
              ldy ##5000
bonusTreasure:jsr abs:.word0 (LogicSound)
              tya
              jsr abs:.word0 (GivePoints)
              inc abs:V_treasurecount
              jmp abs:.word0 (bonusTaken)
bonusClip:    lda ##8
              bra bonusAmmo
bonusClip2:   lda ##4
bonusAmmo:    ldx abs:V_ammo
              cpx ##99
              beq bonusNone
              pha
              lda ##GETAMMOSND
              jsr abs:.word0 (LogicSound)
              pla
              jsr abs:.word0 (GiveAmmo)
              jmp abs:.word0 (bonusTaken)
bonusMachineGun:
              lda ##GETMACHINESND
              jsr abs:.word0 (LogicSound)
              lda ##2
              jsr abs:.word0 (GiveWeapon)
              jmp abs:.word0 (bonusTaken)
bonusChainGun:lda ##GETGATLINGSND
              jsr abs:.word0 (LogicSound)
              lda ##3
              jsr abs:.word0 (GiveWeapon)
              stz abs:V_facecount
              lda ##1
              sta abs:V_gotgatgun
              lda ##GATLINGTICS
              sta abs:V_gatling
              sep #0x20
              lda #0xad
              sta long:playerCounts
              rep #0x20
              lda ##EV_FACE
              tsb abs:V_events
              bra bonusTaken
bonusFullHeal:lda ##BONUS1UPSND
              jsr abs:.word0 (LogicSound)
              lda ##99
              jsr abs:.word0 (HealSelf)
              lda ##25
              jsr abs:.word0 (GiveAmmo)
              jsr abs:.word0 (GiveExtraMan)
              inc abs:V_treasurecount
              bra bonusTaken
bonusFood:    lda abs:V_health
              cmp ##100
              beq bonusRefused
              lda ##HEALTH1SND
              jsr abs:.word0 (LogicSound)
              lda ##10
              jsr abs:.word0 (HealSelf)
              bra bonusTaken
bonusAlpo:    lda abs:V_health
              cmp ##100
              beq bonusRefused
              lda ##HEALTH1SND
              jsr abs:.word0 (LogicSound)
              lda ##4
              jsr abs:.word0 (HealSelf)
              bra bonusTaken
bonusGibs:    lda abs:V_health
              cmp ##11
              bcs bonusRefused
              lda ##SLURPIESND
              jsr abs:.word0 (LogicSound)
              lda ##1
              jsr abs:.word0 (HealSelf)
bonusTaken:   lda ##EV_BONUS
              tsb abs:V_events
              .extern staticRevision
              lda long:staticRevision
              inc a
              sta long:staticRevision
              ldx dp:L_SAVE
              lda ##0xffff
              sta abs:2,x                 ; shapenum = -1: removed
              lda ##1
              sta abs:V_mapdirty          ; the renderer's object list changed
              bra pickupMark
bonusRefused: rts
;;; The cell keeps bit 1 of its object marker (refreshStatics looks for it) only
;;; while another pickup waits in it.
pickupMark:   lda abs:0,x
              sta dp:L_MC
              and ##0x0fc0
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0xfffe
              tax                         ; the cell's two-tile X bin
              ldy ##STATICS               ; and the group's first record
;;; One coarse X bin includes every record that could share this cell.
;;; The exact cell comparison below rejects its other column.
pickupGroup:  lda long:STATIC_INDEX+0x2,x
              eor long:STATIC_INDEX+0x4,x
              bne pickupMasked
pickupAdvance:txa
              clc
              adc ##140
              tax
              tya
              clc
              adc ##128
              tay
              cpy abs:V_laststat
              bcc pickupGroup
              ldx dp:L_MC
              sep #0x20
              lda long:OBJECT_MARKERS,x
              and #0xfd
              sta long:OBJECT_MARKERS,x
              rep #0x20
pickupKept:   rts
pickupMasked: sta dp:L_W                  ; one bit for each record, from Y
              stx dp:L_V
              sty dp:L_U
              tyx
pickupBit:    lsr dp:L_W
              bcs pickupSibling
              beq pickupGroupDone
pickupStep:   txa
              clc
              adc ##8
              tax
              bra pickupBit
pickupSibling:lda abs:2,x
              cmp ##0xffff
              beq pickupNext
              lda abs:4,x
              bit ##FL_BONUS
              beq pickupNext
              lda abs:0,x
              cmp dp:L_MC
              beq pickupKept
pickupNext:   lda dp:L_W
              bne pickupStep
pickupGroupDone:
              ldx dp:L_V
              ldy dp:L_U
              bra pickupAdvance
keyBits:      .byte 1,2,4,8

turnDivide:   cmp ##1024
              bcs turnDivideLarge
              tax
              lda abs:DIV20,x
              and ##255
              rts
turnDivideLarge:
              jsl long:MouseAngleDivide
              rts

#ifdef WOLF_SPEAR
              .section logiccode, text, root, noreorder
              .public SpearArrival
SpearArrival: php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              ldx ##OBJLIST
              stz dp:L_ANGLE
              stz dp:L_SPEED
              stz dp:L_SPEED+2
              jsr abs:.word0 (Thrust)
              pld
              plb
              plp
              rtl
#endif
