;;; Shared floor-flow and tally state. The loader path is in continue.s.
#include "campaign.inc"
              .section gamedata, data, root
              .public nextFloor, flowPhase, playerCell, levelStart
              .public levelHeld, levelHeldOn, levelPauseAt, levelPauseOn, levelRestarted
              .public levelSeed
playerCell:   .word 65535
nextFloor:    .word 0
flowPhase:    .word 0
levelStart:   .word 0,0
;;; Saved elapsed waiting for the load to reach the play loop, and the
;;; menu-entry clock so a pause is not part of the floor time.
levelHeld:    .word 0,0
levelHeldOn:  .word 0
levelPauseAt: .word 0,0
levelPauseOn: .word 0
levelRestarted: .word 0
;;; The rndindex ApplyLevel handed to setup, so a failed load can rebuild it.
levelSeed:    .word 0
noteScratch:  .word 0
              .public tallyBonus, tallyKill, tallySecret, tallyTreasure
              .public tallySec, tallyLeft, tallyPar, tallyTimePart, musicRequest
              .public flowShownBonus, flowShown, flowStep, flowPause, flowAck, flowPaid
              .public flowPtr, flowX, flowY, flowScr, flowBits, flowGlyph, flowRows
              .public flowRight, flowSuffix, flowClearW, flowClearB, flowDigitStart
              .public flowElapsed, flowNum, flowMul, flowDiv, flowPay, flowRem
              .public flowTarget, flowNib, flowDigits
tallyBonus:   .word 0,0
tallyKill:    .word 0
tallySecret:  .word 0
tallyTreasure:.word 0
tallySec:     .word 0
tallyLeft:    .word 0
tallyPar:     .word 0
tallyTimePart:.word 0,0
musicRequest: .word 0
flowShownBonus:.word 0,0
flowShown:    .word 0
flowStep:     .word 0
flowPause:    .word 0
flowAck:      .word 0
flowPaid:     .word 0
flowPtr:      .word 0
flowX:        .word 0
flowY:        .word 0
flowScr:      .word 0
flowBits:     .word 0
flowGlyph:    .word 0
flowRows:     .word 0
flowRight:    .word 0
flowSuffix:   .word 0
flowClearW:   .word 0
flowClearB:   .word 0
flowDigitStart:.word 0
flowDigitCount:.word 0
flowElapsed:  .word 0,0
flowNum:      .word 0
flowMul:      .word 0
flowDiv:      .word 0
flowPay:      .word 0,0
flowRem:      .word 0
flowTarget:   .word 0
flowNib:      .word 0
flowDigits:   .space 8
