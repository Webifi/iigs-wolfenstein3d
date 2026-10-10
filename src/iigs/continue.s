;;; End of a floor. LoadFloorAssets is the only disk reader. It replaces
;;; bank $28, so the persistent words are copied out and written back.
#include "memmap.inc"
#include "game.inc"
#include "logic.inc"
#include "campaign.inc"
              .section gamecode, text, root, noreorder
              .extern MarkFloorVisited
              .public LevelFlow, EnterFloor, StartFloor
              .extern LoadFloorAssets, ApplyLevel, LogicPublish
              .extern I_GetTime, ResetTics, MenuReturnTitle, setView, SelectMusic, UiLoadDone, floorRearm
              .extern levelState, levelIndex, nextFloor, flowPhase
              .extern flowStep, flowAck, inputSerial, musicRequest, deathPhase
              .extern PrepareMusic, StartPreparedMusic
              .extern TallyOpen, TallyTick, TallyWait
              .extern tallyKill, tallySecret, tallyTreasure, tallySec
              .extern VictoryShow, EndShow
              .extern PlayCacheLeave
#ifdef WOLF_SPEAR
              .extern campaignSpear
#endif
              .extern screenHold, weaponViewIndex, ShowView

;;; Phase 0 latches a completed floor and selects its campaign route.
;;; Phase 1 shows the ending; phases 2 and 3 run and acknowledge the tally.
;;; Phase 4 enters the next floor. Spear phase 6 waits for the pickup pause
;;; before advancing to phase 4. Other values leave the state unchanged.
LevelFlow:    lda abs:.word0 (flowPhase)
              beq flowLatch
              cmp ##1
              beq flowEpisode
              cmp ##2
              beq flowTick
              cmp ##3
              beq flowWait
#ifdef WOLF_SPEAR
              cmp ##6
              bne flowNotSpearWait
              jmp abs:.word0 (flowSpearWait)
flowNotSpearWait:
#endif
              cmp ##4
              bne flowIdle
              jmp abs:.word0 (EnterFloor)
flowIdle:     rts
flowEpisode:  jmp abs:.word0 (EpisodeEnd)
flowTick:     jsr abs:.word0 (TallyTick)
              jsr abs:.word0 (NoteRatio)
              rts
flowWait:     jsr abs:.word0 (NoteRatio)
              jmp abs:.word0 (TallyWait)
flowLatch:    lda abs:.word0 (levelIndex)
              cmp ##CAMPAIGN_FLOORS
#ifdef WOLF_SPEAR
              bcc flowValid
              jmp abs:.word0 (flowInvalid)
flowValid:
#else
              bcs flowInvalid
#endif
              asl a
              tax
#ifdef WOLF_SPEAR
              lda long:LOGIC_BASE+V_spearflag
              beq flowOrdinary
              lda long:campaignSpear,x
              bra flowRoute
flowOrdinary:
#endif
              lda abs:.word0 (levelState)
              cmp ##6
              beq flowVictory
              cmp ##5
              beq flowSecret
              lda long:campaignNormal,x
              bra flowRoute
flowSecret:   lda long:campaignSecret,x
              bra flowRoute
flowVictory:  lda long:campaignVictory,x
flowRoute:    cmp ##65534
              beq flowInvalid
              cmp ##65535
              beq flowEnding
#ifdef WOLF_SPEAR
              pha
              and ##0x4000
              sta abs:.word0 (holdPose)
              pla
#endif
              pha
              and ##0x3fff
              sta abs:.word0 (nextFloor)
              pla
              bit ##0x8000
              bne flowDirect
              lda ##2
              sta abs:.word0 (flowPhase)
              jmp abs:.word0 (TallyOpen)
flowDirect:
#ifdef WOLF_SPEAR
              lda abs:.word0 (holdPose)
              beq flowDirectNow
              jsl long:I_GetTime
              sta abs:.word0 (spearAt)
              lda ##6
              sta abs:.word0 (flowPhase)
              rts
flowSpearWait:
              jsl long:I_GetTime
              sec
              sbc abs:.word0 (spearAt)
              cmp ##150
              bcc flowSpearWaiting
flowDirectNow:
#endif
              lda ##4
              sta abs:.word0 (flowPhase)
#ifdef WOLF_SPEAR
flowSpearWaiting:
#endif
              rts
