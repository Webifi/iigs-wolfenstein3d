;;; Moving-wall ray intersections and level restart/death transitions.
;;; Gameplay state lives in LOGIC_BASE; this bridge resets the renderer,
;;; display effects, and tic queue when a floor is restarted.
#include "memmap.inc"
#include "game.inc"
#include "picture_config.inc"
#include "logic.inc"
              .section gamecode, text, root, noreorder
              .public PWallHit, RestartLevel, DeathTick, killerObject, deathPhase, deathTarget, deathClock
              .extern ResetTics
              .extern LogicMarkActorRays, UseRayActorVisibility
              .extern hitCoordinate, mulFrac, levelIndex, levelState, ApplyLevel
              .extern inputSerial, InitFlash, I_GetTime, LogicNewGame, LogicPublish
              .extern pwallPosition, UpdateHUD, hudDirty, UiGameOver
              .extern DeathFadeStart, DeathFadeStep, DeathSettle, DeathReveal, DeathLoading

L             .equ LOGIC_BASE

;;; Restart according to levelState. A death consumes one life and resets
;;; the loadout to a pistol with 8 rounds and the score at floor entry.
RestartLevel: lda abs:.word0 (levelState)
              bne restartNeeded
              rts
restartNeeded:cmp ##3
              beq newGame
              cmp ##1
              bne restartFloor
              lda long:L+V_lives
              dec a
              sta long:L+V_lives
              bpl livesLeft
              lda ##3
              sta abs:.word0 (levelState)
              jsr abs:.word0 (DeathSettle)
              jsr abs:.word0 (showGameOver)
              jsr abs:.word0 (UiGameOver)
              rts
livesLeft:    lda ##100
              sta long:L+V_health
              lda ##1
              sta long:L+V_weapon
              sta long:L+V_bestweapon
              sta long:L+V_chosenweapon
              lda ##8
              sta long:L+V_ammo
              lda ##0
              sta long:L+V_keys
              sta long:L+V_attackframe
              sta long:L+V_attackcount
              sta long:L+V_weaponframe
              lda long:L+V_oldscore
              sta long:L+V_score
              lda long:L+V_oldscore_hi
              sta long:L+V_score_hi
              bra restartFloor
newGame:      lda abs:.word0 (levelIndex)
              tax
              lda ##2
              jsl long:LogicNewGame
restartFloor: stz abs:.word0 (deathPhase)
              jsr abs:.word0 (DeathLoading)
              jsl long:I_GetTime
              and ##255
              jsr abs:.word0 (ApplyLevel)
              jsr abs:.word0 (DeathReveal)
              jsl long:InitFlash
              stz abs:.word0 (levelState)
              lda ##1
              sta abs:.word0 (hudDirty)
              jsr abs:.word0 (UpdateHUD)
              jsl long:I_GetTime
              sta dp:TIME
              sta dp:LASTTIC
              jsr abs:.word0 (ResetTics)
              rts

;;; Add pwallPosition/64 of the ray step; reject a hit beyond either cell edge.
;;; Both high tile bits select this path; door IDs never index past the array.
PWallHit:     lda dp:SIDE
              beq wallVerticalStep
              lda dp:DY
              bra wallPartialStep
wallVerticalStep:
              lda dp:DX
wallPartialStep:
              ldy abs:.word0 (pwallPosition)
              jsr abs:.word0 (mulFrac)
              clc
              adc dp:DIST
              bcs wallRayPass
              cmp dp:TX
              bcs wallRayPass
              cmp dp:TY
              bcs wallRayPass
              sta dp:DIST
              jsr abs:.word0 (hitCoordinate)
              lda dp:TILE
              and ##63
              dec a
              asl a
              ldx dp:SIDE
              bne wallHorizontalPage
              inc a
wallHorizontalPage:
              sta dp:PAGE
#if WOLF_PREPARED
              lda dp:RAY
#else
              lda dp:TEXU
#endif
              ldx dp:SIDE
              bne wallHorizontalFlip
              ldx dp:STEPX
              bpl wallTextureReady
#if WOLF_PREPARED
              eor ##4095
#else
              eor ##63
#endif
              bra wallTextureReady
wallHorizontalFlip:
              ldx dp:STEPY
              bmi wallTextureReady
#if WOLF_PREPARED
              eor ##4095
#else
              eor ##63
#endif
wallTextureReady:
#if WOLF_PREPARED
              sta dp:RAY
              and ##63
#endif
              sta dp:TEXU
              sec
              rts
wallRayPass:  clc
              rts

;;; Death uses DOC tics. The world stops while the final view faces its killer.
DeathTick:    lda abs:.word0 (levelState)
              cmp ##1
              beq dyingPlayer
              clc
              rts
dyingPlayer:  lda abs:.word0 (deathPhase)
              beq startDeath
              cmp ##1
              bne deathAfterTurn
              jmp abs:.word0 (turnToKiller)
deathAfterTurn: cmp ##2
              bne waitAfterDeath
              jmp abs:.word0 (deathFizzle)
