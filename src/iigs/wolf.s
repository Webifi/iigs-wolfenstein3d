#include "memmap.inc"
#include "progress.inc"
#include "sound_ids.inc"
;;; Grid traversal uses 8.8 distances and positions with table-based products.
;;; The prepared renderer builds descriptors before writing pixels, then paints
;;; them in one continuous left-to-right pass.
#include "picture_config.inc"
#include "tics.inc"
              .section gamecode, text, root, noreorder
              .public start
              .extern PlaySoundEvent, InitSound, PlaySound, CacheFloorMusic, CacheFloorEffects, FloorMusic, AudioSettingKey
              .extern IIGS_InitDocTimer, I_GetTime, UiBootCells, UiLoadSign, UiLoadDone
              .extern PrepareSprites, ComposeAndPaint
              .extern weapon, weaponFrame, keys, sfxEvent, levelState
              .extern DeathTick, PWallHit, RestartLevel, ApplyLevel, doorBytes
              .extern InitHUD, UpdateHUD, PalBlack, RevealPal
              .extern StartKeys, ReadKeys, keyCommand, mouseCountX, mouseCountY, inputTimed, inputUntil, inputHead, inputLimit
              .extern RefreshFlash
              .extern PrepareRayPages, EnsureRayHeights
              .public DemoStep, DemoAbort, PollTicInput
              .extern ResetTics, tryRunTics
              .extern LogicFrame, LogicTick, LogicFinish, LogicNewGame, LogicPublish, LogicControls, StartDemoPrompt, DemoPacket
              .extern demoMode, timeDemo, demoPtr, demoEnd, weaponRequest, levelIndex
              .public castMinX, castMaxX, castMinY, castMaxY
              .public castMinHeight
              .public DeferWallOutputs, FinishWallOutputs, CompleteWallOutputs
              .public heightStreams, heightView
              .public mulFrac, viewFactor, viewTop, viewBottom, viewLeft, viewBytes
              .public scaleIndex, scaleHeight, scaleBank, scaleWidthRecip
              .public rowCodeBase, rowTexBase, texEndpointBase, spriteFrame
              .public horizontalBase
              .public screenRows
              .public viewScaleTop, viewScaleBottom, viewScaleTex
#if !WOLF_PREPARED
              .public flatNonempty
#endif
#if WOLF_GROUPS
              .public groupBase
              .public screenStoreBanks
#endif
              .public oldHeight, oldSource, oldBank
              .public weaponReady
              .public texBase, texBank, doorOrient, doorCells
              .public cellX, doorHit, doorPosition
              .public hitCoordinate, focalProduct, prepareHook
              .public shootDelta
              .public ExpandArt, setView, setViewInPlay, viewPal
              .public castFrame, paintFrame, columnLight
              .public paintSiteGame, paintSiteView
              .public viewBytes, viewTop, viewBottom, viewLeft
              .public castPX, castPY, castAngle
#if WOLF_PREPARED
              .public rowX160, paintStamp, paintPX, paintPY, paintAngle
#endif
              .extern uiShortcut, UiOpen, MenuBoot, LevelFlow, bootComplete, floorReady, UiStartGame, BuildRayPartial
              .public weaponViewIndex
              .public wallDirty
              .extern mouseSensitivity, mouseWalk

#include "game.inc"
#include "logic.inc"
#include "sprite_layout.inc"
DEATH_PALETTE .equ PALBUF
#include "sprite_ids.inc"
#include "ray_mode.inc"
#include "ray_program.inc"
#define WOLF_SPAN_FILL (WOLF_PREPARED && WOLF_QUARTER_RAYS && WOLF_RAY_STRIDE >= 8)
#define WOLF_COMPILED_RAYS WOLF_SPAN_FILL
#if WOLF_COMPILED_RAYS
              .extern castProgram80,castProgramAddrs
              .public traceRay,interpolateRay,castDone,raySpacing
              .public interpolateAnchors2,interpolateAnchors4,interpolateAnchors8,interpolateAnchors16
#endif
#if WOLF_PREPARED && !WOLF_TRUE_PIXELS
              .extern viewCutHook, sizeArm
#endif
#include "prepared.inc"

start:        sei
              clc
              xce
              rep #0x38
              ldx ##0x1fff
              txs
              lda ##0x1000
              tcd
              sep #0x20
              lda #2
              pha
              plb
              lda long:SHADOW
              ora #0x5f                 ; bank 1 sight stamps need RAM at C000
              sta long:SHADOW
              lda long:CYAREG
              ora #0x80
              and #0xef                 ; all-bank shadowing would slow code
              sta long:CYAREG
              rep #0x30
              lda ##0
              ldx ##254
clearDP:      sta dp:0,x
              dex
              dex
              bpl clearDP
              sep #0x20
              lda #0
              sta long:COMMAND_LATCH
              sta long:VIEW_LATCH          ; firmware does not own our test latches
              sta long:DEMO_LATCH
              sta long:TIMEDEMO_LATCH
              sta long:DEMO_STATUS
              sta long:UI_SKIP
              sta long:UI_SKIP+0x1
              rep #0x20
;;; word-products ($06:0000-$07:FFFF, tools/gen_ray_tables.py): row b at 512*b
;;; holds a*b for a = 0..255. Built here instead of loaded (128 KB that do not pack).
              phb
              ldy ##0                   ; b
productRow:   tya
              xba
              asl a                     ; 512*b, wrapping into bank $07 at b = 128
              tax
              sep #0x20
              tya
              asl a                     ; carry: b >= 128
              lda #0x06
              adc #0
              pha
              plb
              rep #0x20
              phy                       ; the step b
              lda ##0
              ldy ##256
productWord:  sta abs:0,x
              clc
              adc 1,s
              inx
              inx
              dey
              bne productWord
              ply
              iny
              cpy ##256
              bcc productRow
              plb
              jsl long:BuildRayPartial
              phb
              ldx ##0x8400              ; boot-only source-plane staging
              ldy ##0xa000
              lda ##8191
              .byte 0x54,0xe1,0x0e
              plb
#if WOLF_PREPARED
              jsr abs:.word0 (ExpandArt)
#endif
;;; The loaded art already contains its light variants; no boot expansion remains.
              lda ##34
              ldx ##2
              jsl long:UiBootCells
              jsl long:IIGS_InitDocTimer
              lda long:LOGIC_BASE+LEVELBLOCK+0x10
              tax
              lda ##2                     ; gd_medium, the menu's default
              jsl long:LogicNewGame
              jsl long:I_GetTime
              and ##255                   ; US_InitRndT(true)
              jsr abs:.word0 (ApplyLevel)
              lda ##36                    ; the cell of the loader's bar for the level
              ldx ##1
              jsl long:UiBootCells
              lda ##1
              sta dp:FIRST
              jsl long:InitSound
              jsl long:I_GetTime
              sta dp:LASTTIC
;;; The loader's picture is still on the screen. InitFlash inside StartKeys
;;; must not replace its palettes with the floor's (flashWrite honors palHold).
              lda ##1
              sta abs:.word0 (palHold)
              jsr abs:.word0 (StartKeys)
              jsr abs:.word0 (CacheFloorMusic)
              jsl long:CacheFloorEffects
              jsl long:MenuBoot             ; the title and main menu; A = view size
              pha
              lda ##1
              sta long:bootComplete
              lda long:floorReady           ; the boot holds no floor: a test latch skipped the menu
              bne bootFloorReady
              lda 1,s                       ; the view, before any view work reads the floor
              asl a
              sta abs:.word0 (weaponViewIndex)
              lda ##2                       ; floor 1 as New Game starts it
              ldx ##0
              jsl long:UiStartGame
bootFloorReady:
              pla
              jsr abs:.word0 (setView)
              jsl long:FloorMusic
              jsl long:I_GetTime
              sta dp:LASTTIC             ; boot and menu setup are paused time
              jsr abs:.word0 (ResetTics)
              lda ##0
              sta abs:.word0 (frameCount)

;;; The DOC clock determines simulation work; one completed picture follows.
;;; Benchmarks alone request one original recorded packet per picture.
frameLoop:    jsl long:I_GetTime
              sta dp:TIME
              lda abs:.word0 (demoMode)
              beq liveFrame
              lda abs:.word0 (timeDemo)
              bne demoFrame
              lda dp:TIME                 ; a demo waits for DEMOTICS
              sec
              sbc dp:LASTTIC
              cmp ##4
              bcc frameLoop
              jsr abs:.word0 (frameStart)
              jsr abs:.word0 (tryRunTics)
              jmp abs:.word0 (publishFrame)
demoFrame:    lda ##4
              sta dp:TICS
              jsr abs:.word0 (frameStart)
              jsr abs:.word0 (DemoPacket)
              jmp abs:.word0 (runLogic)
liveFrame:    lda dp:TIME
              sec
              sbc dp:LASTTIC
              bne liveTics
              jmp abs:.word0 (frameLoop)  ; CalcTics waits for a tic
liveTics:     sta abs:.word0 (liveLeft)
              lda abs:.word0 (inputHead)
              sta abs:.word0 (inputLimit)
              jsr abs:.word0 (frameStart)
              lda abs:.word0 (levelState)
              beq liveCommands
              lda abs:.word0 (liveLeft)
              sta dp:TICS
              clc
              adc dp:LASTTIC
              sta dp:LASTTIC
              sta abs:.word0 (inputUntil)
              lda ##1
              sta abs:.word0 (inputTimed)
              jsr abs:.word0 (input)
              stz abs:.word0 (inputTimed)
              lda abs:.word0 (demoMode)
              bne runLogic
              lda abs:.word0 (levelState)
              beq liveFinish
              cmp ##4
              bcc runDeath
              jsr abs:.word0 (LevelFlow)
              jmp abs:.word0 (frameDone)
runDeath:     jsr abs:.word0 (DeathTick)
              jmp abs:.word0 (renderFrame)

liveCommands: jsr abs:.word0 (tryRunTics)
              lda abs:.word0 (demoMode)
              bne runLogic
liveFinish:   jsl long:LogicFinish
              jsr abs:.word0 (LogicPublish)
              jsr abs:.word0 (UpdateHUD)
              jmp abs:.word0 (endStates)
runLogic:     jsl long:LogicFrame
publishFrame: jsr abs:.word0 (LogicPublish)
              jsr abs:.word0 (UpdateHUD)
              jmp abs:.word0 (endStates)
renderFrame:  sep #0x20
              lda #1
              sta long:CAST_MARK
              rep #0x20
              jsr abs:.word0 (castFrame)
              sep #0x20
              lda #2
              sta long:CAST_MARK
              rep #0x20
prepareHook:  jsr abs:.word0 (PrepareSprites)
              sep #0x20
              lda #1
              sta long:PAINT_MARK         ; visible-paint profiler boundary
              rep #0x20
paintSiteGame: jsr abs:.word0 (paintFrame)
              sep #0x20
              lda #2
              sta long:PAINT_MARK
              rep #0x20
frameDone:    inc abs:.word0 (frameCount)
              sep #0x20
              lda #2
              sta long:FRAME_MARK
              rep #0x20
              lda abs:.word0 (demoOver)
              beq nextFrame
              stz abs:.word0 (demoOver)
              jsr abs:.word0 (demoFinished)
              lda abs:.word0 (demoStepCall)
              beq nextFrame
              stz abs:.word0 (demoStepCall)
              sec
              rts
nextFrame:    lda abs:.word0 (demoStepCall)
              beq loopAgain
              stz abs:.word0 (demoStepCall)
              clc
              rts
              .public debugFrameJump, frameLoop
debugFrameJump:
loopAgain:    jmp abs:.word0 (frameLoop)

frameStart:   sep #0x20
              lda #1
              sta long:FRAME_MARK
              rep #0x20
              rts

;;; The source's playstate after a pass: a demo ends on death, on the last
;;; packet or at the elevator; play dies or stops at the elevator.
endStates:    lda abs:.word0 (demoMode)
              beq liveStates
              lda long:LOGIC_BASE+V_playstate
              bne demoEnded
              lda abs:.word0 (demoPtr)
              cmp abs:.word0 (demoEnd)
              bcc statesDone
demoEnded:    lda ##1
              sta abs:.word0 (demoOver)
              jmp abs:.word0 (renderFrame)
liveStates:
              .extern DeathCamFrame
              jsl long:DeathCamFrame
              lda long:LOGIC_BASE+V_playstate
              beq statesDone
              cmp ##2                     ; ex_died
              bne levelDone
              lda ##1
              sta abs:.word0 (levelState)
              jmp abs:.word0 (renderFrame)
levelDone:    cmp ##9                     ; ex_secretlevel
              beq levelSecret
              cmp ##6                     ; ex_victorious
              beq levelVictory
              lda ##4
              bra levelStateReady
levelSecret:  lda ##5
              bra levelStateReady
levelVictory: lda ##6
levelStateReady:
              sta abs:.word0 (levelState)
              jsr abs:.word0 (LevelFlow)
              jmp abs:.word0 (frameDone)
statesDone:   jmp abs:.word0 (renderFrame)

;;; A demo ended: $03F5 = 2 for test tools, then a new game on this floor.
demoFinished: jsl long:I_GetTime
              sta abs:.word0 (demoEndTime)
              sep #0x20
              lda #2
              sta long:DEMO_STATUS
              rep #0x20
              lda ##0
              jsl long:UiLoadSign         ; preserve the last frame under the loading overlay
              stz abs:.word0 (demoMode)
              stz abs:.word0 (timeDemo)
              lda abs:.word0 (levelIndex)
              tax
              lda ##2
              jsl long:LogicNewGame
              jsl long:I_GetTime
              and ##255
              jsr abs:.word0 (ApplyLevel)
              stz abs:.word0 (levelState)
              jsl long:I_GetTime
              sta dp:TIME
              sta dp:LASTTIC
              jsr abs:.word0 (ResetTics)
              jsl long:UiLoadDone         ; what follows is the front end's own screen
              rts

;;; The front end owns input and receives one complete frame from the same loop.
DemoStep:     lda ##1
              sta abs:.word0 (demoStepCall)
              jmp abs:.word0 (frameLoop)
DemoAbort:    stz abs:.word0 (demoOver)
              stz abs:.word0 (demoStepCall)
              jmp abs:.word0 (demoFinished)

screenInit:   lda abs:.word0 (viewKeep)
              beq screenFull
              stz abs:.word0 (viewKeep)
              stz abs:.word0 (palHold)
              jmp abs:.word0 (screenBorder)
;;; Palettes go to PALBUF, not the hardware. The caller paints, then RevealPal
;;; at the blank, so the old picture never shows under these colors.
screenFull:   lda ##1
              sta abs:.word0 (palHold)
              jsl long:PalBlack
              ldx ##510
              lda ##0
clearPalBuf:  sta long:DEATH_PALETTE,x
              dex
              dex
              bpl clearPalBuf
              sep #0x20
              lda #0xc1
              sta long:NEWVIDEO
              ldx ##199
              lda #0
clearSCB:     sta long:SHR_SCB,x
              dex
              bpl clearSCB
              php
              sei
              ldx ##30
paletteLoop:  rep #0x20
              lda abs:.word0 (viewPal),x
              sta long:DEATH_PALETTE,x
              dex
              dex
              bpl paletteLoop
              plp
              rep #0x20
;;; FIRST repaints every view byte; the HUD also writes its whole rectangle.
              jsr abs:.word0 (screenBorder)
              jsr abs:.word0 (InitHUD)
              rts

;;; A size key in play: the status bar, the palettes and the SCB are as they were. Clear the screen
;;; outside the new view above the status bar, and leave a black margin. The picture that follows
;;; paints the whole view, so a word that reaches into it does no harm.
setViewInPlay:
              ldx ##1
              stx abs:.word0 (viewKeep)
              jmp abs:.word0 (setView)

screenBorder: lda abs:.word0 (viewTop)
              asl a
              tax
              lda abs:.word0 (screenRows),x      ; the bytes above the view
              tax
              dex
              dex
              bmi borderBelow
              lda ##0
borderAbove:  sta long:SHR,x
              dex
              dex
              bpl borderAbove
borderBelow:  lda abs:.word0 (viewBottom)
              cmp ##160
              bcs borderSides
              asl a
              tax
              lda abs:.word0 (screenRows),x
              sta abs:.word0 (borderFrom)
              ldx ##25598
              lda ##0
borderUnder:  sta long:SHR,x
              dex
              dex
              cpx abs:.word0 (borderFrom)
              bcs borderUnder
borderSides:  lda abs:.word0 (viewLeft)
              beq borderEdge
              lda abs:.word0 (viewBottom)
              asl a
              sta abs:.word0 (borderFrom)
              lda abs:.word0 (viewTop)
              asl a
              tay
borderRow:    cpy abs:.word0 (borderFrom)
              bcs borderEdge
              lda abs:.word0 (screenRows),y
              tax
              lda abs:.word0 (viewLeft)
              inc a
              lsr a
              sta abs:.word0 (borderCount)
              lda ##0
borderLeft:   sta long:SHR,x
              inx
              inx
              dec abs:.word0 (borderCount)
              bne borderLeft
              lda abs:.word0 (screenRows),y
              clc
              adc abs:.word0 (viewLeft)
              adc abs:.word0 (viewBytes)
              tax                                ; the first byte right of the view
              lda ##160
              sec
              sbc abs:.word0 (viewLeft)
              sbc abs:.word0 (viewBytes)
              inc a
              lsr a
              sta abs:.word0 (borderCount)
              lda ##0
borderRight:  sta long:SHR,x
              inx
              inx
              dec abs:.word0 (borderCount)
              bne borderRight
              iny
              iny
              bra borderRow
borderEdge:   jmp abs:.word0 (drawPlayBorder)

#if WOLF_PREPARED
;;; The disk holds one source index per texel ($24:0000 on); light tables at
;;; $0A:2000 follow a 16-byte header at $0A:1FF0 (wall and total 64-byte units). Write the dark,
;;; mid and bright A/B copies 8 banks apart ($10, $18, $20) before the first
;;; frame; the last four cells of the boot bar show the progress. Each index
;;; selects a 16-byte bank-0 table entry through the direct page. Bright
;;; output never overtakes unread input: byte i goes to 2i, input sits at
;;; 256K+i of the same 512 KB copy.
EX_CHUNK      .equ SP_TOP               ; scratch until the first frame
EX_WALL       .equ SP_BOT
EX_TOTAL      .equ SP_ROW
EX_BASE       .equ SP_END
EX_END        .equ SP_N
EX_CELL       .equ SP_OLD
EX_TMP        .equ SP_NEW
EX_E1         .equ SP_EXTRA
EX_E3         .equ SP_TMP
ExpandArt:    rts                       ; loaded art already contains its light variants
#endif

;;; Keys and test latches: $03E0 adds command bits for a whole frame, $03E1
;;; selects a view, $03E2 starts demo n-1 ($03E3 bit 0: timedemo).
input:        jsr abs:.word0 (PollTicInput)
              lda abs:.word0 (demoMode)
              bne inputReady
              lda dp:COMMAND
              jmp abs:.word0 (LogicControls)
inputReady:   rts
PollTicInput: sep #0x20
              lda long:VIEW_LATCH
              beq noViewLatch
              dec a
              rep #0x20
              and ##255
              jsr abs:.word0 (setView)
              sep #0x20
              lda #0
              sta long:VIEW_LATCH
noViewLatch:  lda long:DEMO_LATCH
              beq noDemoLatch
              dec a
              rep #0x20
              and ##255
              pha
              lda long:TIMEDEMO_LATCH
              and ##1
              sta abs:.word0 (timeDemo)
              sep #0x20
              lda #0
              sta long:DEMO_LATCH
              rep #0x20
              lda ##1
              sta abs:.word0 (screenHold)
              pla
              jsr abs:.word0 (StartDemoPrompt)
              php
              jsl long:UiLoadDone
              stz abs:.word0 (screenHold)
              lda abs:.word0 (weaponViewIndex)
              lsr a
              jsr abs:.word0 (setView)
              plp
              sep #0x20
              lda #1
              bcs demoStatus
              lda #3                      ; the demo's floor is not loaded
demoStatus:   sta long:DEMO_STATUS
              rep #0x20
              lda abs:.word0 (demoMode)
              beq noDemoLatch
              jmp abs:.word0 (DemoPacket)
noDemoLatch:  rep #0x20
              jsr abs:.word0 (ReadKeys)
              sep #0x20
              cmp #0
              bne readKey
              jmp abs:.word0 (keysDone)
readKey:      .extern DebugDispatch
              cmp #0xfe
              bne ordinaryKey
              jsl long:DebugDispatch
              jmp abs:.word0 (keysDone)
ordinaryKey:      cmp #'1'
              bcc actionKey
              cmp #'5'
              bcs actionKey
              sec
              sbc #'1'
              rep #0x20
              and ##255
              sta abs:.word0 (weaponRequest)
              sep #0x20
              jmp abs:.word0 (keysDone)
actionKey:    cmp #0x81
              bcc actionOrdinary
              cmp #0x8a
              bcs actionOrdinary
              and #15
              sta long:uiShortcut
              lda #27
actionOrdinary: cmp #27
              bne notEscKey
              rep #0x20
              lda abs:.word0 (levelState)
              bne escNoMenu               ; dying or the floor's end: Esc is only a key (DOS)
              jsr abs:.word0 (UiOpen)
              jmp abs:.word0 (keysDone)
escNoMenu:    lda ##0                     ; a function key's page waits for no later Esc
              sta long:uiShortcut
              jmp abs:.word0 (keysDone)
notEscKey:    cmp #'-'
              bne notSmaller
              rep #0x20
              lda abs:.word0 (weaponViewIndex)
              beq sizeKeyDone
              lsr a
              dec a
              jsl long:ViewSelect
#if WOLF_PREPARED && !WOLF_TRUE_PIXELS
              jsr abs:.word0 (sizeArm)
#else
              jsr abs:.word0 (setViewInPlay)
#endif
sizeKeyDone:  sep #0x20
              jmp abs:.word0 (keysDone)
notSmaller:   cmp #'='
              bne notLarger
              rep #0x20
              lda abs:.word0 (weaponViewIndex)
              lsr a
              cmp ##3
              bcs sizeKeyDone
              inc a
              jsl long:ViewSelect
#if WOLF_PREPARED && !WOLF_TRUE_PIXELS
              jsr abs:.word0 (sizeArm)
#else
              jsr abs:.word0 (setViewInPlay)
#endif
              bra sizeKeyDone
notLarger:    and #0xdf
              cmp #'Y'
              bne notMouseY
              rep #0x20
              lda abs:.word0 (mouseWalk)
              eor ##1
              sta abs:.word0 (mouseWalk)
              sep #0x20
              jmp abs:.word0 (keysDone)
notMouseY:    cmp #'['
              bne notMouseSlower
              rep #0x20
              lda abs:.word0 (mouseSensitivity)
              beq mouseSettingDone
              dec abs:.word0 (mouseSensitivity)
mouseSettingDone:
              sep #0x20
              jmp abs:.word0 (keysDone)
notMouseSlower:
              cmp #']'
              bne notMouseFaster
              rep #0x20
              lda abs:.word0 (mouseSensitivity)
              cmp ##15
              bcs mouseSettingDone
              inc abs:.word0 (mouseSensitivity)
              bra mouseSettingDone
notMouseFaster:
              cmp #'P'
              bne notShadeKey
              rep #0x20
              lda abs:.word0 (columnLight)
              eor ##1
              sta abs:.word0 (columnLight)
              lda abs:.word0 (weaponViewIndex)
              lsr a
#if WOLF_PREPARED && !WOLF_TRUE_PIXELS
              jsr abs:.word0 (sizeArm)        ; new light tables and a whole new picture
#else
              jsr abs:.word0 (setViewInPlay)  ; new light tables and a whole new picture
#endif
              sep #0x20
              bra keysDone
notShadeKey:  cmp #'R'
              bne notRestartKey
              rep #0x20
              jsr abs:.word0 (RestartLevel)
              sep #0x20
              bra keysDone
notRestartKey:jsl long:AudioSettingKey
              bcs keysDone
              cmp #'Q'
              bne keysDone
              rep #0x20
              lda long:LOGIC_BASE+V_chosenweapon ; Q selects the next owned weapon
              inc a
              cmp long:LOGIC_BASE+V_bestweapon
              bcc cycleReady
              beq cycleReady
              lda ##0
cycleReady:   sta abs:.word0 (weaponRequest)
              sep #0x20
keysDone:     rep #0x20
              lda abs:.word0 (keyCommand)
              sta dp:COMMAND
              lda long:COMMAND_LATCH
              and ##0x00ff
              ora dp:COMMAND
              sta dp:COMMAND
              jsr abs:.word0 (mouseControls)
              lda dp:COMMAND
              rts

              .extern MouseControls
mouseControls:jsl long:MouseControls
              rts

;;; The margin around a smaller view is the black clear. A bevel is not drawn.
drawPlayBorder: rts

#if !WOLF_TRUE_PIXELS
;;; Rebuild the selected reciprocal-height table during loading or resizing.
expandRayHeight:
              jmp abs:.word0 (PrepareRayPages)
#endif

              .extern EnsureViewAssets, EnsureGameplayAssets
              .public ShowView
              .extern ViewSelect
setView:      cmp ##4
              bcc validView
              stz abs:.word0 (viewKeep)
              rts
validView:
              jsl long:EnsureViewAssets
              pha
              jsr abs:.word0 (restoreScaleCuts)
              pla
              asl a
              sta abs:.word0 (weaponViewIndex)
              tax
#if WOLF_PREPARED
              .extern spriteSideLimit
              clc
              adc ##216
              sta abs:.word0 (spriteSideLimit+1)
#endif
              lda abs:.word0 (viewSizes),x
              sta abs:.word0 (viewBytes)
#if WOLF_TRUE_PIXELS
              asl a
              sta abs:.word0 (viewWidth)
              lsr a
#else
#if WOLF_PREPARED && !WOLF_TRUE_PIXELS
              jsr abs:.word0 (viewCutHook)
#else
              sta abs:.word0 (viewWidth)
#endif
#endif
              lda abs:.word0 (viewWidth)
              asl a
              sta abs:.word0 (viewPostBytes)
              lda abs:.word0 (viewBytes)
              sta dp:MULR
              lda ##160
              sec
              sbc dp:MULR
              lsr a
              sta abs:.word0 (viewTop)
              sta abs:.word0 (viewLeft)
              clc
              adc dp:MULR
              sta abs:.word0 (viewBottom)
#if WOLF_PREPARED
              phx
              jsl long:clipSpriteEndpoints
              plx
