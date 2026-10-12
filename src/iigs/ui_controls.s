;;; Key-binding editor for boundKeys/boundBits. Each action displays its first
;;; two bindings; reassignment makes the selected key the action's sole key.
;;; Cancellation leaves bindings unchanged. Unbound entries must
;;; have their action bit cleared because gameplay reads the tables directly.
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public ControlsScreen, ControlsApply, ControlsCollect, ControlsDefaults
              .extern ListResume, listValueUpdate, listValueItem, ListRun, DrawList, GetKey, LoadLump, UiSound, DrawStr, DrawStrRight, OutStr, listItem, MenuScreen
              .extern listValVec, dlControls, keyNames, boundKeys, boundBits, keyChars, heldKey, menuBindMouse

NOKEY         .equ 0xffff
KEY_COUNT     .equ 26                       ; the entries of boundKeys in keys.s
KEY_OLD       .equ 20                       ; the entries that files without S_KEYPAD hold
KEY_NONE      .equ 0x7f                     ; a code no key sends: an entry with no key
MOUSE_A       .equ 0x7e                     ; keys.s counts the mouse buttons as keys
MOUSE_B       .equ 0x70
ACTIONS       .equ 10
NOWAYSND      .equ 6
ESCPRESSEDSND .equ 39
CT_CX         .equ 16                       ; the gun

ControlsScreen:
              jsr abs:.word0 (ctlSnapshot)
              lda ##LUMP_CONTROLS
              jsr abs:.word0 (LoadLump)
              bcc ctlDraw
              rts
ctlDraw:      ldx ##.word0 (dlControls)
              jsr abs:.word0 (MenuScreen)
              SCREEN_ID 9
ctlList:      lda ##.word0 (ctlItems)
              sta dp:UL_ITEMS
              lda ##CT_ITEMS
              sta dp:UL_COUNT
              lda ##CT_X
              sta dp:UL_X
              lda ##CT_Y
              sta dp:UL_Y
              lda ##CT_STEP
              sta dp:UL_STEP
              lda ##CT_CX
              sta dp:UL_CX
              lda ##.word0 (ctlActive)
              sta dp:UL_ACT
              lda abs:.word0 (ctlCur)
              sta dp:UL_CUR
              stz dp:UL_HOOK
              stz dp:UL_LRHOOK
              lda ##256
              sta dp:UL_WIDTH
              lda ##.word0 (ctlValue)
              sta dp:UL_VALHOOK
              sta abs:.word0 (listValVec)
              jsr abs:.word0 (ListRun)
ctlPicked:    cmp ##NOKEY
              beq ctlDone
              sta abs:.word0 (ctlCur)
              cmp ##ACTIONS
              beq ctlDefaultKeys
              jsr abs:.word0 (ctlRebind)
              jsr abs:.word0 (listValueUpdate)
              bra ctlResume
ctlDefaultKeys:
              jsr abs:.word0 (ControlsDefaults)
              bra ctlValues
ctlValues:    lda dp:UL_CUR
              pha
              lda dp:UL_TOP
              sta abs:.word0 (ctlUpdateRow)
ctlValueNext: lda abs:.word0 (ctlUpdateRow)
              cmp ##ACTIONS
              bcs ctlValuesDone
              sec
              sbc dp:UL_TOP
              cmp dp:UL_VISIBLE
              bcs ctlValuesDone
              lda abs:.word0 (ctlUpdateRow)
              sta dp:U_ITEM
              jsr abs:.word0 (listValueItem)
              inc abs:.word0 (ctlUpdateRow)
              bra ctlValueNext
ctlValuesDone: pla
              sta dp:UL_CUR
ctlResume:    jsr abs:.word0 (ListResume)
              bra ctlPicked
ctlDone:      rts

;;; Row UL_CUR waits for a key. Esc leaves the keys as they are; a key the
;;; game uses for something else is refused.
ctlRebind:    lda dp:UL_CUR
              sta abs:.word0 (ctlWait)
              stz abs:.word0 (ctlRefused)
              sta dp:U_ITEM
              jsr abs:.word0 (listValueUpdate)
              lda ##1
              sta abs:.word0 (menuBindMouse)
ctlWaitKey:   jsr abs:.word0 (GetKey)
              cmp ##K_ESC
              beq ctlCancel
              sta dp:KD_CODE
              jsr abs:.word0 (ctlReserved)
              bcc ctlTake
              lda ##1
              sta abs:.word0 (ctlRefused)
              lda dp:UL_CUR
              sta dp:U_ITEM
              jsr abs:.word0 (listValueUpdate)
              lda ##NOWAYSND
              jsr abs:.word0 (UiSound)
              bra ctlWaitKey
ctlTake:      jsr abs:.word0 (ctlBind)
              bra ctlWaited
ctlCancel:    lda ##ESCPRESSEDSND
              jsr abs:.word0 (UiSound)
ctlWaited:    stz abs:.word0 (menuBindMouse)
              lda ##NOKEY
              sta abs:.word0 (ctlWait)
              sta abs:.word0 (heldKey)      ; a held arrow key must not repeat in the list
              rts