flowEnding:   sta abs:.word0 (nextFloor)
              stz abs:.word0 (holdScreen)
              lda ##1
              sta abs:.word0 (flowPhase)
              rts
;;; A non-final boss can die on a floor without an ending route.
flowInvalid:  lda ##0
              sta long:LOGIC_BASE+V_playstate
              sta long:LOGIC_BASE+V_victoryflag
              stz abs:.word0 (levelState)
              rts

;;; JSL. Native, 16-bit A and X. A is a source floor index in this campaign.
;;; The caller has already stored the saved words in bank $28.
;;; Direct page, the data bank, X and Y come back. Carry clear means the
;;; floor is in play. Carry set means the floor number was rejected or
;;; LoadFloorAssets returned carry clear.
StartFloor:   php
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              lda ##0x1000
              tcd
              lda 8,s
              cmp ##CAMPAIGN_FLOORS
              bcs startBad
              sta abs:.word0 (nextFloor)
              lda ##1
              sta abs:.word0 (holdCounts)
#ifdef WOLF_SPEAR
              stz abs:.word0 (holdPose)
#endif
              lda abs:.word0 (nextFloor)
              jsr abs:.word0 (OpenFloor)
              lda ##0
              rol a
              sta abs:.word0 (holdOk)
              bra startKeep
startBad:     stz abs:.word0 (holdOk)
startKeep:    lda abs:.word0 (holdOk)
              beq startStack
              stz abs:.word0 (levelState)
              stz abs:.word0 (flowPhase)
              stz abs:.word0 (deathPhase)
              jsl long:I_GetTime
              sta dp:LASTTIC
              jsr abs:.word0 (ResetTics)
startStack:   lda abs:.word0 (holdOk)
              sta 8,s
startLeave:   pld
              plb
              ply
              plx
              pla
              plp
              cmp ##0                    ; PLP restored the caller's Z flag
              bne startOk
              sec
              rtl
startOk:      clc
              rtl

;;; The tally has been acknowledged. nextFloor is the floor to enter.
EnterFloor:   phd
              phb
              php
              rep #0x30
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              lda ##0x1000
              tcd
              stz abs:.word0 (holdCounts)
              lda abs:.word0 (nextFloor)
              cmp ##CAMPAIGN_FLOORS
              bcs enterFail
              jsr abs:.word0 (OpenFloor)
              bcc enterFail
              jsl long:MarkFloorVisited
              stz abs:.word0 (levelState)
              stz abs:.word0 (deathPhase)
              jsl long:I_GetTime
              sta dp:LASTTIC
              jsr abs:.word0 (ResetTics)
              bra enterOut
enterFail:    lda ##5
              sta abs:.word0 (flowPhase)
enterOut:     plp
              plb
              pld
              rts

;;; A is the floor. Carry set when the new floor is running.
OpenFloor:    sta abs:.word0 (nextFloor)
              lda abs:.word0 (screenHold)
              pha
              lda ##1
              sta abs:.word0 (screenHold)
              jsr abs:.word0 (snapStats)
              lda abs:.word0 (nextFloor)
              jsr abs:.word0 (LoadFloorAssets)
              bcc openFail
              jsr abs:.word0 (restoreStats)
              jsl long:I_GetTime
              and ##255
              jsr abs:.word0 (ApplyLevel)
#ifdef WOLF_SPEAR
              lda abs:.word0 (holdPose)
              beq poseRestored
              ldx ##6
restorePose:  lda abs:.word0 (spearPose),x
              sta long:LOGIC_BASE+OBJLIST+O_X,x
              dex
              dex
              bpl restorePose
              lda abs:.word0 (spearPose+8)
              sta long:LOGIC_BASE+OBJLIST+O_ANGLE
              lda abs:.word0 (spearKeys)
              sta long:LOGIC_BASE+V_keys
              .extern SpearArrival
              jsl long:SpearArrival
              stz abs:.word0 (holdPose)
              lda ##0
              sta long:LOGIC_BASE+V_spearflag
poseRestored:
#endif
              lda abs:.word0 (holdCounts)
              beq openView
              lda abs:.word0 (holdKills)
              sta long:LOGIC_BASE+V_killcount
              lda abs:.word0 (holdTreas)
              sta long:LOGIC_BASE+V_treasurecount
              jsr abs:.word0 (LogicPublish)