#endif
              lda abs:.word0 (viewFactors),x
              sta abs:.word0 (viewFactor)
              cpx abs:.word0 (heightView)
              beq heightDone            ; reuse only while the gray menu copy has not overwritten them
              phx
#if WOLF_TRUE_PIXELS
              lda abs:.word0 (heightStreams),x
              sta dp:ENTRY
              lda ##11
              sta dp:ENTRY+2
              ldx ##0
              ldy ##0
;;; The true-pixel build retains its separate reciprocal table.
heightRun:    lda [ENTRY],y
              sta dp:MULW
              iny
              iny
              lda [ENTRY],y
heightFill:   sta long:NP_TRUE_HEIGHTS,x
              inx
              inx
              cpx dp:MULW
              bcc heightFill
              iny
              iny
              cpx ##32768
              bcc heightRun
#else
              jsr abs:.word0 (expandRayHeight)
#endif
              plx
              stx abs:.word0 (heightView)
heightDone:
              lda abs:.word0 (shootLimits),x
#if WOLF_TRUE_PIXELS
              asl a
#endif
              sta abs:.word0 (shootDelta)
              lda abs:.word0 (viewClips),x
              sta dp:ENTRY
              lda ##11                  ; view clips at $0B:B000
              sta dp:ENTRY+2
              phx
              ldx ##0
              ldy ##0
copyClips:    lda [ENTRY],y
              sta abs:.word0 (viewScaleAddr),x
              inx
              inx
              iny
              iny
              cpx ##CLIPBYTES
              bcc copyClips
#if WOLF_GROUPS
              phx
              jsr abs:.word0 (installGroupView)
              plx
#endif
              jsr abs:.word0 (installScaleCuts)
#if WOLF_PREPARED
              ldx ##398
rowXHeight:   lda abs:.word0 (viewScaleTop),x
              jsr abs:.word0 (times160)
              sta abs:.word0 (topRowX),x
              lda abs:.word0 (viewScaleBottom),x
              jsr abs:.word0 (times160)
              sta abs:.word0 (bottomRowX),x
              dex
              dex
              bpl rowXHeight
              jsl long:buildLightTables
#endif
              plx
#if WOLF_PREPARED
#if WOLF_COMPILED_RAYS
              lda abs:.word0 (castProgramAddrs),x
              sta abs:.word0 (runCastProgram+1)
#endif
              lda long:WEIGHT_DIRECTORY,x
              sta abs:.word0 (weightViewLoad+1)
              lda long:WEIGHT_DIRECTORY+0x8,x
              sta abs:.word0 (weightFourViewLoad+1)
              lda long:WEIGHT_DIRECTORY+0x10,x
              sta abs:.word0 (weightEightViewLoad+1)
#endif
              lda abs:.word0 (viewAngles),x
              sta dp:ENTRY
              lda abs:.word0 (viewCosines),x
              sta dp:EXITP
              lda ##2
              sta dp:ENTRY+2
              sta dp:EXITP+2
              ldx ##0
              ldy ##0
copyView:     lda [ENTRY],y             ; table pointers name bank 2 explicitly
              sta abs:.word0 (pixelAngle),x
              lda [EXITP],y
#if !WOLF_TRUE_PIXELS
              cmp ##256
              beq copyCosIdentity
              phx
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              plx
              bra copyCosReady
copyCosIdentity:
              lda ##0
copyCosReady:
#endif
              sta abs:.word0 (pixelCos),x
#if WOLF_PREPARED
weightViewLoad:
              lda long:WEIGHT_DIRECTORY+0x6,x
              sta long:VIEW_WEIGHTS,x
weightFourViewLoad:
              lda long:WEIGHT_DIRECTORY+0x12,x
              sta long:WEIGHTS_FOUR,x
weightEightViewLoad:
              lda long:WEIGHT_DIRECTORY+0x12,x
              sta long:WEIGHTS_EIGHT,x
#endif
              iny
              iny
              inx
              inx
              txa
              lsr a
              cmp abs:.word0 (viewWidth)
              bcc copyView
              lda ##1
              sta dp:FIRST
ShowView:
              jsl long:WallPaintShow
#if !WOLF_TRUE_PIXELS
              jsr abs:.word0 (EnsureRayHeights)
#endif
              lda abs:.word0 (screenHold)
              bne viewShown
              jsr abs:.word0 (screenInit)
              lda abs:.word0 (palHold)
              beq viewShown
              jsr abs:.word0 (castFrame)
              jsr abs:.word0 (PrepareSprites)
paintSiteView: jsr abs:.word0 (paintFrame)
              jsl long:RevealPal
viewShown:    rts

;;; The view's bottom is fixed until a size change. Cut each wall scaler
;;; once here; arbitrary sprite spans restore this same opcode after use.
#if WOLF_PREPARED
times160:     sta dp:MULR
              asl a
              asl a
              clc
              adc dp:MULR
              asl a
              asl a
              asl a
              asl a
              asl a
              rts
#endif
restoreScaleCuts:
              lda abs:.word0 (scaleCutsSet)
              beq scaleCutsRestored
              ldx ##0
restoreScaleCut:
              lda abs:.word0 (viewScaleExit),x
              sta dp:EXITP
              lda abs:.word0 (viewScaleBank),x
              sta dp:EXITP+2
              sep #0x20
              lda abs:.word0 (scaleCutBytes),x
              sta [EXITP]
              rep #0x20
              inx
              inx
              cpx ##400
              bcc restoreScaleCut
scaleCutsRestored:
              rts
#if WOLF_GROUPS
;;; A grouped texel can straddle a view edge. Its off-view stores go to
;;; reserved bank-zero RAM at $9000; masks change only here, never behind
;;; screen stores. Patching the address/bank word leaves X indexing intact.
installGroupView:
              stz dp:MASK_COUNT
groupViewHeight:
              ldx dp:MASK_COUNT
              lda abs:.word0 (scaleBank),x
              bit ##256
              beq nextGroupViewHeight
              sta dp:MASK_PTR+2
              lda abs:.word0 (groupBase),x
              sta dp:GROUP_BASE
              stz dp:MASK_ROW
groupViewRow: lda dp:MASK_ROW
              asl a
              asl a
              clc
              adc dp:GROUP_BASE
              tax
              lda long:NP_GROUP_META,x
              sta dp:MASK_PTR
              lda dp:MASK_ROW
              cmp abs:.word0 (viewTop)
              bcc hiddenGroupRow
              cmp abs:.word0 (viewBottom)
              bcs hiddenGroupRow
              lda dp:MASK_ROW
              asl a
              tax
              lda abs:.word0 (screenStoreBanks),x
              bra writeGroupRow
hiddenGroupRow:
              lda ##0x0090
writeGroupRow:sta [MASK_PTR]
              inc dp:MASK_ROW
              lda dp:MASK_ROW
              cmp ##160
              bcc groupViewRow
nextGroupViewHeight:
              inc dp:MASK_COUNT
              inc dp:MASK_COUNT
              lda dp:MASK_COUNT
              cmp ##400
              bcc groupViewHeight
              rts
#endif
installScaleCuts:
              ldx ##0
installScaleCut:
              lda abs:.word0 (viewScaleExit),x
              sta dp:EXITP
              lda abs:.word0 (viewScaleBank),x
              sta dp:EXITP+2
              sep #0x20
              lda [EXITP]
              sta abs:.word0 (scaleCutBytes),x
              lda #0x6b
              sta [EXITP]
              rep #0x20
              inx
              inx
              cpx ##400
              bcc installScaleCut
              lda ##1
              sta abs:.word0 (scaleCutsSet)
              rts

cellX:        and ##0xff00
              lsr a
              lsr a
              rts
;;; A = unsigned 8.8 value, Y = unsigned fraction 0..256.
;;; Clobbers X and Y. A row stores both bytes of each product together.
mulFrac:      cpy ##256
              beq mulDone
              sta dp:MULW
              stz dp:MULP
              tya
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta dp:MULP+1
              lda dp:MULW
              and ##255
              asl a
              tay
              lda [MULP],y
              xba
              and ##255
              sta dp:MULV
              lda dp:MULW
              xba
              and ##255
              asl a
              tay
              lda [MULP],y
              clc
              adc dp:MULV
mulDone:      rts

focalProduct: cmp ##0x8000
              bcc positiveFocal
              eor ##65535
              inc a
              jsr abs:.word0 (mulFrac)
              eor ##65535
              inc a
              rts
positiveFocal:
              jmp abs:.word0 (mulFrac)

              .public InitRayTextureDirectory
InitRayTextureDirectory:
#if WOLF_PREPARED
              jsl long:InitWallRuns
#endif
#if WOLF_SPAN_FILL
              ldx ##WOLF_POST_BYTES-2
clearRayHeights:
              stz abs:.word0 (heightIndex),x
              dex
              dex
              bpl clearRayHeights
#endif
              rts


;;; id moves the viewpoint 0x5700 behind the player before casting.
castFrame:    lda dp:ANGLE
              cmp abs:.word0 (castAngle)
angleChangeBranch:
              bne changedView
              lda dp:FIRST
              ora abs:.word0 (wallDirty)
              bne changedView
              lda dp:PX
              cmp abs:.word0 (castPX)
#if !WOLF_EXACT_RAYS
positionXBranch:
              bne startOrigin
#else
              bne changedView
#endif
              lda dp:PY
              cmp abs:.word0 (castPY)
#if !WOLF_EXACT_RAYS
positionYBranch:
              bne startOrigin
#else
              bne changedView
#endif
              lda abs:.word0 (castVX)    ; sight tests also use these scratch words
              sta dp:VX
              lda abs:.word0 (castVY)
              sta dp:VY
              rts                       ; same walls; actors still project anew
#if !WOLF_EXACT_RAYS
startOrigin:  jmp abs:.word0 (enableOriginMode)
stopOrigin:   jmp abs:.word0 (disableOriginMode)
#endif
changedView:  stz abs:.word0 (wallDirty)
              lda dp:PX
              sta abs:.word0 (castPX)
              lda dp:PY
              sta abs:.word0 (castPY)
              lda dp:ANGLE
              sta abs:.word0 (castAngle)
              asl a
              tax
              lda long:RAY_FOCAL,x
              sta dp:MULR
              lda dp:PX
              sec
              sbc dp:MULR
              sta dp:VX
              sta abs:.word0 (castVX)
              lda dp:ANGLE
              asl a
              tax
              lda long:RAY_FOCAL+0x800,x
              sta dp:MULR
              lda dp:PY
              sec
              sbc dp:MULR
              sta dp:VY
              sta abs:.word0 (castVY)
              and ##255
              asl a
              sta abs:.word0 (fracNegativeY)
              eor ##511
              inc a
              and ##511
              sta abs:.word0 (fracPositiveY)
              lda dp:VX
              and ##255
              asl a
              sta abs:.word0 (fracNegativeX)
              eor ##511
              inc a
              and ##511
              sta abs:.word0 (fracPositiveX)
              stz dp:ENTRY
              lda dp:VISSTAMP
              inc a
              bne validStamp
              lda ##0
              ldx ##8190
clearStamps:  sta long:VIS_STAMPS,x
              dex
              dex
              bpl clearStamps
              inc a
validStamp:   sta dp:VISSTAMP
              lda ##398
              sta abs:.word0 (castMinHeight)
              lda dp:VX
              jsr abs:.word0 (cellX)
              sta dp:ROOTMAP
              lda dp:VY
              xba
              and ##255
              ora dp:ROOTMAP
              asl a
              sta dp:ROOTMAP
              tax
              lda dp:VISSTAMP
              sta long:VIS_STAMPS,x
              txa
              lsr a
              and ##0x0fc0
              sta abs:.word0 (castMinX)
              sta abs:.word0 (castMaxX)
              lda dp:ROOTMAP
              lsr a
              and ##63
              sta abs:.word0 (castMinY)
              sta abs:.word0 (castMaxY)
originFrameHook:
              stz dp:SCAN
              stz dp:CASTPASS
originFrameContinue:
#if WOLF_COMPILED_RAYS
runCastProgram:
              jmp long:castProgram80
initialSkipTrampoline:
              jmp abs:.word0 (originJumpY)
#else

#if WOLF_QUARTER_RAYS
              lda ##WOLF_RAY_STRIDE
              asl a
              sta abs:.word0 (rayAdvance+1)
              sta abs:.word0 (raySpacing)
#endif
rayLoop:
#if !WOLF_EXACT_RAYS
              lda dp:CASTPASS
              beq traceRay
              jmp abs:.word0 (interpolateRay)
#endif
#if !WOLF_EXACT_RAYS
initialSkipTrampoline:
              jmp abs:.word0 (originJumpY)
#endif
#endif
traceRay:      ldx dp:SCAN
              lda abs:.word0 (pixelAngle),x
              clc
              adc dp:ANGLE
              and ##1023
              sta dp:RA
;;; Both directions share a fraction row; positive zero uses the full step.
              asl a
              asl a
              asl a
              asl a
              tax
              lda long:RAY_SETUP,x
              sta dp:DX
              lda long:RAY_SETUP+0x2,x
              sta dp:DY
              lda long:RAY_SETUP+0x8,x
              sta dp:ENTRY+1
              ldy abs:.word0 (fracNegativeX)
              lda long:RAY_SETUP+0x4,x
              sta dp:STEPX
              bmi loadPartialX
              ldy abs:.word0 (fracPositiveX)
              bne loadPartialX
              lda dp:DX
              bra initialXReady
loadPartialX: lda [ENTRY],y
initialXReady:
              sta dp:TX
              lda long:RAY_SETUP+0xa,x
              sta dp:ENTRY+1
              ldy abs:.word0 (fracNegativeY)
              lda long:RAY_SETUP+0x6,x
              sta dp:STEPY
              bmi loadPartialY
              ldy abs:.word0 (fracPositiveY)
              bne loadPartialY
              lda dp:DY
              bra initialYReady
loadPartialY: lda [ENTRY],y
initialYReady:
              sta dp:TY
              lda long:RAY_SETUP+0xc,x
              sta long:wallDDA+1
initialSkip:  ldx dp:ROOTMAP
ddaLoop:      jmp long:wallDDA
solidTile:    txa
              lsr a
              sta dp:MAPIDX
              and ##63
              cmp abs:.word0 (castMinY)
              bcs castExtentYMax
              sta abs:.word0 (castMinY)
              bra castExtentYDone
castExtentYMax:
              cmp abs:.word0 (castMaxY)
              bcc castExtentYDone
              sta abs:.word0 (castMaxY)
castExtentYDone:
              lda dp:MAPIDX
              and ##0x0fc0
              cmp abs:.word0 (castMinX)
              bcs castExtentMax
              sta abs:.word0 (castMinX)
              bra castExtentDone
castExtentMax:
              cmp abs:.word0 (castMaxX)
              bcc castExtentDone
              sta abs:.word0 (castMaxX)
castExtentDone:
              lda dp:TILE
              cmp ##128
              bcc wallHit
              jsr abs:.word0 (doorHit)
              bcs makeHeight
              lda dp:MAPIDX
              asl a
              tax
              jmp abs:.word0 (ddaLoop)
#if WOLF_PREPARED
;;; A wall is vertical (SIDE 0: the hit's Y coordinate, an odd page, and the
;;; texture runs backward when STEPX is negative) or horizontal (the X
;;; coordinate, an even page, backward when STEPY is not negative). Each has
;;; its own straight code to the plane.
wallHit:      lda dp:SIDE
              bne wallHorizontal
              lda dp:RA
              asl a
              tax
              jsr abs:.word0 (hitYBody)
              lda dp:TILE
              dec a
              asl a
              inc a                      ; DOS vertical walls are odd pages
              sta dp:PAGE
              lda dp:RAY
              ldx dp:STEPX
              bpl wallVertical
              eor ##4095
wallVertical: sta dp:RAY
              and ##63
              sta dp:TEXU
              lda dp:MAPIDX
              asl a
              tax
              lda long:wallRunCells,x
              and ##63
              eor dp:MAPIDX
              jmp abs:.word0 (keepPlane)
wallHorizontal:
              lda dp:RA
              asl a
              tax
              jsr abs:.word0 (hitX)
              lda dp:TILE
              dec a
              asl a
              sta dp:PAGE
              lda dp:RAY
              ldx dp:STEPY
              bmi wallHorizontalKept
              eor ##4095
wallHorizontalKept:
              sta dp:RAY
              and ##63
              sta dp:TEXU
              lda dp:MAPIDX
              asl a
              tax
              lda long:wallRunCells,x
              and ##0x0fc0
              eor dp:MAPIDX
              ora ##0x8000
              jmp abs:.word0 (keepPlane)
#else
wallHit:      jsr abs:.word0 (hitCoordinate)
coordinateHit:
              lda dp:TILE
              dec a
              asl a
              ldx dp:SIDE
              bne horizontalPage
              inc a                      ; DOS vertical walls are odd pages
horizontalPage:
              sta dp:PAGE
#if WOLF_PREPARED
              lda dp:RAY
#else
              lda dp:TEXU
#endif
              ldx dp:SIDE
              bne flipHorizontal
              ldx dp:STEPX
              bpl noFlip
#if WOLF_PREPARED
              eor ##4095
#else
              eor ##63
#endif
              bra noFlip
flipHorizontal:
              ldx dp:STEPY
              bmi noFlip
#if WOLF_PREPARED
              eor ##4095
#else
              eor ##63
#endif
noFlip:
#if WOLF_PREPARED
              sta dp:RAY
              and ##63
#endif
              sta dp:TEXU
#endif
makeHeight:   lda dp:MAPIDX
              ldx dp:SIDE
#if WOLF_PREPARED
              beq verticalPlane
              and ##63
              ora ##0x8000
              bra planeReady
verticalPlane:
              and ##0x0fc0
#else
              beq planeReady
              ora ##0x8000
#endif
planeReady:   ldx dp:TILE
              cpx ##128
              bcc keepPlane
#if WOLF_PREPARED
              cpx ##192
              bcs movingWallPlane
              lda dp:SIDE
              ror a
              ror a
              and ##0x8000
              ora dp:MAPIDX
              ora ##0x4000
              bra keepPlane
movingWallPlane:
pushPlane:    lda dp:SIDE
              ror a
              ror a
              and ##0x8000
              ora dp:MAPIDX
              ora ##0x2000
#else
              lda ##65535
#endif
keepPlane:    ldx dp:SCAN
              sta abs:.word0 (hitPlane),x
              lda abs:.word0 (pixelCos),x
#if WOLF_TRUE_PIXELS
              tay
              lda dp:DIST
              jsr abs:.word0 (mulFrac)
              cmp ##16383
              bcc heightRange
              lda ##16383
heightRange:  asl a
              tax
              lda long:NP_TRUE_HEIGHTS,x
#else
rayHeightProduct:
              beq rayHeightIdentity
              stz dp:MULP
              sta dp:MULP+1            ; exact cosine byte-product row
              lda dp:DIST
              and ##255
              asl a
              tay
              lda [MULP],y
              xba
              and ##255
              sta dp:MULV
              lda dp:DIST
              xba
              and ##255
              asl a
              tay
              lda [MULP],y
              clc
              adc dp:MULV
              bra rayHeightDepth
rayHeightIdentity:
              lda dp:DIST
rayHeightDepth:
              cmp ##16383
              bcc heightRange
              lda ##16383
heightRange:  asl a
              tax
              lda long:HEIGHT_TABLE,x
#endif
heightCalculated:
              cmp abs:.word0 (castMinHeight)
              bcs heightMinimumKept
              sta abs:.word0 (castMinHeight)
heightMinimumKept:
              sta dp:HEIGHT
              ldx dp:SCAN
              sta abs:.word0 (heightIndex),x
#if WOLF_PREPARED
#if !WOLF_EXACT_RAYS
              lda dp:RAY
              sta abs:.word0 (raySurface),x
#endif
anchorTexture:
              lda dp:PAGE
              xba
              sta dp:MULR
              lda dp:TEXU
              asl a
              asl a
              ora dp:MULR
              tax
              ldy dp:SCAN
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank),y
#else
#if !WOLF_EXACT_RAYS
              lda dp:PAGE
              xba
              ora dp:TEXU
              sta abs:.word0 (raySurface),x
#endif
              lda dp:SCAN
              lsr a
              sta dp:COL
              ldx dp:PAGE
              sep #0x20
              lda abs:.word0 (texBank),x
              ldx dp:COL
              sta abs:.word0 (sourceBank),x
              rep #0x20
              lda dp:PAGE
              asl a
              tax
              lda abs:.word0 (texBase),x
              sta dp:MULR
              lda dp:TEXU
              asl a
              tax
              lda abs:.word0 (texOffsets),x
              clc
              adc dp:MULR
              tax
              lda long:COLUMN_DIR+0x2,x
              sep #0x20
              ldy dp:COL
              sta abs:.word0 (sourceBank),y
              rep #0x20
              lda long:COLUMN_DIR,x
              ldx dp:SCAN
              sta abs:.word0 (sourceAddr),x
#endif
#if WOLF_COMPILED_RAYS
nextRay:      rtl
#else
nextRay:      lda dp:SCAN
              clc
#if WOLF_QUARTER_RAYS
rayAdvance:   adc ##16
#elif WOLF_EXACT_RAYS
              adc ##2
#else
              adc ##4
#endif
              sta dp:SCAN
              cmp abs:.word0 (viewPostBytes)
              bcs passDone
              jmp abs:.word0 (rayLoop)
passDone:
#if WOLF_QUARTER_RAYS
              lda abs:.word0 (raySpacing)
              lsr a
              cmp ##2
              bcc castDone
              sta abs:.word0 (raySpacing)
              sta dp:SCAN
              asl a
              sta abs:.word0 (rayAdvance+1)
              inc dp:CASTPASS
              jmp abs:.word0 (rayLoop)
#elif !WOLF_EXACT_RAYS
              lda dp:CASTPASS
              bne castDone
              inc dp:CASTPASS
              lda ##2
              sta dp:SCAN
              jmp abs:.word0 (rayLoop)
#endif
#endif
castDone:     rts

;;; Intermediate demo views retain geometry and material identity. Texture
;;; addresses are needed only for the view that reaches the painter.
deferredAnchorTexture:
              lda dp:PAGE
              xba
              sta abs:.word0 (sourceBank),x
              rtl
deferredMidpointTexture:
              ldx dp:SCAN
              lda dp:PAGE
              sta abs:.word0 (sourceBank),x
              rtl
repairAnchorTexture:
              ldx dp:SCAN
              lda abs:.word0 (sourceBank),x
              and ##0xff00
              sta dp:PAGE
              lda abs:.word0 (raySurface),x
              and ##63
              asl a
              asl a
              ora dp:PAGE
              tax
              ldy dp:SCAN
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank),y
              rtl

              .section flowcode, text, root
;;; Recorded catch-up still needs every packet's exact visibility. Accepted
;;; strips have no further rays or anchor consumers, so their pixel inputs can
;;; wait for the final packet. Patching the existing jumps leaves normal casts
;;; unchanged. A changed visibility stamp records incomplete wall outputs. The final
;;; packet or CompleteWallOutputs restores them before sprite preparation.
DeferWallOutputs:
#if WOLF_SPAN_FILL
              lda abs:.word0 (wallOutputsDeferred)
              bne wallOutputDone
              inc abs:.word0 (wallOutputsDeferred)
              lda ##.word0 (deferredAnchorTexture)
              sta abs:.word0 (anchorTexture+1)
              lda ##.word0 (deferredMidpointTexture)
              sta abs:.word0 (knownMidpointPage+1)
              sep #0x20
              lda #0x4c
              sta abs:.word0 (anchorTexture)
              sta abs:.word0 (knownMidpointPage)
              rep #0x20
              lda dp:VISSTAMP
              sta abs:.word0 (deferredVisStamp)
              lda ##.word0 (spanFillDone)
              sta abs:.word0 (linearSpanJump+1)
              sta abs:.word0 (uniformLinearSpanJump+1)
              sta abs:.word0 (splitLinearSpanJump+1)
              sta abs:.word0 (mixedLinearSpanJump+1)
              lda ##.word0 (deferredWeightedSpan)
              sta abs:.word0 (weightedSpanJump+1)
              sta abs:.word0 (uniformWeightedSpanJump+1)
              sta abs:.word0 (splitWeightedSpanJump+1)
              sta abs:.word0 (mixedWeightedSpanJump+1)
#endif
wallOutputDone:
              rts

FinishWallOutputs:
#if WOLF_SPAN_FILL
              lda abs:.word0 (wallOutputsDeferred)
              beq wallOutputDone
              stz abs:.word0 (wallOutputsDeferred)
              lda ##0xa5+PAGE*256
              sta abs:.word0 (anchorTexture)
              lda ##63
              sta abs:.word0 (knownMidpointPage+1)
              sep #0x20
              lda #0xeb
              sta abs:.word0 (anchorTexture+2)
              lda #0x29
              sta abs:.word0 (knownMidpointPage)
              rep #0x20
              lda ##.word0 (fillRaySpan)
              sta abs:.word0 (linearSpanJump+1)
              sta abs:.word0 (uniformLinearSpanJump+1)
              lda ##.word0 (fillSplitRaySpan)
              sta abs:.word0 (splitLinearSpanJump+1)
              lda ##.word0 (fillMixedRaySpan)
              sta abs:.word0 (mixedLinearSpanJump+1)
              lda ##.word0 (fillWeightedSpan)
              sta abs:.word0 (weightedSpanJump+1)
              sta abs:.word0 (uniformWeightedSpanJump+1)
              lda ##.word0 (fillSplitWeightedSpan)
              sta abs:.word0 (splitWeightedSpanJump+1)
              lda ##.word0 (fillMixedWeightedSpan)
              sta abs:.word0 (mixedWeightedSpanJump+1)
              lda dp:VISSTAMP
              cmp abs:.word0 (deferredVisStamp)
              beq wallOutputDone
              sta abs:.word0 (missingWallStamp)
#endif
              rts

;;; If the final packet did not move the camera, rebuild only the discarded
;;; strip outputs. All traced anchors and visibility stamps are still current.
;;; Replaying the same interpolation tree therefore needs no new DDA walks.
CompleteWallOutputs:
              jsr abs:.word0 (FinishWallOutputs)
#if WOLF_SPAN_FILL
              lda abs:.word0 (missingWallStamp)
              beq wallOutputDone
              stz abs:.word0 (missingWallStamp)
              cmp dp:VISSTAMP
              bne wallOutputDone
              lda abs:.word0 (castVX)
              jsr abs:.word0 (cellX)
              sta dp:ROOTMAP
              lda abs:.word0 (castVY)
              xba
              and ##255
              ora dp:ROOTMAP
              asl a
              sta dp:ROOTMAP
              stz dp:ENTRY
              lda ##.word0 (repairAnchorTexture)
              sta abs:.word0 (traceRay+1)
              sep #0x20
              lda #0x4c
              sta abs:.word0 (traceRay)
              rep #0x20
              jsr abs:.word0 (runCastProgram)
              lda ##0xa6+SCAN*256
              sta abs:.word0 (traceRay)
              sep #0x20
              lda #0xbd                  ; LDA abs:pixelAngle,X
              sta abs:.word0 (traceRay+2)
              rep #0x20
