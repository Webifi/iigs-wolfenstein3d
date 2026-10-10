;;; Bank 2 side of the front end. The game's routines assume DBR = 2 and
;;; D = $1000 and end with RTS, so the menus in bank $3F reach them through
;;; these stubs. Menus and debug commands enter from the input action path;
;;; the debug frame stub is installed only while a delay is enabled.
#include "memmap.inc"
#include "game.inc"
#include "logic.inc"
              .extern EnsureGameplayAssets
              .extern projectionCold, EnsureRayHeights
              .section gamecode, text, root, noreorder
              .public UiOpen, UiGetTime, UiDrain, UiInitFlash, UiStartGame
              .public UiRender, UiResetInput, UiSetView, UiShowView, UiGameOver, UiKeepView
              .extern ResetTics, MarkFloorVisited
              .extern MenuOpen, MenuGameOver, MenuReturnTitle, I_GetTime, CaptureInput, InitFlash
              .extern LoadFloorAssets, LogicNewGame, ApplyLevel, LogicPublish, levelState, deathPhase, StartFloor, deathFaded
              .extern levelStart, levelHeld, levelHeldOn, levelPauseAt, levelPauseOn, levelRestarted
              .extern demoMode, timeDemo, hudDirty
              .public UiStartSavedFloor, UiPublishGame
              .public UiDemoStart, UiDemoStep, UiDemoAbort
              .extern StartDemo, StartDemoPrompt, DemoStep, DemoAbort
              .extern castFrame, paintFrame, PrepareSprites, setView, ShowView, viewKeep
              .extern weaponViewIndex
              .public paintSiteUi
              .extern palHold
              .extern inputHead, inputTail, keyHeld, keyAction, keyCommand
              .extern inputCursor, inputUntil, inputDropped, heldCommand, keyLatch, mouseCountX, mouseCountY

;;; Enter game context keeping A: flags, DBR and D are pushed.
GAME_ENTER    .macro
              php
              phb
              phd
              rep #0x30
              pha
              sep #0x20
              lda #2
              pha
              plb
              rep #0x30
              lda ##0x1000
              tcd
              pla
              .endm
GAME_LEAVE    .macro
              pld
              plb
              plp
              .endm

;;; The Esc key opens the menu. A, X and Y 16 bits on return are the game's
;;; own; the menu has put the input state back (UiLeave in ui_main.s).
UiOpen:       php
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              jsl long:I_GetTime
              sta long:levelPauseAt
              txa
              sta long:levelPauseAt+2
              lda ##1
              sta long:levelPauseOn
              .extern DebugMenuEntry
              jsl long:DebugMenuEntry
              jsl long:EnsureGameplayAssets
              jsr abs:.word0 (resumeView)
              lda long:levelRestarted
              bne uiOpenSkip
              jsl long:I_GetTime
              sec
              sbc long:levelPauseAt
              pha
              txa
              sbc long:levelPauseAt+2
              sta long:levelPauseAt+2
              pla
              clc
              adc long:levelStart
              sta long:levelStart
              lda long:levelPauseAt+2
              adc long:levelStart+2
              sta long:levelStart+2
uiOpenSkip:   lda ##0
              sta long:levelRestarted
              sta long:levelPauseOn
              pld
              plb
              ply
              plx
              pla
              plp
              rts

;;; The in-game pause kept no picture. Take UiLeave's view latch now, as
;;; PollTicInput would at the next tic: setView blacks the colors, repaints the
;;; whole view and status bar and reveals them at the blank, so no game frame
;;; paints under the menu's colors. The tic clock stays the one UiLeave reset:
;;; as after the latch, the player's commands then run before the world catches
;;; up (tics.s worldCaughtUp). A clock reset here let the world run first, with
;;; the player's position (V_plux) of a game the benchmark had replaced: CheckLine
;;; left the map (lsight.s brk) on the first tic.
resumeView:   sep #0x20
              lda long:VIEW_LATCH
              beq resumeKept
              dec a
              rep #0x20
              and ##255
              jsr abs:.word0 (setView)
              sep #0x20
              lda #0
              sta long:VIEW_LATCH
