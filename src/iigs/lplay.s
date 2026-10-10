;;; Gameplay scheduling and actor state transitions. The caller supplies
;;; V_tics, V_controlx/y and V_buttonstate before entering LogicFrame.
;;; Live play may run world actors in batches while advancing the player
;;; separately; LogicFinish refreshes visibility and advances V_framecount.
#include "memmap.inc"
#include "logic.inc"
#include "logic_dp.inc"
#include "tics.inc"
              .section logiccode, text, root, noreorder
              .public LogicFrame, LogicTick, LogicPlayerTick, LogicWorldRun, LogicFinish, Rnd, Mul16, MulHigh16, NewState, CellOfX, RemoveObj, GetNewActor
              .public InitActorList, thinkTable, actionTable
              .public ResetLogicTimers, playerCounts
              .extern ClearSightActors, IndexSightActor, ForgetSightActor
              .extern MoveDoors, MovePWalls, LogicRefresh
              .extern MarkActorCell, MarkActorCellTail, speedTickTest
              .extern T_Stand, T_Path, T_Chase, T_DogChase, T_Player, T_Attack
              .extern A_DeathScream, T_Shoot, T_Bite
              .extern T_BJRun, T_BJJump, T_BJYell, T_BJDone
#ifdef WOLF_SPEAR
              .extern T_Ghosts, T_Projectile, T_Will
              .extern A_Breathing, A_Dormant, A_Relaunch, A_Slurpie, A_Smoke
              .extern A_StartAttack, A_Victory, T_Launch, T_UShoot
#else
              .extern T_Fake, T_Fat, T_Ghosts, T_Gift, T_Projectile, T_Schabb
              .extern A_HitlerMorph, A_MechaSound, A_Slurpie, A_Smoke, A_StartDeathCam
              .extern T_FakeFire, T_GiftThrow, T_SchabbThrow
#endif

FL_SHOOTABLE  .equ 1
FL_NEVERMARK  .equ 4
FL_NONMARK    .equ 128

;;; JSL from any bank. D, DBR and P are restored; A/X/Y are scratch.
LogicFrame:
              php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              jsr abs:.word0 (advanceLogic)
              jsr abs:.word0 (finishLogic)
              pld
              plb
              plp
              rtl

;;; Live catch-up advances the world without repeating visibility or drawing.
LogicTick:
              php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              jsr abs:.word0 (advanceLogic)
              pld
              plb
              plp
              rtl

;;; TICSTEP leaves the player at one tic; only the other world work batches.
LogicPlayerTick:
              php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              jsr abs:.word0 (playerCounts)
playerTicBegin:
              jsr abs:.word0 (playerThink)
playerTicEnd:
              pld
              plb
              plp
              rtl

;;; A whole world run has an integral number of TICSTEP groups. V_tics
;;; stays 1 inside: every door, push wall and actor takes each safe step.
LogicWorldRun:
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
              sta dp:L_WORLDLEFT
              sta dp:L_WORLDCOUNT
              lda ##1
worldRunBegin:sta abs:V_tics
              lda long:ACTIVE_DOORS
              bpl worldTic
              lda abs:V_pwallstate
              bne worldTic
;;; No actor runs until this pass ends, so neither system can start here.
worldDoorsIdle:
              bra worldActorBatch
worldTic:     jsr abs:.word0 (worldDoors)
              dec dp:L_WORLDLEFT
              bne worldTic
;;; No other thinker runs inside one actor's batch. Keep its cell unmarked
;;; until its last tic, then publish its final cell once.
worldActorBatch:
              sep #0x20
              lda #0x60
              sta long:markActor
              sta long:MarkActorCell
              sta long:speedTickTest      ; every movement pass has V_tics = 1
              rep #0x20
              ldx abs:OBJLIST+O_NEXT
              beq worldActorsDone
;;; The player does not move during this run, so area eligibility is
;;; checked once per actor before its batch of one-tic updates.
batchActor:   stx dp:L_OB
              lda abs:O_ACTIVE,x
              bne batchActive
              ldy abs:O_AREA,x
              lda abs:AREABYPLAYER,y
              and ##255
              beq nextBatchActor