#endif
              rts

#if WOLF_SPAN_FILL
;;; Weighted strips reject reversed coordinates by tracing their midpoint.
;;; Keep that visibility-producing fallback when their pixel output is deferred.
deferredWeightedSpan:
              lda abs:.word0 (raySurface),x
              sta dp:TY
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tay
              lda abs:.word0 (raySurface),y
              sec
              sbc dp:TY
              bmi deferredTrace
              jmp abs:.word0 (spanFillDone)
deferredTrace:
              jmp abs:.word0 (traceRay)

              .section gamedata, data, root
wallOutputsDeferred: .word 0
deferredVisStamp:    .word 0
missingWallStamp:    .word 0
#endif
              .section gamecode, text, root, noreorder

#if !WOLF_EXACT_RAYS
enableOriginMode:
              sep #0x20
              lda #.byte0 (changedView-positionXBranch-2)
              sta abs:.word0 (positionXBranch+1)
              lda #.byte0 (changedView-positionYBranch-2)
              sta abs:.word0 (positionYBranch+1)
              lda #.byte0 (stopOrigin-angleChangeBranch-2)
              sta abs:.word0 (angleChangeBranch+1)
              lda #0x4c
              sta abs:.word0 (originFrameHook)
              rep #0x20
              lda ##.word0 (originFrame)
              sta abs:.word0 (originFrameHook+1)
              jmp abs:.word0 (changedView)
disableOriginMode:
              sep #0x20
              lda #.byte0 (startOrigin-positionXBranch-2)
              sta abs:.word0 (positionXBranch+1)
              lda #.byte0 (startOrigin-positionYBranch-2)
              sta abs:.word0 (positionYBranch+1)
              lda #.byte0 (changedView-angleChangeBranch-2)
              sta abs:.word0 (angleChangeBranch+1)
              rep #0x20
              lda ##0xa6+ROOTMAP*256
              sta abs:.word0 (initialSkip)
              lda ##0x64+SCAN*256
              sta abs:.word0 (originFrameHook)
              lda ##0x64+CASTPASS*256
              sta abs:.word0 (originFrameHook+2)
              jmp abs:.word0 (changedView)
originFrame:  jsr abs:.word0 (InitOriginJump)
              stz dp:SCAN
              stz dp:CASTPASS
              jmp abs:.word0 (originFrameContinue)

;;; Gate one initial run per frame; disabled rays keep their original LDX.
InitOriginJump:
              lda ##0xa6+ROOTMAP*256
              sta abs:.word0 (initialSkip)
              lda dp:ANGLE
              clc
              adc ##63
              sta dp:MULP
              and ##255
              cmp ##127
              bcc originAngleReady
              rts
originAngleReady:
              lda dp:MULP
              and ##0x0300
              xba
              asl a
              tay
              lda abs:.word0 (originSteps),y
              sta dp:MULR
              ldx dp:ROOTMAP
              lda ##3
              sta dp:MULW
originCheckCell:
              txa
              clc
              adc dp:MULR
              tax
              lda long:TILE_MIRROR,x
              bmi originEmptyCell
              beq originEmptyCell
              rts
originEmptyCell:
              dec dp:MULW
              bne originCheckCell
              stx abs:.word0 (originJumpTarget)
              lda dp:MULR
              bmi originNegative
              lda dp:ROOTMAP
              clc
              adc dp:MULR
              bra originFirstReady
originNegative:
              txa
originFirstReady:
              sta abs:.word0 (originJumpFirst)
              lda abs:.word0 (originJumps),y
              sta abs:.word0 (initialSkipTrampoline+1)
              sep #0x20
              lda #.byte0 (initialSkipTrampoline-initialSkip-2)
              sta abs:.word0 (initialSkip+1)
              lda #0x80
              sta abs:.word0 (initialSkip)
              rep #0x20
              lda ##4
              sta dp:MULW
originCheckSeven:
              txa
              clc
              adc dp:MULR
              tax
              lda long:TILE_MIRROR,x
              bmi originSevenEmpty
              bne noOriginJump
originSevenEmpty:
              dec dp:MULW
              bne originCheckSeven
              stx abs:.word0 (originSevenTarget)
              lda dp:MULR
              bmi originSevenNegative
              lda abs:.word0 (originJumpFirst)
              bra originSevenFirst
originSevenNegative:
              txa
originSevenFirst:
              sta abs:.word0 (originSevenFirstCell)
              lda abs:.word0 (originSevenJumps),y
              sta abs:.word0 (initialSkipTrampoline+1)
noOriginJump: rts
;;; The X-facing origin cone keeps DX below 384: doubling cannot saturate.
originJumpX:
              lda dp:DX
              asl a
              clc
              adc dp:TX
              cmp dp:TY
              bcs originJumpNone
originJumpUsedX:
              clc
              adc dp:DX
              sta dp:TX
              ldx abs:.word0 (originJumpFirst)
              lda dp:VISSTAMP
              sta long:VIS_STAMPS,x
              sta long:VIS_STAMPS+0x80,x
              sta long:VIS_STAMPS+0x100,x
              ldx abs:.word0 (originJumpTarget)
              jmp abs:.word0 (ddaLoop)
originJumpY:
              lda long:RAY_SETUP+0xe,x
              clc
              adc dp:TY
              cmp dp:TX
              bcs originJumpNone
originJumpUsedY:
              clc
              adc dp:DY
              sta dp:TY
              ldx abs:.word0 (originJumpFirst)
              lda dp:VISSTAMP
              sta long:VIS_STAMPS,x
              sta long:VIS_STAMPS+0x2,x
              sta long:VIS_STAMPS+0x4,x
              ldx abs:.word0 (originJumpTarget)
              jmp abs:.word0 (ddaLoop)
originJumpNone:
              ldx dp:ROOTMAP
              jmp abs:.word0 (ddaLoop)
originJumpSevenX:
              lda dp:DX
              asl a
              clc
              adc dp:TX
              cmp dp:TY
              bcc originTrySevenX
              jmp abs:.word0 (originJumpNone)
originTrySevenX:
              sta dp:DIST
              lda dp:DX
              asl a
              asl a
              clc
              adc dp:DIST
              cmp dp:TY
              bcs originUseThreeX
originJumpUsedSevenX:
              clc
              adc dp:DX
              sta dp:TX
              ldx abs:.word0 (originSevenFirstCell)
              lda dp:VISSTAMP
              sta long:VIS_STAMPS,x
              sta long:VIS_STAMPS+0x80,x
              sta long:VIS_STAMPS+0x100,x
              sta long:VIS_STAMPS+0x180,x
              sta long:VIS_STAMPS+0x200,x
              sta long:VIS_STAMPS+0x280,x
              sta long:VIS_STAMPS+0x300,x
              ldx abs:.word0 (originSevenTarget)
              jmp abs:.word0 (ddaLoop)
originUseThreeX:
              lda dp:DIST
              jmp abs:.word0 (originJumpUsedX)
originJumpSevenY:
              lda long:RAY_SETUP+0xe,x
              clc
              adc dp:TY
              cmp dp:TX
              bcc originTrySevenY
              jmp abs:.word0 (originJumpNone)
originTrySevenY:
              sta dp:DIST
              lda long:RAY_SETUP+0xe,x
              asl a
              clc
              adc dp:DIST
              cmp dp:TX
              bcs originUseThreeY
originJumpUsedSevenY:
              clc
              adc dp:DY
              sta dp:TY
              ldx abs:.word0 (originSevenFirstCell)
              lda dp:VISSTAMP
              sta long:VIS_STAMPS,x
              sta long:VIS_STAMPS+0x2,x
              sta long:VIS_STAMPS+0x4,x
              sta long:VIS_STAMPS+0x6,x
              sta long:VIS_STAMPS+0x8,x
              sta long:VIS_STAMPS+0xa,x
              sta long:VIS_STAMPS+0xc,x
              ldx abs:.word0 (originSevenTarget)
              jmp abs:.word0 (ddaLoop)
originUseThreeY:
              lda dp:DIST
              jmp abs:.word0 (originJumpUsedY)

#endif

;;; Height is linear across a planar wall in screen space. Prepared spans
;;; bound texture error before subdividing; rejected midpoints are traced.
#if WOLF_COMPILED_RAYS
;;; The generated view program supplies X/Y anchor offsets. Separate entry
;;; addresses encode the fixed spacing without growing each call record.
interpolateAnchors16:
              lda ##16
              bra knownRaySpacing
interpolateAnchors8:
              lda ##8
              bra knownRaySpacing
interpolateAnchors4:
              lda ##4
              bra knownRaySpacing
interpolateAnchors2:
              lda ##2
knownRaySpacing:
              sta abs:.word0 (raySpacing)
              bra interpolateAnchors
#endif
interpolateRay:
              lda dp:SCAN
#if WOLF_QUARTER_RAYS
              clc
              adc abs:.word0 (raySpacing)
#else
              inc a
              inc a
#endif
              cmp abs:.word0 (viewPostBytes)
              bcc bothNeighbors
              jmp abs:.word0 (traceRay)
bothNeighbors:
              tay
              lda dp:SCAN
#if WOLF_QUARTER_RAYS
              sec
              sbc abs:.word0 (raySpacing)
#else
              dec a
              dec a
#endif
              tax
;;; Generated commands already know the two in-bounds anchor offsets.
interpolateAnchors:
              lda abs:.word0 (hitPlane),x
              cmp ##65535
              bne finitePlane
              jmp abs:.word0 (traceRay)
finitePlane:  cmp abs:.word0 (hitPlane),y
              beq samePlane
              jmp abs:.word0 (traceRay)
samePlane:    sta dp:TILE
#if WOLF_PREPARED
              lda abs:.word0 (sourceBank),x
              eor abs:.word0 (sourceBank),y
              and ##0xff00
              beq sameMaterial
              lda ##65535
              sta dp:PAGE
              bra materialReady
sameMaterial:
;;; Equal endpoint materials do not prove that intervening tiles match.
;;; Rounded coordinates can also sit just across the actual hit-cell edge.
;;; Only a single coordinate cell can safely reuse an ordinary-wall page.
              lda abs:.word0 (raySurface),x
              eor abs:.word0 (raySurface),y
              and ##0xffc0
              beq nearbyMaterial
              lda dp:TILE
              bit ##0x6000
              bne nearbyMaterial
              lda ##65535
              sta dp:PAGE
              bra materialReady
nearbyMaterial:
              lda abs:.word0 (sourceBank),x
              and ##0xff00
              sta dp:PAGE
materialReady:
              lda abs:.word0 (raySurface),x
              sec
              sbc abs:.word0 (raySurface),y
              bpl positiveGap
              eor ##65535
              inc a
positiveGap:  cmp ##256
              bcc boundedGap
              jmp abs:.word0 (traceRay)
boundedGap:   sta dp:MULW
              lda abs:.word0 (raySurface),x
              clc
              adc abs:.word0 (raySurface),y
              lsr a
              sta dp:RAY
              lda abs:.word0 (heightIndex),x
              clc
              adc ##0x3700
              sta dp:ENTRY+1
              lda abs:.word0 (heightIndex),y
              tay
              lda [ENTRY],y
              sta dp:MULR
              xba
              and ##255
              cmp dp:MULW
              bcs accurateMidpoint
              jmp abs:.word0 (weightedRay)
accurateMidpoint:
#if WOLF_SPAN_FILL
              lda abs:.word0 (raySpacing)
              cmp ##4
              bcc singleMidpoint
              cmp ##9
              bcs singleMidpoint
              lda dp:PAGE
              bmi mixedLinearSpan
linearSpanJump:
              jmp abs:.word0 (fillRaySpan)
mixedLinearSpan:
              jsr abs:.word0 (prepareMixedSpan)
              bcc singleMidpoint
              lda dp:PAGE
              bmi mixedLinearMaterials
uniformLinearSpanJump:
              jmp abs:.word0 (fillRaySpan)
mixedLinearMaterials:
              jsr abs:.word0 (prepareSplitSpan)
              bcc mixedLinearSpanMap
splitLinearSpanJump:
              jmp abs:.word0 (fillSplitRaySpan)
mixedLinearSpanMap:
mixedLinearSpanJump:
              jmp abs:.word0 (fillMixedRaySpan)
singleMidpoint:
#endif
midpointHeight:
              lda dp:MULR
              and ##255
              asl a
#else
              lda abs:.word0 (raySurface),x
              eor abs:.word0 (raySurface),y
              and ##0xff00
              bne traceMidpoint
              lda abs:.word0 (raySurface),x
              sec
              sbc abs:.word0 (raySurface),y
              bpl positiveGap
              eor ##65535
              inc a
positiveGap:
#if WOLF_PREPARED
              cmp ##65
#else
              cmp ##17
#endif
              bcs traceMidpoint
              lda abs:.word0 (raySurface),x
              clc
              adc abs:.word0 (raySurface),y
              ror a                      ; include the carry from the 17-bit sum
#if WOLF_PREPARED
              and ##0xfffc
#endif
              sta dp:RAY
              lda abs:.word0 (heightIndex),x
              tax
              lda abs:.word0 (scaleHeight),x
              sta dp:MULR
              lda abs:.word0 (heightIndex),y
              tax
              lda abs:.word0 (scaleHeight),x
              clc
              adc dp:MULR
              lsr a
              asl a
              tax
              lda abs:.word0 (scaleIndex),x
#endif
              ldx dp:SCAN
              sta abs:.word0 (heightIndex),x
              lda dp:TILE
              sta abs:.word0 (hitPlane),x
              lda dp:RAY
              sta abs:.word0 (raySurface),x
#if WOLF_PREPARED
              bit dp:PAGE
              bpl knownMidpointPage
              jsr abs:.word0 (resolveRayMaterial)
              bcs resolvedMidpointPage
              jmp abs:.word0 (traceRay)
resolvedMidpointPage:
              lda dp:RAY
knownMidpointPage:
              and ##63
              asl a
              asl a
              ora dp:PAGE
              tax
              ldy dp:SCAN
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank),y
#else
              lda dp:SCAN
              lsr a
              sta dp:COL
              lda dp:RAY
              xba
              and ##255
              tax
              sep #0x20
              lda abs:.word0 (texBank),x
              ldx dp:COL
              sta abs:.word0 (sourceBank),x
              rep #0x20
              lda dp:RAY
              xba
              and ##255
              asl a
              tax
              lda abs:.word0 (texBase),x
              sta dp:MULR
              lda dp:RAY
              and ##255
              asl a
              tax
              lda abs:.word0 (texOffsets),x
              clc
              adc dp:MULR
              ldx dp:SCAN
              sta abs:.word0 (sourceAddr),x
#endif
              jmp abs:.word0 (nextRay)
traceMidpoint:
              jmp abs:.word0 (traceRay)

#if WOLF_SPAN_FILL
;;; One post of a filled span. Y addresses the span's last post, so a post is
;;; K-12 bytes from it (K = 0, 2 .. 12 for the seven posts).
SPANPOST      .macro k
              lda dp:TX
              clc
              adc dp:DX
              sta dp:TX
              asl a
              tax
              lda long:RAY_SPAN_HEIGHT,x
              sta abs:.word0 (heightIndex + \k - 12),y
              lda dp:TY
              clc
              adc dp:DY
              sta dp:TY
              lsr a                       ; four bytes per texture column
              and ##0xfc
              ora dp:PAGE
              tax
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr + \k - 12),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank + \k - 12),y
              .endm

;;; Coarse acceptance bounds the whole same-material span. Fixed eighths
;;; fill four or eight columns, then skip their child calls.
fillRaySpan:
              stx dp:MAPIDX
              lda abs:.word0 (raySurface),x
              sta dp:MULR
              asl a
              asl a
              asl a
              sta dp:TY
              lda abs:.word0 (heightIndex),x
              tay
              lda abs:.word0 (scaleHeight),y
              sta dp:DIST
              asl a
              asl a
              asl a
              sta dp:TX
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tay
              lda abs:.word0 (raySurface),y
              sec
              sbc dp:MULR
              sta dp:DY
              lda abs:.word0 (heightIndex),y
              tay
              lda abs:.word0 (scaleHeight),y
              sec
              sbc dp:DIST
              sta dp:DX
              lda abs:.word0 (raySpacing)
              cmp ##4
              bne spanEight
              asl dp:DX
              asl dp:DY
              lda dp:MAPIDX
              clc
              adc ##6                     ; the last of three posts
              tay
              jmp abs:.word0 (spanPost4)
spanEight:    lda dp:MAPIDX
              clc
              adc ##14                    ; the last of seven posts
              tay
spanFillPost: SPANPOST 0
              SPANPOST 2
              SPANPOST 4
              SPANPOST 6
spanPost4:    SPANPOST 8
              SPANPOST 10
              SPANPOST 12
;;; A filled span's columns are never anchors, so raySurface and hitPlane keep
;;; only the traced rays' and single midpoints' values; only interpolateRay
;;; reads them, at anchors.
;;; The generated command width is shared with its build-time emitter.
spanFillDone: lda abs:.word0 (raySpacing)
              cmp ##4
              beq returnShortSpan
              lda ##6*RAY_INTERPOLATE_BYTES
              bra returnFilledSpan
returnShortSpan:
              lda ##2*RAY_INTERPOLATE_BYTES
returnFilledSpan:
              clc
              adc 1,s
              sta 1,s
              rtl
#endif

#if WOLF_SPAN_FILL
fillWeightedSpan:
              stx dp:MAPIDX
              lda abs:.word0 (raySurface),x
              sta dp:TY
              lda abs:.word0 (heightIndex),x
              tay
              lda abs:.word0 (scaleHeight),y
              sta dp:DIST
              asl a
              asl a
              asl a
              sta dp:TX
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tay
              lda abs:.word0 (raySurface),y
              sec
              sbc dp:TY
              bpl weightedSpanIncreasing
              jmp abs:.word0 (traceRay)
weightedSpanIncreasing:
              sta dp:DY
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta abs:.word0 (spanWeightProduct+2)
              lda abs:.word0 (heightIndex),y
              tay
              lda abs:.word0 (scaleHeight),y
              sec
              sbc dp:DIST
              sta dp:DX
              lda abs:.word0 (raySpacing)
              dec a
              sta dp:TEXU
              cmp ##3
              bne weightedSpanEight
              asl dp:DX
              lda ##0xc140
              bra weightedSpanDirectory
weightedSpanEight:
              lda ##0xc280
weightedSpanDirectory:
              sta abs:.word0 (spanWeightRow+1)
              ldx dp:SCAN
spanWeightRow: lda long:WEIGHTS_EIGHT,x
              sta abs:.word0 (weightedSpanVector+2)
              xba
              and ##0xff00
              sta dp:MULP
              lda abs:.word0 (pixelAngle),x
              clc
              adc dp:ANGLE
              ldx dp:TILE
              bpl weightedSpanAngle
              clc
              adc ##256
weightedSpanAngle:
              inc a
              and ##508
              ldx abs:.word0 (raySpacing)
              cpx ##4
              beq weightedSpanOffset
              asl a
weightedSpanOffset:
              clc
              adc dp:MULP
              sta abs:.word0 (weightedSpanVector+1)
              ldy dp:MAPIDX
              iny
              iny
weightedSpanPost:
              lda dp:TX
              clc
              adc dp:DX
              sta dp:TX
              asl a
              tax
              lda long:RAY_SPAN_HEIGHT,x
              sta abs:.word0 (heightIndex),y
              ldx dp:TEXU
weightedSpanVector:
              lda long:WEIGHTS,x
              and ##255
              asl a
              tax
spanWeightProduct:
              lda long:0x000001,x
              and ##255
              clc
              adc dp:TY
              and ##63
              asl a
              asl a
              ora dp:PAGE
              tax
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank),y
              iny
              iny
              dec dp:TEXU
              bne weightedSpanPost
              jmp abs:.word0 (spanFillDone)
fillMixedRaySpan:
              stx dp:MAPIDX
              lda abs:.word0 (raySurface),x
              sta dp:MULR
              asl a
              asl a
              asl a
              sta dp:TY
              lda abs:.word0 (heightIndex),x
              tay
              lda abs:.word0 (scaleHeight),y
              sta dp:DIST
              asl a
              asl a
              asl a
              sta dp:TX
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tay
              lda abs:.word0 (raySurface),y
              sec
              sbc dp:MULR
              sta dp:DY
              lda abs:.word0 (heightIndex),y
              tay
              lda abs:.word0 (scaleHeight),y
              sec
              sbc dp:DIST
              sta dp:DX
              lda abs:.word0 (raySpacing)
              cmp ##4
              bne mixedStepReady
              asl dp:DX
              asl dp:DY
mixedStepReady:
              dec a
              sta dp:TEXU
              ldy dp:MAPIDX
              iny
              iny
mixedSpanPost: lda dp:TX
              clc
              adc dp:DX
              sta dp:TX
              asl a
              tax
              lda long:RAY_SPAN_HEIGHT,x
              sta abs:.word0 (heightIndex),y
              lda dp:TY
              clc
              adc dp:DY
              sta dp:TY
              lsr a
              lsr a
              lsr a
              jsr abs:.word0 (mixedMaterial)
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank),y
              iny
              iny
              dec dp:TEXU
              bne mixedSpanPost
;;; Skip the same generated child commands as a same-material span.
              jmp abs:.word0 (spanFillDone)

fillMixedWeightedSpan:
              stx dp:MAPIDX
              lda abs:.word0 (raySurface),x
              sta dp:TY
              lda abs:.word0 (heightIndex),x
              tay
              lda abs:.word0 (scaleHeight),y
              sta dp:DIST
              asl a
              asl a
              asl a
              sta dp:TX
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tay
              lda abs:.word0 (raySurface),y
              sec
              sbc dp:TY
              bpl mixedWeightedIncreasing
              jmp abs:.word0 (traceRay)
mixedWeightedIncreasing:
              sta dp:DY
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta abs:.word0 (mixedWeightProduct+2)
              lda abs:.word0 (heightIndex),y
              tay
              lda abs:.word0 (scaleHeight),y
              sec
              sbc dp:DIST
              sta dp:DX
              lda abs:.word0 (raySpacing)
              dec a
              sta dp:TEXU
              cmp ##3
              bne mixedWeightedEight
              asl dp:DX
              lda ##0xc140
              bra mixedWeightedDirectory
mixedWeightedEight:
              lda ##0xc280
mixedWeightedDirectory:
              sta abs:.word0 (mixedWeightRow+1)
              ldx dp:SCAN
mixedWeightRow: lda long:WEIGHTS_EIGHT,x
              sta abs:.word0 (mixedWeightedVector+2)
              xba
              and ##0xff00
              sta dp:MULP
              lda abs:.word0 (pixelAngle),x
              clc
              adc dp:ANGLE
              ldx dp:TILE
              bpl mixedWeightedAngle
              clc
              adc ##256
mixedWeightedAngle:
              inc a
              and ##508
              ldx abs:.word0 (raySpacing)
              cpx ##4
              beq mixedWeightedOffset
              asl a
mixedWeightedOffset:
              clc
              adc dp:MULP
              sta abs:.word0 (mixedWeightedVector+1)
              ldy dp:MAPIDX
              iny
              iny
mixedWeightedPost:
              lda dp:TX
              clc
              adc dp:DX
              sta dp:TX
              asl a
              tax
              lda long:RAY_SPAN_HEIGHT,x
              sta abs:.word0 (heightIndex),y
              ldx dp:TEXU
mixedWeightedVector:
              lda long:WEIGHTS,x
              and ##255
              asl a
              tax
mixedWeightProduct:
              lda long:0x000001,x
              and ##255
              clc
              adc dp:TY
              jsr abs:.word0 (mixedMaterial)
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank),y
              iny
              iny
              dec dp:TEXU
              bne mixedWeightedPost
              jmp abs:.word0 (spanFillDone)

fillSplitRaySpan:
              stx dp:MAPIDX
              lda abs:.word0 (raySurface),x
              sta dp:MULR
              asl a
              asl a
              asl a
              sta dp:TY
              lda abs:.word0 (heightIndex),x
              tay
              lda abs:.word0 (scaleHeight),y
              sta dp:DIST
              asl a
              asl a
              asl a
              sta dp:TX
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tay
              lda abs:.word0 (raySurface),y
              sec
              sbc dp:MULR
              sta dp:DY
              lda abs:.word0 (heightIndex),y
              tay
              lda abs:.word0 (scaleHeight),y
              sec
              sbc dp:DIST
              sta dp:DX
              lda abs:.word0 (raySpacing)
              cmp ##4
              bne splitStepReady
              asl dp:DX
              asl dp:DY
splitStepReady:
              dec a
              sta dp:TEXU
              ldy dp:MAPIDX
              iny
              iny
splitSpanPost: lda dp:TX
              clc
              adc dp:DX
              sta dp:TX
              asl a
              tax
              lda long:RAY_SPAN_HEIGHT,x
              sta abs:.word0 (heightIndex),y
              lda dp:TY
              clc
              adc dp:DY
              sta dp:TY
              lsr a
              lsr a
              lsr a
              cmp dp:FLAGS
              bcc splitLinearLeftPage
              and ##63
              asl a
              asl a
              ora dp:MULW
              bra splitLinearPageReady
splitLinearLeftPage:
              and ##63
              asl a
              asl a
              ora dp:PAGE
splitLinearPageReady:
              tax
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank),y
              iny
              iny
              dec dp:TEXU
              bne splitSpanPost
              jmp abs:.word0 (spanFillDone)

fillSplitWeightedSpan:
              stx dp:MAPIDX
              lda abs:.word0 (raySurface),x
              sta dp:TY
              lda abs:.word0 (heightIndex),x
              tay
              lda abs:.word0 (scaleHeight),y
              sta dp:DIST
              asl a
              asl a
              asl a
              sta dp:TX
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tay
              lda abs:.word0 (raySurface),y
              sec
              sbc dp:TY
              bpl splitWeightedIncreasing
              jmp abs:.word0 (traceRay)
splitWeightedIncreasing:
              sta dp:DY
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta abs:.word0 (splitWeightProduct+2)
              lda abs:.word0 (heightIndex),y
              tay
              lda abs:.word0 (scaleHeight),y
              sec
              sbc dp:DIST
              sta dp:DX
              lda abs:.word0 (raySpacing)
              dec a
              sta dp:TEXU
              cmp ##3
              bne splitWeightedEight
              asl dp:DX
              lda ##0xc140
              bra splitWeightedDirectory
