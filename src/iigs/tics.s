;;; DOC time makes queued commands; each command advances one normal tic.
#include "memmap.inc"
#include "game.inc"
#include "logic.inc"
#include "tics.inc"
              .section gamecode, text, root, noreorder
              .public ResetTics, buildNewTiccmds, tryRunTics
              .extern I_GetTime, PollTicInput, LogicTicControls, LogicWorldPublish, LogicEvents
              .extern LogicTick, LogicPlayerTick, LogicWorldRun
              .extern LogicFrame, DemoPacket, demoPtr, demoEnd
              .extern DeferWallOutputs, FinishWallOutputs, CompleteWallOutputs
              .extern demoMode, weaponRequest, inputTimed, inputUntil, inputHead, inputLimit

ResetTics:    sta abs:.word0 (lastMadeTic)
              sta abs:.word0 (worldAt)
              stz abs:.word0 (ticCount)
              stz abs:.word0 (fineTurnFrames)
              stz abs:.word0 (fineNewFrame)
              inc abs:.word0 (ticEpoch)
              rts

;;; Advance lastMadeTic only after a command has entered the queue.
;;; A full queue leaves the remaining DOC time due on the following frame.
              .public J13FrameSite
buildNewTiccmds:
J13FrameSite: jsl long:I_GetTime
              sta dp:TIME
              sec
              sbc abs:.word0 (lastMadeTic)
              sta abs:.word0 (buildLeft)
              lda abs:.word0 (inputHead)
              sta abs:.word0 (inputLimit)
buildNext:    lda abs:.word0 (ticCount)
              cmp ##MAXTICS
              bcs buildDone
              lda abs:.word0 (buildLeft)
              beq buildDone
              lda abs:.word0 (lastMadeTic)
              sta abs:.word0 (inputUntil)
              lda abs:.word0 (ticEpoch)
              sta abs:.word0 (buildEpoch)
              lda ##1
              sta dp:TICS
              sta abs:.word0 (inputTimed)
              jsr abs:.word0 (PollTicInput)
              stz abs:.word0 (inputTimed)
              stx abs:.word0 (commandMouseX)
              sty abs:.word0 (commandMouseY)
              lda abs:.word0 (demoMode)
              bne buildDone
              lda abs:.word0 (ticEpoch)
              cmp abs:.word0 (buildEpoch)
              bne buildDone             ; a menu or a new game reset the queue
              jsr abs:.word0 (BuildFineTurn)
              lda abs:.word0 (ticCount)
              asl a
              asl a
              asl a
              tax
              lda dp:COMMAND
              sta abs:.word0 (ticCommands),x
              lda abs:.word0 (commandMouseX)
              sta abs:.word0 (ticCommands+2),x
              lda abs:.word0 (commandMouseY)
              sta abs:.word0 (ticCommands+4),x
              lda abs:.word0 (weaponRequest)
              sta abs:.word0 (ticCommands+6),x
              lda ##0xffff
              sta abs:.word0 (weaponRequest)
              inc abs:.word0 (lastMadeTic)
              inc abs:.word0 (ticCount)
              dec abs:.word0 (buildLeft)
              bra buildNext
buildDone:
              rts

;;; The first three rendered frames of a held turn each get one small
;;; step, even when a frame queues several tics. Both input polls share
;;; fineNewFrame so they cannot issue two fine steps in the same frame.
;;; Bits 10-12 carry 1/2/3 for that step, 4 for the other fine-frame tics.
BuildFineTurn:
              lda dp:COMMAND
              and ##12
              bne fineHeld
              stz abs:.word0 (fineTurnFrames)
              bra fineMade
fineHeld:     ldx abs:.word0 (fineTurnFrames)
              lda abs:.word0 (fineNewFrame)
              bne fineNextFrame
              txa
              bne fineSameFrame
fineNextFrame:cpx ##4
              bcs fineMade
              inx
              stx abs:.word0 (fineTurnFrames)
              cpx ##4
              bcs fineMade
              txa
              xba
              asl a
              asl a
              bra fineStamp
fineSameFrame:cpx ##4
              bcs fineMade
              lda ##0x1000
fineStamp:    ora dp:COMMAND
              sta dp:COMMAND
fineMade:     stz abs:.word0 (fineNewFrame)
              rts

tryRunTics:   lda abs:.word0 (demoMode)
              beq runLiveTics
              jmp abs:.word0 (runRecordedTics)
runLiveTics:  lda ##1
              sta abs:.word0 (fineNewFrame)
              jsr abs:.word0 (buildNewTiccmds)
              lda abs:.word0 (demoMode)
              beq runLiveCommands
              rts
runLiveCommands:
#if TICSTEP > 1
              lda dp:LASTTIC
              clc
              adc abs:.word0 (ticCount)
              sec
              sbc abs:.word0 (worldAt)
              beq worldCaughtUp
              bmi worldCaughtUp
              ldx ##0
worldSteps:   pha
              txa
              clc
              adc ##TICSTEP
              tax
              pla
              sec
              sbc ##TICSTEP
              beq worldReady
              bpl worldSteps
worldReady:   txa
              pha
              clc
              adc abs:.word0 (worldAt)
              sta abs:.word0 (worldAt)
              pla
              jsl long:LogicWorldRun
              jsr abs:.word0 (LogicWorldPublish)
worldCaughtUp:
              jsr abs:.word0 (buildNewTiccmds) ; keys arriving during world work
              lda abs:.word0 (demoMode)
              beq runCommands
              rts