batchActive:  lda abs:O_FLAGS,x
              and ##FL_NONMARK|FL_NEVERMARK
              bne batchCellReady
              lda abs:O_CELL,x
              asl a
              tay
              lda ##0
              sta abs:ACTORAT,y
batchCellReady:
              lda dp:L_WORLDCOUNT
              sta dp:L_WORLDLEFT
batchActorTic:jsr abs:.word0 (actorOneTic)
actorBatchReturned:
              lda abs:O_STATE,x
              beq nextBatchActor
              dec dp:L_WORLDLEFT
              bne batchActorTic
              lda abs:O_FLAGS,x
              jsr abs:.word0 (markActorReady)
actorPublishReturned:
              lda abs:O_X+2,x
              jsr abs:.word0 (MarkActorCellTail)
nextBatchActor:
              lda abs:O_NEXT,x
              tax
              bne batchActor
worldActorsDone:
              sep #0x20
              lda #0xbd
              sta long:markActor
              sta long:MarkActorCell
              lda #0xac                  ; LDY abs:V_tics outside the live batch
              sta long:speedTickTest
              rep #0x20
              stz abs:V_madenoise          ; shots since the last world run
worldRunDone:
              pld
              plb
              plp
              rtl

LogicFinish:
              php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              jsr abs:.word0 (finishLogic)
              pld
              plb
              plp
              rtl

advanceLogic:
              stz abs:V_madenoise
              jsr abs:.word0 (playerCounts)
advanceTicBegin:
              jsr abs:.word0 (worldDoors)
              jsr abs:.word0 (playerThink)
              ldx abs:OBJLIST+O_NEXT
              beq ticFinished
              jsr abs:.word0 (actorList)
ticFinished:
              rts

;;; The player's two states have no state timer or actor-map marks.
playerThink:  ldx ##OBJLIST
              stx dp:L_OB
playerThinkReady:
              lda abs:OBJLIST+O_STATE
              cmp ##s_attack
              beq playerThinkAttack
#if !defined(WOLF_SPEAR)
              cmp ##s_deathcam
              bne playerThinkNormal
              rts
playerThinkNormal:
#endif
              jmp abs:.word0 (T_Player)
playerThinkAttack:
              jmp abs:.word0 (T_Attack)

;;; Re-enable countdowns after a full saved-state restore. P/DBR/D/X/Y kept.
ResetLogicTimers:
              php
              sep #0x20
              lda #0xad
              sta long:playerCounts
              plp
              rtl

playerCounts: lda abs:V_gatling
              beq gatlingFreeze
              sec
              sbc abs:V_tics
              bcs gatlingLeft
              lda ##0
gatlingLeft:  sta abs:V_gatling
              bne gatlingQuiet
gatlingFreeze:
              sep #0x20
              lda #0x60
              sta long:playerCounts
              rep #0x20
gatlingQuiet: rts

worldDoors:
              jsr abs:.word0 (MoveDoors)
              jsr abs:.word0 (MovePWalls)
worldDoorsDone:
              rts

actorList:
actorLoop:    lda abs:O_ACTIVE,x
              bne actorGo
              ldy abs:O_AREA,x
              lda abs:AREABYPLAYER,y
              and ##255
              bne actorGo
              lda abs:O_NEXT,x          ; neither active nor in a connected area
              tax
              bne actorLoop
              rts
actorGo:      jsr abs:.word0 (DoActor)
actorLoopReturned:
              lda abs:O_NEXT,x          ; RemoveObj leaves next intact
              tax
              bne actorLoop
              rts

finishLogic:
              jsr abs:.word0 (LogicRefresh)
logicObjectsDone:

              inc abs:V_framecount
              rts

;;; US_RndT: A = rndtable[++rndindex & 255]. X and Y are kept.
Rnd:          phx
              lda abs:V_rndindex
              inc a
              and ##255
              sta abs:V_rndindex
