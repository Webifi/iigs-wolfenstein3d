#include "memmap.inc"
#include "campaign.inc"
;;; Settings image and saved games. WOLF.SETTINGS lives in RAM at SETTINGS_IN
;;; (bank 0) as the loader read it; a slot is the 32-byte summary. The world
;;; itself is WOLF.SAVE0-7 on the home disk (gamesave.s). The disk is written only
;;; for Save Settings or a saved game. The slot lines are the settings image
;;; already in memory, so opening this screen asks for no disk.
#include "frontend.inc"
#include "logic.inc"
              .section menucode, text, root, noreorder
              .public LoadSettings, SaveSlotScreen, SlotUsed, CaptureSlot, RestoreSlot
              .public SettingsSum, CollectSettings, ApplySettings, settingsKnown, SettingsSumAll, OutStr
              .extern ExtCheck
              .extern VsyncLoad, VsyncStore, TransparencyLoad, TransparencyStore
              .public slotNameBuf
              .extern AskSlotName, ListPage, MenuFinish
              .public slotCur, editorName, nameLine, nameLen, nameShift, nameCaps, nameCursor
              .public NamePollKey, NameOutStr, NameDrawStr, NameStrWidth
              .extern SlotCount, SlotName, SlotNameStore, SlotQuick, SlotQuickSet
              .extern BeginUpdate, EndUpdate, StrWidth, PollKey, listInk, adbPlain, adbShift
              .extern ListRun, DrawList, GetKey, Confirm, LoadLump, UiSound, NumToStr, MenuScreen
              .extern UiStartSavedFloor, UiPublishGame, UiTime, DrawStr, FillRect, listActiveAt, StartSign, StartSignStep, BusyHide
              .extern Num32ToStr, WriteSettings, ShowNote, DefaultScores, ViewApply, ViewCollect
              .extern SaveWorld, LoadWorldRead, LoadWorldApply, gsLoadNoted
              .extern dlLoad, dlSave, uiGameOn, visitMask, MarkFloorVisited
              .extern progressExtra, IsFloppy
              .extern levelIndex
              .extern PlayCacheLeave, floorReady
              .extern LoadVisitedFloors, StoreVisitedFloors
              .extern hudDirty, levelState
              .extern columnLight, mouseWalk, mouseSensitivity, weaponViewIndex
              .extern MouseSettingsLoad, MouseSettingsStore, j13Enabled, j13Available
              .extern ControlsApply, ControlsCollect, ControlsDefaults
              .extern SoundRecordLoad, SoundRecordStore, SoundLevels

NOKEY         .equ 0xffff
SOUND_NOWAY   .equ 6
SOUND_SHOOT   .equ 32

;;; ---------------------------------------------------------------------------
;;; The settings image
;;; ---------------------------------------------------------------------------

;;; Validate the image the loader left; without a valid one, make the defaults
;;; (in RAM only: nothing is written to the disk) and clear the slots.
LoadSettings: ldx ##0
              lda ##0
loadMagic:    sep #0x20
              lda long:SETTINGS_IN,x
              cmp abs:.word0 (magic),x
              rep #0x20
              bne settingsNew
              inx
              cpx ##8
              bcc loadMagic
              jsr abs:.word0 (SettingsSumAll)
              cmp long:SETTINGS_IN + S_SUM
              bne settingsNew
              jsr abs:.word0 (ApplySettings)
              jsr abs:.word0 (SettingsSum)
              sta abs:.word0 (settingsKnown)
              jsl long:ExtCheck
              rts
settingsNew:  ldx ##0                       ; the bytes the front end owns: clear
              lda ##0
newClear:     sta long:SETTINGS_IN,x
              inx
              inx
              cpx ##496
              bcc newClear
              ldx ##0
