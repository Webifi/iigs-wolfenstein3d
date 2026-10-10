;;; Front end: menu entry points, key input, the list menus and dialogs.
;;; MenuBoot runs once at start (title, main menu); MenuOpen runs when Esc is
;;; pressed in play. Both run in bank $3F with DBR = $3F and D = UI_DP.
#include "memmap.inc"
#include "frontend.inc"
#include "campaign.inc"
#include "logic.inc"
#include "picture_config.inc"
              .extern EnsureUIAssets, PauseWords
              .section menucode, text, root, noreorder
              .public MenuOpen, MenuBoot, MenuReturnTitle, PollKey, UiSound, GetKey, Confirm
              .public uiGameOn, benchFresh, listActiveAt, ListRun, idleVector, idleNone, listItem
              .public listValVec, listLrVec, listClean, ListResume, listValueUpdate, listValueItem
              .extern RenderPage, pageBlack
              .extern RowSelectInit, RowSelectMove, rowCacheValid, composing
              .extern BeginUpdate, BeginRecolor, EndUpdate, SetListHighlight, pageList, ListPage
              .public listItem, listCursor, listPageHook, listHookVec
              .public menuHalt, ShowNote, UiScreen, UiEnterCore, UiLeaveCore
              .extern UiGetTime, UiDrain, UiStartGame, UiResetInput, FloorMusic, SelectMusic
              .extern inputHead, inputTail, inputRing, weaponViewIndex, keyHeld
#if WOLF_PREPARED && !WOLF_TRUE_PIXELS
              .extern clearIfFull
#endif
              .extern DrawList, FillRect, DrawStr, StrWidth, DrawStrCenter
              .extern MenuDimOpen, MenuDimClose, MenuScreen, MenuFinish, GrayRect, menuDim, MenuPrepare
              .extern FlashQuiet, PalBlack, FloorToFade, RevealFloor, screenHold
              .extern PreviewHook, ListFloorColumn, ListLetterMatch, MenuFunctionKey, QuickSlotScreen, OptionsShortcut
              .extern DrawStrRight, SaveBox, RestoreBox, NumToStr, RowOffset
              .extern DiskInit, NeedHomeDisk, LoadLump, UiTime, BusyShow, BusyHide, BusyForget, StartSign, StartSignStep, busyShown
              .extern InitWords, BlackScreen, InitLettering, DrawCursorCore, FloorSelect, visitMask, bootComplete, chosenFloor, floorColumns
              .extern dlMain, dlNewGame, lumpTable, fontInfo, smallWidths
              .extern LoadSettings, SaveSlotScreen, levelState, SoundPlay, OptionsScreen
              .extern ScoreScreen, DoQuit, UiFwKeep
              .extern BootPicture, PgPage, TitleScreens, PlayTitleDemo, screenBlack

KEY_REPEAT_FIRST .equ 12
KEY_REPEAT_NEXT  .equ 4
NOKEY            .equ 0xffff
K_Y              .equ 0x10
K_N              .equ 0x2d

