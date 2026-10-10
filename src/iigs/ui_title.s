#include "campaign.inc"
;;; Attract-mode sequence: PG-13 once, then title (15 s), credits (10 s),
;;; high scores (10 s), and a demo in a loop. Menu input pauses image fades
;;; and holds; closing the menu resumes that phase. Starting or loading a
;;; game unwinds the slideshow.
#include "memmap.inc"
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public BootPicture, PgPage, TitleScreens, PlayTitleDemo, WaitInput, PalHide, FadeIn, FadeOut, screenBlack, UiBootCells, BlackScreen, IsFloppy
              .extern PollOpenKey, UiTime, UiScreen, LoadLump, DrawList, StreamScreen, ScoreFadeDraw, StartSign, StartSignStep, SignUp, BusyHide, BusyForget, FetchMainMenu
              .public FloorToFade, RevealFloor, fadeBase
              .extern levelIndex, tintFloorOffsets, menuDim, WaitBlank, screenHold
              .extern FillRect, UiDemoStart, UiDemoStep, UiDemoAbort, UiSetView, weaponViewIndex
              .extern UiResetInput, UiShowView
              .extern fadeTab, inputHead, inputTail, SelectMusic, bootComplete, MenuDimOpen, MenuDimClose
              .extern BindInit, BindBootSlots
              .extern AttractPoll, attractActive, FadeStepCore

NOKEY         .equ 0xffff
PIC_STRIP     .equ PIC_PALS + 15 * 32     ;   to $0A:8000; palette 15 is the load strip
TICKBASE      .equ 70
PG13_TICS     .equ TICKBASE * 7
TITLE_TICS    .equ TICKBASE * 15
CREDITS_TICS  .equ TICKBASE * 10
SCORES_TICS   .equ TICKBASE * 10

;;; ---------------------------------------------------------------------------
;;; Waiting for the player
;;; ---------------------------------------------------------------------------

;;; Wait A tics (0 for ever). During the slideshow, menu time is excluded and
;;; carry means a game was started/loaded. Other callers return carry on input.
WaitInput:    pha
              lda long:attractActive
              bne waitKeepInput
              lda long:inputHead             ; keys pressed before the page was there do not count
              sta long:inputTail
waitKeepInput:
              lda abs:.word0 (waitFetch)     ; the title page fetches the picture of the main menu first:
              beq waitStart                  ;   a key pressed meanwhile is read after it
              stz abs:.word0 (waitFetch)
              jsr abs:.word0 (FetchMainMenu)
waitStart:    pla
              sta dp:U_T4
              jsr abs:.word0 (UiTime)
              sta dp:U_T5
waitLoop:     lda long:attractActive
              beq waitOrdinary
              jsl long:AttractPoll
              bcs waitStartedGame
              clc
              adc dp:U_T5
              sta dp:U_T5
              bra waitClock
waitOrdinary: jsl long:PollOpenKey
              cmp ##NOKEY
              bne waitEvent
waitClock:    lda dp:U_T4
              beq waitLoop
              jsr abs:.word0 (UiTime)
              sec
              sbc dp:U_T5
              cmp dp:U_T4
              bcc waitLoop
              clc
              rts
waitStartedGame:
              rts
waitEvent:    bit ##0x80                  ; a key going up is not input
              bne waitLoop
              sec
              rts

;;; ---------------------------------------------------------------------------
;;; Fades: the 16 palettes of the screen, scaled to k/16 of their colors
;;; ---------------------------------------------------------------------------

              .extern FloorToFadeCore, RevealFloorCore
FloorToFade:  jsl long:FloorToFadeCore
              rts
RevealFloor:  jsl long:RevealFloorCore
              rts

;;; Keep the palettes on the screen aside (fadeBase) and turn the screen black.
PalHide:      jsr abs:.word0 (PalSave)
              ldx ##0
              lda ##0
hideColor:    sta long:SHR_PAL,x
              inx
              inx
              cpx ##512
              bcc hideColor
              lda ##1
              sta abs:.word0 (screenBlack)
              rts

PalSave:      ldx ##0x9e00
              ldy ##.word0 (fadeBase)
              lda ##511
              .byte 0x54, 0x3f, 0xe1         ; MVN: bank $E1 to bank $3F
              phk
              plb
              rts

;;; The screen goes from black to the palettes in fadeBase.
FadeIn:       stz abs:.word0 (screenBlack)
              lda ##1
              sta dp:U_T3
fadeInStep:   lda dp:U_T3
              jsl long:FadeStepCore
              bcs fadedOut
              inc dp:U_T3
              lda dp:U_T3
              cmp ##17
              bcc fadeInStep
              clc
              rts

;;; The screen goes to black. The palettes it had stay in fadeBase. A screen that
;;; is black already stays as it is.
FadeOut:      lda abs:.word0 (screenBlack)
              beq fadeOutStart
              clc
              rts
fadeOutStart:
              jsr abs:.word0 (PalSave)
              lda ##15
              sta dp:U_T3
fadeOutStep:  lda dp:U_T3
              jsl long:FadeStepCore
              bcs fadedOut
              dec dp:U_T3
              bpl fadeOutStep
              lda ##1
              sta abs:.word0 (screenBlack)
              clc