newMagic:     sep #0x20
              lda abs:.word0 (magic),x
              sta long:SETTINGS_IN,x
              rep #0x20
              inx
              cpx ##8
              bcc newMagic
              sep #0x20
              lda #S_VIEW_NOTSET
              sta long:SETTINGS_IN + S_VIEW
              lda #S_PAINT_NOTSET
              sta long:SETTINGS_IN + S_DRAW_BUFFER
              sta long:SETTINGS_IN + S_FAST_WALLS
              lda #1
              sta long:SETTINGS_IN + S_SHADE
              sta long:SETTINGS_IN + S_MWALK
              sta long:SETTINGS_IN + S_FAST_TRANSPARENCY
              lda #4
              sta long:SETTINGS_IN + S_MSPEED
              rep #0x20
              jsr abs:.word0 (ControlsDefaults)
              jsr abs:.word0 (ControlsCollect)
              jsr abs:.word0 (DefaultScores)
              jsr abs:.word0 (ApplySettings)
              jsr abs:.word0 (SettingsSum)
              sta abs:.word0 (settingsKnown)
              jsl long:ExtCheck
              rts

;;; The settings bytes (view to the key codes) as the game uses them.
ApplySettings:
              jsl long:LoadVisitedFloors
              jsl long:ViewApply             ; the size of the file, or the one that the speed test chooses
              sta long:weaponViewIndex
              sep #0x20
              lda long:SETTINGS_IN + S_SHADE
              and #1
              rep #0x20
              and ##255
              sta long:columnLight
              sep #0x20
              lda long:SETTINGS_IN + S_MWALK
              and #1
              rep #0x20
              and ##255
              sta long:mouseWalk
              jsl long:VsyncLoad
              jsl long:TransparencyLoad
              jsl long:MouseSettingsLoad
              jsr abs:.word0 (ControlsApply)
              jmp abs:.word0 (SoundRecordLoad)

;;; Put the settings the game holds back into the image.
CollectSettings:
              jsl long:StoreVisitedFloors
              jsl long:ViewCollect           ; the size: "not set" stays so until the player picks one
              lda long:columnLight
              and ##1
              sep #0x20
              sta long:SETTINGS_IN + S_SHADE
              rep #0x20
              lda long:mouseWalk
              sep #0x20
              sta long:SETTINGS_IN + S_MWALK
              rep #0x20
              jsl long:VsyncStore
              jsl long:TransparencyStore
              jsl long:MouseSettingsStore
              jsr abs:.word0 (ControlsCollect)
              jmp abs:.word0 (SoundRecordStore)

;;; A = the sum of the settings and high score bytes 12-231 and the sound levels (what
;;; Save Settings changes). A saved game writes itself.
SettingsSum:  jsr abs:.word0 (CollectSettings)
              ldx ##12
              stz dp:U_T0
sumSettings:  sep #0x20
              lda long:SETTINGS_IN,x
              rep #0x20
              and ##255
              clc
              adc dp:U_T0
              sta dp:U_T0
              inx
              cpx ##S_SLOTS
              bcc sumSettings
              jsr abs:.word0 (SoundLevels)
              clc
              adc dp:U_T0
              rts

;;; The checksum stored at S_SUM: the sum of the bytes 12-495.
SettingsSumAll:
              ldx ##12
              stz dp:U_T0
sumAll:       sep #0x20
              lda long:SETTINGS_IN,x
              rep #0x20
              and ##255
              clc
              adc dp:U_T0
              sta dp:U_T0
              inx
              cpx ##496
              bcc sumAll
              lda dp:U_T0
              rts

;;; ---------------------------------------------------------------------------
;;; Saved games
;;; ---------------------------------------------------------------------------

;;; Z clear when slot A has a game that checks out.
SlotUsed:     jsr abs:.word0 (SlotBase)
              lda long:SETTINGS_IN + S_SLOTS + SL_USED,x
              cmp ##1
              bne slotNo
              jsr abs:.word0 (SlotSum)
              cmp long:SETTINGS_IN + S_SLOTS + SL_CHECK,x
              bne slotNo
              lda ##1
              rts
slotNo:       lda ##0
              rts

;;; X = the offset of slot A in the settings image (relative to S_SLOTS).
SlotBase:     asl a
              asl a
              asl a
              asl a
              asl a
              tax
              rts

;;; A = the sum of the words at SL_USED to SL_TREAS of the slot at X.
SlotSum:      phx
              ldy ##0
              lda ##0
slotWord:     clc
              adc long:SETTINGS_IN + S_SLOTS,x
              inx
              inx
              iny
              iny
              cpy ##SL_CHECK
              bcc slotWord
              plx
              rts

