;;; Options callbacks apply values immediately and refresh their row displays.
;;; Controls and Benchmark delegate to separate screens. The save action is
;;; enabled when SettingsSum differs from the stored settings checksum.
#include "frontend.inc"
#include "campaign.inc"
#include "logic.inc"
              .section menucode, text, root, noreorder
              .public OptionsScreen, viewNames, OptionsShortcut
              .extern uiShortcut
              .extern ListResume, listValueUpdate, ListRun, DrawList, GetKey, LoadLump, UiSound, FillRect, StrWidth, MenuScreen, GrayRect
              .extern DrawStr, DrawStrRight, listActiveAt, UiTime, UiMul16, UiDiv16
              .extern idleNone, dlOptions, SettingsSum, settingsKnown, WriteSettings, listValVec, listLrVec
              .extern columnLight, mouseWalk, mouseSensitivity, weaponViewIndex
              .extern listDelta
              .extern listItem, SoundPresent, SoundVolGet, SoundVolSet, MusicVolGet, MusicVolSet
              .extern ControlsScreen, BenchScreen, j13Enabled, j13Available, J13Toggle
              .extern VsyncToggle, vsyncOn, BufferToggle, bufferOn, BufferChangeView, BufferOptionValue

              .extern fastTransparencyOn, TransparencyToggle
              .extern PaintingToggle, WallPaintToggle, wallPaintOn

NOKEY         .equ 0xffff
OP_COUNT      .equ 12
OP_X          .equ 42                       ; labels
OP_Y          .equ 44
OP_STEP_DISPLAY .equ 12                     ; Display & Sound has no picture below its rows
OP_CX         .equ 12                       ; the gun
OP_VALUE_X    .equ 288                      ; right edge of the values
OP_BAR_X      .equ 218                      ; sliders
OP_BAR_W      .equ 64
SELECTITEMSND .equ 2

OP_SOUND      .equ 0
OP_MUSIC      .equ 1
OP_VIEW       .equ 2
OP_SHADE      .equ 3
OP_VSYNC      .equ 4
OP_BUFFER     .equ 5
OP_WALLS      .equ 6
OP_TRANSPARENCY .equ 7
OP_MWALK      .equ 8
OP_MSPEED     .equ 9
OP_J13        .equ 10
OP_CONTROLS   .equ 11

OptionsScreen:
rootDraw:     lda abs:.word0 (uiShortcut)
              beq rootReady
              rts
rootReady:    lda ##LUMP_MAIN
              jsr abs:.word0 (LoadLump)
              ldx ##.word0 (dlOptions)
              jsr abs:.word0 (MenuScreen)
rootList:     jsr abs:.word0 (SettingsSum)
              cmp abs:.word0 (settingsKnown)
              beq rootClean
              lda ##1
              bra rootChanged
rootClean:    lda ##3
rootChanged:  sep #0x20
              sta abs:.word0 (rootActive+3)
              rep #0x20
              lda ##.word0 (rootItems)
              sta dp:UL_ITEMS
              lda ##4
              sta dp:UL_COUNT
              lda ##60
              sta dp:UL_X
              lda ##66
              sta dp:UL_Y
              lda ##27
              sta dp:UL_STEP
              lda ##30
              sta dp:UL_CX
              lda ##.word0 (rootActive)
              sta dp:UL_ACT
              lda abs:.word0 (rootCur)
              sta dp:UL_CUR
              lda ##252
              sta dp:UL_WIDTH
              stz dp:UL_HOOK
              stz dp:UL_VALHOOK
              stz dp:UL_LRHOOK
              SCREEN_ID 7
              jsr abs:.word0 (ListRun)
              cmp ##NOKEY
              beq optionsDone
              sta abs:.word0 (rootCur)
              cmp ##3
              beq rootSave
              cmp ##2
              beq rootBench
              cmp ##1
              beq rootControl
              stz abs:.word0 (optBase)
              lda ##8
              sta abs:.word0 (optCount)
              lda ##LUMP_OPTIONS
              bra rootPage