;;; ShowView's InitHUD draws the new floor number with the new picture.
;;; Keep the tally and its HUD intact while the loading box is visible.
openView:     lda abs:.word0 (weaponViewIndex)
              lsr a
              jsr abs:.word0 (setView)
              jsl long:floorRearm           ; the load sign drops, then this floor's lights arm again
              pla
              sta abs:.word0 (screenHold)
              bne openReady
              jsr abs:.word0 (ShowView)
openReady:    sec
              rts
openFail:     pla
              sta abs:.word0 (screenHold)
              clc
              rts

snapStats:
#ifdef WOLF_SPEAR
              ldx ##6
snapPose:     lda long:LOGIC_BASE+OBJLIST+O_X,x
              sta abs:.word0 (spearPose),x
              dex
              dex
              bpl snapPose
              lda long:LOGIC_BASE+OBJLIST+O_ANGLE
              sta abs:.word0 (spearPose+8)
              lda long:LOGIC_BASE+V_keys
              sta abs:.word0 (spearKeys)
#endif
              lda long:LOGIC_BASE+V_difficulty
              sta abs:.word0 (holdDiff)
              lda long:LOGIC_BASE+V_score
              sta abs:.word0 (holdScore)
              lda long:LOGIC_BASE+V_score_hi
              sta abs:.word0 (holdScore+2)
              lda long:LOGIC_BASE+V_nextextra
              sta abs:.word0 (holdExtra)
              lda long:LOGIC_BASE+V_nextextra_hi
              sta abs:.word0 (holdExtra+2)
              lda long:LOGIC_BASE+V_lives
              sta abs:.word0 (holdLives)
              lda long:LOGIC_BASE+V_health
              sta abs:.word0 (holdHealth)
              lda long:LOGIC_BASE+V_ammo
              sta abs:.word0 (holdAmmo)
              lda long:LOGIC_BASE+V_bestweapon
              sta abs:.word0 (holdBest)
              lda long:LOGIC_BASE+V_weapon
              sta abs:.word0 (holdWeapon)
              lda long:LOGIC_BASE+V_chosenweapon
              sta abs:.word0 (holdChosen)
              lda long:LOGIC_BASE+V_killcount
              sta abs:.word0 (holdKills)
              lda long:LOGIC_BASE+V_treasurecount
              sta abs:.word0 (holdTreas)
              rts

restoreStats: lda abs:.word0 (nextFloor)
              sta long:LOGIC_BASE+V_mapon
              lda abs:.word0 (holdDiff)
              sta long:LOGIC_BASE+V_difficulty
              lda abs:.word0 (holdScore)
              sta long:LOGIC_BASE+V_score
              lda abs:.word0 (holdScore+2)
              sta long:LOGIC_BASE+V_score_hi
              lda abs:.word0 (holdExtra)
              sta long:LOGIC_BASE+V_nextextra
              lda abs:.word0 (holdExtra+2)
              sta long:LOGIC_BASE+V_nextextra_hi
              lda abs:.word0 (holdLives)
              sta long:LOGIC_BASE+V_lives
              lda abs:.word0 (holdHealth)
              sta long:LOGIC_BASE+V_health
              lda abs:.word0 (holdAmmo)
              sta long:LOGIC_BASE+V_ammo
              lda abs:.word0 (holdBest)
              sta long:LOGIC_BASE+V_bestweapon
              lda abs:.word0 (holdWeapon)
              sta long:LOGIC_BASE+V_weapon
              lda abs:.word0 (holdChosen)
              sta long:LOGIC_BASE+V_chosenweapon
              lda ##0
              sta long:LOGIC_BASE+V_keys
              sta long:LOGIC_BASE+V_victoryflag
              sta long:LOGIC_BASE+V_playstate
              sta long:LOGIC_BASE+V_faceframe
              sta long:LOGIC_BASE+V_attackframe
              sta long:LOGIC_BASE+V_attackcount
              sta long:LOGIC_BASE+V_weaponframe
              rts

