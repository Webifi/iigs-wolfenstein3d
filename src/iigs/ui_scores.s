#include "campaign.inc"
;;; View Scores: the seven best games kept in WOLF.SETTINGS, as in the original
;;; (names of id Software until a player beats them). When a game ends with a
;;; score that reaches the table, text over the game's own screen asks for a
;;; name. The table goes to the disk with Save Settings, like the other settings.
#include "frontend.inc"
#include "logic.inc"
              .section menucode, text, root, noreorder
              .public ScoreScreen, ScoreDraw, ScoreFadeDraw, DefaultScores, MenuGameOver
              .extern RenderPage, RenderFadePage, pageBlack, DrawPageList
              .extern LoadLump, DrawList, DrawStr, DrawStrRight, GetKey, NumToStr, MenuScreen, MenuFinish, GrayRect, RevealFloor
              .extern Num32ToStr, dlScores, UiSound, scoreTable, UiEnterCore, UiLeaveCore
              .extern PollKey, BusyShow, BusyHide, FillRect, StrWidth, UiTime, adbPlain, adbShift
              .extern score, levelIndex, SelectMusic
              .extern PlayCacheLeave

NOKEY         .equ 0xffff
SC_NAME_X     .equ 24
SC_FLOOR_X    .equ 304
SC_SCORE_X    .equ 228
SC_Y          .equ 64
SC_STEP       .equ 18
SC_COUNT      .equ 7
SC_SIZE       .equ 24                  ; name 16, score 4, floor 1, pad 3
SC_SCORE      .equ 16
SC_FLOOR      .equ 20
SC_NAME_W     .equ 134                 ; the name column width
SC_NAME_MAX   .equ 15

;;; View Scores from the menu: any key goes back.
ScoreScreen:  jsr abs:.word0 (ScoreDraw)
              bcs scoreOut
              jsr abs:.word0 (RevealFloor)
              jsr abs:.word0 (GetKey)
scoreOut:     rts

;;; The table on the screen. Carry set when its pictures did not load.
ScoreFadeDraw: lda ##1
              bra scoreBegin
ScoreDraw:    lda ##0
scoreBegin:   sta abs:.word0 (scoreFade)
              lda ##LUMP_SCORES
              jsr abs:.word0 (LoadLump)
              bcc scoreShow
scoreFail:    rts
scoreShow:    ldx ##.word0 (dlScores)
              jsr abs:.word0 (MenuScreen)
              lda ##0
              sta long:pageBlack
              ldx ##.word0 (scorePaint)
              lda abs:.word0 (scoreFade)
              beq scoreMenuPage
              jsl long:RenderFadePage
              bra scoreReady
scoreMenuPage:
              jsl long:RenderPage
              jsr abs:.word0 (MenuFinish)
scoreReady:   SCREEN_ID 6
              clc
              rts
scorePaint:   jsr abs:.word0 (DrawPageList)
              lda ##C_YELLOW
              sta dp:U_C
              stz dp:U_FONT
              lda ##SC_NAME_X
              sta dp:U_X
              lda ##SC_Y - 16
              sta dp:U_Y
              lda ##.word0 (hName)
              sta dp:U_STR
              jsr abs:.word0 (DrawStr)
              lda ##SC_FLOOR_X
              sta dp:U_X
              lda ##.word0 (hFloor)
              sta dp:U_STR
              jsr abs:.word0 (DrawStrRight)
              lda ##SC_SCORE_X
              sta dp:U_X
              lda ##.word0 (hScore)
              sta dp:U_STR
              jsr abs:.word0 (DrawStrRight)
              stz dp:U_ITEM
scoreRow:     lda dp:U_ITEM
              asl a
              asl a
              asl a
              sta dp:U_T5                  ; * 8
              asl a                        ; * 16
              clc
              adc dp:U_T5                  ; * 24
              tax
              stx dp:U_T4
              ldy ##0
scoreName:    sep #0x20
              lda long:SETTINGS_IN + S_SCORES,x
              sta abs:.word0 (nameBuf),y
              rep #0x20
              inx
              iny
              cpy ##16
              bcc scoreName
              sep #0x20
              lda #0
              sta abs:.word0 (nameBuf + 15)
              rep #0x20
              lda ##15
              sta dp:U_T3