splitWeightedEight:
              lda ##0xc280
splitWeightedDirectory:
              sta abs:.word0 (splitWeightRow+1)
              ldx dp:SCAN
splitWeightRow: lda long:WEIGHTS_EIGHT,x
              sta abs:.word0 (splitWeightedVector+2)
              xba
              and ##0xff00
              sta dp:MULP
              lda abs:.word0 (pixelAngle),x
              clc
              adc dp:ANGLE
              ldx dp:TILE
              bpl splitWeightedAngle
              clc
              adc ##256
splitWeightedAngle:
              inc a
              and ##508
              ldx abs:.word0 (raySpacing)
              cpx ##4
              beq splitWeightedOffset
              asl a
splitWeightedOffset:
              clc
              adc dp:MULP
              sta abs:.word0 (splitWeightedVector+1)
              ldy dp:MAPIDX
              iny
              iny
splitWeightedPost:
              lda dp:TX
              clc
              adc dp:DX
              sta dp:TX
              asl a
              tax
              lda long:RAY_SPAN_HEIGHT,x
              sta abs:.word0 (heightIndex),y
              ldx dp:TEXU
splitWeightedVector:
              lda long:WEIGHTS,x
              and ##255
              asl a
              tax
splitWeightProduct:
              lda long:0x000001,x
              and ##255
              clc
              adc dp:TY
              cmp dp:FLAGS
              bcc splitWeightedLeftPage
              and ##63
              asl a
              asl a
              ora dp:MULW
              bra splitWeightedPageReady
splitWeightedLeftPage:
              and ##63
              asl a
              asl a
              ora dp:PAGE
splitWeightedPageReady:
              tax
              lda long:WALL_COLUMNS,x
              sta abs:.word0 (sourceAddr),y
              lda long:WALL_COLUMNS+0x2,x
              sta abs:.word0 (sourceBank),y
              iny
              iny
              dec dp:TEXU
              bne splitWeightedPost
              jmp abs:.word0 (spanFillDone)

prepareSplitSpan:
              lda abs:.word0 (raySurface),x
              and ##0xffc0
              clc
              adc ##64
              sta dp:FLAGS
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tay
              lda abs:.word0 (raySurface),y
              and ##0xffc0
              cmp dp:FLAGS
              bne splitSpanUnavailable
;;; TX and TY retain both coordinate-cell materials. A flipped surface
;;; visits them in reverse map order; restore screen order for the split.
;;; DDA endpoint pages cannot replace these rounded-coordinate cells.
              lda abs:.word0 (mixedFlip+1)
              bne splitSpanReversed
              lda dp:TX
              ldy dp:TY
              bra splitSpanPages
splitSpanReversed:
              lda dp:TY
              ldy dp:TX
splitSpanPages:
              asl a
              sec
              sbc abs:.word0 (mixedPageOffset+1)
              xba
              sta dp:PAGE
              tya
              asl a
              sec
              sbc abs:.word0 (mixedPageOffset+1)
              xba
              sta dp:MULW
              ldx dp:MAPIDX
              sec
              rts
splitSpanUnavailable:
              clc
              rts

prepareMixedSpan:
              stx dp:MAPIDX
              lda dp:TILE
              bmi prepareHorizontalSpan
              and ##0x0fc0              ; strip the contiguous-run origin
              sta dp:MULP
              asl a
              clc
              adc ##0x2000
              sta abs:.word0 (mixedCheckTile+1)
              sta abs:.word0 (mixedFirstTile+1)
              lda ##2
              sta dp:FLAGS
              lda ##.word0 (mixedVerticalIndex)
              sta abs:.word0 (mixedAxis+1)
              lda dp:ROOTMAP
              lsr a
              and ##0x0fc0
              cmp dp:MULP
              bra prepareSpanFlip
prepareHorizontalSpan:
              and ##63
              asl a
              clc
              adc ##0x2000
              sta abs:.word0 (mixedCheckTile+1)
              sta abs:.word0 (mixedFirstTile+1)
              lda ##128
              sta dp:FLAGS
              lda ##.word0 (mixedHorizontalIndex)
              sta abs:.word0 (mixedAxis+1)
              lda dp:ROOTMAP
              lsr a
              and ##63
              sta dp:MULP
              lda dp:TILE
              and ##63
              cmp dp:MULP
prepareSpanFlip:
              lda ##0
              bcc spanFlipReady
              lda ##4095
spanFlipReady:
              sta abs:.word0 (mixedFlip+1)
              lda abs:.word0 (raySurface),x
              jsr abs:.word0 (mixedCellIndex)
              sta dp:DIST
              lda dp:SCAN
              clc
              adc abs:.word0 (raySpacing)
              tax
              lda abs:.word0 (raySurface),x
              jsr abs:.word0 (mixedCellIndex)
              cmp dp:DIST
              bcc mixedFirstCell
              ldx dp:DIST
              sta dp:DIST
              bra mixedFirstTile
mixedFirstCell:
              tax
;;; Prove a uniform span once. Only actual material changes need the
;;; per-post map lookup or the two-material split loop.
mixedFirstTile:
              lda long:TILE_MIRROR,x
              sta dp:PAGE
              sta dp:TX
              sta dp:TY
              beq mixedSpanInvalid
              bra mixedValidateTile
mixedCheckTile:
              lda long:TILE_MIRROR,x
              sta dp:TY
              beq mixedSpanInvalid
              cmp dp:PAGE
              beq mixedTileMatches
;;; Zero cannot match a valid tile, including after a material change.
              ldy ##0
              sty dp:PAGE
mixedValidateTile:
              cmp ##64
              bcs mixedSpanInvalid
mixedTileMatches:
              cpx dp:DIST
              beq mixedSpanValid
              txa
              clc
              adc dp:FLAGS
              tax
              bra mixedCheckTile
mixedSpanInvalid:
              lda ##65535
              sta dp:PAGE
              ldx dp:MAPIDX
              clc
              rts
mixedSpanValid:
              lda dp:PAGE
              beq mixedSpanSetup
              dec a
              asl a
              ldx dp:TILE
              bmi mixedUniformPage
              inc a
mixedUniformPage:
              xba
              sta dp:PAGE
mixedSpanReady:
              ldx dp:MAPIDX
              sec
              rts
mixedSpanSetup:
;;; Only mixed spans need the per-post lookup's row and page orientation.
              lda ##65535
              sta dp:PAGE
              lda abs:.word0 (mixedCheckTile+1)
              sta abs:.word0 (mixedTile+1)
              lda ##1
              ldx dp:TILE
              bpl mixedSpanPageOffset
              inc a
mixedSpanPageOffset:
              sta abs:.word0 (mixedPageOffset+1)
              bra mixedSpanReady
mixedMaterial:
              sta dp:MULV
              and ##63
              asl a
              asl a
              sta dp:MULP
              lda dp:MULV
              jsr abs:.word0 (mixedCellIndex)
              tax
mixedTile:    lda long:TILE_MIRROR,x
              asl a
              sec
mixedPageOffset:
              sbc ##2
              xba
              ora dp:MULP
              tax
              rts
mixedCellIndex:
mixedFlip:    eor ##0
              and ##0x0fc0
mixedAxis:    jmp abs:.word0 (mixedVerticalIndex)
mixedHorizontalIndex:
              asl a
              rts
mixedVerticalIndex:
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              rts
#endif

#if WOLF_PREPARED
;;; The angle table includes the integer angle rounding between endpoints.
weightedRay:  lda dp:TILE
              bit ##0x4000
              beq weightedWall
              jmp abs:.word0 (traceRay)
weightedWall:
#if WOLF_SPAN_FILL
              lda abs:.word0 (raySpacing)
              cmp ##4
              bcc weightedSingle
              cmp ##9
              bcs weightedSingle
              lda dp:PAGE
              bmi mixedWeightedSpan
weightedSpanJump:
              jmp abs:.word0 (fillWeightedSpan)
mixedWeightedSpan:
              jsr abs:.word0 (prepareMixedSpan)
              bcc weightedSingle
              lda dp:PAGE
              bmi mixedWeightedMaterials
uniformWeightedSpanJump:
              jmp abs:.word0 (fillWeightedSpan)
mixedWeightedMaterials:
              jsr abs:.word0 (prepareSplitSpan)
              bcc mixedWeightedSpanMap
splitWeightedSpanJump:
              jmp abs:.word0 (fillSplitWeightedSpan)
mixedWeightedSpanMap:
mixedWeightedSpanJump:
              jmp abs:.word0 (fillMixedWeightedSpan)
weightedSingle:
#endif
              ldx dp:SCAN
              lda long:VIEW_WEIGHTS,x
              sta dp:ENTRY+1
              lda abs:.word0 (pixelAngle),x
              clc
              adc dp:ANGLE
              ldx dp:TILE
              bpl weightVertical
              clc
              adc ##256
weightVertical:
              and ##511
              tay
              lda [ENTRY],y
              and ##255
              asl a
              sta dp:MULP
              lda dp:SCAN
              sec
#if WOLF_QUARTER_RAYS
              sbc abs:.word0 (raySpacing)
#else
              sbc ##2
#endif
              tax
              lda abs:.word0 (raySurface),x
              sta dp:MULV
              lda dp:SCAN
              clc
#if WOLF_QUARTER_RAYS
              adc abs:.word0 (raySpacing)
#else
              adc ##2
#endif
              tax
              lda abs:.word0 (raySurface),x
              sec
              sbc dp:MULV
              bpl weightPositiveGap
              jmp abs:.word0 (traceRay)
weightPositiveGap:
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta dp:ENTRY+1
              ldy dp:MULP
              lda [ENTRY],y
              xba
              and ##255
              clc
              adc dp:MULV
              sta dp:RAY
              jmp abs:.word0 (midpointHeight)
#endif

#if WOLF_PREPARED
;;; A material boundary does not change the wall plane. Resolve the
;;; midpoint cell directly; gaps and moving walls still need an exact trace.
resolveRayMaterial:
              lda dp:TILE
              bmi horizontalMaterial
              lda dp:RAY
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:MULP
              lda dp:TILE
              and ##0x0fc0
              sta dp:MULR
              lda dp:ROOTMAP
              lsr a
              and ##0x0fc0
              cmp dp:MULR
              bcc verticalMaterialCell
              lda dp:MULP
              eor ##63
              sta dp:MULP
verticalMaterialCell:
              lda dp:TILE
              and ##0x0fc0
              ora dp:MULP
              bra midpointMaterialCell
horizontalMaterial:
              lda dp:RAY
              and ##0x0fc0
              sta dp:MULP
              lda dp:ROOTMAP
              lsr a
              and ##63
              sta dp:MULR
              lda dp:TILE
              and ##63
              cmp dp:MULR
              bcc horizontalMaterialCell
              lda dp:MULP
              eor ##0x0fc0
              sta dp:MULP
horizontalMaterialCell:
              lda dp:TILE
              and ##63
              ora dp:MULP
midpointMaterialCell:
              asl a
              tax
              lda long:TILE_MIRROR,x
              beq uncertainMaterial
              cmp ##64
              bcs uncertainMaterial
              dec a
              asl a
              ldx dp:TILE
              bmi midpointMaterialPage
              inc a
midpointMaterialPage:
              xba
              sta dp:PAGE
              sec
              rts
uncertainMaterial:
              clc
              rts
#endif

;;; The texture address uses only the fractional coordinate.
mulLowFrac:   jsr abs:.word0 (mulFrac)
              and ##255
              rts

hitCoordinate:
              lda dp:RA
              asl a
              tax
              lda dp:SIDE
              bne hitX
#if WOLF_PREPARED
hitYBody:     lda long:SIN_ROWS,x
              beq hitYIdentity
              stz dp:MULP
              sta dp:MULP+1
              lda dp:DIST
              and ##255
              asl a
              tay
              lda [MULP],y
              xba
              and ##255
              sta dp:MULV
              lda dp:DIST
              xba
              and ##255
              asl a
              tay
              lda [MULP],y
              clc
              adc dp:MULV
              bra hitYProductReady
hitYIdentity:
              lda dp:DIST
hitYProductReady:
#else
              lda long:ABS_SIN_TABLE,x
              tay
              lda dp:DIST
              jsr abs:.word0 (mulLowFrac)
#endif
              ldx dp:STEPY
              bpl positiveYHit
              eor ##65535
              inc a
positiveYHit: clc
              adc dp:VY
              bra coordinateDone
hitX:
#if WOLF_PREPARED
              lda long:COS_ROWS,x
              beq hitXIdentity
              stz dp:MULP
              sta dp:MULP+1
              lda dp:DIST
              and ##255
              asl a
              tay
              lda [MULP],y
              xba
              and ##255
              sta dp:MULV
              lda dp:DIST
              xba
              and ##255
              asl a
              tay
              lda [MULP],y
              clc
              adc dp:MULV
              bra hitXProductReady
hitXIdentity:
              lda dp:DIST
hitXProductReady:
#else
              lda long:ABS_COS_TABLE,x
              tay
              lda dp:DIST
              jsr abs:.word0 (mulLowFrac)
#endif
              ldx dp:STEPX
              bpl positiveXHit
              eor ##65535
              inc a
positiveXHit: clc
              adc dp:VX
coordinateDone:
#if WOLF_PREPARED
              lsr a
              lsr a
              sta dp:RAY
              and ##63
#else
              and ##255
              lsr a
              lsr a
#endif
              sta dp:TEXU
              rts

doorHit:      lda dp:TILE
              bit ##64
              beq ordinaryDoorHit
              jmp abs:.word0 (PWallHit)
ordinaryDoorHit:
              and ##127
              asl a
              sta dp:DOORID
              tax
              lda abs:.word0 (doorOrient),x
              beq horizontalDoor
              stz dp:SIDE
              lda dp:DX
              lsr a
              sta dp:MULR
              lda dp:TX
              sec
              sbc dp:MULR
              bra doorDistance
horizontalDoor:
              lda ##1
              sta dp:SIDE
              lda dp:DY
              lsr a
              sta dp:MULR
              lda dp:TY
              sec
              sbc dp:MULR
doorDistance: cmp dp:DIST
              bcc doorPass
              cmp dp:TX
              bcs doorPass
              cmp dp:TY
              bcs doorPass
              sta dp:DIST
              jsr abs:.word0 (hitCoordinate)
#if WOLF_PREPARED
              jsl long:ClampDoorCoordinate
#endif
              lda dp:TEXU
              asl a
              asl a
              ldx dp:DOORID
              cmp abs:.word0 (doorPosition),x
              bcc doorPass
              sec
              sbc abs:.word0 (doorPosition),x
              lsr a
              lsr a
              sta dp:TEXU
#if WOLF_PREPARED
              lda dp:RAY
              and ##0xffc0
              ora dp:TEXU
              sta dp:RAY
#endif
              lda ##DOORWALL
              ldx dp:SIDE
              bne doorPageReady
              inc a
doorPageReady:
              sta dp:PAGE
              sec
              rts
doorPass:     clc
              rts

;;; Draw only the final wall and the flats it exposes. Both are inside
;;; this column's paint before the scan advances; the old view stays whole
;;; until the scan begins. The scaler's clipped exit byte is restored.
#if WOLF_TRUE_PIXELS
              .extern PaintTrueFrame
paintFrame:   jmp abs:.word0 (PaintTrueFrame)
#elif WOLF_PREPARED
;;; Phase A decides every column right to left before any store and pushes
;;; its spans on a bank-0 list. Phase B pops it left to right: each stub
;;; only pulls registers and returns into row code, whose RTL pulls the next
;;; stub. Interrupts push below S, into list bytes already used.
              .extern flatOp, flatCode
              .extern weaponMaskTable, oldWeaponMaskTable, weaponScaleIndex
              .extern maskFallback, maskOwners, maskColumnBytes, maskBitOnlyUsed
MX_EP         .equ SP_C                 ; long pointer: an owner height's endpoint rows
PA_CEIL       .equ TOP                  ; plain column: rows of new ceiling
MW_H          .equ HEIGHT               ; mixed column: the wall's height,
MW_T          .equ SP_LEFT              ; clipped top and bottom rows,
MW_B          .equ SP_RIGHT
MW_SRC        .equ SP_DX                ; source,
MW_BK         .equ SP_DY                ; lit bank << 8 | scaler bank,
MW_RCB        .equ BOTTOM               ; long row-code pointer; OLDTOP holds its bank
OWNER_INFO_MAX .equ 128                 ; visible records with prepared owner words
OW_NEXT       .equ OLDBOTTOM            ; where an owner's runs go on
BG_RET        .equ ENTRY                ; where background rows go on
BG_WT         .equ ENTRY+2               ; clipped wall top in the direct wall walkers
OW_CV0        .equ EXITP                ; covered bytes when the owner began
MX_TMP        .equ EXITP+2
OW_PTR        .equ SP_PTR               ; long pointer: the owner's current run
OW_RCB        .equ SP_BASE              ; row code base,
OW_BK         .equ SP_EXTRA             ; lit source bank << 8 | scaler bank,
OW_VB         .equ SP_N                 ; and view exit row
MX_MASK       .equ SP_SHAPE
EXTRA_OWNER_BASE .equ SP_HI            ; extra-mask directory offset; fastOwner is inactive here
MX_BIT        .equ SP_VPOS
CUR           .equ SP_TMP
CV_N          .equ SP_RUNS              ; bytes used in coverList
CV_I          .equ SP_FPOS
RN_T          .equ SP_ROW               ; the run, clipped to the dirty rows
RN_B          .equ SP_END
RN_SRC        .equ SP_SRC
RN_BK         .equ SP_BANK              ; lit bank << 8 | scaler bank
MX_WNEW       .equ SP_OLD
PC_T          .equ SP_CACHE             ; a piece [PC_T, PC_B)
PC_B          .equ SP_CACHE+2
MX_WOLD       .equ SP_NEW
MX_WSKIP      .equ SP_WEAPON
DW_T          .equ DX                   ; wall rows to repaint [DW_T, DW_B)
DW_B          .equ DY
G1_T          .equ TX                   ; rows sprites showed last frame:
G1_B          .equ TY                   ; one hull above row 80,
G2_T          .equ DIST                 ; one at or below it
G2_B          .equ SIDE
NG1_T         .equ RA                   ; the same hulls for this frame
NG1_B         .equ TILE
NG2_T         .equ MULV
NG2_B         .equ MULP
CLIPB         .equ MULR                 ; bottom edge still open to farther owners
WK_T          .equ MULW                 ; dirty rows [WK_T, WK_B) for bgWalk
WK_B          .equ TEXU
WK_RET        .equ PAGE
CV_UP         .equ MAPIDX               ; fast path: coverList bytes of runs below the wall
FW_COLOR      .equ STEPX                ; flatWalk: flat bank and color
FP_LO         .equ STEPY                ; fast path: the low end of a coverList part
FP_WT         .equ EXITBYTE             ; fast path: the wall's first row below runs reaching into it
FP_ANY        .equ SP_HI                ; fast path: a nearer sprite's runs are placed
DN_T          .equ SP_SIDE              ; moved light column: its run below the wall,
DN_B          .equ SP_BEST
DN_BK         .equ MAPIDX
UP_T          .equ SP_PREV              ; its run above the wall,
UP_B          .equ PA_HULL
UP_SRC        .equ RAY
UP_BK         .equ CASTPASS
RG_T          .equ SP_RUNS              ; and a run that flat rows go around
RG_B          .equ SP_FPOS
FP_WALLB      .equ RAY                  ; fast path: the wall's last row + 1 above the weapon
TIGHT_END     .equ CASTPASS             ; tight run: 2*column to stop at
MX_FLAGS      .equ SP_DEPTH             ; this and last frame's column marks
;;; Local span builders keep continuations in code, not DP scratch.
;;; A is the bottom row on cut entry; draw records are unchanged.
;;; The wall token identifies all four lit sources. Height selects the light,
;;; so the material tag is needed by rays but not by the prepared paint cache.
;;; Tokens are 16-byte aligned; light offsets occupy only their low four bits.
;;; Both macros consume X. Save the column only when the continuation needs it.
PUSH_WALL_SOURCE .macro
              lda abs:.word0 (sourceAddr),x
              sta abs:.word0 (oldSource),x
              ora abs:.word0 (lightDelta),y
              tax
              lda long:WALL_LIGHT_POINTERS,x
              pha
              lda long:WALL_LIGHT_POINTERS+2,x
              ora abs:.word0 (viewScaleBank),y
              .endm
RESOLVE_WALL_SOURCE .macro
              lda abs:.word0 (sourceAddr),x
              ora abs:.word0 (lightDelta),y
              tax
              lda long:WALL_LIGHT_POINTERS,x
              sta dp:MW_SRC
              lda long:WALL_LIGHT_POINTERS+2,x
              ora abs:.word0 (viewScaleBank),y
              sta dp:MW_BK
              .endm
PUSH_RAW_CUT .macro
              asl a
              tay
              lda [OW_RCB],y
              tax
              lda dp:PC_T
              asl a
              tay
              lda [OW_RCB],y
              dec a
              pha
              pei dp:PA_SX
              ldy dp:OW_LIGHT
              lda [OW_PTR],y
              pha
              phx
              pei dp:OW_BK
              pea #CUTOP-1
              .endm
PUSH_RAW_UNCUT .macro
              lda dp:PC_T
              asl a
              tay
              lda [OW_RCB],y
              dec a
              pha
              pei dp:PA_SX
              ldy dp:OW_LIGHT
              lda [OW_PTR],y
              pha
              pei dp:OW_BK
              pea #WALLOP-1
              .endm
PUSH_CACHED_CUT .macro top, base, source, banks
              asl a
              tay
              lda [\base],y
              tax                       ; the cut stub retains this exit for its bank
              lda dp:\top
              asl a
              tay
              lda [\base],y
              dec a
              pha
              pei dp:PA_SX
              pei dp:\source
              phx
              pei dp:\banks
              pea #CUTOP-1
              .endm
PUSH_CACHED_UNCUT .macro top, base, source, banks
              lda dp:\top
              asl a
              tay
              lda [\base],y
              dec a
              pha
              pei dp:PA_SX
              pei dp:\source
              pei dp:\banks
              pea #WALLOP-1
              .endm

paintFrame:   lda dp:FIRST
              bne paintFirst
              lda dp:VISSTAMP
              cmp abs:.word0 (paintStamp)
              bne paintChanged
              lda abs:.word0 (weaponMaskTable)
              cmp abs:.word0 (oldWeaponMaskTable)
              bne paintChanged
              ldx abs:.word0 (viewWidth)
              txa
              and ##1
              beq paintEvenMarks
              dex                       ; the 214-pixel view has one unpaired mark
              sep #0x20
              lda long:MARKS,x
              bit #16
              rep #0x20
              bne paintChanged
paintEvenMarks:
              dex
              dex
paintMarkTest:
              lda long:MARKS,x
              bit ##0x1010
              bne paintChanged
              dex
              dex
              bpl paintMarkTest
;;; Cached rays and unchanged projections leave the whole view intact.
;;; PrepareSprites still expects paint to clear the masks it just built.
              lda abs:.word0 (viewWidth)
              asl a
              tax
              lda ##0
paintClearMasks:
              dex
              dex
              sta long:COLUMN_MASKS,x
              bne paintClearMasks
              rts
paintChanged: jmp abs:.word0 (paintPrepare)
paintFirst:   lda abs:.word0 (viewWidth)
              asl a
              tax
firstColumns: dex
              dex
              lda ##398                 ; a full-view wall: both flats are new
              sta abs:.word0 (oldHeight),x
              lda ##0xffff              ; no wall column starts at an odd byte
              sta abs:.word0 (oldSource),x
              lda ##255                 ; no sprite rows shown yet
              sta abs:.word0 (ghost1T),x
              sta abs:.word0 (ghost2T),x
              lda ##0
              sta abs:.word0 (ghost1B),x
              sta abs:.word0 (ghost2B),x
              sta long:OLD_MARKS,x       ; old weapon marks index a different view's compact directory
              txa
              bne firstColumns
              stz abs:.word0 (mixLowLast) ; a new view checks every column
              lda abs:.word0 (viewWidth)
              sta abs:.word0 (mixHighLast)
paintPrepare:
;;; Normally every owner-mask bit also sets a world mark, so a plain or
;;; weapon-only column has a zero mask already. A bit-only owner requires
;;; the original clear. Patch LDA #0 into BRA over the clear when it is idle;
;;; the third immediate byte stays zero for the next frame's LDA.
              lda ##0x00a9
              ldx abs:.word0 (maskBitOnlyUsed)
              bne paintMaskClearMode
              lda ##0x80+256*(plainMaskReady-plainMaskClear-2)
paintMaskClearMode:
              sta abs:.word0 (plainMaskClear)
              sta abs:.word0 (clipMaskClear)
              lda ##0x0300
              sta dp:LASTCUT3+1
              lda ##0x0400
              sta dp:LASTCUT4+1
              lda ##0x0500
              sta dp:LASTCUT5+1
              stz dp:LASTCUT3
              stz dp:LASTCUT4
              stz dp:LASTCUT5
              lda dp:VISSTAMP
              sta abs:.word0 (paintStamp)
              stz dp:PC_T               ; all later row-word writes keep their high bytes zero
              stz dp:PC_B
              stz dp:RN_T
              stz dp:RN_B
              lda ##0x09                 ; sprite endpoint rows live in bank $09
              sta dp:MX_EP+2
;;; OW_RCB is a long row-code pointer during painting. Its bank occupies
;;; the projection-only SP_LIMIT word, which painting otherwise leaves idle.
              lda ##.byte2 (ROWCODE)
              sta dp:OW_RCB+2
              sta dp:MW_RCB+2
              lda ##WORLD_RUN_BANK
              sta dp:OW_PTR+2
              lda ##0xffff
              sta dp:MW_H               ; no wall row bounds have been prepared yet
              sta dp:FP_LASTREC
              sta abs:.word0 (lightLastMask)
              tsc
              sta dp:PA_STACK
              lda ##PAINT_LIST
              tcs
              phk
              pea #.word0 (paintListDone-1)
              lda ##.word0 (preparedColumn)
              sta abs:.word0 (prepareDone+1)
              lda abs:.word0 (viewWidth)
              dec a
              sta dp:COL
              asl a
              sta dp:SCAN
              lda dp:COL
              clc
              adc abs:.word0 (viewLeft)
              sta dp:PA_SX