;;; sounds of the original list (the same numbers as wolfsound's sound_ids.inc)
MOVEGUN2SND      .equ 4
MOVEGUN1SND      .equ 5
NOWAYSND         .equ 6
SHOOTSND         .equ 32
ESCPRESSEDSND    .equ 39

;;; ---------------------------------------------------------------------------
;;; Entry points
;;; ---------------------------------------------------------------------------

;;; Esc during play. Registers and the game's direct page are the caller's.
MenuOpen:     php
              rep #0x30
              phb
              phd
              phk
              plb
              stz abs:.word0 (menuDim)
              stz abs:.word0 (benchFresh)
              jsr abs:.word0 (UiEnterCore)
              lda ##1                        ; before MenuDimOpen: this menu is the in-game pause
              sta abs:.word0 (uiGameOn)
              jsl long:MenuDimOpen
              jsr abs:.word0 (MainMenu)
              jsl long:MenuDimClose
              lda abs:.word0 (uiGameOn)
              bne openResume
              jmp abs:.word0 (bootCycle)
openResume:   jsr abs:.word0 (UiLeave)
              SCREEN_ID 0
              pld
              plb
              plp
              rtl

;;; At start, before the first view is drawn. Returns A = the view size to
;;; use (0 half, 1 two thirds, 2 three quarters, 3 full). A test latch skips the whole front end.
MenuBoot:     php
              rep #0x30
              phb
              phd
              phk
              plb
              stz abs:.word0 (bootAgain)
              bra bootEntry
MenuReturnTitle:
              php
              rep #0x30
              phb
              phd
              phk
              plb
              lda ##1
              sta abs:.word0 (bootAgain)
              lda ##0
              sta long:UI_SKIP
bootEntry:
              jsl long:EnsureUIAssets
              jsl long:InitWords
              jsl long:UiFwKeep
              jsr abs:.word0 (InitLettering)
              stz abs:.word0 (menuDim)
              stz abs:.word0 (benchFresh)
              SCREEN_ID 0
              lda long:UI_SKIP
              cmp ##UI_SKIP_MAGIC
              bne bootMenu
              lda ##0
              sta long:UI_SKIP
              lda ##1
              sta abs:.word0 (uiGameOn)
              stz abs:.word0 (bootComplete)
              jsr abs:.word0 (DiskInit)      ; a menu in a test still reads the disk
              lda ##1                        ; the view: two thirds
              bra bootDone
bootMenu:     jsr abs:.word0 (DiskInit)
              bcs bootSkip
              jsr abs:.word0 (UiEnterCore)
              jsr abs:.word0 (NeedHomeDisk)  ; the boot ends with the home disk in the drive
              stz abs:.word0 (uiGameOn)
              lda abs:.word0 (bootAgain)
              bne bootCycle
              jsr abs:.word0 (LoadSettings)
              jsr abs:.word0 (BootPicture)
              jsr abs:.word0 (PgPage)
              bcs bootGame
bootCycle:    jsr abs:.word0 (TitleScreens)
              bcs bootGame
              jsr abs:.word0 (PlayTitleDemo)
              bcc bootCycle
bootMainMenu: jsl long:MenuDimOpen
              jsr abs:.word0 (MainMenu)
              pha
              jsl long:MenuDimClose
              pla
              cmp ##1
              beq bootGame
              lda abs:.word0 (uiGameOn)      ; Back to Demo, or Back to Game for a game the benchmark made
              beq bootCycle
bootGame:     jsr abs:.word0 (UiLeave)
;;; The caller paints once. A full view still drops the latch here. A reduced
;;; view keeps it so that one setView arms the ceiling lights, and viewCutHook
;;; clears it before the next frame can paint the picture again. Same length
;;; either way: the menu code after this must not move.
#if WOLF_PREPARED && !WOLF_TRUE_PIXELS
              jsl long:clearIfFull
              .byte 0xea, 0xea, 0xea, 0xea, 0xea, 0xea
#else
              sep #0x20
              lda #0
              sta long:VIEW_LATCH
              rep #0x20
#endif
              SCREEN_ID 0
              lda long:weaponViewIndex
              lsr a
              bra bootDone
bootSkip:     lda ##1
bootDone:     pld
              plb
              plp
              rtl

;;; Take over the keys: D moves to UI_DP and the page there is saved.
UiEnterCore:  jsl long:J13Menu
              lda ##UI_DP
              tcd
              ldx ##UI_DP
              ldy ##.word0 (dpSave)
              lda ##255
              .byte 0x54, 0x3f, 0x00         ; MVN: bank 0 to bank $3F
              phk
              plb
              stz dp:UC_FIRST
              stz dp:UC_Y
              lda ##32000
              sta dp:UC_END
              lda ##200
              sta dp:UC_BOTTOM
              stz abs:.word0 (menuBindMouse)
              stz abs:.word0 (busyShown)     ; a sign of the game's load is over by now
              jsl long:UiDrain
              lda long:inputHead
              sta long:inputTail
;;; The dropped events can hold the release of the key that opened the menu (Esc
;;; held while the pause comes up). Its held mark would then stay, and J13MenuKey
;;; would drop that key's next press (Esc ignored once). No key is held from here on.
              lda ##0
              ldx ##126
enterHeld:    sta long:keyHeld,x
              dex
              dex
              bpl enterHeld
              lda ##NOKEY
              sta abs:.word0 (heldKey)
              lda ##.word0 (idleNone)
              sta abs:.word0 (idleVector)
              rts

;;; Rows use palette 0. The hardware stays black; the caller fills fadeBase
;;; and fades in, or RevealFloor publishes it at the blank.
UiScreen:     jsl long:FlashQuiet
              jsl long:PalBlack
              ldx ##198
              lda ##0
clearScb:     sta long:SHR_SCB,x
              dex
              dex
              bpl clearScb
              rts

;;; Put the page back, the keys to a clean state, and ask the game for its
;;; view again (it redraws border, status bar and picture).
UiLeave:      jsl long:FloorMusic
              jsr abs:.word0 (UiLeaveCore)
              lda long:weaponViewIndex
              lsr a
              inc a
              sep #0x20
              sta long:VIEW_LATCH
              rep #0x20
              rts

;;; The same without the redraw, for a box over the game's own screen.
UiLeaveCore:  jsr abs:.word0 (BusyForget)     ; a sign of the load stays on the screen until the game draws its own
              ldx ##.word0 (dpSave)
              ldy ##UI_DP
              lda ##255
              .byte 0x54, 0x00, 0x3f         ; MVN: bank $3F to bank 0
              phk
              plb
              jsl long:UiResetInput
              jsl long:J13Game
              rts

;;; ---------------------------------------------------------------------------
;;; Keys: ADB key events from the game's ring, with repeat for the arrows
;;; ---------------------------------------------------------------------------

              .extern J13Menu, J13Game, J13Poll, J13MenuKey
              .public PollKeyLong, MainMenuLong, menuBindMouse
PollKeyLong:  jsr abs:.word0 (PollKey)
              rtl
MainMenuLong: jsr abs:.word0 (MainMenu)
              rtl

;;; A = a raw key code or NOKEY. Mouse reports are drained without menu
;;; navigation; button presses are exposed only while binding an action.
PollKey:      jsl long:J13Poll
pollNext:     lda long:inputTail
              cmp long:inputHead
              bne pollQueued
              lda ##NOKEY
              rts
pollQueued:   tax
              lda long:inputRing + 2,x
              cmp ##1
              beq pollMouse
              lda long:inputRing + 4,x
              and ##255
              jsl long:J13MenuKey
              pha
              jsr abs:.word0 (pollAdvance)
              pla
              rts
pollMouse:    lda long:inputRing + 4,x       ; the report: bit 7 of its two bytes is 0 for a button down
              and ##0x80
              lsr a
              sta abs:.word0 (mouseNow)      ; button 0 in bit 6
              lda long:inputRing + 6,x
              and ##0x80                     ; button 1 in bit 7
              ora abs:.word0 (mouseNow)
              sta abs:.word0 (mouseNow)
              jsr abs:.word0 (pollAdvance)
              lda abs:.word0 (mouseWas)
              eor abs:.word0 (mouseNow)
              and abs:.word0 (mouseWas)      ; the buttons that went down
              pha
              lda abs:.word0 (mouseNow)
              sta abs:.word0 (mouseWas)
              pla
              ldx abs:.word0 (menuBindMouse)
              beq pollMouseNext
              bit ##0x40
              beq pollButton1
              lda ##0x7e                     ; the codes keys.s uses for the buttons
              rts
pollButton1:  bit ##0x80
              beq pollMouseNext
              lda ##0x70
              rts
pollMouseNext: jmp abs:.word0 (pollNext)
pollNone:     lda ##NOKEY
              rts
pollAdvance:  txa
              clc
              adc ##8
              and ##1023
              sta long:inputTail
              rts

;;; A = the next key going down, as a raw code 0-127. Calls the idle routine
;;; while it waits and repeats a held arrow key.
GetKey:       jsr abs:.word0 (PollKey)
              cmp ##NOKEY
              bne gotEvent
              jsr abs:.word0 (idleStub)
              lda abs:.word0 (heldKey)
              cmp ##NOKEY
              beq GetKey
              jsr abs:.word0 (UiTime)
              sec
              sbc abs:.word0 (repeatAt)
              bmi GetKey
              jsr abs:.word0 (UiTime)
              clc
              adc ##KEY_REPEAT_NEXT
              sta abs:.word0 (repeatAt)
              lda abs:.word0 (heldKey)
              rts
gotEvent:     bit ##0x80
              beq keyDown
              and ##0x7f
              cmp abs:.word0 (heldKey)
              bne GetKey
              lda ##NOKEY
              sta abs:.word0 (heldKey)
              bra GetKey
keyDown:      cmp ##K_UP
              beq startRepeat
              cmp ##K_DOWN
              beq startRepeat
              cmp ##K_LEFT
              beq startRepeat
              cmp ##K_RIGHT
              beq startRepeat
              rts
startRepeat:  sta abs:.word0 (heldKey)
              pha
              jsr abs:.word0 (UiTime)
              clc
              adc ##KEY_REPEAT_FIRST
              sta abs:.word0 (repeatAt)
              pla
              rts

idleStub:     ldx ##0
              .byte 0x7c                     ; JMP (abs,X): the vector is read in this bank
              .word .word0 (idleVector)
idleNone:     rts

;;; A = a sound from the original sound list; nothing when the sound code
;;; is not in this build.
UiSound:      jmp abs:.word0 (SoundPlay)

;;; ---------------------------------------------------------------------------
;;; List menus with the gun cursor. The caller sets the UL_* page, calls
;;; ListRun, and gets the chosen item in A, or NOKEY for Esc.
;;; ---------------------------------------------------------------------------
ListRun:      stz dp:UL_TOP
              stz dp:UL_VISIBLE
              lda dp:UL_Y
listFit:      inc dp:UL_VISIBLE
              clc
              adc dp:UL_STEP
              cmp ##181
              bcc listFit
              lda abs:.word0 (floorColumns)
              beq listFitted
              lda ##10
              sta dp:UL_VISIBLE
listFitted:   lda dp:UL_CUR
              jsr abs:.word0 (listFirstActive)
              sta dp:UL_CUR
              jsr abs:.word0 (listScroll)
              stz dp:UL_FRAME
              lda ##.word0 (listIdle)
              sta abs:.word0 (idleVector)
              jsl long:ListPage
listPageHook: lda dp:UL_HOOK
              beq listNoHook
              jsr abs:.word0 (listHookCall)
listNoHook:   jsl long:SetListHighlight
              stz abs:.word0 (listClean)
              jsr abs:.word0 (MenuFinish)
              jsr abs:.word0 (RevealFloor)
ListResume:   lda ##.word0 (listIdle)
              sta abs:.word0 (idleVector)
              jsr abs:.word0 (UiTime)
              clc
              adc ##70
              sta dp:UL_NEXT
listKey:      jsr abs:.word0 (GetKey)
              pha
              jsl long:MenuFunctionKey
              beq listOrdinaryKey
              sta abs:.word0 (uiShortcut)
              pla
              jmp abs:.word0 (listEsc)
listOrdinaryKey: pla
              cmp ##K_UP
              bne notListUp
              jmp abs:.word0 (listUp)
notListUp:
              cmp ##K_DOWN
              bne notListDown
              jmp abs:.word0 (listDown)
notListDown:
              cmp ##K_RETURN
              bne uiLong8_390
              jmp abs:.word0 (listPick)
uiLong8_390:
              cmp ##K_ENTER
              bne uiLong7_392
              jmp abs:.word0 (listPick)
uiLong7_392:
              cmp ##K_SPACE
              beq listPick
              cmp ##K_ESC
              beq listEsc
              cmp ##K_LEFT
              beq listLeft
              cmp ##K_RIGHT
              beq listRight
              jsl long:ListLetterMatch
              bcs listLetterFound
              jmp abs:.word0 (listKey)
listLetterFound: pha
              lda dp:UL_CUR
              sta abs:.word0 (listOld)
              pla
              sta dp:UL_CUR
              jmp abs:.word0 (listMoveFound)
listLeft:     lda ##0xffff
              bra listLr
listRight:    lda ##1
listLr:       ldx abs:.word0 (floorColumns)
              beq listLrValue
              sta dp:U_MORE
              lda dp:UL_CUR
              sta abs:.word0 (listOld)
              lda dp:UL_COUNT
              sta dp:U_T5
              lda dp:U_MORE
              jsl long:ListFloorColumn
              sta dp:UL_CUR
              jsr abs:.word0 (listActiveAt)
              beq listColumnSkip
              jmp abs:.word0 (listMoveFound)
listColumnSkip: jmp abs:.word0 (listStep)
listLrValue:  sta dp:U_MORE
              lda dp:UL_LRHOOK
              bne uiBranch427
              jmp abs:.word0 (listKey)
uiBranch427:
              jsr abs:.word0 (listLrCall)
              lda dp:UL_CUR
              sta dp:U_ITEM
              jsr abs:.word0 (listValueUpdate)
              jmp abs:.word0 (listKey)
listEsc:      lda ##ESCPRESSEDSND
              jsr abs:.word0 (UiSound)
              lda ##.word0 (idleNone)
              sta abs:.word0 (idleVector)
              lda ##NOKEY
              rts
listPick:     lda dp:UL_CUR
              jsr abs:.word0 (listActiveAt)
              beq listNoWay
              lda ##SHOOTSND
              jsr abs:.word0 (UiSound)
              lda ##.word0 (idleNone)
              sta abs:.word0 (idleVector)
              lda dp:UL_CUR
              rts
listNoWay:    lda ##NOWAYSND
              jsr abs:.word0 (UiSound)
              jmp abs:.word0 (listKey)
listUp:       lda ##0xffff
              bra listMove
listDown:     lda ##1
listMove:     sta dp:U_MORE
              lda dp:UL_CUR
              sta abs:.word0 (listOld)
              lda dp:UL_COUNT
              sta dp:U_T5
listStep:     lda dp:UL_CUR
              clc
              adc dp:U_MORE
              bpl listNoLow
              lda dp:UL_COUNT
              dec a
listNoLow:    cmp dp:UL_COUNT
              bcc listInRange
              lda ##0
listInRange:  sta dp:UL_CUR
              jsr abs:.word0 (listActiveAt)
              bne listMoveFound
              dec dp:U_T5
              bne listStep
              jmp abs:.word0 (listKey)
listMoveFound: lda dp:UL_CUR
              cmp abs:.word0 (listOld)
              bne listChanged
              jmp abs:.word0 (listKey)
listChanged:  jsr abs:.word0 (listScroll)
              bcc listWithinPage
              stz dp:U_ITEM
listPagePaint: jsr abs:.word0 (listItem)
              inc dp:U_ITEM
              lda dp:U_ITEM
              cmp dp:UL_COUNT
              bcc listPagePaint
              bra listCursorMoved
;;; A cursor move restores only the old and new gun rectangles. Item
;;; glyphs need repainting only when scrolling changes the page.
listWithinPage:
listCursorMoved: stz abs:.word0 (listDelta)
              stz dp:UL_FRAME
              jsr abs:.word0 (listCursor)
              lda ##MOVEGUN2SND
              jsr abs:.word0 (UiSound)
              lda dp:UL_HOOK
              beq listMoved
              jsr abs:.word0 (listHookCall)
listMoved:    jsr abs:.word0 (UiTime)
              clc
              adc ##70
              sta dp:UL_NEXT
              jmp abs:.word0 (listKey)
listHookCall: ldx ##0
              .byte 0x7c
              .word .word0 (listHookVec)
listLrCall:   ldx ##0
              .byte 0x7c
              .word .word0 (listLrVec)
listValCall:  ldx ##0
              .byte 0x7c
              .word .word0 (listValVec)

listScroll:   lda dp:UL_CUR
              cmp dp:UL_TOP
              bcc listScrollUp
              sec
              sbc dp:UL_TOP
              cmp dp:UL_VISIBLE
              bcc listScrollSame
              lda dp:UL_CUR
              sec
              sbc dp:UL_VISIBLE
              inc a
listScrollUp: sta dp:UL_TOP
              sec
              rts
listScrollSame: clc
              rts

;;; A = the first active item at or after A, else the last one before it (0 when none).
listFirstActive:
              sta dp:U_ITEM
              sta dp:U_T7
listFindActive:
              lda dp:U_ITEM
              jsr abs:.word0 (listActiveAt)
              bne listFound
              inc dp:U_ITEM
              lda dp:U_ITEM
              cmp dp:UL_COUNT
              bcc listFindActive
              lda dp:U_T7                     ; none after it: the last one before it
              sta dp:U_ITEM
listFindBack: lda dp:U_ITEM
              jsr abs:.word0 (listActiveAt)
              bne listFound
              dec dp:U_ITEM
              bpl listFindBack
              lda ##0
              rts
listFound:    lda dp:U_ITEM
              rts

;;; A = the flag of item A (0 off, 1 on, 2 special); Z set when off.
listActiveAt: clc
              adc dp:UL_ACT
              tax
              sep #0x20
              lda abs:0,x
              rep #0x20
              and ##255
              rts

ListPageItem: jsr abs:.word0 (listItem)
              rtl
ListPageCursor: jsr abs:.word0 (listCursor)
              rtl
ListPageDraw: ldx abs:.word0 (pageList)
              jsr abs:.word0 (DrawList)
              rtl
              .public ListPageItem, ListPageCursor, ListPageDraw

;;; Item U_ITEM, highlighted when it is the current one.
listItem:     lda dp:U_ITEM
              cmp dp:UL_CUR
              bne listItemPlain
              ldy ##1
              bra listItemDraw
listItemPlain:
              ldy ##0
listItemDraw: sty dp:U_T6
              lda dp:U_ITEM
              sec
              sbc dp:UL_TOP
              bcc listItemHidden
              cmp dp:UL_VISIBLE
              bcc listItemVisible
listItemHidden: rts
listItemVisible: ldy dp:U_T6
              sty dp:U_T6                     ; 1: highlighted
              lda dp:U_ITEM
              jsr abs:.word0 (listActiveAt)
              tax                             ; X = the flag
              ldy ##C_DKRED
              cpx ##0
              beq listColor
              cpx ##3
              beq listColor
              ldy ##C_WHITE
              lda dp:U_T6
              bne listColor
              ldy ##C_GRAY
              cpx ##2
              bne listColor
              ldy ##C_YELLOW
listColor:    sty dp:U_C
              lda abs:.word0 (listClean)
              beq listColorReady
              lda long:composing
              beq listColorReady
              lda abs:.word0 (listPictures)
              beq listColorReady
              cmp ##3
              bcs listColorReady
              cpy ##C_WHITE
              bne listColorReady
              lda ##C_GRAY
              sta dp:U_C
listColorReady:
              lda dp:U_ITEM
              sec
              sbc dp:UL_TOP                   ; visible row
              jsr abs:.word0 (listPosition)
              ldx dp:UL_STEP
              jsr abs:.word0 (mulSmall)
              clc
              adc dp:UL_Y
              sta dp:UL_ROWY
              lda abs:.word0 (listClean)
              bne listTextReady
              lda dp:UL_ROWX
              dec a
              and ##0xfffc
              sta dp:U_X
              lda dp:UL_ROWY
              dec a
              sta dp:U_Y
              lda dp:UL_WIDTH
              clc
              adc ##7
              and ##0xfffc
              sta dp:U_W
              lda ##10
              ldx abs:.word0 (listFont)
              beq listHeightReady
              lda ##13
              cpx ##2
              beq listHeightReady
              lda ##17
listHeightReady: sta dp:U_H
              lda abs:.word0 (listDelta)
              beq listReplace
              jsl long:BeginRecolor
              bra listTextReady
listReplace:  jsl long:BeginUpdate
listTextReady: lda dp:U_ITEM
              asl a
              clc
              adc dp:UL_ITEMS
              tax
              lda abs:0,x
              sta dp:U_STR
              lda dp:UL_ROWX
              sta dp:U_X
              lda dp:UL_ROWY
              sta dp:U_Y
              lda abs:.word0 (listFont)
              sta dp:U_FONT
              lda ##1
              ldx abs:.word0 (listPictures)
              beq listPaletteInk
              lda ##0
listPaletteInk: sta abs:.word0 (listInk)
              jsr abs:.word0 (DrawStr)
              lda dp:UL_VALHOOK
              beq listRowDone
              jsr abs:.word0 (listValCall)
listRowDone:  lda abs:.word0 (listClean)
              beq listRowInkDone
              lda long:composing
              beq listRowInkDone
              lda abs:.word0 (listPictures)
              beq listRowInkDone
              cmp ##3
              bcs listRowInkDone
              lda dp:U_ITEM
              cmp dp:UL_CUR
              bne listRowInkDone
              jsl long:RowSelectInit
listRowInkDone: stz abs:.word0 (listInk)
              lda abs:.word0 (listClean)
              bne listRowReady
              jsl long:EndUpdate
listRowReady: rts

listValueUpdate:
              lda dp:UL_CUR
              sta dp:U_ITEM
listValueItem: lda dp:U_ITEM
              sec
              sbc dp:UL_TOP
              ldx dp:UL_STEP
              jsr abs:.word0 (mulSmall)
              clc
              adc dp:UL_Y
              sta dp:UL_ROWY
              dec a
              sta dp:U_Y
              lda ##204
              sta dp:U_X
              lda ##104
              sta dp:U_W
              lda ##10
              sta dp:U_H
              jsl long:BeginUpdate
              ldy ##0
              lda dp:U_ITEM
              cmp dp:UL_CUR
              bne valueState
              iny
valueState:   sty dp:U_T6
              lda ##1
              sta abs:.word0 (listInk)
              jsr abs:.word0 (listValCall)
              stz abs:.word0 (listInk)
              jsl long:EndUpdate
              rts

;;; Only the previous gun footprint is restored; the new one is composed.
              .extern ListCursorCore
listCursor:   jsl long:ListCursorCore
              rts
ListPositionLong: jsr abs:.word0 (listPosition)
              rtl
ListMulLong:   jsr abs:.word0 (mulSmall)
              rtl
              .public ListPositionLong, ListMulLong, cursorX, cursorY

listPosition: ldx dp:UL_X
              stx dp:UL_ROWX
              ldx abs:.word0 (floorColumns)
              beq listPositionDone
              cmp ##4
              bcc listPositionDone
              sbc ##4
              ldx ##150
              stx dp:UL_ROWX
              cmp ##3
              bcc listPositionDone
              sbc ##3
              ldx ##250
              stx dp:UL_ROWX
listPositionDone: rts

;;; The gun blinks: it shows its muzzle flash for 8 tics every second.
listIdle:     jsr abs:.word0 (UiTime)
              sec
              sbc dp:UL_NEXT
              bmi idleWait
              lda dp:UL_FRAME
              eor ##1
              sta dp:UL_FRAME
              ldx ##8
              cmp ##1
              beq idleHold
              ldx ##70
idleHold:     stx dp:U_T6
              jsr abs:.word0 (UiTime)
              clc
              adc dp:U_T6
              sta dp:UL_NEXT
              jsr abs:.word0 (listCursor)
idleWait:     rts

;;; A * X for small values (X below 16): the result in A.
mulSmall:     sta dp:U_T0
              lda ##0
              cpx ##0
              beq mulSmallDone
mulSmallAdd:  clc
              adc dp:U_T0
              dex
              bne mulSmallAdd
mulSmallDone: rts

;;; ---------------------------------------------------------------------------
;;; The main menu
;;; ---------------------------------------------------------------------------
MM_NEWGAME    .equ 0
MM_LOAD       .equ 1
MM_SAVE       .equ 2
MM_OPTIONS    .equ 3
MM_SCORES     .equ 4
MM_ENDGAME    .equ 5
MM_RESUME     .equ 6
MM_QUIT       .equ 7

;;; Result: A = 0 back to the game, 1 a game was started.
;;; screenHold keeps a new game's setView from painting over this menu.
;;; The song that is playing goes on: the menu has no song of its own.
MainMenu:
              lda ##1
              sta long:screenHold
mainDraw:     lda abs:.word0 (uiShortcut)
              beq mainShow
              stz abs:.word0 (uiShortcut)
              cmp ##1
              bne uiBranch788
              jmp abs:.word0 (mainSave)
uiBranch788:
              cmp ##2
              bne uiBranch790
              jmp abs:.word0 (mainLoad)
uiBranch790:
              cmp ##6
              bne uiBranch792
              jmp abs:.word0 (mainEnd)
uiBranch792:
              cmp ##7
              beq mainQuickSave
              cmp ##8
              beq mainQuickLoad
              cmp ##9
              bne uiBranch798
              jmp abs:.word0 (mainQuit)
uiBranch798:
              jsr abs:.word0 (OptionsShortcut)
              bra mainDraw
mainQuickSave: lda ##1
              bra mainQuick
mainQuickLoad: lda ##0
mainQuick:    jsr abs:.word0 (QuickSlotScreen)
              cmp ##1
              beq mainLoaded
              cmp ##2
              bne uiBranch808
              jmp abs:.word0 (mainBack)
uiBranch808:
              bra mainDraw
mainShow:
              jsl long:PauseWords            ; the in-game pause reads the page's words
              ldx ##.word0 (dlMain)
              jsr abs:.word0 (MenuScreen)
              SCREEN_ID 2
              jsr abs:.word0 (mainSetup)
              jsr abs:.word0 (ListRun)
              cmp ##NOKEY
              beq mainEsc
              sta abs:.word0 (mainCur)
              cmp ##MM_RESUME
              beq mainEsc
              cmp ##MM_ENDGAME
              beq mainEnd
              cmp ##MM_QUIT
              beq mainQuit
              cmp ##MM_NEWGAME
              beq mainNew
              cmp ##MM_LOAD
              beq mainLoad
              cmp ##MM_SAVE
              beq mainSave
              cmp ##MM_OPTIONS
              beq mainOptions
              cmp ##MM_SCORES
              beq mainScores
mainAgain:    jmp abs:.word0 (mainDraw)
mainOptions:  jsr abs:.word0 (OptionsScreen)
              bra mainAgain
mainScores:   jsr abs:.word0 (ScoreScreen)
              bra mainAgain
mainLoad:     lda ##0
              bra mainSlots
mainSave:     lda abs:.word0 (uiGameOn)
              beq mainAgain
              lda long:levelState
              bne mainAgain
              lda ##1
mainSlots:    jsr abs:.word0 (SaveSlotScreen)
              cmp ##1
              bne mainAgain
mainLoaded:   sta abs:.word0 (uiGameOn)
              stz abs:.word0 (benchFresh)
              lda ##1
              bra mainLeave
mainEnd:      lda abs:.word0 (uiGameOn)
              beq mainAgain
              lda ##.word0 (strEndGame)
              sta dp:U_STR
              jsr abs:.word0 (Confirm)
              bcs mainAgain
              stz abs:.word0 (uiGameOn)
              bra mainBack
mainEsc:      lda abs:.word0 (uiShortcut)
              beq mainBack
              jmp abs:.word0 (mainDraw)
              bra mainBack               ; Esc returns; Quit is the menu item
mainBack:     lda ##0
mainLeave:    pha
              lda ##0
              sta long:screenHold
              pla
              rts
mainQuit:     jsr abs:.word0 (QuitConfirm)
              bra mainAgain
mainNew:      jsr abs:.word0 (NewGame)
              lda abs:.word0 (menuResult)
              beq mainAgain
              lda ##1
              bra mainLeave

mainSetup:    lda ##.word0 (sBackDemo)
              ldx abs:.word0 (uiGameOn)
              beq mainBackLabel
              lda ##.word0 (sBackGame)
mainBackLabel: sta abs:.word0 (mainItems+12)
              lda ##1
              sta abs:.word0 (listFont)
              lda ##.word0 (mainItems)
              sta dp:UL_ITEMS
              lda ##8
              sta dp:UL_COUNT
              lda ##ITEM_X
              sta dp:UL_X
              lda ##ITEM_Y
              sta dp:UL_Y
              lda ##ITEM_STEP
              sta dp:UL_STEP
              lda ##69
              sta dp:UL_CX
              lda ##.word0 (mainActive)
              sta dp:UL_ACT
              lda abs:.word0 (mainCur)
              sta dp:UL_CUR
              stz dp:UL_HOOK
              stz dp:UL_VALHOOK
              stz dp:UL_LRHOOK
              lda ##210
              sta dp:UL_WIDTH
              ; New Game starts at the title. End Game needs an active game.
              lda abs:.word0 (uiGameOn)
              sep #0x20
              sta abs:.word0 (mainActive + MM_ENDGAME)
              eor #1
              sta abs:.word0 (mainActive + MM_NEWGAME)
              rep #0x20
              lda abs:.word0 (uiGameOn)
              beq saveOff
              lda long:levelState
              beq saveOn
saveOff:      lda ##0
              bra saveSet
saveOn:       lda ##1
saveSet:      sep #0x20
              sta abs:.word0 (mainActive + MM_SAVE)
              rep #0x20
              rts

;;; ---------------------------------------------------------------------------
;;; New game: the four difficulties, with the face of the current one
;;; ---------------------------------------------------------------------------
NG_X          .equ 90
NG_Y          .equ 104
NG_FACE_X     .equ 234
NG_FACE_Y     .equ 107

              .public diffCur, menuResult
              .extern PsychedPrepare, PsychedNewGame
NewGame:      stz abs:.word0 (menuResult)
              jsl long:PsychedPrepare
newFloor:     lda abs:.word0 (uiShortcut)
              beq newFloorReady
              sec
              rts
newFloorReady: jsr abs:.word0 (FloorSelect)
              bcc newAccepted
              jmp abs:.word0 (newFail)
newAccepted:
              lda ##LUMP_NEWGAME
              jsr abs:.word0 (LoadLump)
              bcc newLumpOk
              jmp abs:.word0 (newFail)
newLumpOk:
newDraw:      ldx ##.word0 (dlNewGame)
              jsr abs:.word0 (MenuScreen)
              SCREEN_ID 3
              lda ##.word0 (diffItems)
              sta dp:UL_ITEMS
              lda ##4
              sta dp:UL_COUNT
              lda ##NG_X
              sta dp:UL_X
              lda ##NG_Y
              sta dp:UL_Y
              lda ##14
              sta dp:UL_STEP
              lda ##64
              sta dp:UL_CX
              lda ##.word0 (diffActive)
              sta dp:UL_ACT
              lda abs:.word0 (diffCur)
              sta dp:UL_CUR
              stz dp:UL_VALHOOK
              stz dp:UL_LRHOOK
              lda ##210
              sta dp:UL_WIDTH
              lda ##2
              sta abs:.word0 (listFont)
              lda ##1
              sta abs:.word0 (listPictures)
              lda ##.word0 (PreviewHook)
              sta abs:.word0 (listHookVec)
              sta dp:UL_HOOK
              jsr abs:.word0 (ListRun)
              cmp ##NOKEY
              beq newFloor
              sta abs:.word0 (diffCur)
newGo:        jsl long:PsychedNewGame
newFail:      rts

;;; ---------------------------------------------------------------------------

Dialog:       lda dp:U_STR
              sta dp:DG_START
              sta dp:DG_CUR
              stz dp:DG_MAXW
              stz dp:DG_LINES
dialogMeasure:
              jsr abs:.word0 (copyLine)
              lda ##0
              rol a
              sta dp:DG_LAST
              inc dp:DG_LINES
              lda ##.word0 (lineBuf)
              sta dp:U_STR
              stz dp:U_FONT
              jsr abs:.word0 (StrWidth)
              cmp dp:DG_MAXW
              bcc dialogNarrow
              sta dp:DG_MAXW
dialogNarrow: lda dp:DG_LAST
              beq dialogMeasure
              lda dp:DG_MAXW                  ; w = widest line + 24, even
              clc
              adc ##25
              and ##0xfffe
              sta dp:DG_W
              lda dp:DG_LINES                 ; h = 13 per line + 12
              ldx ##21
              jsr abs:.word0 (mulSmall)
              clc
              adc ##12
              sta dp:DG_H
              lda ##320
              sec
              sbc dp:DG_W
              lsr a
              and ##0xfffe
              sta dp:DG_X
              lda ##200
              sec
              sbc dp:DG_H
              lsr a
              sta dp:DG_Y
              jsl long:MenuPrepare
              lda dp:DG_START
              sta abs:.word0 (dialogSource)
              lda ##0
              sta long:pageBlack
              ldx ##.word0 (dialogText)
              jsl long:RenderPage
              jsr abs:.word0 (MenuFinish)
              rts
dialogText:   lda abs:.word0 (dialogSource)
              sta dp:DG_START
   lda dp:DG_START
              sta dp:DG_CUR
              lda dp:DG_Y
              clc
              adc ##6
              sta dp:DG_START
dialogLine:   jsr abs:.word0 (copyLine)
              lda ##0
              rol a
              sta dp:DG_LAST
              lda ##.word0 (lineBuf)
              sta dp:U_STR
              lda dp:DG_X
              clc
              adc dp:DG_W
              sec
              sbc dp:DG_X
              lsr a
              clc
              adc dp:DG_X
              sta dp:U_X
              lda dp:DG_START
              sta dp:U_Y
              stz dp:U_FONT
              lda ##C_GRAY
              sta dp:U_C
              jsr abs:.word0 (DrawStrCenter)
              lda dp:DG_START
              clc
              adc ##21
              sta dp:DG_START
              lda dp:DG_LAST
              beq dialogLine
              rts

;;; Copy the line at DG_CUR to lineBuf and move DG_CUR past it. Carry set
;;; when that was the last line.
copyLine:     ldy ##0
              stz dp:DG_WIDTH
              stz dp:DG_BREAK
copyChar:     lda (DG_CUR),y
              and ##255
              beq copyLast
              cmp ##10
              beq copyNl
              cmp ##32
              bne copyWidth
              sty dp:DG_BREAK
copyWidth:    pha
              sec
              sbc ##32
              tax
              lda abs:.word0 (smallWidths),x
              and ##255
              clc
              adc dp:DG_WIDTH
              sta dp:DG_WIDTH
              cmp ##280
              bcs copyWrap
              pla
              sep #0x20
              sta abs:.word0 (lineBuf),y
              rep #0x20
              iny
              bra copyChar
copyWrap:     pla
              lda dp:DG_BREAK
              beq copySplit
              tay
              bra copyNl
copySplit:    sep #0x20
              lda #0
              sta abs:.word0 (lineBuf),y
              rep #0x20
              bra copyAdvance
copyNl:       sep #0x20
              lda #0
              sta abs:.word0 (lineBuf),y
              rep #0x20
              iny
copyAdvance:  tya
              clc
              adc dp:DG_CUR
              sta dp:DG_CUR
              clc
              rts
copyLast:     sep #0x20
              sta abs:.word0 (lineBuf),y
              rep #0x20
              tya
              clc
              adc dp:DG_CUR
              sta dp:DG_CUR
              sec
              rts

;;; A yes or no question: carry clear for Y, set for N or Esc.
Confirm:      jsr abs:.word0 (Dialog)
confirmKey:   jsr abs:.word0 (GetKey)
              cmp ##K_Y
              beq confirmYes
              cmp ##K_N
              beq confirmNo
              cmp ##K_ESC
              bne confirmKey
confirmNo:    lda ##ESCPRESSEDSND
              jsr abs:.word0 (UiSound)
              sec
              rts
confirmYes:   clc
              rts

;;; A message and a key: the text at U_STR in a box, then any key.
ShowNote:     jsr abs:.word0 (Dialog)
noteKey:      jsr abs:.word0 (GetKey)
              rts

QuitConfirm:  lda abs:.word0 (quitIndex)
              asl a
              tax
              inc abs:.word0 (quitIndex)
              lda abs:.word0 (quitIndex)
              cmp ##9
              bcc quitIndexReady
              stz abs:.word0 (quitIndex)
quitIndexReady: lda abs:.word0 (quitPrompts),x
              sta dp:U_STR
              jsr abs:.word0 (Confirm)
              bcs quitNo
              jmp abs:.word0 (DoQuit)
quitNo:       rts

menuHalt:     rts

              .section menudata, data, root
              .public mainCur, heldKey, strCurGame, dpSave
uiGameOn:     .word 0
benchFresh:   .word 0                        ; the game is the one the benchmark started, untouched
heldKey:      .word 0xffff
              .public uiShortcut, listFont, listPictures
uiShortcut:   .word 0
listPictures: .word 0
listFont:     .word 0
menuBindMouse: .word 0
mouseNow:     .word 0xc0
mouseWas:     .word 0xc0
repeatAt:     .word 0
menuResult:   .word 0
idleVector:   .word 0
listHookVec:  .word 0
listLrVec:    .word 0
listValVec:   .word 0
mainCur:      .word 0
diffCur:      .word 2
lineBuf:      .space 96
dpSave:       .space 256
mainActive:   .byte 1, 1, 0, 1, 1, 1, 1, 1
mainItems:    .word .word0 (sNew), .word0 (sLoad), .word0 (sSave), .word0 (sOptions)
              .word .word0 (sScores), .word0 (sBack), .word0 (sBackDemo), .word0 (sQuit)
sNew:         .asciz "New Game"
sLoad:        .asciz "Load Game"
sSave:        .asciz "Save Game"
sOptions:     .asciz "Options"
sScores:      .asciz "High Scores"
sBack:        .asciz "End Game"
sBackGame:    .asciz "Back to Game"
sBackDemo:    .asciz "Back to Demo"
sQuit:        .asciz "Quit"
diffActive:   .byte 1, 1, 1, 1
diffItems:    .word .word0 (sDaddy), .word0 (sHurt), .word0 (sBring), .word0 (sDeath)
sDaddy:       .asciz "Can I play, Daddy?"
sHurt:        .asciz "Don't hurt me."
sBring:       .asciz "Bring 'em on!"
sDeath:       .asciz "I am Death incarnate!"
strCurGame:   .asciz "You are in a game.\nStart a new game?\nY / N"
strEndGame:   .asciz "End this game?\nY / N"
quitText:     .asciz "Quit Wolfenstein 3-D?\nY / N"

              .section menudata, data, root
bootAgain:    .word 0
listClean:    .word 0

              .section menudata, data, root
listOld: .word 0
cursorX: .word 0
cursorY: .word 0

              .public listDelta
listDelta: .word 0

              .public listInk
listInk: .word 0

dialogSource: .word 0

              .section menudata, data, root
quitIndex: .word 0
quitPrompts: .word .word0 (quitPrompt0), .word0 (quitPrompt1), .word0 (quitPrompt2), .word0 (quitPrompt3), .word0 (quitPrompt4), .word0 (quitPrompt5), .word0 (quitPrompt6), .word0 (quitPrompt7), .word0 (quitPrompt8)
quitPrompt0: .asciz "Dost thou wish to\nleave with such hasty\nabandon?\nY / N"
quitPrompt1: .asciz "Chickening out...\nalready?\nY / N"
quitPrompt2: .asciz "Press N for more carnage.\nPress Y to be a weenie.\nY / N"
quitPrompt3: .asciz "So, you think you can\nquit this easily, huh?\nY / N"
quitPrompt4: .asciz "Press N to save the world.\nPress Y to abandon it in\nits hour of need.\nY / N"
quitPrompt5: .asciz "Press N if you are brave.\nPress Y to cower in shame.\nY / N"
quitPrompt6: .asciz "Heroes, press N.\nWimps, press Y.\nY / N"
quitPrompt7: .asciz "You are at an intersection.\nA sign says, 'Press Y to quit.'\n>\nY / N"
quitPrompt8: .asciz "For guns and glory, press N.\nFor work and worry, press Y.\nY / N"

;;; X selects a near menu helper; DBR=$3F and A/X/Y are 16 bits.
              .section menucode, text, root, noreorder
              .public DebugUiCall
DebugUiCall:  jsr (abs:.word0 (debugUiTable),x)
              rtl
debugUiTable:.word .word0 UiEnterCore, .word0 UiLeave
              .word .word0 Dialog, .word0 GetKey, .word0 DoQuit, .word0 UiLeaveCore
