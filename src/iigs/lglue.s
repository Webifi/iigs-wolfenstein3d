#include "memmap.inc"
#include "progress.inc"
;;; Between the exact logic (bank $28 data, code in bank $0D) and the
;;; renderer, HUD and input in bank 2: level start, demo packets, the
;;; status mirrors and the logic's events.
#include "game.inc"
#include "logic.inc"
              .section gamecode, text, root, noreorder
              .public ApplyLevel, LogicPublish, StartDemo, DemoPacket, LogicControls
              .public LogicTicControls, LogicEvents, LogicWorldPublish
              .public demoMode, timeDemo, demoEnd, demoPtr, LoadFloorAssets, floorReady
              .public StartDemoPrompt
              .extern LogicSetupLevel, LogicNewGame, LogicMarkObjects
              .extern UseLogicActorVisibility
              .extern InitRayTextureDirectory, texBase, texBank, doorOrient, doorCells
              .extern doorPosition, wallDirty, levelIndex
              .extern StartDamageFlash, StartBonusFlash, UpdateHUD
              .extern LoadFloorData, ProbeFloorData, ExpandArt, setView, viewPal, tintFloorOffsets
              .extern InitFlash, weaponViewIndex, flowPhase, levelStart, UiFwKeep
              .extern I_GetTime, PlaySound, StopMusic, StopEffects, FloorMusic, CacheFloorMusic, CacheFloorEffects, UiLoadSign
              .extern levelHeldOn, levelPauseOn, levelRestarted, levelSeed
              .extern ResetTics

L             .equ LOGIC_BASE               ; long base of the logic bank
EV_STATUS     .equ 1
EV_FACE       .equ 2
EV_BONUS      .equ 8

;;; ApplyLevel: A = the starting rndindex. The floor's planes are in bank
;;; $28. Builds the logic level, then the renderer's map, stamps and doors.
ApplyLevel:   sta long:levelSeed
              pha
              stz abs:.word0 (flowPhase)
              jsl long:I_GetTime
              sta abs:.word0 (levelStart)
              stx abs:.word0 (levelStart+2)
              lda ##0
              sta abs:.word0 (levelHeldOn)
              sta abs:.word0 (levelRestarted)
              lda abs:.word0 (levelPauseOn)
              beq applyClock
              lda ##1
              sta abs:.word0 (levelRestarted)
              lda ##0
              sta abs:.word0 (levelPauseOn)
applyClock:   inc abs:.word0 (wallDirty)
              lda long:L+LEVELBLOCK+0x10
              sta abs:.word0 (levelIndex)
              ldx ##210
applyWallPtrs:lda long:L+LEVELBLOCK+0x100,x
              sta abs:.word0 (texBase),x
              dex
              dex
              bpl applyWallPtrs
              sep #0x20
              ldx ##105
applyWallBanks:
              lda long:L+LEVELBLOCK+0x1d4,x
              sta abs:.word0 (texBank),x
              dex
              bpl applyWallBanks
              rep #0x20
              pla
              jsl long:LogicSetupLevel
              lda long:L+V_doornum
              asl a
              sta abs:.word0 (doorBytes)
              ldx ##126
applyDoors:   lda ##0
              sta abs:.word0 (doorPosition),x
              lda long:L+DOORVERT,x
              sta abs:.word0 (doorOrient),x
              lda long:L+DOORTILE,x
              sta abs:.word0 (doorCells),x
              dex
              dex
              bpl applyDoors
;;; The renderer's map holds walls without the door-side bit.
              ldx ##4095
renderMap:    lda long:L+TILEMAP,x
              and ##255
              beq renderStore
              bit ##0x80
              bne renderStore
              and ##63
renderStore:  sta dp:MULW
              sep #0x20
              sta long:MAP,x
              lda #0
              sta long:OBJECT_MARKERS,x         ; no object markers yet
              rep #0x20
              txa
              asl a
              tax
              lda dp:MULW
              sta long:TILE_MIRROR,x
              lda ##0
              sta long:VIS_STAMPS,x         ; ray stamps
              txa
              lsr a
              tax
              dex
              txa
              and ##255
              bne renderMapProgress
              jsl long:Progress1