;;; Once a frame, per visible record: row code base, light/scaler banks,
;;; view exit and endpoint rows. Each record retains the selected light-word
;;; offset at +4 and the command bank at +12.
              lda dp:SP_COUNT
              cmp ##OWNER_INFO_MAX
              bcc ownerInfoCount
              lda ##OWNER_INFO_MAX
ownerInfoCount:
              asl a
              asl a
              asl a
              asl a
              tax
              stz dp:MX_BIT
              beq ownerInfoStart
;;; The final submitted record is the weapon when present. Its literal
;;; drawers never read ownerInfo, and sorting places it before world owners.
              lda long:SPR_RECORDS-4,x
              inc a
              bne ownerInfoStart
              lda ##2
              sta dp:MX_BIT             ; skip that first order entry in the decal scan
              txa
              sec
              sbc ##16
              tax
ownerInfoStart:
              bra ownerInfoTest
ownerInfoLoop:lda long:SPR_RECORDS+6,x
              sta abs:.word0 (ownerInfo+10),x
              lda long:SPR_RECORDS+4,x
              tay
              lda abs:.word0 (rowCodeBase),y
              sta abs:.word0 (ownerInfo),x
              lda abs:.word0 (lightDelta),y
              lsr a
              clc
              adc ##2
              sta abs:.word0 (ownerInfo+4),x
              phx
              lda long:SPR_RECORDS+6,x
              tax
              lda long:SPRITE_CMDS+SPR_COMMAND_BANK,x
              sta dp:OW_PTR+2
              lda abs:.word0 (lightDelta),y
              lsr a
              lsr a
              sta dp:RAW_EXIT
              txa
              clc
              adc dp:RAW_EXIT
              tax
              lda long:SPRITE_CMDS+SPR_LIGHT_BANKS,x
              and ##255
              xba
              ora abs:.word0 (viewScaleBank),y
              plx
              sta abs:.word0 (ownerInfo+2),x
              lda dp:OW_PTR+2
              sta abs:.word0 (ownerInfo+12),x
              cpy ##62
              bcs ownerScaleReady
              phx
              lda long:SPR_RECORDS+6,x
              tax
              lda long:SPRITE_CMDS+SPR_GAP,x
              plx
              and ##0x8000
              beq ownerScaleReady
              inc abs:.word0 (ownerInfo+2),x
ownerScaleReady:
              lda abs:.word0 (viewScaleBottom),y
              sta abs:.word0 (ownerInfo+6),x
              lda abs:.word0 (epPage),y
              sta abs:.word0 (ownerInfo+8),x
ownerInfoTest:txa
              sec
              sbc ##16
              tax
              bpl ownerInfoLoop
;;; Mask bits follow the near-first order of the world sprites. A sprite
;;; with a transparent middle band (a ceiling light) may take the fast path.
              stz abs:.word0 (decalMask)
              lda ##1
              sta dp:MX_MASK
decalNext:    lda dp:MX_BIT
              lsr a
              cmp dp:SP_COUNT
              bcs decalDone
              ldx dp:MX_BIT
              inc dp:MX_BIT
              inc dp:MX_BIT
              lda long:SPR_ORDER,x
              tax
              lda long:SPR_RECORDS+12,x
              inc a
              beq decalNext             ; the weapon has no mask bit
              cpx ##OWNER_INFO_MAX*16
              bcs decalSkip
              lda long:SPR_RECORDS+6,x
              tax
              lda long:SPRITE_CMDS+SPR_GAP,x       ; its band's top texel: 255 for none
              and ##255
              cmp ##255
              beq decalSkip
              lda dp:MX_MASK
              tsb abs:.word0 (decalMask)
decalSkip:    asl dp:MX_MASK
              bne decalNext
decalDone:
;;; Only columns inside this or last frame's sprite silhouettes can carry a
;;; mark; the others run as plain columns without the mark test.
              lda ##255
              sta dp:MX_MASK            ; this frame's lowest column
              stz dp:MX_BIT             ; and highest + 1
              lda dp:SP_COUNT
              asl a
              tax
              bra mixTest
mixLoop:      lda long:SILHOUETTES,x       ; first column | last + 1 << 8
              tay
              and ##255
              sta dp:CUR
              tya
              xba
              and ##255
              cmp dp:CUR
              beq mixTest
              bcc mixTest
              cmp dp:MX_BIT
              bcc mixHighKept
              sta dp:MX_BIT
mixHighKept:  lda dp:CUR
              cmp dp:MX_MASK
              bcs mixTest
              sta dp:MX_MASK
mixTest:      dex
              dex
              bpl mixLoop
              lda dp:MX_MASK
              cmp abs:.word0 (mixLowLast)
              bcc mixLowReady
              lda abs:.word0 (mixLowLast)
mixLowReady:  sta abs:.word0 (mixLow)
              lda dp:MX_BIT
              cmp abs:.word0 (mixHighLast)
              bcs mixHighReady
              lda abs:.word0 (mixHighLast)
mixHighReady: sta abs:.word0 (mixHigh)
              lda dp:MX_MASK
              sta abs:.word0 (mixLowLast)
              lda dp:MX_BIT
              sta abs:.word0 (mixHighLast)
;;; Every path keeps the wall record current, including moving lights.
;;; Stopping the camera therefore needs no forced wall refresh.
              lda abs:.word0 (castPX)
              cmp abs:.word0 (paintPX)
              bne poseMoved
              lda abs:.word0 (castPY)
              cmp abs:.word0 (paintPY)
              bne poseMoved
              lda abs:.word0 (castAngle)
              cmp abs:.word0 (paintAngle)
              bne poseMoved
              stz dp:WALLS_MOVED
              lda abs:.word0 (weaponMaskTable)
              sbc abs:.word0 (oldWeaponMaskTable) ; the equal pose comparison set carry
              sta abs:.word0 (heldWeaponChanged)
              bra prepareColumn
poseMoved:    lda abs:.word0 (castPX)
              sta abs:.word0 (paintPX)
              lda abs:.word0 (castPY)
              sta abs:.word0 (paintPY)
              lda abs:.word0 (castAngle)
              sta abs:.word0 (paintAngle)
              lda ##1
              sta dp:WALLS_MOVED
prepareColumn:
              lda dp:COL
              cmp abs:.word0 (mixLow)
              bcc tightBelow
              cmp abs:.word0 (mixHigh)
              bcc prepareChecked
              lda abs:.word0 (mixHigh)  ; above the marked range: down to it
              dec a
              asl a
              bra tightRun
tightBelow:   lda ##0xfffe              ; below it: down to column 0
tightRun:     sta dp:TIGHT_END
              tsc                       ; a plain column pushes 26 bytes at most
              sec
              sbc ##PAINT_GUARD+160*26
              bcc prepareChecked
              ldx dp:SCAN
tightDispatch: jmp abs:.word0 (tightLoop)
              .public preparedAll, deferDone, deferOp, paintListDone, bufferFinishHook
              .public drawWeaponPose, weaponPoseCall, weaponPoseBank, weaponDrawerEntries
              .public viewScaleExit, viewScaleBottom
preparedAll:  sep #0x20
              rtl                       ; the first pull starts the scan
;;; The next column after a checked one lies below the marked range's top, so
;;; only its bottom can end the range.
preparedColumn:
              dec dp:PA_SX
              ldx dp:SCAN
              dex
              dex
              stx dp:SCAN
              dec dp:COL
              bmi preparedAll
              lda dp:COL
              cmp abs:.word0 (mixLow)
              bcc tightBelow
prepareChecked:
              tsc
              cmp ##PAINT_GUARD
              bcs prepareOne
              jmp abs:.word0 (deferColumns)
prepareOne:   ldx dp:COL
              lda long:OLD_MARKS,x
              ora long:MARKS,x
              bit ##1
              beq preparePlain
              jmp abs:.word0 (prepareFlagged)
;;; A plain column: its wall, then the flat rows its edges uncovered. A
;;; flat run of c rows enters the shared row stores at entry-1 =
;;; flatCode+640-4c-1 and ends at the X row.
preparePlain: ldx dp:SCAN
plainMaskClear:
              lda ##0
              sta long:COLUMN_MASKS,x
plainMaskReady:
              lda abs:.word0 (heightIndex),x
              cmp abs:.word0 (oldHeight),x
              bne plainHeight
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne plainSource
              bra prepareDone
plainSource:  ldy abs:.word0 (heightIndex),x
plainWallOnly:lda abs:.word0 (viewScaleAddr),y ; entry-1
              pha
              pei dp:PA_SX
              PUSH_WALL_SOURCE
              pha
              pea #WALLOP-1             ; the same stub offset in every scaler bank
prepareDone:  jmp abs:.word0 (preparedColumn) ; a deferred column patches this
plainGrow:    sta abs:.word0 (oldHeight),x ; as tightGrow: no flat row shows
              bra plainWallOnly
plainHeight:  tay                       ; Y: new height, X: old height
              bcs plainGrow
              lda abs:.word0 (oldHeight),x
              sta dp:PA_OLD
              tya
              sta abs:.word0 (oldHeight),x
              ldx dp:PA_OLD
              lda abs:.word0 (viewScaleTop),y
              sec
              sbc abs:.word0 (viewScaleTop),x
              sta dp:PA_CEIL
              lda abs:.word0 (viewScaleBottom),x
              sec
              sbc abs:.word0 (viewScaleBottom),y
              beq plainWall
              bcc plainWall
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda abs:.word0 (bottomRowX),x
              clc
              adc dp:PA_SX
              pha
flat_floor_wolf_2_0:
              pea #(FLATBANK+FLOOR*256)
              pea #.word0 (flatOp-1)
plainWall:    ldx dp:SCAN
              lda abs:.word0 (viewScaleAddr),y
              pha
              pei dp:PA_SX
              PUSH_WALL_SOURCE
              pha
              pea #WALLOP-1
              lda dp:PA_CEIL
              beq prepareDone
              bmi prepareDone
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda abs:.word0 (topRowX),y
              clc
              adc dp:PA_SX
              pha
flat_ceiling_wolf_2_1:
              pea #(FLATBANK+CEILING*256)
              pea #.word0 (flatOp-1)
              jmp abs:.word0 (prepareDone)
;;; Plain columns in a row, the column in X: the same records as
;;; preparePlain, without the mark test or the overflow check.
tightLoop:    lda abs:.word0 (heightIndex),x
              cmp abs:.word0 (oldHeight),x
              bne tightHeight
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne tightSource
tightNext:    dec dp:PA_SX
              dex
              dex
              cpx dp:TIGHT_END
              bne tightLoop
tightRangeDone:
              stx dp:SCAN
              txa
              cmp ##0x8000
              ror a
              sta dp:COL
              bmi tightAll
              jmp abs:.word0 (prepareColumn)
tightAll:     jmp abs:.word0 (preparedAll)
tightSource:  ldy abs:.word0 (heightIndex),x
tightWall:    lda abs:.word0 (viewScaleAddr),y
tightWallEntry:
              pha
              pei dp:PA_SX
              stx dp:WALL_COL
              PUSH_WALL_SOURCE
              ldx dp:WALL_COL
              pha
              pea #WALLOP-1
              bra tightNext
;;; The compare that sent the column here left carry set when the new wall is
;;; as tall as the old one or taller: it covers the old rows, no flat shows.
tightGrow:    sta abs:.word0 (oldHeight),x ; A: the new height
              bra tightWall
tightHeight:  tay
              bcs tightGrow
tightLower:   lda abs:.word0 (oldHeight),x
              sta dp:PA_OLD
              tya
              sta abs:.word0 (oldHeight),x
              lda abs:.word0 (viewScaleAddr),y
              pha
              pei dp:PA_SX
              stx dp:WALL_COL
              PUSH_WALL_SOURCE
              ldx dp:WALL_COL
              pha
              pea #WALLOP-1
              stx dp:SCAN
              ldx dp:PA_OLD
              lda abs:.word0 (viewScaleBottom),x
              sec
              sbc abs:.word0 (viewScaleBottom),y
              beq tightNoFloor
              bcc tightNoFloor
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda abs:.word0 (bottomRowX),x
              clc
              adc dp:PA_SX
              pha
flat_floor_wolf_2_2:
              pea #(FLATBANK+FLOOR*256)
              pea #.word0 (flatOp-1)
tightNoFloor: lda abs:.word0 (viewScaleTop),y
              sec
              sbc abs:.word0 (viewScaleTop),x
              beq tightNoCeiling
              bmi tightNoCeiling
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda abs:.word0 (topRowX),y
              clc
              adc dp:PA_SX
              pha
flat_ceiling_wolf_2_3:
              pea #(FLATBANK+CEILING*256)
              pea #.word0 (flatOp-1)
tightNoCeiling:
              ldx dp:SCAN
              jmp abs:.word0 (tightNext)
;;; Overflow guard: the remaining left columns are prepared in the scan, each
;;; just before its own stores, below the list position it has reached.
deferColumns: ldy ##0                   ; column 0 first: the scan then prepares the
deferPush:    tya                       ; right-hand column first, as the marks need
              xba
              ora ##2                   ; deferOp's bank, then the column
              pha
              pea #.word0 (deferOp-1)
              cpy dp:COL
              iny
              bcc deferPush
              jmp abs:.word0 (preparedAll)
deferOp:      pla
              phk
              plb
              rep #0x30
              and ##255
              sta dp:COL
              asl a
              sta dp:SCAN
              lda dp:COL
              clc
              adc abs:.word0 (viewLeft)
              sta dp:PA_SX
              lda ##.word0 (deferDone)
              sta abs:.word0 (prepareDone+1)
              jmp abs:.word0 (prepareOne)
deferDone:    sep #0x20
              rtl

;;; A column a sprite or the weapon marks now or marked last frame. An
;;; unchanged weapon alone is a floor clip: when every changed row lies
;;; above its top opaque row, the column is plain.
prepareFlagged:
              sta dp:MX_FLAGS
              ldy dp:WALLS_MOVED
              beq flaggedHeld
              bit ##4
              bne flaggedChecks
              jmp abs:.word0 (movedLight)
;;; Projection invalidation includes height, shape, bounds and retirement.
;;; sortVisible uses height and stable source order, so unchanged projections
;;; retain their ordering too, as the general mixed-column path requires.
flaggedHeld:   bit ##16
              bne flaggedChecks
              ldy abs:.word0 (heldWeaponChanged)
              bne flaggedChecks
              ldx dp:SCAN
              lda abs:.word0 (heightIndex),x
              cmp abs:.word0 (oldHeight),x
              bne flaggedKeepMiss
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne flaggedKeepMiss
              jmp abs:.word0 (mixedDone)
flaggedKeepMiss:
              ldx dp:COL
              lda dp:MX_FLAGS
flaggedChecks:
              bit ##8
              bne prepareMixedJ         ; a world sprite is or was in front
              lda long:MARKS,x
              and ##255
              bit ##16                  ; a sprite rectangle changed here
              bne prepareMixedJ
              lda dp:SCAN
              clc
              adc abs:.word0 (oldWeaponMaskTable)
              tax
              lda long:WEAPON_RUNS,x
              sta dp:MX_WOLD
              lda dp:SCAN
              clc
              adc abs:.word0 (weaponMaskTable)
              tax
              lda long:WEAPON_RUNS,x
              cmp dp:MX_WOLD
              bne prepareMixedJ
              tax
              stx dp:MX_WNEW
              ldy ##255
              lda long:WEAPON_RUNS,x       ; run count, then the top opaque row
              bit ##255
              beq weaponClipRow         ; no runs: nothing to clip
              xba
              and ##255
              tay
weaponClipRow:
              sty dp:MX_TMP
              ldx dp:SCAN
              ldy abs:.word0 (oldHeight),x
              lda abs:.word0 (viewScaleBottom),y
              ldy abs:.word0 (heightIndex),x
              cmp abs:.word0 (viewScaleBottom),y
              bcs weaponClipBottom
              lda abs:.word0 (viewScaleBottom),y
weaponClipBottom:
              cmp dp:MX_TMP
              beq weaponClipPlain
              bcc weaponClipPlain
              ldx dp:MX_WNEW            ; one run down to the view's bottom: the
              lda long:WEAPON_RUNS,x       ; wall stops at its top
              and ##255
              cmp ##1
              bne prepareMixedJ
              lda long:WEAPON_RUNS+0x3,x
              and ##255
              cmp abs:.word0 (viewBottom)
              bne prepareMixedJ
              lda dp:MX_TMP
              sta dp:CLIPB
              jmp abs:.word0 (weaponClipCut)
prepareMixedJ:jmp abs:.word0 (prepareMixed)
weaponClipPlain:
              ldx dp:COL
              sep #0x20
              lda long:MARKS,x
              sta long:OLD_MARKS,x
              rep #0x20
              jmp abs:.word0 (preparePlain)

;;; The camera moved and the only sprite is a ceiling light with at most one
;;; run below the wall and one above it: the column is its whole wall, those
;;; runs, and flat rows (the old wall's edges, last frame's light rows)
;;; around them. Everything is checked before the first push.
movedLight:   lda dp:MX_FLAGS
              bit ##32                  ; extra owners invalidate even a repeated light mask
              bne lightNo
              ldx dp:SCAN
              lda long:COLUMN_MASKS,x
              beq lightNo
              cmp abs:.word0 (lightLastMask) ; the light of the column to the right
              bne lightNewMask
              ldx abs:.word0 (lightLastRec)
              bra lightRecord
lightNewMask: sta dp:MX_MASK
              dec a
              and dp:MX_MASK
              bne lightNo
              lda dp:MX_MASK
              and abs:.word0 (decalMask)
              beq lightNo
              ldy ##0
              lda dp:MX_MASK
lightBit:     lsr a
              bcs lightBitFound
              iny
              iny
              bra lightBit
lightNo:      lda dp:MX_FLAGS
              ldx dp:COL
              jmp abs:.word0 (flaggedChecks)
lightBitFound:ldx abs:.word0 (maskOwners),y
              lda dp:MX_MASK
              sta abs:.word0 (lightLastMask)
              stx abs:.word0 (lightLastRec)
lightRecord:  txy
              lda long:SPR_RECORDS+14,x
              clc
              adc dp:COL
              tax
              lda long:HORIZONTAL,x       ; its source column here
              and ##255
              asl a
              adc abs:.word0 (ownerInfo+10),y
              tax
              lda long:SPRITE_CMDS,x
              sta dp:OW_PTR
              ; A transparent intervening owner may change the command bank
              ; without replacing the cached scale/light words.
              lda abs:.word0 (ownerInfo+12),y
              sta dp:OW_PTR+2
              cpy dp:FP_LASTREC
              beq lightWords
              sty dp:FP_LASTREC
              lda abs:.word0 (ownerInfo),y
              sta dp:OW_RCB
              lda abs:.word0 (ownerInfo+2),y
              sta dp:OW_BK
              lda abs:.word0 (ownerInfo+4),y
              sta dp:OW_LIGHT
              lda abs:.word0 (ownerInfo+6),y
              sta dp:OW_VB
              lda abs:.word0 (ownerInfo+8),y
              sta dp:MX_EP
lightWords:   ldx dp:SCAN
              ldy abs:.word0 (heightIndex),x
              cpy dp:MW_H
              beq lightBoundsReady
              sty dp:MW_H
              lda abs:.word0 (rowCodeBase),y
              sta dp:MW_RCB
              lda abs:.word0 (viewScaleTop),y
              sta dp:MW_T
              lda abs:.word0 (viewScaleBottom),y
              sta dp:MW_B
lightBoundsReady:
              lda ##255
              sta dp:DN_T
              sta dp:UP_T
              stz dp:DN_B
              stz dp:UP_B
lightRun:     lda [OW_PTR]
              bne lightRunRows
              jmp abs:.word0 (lightCommit)
lightRunRows: sep #0x20
              sta dp:MX_EP              ; replace the page's low byte before every read
              lda [MX_EP]
              sta dp:PC_T
              xba                       ; the command's bottom texel stayed in B
              sta dp:MX_EP
              lda [MX_EP]
lightBottomKept:
              sta dp:PC_B
              lda dp:PC_T
lightTopKept: cmp dp:PC_B
              rep #0x20
              bcs lightNext             ; none of it in view
              lda dp:PC_B
              cmp dp:MW_T
              beq lightUp
              bcc lightUp
              lda dp:PC_T
              cmp dp:MW_B
              bcc lightReject            ; across the wall
              lda dp:DN_B
              bne lightReject            ; a second run below
              lda dp:PC_T
              sta dp:DN_T
              lda dp:PC_B
              sta dp:DN_B
              ldy dp:OW_LIGHT
              lda [OW_PTR],y
              sta dp:DN_SRC
              lda dp:OW_BK
              sta dp:DN_BK
              bra lightNext
lightUp:      lda dp:UP_B
              bne lightReject            ; a second run above
              lda dp:PC_T
              sta dp:UP_T
              lda dp:PC_B
              sta dp:UP_B
              ldy dp:OW_LIGHT
              lda [OW_PTR],y
              sta dp:UP_SRC
              lda dp:OW_BK
              sta dp:UP_BK
lightNext:    lda dp:OW_PTR
              clc
              adc ##SPR_RUN_BYTES
              sta dp:OW_PTR
              jmp abs:.word0 (lightRun)
lightReject:  lda dp:MX_FLAGS
              ldx dp:COL
              jmp abs:.word0 (flaggedChecks)
lightCommit:  ldx dp:SCAN               ; the whole wall
              lda abs:.word0 (oldHeight),x
              sta dp:PA_OLD
              ldy dp:MW_H
              tya
              sta abs:.word0 (oldHeight),x
              lda abs:.word0 (viewScaleAddr),y
              pha
              pei dp:PA_SX
              PUSH_WALL_SOURCE
              pha
              pea #WALLOP-1
lightDownPiece: lda dp:DN_B
              beq lightNoDown
              cmp dp:OW_VB
              beq lightDownPieceUncut
              PUSH_CACHED_CUT DN_T, OW_RCB, DN_SRC, DN_BK
              bra lightNoDown
lightDownPieceUncut:
              PUSH_CACHED_UNCUT DN_T, OW_RCB, DN_SRC, DN_BK
lightNoDown:
lightUpPiece: lda dp:UP_B
              beq lightNoUp
              cmp dp:OW_VB
              beq lightUpPieceUncut
              PUSH_CACHED_CUT UP_T, OW_RCB, UP_SRC, UP_BK
              bra lightNoUp
lightUpPieceUncut:
              PUSH_CACHED_UNCUT UP_T, OW_RCB, UP_SRC, UP_BK
lightNoUp:    ldx dp:SCAN               ; floor rows: last frame's light rows and
              lda abs:.word0 (ghost2B),x ; the old wall's lower edge, minus the run
              beq lightFloorEdge        ; below the wall
              sta dp:WK_B
              lda abs:.word0 (ghost2T),x
              cmp dp:MW_B
              bcs lightLowKept
              lda dp:MW_B
lightLowKept: sta dp:WK_T
              lda dp:DN_T
              sta dp:RG_T
              lda dp:DN_B
              sta dp:RG_B
flat_floor_wolf_2_8:
              lda ##(FLATBANK+FLOOR*256)
              sta dp:FW_COLOR
              lda ##.word0 (lightFloorEdge)
              sta dp:WK_RET
              jmp abs:.word0 (flatsAround)
lightFloorEdge:
              ldx dp:PA_OLD
              lda abs:.word0 (viewScaleBottom),x
              cmp dp:MW_B
              beq lightCeiling
              bcc lightCeiling
              sta dp:WK_B
              lda dp:MW_B
              sta dp:WK_T
              lda dp:DN_T
              sta dp:RG_T
              lda dp:DN_B
              sta dp:RG_B
flat_floor_wolf_2_9:
              lda ##(FLATBANK+FLOOR*256)
              sta dp:FW_COLOR
              lda ##.word0 (lightCeiling)
              sta dp:WK_RET
              jmp abs:.word0 (flatsAround)
lightCeiling: ldx dp:SCAN               ; ceiling rows likewise, minus the run above
              lda abs:.word0 (ghost1B),x
              beq lightCeilingEdge
              cmp dp:MW_T
              bcc lightUpKept
              lda dp:MW_T
lightUpKept:  sta dp:WK_B
              lda abs:.word0 (ghost1T),x
              sta dp:WK_T
              lda dp:UP_T
              sta dp:RG_T
              lda dp:UP_B
              sta dp:RG_B
flat_ceiling_wolf_2_10:
              lda ##(FLATBANK+CEILING*256)
              sta dp:FW_COLOR
              lda ##.word0 (lightCeilingEdge)
              sta dp:WK_RET
              jmp abs:.word0 (flatsAround)
lightCeilingEdge:
              ldx dp:PA_OLD
              lda abs:.word0 (viewScaleTop),x
              cmp dp:MW_T
              bcs lightGhosts
              sta dp:WK_T
              lda dp:MW_T
              sta dp:WK_B
              lda dp:UP_T
              sta dp:RG_T
              lda dp:UP_B
              sta dp:RG_B
flat_ceiling_wolf_2_11:
              lda ##(FLATBANK+CEILING*256)
              sta dp:FW_COLOR
              lda ##.word0 (lightGhosts)
              sta dp:WK_RET
              jmp abs:.word0 (flatsAround)
lightGhosts:  ldx dp:SCAN
              lda dp:UP_T
              sta abs:.word0 (ghost1T),x
              lda dp:UP_B
              sta abs:.word0 (ghost1B),x
              lda dp:DN_T
              sta abs:.word0 (ghost2T),x
              lda dp:DN_B
              sta abs:.word0 (ghost2B),x
              jmp abs:.word0 (mixedDoneX)
;;; Flat rows [WK_T, WK_B) of FW_COLOR, minus the run [RG_T, RG_B).
flatsAround:  lda dp:WK_T
              cmp dp:WK_B
              bcs aroundDone            ; no rows
              lda dp:RG_T
              cmp dp:RG_B
              bcs aroundAll             ; no run
              cmp dp:WK_B
              bcs aroundAll             ; the run lies below the rows
              lda dp:RG_B
              cmp dp:WK_T
              beq aroundAll             ; or above them
              bcc aroundAll
              lda dp:RG_T               ; rows above the run
              cmp dp:WK_T
              beq aroundBelow
              bcc aroundBelow
              sta dp:PC_B
              lda dp:WK_T
              sta dp:PC_T
              lda dp:PC_B
              sec
              sbc dp:PC_T
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tax
              lda abs:.word0 (rowX160),x
              clc
              adc dp:PA_SX
              pha
              pei dp:FW_COLOR
              pea #.word0 (flatOp-1)
aroundBelow:  lda dp:RG_B               ; rows below it
              cmp dp:WK_B
              bcs aroundDone
              sta dp:PC_T
              lda dp:WK_B
              sta dp:PC_B
              lda dp:PC_B
              sec
              sbc dp:PC_T
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tax
              lda abs:.word0 (rowX160),x
              clc
              adc dp:PA_SX
              pha
              pei dp:FW_COLOR
              pea #.word0 (flatOp-1)