;;; Ratios use the current episode's compact save-compatible table.
NoteRatio:    lda abs:.word0 (flowPhase)
              cmp ##3
              bne noteDone
              lda abs:.word0 (levelIndex)
              asl a
              tax
              lda long:campaignRatioOffset,x
              cmp ##65535
              beq noteDone
              tax
              lda abs:.word0 (tallyKill)
              sta abs:.word0 (ratioTable),x
              lda abs:.word0 (tallySecret)
              sta abs:.word0 (ratioTable+2),x
              lda abs:.word0 (tallyTreasure)
              sta abs:.word0 (ratioTable+4),x
              lda abs:.word0 (tallySec)
              sta abs:.word0 (ratioTable+6),x
noteDone:     rts

;;; The boss exit. Victory picture, both ending pages, then the title.
EpisodeEnd:   phd
              phb
              php
              rep #0x30
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              lda ##0x1000
              tcd
              lda abs:.word0 (holdScreen)
              bne epHeld
              lda ##0xffff                  ; the play cache before the victory song
              jsl long:PlayCacheLeave       ; (home disk) asks for another disk
#ifdef WOLF_SPEAR
              lda ##CAMPAIGN_MUSIC_VICTORY
#else
              lda ##24
#endif
              sta abs:.word0 (musicRequest)
              jsl long:PrepareMusic
              jsl long:VictoryShow
              jsl long:StartPreparedMusic
              bcc epVictoryOK
              jmp abs:.word0 (epBoot)
epVictoryOK:
              lda abs:.word0 (inputSerial)
              sta abs:.word0 (flowAck)
              lda ##1
              sta abs:.word0 (holdScreen)
#ifdef WOLF_SPEAR
              jmp abs:.word0 (epOut)
#else
              bra epOut
#endif
epHeld:       lda abs:.word0 (inputSerial)
              cmp abs:.word0 (flowAck)
              beq epOut
              lda abs:.word0 (holdScreen)
              cmp ##1
              bne epPage
              stz abs:.word0 (flowStep)
#ifdef WOLF_SPEAR
              lda ##CAMPAIGN_MUSIC_ENDING
              jsl long:SelectMusic
#endif
              lda abs:.word0 (levelIndex)
              asl a
              tax
              lda long:campaignEndBase,x
              jsl long:EndShow
              bcs epBoot
              lda abs:.word0 (inputSerial)
              sta abs:.word0 (flowAck)
              lda ##2
              sta abs:.word0 (holdScreen)
#ifdef WOLF_SPEAR
              jmp abs:.word0 (epOut)
#else
              bra epOut
#endif
epPage:       inc abs:.word0 (flowStep)
              lda abs:.word0 (flowStep)
              pha
              lda abs:.word0 (levelIndex)
              asl a
              tax
              pla
              cmp long:campaignEndCount,x
              bcs epBoot
              clc
              adc long:campaignEndBase,x
              jsl long:EndShow
              bcs epBoot
              lda abs:.word0 (inputSerial)
              sta abs:.word0 (flowAck)
#ifdef WOLF_SPEAR
              jmp abs:.word0 (epOut)
#else
              bra epOut
#endif
epBoot:       lda ##1
              sta abs:.word0 (holdMark)
              jsl long:MenuReturnTitle
              jsr abs:.word0 (setView)
              stz abs:.word0 (levelState)
              stz abs:.word0 (flowPhase)
              stz abs:.word0 (holdScreen)
              jsl long:I_GetTime
              sta dp:LASTTIC
              jsr abs:.word0 (ResetTics)
              lda ##2
              sta abs:.word0 (holdMark)
epOut:        plp
              plb
              pld
              rts

              .section gamedata, data, root
              .public holdMark, ratioTable
holdDiff:     .word 0
holdScore:    .word 0, 0
holdExtra:    .word 0, 0
holdLives:    .word 0
holdHealth:   .word 0
holdAmmo:     .word 0
holdBest:     .word 0
holdWeapon:   .word 0
holdChosen:   .word 0
holdKills:    .word 0
holdTreas:    .word 0
holdCounts:   .word 0
holdOk:       .word 0
holdScreen:   .word 0
holdMark:     .word 0
#ifdef WOLF_SPEAR
holdPose:     .word 0
spearAt:      .word 0
spearKeys:    .word 0
spearPose:    .space 10
ratioTable:   .space CAMPAIGN_RATIO_BYTES
#else
ratioTable:   .word 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
              .word 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0

#endif
#include "campaign-flow.inc"