renderMapProgress:
              txa
              bpl renderMap
              stz dp:VISSTAMP
              stz dp:SP_COUNT
              lda ##0
              ldx ##510
clearSpriteCols:
              sta long:OLD_MARKS,x
              dex
              dex
              bpl clearSpriteCols
              ldx ##550
clearObjectStamps:
              sta long:OBJECT_STAMPS,x
              dex
              dex
              bpl clearObjectStamps
              ldx ##550*8
clearProjection:
              lda ##65535
              sta long:SPR_HISTORY+4,x
              txa
              sec
              sbc ##8
              tax
              bpl clearProjection
              jsl long:LogicMarkObjects
              jsr abs:.word0 (UseLogicActorVisibility)
              jsr abs:.word0 (InitRayTextureDirectory)
              lda ##0
              sta abs:.word0 (pwallPosition)
              lda ##1
              sta dp:FIRST
              sta abs:.word0 (hudDirty)
              jmp abs:.word0 (LogicPublish)

;;; World-only batches can change health; the other mirrors remain current.
LogicWorldPublish:
              lda long:L+V_health
              sta abs:.word0 (health)
              jmp abs:.word0 (LogicEvents)

;;; The player's view for the renderer, the status mirrors and the events.
LogicPublish: lda long:L+OBJLIST+O_X+1
              sta dp:PX
              lda long:L+OBJLIST+O_Y+1
              sta dp:PY
              lda long:L+OBJLIST+O_ANGLE
              asl a
              tax
              lda long:L+DEG1024,x
              sta dp:ANGLE
              lda long:L+V_health
              sta abs:.word0 (health)
              lda long:L+V_ammo
              sta abs:.word0 (ammo)
              lda long:L+V_keys
              sta abs:.word0 (keys)
              lda long:L+V_lives
              sta abs:.word0 (lives)
              lda long:L+V_score
              sta abs:.word0 (score)
              lda long:L+V_score_hi
              sta abs:.word0 (score+2)
              lda long:L+V_weapon
              sta abs:.word0 (weapon)
              lda long:L+V_chosenweapon
              sta abs:.word0 (chosenWeapon)
              lda long:L+V_bestweapon
              sta abs:.word0 (bestWeapon)
              lda long:L+V_weaponframe
              sta abs:.word0 (weaponFrame)
              lda long:L+V_killcount
              sta abs:.word0 (killCount)
              lda long:L+V_faceframe
              sta abs:.word0 (faceFrame)
;;; A queued player tic needs events immediately. Renderer/HUD mirrors
;;; are published after LogicFinish, before any consumer reads them.
LogicEvents:  lda long:L+V_events
              beq eventsDone
              pha
              lda ##0
              sta long:L+V_events
              pla
              bit ##EV_STATUS|EV_FACE
              beq noStatusEvent
              ldx ##1
              stx abs:.word0 (hudDirty)
noStatusEvent:bit ##EV_BONUS
              beq eventsDone
              jsl long:StartBonusFlash
eventsDone:   lda long:L+V_damageflash
              beq noDamageFlash
              pha
              lda ##0
              sta long:L+V_damageflash
              pla
              jsl long:StartDamageFlash
noDamageFlash:lda long:L+V_sound
              cmp ##0xffff
              beq noSound
              sta abs:.word0 (sfxEvent)
              jsl long:PlaySound
              lda ##0xffff
              sta long:L+V_sound
noSound:      rts

;;; StartDemo: A = demo number. Carry clear if it is unavailable.
StartDemo:    stz abs:.word0 (demoPrompt)
              bra demoRequest
;;; Explicit benchmark requests may use the loader's disk-swap prompt.
StartDemoPrompt:
              ldx ##1
              stx abs:.word0 (demoPrompt)
demoRequest:  cmp ##4
              bcc demoValid
              clc
              rts
demoValid:    sta abs:.word0 (demoNumber)
              asl a
              sta abs:.word0 (demoTmp)
              asl a
              clc
              adc abs:.word0 (demoTmp)    ; *6
              tax
              lda long:DEMOS,x
              bne demoExists
              clc
              rts
