;;; A boss replay pauses simulation while its notice and camera are prepared.
;;; Called from the frame boundary with the ordinary gameplay context.
#include "memmap.inc"
#include "logic.inc"
#include "game.inc"
#if !defined(WOLF_SPEAR)
              .section registeredlogic, text, root, noreorder
              .public DeathCamFrame
              .extern InitFlash, WaitBlank, RegisteredDeathNotice
              .extern DeathCamPosition, LogicFinish, UiPublishGame, UiShowView, UiResetInput

DeathCamFrame:
              lda long:LOGIC_BASE+V_deathcam_phase
              cmp ##1
              beq replayPrepare
              cmp ##3
              beq replayExit
              rtl
replayPrepare:
              jsl long:InitFlash
              jsr abs:.word0 (replayWait)
              jsl long:RegisteredDeathNotice
              jsl long:DeathCamPosition
              jsl long:LogicFinish
              jsl long:UiPublishGame
              lda ##1
              sta dp:FIRST
              jsl long:UiShowView
              jsl long:UiResetInput
              rtl
replayExit:   jsl long:InitFlash
              jsr abs:.word0 (replayWait)
              lda ##6
              sta long:LOGIC_BASE+V_playstate
              lda ##0
              sta long:LOGIC_BASE+V_deathcam_phase
              rtl
replayWait:   ldx ##100
replayWaitVbl:
              phx
              jsl long:WaitBlank
              plx
              dex
              bne replayWaitVbl
              rts
#endif

#ifdef WOLF_SPEAR
              .section gamecode, text, root
              .public DeathCamFrame
DeathCamFrame: rtl
#endif