aroundDone:   .byte 0x6c                ; JMP (WK_RET)
              .word 0x1000+WK_RET
aroundAll:    lda dp:WK_T
              sta dp:PC_T
              lda dp:WK_B
              sta dp:PC_B
              lda dp:PC_B
              sec
              sbc dp:PC_T
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tax
              lda abs:.word0 (rowX160),x
              clc
              adc dp:PA_SX
              pha
              pei dp:FW_COLOR
              pea #.word0 (flatOp-1)
              bra aroundDone

;;; A still weapon alone, one run from CLIPB down: a plain column whose wall
;;; and floor edge stop at the weapon's top.
weaponClipCut:ldx dp:COL
              sep #0x20
              lda long:MARKS,x
              sta long:OLD_MARKS,x
              rep #0x20
              ldx dp:SCAN
clipMaskClear:
              lda ##0
              sta long:COLUMN_MASKS,x
clipMaskReady:
              lda abs:.word0 (heightIndex),x
              cmp abs:.word0 (oldHeight),x
              bne clipChanged
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne clipChanged
              jmp abs:.word0 (prepareDone)
clipChanged:  ldy abs:.word0 (heightIndex),x
              lda abs:.word0 (oldHeight),x
              sta dp:PA_OLD
              tya
              sta abs:.word0 (oldHeight),x
              cpy dp:MW_H
              beq clipBoundsReady
              sty dp:MW_H
              lda abs:.word0 (rowCodeBase),y
              sta dp:MW_RCB
              lda abs:.word0 (viewScaleTop),y
              sta dp:MW_T
              lda abs:.word0 (viewScaleBottom),y
              sta dp:MW_B
clipBoundsReady:
              lda abs:.word0 (sourceAddr),x
              sta abs:.word0 (oldSource),x
              RESOLVE_WALL_SOURCE
              lda dp:MW_B
              cmp dp:CLIPB
              beq clipWhole
              bcc clipWhole
              lda dp:CLIPB
              sta dp:PC_B
              lda dp:MW_T
              sta dp:BG_WT
clipWallPiece:
              lda dp:PC_B
              cmp dp:MW_B
              beq clipWallPieceUncut
              PUSH_CACHED_CUT BG_WT, MW_RCB, MW_SRC, MW_BK
              bra clipWallDone
clipWallPieceUncut:
              PUSH_CACHED_UNCUT BG_WT, MW_RCB, MW_SRC, MW_BK
              bra clipWallDone
clipWhole:    lda abs:.word0 (viewScaleAddr),y
              pha
              pei dp:PA_SX
              pei dp:MW_SRC
              pei dp:MW_BK
              pea #WALLOP-1
clipWallDone: ldx dp:MW_H
              cpx dp:PA_OLD
              bcs clipDone              ; as tall as before: no flat row is uncovered
              ldx dp:PA_OLD             ; floor rows the old wall left above
              lda abs:.word0 (viewScaleBottom),x ; the weapon
              cmp dp:CLIPB
              bcc clipFloorEnd
              lda dp:CLIPB
clipFloorEnd: sta dp:PC_B
              sec
              sbc dp:MW_B
              beq clipNoFloor
              bmi clipNoFloor
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tay
              lda abs:.word0 (rowX160),y
              clc
              adc dp:PA_SX
              pha
flat_floor_wolf_2_12:
              pea #(FLATBANK+FLOOR*256)
              pea #.word0 (flatOp-1)
clipNoFloor:  ldy dp:MW_H
              lda abs:.word0 (viewScaleTop),y
              sec
              sbc abs:.word0 (viewScaleTop),x
              beq clipDone
              bmi clipDone
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda abs:.word0 (topRowX),y
              clc
              adc dp:PA_SX
              pha
flat_ceiling_wolf_2_13:
              pea #(FLATBANK+CEILING*256)
              pea #.word0 (flatOp-1)
clipDone:     jmp abs:.word0 (prepareDone)

;;; A mixed column repaints the old and new wall extent and the rows its
;;; sprites showed last frame, kept as one hull above row 80 and one below,
;;; where no owner covers them now; every owner run in view is painted.
;;; An unchanged weapon keeps its pixels: one run down to the view's bottom
;;; only raises the column's bottom, more runs cover rows unpainted.
prepareMixed: ldx dp:SCAN
              ldy abs:.word0 (heightIndex),x
              cpy dp:MW_H
              beq mixedBoundsReady
              sty dp:MW_H
              lda abs:.word0 (rowCodeBase),y
              sta dp:MW_RCB
              lda abs:.word0 (viewScaleTop),y
              sta dp:MW_T
              lda abs:.word0 (viewScaleBottom),y
              sta dp:MW_B
mixedBoundsReady:
              stx dp:WALL_COL
              RESOLVE_WALL_SOURCE
              ldx dp:WALL_COL
              lda ##255
              sta dp:DW_T               ; no wall rows to repaint yet
              stz dp:DW_B
              tya
              cmp abs:.word0 (oldHeight),x
              bne mixedWall
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne mixedWall
              bra mixedWeapon
mixedWall:    ldy abs:.word0 (oldHeight),x
              lda dp:MW_H
              sta abs:.word0 (oldHeight),x
              lda abs:.word0 (sourceAddr),x
              sta abs:.word0 (oldSource),x
              cpy dp:MW_H               ; the rows to repaint are the taller wall's
              bcs mixedOldTaller
              lda dp:MW_T
              sta dp:DW_T
              lda dp:MW_B
              sta dp:DW_B
              bra mixedWallRows
mixedOldTaller:
              lda abs:.word0 (viewScaleTop),y
              sta dp:DW_T
              lda abs:.word0 (viewScaleBottom),y
              sta dp:DW_B
mixedWallRows:lda dp:MX_FLAGS           ; a changed wall is never empty
              bit ##4
              bne mixedWeaponHere
              bra mixedNoWeapon
mixedWeapon:  lda dp:MX_FLAGS
              bit ##4
              bne mixedWeaponHere
;;; No weapon here now or last frame: nothing of it to keep or repaint.
              lda dp:DW_T
              cmp dp:DW_B
              bcc mixedNoWeapon
              ldx dp:COL
              lda long:MARKS,x       ; no sprite rectangle moved here either
              and ##255
              bit ##16
              bne mixedNoWeapon
              jmp abs:.word0 (mixedDone)
mixedNoWeapon:ldx dp:SCAN
              lda abs:.word0 (ghost1T),x
              sta dp:G1_T
              lda abs:.word0 (ghost1B),x
              sta dp:G1_B
              lda abs:.word0 (ghost2T),x
              sta dp:G2_T
              lda abs:.word0 (ghost2B),x
              sta dp:G2_B
              lda ##255
              sta dp:NG1_T
              sta dp:NG2_T
              stz dp:NG1_B
              stz dp:NG2_B
              lda abs:.word0 (viewBottom)
              sta dp:CLIPB
              stz dp:CV_N
              stz dp:CV_UP
              lda dp:MX_FLAGS
              bit ##32
              bne mixedNoWeaponGeneral
              lda long:COLUMN_MASKS,x
              sta dp:MX_MASK
              ora abs:.word0 (decalMask)
              cmp abs:.word0 (decalMask)
              bne mixedNoWeaponMasks
              lda dp:MW_B               ; nothing hides the wall's bottom
              sta dp:FP_WALLB
              lda dp:MW_T
              sta dp:FP_WT
              jmp abs:.word0 (fastUpHull)
mixedNoWeaponMasks:                     ; a sprite that is no ceiling light is here
              lda dp:MX_MASK
              jmp abs:.word0 (maskOwnersHere)
mixedNoWeaponGeneral:
              jmp abs:.word0 (spriteOwners)
mixedWeaponHere:
              lda dp:SCAN
              clc
              adc abs:.word0 (weaponMaskTable)
              tax
              lda long:WEAPON_RUNS,x
              sta dp:MX_WNEW
              ldy ##1                   ; same runs: the weapon pixels stay
              lda abs:.word0 (weaponMaskTable)
              cmp abs:.word0 (oldWeaponMaskTable)
              beq mixedWeaponSet        ; the same frame and view: same runs
              lda dp:SCAN
              clc
              adc abs:.word0 (oldWeaponMaskTable)
              tax
              lda long:WEAPON_RUNS,x
              cmp dp:MX_WNEW
              beq mixedWeaponSet
              sta dp:MX_WOLD
              ldy ##0
mixedWeaponSet:
              sty dp:MX_WSKIP
              tya
              beq mixedChanged
              lda dp:DW_T
              cmp dp:DW_B
              bcc mixedChanged
              ldx dp:COL
              lda long:MARKS,x       ; no sprite rectangle moved here either
              and ##255
              bit ##16
              bne mixedChanged
              jmp abs:.word0 (mixedDone)
mixedChanged: ldx dp:SCAN
              lda abs:.word0 (ghost1T),x
              sta dp:G1_T
              lda abs:.word0 (ghost1B),x
              sta dp:G1_B
              lda abs:.word0 (ghost2T),x
              sta dp:G2_T
              lda abs:.word0 (ghost2B),x
              sta dp:G2_B
              lda ##255
              sta dp:NG1_T
              sta dp:NG2_T
              stz dp:NG1_B
              stz dp:NG2_B
              lda abs:.word0 (viewBottom)
              sta dp:CLIPB
              lda dp:MX_WSKIP
              bne mixedOwners
              ldx dp:MX_WOLD            ; the old weapon's rows show what is
              lda long:WEAPON_RUNS,x       ; behind it now
              bit ##255
              beq mixedOwners
              xba
              and ##255
              cmp dp:G2_T
              bcs mixedOldWeaponTop
              sta dp:G2_T
mixedOldWeaponTop:
              lda long:WEAPON_RUNS+0x3,x
              and ##255
              cmp dp:G2_B
              bcc mixedOwners
              sta dp:G2_B

;;; Owners nearest first: the weapon, then the world sprites in front of the
;;; wall. Rows of a run that no nearer run covers become a piece; coverList
;;; keeps every covered run, bottoms descending. Rows nobody covers show
;;; the background.
mixedOwners:  stz dp:CV_N
              ldx dp:MX_WNEW
              lda long:WEAPON_RUNS,x       ; run count, then the top opaque row
              bit ##255
              bne weaponRuns
              jmp abs:.word0 (noWeaponOwner)
;;; A bottom-reaching weapon run is the view edge, even while firing.
;;; Clip every later owner above it. The whole-pose drawer owns weapon stores.
weaponRuns:   lda long:WEAPON_RUNS+0x3,x
              and ##255
              cmp dp:CLIPB
              beq weaponBase
weaponNoBase: ldy dp:MX_WSKIP
              beq weaponOwner
              bra weaponStill
weaponBase:   lda long:WEAPON_RUNS+0x2,x
              and ##255
              cmp ##80                  ; upper restoration hulls stay independent
              bcc weaponNoBase
              sta dp:CLIPB
weaponBaseDone:
              lda long:WEAPON_RUNS+0x4,x
              beq weaponBaseOnly
              txa
              clc
              adc ##4
              sta dp:OW_PTR
              bra weaponOwnerReady
weaponBaseOnly:
              jmp abs:.word0 (noWeaponOwner)
;;; An unchanged weapon alone, all below the wall: its runs only cover floor
;;; rows, so the fast path takes them as runs below the wall, unpainted.
weaponStill:  lda dp:MX_FLAGS
              bit ##32
              bne weaponOwner
              ldy dp:SCAN
              tyx
              lda long:COLUMN_MASKS,x
              bne weaponOwnerAgain
              ldx dp:MX_WNEW
              lda long:WEAPON_RUNS+0x1,x
              and ##255
              cmp dp:MW_B
              bcc weaponOwner
              inx
              inx
              ldy ##0
weaponCover:  lda long:WEAPON_RUNS,x
              beq weaponCovered
              sta abs:.word0 (coverList),y
              iny
              iny
              txa
              clc
              adc ##2
              tax
              bra weaponCover
weaponCovered:sty dp:CV_N
              sty dp:CV_UP
              stz dp:MX_MASK
              jmp abs:.word0 (fastRegions)
weaponOwnerAgain:
              ldx dp:MX_WNEW
weaponOwner:  inx
              inx
              stx dp:OW_PTR
weaponOwnerReady:
              lda ##0x08
              sta dp:OW_PTR+2
              stz dp:OW_CV0             ; the weapon is the first owner
              stz dp:CV_I
;;; Coverage runs are just bottom/top words, followed by zero. A changed
;;; pose draws after the world; these intervals keep its background hidden.
weaponLoop:   lda [OW_PTR]
              beq weaponOwnersDone
              ldx dp:CV_N
              sta abs:.word0 (coverList),x
              inx
              inx
              stx dp:CV_N
weaponNext:   lda dp:OW_PTR
              clc
              adc ##2
              sta dp:OW_PTR
              bra weaponLoop
weaponOwnersDone:
              lda ##WORLD_RUN_BANK
              sta dp:OW_PTR+2
spriteOwners: lda dp:MX_FLAGS
              bit ##32
              beq maskOwners0
              jmp abs:.word0 (scanOwners)
maskOwners0:
              ldx dp:SCAN
              lda long:COLUMN_MASKS,x
              bne maskOwnersHere
              jmp abs:.word0 (ownersDone)
maskOwnersHere:
              sta dp:MX_MASK
              ldx ##.word0 (maskOwnerNext)
              stx dp:OW_NEXT
              bra maskOwner
maskOwnerNext:lda dp:MX_MASK
              bne maskOwner
              jmp abs:.word0 (ownersDone)
;;; Keep the remaining bits in their original positions. The byte lookup
;;; selects the next owner directly, including sparse masks in crowded views.
;;; MX_MASK=0 still identifies the last owner for the single-owner shortcut.
maskOwner:    bit ##1
              bne maskOwnerFirst
maskOwnerLookup:
              tay
              dec a
              and dp:MX_MASK
              sta dp:MX_MASK
              tya
              and ##255
              beq maskOwnerHigh
              tax
              lda abs:.word0 (ownerFirstBit),x
              and ##255
              tay
maskOwnerRecord:
              ldx abs:.word0 (maskOwners),y
              jmp abs:.word0 (spriteOwner)
maskOwnerHigh:tya
              xba
              tax
              lda abs:.word0 (ownerFirstBit),x
              and ##255
              ora ##16
              tay
              bra maskOwnerRecord
maskOwnerFirst:
              dec a
              sta dp:MX_MASK
              ldx abs:.word0 (maskOwners)
              jmp abs:.word0 (spriteOwner)

;;; Fast path: no weapon owner and at most one world sprite, a ceiling
;;; light, whose runs in view, like last frame's sprite rows, each lie above
;;; the wall's top or below its bottom. The wall then shows whole and each
;;; flat region repaints its dirty rows minus this frame's runs there. A run
;;; across the wall sends it and the rest of the column the general way.
noWeaponOwner:
              stz dp:CV_UP
              lda dp:MX_FLAGS
              bit ##32
              beq fastMask
fastGeneral:  jmp abs:.word0 (spriteOwners)
fastMask:     ldx dp:SCAN
              lda long:COLUMN_MASKS,x
              sta dp:MX_MASK
              ora abs:.word0 (decalMask)   ; every sprite here a ceiling light
              cmp abs:.word0 (decalMask)
              bne fastGeneral
fastRegions:  lda dp:MW_B                ; the wall shows down to the weapon
              cmp dp:CLIPB
              bcc fastWallBottom
              lda dp:CLIPB
fastWallBottom:
              sta dp:FP_WALLB
              lda dp:MW_T
              sta dp:FP_WT
              lda dp:G2_B
              cmp dp:CLIPB
              bcc fastUpHull
              lda dp:CLIPB
              sta dp:G2_B
fastUpHull:   lda dp:G1_B               ; last frame's sprite rows in the wall's
              cmp dp:MW_T               ; rows: the repainted wall covers them,
              beq fastLowHull           ; an unchanged one cannot
              bcc fastLowHull
              ldx dp:DW_T
              cpx dp:DW_B
              bcs fastGeneral
              lda dp:MW_T
              sta dp:G1_B
fastLowHull:  lda dp:G2_T
              cmp dp:MW_B
              bcs fastOwners
              ldx dp:DW_T
              cpx dp:DW_B
              bcs fastGeneral
              lda dp:MW_B
              sta dp:G2_T
;;; The sprites nearest first. Runs below the wall keep coverList bytes
;;; [0, CV_UP), runs above it [CV_UP, CV_N), each part bottoms descending; a
;;; run across the wall or over a nearer run goes, with all that follows,
;;; the general way, which then subtracts what is already covered.
fastOwners:   stz dp:FP_ANY
fastOwnerLoop:lda dp:MX_MASK
              bne fastOwnerBit
              jmp abs:.word0 (fastRunsDone)
fastOwnerBit: bit ##1
              bne fastOwnerFirst
fastOwnerLookup:
              tay
              dec a
              and dp:MX_MASK
              sta dp:MX_MASK
              tya
              and ##255
              beq fastOwnerHigh
              tax
              lda abs:.word0 (ownerFirstBit),x
              and ##255
              tay
              bra fastOwnerRecord
fastOwnerHigh:tya
              xba
              tax
              lda abs:.word0 (ownerFirstBit),x
              and ##255
              ora ##16
              tay
fastOwnerRecord:
              ldx abs:.word0 (maskOwners),y
              bra fastInfo
fastOwnerFirst:
              dec a
              sta dp:MX_MASK
              ldx abs:.word0 (maskOwners)
fastInfo:     txy                       ; Y: the record
              lda long:SPR_RECORDS+14,x
              clc
              adc dp:COL
              tax
              lda long:HORIZONTAL,x       ; its source column here
              and ##255
              asl a
              adc abs:.word0 (ownerInfo+10),y
              tax
              lda long:SPRITE_CMDS,x
              sta dp:OW_PTR
              lda abs:.word0 (ownerInfo+12),y
              sta dp:OW_PTR+2
              cpy dp:FP_LASTREC         ; the last sprite's words still here
              beq fastRun
              sty dp:FP_LASTREC
              lda abs:.word0 (ownerInfo),y
              sta dp:OW_RCB
              lda abs:.word0 (ownerInfo+2),y
              sta dp:OW_BK
              lda abs:.word0 (ownerInfo+4),y
              sta dp:OW_LIGHT
              lda abs:.word0 (ownerInfo+6),y
              sta dp:OW_VB
              lda abs:.word0 (ownerInfo+8),y
              sta dp:MX_EP
fastRun:      lda [OW_PTR]
              bne fastRunRows
              lda dp:MX_MASK            ; this sprite is done
              bne fastOwnerAfter
              jmp abs:.word0 (fastRunsDone)
fastOwnerAfter:
              inc dp:FP_ANY
              jmp abs:.word0 (fastOwnerBit)
fastRunRows:  sep #0x20
              sta dp:MX_EP              ; replace the page's low byte before every read
              lda [MX_EP]
              sta dp:PC_T
              xba                       ; the command's bottom texel stayed in B
              sta dp:MX_EP
              lda [MX_EP]
              cmp dp:CLIPB
              bcc fastBottomKept
              lda dp:CLIPB
fastBottomKept:
              sta dp:PC_B               ; the row words keep their high bytes zero
              lda dp:PC_T
fastTopKept:  cmp dp:PC_B
              rep #0x20
              bcc fastInView
              jmp abs:.word0 (fastNext)
fastInView:   lda dp:PC_B
              cmp dp:MW_T
              beq fastUp
              bcc fastUp
              lda dp:PC_T
              cmp dp:MW_B
              bcs fastDown
              cmp dp:MW_T               ; reaching into the wall from above: the
              beq fastUpInto            ; wall starts below it
              bcc fastUpInto
              lda dp:PC_B               ; from below: the wall ends above it
              cmp dp:MW_B
              bcc fastSwitch
              lda dp:PC_T
              cmp dp:FP_WALLB
              bcs fastDown
              sta dp:FP_WALLB
              bra fastDown
fastUpInto:   lda dp:PC_B
              cmp dp:FP_WT
              bcc fastUp
              sta dp:FP_WT
              bra fastUp
fastSwitch:   ; convert earlier fast runs to the general path's single hull
              lda dp:NG2_T
              cmp dp:NG1_T
              bcs switchHullBottom
              sta dp:NG1_T
switchHullBottom:
              lda dp:NG1_B
              cmp dp:NG2_B
              bcc switchHullReady
              sta dp:NG2_B
switchHullReady:
              lda ##.word0 (maskOwnerNext)
              sta dp:OW_NEXT
              jmp abs:.word0 (ownerRuns)
fastDown:     lda dp:FP_ANY             ; the nearest sprite's runs come bottom
              bne fastDownPlace         ; first: the next one goes last
              ldx dp:CV_N
              lda dp:PC_B
              xba
              ora dp:PC_T
              sta abs:.word0 (coverList),x
              inx
              inx
              stx dp:CV_N
              stx dp:CV_UP
              bra fastDownGhost
fastDownPlace:ldx dp:CV_UP              ; its place below the wall
              stz dp:FP_LO
              jsr abs:.word0 (fastPlace)
              bcs fastSwitch
              inc dp:CV_UP
              inc dp:CV_UP
fastDownGhost:lda dp:PC_T
              cmp dp:NG2_T
              bcs fastDownTop
              sta dp:NG2_T
fastDownTop:  lda dp:PC_B
              cmp dp:NG2_B
              bcc fastPiece
              sta dp:NG2_B
              bra fastPiece
fastUp:       lda dp:FP_ANY
              bne fastUpPlace
              ldx dp:CV_N
              lda dp:PC_B
              xba
              ora dp:PC_T
              sta abs:.word0 (coverList),x
              inx
              inx
              stx dp:CV_N
              bra fastUpGhost
fastUpPlace:  ldx dp:CV_N               ; its place above the wall
              lda dp:CV_UP
              sta dp:FP_LO
              jsr abs:.word0 (fastPlace)
              bcs fastSwitch
fastUpGhost:  lda dp:PC_T
              cmp dp:NG1_T
              bcs fastUpTop
              sta dp:NG1_T
fastUpTop:    lda dp:PC_B
              cmp dp:NG1_B
              bcc fastPiece
              sta dp:NG1_B
fastPiece:    lda dp:PC_B
              cmp dp:OW_VB
              bne fastCut
              lda dp:PC_T
              asl a
              tay
              lda [OW_RCB],y
              dec a
              pha
              pei dp:PA_SX
              ldy dp:OW_LIGHT
              lda [OW_PTR],y
              pha
              pei dp:OW_BK
              pea #WALLOP-1
              bra fastNext
fastCut:      PUSH_RAW_CUT
fastNext:     lda dp:OW_PTR
              clc
              adc ##SPR_RUN_BYTES
              sta dp:OW_PTR
              jmp abs:.word0 (fastRun)
;;; Place [PC_T, PC_B) among coverList bytes [FP_LO, X), bottoms descending,
;;; and shift the rest up one entry. Carry set: it overlaps a run already
;;; there (nothing changed). It pushes no record, so a JSR to it is safe.
fastPlace:    cpx dp:FP_LO
              beq fastPlaceAt
              lda abs:.word0 (coverList-1),x ; the entry before X: its bottom
              and ##255
              cmp dp:PC_B
              bcs fastPlaceLow
              cmp dp:PC_T               ; a higher entry reaching into it
              beq fastPlaceUp
              bcs fastPlaceHit
fastPlaceUp:  dex
              dex
              bra fastPlace
fastPlaceLow: lda abs:.word0 (coverList-2),x ; a lower entry reaching into it
              and ##255
              cmp dp:PC_B
              bcc fastPlaceHit
fastPlaceAt:  stx dp:CV_I
              ldx dp:CV_N
fastShift:    cpx dp:CV_I
              beq fastPut
              lda abs:.word0 (coverList-2),x
              sta abs:.word0 (coverList),x
              dex
              dex
              bra fastShift
fastPut:      lda dp:PC_B
              xba
              ora dp:PC_T
              sta abs:.word0 (coverList),x
              inc dp:CV_N
              inc dp:CV_N
              clc
              rts
fastPlaceHit: sec
              rts
fastRunsDone: lda dp:DW_T               ; the wall, whole or between the runs
              cmp dp:DW_B               ; reaching into it and the weapon
              bcs fastFloor
              lda dp:FP_WT
              cmp dp:MW_T
              bne fastWallPart
              lda dp:FP_WALLB
              cmp dp:MW_B
              bne fastWallCut
              ldy dp:MW_H
              lda abs:.word0 (viewScaleAddr),y
              pha
              pei dp:PA_SX
              pei dp:MW_SRC
              pei dp:MW_BK
              pea #WALLOP-1
              bra fastFloor
fastWallPart: lda dp:FP_WALLB
fastWallCut:  sta dp:PC_B
              lda dp:FP_WT
              cmp dp:PC_B
              bcs fastFloor             ; runs cover all of it
              sta dp:BG_WT
fastWallPiece:
              lda dp:PC_B
              cmp dp:MW_B
              beq fastWallPieceUncut
              PUSH_CACHED_CUT BG_WT, MW_RCB, MW_SRC, MW_BK
              bra fastFloor
fastWallPieceUncut:
              PUSH_CACHED_UNCUT BG_WT, MW_RCB, MW_SRC, MW_BK
fastFloor:    lda dp:DW_T               ; floor rows: the wall's lower edge,
              cmp dp:DW_B               ; then last frame's lower sprite rows
              bcs fastFloorHull
              lda dp:DW_B
              cmp dp:CLIPB
              bcc fastFloorEdgeIn
              lda dp:CLIPB
fastFloorEdgeIn:
              cmp dp:MW_B
              beq fastFloorHull
              bcc fastFloorHull
              sta dp:WK_B
              lda dp:MW_B
              sta dp:WK_T
              lda dp:G2_T               ; a hull touching the edge joins it
              cmp dp:G2_B
              bcs fastFloorEdge
              cmp dp:WK_B
              beq fastFloorJoin
              bcs fastFloorEdge
fastFloorJoin:lda dp:G2_B
              cmp dp:WK_B
              bcc fastFloorJoined
              sta dp:WK_B
fastFloorJoined:
              lda ##255
              sta dp:G2_T
fastFloorEdge:lda ##.word0 (fastFloorHull)
              bra fastFloorWalk
fastFloorHull:lda dp:G2_T
              cmp dp:G2_B
              bcs fastCeiling
              sta dp:WK_T
              lda dp:G2_B
              sta dp:WK_B
              lda ##.word0 (fastCeiling)