;;; The game now, as slot A.
CaptureSlot:  jsr abs:.word0 (SlotBase)
              lda ##1
              sta long:SETTINGS_IN + S_SLOTS + SL_USED,x
              lda long:LOGIC_BASE+V_difficulty
              sta long:SETTINGS_IN + S_SLOTS + SL_SKILL,x
              lda long:levelIndex
              sta long:SETTINGS_IN + S_SLOTS + SL_FLOOR,x
              lda long:LOGIC_BASE+V_lives
              sta long:SETTINGS_IN + S_SLOTS + SL_LIVES,x
              lda long:LOGIC_BASE+V_health
              sta long:SETTINGS_IN + S_SLOTS + SL_HEALTH,x
              lda long:LOGIC_BASE+V_ammo
              sta long:SETTINGS_IN + S_SLOTS + SL_AMMO,x
              lda long:LOGIC_BASE+V_bestweapon
              sta long:SETTINGS_IN + S_SLOTS + SL_BEST,x
              lda long:LOGIC_BASE+V_chosenweapon
              sta long:SETTINGS_IN + S_SLOTS + SL_CHOSEN,x
              lda long:LOGIC_BASE+V_weapon
              sta long:SETTINGS_IN + S_SLOTS + SL_WEAPON,x
              lda long:LOGIC_BASE+V_score
              sta long:SETTINGS_IN + S_SLOTS + SL_SCORE,x
              lda long:LOGIC_BASE+V_score + 2
              sta long:SETTINGS_IN + S_SLOTS + SL_SCORE + 2,x
              lda long:LOGIC_BASE+V_nextextra
              sta long:SETTINGS_IN + S_SLOTS + SL_EXTRA,x
              lda long:LOGIC_BASE+V_nextextra + 2
              sta long:SETTINGS_IN + S_SLOTS + SL_EXTRA + 2,x
              lda long:LOGIC_BASE+V_killcount
              sta long:SETTINGS_IN + S_SLOTS + SL_KILLS,x
              lda long:LOGIC_BASE+V_treasurecount
              sta long:SETTINGS_IN + S_SLOTS + SL_TREAS,x
              jsr abs:.word0 (SlotSum)
              sta long:SETTINGS_IN + S_SLOTS + SL_CHECK,x
              rts

;;; The saved words must precede StartFloor so its oldscore is the saved score.
;;; The world file is read first, from the home disk (in the drive at the title), then
;;; StartFloor reads the floor's disks and the world goes in from RAM: two disk
;;; changes on one drive. Carry set when the floor is not in this build, or the
;;; world could not be read (gsLoadNoted: the note is already on screen).
;;; In play, the play cache gets back the slots the floor's art took (PlayCacheLeave)
;;; before the file is read, while that floor's disk is still in the drive: the load
;;; then asks only for the home disk and the next floor's disks. When the file then
;;; cannot be read, the game in play ends (its floor art is gone), as End Game does.
RestoreSlot:  stz abs:.word0 (gsLoadNoted)
              jsr abs:.word0 (SlotBase)
              lda long:SETTINGS_IN + S_SLOTS + SL_FLOOR,x
              cmp ##CAMPAIGN_FLOORS
              bcc restoreValid
              sec
              rts
restoreValid: phx
              lda long:floorReady
              sta abs:.word0 (restoreArt)
              lda long:SETTINGS_IN + S_SLOTS + SL_FLOOR,x
              jsl long:PlayCacheLeave
              lda long:floorReady
              eor abs:.word0 (restoreArt)  ; not 0: the floor in play gave its art slots back
              sta abs:.word0 (restoreArt)
              jsr abs:.word0 (IsFloppy)
              lda ##400
              bcc restoreBudget
              lda ##1400
restoreBudget:sta abs:.word0 (progressExtra)
              lda 1,s
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              jsl long:LoadWorldRead
              plx
              bcc restoreRead
              lda abs:.word0 (restoreArt)
              beq restoreKept
              lda ##0
              sta long:uiGameOn            ; End Game: no floor to go back to
restoreKept:
              jmp abs:.word0 (restoreWorld)