rngValue:     tax
              lda abs:RNDTABLE,x
              and ##255
              plx
              clc                 ; carry clear on return
              rts

;;; NewState: X = object, Y = state.
NewState:     tya
              sta abs:O_STATE,x
              lda abs:ST_TICS,y
              sta abs:O_TICS,x
              rts

;;; Y = actorat offset of object X's tile; A = the cell index.
CellOfX:      lda abs:O_TILEX,x
              cmp abs:O_SX,x
              beq actorRowCurrent
              jsr abs:.word0 (IndexSightActor)
              lda abs:O_TILEX,x
actorRowCurrent:
              xba
              lsr a
              lsr a
              ora abs:O_TILEY,x
              sta abs:O_CELL,x
              asl a
              tay
              lsr a
              rts

;;; actorLoop calls only an active actor or one in a connected area.
DoActor:      stx dp:L_OB
actorRuns:    lda abs:O_FLAGS,x
              and ##FL_NONMARK|FL_NEVERMARK
              bne marksKept
              lda abs:O_CELL,x
              asl a
              tay
              lda ##0
              sta abs:ACTORAT,y
marksKept:    lda abs:O_TICS,x
              bne transitional
actorThinkZero:
              ldy abs:O_STATE,x
              lda abs:ST_THINK,y
idleActorBranch:
              beq markActor
              tax
              .byte 0xfc                  ; JSR (thinkTable,X)
              .word .word0 (thinkTable)
              ldx dp:L_OB
              lda abs:O_STATE,x
              bne markActor
              jmp abs:.word0 (RemoveObj)
transitional: sec
              sbc abs:V_tics
              sta abs:O_TICS,x
              beq stateExpired
              bpl thinkNow
stateExpired: ldy abs:O_STATE,x
              lda abs:ST_ACTION,y
              beq nextState
              tax
              .byte 0xfc                  ; JSR (actionTable,X)
              .word .word0 (actionTable)
              ldx dp:L_OB
              ldy abs:O_STATE,x
              bne nextState
              jmp abs:.word0 (RemoveObj)
nextState:    lda abs:ST_NEXT,y
              sta abs:O_STATE,x
              bne stateExists
              jmp abs:.word0 (RemoveObj)
stateExists:  tay
              lda abs:ST_TICS,y
              bne addTics
              stz abs:O_TICS,x
              bra thinkNow
addTics:      clc
              adc abs:O_TICS,x
              sta abs:O_TICS,x
              beq stateExpired
              bmi stateExpired
thinkNow:     ldy abs:O_STATE,x
              lda abs:ST_THINK,y
              beq markActor
              tax
              .byte 0xfc                  ; JSR (thinkTable,X)
              .word .word0 (thinkTable)
              ldx dp:L_OB
              lda abs:O_STATE,x
              bne markActor
              jmp abs:.word0 (RemoveObj)
markActor:    lda abs:O_FLAGS,x
markActorReady:
              bit ##FL_NEVERMARK
              bne marked
              lda abs:O_TILEX,x           ; CellOfX, with its row index current
              cmp abs:O_SX,x
              bne markReindex
markCell:     xba
              lsr a
              lsr a
              ora abs:O_TILEY,x
              sta abs:O_CELL,x
              asl a
              tay
actorCellReturned:
              lda abs:O_FLAGS,x
              bit ##FL_NONMARK
              beq markIt
              lda abs:ACTORAT,y
              bne marked
markIt:       txa
              sta abs:ACTORAT,y
marked:       rts
markReindex:  jsr abs:.word0 (IndexSightActor)
              lda abs:O_TILEX,x
              bra markCell

;;; Zero-timer states without a thinker cannot change during this batch.
;;; One call still observes the terminal state before the final map update.
batchNoThink: lda ##1
              sta dp:L_WORLDLEFT
              rts