demoExists:   sta abs:.word0 (demoPtr)
              lda long:DEMOS+0x2,x
              sta abs:.word0 (demoTmp)
              asl a
              clc
              adc abs:.word0 (demoTmp)
              clc
              adc abs:.word0 (demoPtr)
              sta abs:.word0 (demoEnd)
              lda long:DEMOS+0x4,x
              sta abs:.word0 (floorWanted)
              cmp abs:.word0 (levelIndex)
              beq demoAssets
              ldx abs:.word0 (demoPrompt)
              bne demoAssets
              php
              jsl long:ProbeFloorData
              php
              jsl long:UiFwKeep
              plp
              bcc demoPresent
              plp
              clc
              rts
demoPresent:  plp
              lda abs:.word0 (floorWanted)
demoAssets:
              .extern ProbeDemoAssets, LoadDemoAssets
              lda abs:.word0 (demoPrompt)
              bne demoLoadPackets
              lda abs:.word0 (demoNumber)
              jsl long:ProbeDemoAssets
              bcc demoLoadPackets
              clc
              rts
demoLoadPackets:
              jsl long:StopMusic
              lda abs:.word0 (demoNumber)
              jsl long:LoadDemoAssets
              lda abs:.word0 (floorWanted)
              jsr abs:.word0 (LoadFloorAssets)
              bcs demoFloor
              rts
demoFloor:    lda abs:.word0 (floorWanted)
              tax
              lda ##3                     ; PlayDemo: NewGame, then gd_hard
              jsl long:LogicNewGame
              lda ##0                     ; US_InitRndT(false)
              jsr abs:.word0 (ApplyLevel)
              lda ##1
              sta abs:.word0 (demoMode)
              jsl long:I_GetTime
              sta dp:TIME
              sta dp:LASTTIC
              jsr abs:.word0 (ResetTics)
              sec
              rts

;;; Floor assets replace bank $28; the caller starts the new game after this.
              .extern OverlayFloorChanging, EnsureGameplayAssets, PlayCacheFill, RestoreTitleArt
LoadFloorAssets:
              sta abs:.word0 (floorWanted)
              cmp abs:.word0 (levelIndex)
              bne readDemoFloor
              lda abs:.word0 (floorReady)
              beq readDemoFloor
              cmp ##2
              bne floorArtReady
              jsl long:RestoreTitleArt
floorArtReady:
              jsl long:FloorMusic
              jsl long:EnsureGameplayAssets
              sec
              rts
readDemoFloor:jsl long:StopEffects
              jsl long:StopMusic
              lda ##5
              jsl long:UiLoadSign           ; the read masks interrupts for seconds: the sign goes up first
              lda abs:.word0 (floorWanted)
              ora ##0x2000                  ; keep the background; runtime progress belongs to the sign
              jsl long:OverlayFloorChanging
              stz abs:.word0 (floorReady)
              jsl long:LoadFloorData       ; its own sei: firmware context cannot take the game IRQ
              bcc demoFloorLoaded
              clc
              rts
demoFloorLoaded:
              lda ##1
              sta abs:.word0 (floorReady)
              jsl long:UiFwKeep             ; the next menu I/O must retain this drive state
              lda abs:.word0 (floorWanted)
              sta abs:.word0 (levelIndex)
              jsl long:PlayCacheFill        ; the play cache slots an earlier floor's art took
              jsl long:InitFlash
              lda ##1
              jsl long:UiLoadSign
              jsr abs:.word0 (CacheFloorMusic)
              jsl long:Progress22
              jsl long:CacheFloorEffects
;;; Finish art and view preparation before starting the new floor song.
              jsl long:EnsureGameplayAssets
              jsr abs:.word0 (ExpandArt)
              lda abs:.word0 (floorWanted)
              asl a
              tax
              lda abs:.word0 (tintFloorOffsets),x
              tax
              ldy ##0
floorPalette: lda long:TINTS,x
              sta abs:.word0 (viewPal),y
              inx
              inx
              iny
              iny
              cpy ##32
              bcc floorPalette
              ldx ##0
floorShades:  txa
              and ##31
              tay
              lda abs:.word0 (viewPal),y
              sta long:SHADING,x
              inx
              inx
              cpx ##288
              bcc floorShades
;;; Patch only color operands: normal painting pays no floor-selection cost.
              lda ##2
              sta dp:ENTRY+2
              lda long:L+FLOORCONFIG
              sta abs:.word0 (floorPatchLeft)
              ldx ##2