rootControl:  lda ##OP_MWALK
              sta abs:.word0 (optBase)
              lda ##4
              sta abs:.word0 (optCount)
              lda ##LUMP_CONTROLTOP
rootPage:     jsr abs:.word0 (LoadLump)
              stz abs:.word0 (optCur)
              jsr abs:.word0 (settingsPage)
              jmp abs:.word0 (rootDraw)
rootSave:     jsr abs:.word0 (WriteSettings)
              jmp abs:.word0 (rootDraw)
rootBench:    jsr abs:.word0 (BenchScreen)
              jmp abs:.word0 (rootDraw)
optionsDone:  rts
settingsPage: lda abs:.word0 (uiShortcut)
              beq settingsReady
              rts
settingsReady: ldx ##.word0 (dlOptions)
              jsr abs:.word0 (MenuScreen)
              lda abs:.word0 (optBase)
              bne controlsPageId
              SCREEN_ID 17
              bra optionsList
controlsPageId:
              lda long:j13Available
              sep #0x20
              sta abs:.word0 (optActive + OP_J13)
              rep #0x20
              SCREEN_ID 18
optionsList:  lda abs:.word0 (optBase)
              asl a
              clc
              adc ##.word0 (optItems)
              sta dp:UL_ITEMS
              lda abs:.word0 (optCount)
              sta dp:UL_COUNT
              lda ##OP_X
              sta dp:UL_X
              lda ##OP_Y
              sta dp:UL_Y
              lda abs:.word0 (optBase)
              beq optionsWide
              lda ##8
              bra optionsStep
optionsWide:  lda ##OP_STEP_DISPLAY
optionsStep:  sta dp:UL_STEP
              lda ##OP_CX
              sta dp:UL_CX
              lda ##.word0 (optActive)
              clc
              adc abs:.word0 (optBase)
              sta dp:UL_ACT
              lda abs:.word0 (optCur)
              sta dp:UL_CUR
              stz dp:UL_HOOK
              lda ##180
              sta dp:UL_WIDTH
              lda ##.word0 (optValue)
              sta dp:UL_VALHOOK
              sta abs:.word0 (listValVec)
              lda ##.word0 (optChange)
              sta dp:UL_LRHOOK
              sta abs:.word0 (listLrVec)
              jsr abs:.word0 (ListRun)
optionsPicked: cmp ##NOKEY
              bne optionsHavePick
              rts
optionsHavePick:
              sta abs:.word0 (optCur)
              clc
              adc abs:.word0 (optBase)
              cmp ##OP_CONTROLS
              beq optionsKeys
              lda ##1
              sta dp:U_MORE
              jsr abs:.word0 (optChange)
              jsr abs:.word0 (listValueUpdate)
              jsr abs:.word0 (ListResume)
              bra optionsPicked
optionsKeys:  jsr abs:.word0 (ControlsScreen)
              lda ##LUMP_CONTROLTOP
              jsr abs:.word0 (LoadLump)
              jmp abs:.word0 (settingsPage)

;;; Draw the value of row U_ITEM at y = UL_ROWY. U_T6 holds 1 when the row
;;; is the current one.
optValue:     lda dp:U_ITEM
              clc
              adc abs:.word0 (optBase)
              sta abs:.word0 (optIndex)
              ldx ##C_GRAY
              lda dp:U_T6
              beq optValueColor
              ldx ##C_WHITE
optValueColor: stx dp:U_C
              lda dp:UL_ROWY
              sta dp:U_Y
              stz dp:U_FONT
              lda abs:.word0 (optIndex)
              cmp ##OP_CONTROLS
              bcc optValueHave
              rts
