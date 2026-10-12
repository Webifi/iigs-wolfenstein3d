;;; Front end: constants shared by the bank $3F code, the bank 0 disk bridge
;;; and the bank 2 hooks. The menus run with D = UI_DP, a page of bank 0 next
;;; to the game's direct page ($1000). UiEnterCore saves its 256 bytes and
;;; UiLeaveCore restores them; the menu owns this page between those calls.



UI_PICSIZE    .equ 0x3800

;;; palette slots, the same meaning in every floor's palette
C_BLACK       .equ 0
C_WHITE       .equ 1
C_RED         .equ 2
C_DKRED       .equ 3
C_YELLOW      .equ 4
C_GRAY        .equ 12
C_DKGRAY      .equ 13

;;; ADB raw key codes
K_ESC         .equ 0x35
K_RETURN      .equ 0x24
K_ENTER       .equ 0x4c
K_SPACE       .equ 0x31
K_UP          .equ 0x3e
K_DOWN        .equ 0x3d
K_LEFT        .equ 0x3b
K_RIGHT       .equ 0x3c
K_DELETE      .equ 0x33

;;; test latch: WOLF3D_TEST_SKIP_MENU written here skips the title and menu
UI_SKIP_MAGIC .equ 0x5a5a

;;; test latch: the screen the menu is showing (0 none), read by tools/ui_test.py
SCREEN_ID     .macro n
              sep #0x20
              lda #\n
              sta long:UI_SCREEN
              rep #0x20
              .endm

;;; the busy box in the middle of the screen (ui_disk.s); the high score box uses it too
BOX_X         .equ 70
BOX_Y         .equ 83
BOX_W         .equ 180
BOX_H         .equ 34
BUSY_BAR_X    .equ 80
BUSY_BAR_Y    .equ 109
BUSY_BAR_W    .equ 160
BUSY_BAR_H    .equ 3
BUSY_BAR_INK  .equ 1                  ; aligned bright-neutral role
BUSY_EDGE_INK .equ 12                 ; aligned gray area; the RGB belongs to the picture

;;; 1 when the settings and saved games can be written to the home disk (ui_write.s)
#define UI_WRITE 1

;;; WOLF.SETTINGS: one block, in RAM at SETTINGS_IN as the loader read it.
;;; Bytes 496-511 belong to the sound code (AudioSettingKey in
;;; audio_settings.s); every other byte not named here is kept as it is.
S_MAGIC       .equ 0                  ; "WOLFSET", then the version byte
S_SUM         .equ 8                  ; word: sum of the bytes 12-495
S_VIEW        .equ 12                 ; 0 half, 1 two thirds, 2 three quarters, 3 full, 255 not set
S_VIEW_NOTSET .equ 255                ; no size picked yet: ViewDefault (viewdef.s) chooses one at start
S_SHADE       .equ 13                 ; depth shading 0 off, 1 on
S_MWALK       .equ 14                 ; mouse walk 0 off, 1 on
S_MSPEED      .equ 15                 ; mouse speed 0-15 (older files use 0-9)
S_VISITED     .equ 16                 ; low visited word; version 0 uses ten bits
S_UNUSED_DRAW .equ 18                 ; retired drawing option; ignored on load, zeroed on save
S_J13         .equ 19                 ; bit 0: gameplay; bit 1: explicit choice (menus always accept J13)
S_MOUSE_VERSION .equ 20               ; 1 = calibrated 16-step mouse, 0 = legacy scale
S_VISIT_VERSION .equ 21               ; 1 = 64-bit visited mask, 0 = legacy ten-floor mask
S_VISITED_HI  .equ 22                 ; three upper words, through byte 27
S_VSYNC       .equ 28                 ; wait for vertical blank before painting, default off
S_DRAW_BUFFER .equ 29
S_FAST_TRANSPARENCY .equ 30           ; bit 1: explicit choice, bit 0: enabled; old zero defaults on
S_KEYPAD      .equ 31                 ; 1: S_KEYS holds 26 codes; older files hold 20 (keypad codes default)
S_KEYS        .equ 32                 ; 26 key codes in the order of boundKeys (keys.s), 255 none
S_SCORES      .equ 64                 ; 7 high scores of 24 bytes, through 231
S_SLOTS       .equ 232                ; 8 saved games of 32 bytes (the scores end at 232)
SLOT_SIZE     .equ 32
SLOTS         .equ 8
SL_USED       .equ 0
SL_SKILL      .equ 2
SL_FLOOR      .equ 4
SL_LIVES      .equ 6
SL_HEALTH     .equ 8
SL_AMMO       .equ 10
SL_BEST       .equ 12
SL_CHOSEN     .equ 14
SL_WEAPON     .equ 16
SL_SCORE      .equ 18                 ; 32 bits
SL_EXTRA      .equ 22                 ; 32 bits
SL_KILLS      .equ 26
SL_TREAS      .equ 28
SL_CHECK      .equ 30                 ; sum of the words 0-28

;;; WOLF.SETX, one block at slotExt (bank 2). Names for the eight saves.
;;; Slots 8 and 9 stay zero: the home disk has no room for their world files.
SX_MAGIC      .equ 0                  ; "WOLFSLT1"
SX_SUM        .equ 8                  ; word: sum of the bytes 10-511
SX_QUICK      .equ 10                 ; last slot 0-7, or 255
SX_COUNT      .equ 11                 ; 8
SX_PAD        .equ 12                 ; reserved zero bytes12-15
SX_TAIL       .equ 272                ; unused names8-9 and reserved tail
SX_NAMES      .equ 16                 ; ten names of 32 bytes; 8 and 9 stay 0
SX_NAME       .equ 32
SX_EXTRA      .equ 336                ; two unused slot headers, kept 0

#include "memmap.inc"
#include "menu.inc"
#include "steel-constants.inc"