;;; Carry set when the key code in KD_CODE is not for an action: Esc and the
;;; keys with a fixed use in keys.s (keyChars), and codes the mouse and
;;; the table use.
ctlReserved:  lda dp:KD_CODE
              cmp ##MOUSE_B
              beq ctlRefuse
              cmp ##KEY_NONE
              beq ctlRefuse
              tax
              sep #0x20
              lda long:keyChars,x
              rep #0x20
              and ##255
              bne ctlRefuse
              clc
              rts
ctlRefuse:    sec
              rts

;;; The key KD_CODE becomes the only key of the action of row UL_CUR. No other
;;; action keeps it. The first entry of the action in the table takes it.
ctlBind:      lda dp:UL_CUR
              asl a
              tax
              lda abs:.word0 (ctlMasks),x
              sta dp:KD_MASK
              ldx ##0
bindEntry:    jsr abs:.word0 (ctlIsMouse)
              bcs bindNext
              lda abs:.word0 (ctlBits),x
              cmp dp:KD_MASK
              beq bindClear
              lda long:boundBits,x
              beq bindNext
              lda long:boundKeys,x
              cmp dp:KD_CODE
              bne bindNext
bindClear:    lda ##KEY_NONE
              sta long:boundKeys,x
              lda ##0
              sta long:boundBits,x
bindNext:     inx
              inx
              cpx ##KEY_COUNT * 2
              bcc bindEntry
              ldx ##0
bindFirst:    jsr abs:.word0 (ctlIsMouse)
              bcs bindSkip
              lda abs:.word0 (ctlBits),x
              cmp dp:KD_MASK
              beq bindSet
bindSkip:     inx
              inx
              cpx ##KEY_COUNT * 2
              bcc bindFirst
              rts
bindSet:      lda dp:KD_CODE
              sta long:boundKeys,x
              lda dp:KD_MASK
              sta long:boundBits,x
              rts

;;; Carry set when entry X (2 * entry) is a mouse button.
ctlIsMouse:   lda abs:.word0 (ctlDef),x
              cmp ##MOUSE_B
              beq ctlMouse
              clc
              rts
ctlMouse:     sec
              rts

;;; The keys of row U_ITEM, drawn at CT_VALUE_X: gray, white on the current
;;; row, yellow while it waits for a key. U_T6 is 1 on the current row.
ctlValue:     lda dp:U_ITEM
              cmp ##ACTIONS
              bcs ctlValueDone
              lda ##C_GRAY
              sta dp:U_C
              lda dp:U_T6
              beq ctlValueAt
              lda ##C_WHITE
              sta dp:U_C
ctlValueAt:   lda dp:UL_ROWY
              sta dp:U_Y
              stz dp:U_FONT
              lda ##CT_VALUE_X
              sta dp:U_X
              lda dp:U_ITEM
              cmp abs:.word0 (ctlWait)
              bne ctlValueKeys
              lda ##C_YELLOW
              sta dp:U_C
              lda ##.word0 (sPress)
              ldx abs:.word0 (ctlRefused)
              beq ctlPress
              lda ##.word0 (sInUse)
ctlPress:     sta dp:U_STR
              jmp abs:.word0 (DrawStrRight)
ctlValueKeys: jsr abs:.word0 (ctlKeyText)
              jmp abs:.word0 (DrawStrRight)
ctlValueDone: rts

;;; The first two keys of row U_ITEM as text in ctlText; U_STR points at it.
ctlKeyText:   lda dp:U_ITEM
              asl a
              tax
              lda abs:.word0 (ctlMasks),x
              sta dp:KD_MASK
              lda ##.word0 (ctlText)
              sta dp:U_OUT
              stz dp:KD_N
              ldx ##0
keyScan:      jsr abs:.word0 (ctlIsMouse)
              bcs keyNext
              lda abs:.word0 (ctlBits),x
              cmp dp:KD_MASK
              bne keyNext
              lda long:boundBits,x
              beq keyNext
              lda dp:KD_N
              beq keyName
              phx
              lda ##.word0 (sComma)
              sta dp:U_STR
              jsr abs:.word0 (OutStr)
              plx
keyName:      lda long:boundKeys,x
              and ##127
              asl a
              asl a
              asl a
              clc
              adc ##.word0 (keyNames)
              sta dp:U_STR
              phx
              jsr abs:.word0 (OutStr)
              plx
              inc dp:KD_N
              lda dp:KD_N
              cmp ##2
              bcs keyTextDone
keyNext:      inx
              inx
              cpx ##KEY_COUNT * 2
              bcc keyScan
keyTextDone:  lda dp:KD_N
              bne keyTextEnd
              lda ##.word0 (sNone)
              sta dp:U_STR
              jsr abs:.word0 (OutStr)
keyTextEnd:   lda ##.word0 (ctlText)
              sta dp:U_STR
              rts

;;; ---------------------------------------------------------------------------
;;; The table of keys.s, and the 26 key codes of the settings image
;;; ---------------------------------------------------------------------------