scoreFit:     lda ##.word0 (nameBuf)
              sta dp:U_STR
              jsr abs:.word0 (StrWidth)
              cmp ##SC_NAME_W
              bcc scoreNameFits
              dec dp:U_T3
              ldy dp:U_T3
              lda ##'.'
              sta abs:.word0 (nameBuf),y
              bra scoreFit
scoreNameFits: lda dp:U_ITEM
              ldx ##SC_STEP
              jsr abs:.word0 (mulRow)
              clc
              adc ##SC_Y
              sta dp:U_Y
              lda ##C_GRAY
              sta dp:U_C
              lda ##SC_NAME_X
              sta dp:U_X
              lda ##.word0 (nameBuf)
              sta dp:U_STR
              jsr abs:.word0 (DrawStr)
              ldx dp:U_T4
              lda long:SETTINGS_IN + S_SCORES + SC_FLOOR,x
              and ##255
              jsr abs:.word0 (NumToStr)
              lda ##SC_FLOOR_X
              sta dp:U_X
              lda ##C_GRAY
              sta dp:U_C
              jsr abs:.word0 (DrawStrRight)
              ldx dp:U_T4
              lda long:SETTINGS_IN + S_SCORES + SC_SCORE,x
              sta dp:U_T0
              lda long:SETTINGS_IN + S_SCORES + SC_SCORE + 2,x
              sta dp:U_T1
              jsr abs:.word0 (Num32ToStr)
              lda ##SC_SCORE_X
              sta dp:U_X
              lda ##C_GRAY
              sta dp:U_C
              jsr abs:.word0 (DrawStrRight)
              inc dp:U_ITEM
              lda dp:U_ITEM
              cmp ##SC_COUNT
              bcs scoreDone
              jmp abs:.word0 (scoreRow)
scoreDone:
              clc
              rts

;;; A * X for small values.
mulRow:       sta dp:U_T0
              lda ##0
mulRowAdd:    clc
              adc dp:U_T0
              dex
              bne mulRowAdd
              rts

;;; The table of the original, in the image.
DefaultScores:
              ldx ##0
defaultScore: sep #0x20
              lda abs:.word0 (scoreTable),x
              sta long:SETTINGS_IN + S_SCORES,x
              rep #0x20
              inx
              cpx ##SC_COUNT * SC_SIZE
              bcc defaultScore
              rts

;;; ---------------------------------------------------------------------------
;;; A game over with a score for the table
;;; ---------------------------------------------------------------------------

;;; The game calls this once when it is over (UiGameOver in ui_hooks.s), with its
;;; own direct page: nothing of it is used until the menu page is in.
MenuGameOver: php
              rep #0x30
              phb
              phd
              phk
              plb
              lda ##0xffff                  ; the play cache before the high-score song
              jsl long:PlayCacheLeave       ; (home disk) asks for another disk
#ifdef CAMPAIGN_SPEAR
              lda ##CAMPAIGN_MUSIC_SCORES
#else
              lda ##23
#endif
              jsl long:SelectMusic
              jsr abs:.word0 (ScoreInsert)
              bcs gameOverEnd
              jsr abs:.word0 (UiEnterCore)
              jsr abs:.word0 (ScoreAsk)
              jsr abs:.word0 (UiLeaveCore)
gameOverEnd:  pld
              plb
              plp
              rtl

;;; Put the score of the game that ended in the table. Carry clear when it has
;;; a place: the entry is made with an empty name, scOffset is where it is. A
;;; score the same as one in the table goes below it, unless its floor is higher.
ScoreInsert:  lda long:score
              sta abs:.word0 (scNew)
              lda long:score + 2
              sta abs:.word0 (scNew + 2)
              lda long:levelIndex
              inc a
              sta abs:.word0 (scFloor)
              ldx ##0
              ldy ##0
findPlace:    lda abs:.word0 (scNew + 2)
              cmp long:SETTINGS_IN + S_SCORES + SC_SCORE + 2,x
              bcc findNext
              bne findHere
              lda abs:.word0 (scNew)
              cmp long:SETTINGS_IN + S_SCORES + SC_SCORE,x
              bcc findNext
              bne findHere
              lda long:SETTINGS_IN + S_SCORES + SC_FLOOR,x
              and ##255
              cmp abs:.word0 (scFloor)
              bcs findNext
              bra findHere