floorColor:   lda long:L+FLOORCONFIG,x
              sta dp:ENTRY
              sep #0x20
              lda long:L+FLOORCONFIG+2,x
              sta [ENTRY]
              rep #0x20
              inx
              inx
              inx
              dec abs:.word0 (floorPatchLeft)
              bne floorColor
              lda abs:.word0 (weaponViewIndex)
              lsr a
              jsr abs:.word0 (setView)
              lda ##2
              jsl long:UiLoadSign
              jsl long:FloorMusic
              sec
              rts

;;; PollControls keeps attack/use edges, then reads one exact demo packet.
DemoPacket:   sep #0x20
              lda #1
              sta long:PACKET_MARK           ; after floor/view setup, before packet and logic work
              rep #0x20
              jsr abs:.word0 (holdButtons)
              ldx abs:.word0 (demoPtr)
              lda long:DEMO_BANK,x
              and ##255
packetButtons:asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              tax
              lda long:CONTROL_RECORDS+0xa,x
              sta long:L+V_buttonstate+0
              lda long:CONTROL_RECORDS+0xe,x
              sta long:L+V_buttonstate+2
              lda long:CONTROL_RECORDS+0x1e,x
              sta long:L+V_buttonstate+6
              lda long:CONTROL_RECORDS+0x1a,x
              sta long:L+V_weaponchoice
packetButtonsDone:
              ldx abs:.word0 (demoPtr)
              lda long:DEMO_BANK+0x1,x
              jsr abs:.word0 (signedByte)
              asl a
              asl a                       ; times DEMOTICS
              sta long:L+V_controlx
              ldx abs:.word0 (demoPtr)
              lda long:DEMO_BANK+0x2,x
              jsr abs:.word0 (signedByte)
              asl a
              asl a
              sta long:L+V_controly
              lda ##0
              sta long:L+V_controlstrafe
              lda abs:.word0 (demoPtr)
              clc
              adc ##3
              sta abs:.word0 (demoPtr)
              cmp abs:.word0 (demoEnd)
              bne packetContinues
              lda ##1                     ; PollControls sets ex_completed before the last pass
              sta long:L+V_playstate
packetContinues:
              lda ##4
              sta long:L+V_tics
              rts
signedByte:   and ##255
              cmp ##128
              bcc signedDone
              ora ##0xff00
signedDone:   rts
;;; Only attack and use consume held-state history.
holdButtons:  lda long:L+V_buttonstate
              sta long:L+V_buttonheld
              lda long:L+V_buttonstate+6
              sta long:L+V_buttonheld+6
              rts

;;; Live input: A = command bits, X/Y = signed mouse counts, dp:TICS set.
;;; Populate the V_control* fields and button words consumed by player logic.
;;; V_controlstrafe carries lateral movement independently of turning.
LogicControls:stx abs:.word0 (mouseDX)
              sty abs:.word0 (mouseDY)
              sta abs:.word0 (controlBits)
              jsr abs:.word0 (holdButtons)
              lda dp:TICS
              sta long:L+V_tics
              lda abs:.word0 (controlBits)
              and ##128
              beq walkSpeed
              lda ##70                    ; RUNMOVE
              bra speedSet
walkSpeed:    lda ##35
speedSet:     sta abs:.word0 (moveSpeed)
              lda dp:TICS
              tay
              lda ##0
speedTimes:   cpy ##0
              beq speedDone
              clc
              adc abs:.word0 (moveSpeed)
              dey
              bra speedTimes
speedDone:    sta abs:.word0 (moveSpeed)  ; per frame
              stz abs:.word0 (ctrlX)
              stz abs:.word0 (ctrlY)
              stz abs:.word0 (ctrlStrafe)
              lda abs:.word0 (controlBits)
              bit ##1
              beq notForward
              lda abs:.word0 (ctrlY)
              sec
              sbc abs:.word0 (moveSpeed)
              sta abs:.word0 (ctrlY)
notForward:   lda abs:.word0 (controlBits)
              bit ##2
              beq notBack
              lda abs:.word0 (ctrlY)
              clc
              adc abs:.word0 (moveSpeed)
              sta abs:.word0 (ctrlY)