restoreRead:  lda long:SETTINGS_IN + S_SLOTS + SL_SKILL,x
              sta long:LOGIC_BASE+V_difficulty
              lda long:SETTINGS_IN + S_SLOTS + SL_LIVES,x
              sta long:LOGIC_BASE+V_lives
              lda long:SETTINGS_IN + S_SLOTS + SL_HEALTH,x
              sta long:LOGIC_BASE+V_health
              lda long:SETTINGS_IN + S_SLOTS + SL_AMMO,x
              sta long:LOGIC_BASE+V_ammo
              lda long:SETTINGS_IN + S_SLOTS + SL_BEST,x
              sta long:LOGIC_BASE+V_bestweapon
              lda long:SETTINGS_IN + S_SLOTS + SL_CHOSEN,x
              sta long:LOGIC_BASE+V_chosenweapon
              lda long:SETTINGS_IN + S_SLOTS + SL_WEAPON,x
              sta long:LOGIC_BASE+V_weapon
              lda long:SETTINGS_IN + S_SLOTS + SL_SCORE,x
              sta long:LOGIC_BASE+V_score
              lda long:SETTINGS_IN + S_SLOTS + SL_SCORE + 2,x
              sta long:LOGIC_BASE+V_score + 2
              lda long:SETTINGS_IN + S_SLOTS + SL_EXTRA,x
              sta long:LOGIC_BASE+V_nextextra
              lda long:SETTINGS_IN + S_SLOTS + SL_EXTRA + 2,x
              sta long:LOGIC_BASE+V_nextextra + 2
              lda long:SETTINGS_IN + S_SLOTS + SL_KILLS,x
              sta long:LOGIC_BASE+V_killcount
              lda long:SETTINGS_IN + S_SLOTS + SL_TREAS,x
              sta long:LOGIC_BASE+V_treasurecount
              phx
              lda long:SETTINGS_IN + S_SLOTS + SL_FLOOR,x
              tax                           ; the sign for that floor (A stays the floor)
              jsr abs:.word0 (StartSign)
              jsl long:UiStartSavedFloor
              plx
              bcs restoreFloor
              jsl long:LoadWorldApply
              bcs restoreWorld
              stz abs:.word0 (progressExtra)
              lda ##2
              jsr abs:.word0 (StartSignStep)
              lda ##1
              sta long:hudDirty
              jsl long:UiPublishGame
              jsl long:MarkFloorVisited
              clc
              rts
restoreWorld: jsr abs:.word0 (BusyHide)
              sec
              rts
restoreFloor: jsr abs:.word0 (BusyHide)
              sec
              rts

;;; ---------------------------------------------------------------------------
;;; The Load Game and Save Game screens. A = 0 load, 1 save. Result in
;;; slotResult: 1 when a game was loaded or saved.
;;; ---------------------------------------------------------------------------
SLOT_TEXT     .equ 32
LS_X          .equ 40
LS_Y          .equ 48
LS_CX         .equ 12

SaveSlotScreen:
              sta abs:.word0 (slotMode)
              lda abs:.word0 (slotMode)
              bne slotLoadSave
              lda ##LUMP_LOAD
              bra slotLump
slotLoadSave: lda ##LUMP_SAVE
slotLump:     jsr abs:.word0 (LoadLump)
slotDraw:     ldx ##.word0 (dlLoad)
              lda abs:.word0 (slotMode)
              beq slotBack
              ldx ##.word0 (dlSave)
slotBack:     jsr abs:.word0 (MenuScreen)
              SCREEN_ID 4
slotList:     jsr abs:.word0 (BuildSlotTexts)
              lda ##.word0 (slotPtrs)
              sta dp:UL_ITEMS
              jsl long:SlotCount
              sta dp:UL_COUNT
              lda ##LS_X
              sta dp:UL_X
              lda ##LS_Y
              sta dp:UL_Y
              lda ##15
              sta dp:UL_STEP
              lda ##LS_CX
              sta dp:UL_CX
              lda ##.word0 (slotActive)
              sta dp:UL_ACT
              lda abs:.word0 (slotCur)
              sta dp:UL_CUR
              stz dp:UL_HOOK
              stz dp:UL_VALHOOK
              stz dp:UL_LRHOOK
              lda ##272
              sta dp:UL_WIDTH
              jsr abs:.word0 (ListRun)
              cmp ##NOKEY
              bne slotChosen
              jmp abs:.word0 (slotLeave)