;;; Keep the table keys.s starts with: its codes are the defaults, its bits
;;; say which action each entry belongs to. Done once, before any change.
ctlSnapshot:  lda abs:.word0 (ctlSnapped)
              bne snapshotDone
              ldx ##KEY_COUNT * 2 - 2
snapshotEntry:
              lda long:boundKeys,x
              sta abs:.word0 (ctlDef),x
              lda long:boundBits,x
              sta abs:.word0 (ctlBits),x
              dex
              dex
              bpl snapshotEntry
              lda ##1
              sta abs:.word0 (ctlSnapped)
snapshotDone: rts

;;; The default keys into the table.
ControlsDefaults:
              jsr abs:.word0 (ctlSnapshot)
              ldx ##KEY_COUNT * 2 - 2
defaultEntry: lda abs:.word0 (ctlDef),x
              sta long:boundKeys,x
              lda abs:.word0 (ctlBits),x
              sta long:boundBits,x
              dex
              dex
              bpl defaultEntry
              rts

;;; The 26 codes of the settings image into the table: 255 is no key. The
;;; mouse buttons stay as keys.s has them. A file without S_KEYPAD gets the
;;; default keypad codes.
ControlsApply:
              jsr abs:.word0 (ctlSnapshot)
              ldx ##SETTINGS_IN + S_KEYS
              ldy ##.word0 (ctlBytes)
              lda ##KEY_COUNT - 1
              .byte 0x54, 0x3f, 0x00         ; MVN: bank 0 to bank $3F
              lda long:SETTINGS_IN + S_KEYPAD
              and ##255
              cmp ##1
              beq applyKeypadSaved
              ldx ##KEY_OLD * 2
              ldy ##KEY_OLD
applyKeypadDefault:
              lda abs:.word0 (ctlDef),x
              sep #0x20
              sta abs:.word0 (ctlBytes),y
              rep #0x20
              inx
              inx
              iny
              cpy ##KEY_COUNT
              bcc applyKeypadDefault
applyKeypadSaved:
              ldx ##0
              ldy ##0
applyEntry:   jsr abs:.word0 (ctlIsMouse)
              bcs applyNext
              sep #0x20
              lda abs:.word0 (ctlBytes),y
              rep #0x20
              and ##255
              cmp ##0x80
              bcs applyNone
              sta long:boundKeys,x
              lda abs:.word0 (ctlBits),x
              sta long:boundBits,x
              bra applyNext
applyNone:    lda ##KEY_NONE
              sta long:boundKeys,x
              lda ##0
              sta long:boundBits,x
applyNext:    inx
              inx
              iny
              cpy ##KEY_COUNT
              bcc applyEntry
              rts

;;; The table into the 26 codes of the settings image.
ControlsCollect:
              sep #0x20
              lda #1
              sta long:SETTINGS_IN + S_KEYPAD
              rep #0x20
              ldx ##0
              ldy ##0
collectEntry: lda long:boundBits,x
              beq collectNone
              lda long:boundKeys,x
              bra collectStore
collectNone:  lda ##0xff
collectStore: sep #0x20
              sta abs:.word0 (ctlBytes),y
              rep #0x20
              inx
              inx
              iny
              cpy ##KEY_COUNT
              bcc collectEntry
              ldx ##.word0 (ctlBytes)
              ldy ##SETTINGS_IN + S_KEYS
              lda ##KEY_COUNT - 1
              .byte 0x54, 0x00, 0x3f         ; MVN: bank $3F to bank 0
              phk
              plb
              rts

              .section menudata, data, root
ctlCur:       .word 0
ctlWait:      .word 0xffff
ctlRefused:   .word 0
ctlSnapped:   .word 0
ctlDef:       .space KEY_COUNT * 2
ctlBits:      .space KEY_COUNT * 2
ctlBytes:     .space KEY_COUNT
ctlText:      .space 40
ctlActive:    .byte 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
;;; The action bits of keys.s in the order of the rows.
ctlMasks:     .word 1, 2, 4, 8, 256, 512, 32, 16, 64, 128
ctlItems:     .word .word0 (aForward), .word0 (aBack), .word0 (aTurnL), .word0 (aTurnR)
              .word .word0 (aStrafeL), .word0 (aStrafeR), .word0 (aFire), .word0 (aOpen)
              .word .word0 (aStrafe), .word0 (aRun), .word0 (aDefault)
aForward:     .asciz "Forward"
aBack:        .asciz "Backward"
aTurnL:       .asciz "Turn Left"
aTurnR:       .asciz "Turn Right"
aStrafeL:     .asciz "Strafe Left"
aStrafeR:     .asciz "Strafe Right"
aFire:        .asciz "Fire"
aOpen:        .asciz "Open"
aStrafe:      .asciz "Strafe"
aRun:         .asciz "Run"
aDefault:     .asciz "Default Keys"
sPress:       .asciz "Key?"
sInUse:       .asciz "In use"
sNone:        .asciz "- none -"
sComma:       .asciz ", "

ctlUpdateRow: .word 0