resumeKept:   rep #0x20
              rts

;;; The game is over: a score that reaches the table of high scores asks for
;;; a name in a box over the game's screen. Registers and screen are the game's.
UiGameOver:   php
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              jsl long:MenuGameOver
              jsl long:MenuReturnTitle
              jsr abs:.word0 (setView)
              pld
              plb
              ply
              plx
              pla
              plp
              rts

UiGetTime:    GAME_ENTER
              jsl long:I_GetTime
              GAME_LEAVE
              rtl

;;; ADB data may have arrived while interrupts were off for a disk call.
UiDrain:      GAME_ENTER
              jsl long:CaptureInput
              GAME_LEAVE
              rtl

UiInitFlash:  GAME_ENTER
;;; A loading sign must publish its colors even while the next view is held.
              lda abs:.word0 (palHold)
              pha
              stz abs:.word0 (palHold)
              jsl long:InitFlash
              pla
              sta abs:.word0 (palHold)
              GAME_LEAVE
              rtl

;;; A = difficulty 0-3: a new game of floor 1 as the death restart does it.
UiStartGame:  nop
              GAME_ENTER
              pha
              phx
              txa
              jsr abs:.word0 (LoadFloorAssets)
              bcs uiFloorReady
              plx
              pla
              GAME_LEAVE
              sec
              rtl
uiFloorReady: plx
              pla
              jsl long:LogicNewGame
              jsl long:I_GetTime
              and ##255
              jsr abs:.word0 (ApplyLevel)
              lda long:weaponViewIndex
              lsr a
              jsr abs:.word0 (setView)
              stz abs:.word0 (levelState)
              stz abs:.word0 (deathPhase)
              stz abs:.word0 (deathFaded)
              stz abs:.word0 (demoMode)
              stz abs:.word0 (timeDemo)
              jsl long:InitFlash
              lda ##1
              sta abs:.word0 (hudDirty)
              jsl long:MarkFloorVisited
              GAME_LEAVE
              clc
              rtl

;;; A = saved floor; bank $28 already holds the slot's statistics.
UiStartSavedFloor:
              GAME_ENTER
              jsl long:StartFloor
              bcs savedFloorBad
              stz abs:.word0 (demoMode)
              stz abs:.word0 (timeDemo)
              jsl long:InitFlash
              GAME_LEAVE
              clc
              rtl
savedFloorBad:GAME_LEAVE
              sec
              rtl

UiPublishGame:GAME_ENTER
              jsr abs:.word0 (LogicPublish)
              lda ##1
              sta abs:.word0 (hudDirty)
              GAME_LEAVE
              rtl

;;; One picture of the current pose, as the frame loop makes it.
UiRender:     GAME_ENTER
              jsl long:EnsureGameplayAssets
              jsr abs:.word0 (EnsureRayHeights)
              jsr abs:.word0 (castFrame)
              jsr abs:.word0 (PrepareSprites)
paintSiteUi:  jsr abs:.word0 (paintFrame)
              GAME_LEAVE
              rtl

;;; A = view size 0-3: the game's setView, which also draws the border and the
;;; status bar.
UiSetView:    GAME_ENTER
              jsr abs:.word0 (setView)
              GAME_LEAVE
              rtl

;;; Present a view whose tables were already prepared under a loading sign.
UiShowView:   GAME_ENTER
              jsr abs:.word0 (ShowView)
              GAME_LEAVE
              rtl

;;; The menu restored the picture. The view latch must not reload its colors.
UiKeepView:   GAME_ENTER
              lda ##1
              sta abs:.word0 (viewKeep)
              GAME_LEAVE
              rtl

;;; The recorded demos, from wolf's demo code (ui_demo.s calls these).
;;; A = the demo 0-3, X = 1 to play it as fast as it goes. A = 1 when it started.
UiDemoStart:  GAME_ENTER
              pha
              txa
              sta abs:.word0 (timeDemo)
              pla
              cpx ##0
              beq uiAutoDemo
              jsr abs:.word0 (StartDemoPrompt)
              bra uiDemoResult