notBack:      lda abs:.word0 (controlBits)
              bit ##4
              beq notLeft
              lda abs:.word0 (ctrlX)
              sec
              sbc abs:.word0 (moveSpeed)
              sta abs:.word0 (ctrlX)
notLeft:      lda abs:.word0 (controlBits)
              bit ##8
              beq notRight
              lda abs:.word0 (ctrlX)
              clc
              adc abs:.word0 (moveSpeed)
              sta abs:.word0 (ctrlX)
notRight:     lda abs:.word0 (controlBits)
              bit ##256
              beq notSideLeft
              lda abs:.word0 (ctrlStrafe)
              clc
              adc abs:.word0 (moveSpeed)  ; positive strafes left (angle+90)
              sta abs:.word0 (ctrlStrafe)
notSideLeft:  lda abs:.word0 (controlBits)
              bit ##512
              beq notSideRight
              lda abs:.word0 (ctrlStrafe)
              sec
              sbc abs:.word0 (moveSpeed)
              sta abs:.word0 (ctrlStrafe)
notSideRight: lda abs:.word0 (mouseDX)
              clc
              adc abs:.word0 (ctrlX)
              sta abs:.word0 (ctrlX)
              lda abs:.word0 (mouseDY)
              clc
              adc abs:.word0 (ctrlY)
              sta abs:.word0 (ctrlY)
;;; bound movement to 100 per tic
              lda dp:TICS
              tay
              lda ##0
boundTimes:   cpy ##0
              beq boundDone
              clc
              adc ##100
              dey
              bra boundTimes
boundDone:    sta abs:.word0 (controlMax)
              lda abs:.word0 (controlBits)
              bit ##64
              beq mouseUnboundX
              lda abs:.word0 (ctrlX)
              jsr abs:.word0 (boundControl)
              bra mouseBoundX
mouseUnboundX:lda abs:.word0 (ctrlX)
mouseBoundX:  sta long:L+V_controlx
              lda abs:.word0 (ctrlY)
              jsr abs:.word0 (boundControl)
              sta long:L+V_controly
              lda abs:.word0 (ctrlStrafe)
              jsr abs:.word0 (boundControl)
              sta long:L+V_controlstrafe
;;; Attack, strafe and use stay as words; the weapon request is decoded.
              lda abs:.word0 (controlBits)
              and ##32
              jsr abs:.word0 (flag)
              sta long:L+V_buttonstate
              lda abs:.word0 (controlBits)
              and ##64
              jsr abs:.word0 (flag)
              sta long:L+V_buttonstate+2
              lda abs:.word0 (controlBits)
              and ##16
              jsr abs:.word0 (flag)
              sta long:L+V_buttonstate+6
              jmp abs:.word0 (setWeaponChoice)
flag:         beq flagOff
              lda ##1
flagOff:      rts
boundControl: bpl boundPositive
              eor ##0xffff
              inc a
              cmp abs:.word0 (controlMax)
              bcc boundNegKept
              lda abs:.word0 (controlMax)
boundNegKept: eor ##0xffff
              inc a
              rts
boundPositive:cmp abs:.word0 (controlMax)
              bcc boundKept
              lda abs:.word0 (controlMax)
boundKept:    rts

;;; The live queue supplies whole one-tic commands. Keep the generic
;;; entry for callers with a different tic count.
LogicTicControls:
              stx abs:.word0 (mouseDX)
              sty abs:.word0 (mouseDY)
              sta abs:.word0 (controlBits)
              and ##1023
              asl a
              asl a
              asl a
              asl a
              pha
              jsr abs:.word0 (holdButtons)
              plx
              lda ##1
              sta long:L+V_tics
              lda abs:.word0 (controlBits)
              and ##0xfc00
              beq normalTicTurn
              cmp ##0x1400
              bcs normalTicTurn
              xba
              lsr a
              tay
              lda abs:.word0 (controlBits)
              bit ##64                    ; a held strafe key still moves every tic
              bne normalTicTurn
              lda long:CONTROL_RECORDS,x
              beq fineKeyboardReady       ; both turn keys cancel
              bpl fineRight
              lda abs:.word0 (fineTurnUnits),y
              eor ##0xffff
              inc a
              bra fineKeyboardReady