;;; Live batches enter with V_tics=1 and nonnegative state countdowns.
;;; The separate zero-timer path skips thinkerless batches without a patch.
actorOneTic:  lda abs:O_TICS,x
              bne actorDecTic
              ldy abs:O_STATE,x
              lda abs:ST_THINK,y
              beq batchNoThink
              tax
              .byte 0xfc
              .word .word0 (thinkTable)
              ldx dp:L_OB
              lda abs:O_STATE,x
              bne markActor
              jmp abs:.word0 (RemoveObj)
actorDecTic:  dec a
              sta abs:O_TICS,x
              bne thinkNow
              jmp abs:.word0 (stateExpired)

thinkTable:   .word 0, .word0 (T_Stand), .word0 (T_Path), .word0 (T_Chase), .word0 (T_DogChase)
              .word .word0 (T_Player), .word0 (T_Attack), .word0 (T_BJRun), .word0 (T_BJJump)
#ifdef WOLF_SPEAR
              .word .word0 (T_Ghosts), .word0 (T_Projectile), .word0 (T_Will)
#else
              .word .word0 (T_Fake), .word0 (T_Fat), .word0 (T_Ghosts), .word0 (T_Gift), .word0 (T_Projectile), .word0 (T_Schabb)
#endif
actionTable:  .word 0, .word0 (A_DeathScream), .word0 (T_Shoot), .word0 (T_Bite)
              .word .word0 (T_BJYell), .word0 (T_BJDone)
#ifdef WOLF_SPEAR
              .word .word0 (A_Breathing), .word0 (A_Dormant), .word0 (A_Relaunch), .word0 (A_Slurpie), .word0 (A_Smoke)
              .word .word0 (A_StartAttack), .word0 (A_Victory), .word0 (T_Launch), .word0 (T_UShoot)
#else
              .word .word0 (A_HitlerMorph), .word0 (A_MechaSound), .word0 (A_Slurpie), .word0 (A_Smoke), .word0 (A_StartDeathCam)
              .word .word0 (T_FakeFire), .word0 (T_GiftThrow), .word0 (T_Projectile), .word0 (T_SchabbThrow)
#endif

;;; InitActorList: every record free, prev-linked; the player takes record 0.
InitActorList:
              jsr abs:.word0 (ClearSightActors)
              ldx ##OBJLIST
freeRecords:  txa
              clc
              adc ##OBJSIZE
              sta abs:O_PREV,x
              stz abs:O_NEXT,x
              tax
              cpx ##OBJLIST+OBJSIZE*MAXACTORS
              bcc freeRecords
              stz abs:OBJLIST+OBJSIZE*(MAXACTORS-1)+O_PREV
              lda ##OBJLIST
              sta abs:V_objfreelist
              stz abs:V_lastobj
              jmp abs:.word0 (GetNewActor)

;;; GetNewActor: X = the cleared new record, appended to the list.
GetNewActor:  ldx abs:V_objfreelist
              bne actorFree
              brk                         ; no free spots in objlist
actorFree:    lda abs:O_PREV,x
              sta abs:V_objfreelist
              stz abs:0,x
              stz abs:2,x
              stz abs:4,x
              stz abs:6,x
              stz abs:8,x
              stz abs:10,x
              stz abs:12,x
              stz abs:14,x
              stz abs:16,x
              stz abs:18,x
              stz abs:20,x
              stz abs:22,x
              stz abs:24,x
              stz abs:26,x
              stz abs:28,x
              stz abs:30,x
              stz abs:32,x
              stz abs:34,x
              stz abs:36,x
              stz abs:38,x
              stz abs:40,x
              stz abs:42,x
              stz abs:44,x
              stz abs:46,x
              stz abs:48,x
              stz abs:50,x
              stz abs:52,x
              stz abs:54,x
              stz abs:56,x
              lda ##0xffff
              sta abs:O_SX,x
              stz abs:O_VNEXT,x
              stz abs:O_VPREV,x
              lda abs:V_lastobj
              beq firstActor
              tay
              txa
              sta abs:O_NEXT,y