findNext:     txa
              clc
              adc ##SC_SIZE
              tax
              iny
              cpy ##SC_COUNT
              bcc findPlace
              sec
              rts
findHere:     stx abs:.word0 (scOffset)
              lda ##SC_COUNT - 1             ; the entries below move down one place
              sta abs:.word0 (scCount)
              tya
              eor ##0xffff
              inc a
              clc
              adc abs:.word0 (scCount)
              beq findMake
              asl a
              asl a
              asl a
              sta abs:.word0 (scCount)       ; * 8
              asl a
              clc
              adc abs:.word0 (scCount)       ; * 24 bytes to move
              sta abs:.word0 (scCount)
              lda abs:.word0 (scOffset)
              clc
              adc ##SETTINGS_IN + S_SCORES
              clc
              adc abs:.word0 (scCount)
              dec a
              tax                            ; the last byte of the move
              clc
              adc ##SC_SIZE
              tay                            ; and where it goes
              lda abs:.word0 (scCount)
              dec a
              .byte 0x44, 0x00, 0x00         ; MVP: bank 0 to bank 0, from the end
              phk
              plb
findMake:     ldx abs:.word0 (scOffset)
              lda ##0
              ldy ##8
clearName:    sta long:SETTINGS_IN + S_SCORES,x
              inx
              inx
              dey
              bne clearName
              lda abs:.word0 (scNew)
              sta long:SETTINGS_IN + S_SCORES,x
              lda abs:.word0 (scNew + 2)
              sta long:SETTINGS_IN + S_SCORES + 2,x
              lda abs:.word0 (scFloor)
              and ##255
              sta long:SETTINGS_IN + S_SCORES + 4,x
              lda ##0
              sta long:SETTINGS_IN + S_SCORES + 6,x
              clc
              rts

;;; The box with the name field. Return, Enter or Esc ends it: with no name
;;; typed, the hero's name goes in. The name is written into the entry.
ScoreAsk:     lda ##3
              jsr abs:.word0 (BusyShow)
              ldx ##0
              lda ##0
clearBuf:     sta abs:.word0 (scName),x
              inx
              inx
              cpx ##16
              bcc clearBuf
              stz abs:.word0 (scLen)
              stz abs:.word0 (scShift)
              stz abs:.word0 (scCaps)
              lda ##1
              sta abs:.word0 (scCursor)
              jsr abs:.word0 (blinkTime)
              jsr abs:.word0 (scField)
askKey:       jsr abs:.word0 (PollKey)
              cmp ##NOKEY
              beq askIdle
              sta dp:U_KEY
              and ##0x7f
              sta dp:U_T0                    ; the key
              cmp ##0x38
              beq askShiftKey
              cmp ##0x7b
              beq askShiftKey
              cmp ##0x39
              beq askCapsKey
              lda dp:U_KEY
              bit ##0x80
              bne askKey                     ; a key going up
              lda dp:U_T0
              cmp ##K_RETURN
              beq askDone
              cmp ##K_ENTER
              beq askDone
              cmp ##K_ESC
              beq askDone
              cmp ##K_DELETE
              beq askBack
              jmp abs:.word0 (askChar)
askShiftKey:  lda dp:U_KEY
              and ##0x80
              eor ##0x80                     ; set while the key is down
              sta abs:.word0 (scShift)
              jmp abs:.word0 (askKey)
askCapsKey:   lda dp:U_KEY
              and ##0x80
              eor ##0x80
              sta abs:.word0 (scCaps)
              jmp abs:.word0 (askKey)
askIdle:      jsr abs:.word0 (UiTime)
              sec
              sbc abs:.word0 (scBlink)
              bmi askKey
              lda abs:.word0 (scCursor)
              eor ##1
              sta abs:.word0 (scCursor)
              jsr abs:.word0 (blinkTime)
              jsr abs:.word0 (scField)
              jmp abs:.word0 (askKey)