fineRight:    lda abs:.word0 (fineTurnUnits),y
fineKeyboardReady:
              sta abs:.word0 (ctrlX)
              lda abs:.word0 (mouseDX)
              clc
              adc abs:.word0 (ctrlX)        ; mouse turning retains every count
              bra ticTurnReady
normalTicTurn:lda long:CONTROL_RECORDS,x
              clc
              adc abs:.word0 (mouseDX)
              pha
              lda abs:.word0 (controlBits)
              bit ##64
              bne ticStrafeBound
              pla
              bra ticTurnReady
ticStrafeBound:pla
              jsr abs:.word0 (boundTicControl)
ticTurnReady:
              sta long:L+V_controlx
              lda long:CONTROL_RECORDS+0x2,x
              clc
              adc abs:.word0 (mouseDY)
              jsr abs:.word0 (boundTicControl)
              sta long:L+V_controly
              lda long:CONTROL_RECORDS+0x4,x
              sta long:L+V_controlstrafe
              lda long:CONTROL_RECORDS+0x6,x
              sta long:L+V_buttonstate
              lda long:CONTROL_RECORDS+0x8,x
              sta long:L+V_buttonstate+2
              lda long:CONTROL_RECORDS+0xc,x
              sta long:L+V_buttonstate+6
setWeaponChoice:
              lda abs:.word0 (weaponRequest)
              cmp ##4
              bcc ticWeaponReady
              lda ##0xffff
ticWeaponReady:
              sta long:L+V_weaponchoice
              lda ##0xffff
              sta abs:.word0 (weaponRequest)
              rts
boundTicControl:
              bmi boundTicNegative
              cmp ##100
              bcc boundTicDone
              lda ##100
boundTicDone: rts
boundTicNegative:
              cmp ##0xff9c
              bcs boundTicDone
              lda ##0xff9c
              rts

              .section gamedata, data, root
              .public weaponRequest
              .public health, ammo, keys, lives, score, weapon, chosenWeapon, bestWeapon
              .public weaponFrame, levelState, hudDirty, sfxEvent, killCount, faceFrame
              .public doorBytes, pwallPosition
doorBytes:    .word 0
pwallPosition:.word 0
health:       .word 100
ammo:         .word 8
keys:         .word 0
lives:        .word 3
score:        .word 0,0
weapon:       .word 1
chosenWeapon: .word 1
bestWeapon:   .word 1
weaponFrame:  .word 0
levelState:   .word 0
hudDirty:     .word 1
sfxEvent:     .word 0xffff
killCount:    .word 0
faceFrame:    .word 0
demoMode:     .word 0
timeDemo:     .word 0
demoNumber:   .word 0
demoPrompt:   .word 0
demoPtr:      .word 0
demoEnd:      .word 0
demoTmp:      .word 0
floorWanted:  .word 0
floorReady:   .word 0                     ; 1: resident; 2: resident but title-covered art needs restoring
floorPatchLeft:.word 0
controlBits:  .word 0
fineTurnUnits:.word 0,35,70,140,0           ; twentieths of a degree
mouseDX:      .word 0
mouseDY:      .word 0
moveSpeed:    .word 0
controlMax:   .word 0
ctrlX:        .word 0
ctrlY:        .word 0
ctrlStrafe:   .word 0
weaponRequest:.word 0xffff

;;; JSL from logic with DB=$28/D=$1100. Publish only the camera, then cast
;;; in the renderer's bank/direct page. LogicPublish publishes HUD/events later.
              .section flowcode, text, root, noreorder
              .public CastLogicView
              .extern castFrame, castMinX, castMaxX
CastLogicView:
              phb
              phd
              pea #0x0202
              plb
              plb
              lda ##0x1000
              tcd
              lda long:L+OBJLIST+O_X+1
              sta dp:PX
              lda long:L+OBJLIST+O_Y+1
              sta dp:PY
              lda long:L+OBJLIST+O_ANGLE
              asl a
              tax
              lda long:L+DEG1024,x
              sta dp:ANGLE
              jsr abs:.word0 (castFrame)
              lda dp:VISSTAMP
              ldx abs:.word0 (castMinX)
              ldy abs:.word0 (castMaxX)
              pld
              plb
              rtl