slotChosen:   sta abs:.word0 (slotCur)
              ldx abs:.word0 (slotMode)
              bne slotSave
              jsr abs:.word0 (RestoreSlot)
              bcs slotFailed
              lda abs:.word0 (slotCur)
              jsl long:SlotQuickSet
              lda ##1
              rts
slotFailed:   lda abs:.word0 (gsLoadNoted)
              bne slotRedraw
              jmp abs:.word0 (slotNoFloor)
slotRedraw:   jmp abs:.word0 (slotDraw)
slotNoFloor:  lda ##.word0 (strNoFloor)
              sta dp:U_STR
              jsr abs:.word0 (ShowNote)
              jmp abs:.word0 (slotDraw)
slotSave:     lda abs:.word0 (slotCur)
              jsr abs:.word0 (SlotUsed)
              beq slotAskNew
              lda ##.word0 (strOverwrite)
              sta dp:U_STR
              jsr abs:.word0 (Confirm)
              bcc slotAskOld
              jmp abs:.word0 (slotDraw)
slotAskNew:   jsl long:AskSlotName
              bcs slotSaveBack
              lda abs:.word0 (slotCur)
              jsr abs:.word0 (SaveWorld)
              bcs slotSaveFail
              jsr abs:.word0 (slotCommit)
              jmp abs:.word0 (slotList)
slotAskOld:   ldx ##.word0 (dlSave)
              jsr abs:.word0 (MenuScreen)
              jsl long:ListPage
              jsr abs:.word0 (MenuFinish)
              jsl long:AskSlotName
              bcs slotSaveBack
              lda abs:.word0 (slotCur)
              jsr abs:.word0 (SaveWorld)
              bcs slotSaveFail
              jsr abs:.word0 (slotCommit)
              jmp abs:.word0 (slotDraw)       ; the question box covered the list
slotSaveBack: jmp abs:.word0 (slotDraw)
slotSaveFail: jmp abs:.word0 (slotDraw)

;;; The name is stored only after the world is on the disk.
slotCommit:   ldx ##.word0 (editorName)
              lda abs:.word0 (slotCur)
              jsl long:SlotNameStore
              lda abs:.word0 (slotCur)
              jsr abs:.word0 (CaptureSlot)
              lda abs:.word0 (slotCur)
              jsl long:SlotQuickSet
              jmp abs:.word0 (WriteSettings)
slotLeave:    lda ##0
              rts

;;; slotPtrs, slotActive and the text of each slot from the slot records.
BuildSlotTexts:
              stz dp:U_ITEM
buildSlot:    lda dp:U_ITEM
              jsr abs:.word0 (SlotUsed)
              sta dp:U_T6
              lda dp:U_ITEM
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc ##.word0 (slotText)
              sta dp:U_OUT
              lda dp:U_ITEM
              asl a
              tax
              lda dp:U_OUT
              sta abs:.word0 (slotPtrs),x
              lda dp:U_T6
              beq buildSlotLabel
              lda dp:U_ITEM
              jsl long:SlotName
              cmp ##0
              beq buildSlotLabel
              lda ##.word0 (slotNameBuf)
              sta dp:U_STR
              jsr abs:.word0 (OutStr)
              lda ##1
              jmp abs:.word0 (buildFlag)
buildSlotLabel:
              lda dp:U_ITEM
              inc a
              jsr abs:.word0 (NumToStr)
              jsr abs:.word0 (OutStr)
              lda ##.word0 (strGap)
              sta dp:U_STR
              jsr abs:.word0 (OutStr)
              lda dp:U_T6
              bne buildUsed
              lda ##.word0 (strEmpty)
              sta dp:U_STR
              jsr abs:.word0 (OutStr)
              lda abs:.word0 (slotMode)
              bne buildActive
              lda ##0
              bra buildFlag
buildActive:  lda ##1
              bra buildFlag