firstActor:   lda abs:V_lastobj
              sta abs:O_PREV,x
              stx abs:V_lastobj
              rts

;;; RemoveObj: X = the object; unlink it and return it to the free list.
RemoveObj:    jsr abs:.word0 (ForgetSightActor)
              stz abs:O_STATE,x
              txa
              cmp abs:V_lastobj
              bne notLast
              lda abs:O_PREV,x
              sta abs:V_lastobj
              bra prevLink
notLast:      ldy abs:O_NEXT,x
              lda abs:O_PREV,x
              sta abs:O_PREV,y
prevLink:     ldy abs:O_PREV,x
              lda abs:O_NEXT,x
              sta abs:O_NEXT,y
              lda abs:V_objfreelist
              sta abs:O_PREV,x
              stx abs:V_objfreelist
              rts

;;; Mul16: L_PROD = A * Y, unsigned 16 x 16 -> 32 bits. X/Y survive.
;;; Select complete byte-product rows before evaluating either input byte.
Mul16:        phx
              cpy ##256
              bcs mulWordWide
              sta dp:L_T
              tya
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta long:mulWordLow+2
              sta long:mulWordHigh+2
              lda dp:L_T
              and ##255
              asl a
              tax
mulWordLow:   lda long:0x000000,x
              sta dp:L_PROD
              stz dp:L_PROD+2
              lda dp:L_T+1
              and ##255
              asl a
              tax
mulWordHigh:  lda long:0x000000,x
              clc
              adc dp:L_PROD+1
              sta dp:L_PROD+1
              plx
              rts
mulWordWide:  sta dp:L_T
              sty dp:L_U
              tya
              and ##255
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta long:mulWord00+2
              sta long:mulWord10+2
              lda dp:L_U+1
              and ##255
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta long:mulWord01+2
              sta long:mulWord11+2
              lda dp:L_T
              and ##255
              asl a
              tax
mulWord00:    lda long:0x000000,x
              sta dp:L_PROD
mulWord01:    lda long:0x000000,x
              sta dp:L_V
              lda dp:L_T+1
              and ##255
              asl a
              tax
mulWord11:    lda long:0x000000,x
              sta dp:L_PROD+2
mulWord10:    lda long:0x000000,x
              clc
              adc dp:L_V
              sta dp:L_V
              lda ##0
              adc ##0
              sta dp:L_W
              lda dp:L_V
              clc
              adc dp:L_PROD+1
              sta dp:L_PROD+1
              lda dp:L_W
              adc dp:L_PROD+3
              sta dp:L_PROD+3
              plx
              rts

;;; A = (A * Y) >> 16. X and Y survive.
MulHigh16:    phx
              sta dp:L_T
              cpy ##256
              bcs highWordWide
              tya
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta long:highWordLow+2
              sta long:highWordHigh+2
              lda dp:L_T
              and ##255
              asl a
              tax
highWordLow:  lda long:0x000001,x
              and ##255
              sta dp:L_V
              lda dp:L_T+1
              and ##255
              asl a
              tax
highWordHigh: lda long:0x000000,x
              clc
              adc dp:L_V
              xba
              and ##255
              plx
              rts
highWordWide: sty dp:L_U
              tya
              and ##255
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta long:highWord00+2
              sta long:highWord10+2
              lda dp:L_U+1
              and ##255
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta long:highWord01+2
              sta long:highWord11+2
              lda dp:L_T
              and ##255
              asl a
              tax
highWord00:   lda long:0x000001,x
              and ##255
              sta dp:L_V
highWord01:   lda long:0x000000,x
              clc
              adc dp:L_V
              sta dp:L_V
              lda dp:L_T+1
              and ##255
              asl a
              tax
highWord11:   lda long:0x000000,x
              sta dp:L_PROD+2
highWord10:   lda long:0x000000,x
              clc
              adc dp:L_V
              sta dp:L_V
              lda ##0
              adc ##0
              sta dp:L_W
              lda dp:L_V+1
              clc
              adc dp:L_PROD+2
              plx
              rts