askBack:      lda abs:.word0 (scLen)
              beq askKey
              dec a
              sta abs:.word0 (scLen)
              tay
              sep #0x20
              lda #0
              sta abs:.word0 (scName),y
              rep #0x20
              jsr abs:.word0 (scField)
              jmp abs:.word0 (askKey)
askDone:      lda abs:.word0 (scLen)
              bne askStore
              ldx ##0
askHero:      sep #0x20
              lda abs:.word0 (sHero),x
              sta abs:.word0 (scName),x
              beq askHeroDone
              rep #0x20
              inx
              bra askHero
askHeroDone:  rep #0x20
askStore:     ldx abs:.word0 (scOffset)
              ldy ##0
askCopy:      sep #0x20
              lda abs:.word0 (scName),y
              sta long:SETTINGS_IN + S_SCORES,x
              rep #0x20
              inx
              iny
              cpy ##16
              bcc askCopy
              jmp abs:.word0 (BusyHide)

;;; The key in U_T0 as a character: plain, or shifted when Shift is down (for
;;; a letter, when Shift and Caps Lock differ). It joins the name if the name
;;; stays short enough.
askChar:      ldx dp:U_T0
              sep #0x20
              lda abs:.word0 (adbPlain),x
              rep #0x20
              and ##255
              beq askNone                    ; a key with no character
              sta dp:U_T1
              cmp ##'a'
              bcc askNotLetter
              cmp ##'z' + 1
              bcs askNotLetter
              lda abs:.word0 (scShift)
              eor abs:.word0 (scCaps)
              bra askPick
askNotLetter: lda abs:.word0 (scShift)
askPick:      beq askAdd
              ldx dp:U_T0
              sep #0x20
              lda abs:.word0 (adbShift),x
              rep #0x20
              and ##255
              sta dp:U_T1
askAdd:       lda abs:.word0 (scLen)
              cmp ##SC_NAME_MAX
              bcs askNone
              tay
              sep #0x20
              lda dp:U_T1
              sta abs:.word0 (scName),y
              lda #0
              sta abs:.word0 (scName + 1),y
              rep #0x20
              lda ##.word0 (scName)
              sta dp:U_STR
              stz dp:U_FONT
              jsr abs:.word0 (StrWidth)
              cmp ##SC_NAME_W
              bcc askFits
              ldy abs:.word0 (scLen)         ; too wide: take the letter back
              sep #0x20
              lda #0
              sta abs:.word0 (scName),y
              rep #0x20
              bra askNone
askFits:      inc abs:.word0 (scLen)
              jsr abs:.word0 (scField)
askNone:      jmp abs:.word0 (askKey)

;;; The cursor shows for half a second, then hides for half a second.
blinkTime:    jsr abs:.word0 (UiTime)
              clc
              adc ##35
              sta abs:.word0 (scBlink)
              rts

;;; The name field: wiped, the name, and the cursor when it is on.
scField:      lda ##BOX_X + 6
              sta dp:U_X
              lda ##BOX_Y + 24
              sta dp:U_Y
              lda ##BOX_W - 12
              sta dp:U_W
              lda ##19
              sta dp:U_H
              lda ##C_BLACK
              sta dp:U_C
              jsl long:GrayRect
              lda ##.word0 (scName)
              sta dp:U_STR
              lda ##BOX_X + 12
              sta dp:U_X
              lda ##BOX_Y + 26
              sta dp:U_Y
              stz dp:U_FONT
              lda ##C_WHITE
              sta dp:U_C
              jsr abs:.word0 (DrawStr)
              lda abs:.word0 (scCursor)
              beq fieldDone
              lda ##.word0 (sCursor)
              sta dp:U_STR
              jsr abs:.word0 (DrawStr)
fieldDone:    rts

              .section menudata, data, root
nameBuf:      .space 20
scName:       .space 20
scNew:        .word 0, 0
scFloor:      .word 0
scOffset:     .word 0
scCount:      .word 0
scLen:        .word 0
scShift:      .word 0
scCaps:       .word 0
scCursor:     .word 0
scBlink:      .word 0
hName:        .asciz "NAME"
hFloor:       .asciz "FLOOR"
hScore:       .asciz "SCORE"
scoreFade:    .word 0
sHero:        .asciz "BJ Blazkowicz"
sCursor:      .asciz "_"