optValueHave:
              cmp ##OP_VIEW
              beq optValueView
              cmp ##OP_WALLS
              beq optValueWalls
              cmp ##OP_TRANSPARENCY
              beq optValueTransparency
              cmp ##OP_BUFFER
              beq optValueBuffer
              cmp ##OP_VSYNC
              beq optValueVsync
              cmp ##OP_SHADE
              beq optValueShade
              cmp ##OP_MWALK
              beq optValueMouse
              cmp ##OP_J13
              beq optValueJ13
              cmp ##OP_MSPEED
              beq optValueSpeed
              cmp ##OP_MUSIC
              beq optValueMusic
              jsr abs:.word0 (SoundVolGet)
              ldx ##15
              bra optValueBar
optValueMusic:
              jsr abs:.word0 (MusicVolGet)
              ldx ##15
              bra optValueBar
optValueSpeed:
              lda long:mouseSensitivity
              ldx ##15
              bra optValueBar
optValueView: lda long:weaponViewIndex
              tax
              lda abs:.word0 (viewNames),x
              bra optValueText
optValueShade:
              lda long:columnLight
              bra optValueSwitch
optValueMouse:
              lda long:mouseWalk
              bra optValueSwitch
optValueTransparency:
              lda long:fastTransparencyOn
              bra optValueSwitch
optValueWalls:
              lda long:wallPaintOn
              bra optValueSwitch
optValueBuffer:
              lda long:bufferOn
              asl a
              tax
              lda abs:.word0 (paintModeNames),x
              bra optValueText
optValueVsync:
              lda long:vsyncOn
              bra optValueSwitch
optValueJ13:  lda long:j13Enabled
optValueSwitch:
              beq optValueOff
              lda ##.word0 (sOn)
              bra optValueText
optValueOff:  lda ##.word0 (sOff)
optValueText: sta dp:U_STR
              lda ##OP_VALUE_X
              sta dp:U_X
              jmp abs:.word0 (DrawStrRight)

;;; A = the value, X = its maximum: a bar.
optValueBar:  ldy abs:.word0 (listDelta)
              beq optBarPaint
              rts
optBarPaint:   phx
              ldx ##OP_BAR_W - 4
              jsr abs:.word0 (UiMul16)
              plx
              jsr abs:.word0 (UiDiv16)
              and ##0xfffe
              sta dp:U_T5                   ; filled pixels
              lda ##OP_BAR_X
              sta dp:U_X
              lda dp:UL_ROWY
              clc
              adc ##3
              sta dp:U_Y
              lda ##OP_BAR_W
              sta dp:U_W
              lda ##3
              sta dp:U_H
              lda ##C_DKGRAY
              sta dp:U_C
              jsr abs:.word0 (FillRect)
              lda dp:U_T5
              beq optBarDone
              sta dp:U_W
              lda ##3
              sta dp:U_H
              lda ##C_WHITE
              sta dp:U_C
              jsr abs:.word0 (FillRect)
optBarDone:   rts

;;; Left or right on the current row (U_MORE = -1 or 1).
optChange:    lda dp:UL_CUR
              clc
              adc abs:.word0 (optBase)
              cmp ##OP_VIEW
              beq changeView
              cmp ##OP_WALLS
              beq changeWalls
              cmp ##OP_TRANSPARENCY
              beq changeTransparency
              cmp ##OP_BUFFER
              beq changeBuffer
              cmp ##OP_VSYNC
              beq changeVsync
              cmp ##OP_SHADE
              beq changeShade
              cmp ##OP_MWALK
              beq changeMouse
              cmp ##OP_J13
              beq changeJ13
              cmp ##OP_MSPEED
              beq changeSpeed
              cmp ##OP_SOUND
              beq changeSound
              cmp ##OP_MUSIC
              beq changeMusic
              rts
changeTransparency:
              jsl long:TransparencyToggle
              rts
changeWalls:  jsl long:WallPaintToggle
              rts
changeBuffer: jsl long:PaintingToggle
              rts
changeVsync:  jsl long:VsyncToggle
              rts
changeJ13:    jsl long:J13Toggle
              rts