uiAutoDemo:
              jsr abs:.word0 (StartDemo)
uiDemoResult:
              lda ##0
              rol a
              GAME_LEAVE
              rtl

;;; One picture of the demo. A = 1 when the demo is over.
UiDemoStep:   GAME_ENTER
              jsr abs:.word0 (DemoStep)
              lda ##0
              rol a
              GAME_LEAVE
              rtl

;;; A key stopped the demo.
UiDemoAbort:  GAME_ENTER
              jsr abs:.word0 (DemoAbort)
              GAME_LEAVE
              rtl

;;; After a menu or a disk step: no queued events, no key held, no key
;;; command, and the input clock at now, so the game sees no gap.
              .extern J13Reset, MouseReset
UiResetInput: GAME_ENTER
              jsl long:J13Reset
              jsl long:MouseReset
              lda abs:.word0 (inputHead)
              sta abs:.word0 (inputTail)
              stz abs:.word0 (inputDropped)
              ldx ##126
resetHeld:    stz abs:.word0 (keyHeld),x
              dex
              dex
              bpl resetHeld
              stz abs:.word0 (keyCommand)
              stz abs:.word0 (heldCommand)
              stz abs:.word0 (keyLatch)
              stz abs:.word0 (mouseCountX)
              stz abs:.word0 (mouseCountY)
              stz abs:.word0 (keyAction)
              jsl long:I_GetTime
              sta abs:.word0 (inputCursor)
              sta abs:.word0 (inputUntil)
              sta dp:LASTTIC
              sta dp:TIME
              pha
              phx
              lda abs:.word0 (levelHeldOn)
              beq heldSkip
              plx
              pla
              sec
              sbc abs:.word0 (levelHeld)
              sta abs:.word0 (levelStart)
              txa
              sbc abs:.word0 (levelHeld+2)
              sta abs:.word0 (levelStart+2)
              lda ##0
              sta abs:.word0 (levelHeldOn)
              lda abs:.word0 (levelPauseOn)
              beq heldOut
              lda ##1
              sta abs:.word0 (levelRestarted)
              bra heldOut
heldSkip:     plx
              pla
heldOut:      jsr abs:.word0 (ResetTics)
              GAME_LEAVE
              rtl

              .section tailio, text, root
              .public ResetSharedProjections
;;; Projection records share the paused menu frame. Its contents are discarded
;;; before projection resumes; world state remains intact.
ResetSharedProjections:
              lda ##0
              sta long:projectionCold
              stz dp:SP_COUNT
              ldx ##550*8
readbackClearProjection:
              lda ##65535
              sta long:SPR_HISTORY+4,x
              txa
              sec
              sbc ##8
              tax
              bpl readbackClearProjection
              lda ##1
              sta dp:FIRST
              rtl

;;; Cold cross-bank entries keep the game bank and direct page conventions.
              .section gamecode, text, root, noreorder
              .public DebugOpen, DebugWarp, DebugFrame
              .extern DebugWait, EnterFloor
DebugOpen:    jsr abs:.word0 (UiOpen)
              rtl
DebugWarp:    sta abs:.word0 (nextFloor)
              lda ##4
              sta abs:.word0 (flowPhase)
              jsr abs:.word0 (EnterFloor)
              rtl
DebugFrame:   jsl long:DebugWait
              jmp abs:.word0 (frameLoop)
              .extern nextFloor, flowPhase, frameLoop
              .public DebugClockReset
DebugClockReset:
              jsl long:I_GetTime
              sta dp:LASTTIC
              jsr abs:.word0 (ResetTics)
              rtl

              .public DebugHUD
              .extern UpdateHUD
DebugHUD:     jsr abs:.word0 (UpdateHUD)
              rtl
#ifdef WOLF_SPEAR
              .public DebugGodFace
              .extern hudFace
DebugGodFace: lda long:LOGIC_BASE+V_faceframe
              clc
              adc ##19
              jmp abs:.word0 (hudFace)
#endif