#endif
runCommands:  stz abs:.word0 (ticRead)
              lda abs:.word0 (ticCount)
              sta abs:.word0 (ticLeft)
              beq commandsDone
runCommand:   lda long:LOGIC_BASE+V_playstate
              bne commandsDone
              ldx abs:.word0 (ticRead)
              lda abs:.word0 (ticCommands+6),x
              sta abs:.word0 (weaponRequest)
              lda abs:.word0 (ticCommands),x
              sta dp:COMMAND
              lda abs:.word0 (ticCommands+4),x
              tay
              lda abs:.word0 (ticCommands+2),x
              tax
              lda ##1
              sta dp:TICS
              lda dp:COMMAND
              jsr abs:.word0 (LogicTicControls)
#if TICSTEP > 1
              jsl long:LogicPlayerTick
#else
              jsl long:LogicTick
#endif
              inc dp:LASTTIC
              jsr abs:.word0 (LogicEvents)
              lda abs:.word0 (ticRead)
              clc
              adc ##8
              sta abs:.word0 (ticRead)
              dec abs:.word0 (ticLeft)
              bne runCommand
commandsDone: stz abs:.word0 (ticCount)
              rts

;;; Recorded controls represent indivisible four-tic updates. Use the same
;;; elapsed-time frontier as live commands, retaining any remaining clock debt.
;;; With MAXTICS above 20, prefer five packets before painting. At seven
;;; packets of clock debt, allow up to min(MAXTICS, 32) tics in this pass.
;;; Any remaining debt stays queued. Visibility and events run after every
;;; packet: they affect the next packet's combat and cannot be deferred.
;;; Publishing the view and HUD belongs to the caller, once before painting.
              .section flowcode, text, root
runRecordedTics:
              lda dp:TIME
              sec
              sbc dp:LASTTIC
#if MAXTICS > 20
              cmp ##28
              bcs recordedBacklog
              cmp ##20
              bcc recordedCount
              lda ##20
              bra recordedCount
recordedBacklog:
#endif
#if MAXTICS > 32
              cmp ##32
              bcc recordedCount
              lda ##32
#elif MAXTICS >= 4
              cmp ##MAXTICS
              bcc recordedCount
              lda ##MAXTICS
#else
              ; A recorded packet cannot be split into one-tic live input.
              lda ##4
#endif
recordedCount:
              sta abs:.word0 (ticLeft)
              lsr a
              lsr a
              sta abs:.word0 (recordedFullFrom)
              asl a
              clc
              adc abs:.word0 (recordedFullFrom)
              clc
              adc abs:.word0 (demoPtr)
              cmp abs:.word0 (demoEnd)
              bcc recordedLookback
              lda abs:.word0 (demoEnd)
recordedLookback:
              tax
;;; Small controls can leave the quantized camera unchanged. Keep full wall
;;; outputs from the last substantial motion request onward; all packets still
;;; advance the world, including the small and zero-motion trailing commands.
recordedFindMove:
              cpx abs:.word0 (demoPtr)
              beq recordedLastMove
              dex
              dex
              dex
              lda long:DEMO_BANK+0x1,x         ; horizontal control, signed byte
              clc
              adc ##9
              and ##255
              cmp ##19                   ; outside -9..9
              bcs recordedLastMove
              lda long:DEMO_BANK+0x2,x         ; vertical control, signed byte
              clc
              adc ##3
              and ##255
              cmp ##7                    ; outside -3..3
              bcc recordedFindMove
recordedLastMove:
              stx abs:.word0 (recordedFullFrom)
recordedNext: lda abs:.word0 (ticLeft)
              cmp ##4
              bcc recordedDone
              sec
              sbc ##4
              sta abs:.word0 (ticLeft)
              ldx abs:.word0 (demoPtr)
              cpx abs:.word0 (recordedFullFrom)
              bcs recordedFinalView
              jsr abs:.word0 (DeferWallOutputs)
              bra recordedViewReady
recordedFinalView:
              jsr abs:.word0 (FinishWallOutputs)
recordedViewReady:
              lda ##4
              sta dp:TICS
              jsr abs:.word0 (DemoPacket)
              jsl long:LogicFrame
recordedState:
              jsr abs:.word0 (LogicEvents)
              lda dp:LASTTIC
              clc
              adc ##4
              sta dp:LASTTIC
              sta abs:.word0 (lastMadeTic)
              sta abs:.word0 (worldAt)
              lda long:LOGIC_BASE+V_playstate
              bne recordedDone
              lda abs:.word0 (demoPtr)
              cmp abs:.word0 (demoEnd)
              bcc recordedNext
recordedDone: jmp abs:.word0 (CompleteWallOutputs)

              .section gamedata, data, root
              .public lastMadeTic, worldAt, ticCount, ticCommands
lastMadeTic:  .word 0
worldAt:      .word 0
ticCount:     .word 0
ticRead:      .word 0
ticLeft:      .word 0
recordedFullFrom: .word 0
ticEpoch:     .word 0
buildEpoch:   .word 0
buildLeft:    .word 0
commandMouseX:.word 0
commandMouseY:.word 0
fineTurnFrames:.word 0
fineNewFrame: .word 0
;;; One 8 byte slot for each tic that can be queued (the data region has no room for more).
;;; A slot is written completely before ticCount makes it visible.
ticCommands:  .space MAXTICS*8
