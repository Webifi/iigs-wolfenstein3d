;;; Synthetic camera route for UI_DEMOS=0 builds. Only route 0 is available;
;;; tools/bench_route.py supplies its packets. PlayDemoStart/Step/Stop keep
;;; the same title/benchmark interface without the recorded-demo player.
;;; With UI_DEMOS enabled, callers use UiDemoStart/Step/Abort in ui_hooks.s.
#include "memmap.inc"
#include "frontend.inc"
              .section menucode, text, root, noreorder
#if !UI_DEMOS
              .public PlayDemoStart, PlayDemoStep, PlayDemoStop
              .extern UiRender, UiTime, UiStartGame, benchRoute

PX_ADDR       .equ GAME_DP                 ; the pose in the game's direct page
PY_ADDR       .equ GAME_DP+0x2
ANGLE_ADDR    .equ GAME_DP+0x4
DEMOTICS      .equ 4                        ; logic tics per recorded demo packet

PlayDemoStart: cmp ##0
              bne standNone
              stx abs:.word0 (standTimed)
              lda ##2                       ; Bring 'em on!: the world as a new game has it
              ldx ##0
              jsl long:UiStartGame
              lda long:PX_ADDR
              sta abs:.word0 (standHome)
              lda long:PY_ADDR
              sta abs:.word0 (standHome + 2)
              lda long:ANGLE_ADDR
              sta abs:.word0 (standHome + 4)
              lda abs:.word0 (benchRoute)
              sta long:PX_ADDR
              lda abs:.word0 (benchRoute + 2)
              sta long:PY_ADDR
              lda abs:.word0 (benchRoute + 4)
              sta long:ANGLE_ADDR
              lda ##.word0 (benchRoute + 6)
              sta abs:.word0 (standStep)
              stz abs:.word0 (standLeft)
              lda ##1
              sta abs:.word0 (standFirst)
              jsr abs:.word0 (UiTime)
              sta abs:.word0 (standLast)
              lda ##1
              rts
standNone:    lda ##0
              rts

PlayDemoStep:  lda abs:.word0 (standTimed)
              bne standGo
standWait:    jsr abs:.word0 (UiTime)       ; a picture takes at least a packet's tics
              sec
              sbc abs:.word0 (standLast)
              cmp ##DEMOTICS
              bcc standWait
              lda abs:.word0 (standLast)
              clc
              adc ##DEMOTICS
              sta abs:.word0 (standLast)
standGo:      lda abs:.word0 (standFirst)
              beq standMove
              stz abs:.word0 (standFirst)   ; the first picture is the start of the route
              bra standDraw
standMove:    lda abs:.word0 (standLeft)
              bne standDelta
              ldx abs:.word0 (standStep)
              lda abs:0,x
              sta abs:.word0 (standLeft)
standDelta:   ldx abs:.word0 (standStep)
              lda long:PX_ADDR
              clc
              adc abs:2,x
              sta long:PX_ADDR
              lda long:PY_ADDR
              clc
              adc abs:4,x
              sta long:PY_ADDR
              lda long:ANGLE_ADDR
              clc
              adc abs:6,x
              and ##1023
              sta long:ANGLE_ADDR
              dec abs:.word0 (standLeft)
              bne standDraw
              lda abs:.word0 (standStep)
              clc
              adc ##8
              sta abs:.word0 (standStep)
standDraw:    jsl long:UiRender
              lda abs:.word0 (standLeft)    ; the call that draws the last picture says the demo is over
              bne standGoing
              ldx abs:.word0 (standStep)
              lda abs:0,x
              bne standGoing
              jsr abs:.word0 (standHomeAgain)
              lda ##1
              rts
standGoing:   lda ##0
              rts

PlayDemoStop:  jmp abs:.word0 (standHomeAgain)

;;; The player is where the new game put them.
standHomeAgain:
              lda abs:.word0 (standHome)
              sta long:PX_ADDR
              lda abs:.word0 (standHome + 2)
              sta long:PY_ADDR
              lda abs:.word0 (standHome + 4)
              sta long:ANGLE_ADDR
              rts

              .section menudata, data, root
standTimed:   .word 0
standHome:    .word 0, 0, 0
standStep:    .word 0
standLeft:    .word 0
standFirst:   .word 0
standLast:    .word 0
#endif