waitAfterDeath:
              lda abs:.word0 (inputSerial)
              cmp abs:.word0 (deathInput)
              bne deathRestart
              lda dp:TIME
              sec
              sbc abs:.word0 (deathClock)
              cmp ##100
              bcc deathWaitIdle
deathRestart: jsr abs:.word0 (RestartLevel)
              lda abs:.word0 (levelState)
              cmp ##3
              bne deathRestarted
              clc
              rts
deathRestarted:
              sec
              rts
deathWaitIdle: clc
              rts
startDeath:   jsl long:LogicMarkActorRays
              jsr abs:.word0 (UseRayActorVisibility)
              inc abs:.word0 (deathPhase)
              lda long:L+V_killerobj
              tax
              lda long:L+O_X+1,x
              sec
              sbc dp:PX
              sta abs:.word0 (deathDX)
              bpl deathXPositive
              eor ##65535
              inc a
deathXPositive:
              sta dp:AI_X
              lda dp:PY
              sec
              sbc long:L+O_Y+1,x
              sta abs:.word0 (deathDY)
              bpl deathYPositive
              eor ##65535
              inc a
deathYPositive:
              sta dp:AI_Y
deathNormalize:
              lda dp:AI_X
              ora dp:AI_Y
              cmp ##16
              bcc deathNormalized
              lsr dp:AI_X
              lsr dp:AI_Y
              bra deathNormalize
deathNormalized:
              stz dp:AI_DIR
              lda dp:AI_Y
              cmp dp:AI_X
              bcc deathXMajor
              pha
              lda dp:AI_X
              sta dp:AI_Y
              pla
              sta dp:AI_X
              inc dp:AI_DIR
deathXMajor:  lda dp:AI_X
              asl a
              asl a
              asl a
              asl a
              ora dp:AI_Y
              tax
              lda long:L+DEATHATAN,x
              and ##255
              ldx dp:AI_DIR
              beq deathBaseAngle
              eor ##65535
              sec
              adc ##256
deathBaseAngle:
              ldx abs:.word0 (deathDX)
              bpl deathEastern
              eor ##65535
              sec
              adc ##512
deathEastern: ldx abs:.word0 (deathDY)
              bpl deathNorthern
              eor ##65535
              sec
              adc ##1024
deathNorthern:
              and ##1023
              sta abs:.word0 (deathTarget)
              sec
              rts
turnToKiller: lda abs:.word0 (deathTarget)
              sec
              sbc dp:ANGLE
              and ##1023
              cmp ##512
              bcc deathTurnForward
              ora ##0xfc00
deathTurnForward:
              sta abs:.word0 (deathRemaining)
              lda dp:TICS
              asl a
              clc
              adc dp:TICS
              asl a                     ; 2 original angle degrees per tic
              sta abs:.word0 (deathTurn)
              lda abs:.word0 (deathRemaining)
              bmi deathTurnBackward
              cmp abs:.word0 (deathTurn)
              bcc deathReachKiller
              lda abs:.word0 (deathTurn)
              clc
              adc dp:ANGLE
              bra deathNewAngle
deathTurnBackward:
              eor ##65535
              inc a
              cmp abs:.word0 (deathTurn)
              bcc deathReachKiller
              lda dp:ANGLE
              sec
              sbc abs:.word0 (deathTurn)
deathNewAngle:
              and ##1023
              sta dp:ANGLE
              cmp abs:.word0 (deathTarget)
              bne deathTurned
deathReachKiller:
              lda abs:.word0 (deathTarget)
              sta dp:ANGLE
              inc abs:.word0 (deathPhase)
              lda dp:TIME
              sta abs:.word0 (deathClock)
              jsr abs:.word0 (DeathFadeStart)
deathTurned:  sec
              rts

;;; The palettes of the view go to the red of Died() over 70 tics (ui_death.s).
deathFizzle:  lda dp:TIME
              sec
              sbc abs:.word0 (deathClock)
              jsr abs:.word0 (DeathFadeStep)
              bcc deathIdleJump
              inc abs:.word0 (deathPhase)
              lda dp:TIME
              sta abs:.word0 (deathClock)
              lda abs:.word0 (inputSerial)
              sta abs:.word0 (deathInput)
deathIdleJump:
              clc
              rts
showGameOver: ldx ##0
              sep #0x20
              lda #0x11                  ; white source-font text over the red view
deathText:    sta dp:AI_TMP
              rep #0x20
              lda abs:.word0 (deathGameOver),x
              phx
              tax
              sep #0x20
              lda dp:AI_TMP
              sta long:BANK_E1,x
              plx
              inx
              inx
              cpx ##deathGameOverBytes
              bcc deathText
              rep #0x20
              rts

              .section gamedata, data, root
killerObject: .word 0
deathPhase:   .word 0
deathTarget:  .word 0
deathDX:      .word 0
deathDY:      .word 0
deathRemaining: .word 0
deathTurn:    .word 0
deathClock:   .word 0
deathInput:   .word 0
#include "death.inc"