buildUsed:    lda dp:U_ITEM
              jsr abs:.word0 (SlotBase)
              stx dp:U_T5
              lda ##.word0 (strFloor)
              sta dp:U_STR
              jsr abs:.word0 (OutStr)
              ldx dp:U_T5
              lda long:SETTINGS_IN + S_SLOTS + SL_FLOOR,x
              inc a
              jsr abs:.word0 (NumToStr)
              jsr abs:.word0 (OutStr)
              lda ##.word0 (strGap)
              sta dp:U_STR
              jsr abs:.word0 (OutStr)
              ldx dp:U_T5
              lda long:SETTINGS_IN + S_SLOTS + SL_SKILL,x
              and ##3
              asl a
              tax
              lda abs:.word0 (skillNames),x
              sta dp:U_STR
              jsr abs:.word0 (OutStr)
              lda ##1
buildFlag:    sta dp:U_T6
              lda dp:U_ITEM
              tax
              sep #0x20
              lda dp:U_T6
              sta abs:.word0 (slotActive),x
              rep #0x20
              inc dp:U_ITEM
              lda dp:U_ITEM
              cmp ##SLOTS
              bcs buildEnd
              jmp abs:.word0 (buildSlot)
buildEnd:     rts

;;; Append the string at U_STR to the text at U_OUT: U_OUT moves to the zero.
OutStr:       ldy ##0
outChar:      sep #0x20
              lda (U_STR),y
              sta (U_OUT),y
              beq outDone
              iny
              rep #0x20
              bra outChar
outDone:      rep #0x20
              tya
              clc
              adc dp:U_OUT
              sta dp:U_OUT
              rts

              .public QuickSlotScreen
QuickSlotScreen:
              sta abs:.word0 (slotMode)
              beq quickSlot
              lda abs:.word0 (uiGameOn)
              beq quickFailed
              lda long:levelState
              bne quickFailed
quickSlot:    jsl long:SlotQuick
              cmp ##SLOTS
              bcs quickOpen
              sta abs:.word0 (slotCur)
              jsr abs:.word0 (SlotUsed)
              beq quickOpen
              lda abs:.word0 (slotCur)
              ldx abs:.word0 (slotMode)
              beq quickLoad
              jsr abs:.word0 (SaveWorld)
              bcs quickFailed
              lda abs:.word0 (slotCur)
              jsr abs:.word0 (CaptureSlot)
              jsr abs:.word0 (WriteSettings)
              bcs quickFailed
              lda ##2
              rts
quickLoad:    jsr abs:.word0 (RestoreSlot)
              bcs quickFailed
              lda ##1
              rts
quickOpen:    lda abs:.word0 (slotMode)
              jmp abs:.word0 (SaveSlotScreen)
quickFailed:  lda ##0
              rts

NamePollKey:  jsr abs:.word0 (PollKey)
              rtl
NameOutStr:   jsr abs:.word0 (OutStr)
              rtl
NameDrawStr:  jsr abs:.word0 (DrawStr)
              rtl
NameStrWidth: jsr abs:.word0 (StrWidth)
              rtl

              .section menudata, data, root
settingsKnown: .word 0
restoreArt:   .word 0                     ; RestoreSlot: the refill took the floor's art
slotMode:     .word 0
slotCur:      .word 0
slotActive:   .space 8
slotPtrs:     .space 16
slotText:     .space SLOT_TEXT * SLOTS
slotNameBuf:  .space 32
editorName:     .space 32
nameLine:     .space 33
nameLen:      .word 0
nameShift:    .word 0
nameCaps:     .word 0
nameCursor:   .asciz "_"
magic:        .ascii "WOLFSET"
              .byte 2
strEmpty:     .asciz "- empty -"
strFloor:     .asciz "Floor "
strGap:       .asciz "  "
strOverwrite: .asciz "Overwrite this game?\nPress Y or N."
strNoFloor:   .asciz "That floor is not\nin this build."
skillNames:   .word .word0 (sBaby), .word0 (sEasy), .word0 (sNormal), .word0 (sHard)
sBaby:        .asciz "Baby"
sEasy:        .asciz "Easy"
sNormal:      .asciz "Normal"
sHard:        .asciz "Hard"
