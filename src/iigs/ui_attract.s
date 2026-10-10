#include "memmap.inc"
#include "frontend.inc"
#include "logic.inc"
              .section uifastcode, text, root, noreorder
              .public AttractPoll, attractActive, attractPaused, attractResume, PollOpenKey
              .extern attractPage, attractPalette, fadeBase, screenBlack, menuDim
              .extern PollKeyLong, MainMenuLong, UiGetTime, MenuDimOpen, MenuDimClose
              .extern uiGameOn, UiResetInput

;;; Only a fresh Escape press opens a menu from a title or gameplay demo.
;;; Drain other events so they cannot leak into the next page.
PollOpenKey:  jsl long:PollKeyLong
              cmp ##0xffff
              beq openKeyReady
              cmp ##K_ESC
              bne PollOpenKey
openKeyReady: rtl

;;; Carry clear: A is the number of tics spent in a menu, or zero. Carry set:
;;; the menu started/loaded a game, so the slideshow caller must unwind.
;;; Callers use DBR $3F and UI_DP. The saved working page includes the fade
;;; step and wait counters; the existing menu snapshot preserves the screen.
AttractPoll:  lda long:attractActive
              beq attractNoKey
              jsl long:PollOpenKey
              cmp ##0xffff
              beq attractNoKey
              bit ##0x80
              bne attractNoKey
              jmp abs:.word0 (attractOpen)
attractNoKey: lda ##0
              clc
              rtl
attractOpen:  jsl long:UiGetTime
              sta long:attractTime
              lda long:menuDim
              sta long:attractDim
              lda long:screenBlack
              sta long:attractBlack
              lda long:UI_SCREEN
              and ##255
              sta long:attractScreen
              phb
              ldx ##UI_DP
              ldy ##.word0 (attractPage)
              lda ##255
              .byte 0x54, 0x3c, 0x00
              ldx ##.word0 (fadeBase)
              ldy ##.word0 (attractPalette)
              lda ##511
              .byte 0x54, 0x3c, 0x3f
              plb
              lda ##0
              sta long:attractActive
attractPaused:
              jsl long:MenuDimOpen
              jsl long:MainMenuLong
              ora long:uiGameOn
              sta long:attractResult
              jsl long:MenuDimClose
              lda long:attractResult
              beq attractRestore
              sec
              rtl
attractRestore:
              phb
              ldx ##.word0 (attractPage)
              ldy ##UI_DP
              lda ##255
              .byte 0x54, 0x00, 0x3c
              ldx ##.word0 (attractPalette)
              ldy ##.word0 (fadeBase)
              lda ##511
              .byte 0x54, 0x3f, 0x3c
              plb
              lda long:attractDim
              sta long:menuDim
              lda long:attractBlack
              sta long:screenBlack
              sep #0x20
              lda long:attractScreen
              sta long:UI_SCREEN
              rep #0x20
              ; A release can already be queued behind the Escape that
              ; closed the menu. Reset its held state with the discarded
              ; events, or the next press looks like an already-held key.
              jsl long:UiResetInput
              lda ##1
              sta long:attractActive
              jsl long:UiGetTime
              sec
              sbc long:attractTime
attractResume:
              clc
              rtl
attractActive: .word 0
attractTime:   .word 0
attractDim:    .word 0
attractBlack:  .word 0
attractScreen: .word 0
attractResult: .word 0

              .public FadeStepCore
              .extern fadeTab, WaitBlank
;;; Prepare one complete fade step in the paused UI strip, then publish it
;;; during blanking. Menus can reuse the strip while the fade waits for input.
              .extern OverlayTitleClobbered
FadeStepCore:
              jsl long:OverlayTitleClobbered  ; the fade buffer covers resident art
              asl a
              asl a
              asl a
              asl a
              sta dp:U_T0                    ; the row of fadeTab
              ldx ##0
fadeColor:    lda abs:.word0 (fadeBase),x
              sta dp:U_T1
              and ##15                       ; blue
              clc
              adc dp:U_T0
              tay
              sep #0x20
              lda abs:.word0 (fadeTab),y
              rep #0x20
              and ##255
              sta dp:U_T2
              lda dp:U_T1                    ; green
              lsr a
              lsr a
              lsr a
              lsr a
              and ##15
              clc
              adc dp:U_T0
              tay
              sep #0x20
              lda abs:.word0 (fadeTab),y
              rep #0x20
              and ##255
              asl a
              asl a
              asl a
              asl a
              ora dp:U_T2
              sta dp:U_T2
              lda dp:U_T1                    ; red
              xba
              and ##15
              clc
              adc dp:U_T0
              tay
              sep #0x20
              lda abs:.word0 (fadeTab),y
              rep #0x20
              and ##255
              xba
              ora dp:U_T2
              sta long:FADE_BUFFER,x
              inx
              inx
              cpx ##512
              bcc fadeColor
              jsl long:WaitBlank
              phb
              ldx ##.word0 FADE_BUFFER
              ldy ##0x9e00
              lda ##511
              .byte 0x54, 0xe1, 0x3c
              plb
fadeDelay:    jsl long:UiGetTime
              sta dp:U_T4
fadeWait:     jsl long:AttractPoll
              bcs fadeInterrupted
              clc
              adc dp:U_T4
              sta dp:U_T4
              jsl long:UiGetTime
              sec
              sbc dp:U_T4
              cmp ##2                     ; tics per step, excluding menu time
              bcc fadeWait
              clc
fadeInterrupted:
              rtl