fastFloorWalk:sta dp:WK_RET
              stz dp:CV_I
              lda dp:CV_UP
              sta dp:MX_TMP
flat_floor_wolf_2_14:
              lda ##(FLATBANK+FLOOR*256)
              sta dp:FW_COLOR
              jmp abs:.word0 (flatWalk)
fastCeiling:  lda dp:DW_T               ; ceiling rows: the wall's upper edge,
              cmp dp:MW_T               ; then last frame's upper sprite rows
              bcs fastCeilingHull
              sta dp:WK_T
              lda dp:MW_T
              sta dp:WK_B
              lda dp:G1_T
              cmp dp:G1_B
              bcs fastCeilingEdge
              lda dp:G1_B
              cmp dp:WK_T
              bcc fastCeilingEdge
              lda dp:G1_T
              cmp dp:WK_T
              bcs fastCeilingJoined
              sta dp:WK_T
fastCeilingJoined:
              lda ##255
              sta dp:G1_T
fastCeilingEdge:
              lda ##.word0 (fastCeilingHull)
              bra fastCeilingWalk
fastCeilingHull:
              lda dp:G1_T
              cmp dp:G1_B
              bcs fastDone
              sta dp:WK_T
              lda dp:G1_B
              sta dp:WK_B
              lda ##.word0 (fastDone)
fastCeilingWalk:
              sta dp:WK_RET
              lda dp:CV_UP
              sta dp:CV_I
              lda dp:CV_N
              sta dp:MX_TMP
flat_ceiling_wolf_2_15:
              lda ##(FLATBANK+CEILING*256)
              sta dp:FW_COLOR
              jmp abs:.word0 (flatWalk)
fastDone:     jmp abs:.word0 (ghostsKept)

;;; Flat rows [WK_T, WK_B) of FW_COLOR minus coverList bytes [CV_I, MX_TMP),
;;; bottom up.
flatWalk:     lda dp:WK_B
              sta dp:CUR
;;; The run initialized the row words; only their low bytes change here.
fwLoop:       sep #0x20
              ldx dp:CV_I
fwScan:       cpx dp:MX_TMP
              bcs fwRest8
              inx
              inx
              stx dp:CV_I
              lda abs:.word0 (coverList-2),x
              cmp dp:CUR
              bcs fwScan                ; at or below CUR
              lda abs:.word0 (coverList-1),x
              cmp dp:WK_T
              beq fwRest8               ; at or above the rows: so are the rest
              bcc fwRest8
              cmp dp:CUR
              bcs fwJump
              sta dp:PC_T
              lda dp:CUR
              sta dp:PC_B
              lda abs:.word0 (coverList-2),x
              sta dp:CUR
              rep #0x20
              lda dp:PC_B
              sec
              sbc dp:PC_T
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tax
              lda abs:.word0 (rowX160),x
              clc
              adc dp:PA_SX
              pha
              pei dp:FW_COLOR
              pea #.word0 (flatOp-1)
              bra fwCheck
fwJump:       lda abs:.word0 (coverList-2),x
              sta dp:CUR
              rep #0x20
fwCheck:      lda dp:CUR
              cmp dp:WK_T
              beq fwDone
              bcc fwDone
              bra fwLoop
fwRest8:      rep #0x20
fwRest:       lda dp:CUR
              cmp dp:WK_T
              beq fwDone
              bcc fwDone
              sta dp:PC_B
              lda dp:WK_T
              sta dp:PC_T
              lda dp:PC_B
              sec
              sbc dp:PC_T
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tax
              lda abs:.word0 (rowX160),x
              clc
              adc dp:PA_SX
              pha
              pei dp:FW_COLOR
              pea #.word0 (flatOp-1)
fwDone:       .byte 0x6c                ; JMP (WK_RET)
              .word 0x1000+WK_RET

;;; Crowded columns walk up to three more prepared masks in near-first order.
;;; The original list remains available above 64 world owners.
              .section gamecode, text, root, noreorder
scanOwners:   lda abs:.word0 (maskFallback)
              beq scanLowOnly
              cmp ##4
              bcc scanExtraMasks
              jmp abs:.word0 (scanFullList)
scanExtraMasks:
              stz dp:MX_BIT
              lda ##0xffe0
              sta dp:EXTRA_OWNER_BASE
              lda ##.word0 (extraOwnerNext)
              sta dp:OW_NEXT
              ldx dp:SCAN
              lda long:COLUMN_MASKS,x
              sta dp:MX_MASK
              beq extraOwnerHigh
              jmp abs:.word0 (maskOwner)
scanLowOnly:  jmp abs:.word0 (maskOwners0)
extraOwnerNext:
              lda dp:MX_MASK
              beq extraOwnerHigh
              jmp abs:.word0 (maskOwner)
extraOwnerHigh:
              lda dp:MX_BIT
              cmp abs:.word0 (maskColumnBytes)
              bcc extraGroupMore
              jmp abs:.word0 (ownersDone)
extraGroupMore:
              clc
              adc dp:SCAN
              tax
              lda long:EXTRA_MASKS,x
              sta dp:MX_MASK
              lda dp:EXTRA_OWNER_BASE
              clc
              adc ##32
              sta dp:EXTRA_OWNER_BASE
              lda dp:MX_BIT
              clc
              adc ##320
              sta dp:MX_BIT
              lda dp:MX_MASK
              beq extraOwnerHigh
              lda ##.word0 (extraHighNext)
              sta dp:OW_NEXT
extraHighNext:
              lda dp:MX_MASK
              beq extraOwnerHigh
extraHighOwner:
              tay
              dec a
              and dp:MX_MASK
              sta dp:MX_MASK
              tya
              and ##255
              beq extraHighByte
              tax
              lda abs:.word0 (ownerFirstBit),x
              and ##255
              tay
extraHighRecord:
              tya
              clc
              adc dp:EXTRA_OWNER_BASE
              tax
              lda long:EXTRA_OWNERS,x
              tax
              jmp abs:.word0 (spriteOwner)
extraHighByte:tya
              xba
              tax
              lda abs:.word0 (ownerFirstBit),x
              and ##255
              ora ##16
              tay
              bra extraHighRecord

scanFullList: lda dp:SP_COUNT
              asl a
              sta dp:MX_MASK            ; end of the near-first order
              stz dp:MX_BIT
scanOwner:    ldx dp:MX_BIT
              cpx dp:MX_MASK
              bcc scanCandidate
              jmp abs:.word0 (ownersDone)
scanCandidate:
              inx
              inx
              stx dp:MX_BIT
              lda long:SPR_ORDER-2,x       ; near-first order
              tax
              lda long:SPR_RECORDS+12,x
              inc a
              beq scanOwner             ; the weapon came from its own runs
              lda long:SPR_RECORDS+4,x
              cmp dp:MW_H
              bcc scanOwner             ; behind this column's wall
              lda long:SPR_RECORDS,x
              bmi scanLeftIn
              cmp dp:COL
              beq scanLeftIn
              bcs scanOwner
scanLeftIn:   lda long:SPR_RECORDS+2,x
              cmp dp:COL
              beq scanOwner
              bcc scanOwner
              lda ##.word0 (scanOwner)
              sta dp:OW_NEXT

;;; The world sprite in visible record X at this column: its source column's
;;; runs, with one light from its height.
spriteOwner:  cpx ##OWNER_INFO_MAX*16
              bcs spriteOwnerFar
;;; A mask bit can name any record; the entry guard selects cached owner data.
spriteOwnerNear:
              txy                       ; Y: the record
              lda long:SPR_RECORDS+14,x
              clc
              adc dp:COL
              tax
              lda long:HORIZONTAL,x       ; its source column here
              and ##255
              asl a
              adc abs:.word0 (ownerInfo+10),y
              tax
              lda long:SPRITE_CMDS,x
              sta dp:OW_PTR
              lda abs:.word0 (ownerInfo+12),y
              sta dp:OW_PTR+2
              lda [OW_PTR]
              bne spriteRuns
              .byte 0x6c                ; a transparent column: JMP (OW_NEXT)
              .word 0x1000+OW_NEXT
spriteRuns:   cpy dp:FP_LASTREC
              beq spriteWordsReady
              sty dp:FP_LASTREC
              lda abs:.word0 (ownerInfo),y
              sta dp:OW_RCB
              lda abs:.word0 (ownerInfo+2),y
              sta dp:OW_BK
              lda abs:.word0 (ownerInfo+4),y
              sta dp:OW_LIGHT
              lda abs:.word0 (ownerInfo+6),y
              sta dp:OW_VB
              lda abs:.word0 (ownerInfo+8),y
              sta dp:MX_EP              ; this height's endpoint rows
spriteWordsReady:
              bra ownerRuns
spriteOwnerFar:
              lda ##0xffff
              sta dp:FP_LASTREC
              lda long:SPR_RECORDS+6,x
              sta dp:MX_TMP             ; the frame's command header
              lda long:SPR_RECORDS+4,x
              tay                       ; Y: its height
              lda long:SPR_RECORDS+14,x
              clc
              adc dp:COL
              tax
              lda long:HORIZONTAL,x
              and ##255
              asl a
              adc dp:MX_TMP
              tax
              lda long:SPRITE_CMDS,x
              sta dp:OW_PTR
              ldx dp:MX_TMP
              lda long:SPRITE_CMDS+SPR_COMMAND_BANK,x
              sta dp:OW_PTR+2
              lda [OW_PTR]
              beq spriteNoRuns
              lda abs:.word0 (rowCodeBase),y
              sta dp:OW_RCB
              lda abs:.word0 (lightDelta),y
              lsr a
              clc
              adc ##2
              sta dp:OW_LIGHT
              dec a
              dec a
              lsr a
              clc
              adc dp:MX_TMP
              tax
              lda long:SPRITE_CMDS+SPR_LIGHT_BANKS,x
              and ##255
              xba
              ora abs:.word0 (viewScaleBank),y
              sta dp:OW_BK
              cpy ##62
              bcs farScaleReady
              ldx dp:MX_TMP
              lda long:SPRITE_CMDS+SPR_GAP,x
              bpl farScaleReady
              inc dp:OW_BK
farScaleReady:
              lda abs:.word0 (viewScaleBottom),y
              sta dp:OW_VB
              lda abs:.word0 (epPage),y
              sta dp:MX_EP
              bra ownerRuns
spriteNoRuns: .byte 0x6c                ; JMP (OW_NEXT)
              .word 0x1000+OW_NEXT

;;; The current owner's runs, bottom first: one below the dirty rows is
;;; skipped; one at or above their top ends the owner.
ownerRuns:    lda dp:CV_N
              sta dp:OW_CV0
              bne ownerCovered
              lda dp:MX_MASK
              bne ownerCovered
              lda dp:OW_NEXT
              cmp ##.word0 (maskOwnerNext)
              bne ownerCovered           ; unmasked owner scans retain the general path
              jsr abs:.word0 (prepareDirtyHull)
              lda dp:WK_B
              sta dp:CUR
              lda ##.word0 (soloDone)
              sta dp:OW_NEXT
              jmp abs:.word0 (soloLoop)
ownerCovered: stz dp:CV_I               ; this owner's disjoint runs resume bottom up
              lda dp:OW_CV0
              beq runLoop
              jmp abs:.word0 (coveredLoop)
runsDone:     .byte 0x6c                ; JMP (OW_NEXT)
              .word 0x1000+OW_NEXT
runLoop:      lda [OW_PTR]
              beq runsDone
              sep #0x20
              sta dp:MX_EP              ; replace the page's low byte before every read
              lda [MX_EP]
              sta dp:RN_T
              xba                       ; the command's bottom texel stayed in B
              sta dp:MX_EP
              lda [MX_EP]
              cmp dp:CLIPB
              bcc runRowBottom
              lda dp:CLIPB
runRowBottom: sta dp:RN_B               ; the row words keep their high bytes zero
              lda dp:RN_T
runRowTop:    cmp dp:RN_B
              rep #0x20
              bcc runInView
              jmp abs:.word0 (nearNext)  ; none of it shows
runInView:
runNear:      lda dp:RN_T               ; the nearest owner paints its runs whole
              sta dp:PC_T
              lda dp:RN_B
              sta dp:PC_B
nearGhost:    cmp dp:NG2_B               ; one hull, split only after all owners
              bcc nearGhostTop
              sta dp:NG2_B
nearGhostTop: lda dp:PC_T
              cmp dp:NG1_T
              bcs runUncovered
              sta dp:NG1_T
runUncovered: lda dp:PC_B
              cmp dp:OW_VB
              bne runCut
              lda dp:PC_T
              asl a
              tay
              lda [OW_RCB],y
              dec a
              pha
              pei dp:PA_SX
              ldy dp:OW_LIGHT
              lda [OW_PTR],y
              pha
              pei dp:OW_BK
              pea #WALLOP-1
              bra runAppend
runCut:      PUSH_RAW_CUT
;;; Rows below CLIPB are already owned. A touching span extends that covered
;;; prefix; farther sprites and the background can stop at its new top.
runAppend:    lda dp:PC_B
              cmp dp:CLIPB
              bne runAppendCover
              lda dp:PC_T
              sta dp:CLIPB              ; nearer rows below this edge are complete
              bra nearNext
runAppendCover:
              ldx dp:CV_N
              lda dp:PC_B
              xba
              ora dp:PC_T
              sta abs:.word0 (coverList),x
              inx
              inx
              stx dp:CV_N
nearNext:      lda dp:OW_PTR
              clc
              adc ##SPR_RUN_BYTES
              sta dp:OW_PTR
nearNextJmp:   jmp abs:.word0 (runLoop)
;;; A farther run: walk the covered runs bottom up from its bottom; each gap
;;; below a covered run, and what is left at its top, show.
runNext:      lda dp:OW_PTR
              clc
              adc ##SPR_RUN_BYTES
              sta dp:OW_PTR
coveredLoop:  lda [OW_PTR]
              bne coveredEndpoints
              .byte 0x6c
              .word 0x1000+OW_NEXT
coveredEndpoints:
              sep #0x20
              sta dp:MX_EP
              lda [MX_EP]
              sta dp:RN_T
              xba
              sta dp:MX_EP
              lda [MX_EP]
              cmp dp:CLIPB
              bcc coveredBottom
              lda dp:CLIPB
coveredBottom:sta dp:RN_B
              lda dp:RN_T
              cmp dp:RN_B
              rep #0x20
              bcs runNext
runCovered:   lda dp:RN_B
              sta dp:CUR
;;; The run initialized each row word; only its low byte changes here.
coverWalk:    sep #0x20
              ldx dp:CV_I
coverScan:    cpx dp:CV_N
              bcs coverRest
              inx
              inx
              stx dp:CV_I
              lda abs:.word0 (coverList-2),x
              cmp dp:CUR
              bcs coverScan             ; at or below CUR
              lda abs:.word0 (coverList-1),x
              cmp dp:RN_T
              beq coverRest             ; at or above the run: so are the rest
              bcc coverRest
              cmp dp:CUR
              bcs coverJump             ; no gap below it
              sta dp:PC_T
              lda dp:CUR
              sta dp:PC_B
              lda abs:.word0 (coverList-2),x
              sta dp:CUR
              rep #0x20
              jmp abs:.word0 (coverGapPiece)
coverJump:    cmp dp:RN_B
              bcc coverPartial
              lda abs:.word0 (coverList-2),x
              cmp dp:RN_T
              bcc coverHidden
              bne coverTopReady
coverHidden:  dex                       ; no insertion shifts this covering entry
              dex
              stx dp:CV_I
              rep #0x20
              jmp abs:.word0 (runNext)
coverPartial: lda abs:.word0 (coverList-2),x
coverTopReady:sta dp:CUR
              rep #0x20
coverCheck:   lda dp:CUR
              cmp dp:RN_T
              beq coverInsert
              bcc coverInsert
              bra coverWalk
coverRest:    rep #0x20
              lda dp:CUR
              cmp dp:RN_T
              beq coverInsert
              bcc coverInsert
              sta dp:PC_B
              lda dp:RN_T
              sta dp:PC_T
coveredPixels:
              lda dp:PC_B
              cmp dp:OW_VB
              beq coveredUncut
              PUSH_RAW_CUT
              bra coverInsert
coveredUncut: PUSH_RAW_UNCUT
coverInsert:  lda dp:RN_B
              cmp dp:CLIPB
              bne coverInsertList
              lda dp:RN_T
              sta dp:CLIPB
              stz dp:CV_I               ; no insertion shifted the next covered span
              bra runGhost
;;; Insertion moves the first span reaching above this run to CV_I.
;;; Keeping that cursor skips lower spans on the next run of this owner.
coverInsertList:
              ldx dp:CV_N
              cpx ##12
              bcc coverOrdinary
              jmp abs:.word0 (coverUnion)
coverOrdinary: xba
              sta dp:AI_TMP            ; packed bottom comparison leaves row words intact
              ldx dp:CV_N               ; keep bottoms descending
coverShift:   beq coverPlace
              lda abs:.word0 (coverList-2),x
              cmp dp:AI_TMP
              bcs coverPlace
              sta abs:.word0 (coverList),x
              dex
              dex
              bra coverShift
coverPlace:   lda dp:RN_B
              xba
              ora dp:RN_T
              sta abs:.word0 (coverList),x
              ldx dp:CV_N
              inx
              inx
              stx dp:CV_N

;;; A fully hidden run adds no restoration rows: a nearer world run or
;;; the weapon already remembers them. A holds this run's top in its low byte.
;;; The weapon is always the first owner; covered runs belong to the world.
runGhost:     and ##255                 ; this run's top
              cmp dp:NG1_T
              bcs runGhostBottom
              sta dp:NG1_T
runGhostBottom:
              lda dp:RN_B
              cmp dp:NG2_B
              bcc runGhostDone
              sta dp:NG2_B
runGhostDone: jmp abs:.word0 (runNext)

coverGapPiece:lda dp:PC_B
              cmp dp:OW_VB
              beq coverGapUncut
              PUSH_RAW_CUT
              jmp abs:.word0 (coverCheck)
coverGapUncut:PUSH_RAW_UNCUT
              jmp abs:.word0 (coverCheck)

;;; One conservative dirty hull replaces the three interval merges/walks.
;;; coverList still excludes every current owner, so extra rows get only
;;; their final background value. Empty hulls use top 255, bottom zero.
ownersDone:   lda dp:DW_T
              cmp dp:G1_T
              bcc hullOldLow
              lda dp:G1_T
hullOldLow:   cmp dp:G2_T
              bcc hullOldTop
              lda dp:G2_T
hullOldTop:   sta dp:WK_T
              lda dp:DW_B
              cmp dp:G1_B
              bcs hullOldBottom
              lda dp:G1_B
hullOldBottom:cmp dp:G2_B
              bcs hullClipBottom
              lda dp:G2_B
hullClipBottom:
              cmp dp:CLIPB
              bcc hullReady
              lda dp:CLIPB
hullReady:    sta dp:WK_B
              cmp dp:WK_T
              beq generalGhosts
              bcc generalGhosts
              stz dp:CV_I
              jmp abs:.word0 (bgWalk)
;;; Keep the existing split format for the light and decal shortcuts, but
;;; do this once per column rather than for every visible world run.
generalGhosts:
              stz dp:NG1_B
              lda ##255
              sta dp:NG2_T
              lda dp:NG1_T
              cmp dp:NG2_B
              bcs ghostsKept
              cmp ##80
              bcs hullOnlyLow
              lda dp:NG2_B
              cmp ##81
              bcc hullOnlyHigh
              lda ##80
              sta dp:NG1_B
              sta dp:NG2_T
              bra ghostsKept
hullOnlyHigh: sta dp:NG1_B
              stz dp:NG2_B
              bra ghostsKept
hullOnlyLow:  sta dp:NG2_T
              lda ##255
              sta dp:NG1_T
ghostsKept:   ldx dp:SCAN
              lda dp:NG1_T
              sta abs:.word0 (ghost1T),x
              lda dp:NG1_B
              sta abs:.word0 (ghost1B),x
              lda dp:NG2_T
              sta abs:.word0 (ghost2T),x
              lda dp:NG2_B
              sta abs:.word0 (ghost2B),x
              jmp abs:.word0 (mixedDoneX)

;;; The last owner, with only a fully covered bottom prefix remaining,
;;; streams background gaps between its runs. CUR is the unfilled dirty
;;; bottom. Earlier owners may already have enlarged the restoration hull.
              .section buffersave, text, root, noreorder
prepareDirtyHull:   lda dp:DW_T
              cmp dp:G1_T
              bcc soloHullOldLow
              lda dp:G1_T
soloHullOldLow:   cmp dp:G2_T
              bcc soloHullOldTop
              lda dp:G2_T
soloHullOldTop:   sta dp:WK_T
              lda dp:DW_B
              cmp dp:G1_B
              bcs soloHullOldBottom
              lda dp:G1_B
soloHullOldBottom:cmp dp:G2_B
              bcs soloHullClipBottom
              lda dp:G2_B
soloHullClipBottom:
              cmp dp:CLIPB
              bcc soloHullReady
              lda dp:CLIPB
soloHullReady:    sta dp:WK_B
              rts
              .section gamecode, text, root, noreorder
soloEmpty:    jmp abs:.word0 (soloDone)
soloLoop:     lda [OW_PTR]
              beq soloEmpty
              bpl soloOrdinary
              jmp abs:.word0 (poolLoop)
soloOrdinary:
              sep #0x20
              sta dp:MX_EP              ; replace the page's low byte before every read
              lda [MX_EP]
              sta dp:RN_T
              xba                       ; the command's bottom texel stayed in B
              sta dp:MX_EP
              lda [MX_EP]
              cmp dp:CLIPB
              bcc soloRowBottom
              lda dp:CLIPB
soloRowBottom:sta dp:RN_B               ; the row words keep their high bytes zero
              lda dp:RN_T
soloRowTop:   cmp dp:RN_B
              rep #0x20
              bcc soloRun
              jmp abs:.word0 (soloFirstNext) ; none of it shows
soloRun:      lda dp:RN_B
              cmp dp:WK_T
              bcs soloGapTop
              lda dp:WK_T
soloGapTop:   cmp dp:CUR
              bcs soloSprite
              sta dp:PC_T
              lda dp:CUR
              sta dp:PC_B
              lda ##.word0 (soloSprite)
              sta dp:BG_RET
              jmp abs:.word0 (pushBackground)
soloSprite:   lda dp:RN_T
              sta dp:PC_T
              sta dp:NG1_T               ; disjoint runs are ordered bottom first
              cmp dp:CUR
              bcs soloCursor
              sta dp:CUR
soloCursor:   lda dp:RN_B
              sta dp:PC_B
              cmp dp:NG2_B
              bcc soloSource
              sta dp:NG2_B               ; preserve nearer runs already merged into CLIPB
soloSource:   lda dp:PC_B
              cmp dp:OW_VB
              beq soloUncut
              PUSH_RAW_CUT
              bra soloNext
soloUncut:    PUSH_RAW_UNCUT
              bra soloNext
soloFirstNext:lda dp:OW_PTR
              clc
              adc ##SPR_RUN_BYTES
              sta dp:OW_PTR
              jmp abs:.word0 (soloLoop)
;;; Higher disjoint runs cannot reach the clipped bottom or the scaler exit.
;;; The first visible run already set the bottom restoration edge.
soloNext:     lda dp:OW_PTR
              clc
              adc ##SPR_RUN_BYTES
              sta dp:OW_PTR
soloMoreLoop: lda [OW_PTR]
              beq soloDone
              sep #0x20
              sta dp:MX_EP
              lda [MX_EP]
              sta dp:RN_T
              xba
              sta dp:MX_EP
              lda [MX_EP]
              sta dp:RN_B
              lda dp:RN_T
              cmp dp:RN_B
              rep #0x20
              bcs soloNext
              lda dp:RN_B
              cmp dp:WK_T
              bcs soloMoreGap
              lda dp:WK_T
soloMoreGap:  cmp dp:CUR
              bcs soloMoreSprite
              sta dp:PC_T
              lda dp:CUR
              sta dp:PC_B
              lda ##.word0 (soloMoreSprite)
              sta dp:BG_RET
              jmp abs:.word0 (pushBackground)
soloMoreSprite:
              lda dp:RN_T
              sta dp:PC_T
              sta dp:NG1_T
              cmp dp:CUR
              bcs soloMoreCursor
              sta dp:CUR
soloMoreCursor:
              lda dp:RN_B
              sta dp:PC_B
              PUSH_RAW_CUT
              bra soloNext
soloDone:     lda dp:WK_T
              cmp dp:CUR
              bcs soloGhosts
              sta dp:PC_T
              lda dp:CUR
              sta dp:PC_B
              lda ##.word0 (generalGhosts)
              sta dp:BG_RET
              jmp abs:.word0 (pushBackground)
soloGhosts:   jmp abs:.word0 (generalGhosts)

;;; Dirty rows [WK_T, WK_B) minus the covered runs, bottom up from CV_I. A
;;; covered run reaching above the rows stays for the next, higher walk.
bgWalk:       lda dp:WK_B
              sta dp:CUR
gapWalk:      sep #0x20
              ldx dp:CV_I
gapScan:      cpx dp:CV_N
              bcs gapRest
              inx
              inx
              stx dp:CV_I
              lda abs:.word0 (coverList-2),x
              cmp dp:CUR
              bcs gapScan               ; at or below CUR
              lda abs:.word0 (coverList-1),x
              cmp dp:WK_T
              beq gapAbove              ; at or above the dirty rows: so are the rest
              bcc gapAbove
              cmp dp:CUR
              bcs gapJump
              sta dp:PC_T
              lda dp:CUR
              sta dp:PC_B
              lda abs:.word0 (coverList-2),x
              sta dp:CUR
              rep #0x20
              lda ##.word0 (gapNext)
              sta dp:BG_RET
              jmp abs:.word0 (pushBackground)
gapJump:      lda abs:.word0 (coverList-2),x
              sta dp:CUR
              rep #0x20
gapNext:      lda dp:CUR
              cmp dp:WK_T
              beq gapDone
              bcc gapKeep
              bra gapWalk
gapKeep:      dec dp:CV_I
              dec dp:CV_I
              bra gapDone
gapAbove:     dex
              dex
              stx dp:CV_I
gapRest:      rep #0x20
              lda dp:CUR
              cmp dp:WK_T
              beq gapDone
              bcc gapDone
              sta dp:PC_B
              lda dp:WK_T
              sta dp:PC_T
              lda ##.word0 (gapDone)
              sta dp:BG_RET
              jmp abs:.word0 (pushBackground)