fadedOut:     rts

;;; All pixels to color 0, which is black in every palette.
BlackScreen:  lda ##C_BLACK
              sta dp:U_C
              stz dp:U_X
              stz dp:U_Y
              lda ##320
              sta dp:U_W
              lda ##200
              sta dp:U_H
              jmp abs:.word0 (FillRect)

;;; ---------------------------------------------------------------------------
;;; The boot picture
;;; ---------------------------------------------------------------------------

;;; The loader left the loading picture on the screen in its colors, with the load strip under it. The
;;; record of the picture is at $0A:8000 (tools/mkdisk.py --picture-file); the colors of the strip in
;;; palette 15 show that the record is there. The picture fades out with the strip when the game has
;;; started, and the pixels go black for the page after it.
BootPicture:
#ifdef CAMPAIGN_SPEAR
              lda ##CAMPAIGN_MUSIC_TITLE
#else
              lda ##7
#endif
              jsl long:SelectMusic
              lda ##37
              ldx ##1
              jsl long:UiBootCells
              lda ##1
              sta abs:.word0 (bootComplete)
              jsr abs:.word0 (BootRecord)
              bcs bootNone
              jsr abs:.word0 (FadeOut)
              jsr abs:.word0 (BlackScreen)
bootNone:     rts

;;; Carry clear when the picture record of the loader is at $0A:8000.
BootRecord:   ldx ##16
recordCheck:  lda long:PIC_STRIP,x
              cmp abs:.word0 (stripWords),x
              bne recordNone
              dex
              dex
              bpl recordCheck
              clc
              rts
recordNone:   sec
              rts

;;; JSL from the start of the game (wolf.s): X cells of the load bar of the loader, from cell A, go full. The
;;; loader filled 34 of the 38 cells and left 4 for the game: the art (cells 34 and 35, wolf.s stepBootBar), the level
;;; (cell 36) and the keys (cell 37). Each call also puts the colors of the picture back in palettes 0 and 1.
;;; The game's direct page is in use here, so the variables are absolute.
UiBootCells:  php
              rep #0x30
              phb
              phk
              plb
              sta abs:.word0 (cellNo)
              stx abs:.word0 (cellsLeft)
              jsr abs:.word0 (BootPalettes)
cellsLoop:    lda abs:.word0 (cellNo)
              jsr abs:.word0 (BootBarCell)
              inc abs:.word0 (cellNo)
              dec abs:.word0 (cellsLeft)
              bne cellsLoop
              plb
              plp
              rtl

;;; The game writes palettes 0 and 1 once while it starts (InitFlash in keys.s), and the picture of the loader uses
;;; them: its colors come back from the record at $0A:8000.
BootPalettes: jsl long:BindInit
              jsr abs:.word0 (BootRecord)
              bcs palettesNone
              ldx ##.word0 (PIC_PALS)
              ldy ##0x9e00
              lda ##63
              .byte 0x54, 0xe1, 0x0a         ; MVN: bank $0A to bank $E1
              phk
              plb
              jsl long:BindBootSlots
palettesNone: rts

;;; Cell A of the load bar full (src/iigs/loader.s drawCell): 5 by 5 pixels from x = 44 + 7 A in rows 193 to 197,
;;; color 5 of the strip palette. A pixel at the left or the right of the cell shares a byte with it and stays black.
BootBarCell:  sta abs:.word0 (cellNo2)
              asl a
              asl a
              asl a
              sec
              sbc abs:.word0 (cellNo2)
              clc
              adc ##44
              sta abs:.word0 (cellX)
              lsr a
              clc
              adc ##193 * 160
              tax
              ldy ##5
cellRow:      sep #0x20
              lda abs:.word0 (cellX)
              lsr a
              bcs cellOdd
              lda #0x55
              sta long:SHR,x
              sta long:SHR + 1,x
              lda #0x50
              sta long:SHR + 2,x
              bra cellNext
cellOdd:      lda #0x05
              sta long:SHR,x
              lda #0x55
              sta long:SHR + 1,x
              sta long:SHR + 2,x
cellNext:     rep #0x20
              txa
              clc
              adc ##160
              tax
              dey
              bne cellRow
              rts

;;; ---------------------------------------------------------------------------
;;; The pages
;;; ---------------------------------------------------------------------------

;;; The PG-13 page, once at start, with the same pause/resume behavior as the title.
PgPage:       lda ##1
              sta long:attractActive
#ifdef CAMPAIGN_SPEAR
              lda ##CAMPAIGN_MUSIC_TITLE
#else
              lda ##7
#endif
              jsl long:SelectMusic
              lda ##LUMP_PG13
              ldx ##14
              jmp abs:.word0 (fullPage)

;;; The title picture, credits and high scores. Carry set when the menu started
;;; or loaded a game; an ordinary menu close resumes the interrupted phase.
TitleScreens: lda ##1
              sta long:attractActive
#ifdef CAMPAIGN_SPEAR
              lda ##CAMPAIGN_MUSIC_TITLE
#else
              lda ##7
