;;; Timed demo execution. Consume recorded packets without real-time waits;
;;; DOC tics measure complete frames and exclude the final world reset.
;;; Starting the demo replaces gameplay state, so BenchScreen confirms before
;;; replacing a live game. Cancellation skips the result display. The result
;;; remains in RAM; this path does not write settings or saved games.
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public BenchScreen
              .extern Confirm, ShowNote, PollKey, UiTime, UiSound, NumToStr, Num32ToStr, OutStr, UiDiv16
              .extern UiSetView, uiGameOn, benchFresh, strCurGame, UiScreen, StartSign, BusyHide, BusyForget
              .extern weaponViewIndex, viewNames, UiDemoStart, UiDemoStep, UiDemoAbort, SelectMusic
              .extern MenuDimOpen, MenuPrepare, MenuFinish, PalBlack, BlackPixels, menuDim, screenHold
              .extern RenderPage, pageBlack, GetKey, DrawTitleCore, DrawStr, DrawStrRight, DrawStrCenter, LoadLump
              .extern demoEndTime, BenchDivide, BenchMultiply
              .public dvA, dvB, dvR, mulA, mulB
              .public benchFrames, sMachine, sSeconds, sMs, sPoint
              .public BenchNumOut, BenchNum32Out, BenchOut, BenchDiv16
              .extern BenchTextCore
              .public benchLast, benchSlowest, benchTics, benchRow, benchY, benchLabels, benchOut, sReturn
              .public BenchDrawLeft, BenchDrawRight, BenchDrawCenter
              .extern BenchClock, BenchPaintCore, J13Benchmark, J13Menu, CpuMeasure, StopMusic

NOKEY         .equ 0xffff
ESCPRESSEDSND .equ 39
BENCH_DEMO    .equ 0                        ; E1M1, the first floor

BenchScreen:  lda abs:.word0 (uiGameOn)
              beq benchBegin
              lda abs:.word0 (benchFresh)
              bne benchBegin
              lda ##.word0 (strCurGame)
              sta dp:U_STR
              jsr abs:.word0 (Confirm)
              bcc benchBegin
              rts
benchBegin:   jsl long:J13Benchmark
              lda abs:.word0 (menuDim)
              sta abs:.word0 (benchFromDim)
              ldx ##BENCH_DEMO * 2
              jsr abs:.word0 (StartSign)
              jsl long:StopMusic
              jsl long:CpuMeasure
              lda ##BENCH_DEMO
              ldx ##1
              jsl long:UiDemoStart
              cmp ##1
              beq benchStarted
              jsr abs:.word0 (BusyHide)
              jsl long:J13Menu
              stz abs:.word0 (benchFromDim)
              lda ##.word0 (strNoDemo)
              sta dp:U_STR
              jmp abs:.word0 (ShowNote)
benchStarted: lda long:weaponViewIndex
              lsr a
              jsl long:UiSetView
              jsr abs:.word0 (BusyForget)
              lda abs:.word0 (benchFromDim)
              beq benchArmed
              jsl long:PalBlack
              jsl long:BlackPixels
              stz abs:.word0 (menuDim)
benchArmed:   lda ##1
              sta abs:.word0 (uiGameOn)
              sta abs:.word0 (benchFresh)
              lda ##0
              sta long:screenHold
              lda long:weaponViewIndex
              lsr a
              jsl long:UiSetView
              SCREEN_ID 10
              stz abs:.word0 (benchSlowest)
              stz abs:.word0 (benchFrames)
              stz abs:.word0 (benchTics)
              stz abs:.word0 (benchTics + 2)
              jsr abs:.word0 (UiTime)
              sta abs:.word0 (benchLast)
benchRun:     jsl long:UiDemoStep
              pha
              inc abs:.word0 (benchFrames)
              cmp ##1
              bne benchRunningClock
              lda long:demoEndTime
              bra benchClockReady
benchRunningClock: jsr abs:.word0 (UiTime)
benchClockReady: jsl long:BenchClock
              pla
              cmp ##1
              beq benchDone
              jsr abs:.word0 (benchEsc)
              bcc benchRun
              lda ##ESCPRESSEDSND
              jsr abs:.word0 (UiSound)
              jsl long:UiDemoAbort
              jsl long:MenuDimOpen
              bra benchBack
benchDone:    lda abs:.word0 (benchTics)
              ora abs:.word0 (benchTics + 2)
              bne benchTimed
              lda ##1
              sta abs:.word0 (benchTics)
benchTimed:   jsl long:J13Menu
              jsr abs:.word0 (benchText)
              jsl long:MenuDimOpen
              jsl long:MenuPrepare
              lda ##LUMP_BENCH
              jsr abs:.word0 (LoadLump)
              lda ##0
              sta long:pageBlack
              ldx ##.word0 (benchPaint)
              jsl long:RenderPage
              jsr abs:.word0 (MenuFinish)
              SCREEN_ID 11
              jsr abs:.word0 (GetKey)
benchBack:    jsl long:J13Menu
              lda ##1
              sta long:screenHold
              rts

;;; Carry set when Esc went down. Every key event queued is read.
benchEsc:     jsr abs:.word0 (PollKey)
              cmp ##NOKEY
              beq benchNoEsc
              cmp ##K_ESC
              bne benchEsc
              sec
              rts
benchNoEsc:   clc
              rts

benchText:    jsl long:BenchTextCore
              rts
BenchNumOut:  jsr abs:.word0 (NumToStr)
              jsr abs:.word0 (OutStr)
              rtl
BenchNum32Out: jsr abs:.word0 (Num32ToStr)
              jsr abs:.word0 (OutStr)
              rtl
BenchOut:     jsr abs:.word0 (OutStr)
              rtl
BenchDiv16:   jsr abs:.word0 (UiDiv16)
              rtl

benchPaint:   jsl long:BenchPaintCore
              rts
BenchDrawLeft: jsr abs:.word0 (DrawStr)
              rtl
BenchDrawRight: jsr abs:.word0 (DrawStrRight)
              rtl
BenchDrawCenter: jsr abs:.word0 (DrawStrCenter)
              rtl

              .section menudata, data, root
benchFrames:  .word 0
benchFromDim: .word 0
benchTics:    .word 0, 0
benchLast:    .word 0
dvA:          .word 0, 0
dvB:          .word 0, 0
dvR:          .word 0, 0
mulA:         .word 0, 0
mulB:         .word 0
benchOut:     .space 160
benchSlowest: .word 0
benchRow:     .word 0
benchY:       .word 0
strNoDemo:    .asciz "The demo is not on the disk."
sMachine:     .asciz "IIgs ROM "
sSeconds:     .asciz " s"
sMs:          .asciz " ms"
sPoint:       .asciz "."
sReturn:      .asciz "Any key returns to menu"
benchLabels:  .word .word0 (sMach), .word0 (sView), .word0 (sFrames), .word0 (sTime), .word0 (sAverage), .word0 (sSlowest), .word0 (sFps)
              .word .word0 (sAccel), .word0 (sCPU), .word0 (sCache)
sAccel:       .asciz "Accelerator"
sCPU:         .asciz "CPU"
sCache:       .asciz "Cache"
sMach:        .asciz "Machine"
sView:        .asciz "View"
sFrames:      .asciz "Frames"
sTime:        .asciz "Time"
sAverage:     .asciz "Average"
sSlowest:     .asciz "Slowest"
sFps:         .asciz "FPS"