changeView:   jsl long:BufferChangeView
              rts
              .public BufferMenuSound
BufferMenuSound: jsr abs:.word0 (UiSound)
              rtl
changeShade:  lda long:columnLight
              eor ##1
              sta long:columnLight
              bra optAfter
changeMouse:  lda long:mouseWalk
              eor ##1
              sta long:mouseWalk
              rts
changeSpeed:  lda long:mouseSensitivity
              clc
              adc dp:U_MORE
              bmi optAfter
              cmp ##16
              bcs optAfter
              sta long:mouseSensitivity
              bra optAfter
changeSound:  jsr abs:.word0 (SoundVolGet)
              clc
              adc dp:U_MORE
              bmi optAfter
              cmp ##16
              bcs optAfter
              jsr abs:.word0 (SoundVolSet)
              lda ##SELECTITEMSND
              jsr abs:.word0 (UiSound)
              bra optAfter
changeMusic:  jsr abs:.word0 (MusicVolGet)
              clc
              adc dp:U_MORE
              bmi optAfter
              cmp ##16
              bcs optAfter
              jsr abs:.word0 (MusicVolSet)
              bra optAfter
optAfter:     rts

              .section menudata, data, root
optCur:       .word 0
optActive:    .byte 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
optItems:     .word .word0 (oSound), .word0 (oMusic), .word0 (oView), .word0 (oShade), .word0 (oVsync), .word0 (oBuffer)
              .word .word0 (paintWalls), .word0 (oTransparency), .word0 (oMouse), .word0 (oSpeed), .word0 (oJ13), .word0 (oControls)
oSound:       .asciz "Sound Effects"
oMusic:       .asciz "Music"
oView:        .asciz "View Size"
oShade:       .asciz "Depth Shading"
oVsync:       .asciz "Vsync"
oBuffer:      .asciz "Painting"
paintModeNames: .word .word0 (paintDirect), .word0 (paintBuffered)
paintDirect:  .asciz "Direct"
paintBuffered: .asciz "Buffered"
paintWalls:   .asciz "Fast walls"
oTransparency: .asciz "Fast transparency"
oMouse:       .asciz "Mouse Walk"
oSpeed:       .asciz "Mouse Speed"
oJ13:         .asciz "J13 Keyboard"
oControls:    .asciz "Key Setup"
oBench:       .asciz "Benchmark"
oSave:        .asciz "Save Settings"
sOn:          .asciz "On"
sOff:         .asciz "Off"
viewNames:    .word .word0 (vHalf), .word0 (vTwoThirds), .word0 (vThreeQuarters), .word0 (vFull)
vHalf:        .asciz "1/2"
vTwoThirds:   .asciz "2/3"
vThreeQuarters: .asciz "3/4"
vFull:        .asciz "Full"

rootCur:      .word 0
optBase:      .word 0
optCount:     .word 8
optIndex:     .word 0
rootActive:   .byte 1,1,1,3
rootItems:    .word .word0 (rDisplay), .word0 (rControls), .word0 (oBench), .word0 (oSave)
rDisplay:     .asciz "Display & Sound"
rControls:    .asciz "Controls"

              .section menucode, text, root, noreorder
OptionsShortcut: pha
              stz abs:.word0 (optBase)
              stz abs:.word0 (optCur)
              lda ##8
              sta abs:.word0 (optCount)
              pla
              cmp ##5
              beq shortcutControls
              cmp ##4
              bne shortcutDisplay
              lda ##2
              sta abs:.word0 (optCur)
shortcutDisplay: lda ##LUMP_OPTIONS
              bra shortcutSettings
shortcutControls: lda ##OP_MWALK
              sta abs:.word0 (optBase)
              lda ##4
              sta abs:.word0 (optCount)
              lda ##LUMP_CONTROLTOP
shortcutSettings: jsr abs:.word0 (LoadLump)
              jmp abs:.word0 (settingsPage)