#endif
              jsl long:SelectMusic
              lda ##LUMP_TITLE
              ldx ##1
              jsr abs:.word0 (fullPage)
              bcs titleKey
              lda ##LUMP_CREDITS
              ldx ##12
              jsr abs:.word0 (fullPage)
              bcs titleKey
              jsl long:MenuDimOpen
              jsr abs:.word0 (ScoreFadeDraw)
              bcs scoresNone
              jsr abs:.word0 (FadeIn)
              bcs titleKey
              lda ##SCORES_TICS
              jsr abs:.word0 (WaitInput)
              bra scoresEnd
scoresNone:   clc
scoresEnd:    bcs titleKey
              jsr abs:.word0 (FadeOut)
              bcs titleKey
              lda ##1
              jsl long:MenuDimClose
              clc
titleKey:     php
              lda ##0
              sta long:attractActive
              plp
              rts

;;; The full screen picture A (screen id X): the old page fades out, the picture
;;; streams in under black palettes, fades in, shows for the time of its page and
;;; fades out. Carry set when the menu started or loaded a game.
fullPage:     stx dp:TL_ID
              pha
              jsr abs:.word0 (FadeOut)
              bcc fullLoad
              pla
              sec
              rts
fullLoad:     jsr abs:.word0 (BlackScreen)   ; so that the new row palettes show black pixels
              pla
              jsr abs:.word0 (StreamScreen)
              bcs fullNone
              lda dp:TL_ID
              sep #0x20
              sta long:UI_SCREEN
              rep #0x20
              jsr abs:.word0 (FadeIn)
              bcs fullKey
              lda dp:TL_ID
              cmp ##1
              beq fullTitle
              cmp ##14
              bne fullCredits
              lda ##PG13_TICS
              bra fullWait
fullCredits:  lda ##CREDITS_TICS
              bra fullWait
fullTitle:    lda ##1
              sta abs:.word0 (waitFetch)
              lda ##TITLE_TICS
fullWait:     jsr abs:.word0 (WaitInput)
              bcs fullKey
              jsr abs:.word0 (FadeOut)
              rts
fullKey:      rts
fullNone:     clc
              rts

;;; Carry set when the game booted from a floppy drive (slot 5 or 6).
IsFloppy:     lda long:BI_UNIT
              and ##0x70
              cmp ##0x50
              bcc notFloppy
              cmp ##0x70
              bcs notFloppy
              sec
              rts
notFloppy:    clc
              rts

;;; The next demo of the four, as in the original (LastDemo++ % 4); one that is
;;; not in the drives is skipped without changing the loaded floor.
;;; Carry set when a key stopped it.
PlayTitleDemo:
              jsr abs:.word0 (FadeOut)
              lda ##1
              sta long:screenHold          ; the demo's own setView waits for UiSetView
              ldx ##4
              stx dp:TL_TRIES
pickDemo:     lda abs:.word0 (lastDemo)
              and ##3
              pha
              lda abs:.word0 (lastDemo)
              inc a
              sta abs:.word0 (lastDemo)
              pla
demoStart:    pha                            ; the demo: its floor is twice its number
              asl a
              tax
              pla
              jsr abs:.word0 (StartSign)     ; the sign comes up now when that floor is in memory
              ldx ##0
              jsl long:UiDemoStart
              cmp ##1
              beq demoReady
              lda ##1
              sta abs:.word0 (bootComplete)
              jsr abs:.word0 (BusyHide)      ; no demo: the screen goes back to black
demoSkip:     dec dp:TL_TRIES
              bne pickDemo
              lda ##0
              sta long:screenHold
              clc                         ; return to the visible title cycle after failed loads
              rts
demoReady:    lda long:weaponViewIndex
              lsr a
              jsl long:UiSetView
              jsr abs:.word0 (StartSignStep)
              lda ##0
              sta long:screenHold
              jsr abs:.word0 (BlackScreen)   ; the game screen starts from black
              jsr abs:.word0 (BusyForget)
              jsl long:UiShowView         ; geometry was prepared while the sign was visible
              stz abs:.word0 (screenBlack)
              ; Preparing the screen is paused time, not demo catch-up debt.
              jsl long:UiResetInput
              SCREEN_ID 13
              lda long:inputHead
              sta long:inputTail
demoLoop:     jsl long:UiDemoStep
              cmp ##1
              beq demoOver
              jsl long:PollOpenKey
              cmp ##NOKEY
              beq demoLoop
              bit ##0x80
              bne demoLoop
              jsl long:UiDemoAbort
              sec
              rts
demoOver:     clc
              rts

              .section menudata, data, root
stripWords:   .word 0x0000, 0x0333, 0x0555, 0x0777, 0x0bbb, 0x0fff, 0x0666, 0x0999, 0x0ddd
lastDemo:     .word 0
screenBlack:  .word 0                        ; 1 when the palettes on the screen are black
fadeBase:     .space 512
cellNo:       .word 0
waitFetch:    .word 0                     ; 1: the next WaitInput fetches the main menu first
cellNo2:      .word 0
cellsLeft:    .word 0
cellX:        .word 0