gapDone:      jmp abs:.word0 (generalGhosts)
mixedDone:    ldx dp:SCAN
mixedDoneX:   lda ##0                   ; X: SCAN
              sta long:COLUMN_MASKS,x
              ldx dp:COL                ; this column's marks become last frame's;
              lda long:MARKS,x       ; the column to its right is done and has
              sta long:OLD_MARKS,x       ; its own already
              jmp abs:.word0 (prepareDone)

;;; Background rows [PC_T, PC_B): floor, then wall, then ceiling pieces.
;;; A piece wholly in one region returns directly. Crossing a boundary proves
;;; the next region remains, so it needs neither a saved top nor a tail test.
pushBackground:
              lda dp:PC_B
              cmp dp:MW_B
              beq bgWall
              bcc bgWall
              lda dp:PC_T
              cmp dp:MW_B
              bcc bgCrossFloor
              lda dp:PC_B
              sec
              sbc dp:PC_T
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tax
              lda abs:.word0 (rowX160),x
              clc
              adc dp:PA_SX
              pha
flat_floor_wolf_2_18:
              pea #(FLATBANK+FLOOR*256)
              pea #.word0 (flatOp-1)
              .byte 0x6c                ; JMP (BG_RET)
              .word 0x1000+BG_RET
bgCrossFloor: lda dp:PC_B
              sec
              sbc dp:MW_B
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tax
              lda abs:.word0 (rowX160),x
              clc
              adc dp:PA_SX
              pha
flat_floor_wolf_2_16:
              pea #(FLATBANK+FLOOR*256)
              pea #.word0 (flatOp-1)
              lda dp:MW_B
              sta dp:PC_B
bgWall:       lda dp:PC_B
              cmp dp:MW_T
              beq bgOnlyCeiling
              bcc bgOnlyCeiling
              lda dp:PC_T
              cmp dp:MW_T
              bcc bgCrossWall
              bne bgOnlyWallPiece
              lda dp:PC_B
              cmp dp:MW_B
              bne bgOnlyWallPiece
              ldy dp:MW_H
              lda abs:.word0 (viewScaleAddr),y
              pha
              pei dp:PA_SX
              pei dp:MW_SRC
              pei dp:MW_BK
              pea #WALLOP-1
              .byte 0x6c                ; JMP (BG_RET)
              .word 0x1000+BG_RET
bgOnlyWallPiece:
              lda dp:PC_B
              cmp dp:MW_B
              beq bgOnlyWallUncut
              PUSH_CACHED_CUT PC_T, MW_RCB, MW_SRC, MW_BK
              .byte 0x6c                ; JMP (BG_RET)
              .word 0x1000+BG_RET
bgOnlyWallUncut:
              PUSH_CACHED_UNCUT PC_T, MW_RCB, MW_SRC, MW_BK
              .byte 0x6c                ; JMP (BG_RET)
              .word 0x1000+BG_RET
bgOnlyCeiling:
              jmp abs:.word0 (bgCeiling)
;;; This wall piece starts at the view's wall top. Its precomputed entry
;;; works for both a full wall and a cut bottom; no top-row decode is needed.
bgCrossWall:  lda dp:PC_B
              cmp dp:MW_B
              beq bgCrossWholeWall
              asl a
              tay
              lda [MW_RCB],y
              tay
              ldx dp:MW_H
              lda abs:.word0 (viewScaleAddr),x
              pha
              pei dp:PA_SX
              pei dp:MW_SRC
              phy
              pei dp:MW_BK
              pea #CUTOP-1
              bra bgWallPushed
bgCrossWholeWall:
              ldy dp:MW_H
              lda abs:.word0 (viewScaleAddr),y
              pha
              pei dp:PA_SX
              pei dp:MW_SRC
              pei dp:MW_BK
              pea #WALLOP-1
bgWallPushed: lda dp:MW_T
              sta dp:PC_B
bgCeiling:    lda dp:PC_B
              sec
              sbc dp:PC_T
              asl a
              asl a
              eor ##0xffff
              adc ##.word0 (flatCode+640)
              pha
              lda dp:PC_B
              asl a
              tax
              lda abs:.word0 (rowX160),x
              clc
              adc dp:PA_SX
              pha
flat_ceiling_wolf_2_17:
              pea #(FLATBANK+CEILING*256)
              pea #.word0 (flatOp-1)
bgDone:       .byte 0x6c                ; JMP (BG_RET)
              .word 0x1000+BG_RET

;;; Restore the last cut in every bank before setView can install different
;;; persistent exits. Index0 is an unused header byte when a bank had no cut.
paintListDone:
              lda #0xb9
              sta [LASTCUT3]
              sta [LASTCUT4]
              sta [LASTCUT5]
              rep #0x30
              lda dp:PA_STACK
              tcs
              phk
              plb
bufferFinishHook:
              jsl long:drawWeaponPose
              stz dp:FIRST
              rts
#else
paintFrame:   stz dp:COL
paintNext:    lda dp:COL
              asl a
              sta dp:SCAN
              tax
              lda abs:.word0 (heightIndex),x
              sta dp:HEIGHT
              jsr abs:.word0 (paintColumn)
              inc dp:COL
              lda dp:COL
              cmp abs:.word0 (viewWidth)
              bcc paintNext
              stz dp:FIRST
              rts
#endif
#if !WOLF_PREPARED
paintColumn:  jsr abs:.word0 (ComposeAndPaint)
              bcc plainColumn
              jmp abs:.word0 (painted)
plainColumn:  ldx dp:SCAN
              lda dp:HEIGHT
              cmp abs:.word0 (oldHeight),x
              bne dirtyColumn
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne dirtyColumn
              ldx dp:COL
              sep #0x20
              lda abs:.word0 (sourceBank),x
              cmp abs:.word0 (oldBank),x
              rep #0x20
              bne dirtyColumn
              lda dp:FIRST
              bne dirtyColumn
              rts
dirtyColumn:  ldx dp:HEIGHT
#if !WOLF_FOUR_COLORS
              lda abs:.word0 (viewScaleTex),x
              sta abs:.word0 (scaleInitial+1)
#endif
              lda abs:.word0 (viewScaleTop),x
              sta dp:TOP
              lda abs:.word0 (viewScaleBottom),x
              sta dp:BOTTOM
              lda abs:.word0 (viewScaleAddr),x
              sta dp:ENTRY
              lda abs:.word0 (viewScaleBank),x
              sta dp:ENTRY+2
              sep #0x20
              ldx dp:COL
              lda abs:.word0 (sourceBank),x
              pha
              rep #0x20
              ldx dp:SCAN
              ldy abs:.word0 (sourceAddr),x
              lda dp:COL
              clc
              adc abs:.word0 (viewLeft)
              tax
              sep #0x20
              plb                        ; texture bank for LDA abs,Y
#if !WOLF_FOUR_COLORS
scaleInitial: lda abs:0,y             ; a clipped entry may begin on a repeated texel
#endif
scaleCall:    phk
              pea #.word0 (scaleReturned-1)
              .byte 0xdc                ; JML [ENTRY], descriptor already has the far entry
              .word 0x103a
scaleReturned:
              lda #2
              pha
              plb
              rep #0x20
              ldx dp:SCAN
              lda dp:FIRST
              beq previousSpan
              lda abs:.word0 (viewTop)
              sta dp:OLDTOP
              lda abs:.word0 (viewBottom)
              sta dp:OLDBOTTOM
              bra clearFlats
previousSpan: lda abs:.word0 (oldHeight),x
              tax
              lda abs:.word0 (viewScaleTop),x
              sta dp:OLDTOP
              lda abs:.word0 (viewScaleBottom),x
              sta dp:OLDBOTTOM
clearFlats:   lda dp:COL
              clc
              adc abs:.word0 (viewLeft)
              sta dp:MULR
              lda dp:OLDTOP
              cmp dp:TOP
              bcs floorSpan
              ldy dp:TOP
              sep #0x20
flat_ceiling_wolf_1_18:
              lda #CEILING
              sta dp:EXITBYTE
              rep #0x20
              lda dp:OLDTOP
              jsr abs:.word0 (flatNonempty)
floorSpan:    lda dp:BOTTOM
              cmp dp:OLDBOTTOM
              bcs painted
              ldy dp:OLDBOTTOM
              sep #0x20
flat_floor_wolf_1_19:
              lda #FLOOR
              sta dp:EXITBYTE
              rep #0x20
              lda dp:BOTTOM
              jsr abs:.word0 (flatNonempty)
painted:      ldx dp:SCAN
              lda dp:HEIGHT
              sta abs:.word0 (oldHeight),x
              lda abs:.word0 (sourceAddr),x
              sta abs:.word0 (oldSource),x
              ldx dp:COL
              sep #0x20
              lda abs:.word0 (sourceBank),x
              sta abs:.word0 (oldBank),x
              rep #0x20
              rts

;;; Shared straight stores cost one slow screen access per restored byte.
;;; Clip by replacing one opcode, then restore it before the next span.
flatNonempty: asl a
              tax
              lda abs:.word0 (flatEntry),x
              sta abs:.word0 (flatCall+1)
              tya
              asl a
              tax
              lda abs:.word0 (flatEntry),x
              sta dp:EXITP
              lda ##2
              sta dp:EXITP+2
              sep #0x20
              lda [EXITP]
              sta dp:RAY
              lda #0x60
              sta [EXITP]
              ldx dp:MULR
              lda dp:EXITBYTE
flatCall:     jsr abs:.word0 (flatRows)
              lda dp:RAY
              sta [EXITP]
              rep #0x20
              rts
#endif

#include "assets.inc"
#include "scalers.inc"
#include "views.inc"
#include "sprites.inc"
              .public debugSpriteEnd
debugSpriteEnd:
#include "clips.inc"
              .section gamedata, data, root
              .public viewWidth, frameCount, heightIndex, sourceAddr, sourceBank
viewBytes:    .word 100
viewWidth:    .word 100
viewPostBytes:.word 200
viewFactor:   .word 160
shootDelta:   .word 20
shootLimits:  .word 16,21,24,32
viewTop:      .word 30
viewBottom:   .word 130
viewLeft:     .word 30
frameCount:   .word 0
              .section gamedata, data, root
weaponViewIndex: .word 8
              .public viewRayBank
viewRayBank:  .word 0x34,0x35,0x0f,0x36
heightView:   .word 0xffff               ; the view whose height tables stand
              .public viewKeep
viewKeep:     .word 0                    ; 1: the next setView keeps the screen (a size key in play)
              .public palHold
palHold:      .word 0                    ; 1: screenInit's colors wait in PALBUF
              .public screenHold
screenHold:   .word 0                    ; 1: a menu is up, so setView leaves the screen alone
borderFrom:   .word 0
borderCount:  .word 0
castMinX:     .word 0
castMaxX:     .word 0
castMinY:     .word 0
castMaxY:     .word 0
castMinHeight:.word 0
castPX:       .word 0
castPY:       .word 0
castAngle:    .word 0
castVX:       .word 0
castVY:       .word 0
raySurface:   .space WOLF_POST_BYTES
#if !WOLF_EXACT_RAYS
originSteps:  .word 128,-2,-128,2
originJumps:  .word .word0 originJumpX,.word0 originJumpY,.word0 originJumpX,.word0 originJumpY
originSevenJumps: .word .word0 originJumpSevenX,.word0 originJumpSevenY,.word0 originJumpSevenX,.word0 originJumpSevenY
originSevenFirstCell: .word 0
originSevenTarget: .word 0
originJumpFirst: .word 0
originJumpTarget: .word 0
#endif
raySpacing:   .word 1
fracNegativeX: .word 0
fracNegativeY: .word 0
fracPositiveX: .word 0
fracPositiveY: .word 0
worldLead:    .word 0
worldRan:     .word 0
playerTics:   .word 0
framePX:      .word 0
framePY:      .word 0
frameAngle:   .word 0
frameWeapon:  .word 0
frameWeaponType: .word 0
wallDirty:    .word 1
scaleCutsSet: .word 0
scaleCutBytes: .space 400
heightIndex:  .space WOLF_POST_BYTES
#if WOLF_PREPARED
topRowX:      .space 400                ; clipped wall top/bottom times 160
bottomRowX:   .space 400
coverList:    .space 256                ; a mixed column's covered runs
ghost1T:      .space WOLF_POST_BYTES    ; rows sprites showed: the hull above row 80,
ghost1B:      .space WOLF_POST_BYTES
ghost2T:      .space WOLF_POST_BYTES    ; and the hull at or below it
ghost2B:      .space WOLF_POST_BYTES
ownerInfo:    .space 2048               ; per visible record: owner height words
heldWeaponChanged: .word 0
paintStamp:   .word 0

decalMask:    .word 0                   ; mask bits of sprites with a transparent middle band
lightLastMask:.word 0                   ; the last moved light column's mask and record
lightLastRec: .word 0
mixLow:       .word 0                   ; columns sprites can mark, this or last frame
paintPX:      .word 0xffff              ; the camera pose of the last paint
paintPY:      .word 0
paintAngle:   .word 0
mixHigh:      .word 0
mixLowLast:   .word 0
mixHighLast:  .word 0
lightDelta:   .space 400                ; light bank offset per height
lightCB:      .space 400                ; light offset <<8 | scaler bank
columnLight:  .word 1                   ; P turns distance light off and on
#endif
hitPlane:     .space WOLF_POST_BYTES
sourceAddr:   .space WOLF_POST_BYTES
#if WOLF_PREPARED
sourceBank:   .space WOLF_POST_BYTES
#else
sourceBank:   .space WOLF_COLUMN_BYTES
#endif
oldHeight:    .space WOLF_POST_BYTES
oldSource:    .space WOLF_POST_BYTES
#if WOLF_PREPARED
oldBank:      .space WOLF_POST_BYTES
#else
oldBank:      .space WOLF_COLUMN_BYTES
#endif
doorPosition: .space 128
doorCells:    .space 128
weaponReady:  .word SPR_KNIFEREADY, SPR_PISTOLREADY, SPR_MACHINEGUNREADY, SPR_CHAINREADY
              .public demoEndTime
demoEndTime:  .word 0
demoOver:     .word 0
demoStepCall: .word 0
liveLeft:     .word 0
#if WOLF_PREPARED
endpointView: .word 0xffff
endpointPlans: .word 0,400,800,1200
#endif

#include "shading.inc"

#include "wall_dda.inc"

#if WOLF_PREPARED
;;; Spare scaler space holds the weapon dispatcher and infrequent setup.
;;; Entries restore the caller's DB after any palette, copy or display work.
              .section paintsetup, text, root
;;; Colors and screen destinations are already in the resident pose code.
;;; Only an actual pose change (or FIRST) writes the weapon. No world run
;;; can write these covered pixels, so every store changes old to final.
drawWeaponPose:
              lda dp:FIRST
              bne weaponPoseChanged
              lda long:weaponMaskTable
              cmp long:oldWeaponMaskTable
              bne weaponPoseChanged
              rtl
weaponPoseChanged:
              lda long:levelState
              beq weaponPoseVisible
              rtl
weaponPoseVisible:
              lda long:weapon
              asl a
              tax
              lda long:weaponReady,x
              clc
              adc long:weaponFrame
              sec
              sbc ##SPR_KNIFEREADY
              asl a
              asl a
              tax
              lda long:weaponDrawerEntries,x
              sta long:weaponPoseCall+1
              sep #0x20
              lda long:weaponDrawerEntries+2,x
              sta long:weaponPoseCall+3
              rep #0x20
              phb
weaponPoseBank:
              pea #0xe1e1
              plb
              plb
weaponPoseCall:
              jsl long:0
              plb
              rtl

#include "weapon_drawers.inc"
              .section paintsetup, text, root
;;; Only row bytes change; inverse silhouette bounds at 65..194 are intact.
;;; SPR_EP_SOURCE and SPR_EP_PLANS select the saved rows and copy plans.
;;; This runs on a size change only. MVN copies the middle and repeats each
;;; clipped edge. The four synthetic pool endpoints are clamped separately.
EP_SRC        .equ SP_PTR
EP_LO         .equ SP_LEFT
EP_MIDDLE     .equ SP_RIGHT
EP_PLAN       .equ SP_HI
EP_TOP        .equ SP_TOP
EP_BOTTOM     .equ SP_BOT
EP_POOLS      .equ SP_N
clipSpriteEndpoints:
              lda abs:.word0 (viewTop)
              cmp abs:.word0 (endpointView)
              bne endpointNewView
              rtl
endpointNewView:
              sta abs:.word0 (endpointView)
              sta dp:EP_TOP
              lda abs:.word0 (viewBottom)
              sta dp:EP_BOTTOM
              lda abs:.word0 (endpointPlans),x
              sta dp:EP_PLAN
              lda ##.word0 (SPR_EP_SOURCE)
              sta dp:EP_SRC
              stz dp:ENTRY
              lda ##9
              sta dp:ENTRY+2
              phb
endpointHeight:
              ldx dp:EP_PLAN
              lda long:SPR_EP_PLANS,x
              and ##255
              sta dp:EP_LO
              lda long:SPR_EP_PLANS+1,x
              and ##255
              sta dp:EP_MIDDLE
              ldy dp:ENTRY
              lda dp:EP_LO
              beq endpointCopyMiddle
              tyx
              sep #0x20
              lda dp:EP_TOP
              sta long:ENDPOINTS,x
              rep #0x20
              iny
              lda dp:EP_LO
              dec a
              beq endpointCopyMiddle
              dec a
              .byte 0x54,0x09,0x09     ; repeat the first clipped byte
endpointCopyMiddle:
              lda dp:EP_SRC
              clc
              adc dp:EP_LO
              tax
              lda dp:EP_MIDDLE
              dec a                     ; every height has at least one middle row
              .byte 0x54,0x09,.byte2 (SPR_EP_SOURCE)
              lda ##65
              sec
              sbc dp:EP_MIDDLE
              sbc dp:EP_LO
              beq endpointPools
              pha
              tyx
              sep #0x20
              lda dp:EP_BOTTOM
              sta long:ENDPOINTS,x
              rep #0x20
              iny
              pla
              dec a
              beq endpointPools
              dec a
              .byte 0x54,0x09,0x09     ; repeat the last clipped byte
endpointPools:
              lda dp:EP_SRC
              clc
              adc ##65
              tax
              ldy ##200
              sep #0x20
endpointPool:
              lda long:(SPR_EP_SOURCE & 0xff0000),x
              cmp dp:EP_TOP
              bcs endpointPoolTop
              lda dp:EP_TOP
endpointPoolTop:
              cmp dp:EP_BOTTOM
              bcc endpointPoolBottom
              lda dp:EP_BOTTOM
endpointPoolBottom:
              sta [ENTRY],y
              inx
              iny
              cpy ##SPR_EP_LIMIT
              bne endpointPool
              inc dp:ENTRY+1
              rep #0x20
              stx dp:EP_SRC
              inc dp:EP_PLAN
              inc dp:EP_PLAN
              cpx ##.word0 (SPR_EP_PLANS)
              bcs endpointsReady
              jmp abs:.word0 (endpointHeight)
endpointsReady:
              plb
              rtl

;;; A column's light follows its full-field height: 32 or less dark, 104 or
;;; more bright, the same at every view size. Each distance selects its
;;; source through a light-pointer entry.
;;; This view-setup routine keeps DB at bank 2.
buildLightTables:
              lda abs:.word0 (viewFactor)
              asl a
              asl a
              asl a
              asl a
              asl a
              xba
              and ##255
              sta dp:PA_OLD             ; tallest dark height: 32*factor/256
              lda abs:.word0 (viewFactor)
              asl a
              asl a
              asl a
              sta dp:MULR               ; 8*factor
              asl a
              asl a
              asl a                     ; 64*factor
              sec
              sbc dp:MULR               ; 56*factor
              xba
              and ##255
              sta dp:PA_HULL            ; tallest intermediate height
              lda abs:.word0 (viewFactor)
              asl a
              asl a
              asl a
              sta dp:MULR
              asl a
              clc
              adc dp:MULR
              sta dp:MULR               ; 24*factor
              lda abs:.word0 (viewFactor)
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a                     ; 128*factor
              sec
              sbc dp:MULR               ; 104*factor
              clc
              adc ##255
              xba
              and ##255
              sta dp:PA_SX              ; shortest bright height, rounded up
              ldx ##398
lightHeight:
              ldy ##12
              lda abs:.word0 (columnLight)
              beq lightReady
              lda abs:.word0 (scaleHeight),x
              cmp dp:PA_SX
              bcs lightReady
              ldy ##0
              cmp dp:PA_OLD
              bcc lightReady
              beq lightReady
              ldy ##4
              cmp dp:PA_HULL
              bcc lightReady
              beq lightReady
              ldy ##8
lightReady:   tya
              sta abs:.word0 (lightDelta),x
              lda ##0
              xba
              ora abs:.word0 (viewScaleBank),x
              sta abs:.word0 (lightCB),x
              dex
              dex
              bpl lightHeight
              rtl
#endif

#if WOLF_PREPARED
;;; Two six-bit XOR deltas per tile identify contiguous plain-wall runs.
;;; hitPlane keeps its orientation/special bits; the minor-coordinate bits
;;; hold the run origin. Equal tags cannot bridge a hole.
              .section lowlogic, data, root
              .public wallRunCells
wallRunCells: .space 8192
              .section raycode, text, root, noreorder
              .public InitWallRuns, RefreshWallRuns
InitWallRuns:
              ldx ##0
initWallRunLine:
              jsl long:RefreshWallRuns
              txa
              clc
              adc ##65                  ; one row and one column per call
              tax
              cpx ##4096
              bcc initWallRunLine
              rtl

;;; X is the changed x*64+y cell. Rebuild just its row and column; keep all
;;; caller registers/flags, and use stack locals in either logic/render DP.
RefreshWallRuns:
              php
              pha
              phx
              phy
              txa
              tay
              and ##0x0fc0
              asl a
              tax
              clc
              adc ##128
              pha                       ; column end
              txa
              pha                       ; current run start
wallRunVertical:
              lda long:TILE_MIRROR,x
              dec a
              cmp ##63
              bcc wallRunVerticalSolid
              txa
              inc a
              inc a
              sta 1,s
wallRunVerticalSolid:
              txa
              eor 1,s
              lsr a
              and ##63
              pha
              lda long:wallRunCells,x
              and ##0x0fc0
              ora 1,s
              sta long:wallRunCells,x
              pla
              inx
              inx
              txa
              cmp 3,s
              bcc wallRunVertical
              pla
              pla
              tya
              and ##63
              asl a
              tax
              pha
wallRunHorizontal:
              lda long:TILE_MIRROR,x
              dec a
              cmp ##63
              bcc wallRunHorizontalSolid
              txa
              clc
              adc ##128
              sta 1,s
wallRunHorizontalSolid:
              txa
              eor 1,s
              lsr a
              and ##0x0fc0
              pha
              lda long:wallRunCells,x
              and ##63
              ora 1,s
              sta long:wallRunCells,x
              pla
              txa
              clc
              adc ##128
              tax
              cpx ##8192
              bcc wallRunHorizontal
              pla
              ply
              plx
              pla
              plp
              rtl
#endif

#if WOLF_PREPARED
;;; The 8-bit sine product may round across a tile boundary although DDA
;;; proves this door cell was entered. Do not wrap that error to the opposite
;;; end of a partly open door: retain the nearest edge of the actual cell.
              .section raycode, text, root, noreorder
ClampDoorCoordinate:
              lda dp:SIDE
              bne clampDoorHorizontal
              lda dp:MAPIDX
              and ##63
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              bra clampDoorCell
clampDoorHorizontal:
              lda dp:MAPIDX
              and ##0x0fc0
clampDoorCell:
              sta dp:MULV
              lda dp:RAY
              and ##0x0fc0
              cmp dp:MULV
              beq clampDoorDone
              lda ##0
              bcc clampDoorLow
              lda ##63
clampDoorLow: sta dp:TEXU
              ora dp:MULV
              sta dp:RAY
clampDoorDone:
              rtl
#endif


#if WOLF_PREPARED
;;; Byte offset of the first set bit in maskOwners. The last byte pads the
;;; native word read at index 255; callers mask off its high byte.
              .section tailflow, data, root
ownerFirstBit:
              .byte 0,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 8,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 10,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 8,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 12,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 8,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 10,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 8,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 14,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 8,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 10,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 8,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 12,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 8,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 10,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 8,0,2,0,4,0,2,0,6,0,2,0,4,0,2,0
              .byte 0
#endif

#include "cover_union.inc"

;;; Filtered floor strips can overlap ordinary body runs after projection.
;;; Keep their clipped, independently bounded preparation.
              .section spriteextra, text, root, noreorder
poolEmpty:    jmp abs:.word0 (soloDone)
poolLoop:     lda [OW_PTR]
              beq poolEmpty
              sep #0x20
              sta dp:MX_EP              ; replace the page's low byte before every read
              lda [MX_EP]
              sta dp:RN_T
              xba                       ; the command's bottom texel stayed in B
              sta dp:MX_EP
              lda [MX_EP]
              cmp dp:CLIPB
              bcc poolRowBottom
              lda dp:CLIPB
poolRowBottom:sta dp:RN_B               ; the row words keep their high bytes zero
              lda dp:RN_T
poolRowTop:   cmp dp:RN_B
              rep #0x20
              bcc poolRun
              jmp abs:.word0 (poolNext)  ; none of it shows
poolRun:      lda dp:RN_B
              cmp dp:WK_T
              bcs poolGapTop
              lda dp:WK_T
poolGapTop:   cmp dp:CUR
              bcs poolSprite
              sta dp:PC_T
              lda dp:CUR
              sta dp:PC_B
              lda ##.word0 (poolSprite)
              sta dp:BG_RET
              jmp abs:.word0 (pushBackground)
poolSprite:   lda dp:RN_T
              sta dp:PC_T
              sta dp:NG1_T               ; disjoint runs are ordered bottom first
              cmp dp:CUR
              bcs poolCursor
              sta dp:CUR
poolCursor:   lda dp:RN_B
              sta dp:PC_B
              cmp dp:NG2_B
              bcc poolSource
              sta dp:NG2_B
poolSource:   lda dp:PC_B
              cmp dp:OW_VB
              beq poolUncut
              PUSH_RAW_CUT
              bra poolNext
poolUncut:    PUSH_RAW_UNCUT
poolNext:     lda dp:OW_PTR
              clc
              adc ##SPR_RUN_BYTES
              sta dp:OW_PTR
              jmp abs:.word0 (poolLoop)

              .extern WallPaintShow
              .public tightDispatch, tightLoop, tightNext, tightRangeDone
              .public tightWallEntry, tightLower, tightGrow
              .public viewScaleAddr, viewScaleBank, sourceAddr, oldSource, oldHeight, lightDelta, rowCodeBase
