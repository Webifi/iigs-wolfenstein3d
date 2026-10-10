;;; Per-palette gray tables live in the catalog at $3B. Each hardware slot
;;; keeps the address of the table for the palette loaded into it. The row
;;; converter is unrolled: 8-bit A, one table read, no branch, no mode switch.
#include "memmap.inc"
#include "frontend.inc"
#include "gray.inc"
#include "pages.inc"
#include "menu.inc"
#include "campaign.inc"
              .section graycode, text, root, noreorder
              .public BindIndexed, BindAddr, BindInit, BindBootSlots, BindFullPicture
              .public BindTally, BindFloorSlots, BindHeldTint, BindTintBlock
              .extern heightView
              .public GatherPreviews, GrayRow, GrayRowHold, GrayCopyRows, PublishGrayRow
              .public CloseRestore, CopySlotTable
              .public ClearGrayRows, streamLump, BindVictoryPals
              .public PublishTallyPals, PublishVictoryPals
              .public PlayGrayTables, GraySnapBank
              .extern levelIndex, tintFloorOffsets, previewLast, WaitBlank
PLAY_GRAY     .equ SPAN_BUFFER        ; the in-game pause's records, bank-0 window
;;; gray-unroll.inc (tools/frontend/gray_catalog.py _write_unroll) repeats one
;;; 19-byte group per screen byte: LDA long, STA long (snapshot), TAY, LDA [dp],y,
;;; STA long (gray copy), STA long (frame). The snapshot store's bank byte is at 7.
GRAY_UNROLL_STEP .equ 19
GRAY_SNAP_BANK .equ 7

bindReady:    .word 0
bindLo:       .word 0
bindBk:       .word 0
streamLump:   .word 0
grayRowN:     .word 0
grayTmp:      .word 0
grayTmp2:     .word 0
grayLo:       .word 0
grayHi:       .word 0
closeRow:     .word 0
closeCnt:     .word 0

;;; A = slot. X = low 16 of a 4-byte catalog pointer in bank $3B.
;;; Cold: two 16-bit loads, then the slot record. No mode change per byte.
BindIndexed:  php
              rep #0x30
              pha
              lda long:GRAY_BASE,x
              sta long:bindLo
              lda long:GRAY_BASE+0x2,x
              and ##255
              tay
              lda long:bindLo
              plx
              jsr abs:.word0 (bindStore)
              plp
              rtl

;;; A = low 16 of the record. Y low byte = its bank. X = slot.
BindAddr:     php
              rep #0x30
              jsr abs:.word0 (bindStore)
              plp
              rtl

;;; M and X are 16-bit. Y's low byte is the bank. Both slot words land at once.
bindStore:    sta long:bindLo
              tya
              and ##255
              sta long:bindBk
              txa
              and ##15
              asl a
              asl a
              tax
              lda long:bindLo
              sta long:SLOT_REC,x
              lda long:bindBk
              sta long:SLOT_REC+2,x
              rts

;;; Every slot points at the black record until a real palette is loaded.
BindInit:     php
              rep #0x30
              lda long:bindReady
              bne initDone
              lda ##1
              sta long:bindReady
              ldy ##0
initLoop:     phy
              ldx ##OFF_BLACK
              tya
              jsl long:BindIndexed
              ply
              iny
              cpy ##16
              bcc initLoop
initDone:     plp
              rtl

BindBootSlots: jsl long:BindInit
              ldx ##OFF_BOOT
              lda ##0
              jsl long:BindIndexed
              ldx ##OFF_BOOT + 4
              lda ##1
              jsl long:BindIndexed
              ldx ##OFF_BOOT + 52
              lda ##13
              jsl long:BindIndexed
              ldx ##OFF_BOOT + 56
              lda ##14
              jsl long:BindIndexed
              ldx ##OFF_BOOT + 60
              lda ##15
              jsl long:BindIndexed
              rtl

;;; streamLump is the full-screen picture just copied into fadeBase.
BindFullPicture:
              lda long:streamLump
              cmp ##LUMP_TITLE
              beq pic0
              cmp ##LUMP_CREDITS
              beq pic1
              cmp ##LUMP_PG13
              beq pic2
              cmp ##LUMP_VICTORY
              beq pic3
              cmp ##LUMP_END1
              bcc picNone
              ldx ##OFF_PIC + 256           ; current ending packet replaces this slot
              bra bind16
picNone:
              rtl
pic0:         ldx ##OFF_PIC
              bra bind16
pic1:         ldx ##OFF_PIC + 64
              bra bind16
pic2:         ldx ##OFF_PIC + 128
              bra bind16
pic3:         ldx ##OFF_PIC + 192
              bra bind16
pic4:         ldx ##OFF_PIC + 256
              bra bind16
pic5:         ldx ##OFF_PIC + 320
bind16:       ldy ##0
bind16Loop:   phy
              phx
              tya
              jsl long:BindIndexed
              plx
              ply
              inx
              inx
              inx
              inx
              iny
              cpy ##16
              bcc bind16Loop
              rtl

BindTally:    ldx ##OFF_TALLY
              lda ##0
              jsl long:BindIndexed
              ldx ##OFF_TALLY + 4
              lda ##13
              jsl long:BindIndexed
              ldx ##OFF_TALLY + 8
              lda ##14
              jsl long:BindIndexed
              rtl

;;; Victory publishes palette 0 and palettes 13-15 of the victory picture.
BindVictoryPals:
              ldx ##OFF_PIC + 192
              lda ##0
              jsl long:BindIndexed
              ldx ##OFF_PIC + 244
              lda ##13
              jsl long:BindIndexed
              ldx ##OFF_PIC + 248
              lda ##14
              jsl long:BindIndexed
              ldx ##OFF_PIC + 252
              lda ##15
              jsl long:BindIndexed
              rtl

;;; The tally page writes palette 0, then 13 and 14, at the blank.
PublishTallyPals:
              jsl long:WaitBlank
              ldx ##PAGE_STAGE + TALLY_PALS
              ldy ##0x9e00
              lda ##31
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK
              plb
              ldx ##PAGE_STAGE + TALLY_PALS + 32
              ldy ##0x9e00 + 32 * 13
              lda ##63
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK
              plb
              jsl long:BindTally
              rtl

;;; Victory writes palette 0 and palettes 13-15 at the blank.
PublishVictoryPals:
              jsl long:WaitBlank
              ldx ##PAGE_STAGE + 512 * VICTORY_DIGITS_BLOCKS + 512
              ldy ##0x9e00
              lda ##31
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK
              plb
              ldx ##PAGE_STAGE + 512 * VICTORY_DIGITS_BLOCKS + 512 + 32 * 13
              ldy ##0x9e00 + 32 * 13
              lda ##95
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK
              plb
              jsl long:BindVictoryPals
              rtl

;;; RevealFloor wrote palette 0 from this floor's tint and black in the rest.
BindFloorSlots:
              lda long:levelIndex
              asl a
              tax
              lda long:tintFloorOffsets,x
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              asl a
              asl a
              tax
              lda ##0
              jsl long:BindIndexed
              ldy ##1
floorBlack:   phy
              ldx ##OFF_BLACK
              tya
              jsl long:BindIndexed
              ply
              iny
              cpy ##16
              bcc floorBlack
              rtl

heldIndex:    .word 0
heldStatus:   .word 0
heldValid:    .word 0

;;; A = tint index of palette 0. X = tint index of the first status palette.
BindTintBlock: php
              rep #0x30
              sta long:heldIndex
              txa
              sta long:heldStatus
              lda ##1
              sta long:heldValid
              plp
              rtl

;;; The held tint in PALBUF just reached the hardware.
BindHeldTint: lda long:heldValid
              beq heldSkip
              jsr abs:.word0 (bindTintNow)
heldSkip:     rtl

bindTintNow:  lda long:heldIndex
              asl a
              asl a
              tax
              lda ##0
              jsl long:BindIndexed
              lda long:heldStatus
              asl a
              asl a
              tax
              lda ##1
tintBlock:    phx
              pha
              jsl long:BindIndexed
              pla
              plx
              inx
              inx
              inx
              inx
              inc a
              cmp ##13
              bcc tintBlock
              rts

;;; Pack the 16 preview palettes. The blank write is a single 512-byte move.
GatherPreviews:
              php
              rep #0x30
              lda ##0
              sta long:grayLo
gatherSlot:   lda long:grayLo
              cmp ##16
              bcs gatherDone
              asl a
              asl a
              tax
              lda long:SLOT_REC,x
              clc
              adc ##256
              sta long:grayTmp
              sep #0x20
              lda long:SLOT_REC+2,x
              adc #0
              sta long:gatherMvn+2
              rep #0x20
              lda long:grayLo
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc ##0x8110
              tay
              lda long:grayTmp
              tax
              lda ##31
              phb
gatherMvn:    .byte 0x54, 0x41, 0x3b
              plb
              lda long:grayLo
              inc a
              sta long:grayLo
              bra gatherSlot
gatherDone:   plp
              rtl

;;; X = slot. One pair table lands at $41:8310 for PictureWord's abs,y read.
CopySlotTable:
              php
              rep #0x30
              phy
              txa
              and ##15
              asl a
              asl a
              tax
              lda long:SLOT_SAVE,x
              pha
              sep #0x20
              lda long:SLOT_SAVE+2,x
              sta long:slotMvn+2
              rep #0x20
              pla
              tax
              ldy ##0x8310
              lda ##255
              phb
slotMvn:      .byte 0x54, 0x41, 0x3b
              plb
              ply
              plp
              rtl

;;; A = row. Read each original screen byte once into the snapshot and
;;; convert it into the offscreen gray copy. The display pixels stay intact.
;;; The saved SCB and SLOT_SAVE describe the captured source, independent
;;; of palette bindings used later while composing the menu.
GrayRowHold:
GrayRow:      php
              rep #0x30
              sta long:grayRowN
              lda ##0xffff             ; clean gray pixels reuse the reciprocal table
              sta long:heightView
              lda dp:U_T0
              pha
              lda dp:U_T1
              pha
              lda long:grayRowN
              tax
              sep #0x20
              lda long:SNAP_SCB,x
              and #15
              rep #0x20
              and ##255
              asl a
              asl a
              tax
              lda long:SLOT_SAVE,x
              sta dp:U_T0
              sep #0x20
              lda long:SLOT_SAVE+2,x
              sta dp:U_T0+2
              rep #0x20
              lda long:grayRowN
              pha
              asl a
              asl a
              asl a
              asl a
              asl a
              sta long:grayTmp
              pla
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc long:grayTmp
              clc
              adc ##0x2000
              tax
              sep #0x20
              lda #0
              xba
grayUnroll:
#include "gray-unroll.inc"
              rep #0x20
              pla
              sta dp:U_T1
              pla
              sta dp:U_T0
              plp
              rtl

;;; A = the bank byte of the 160 colour-snapshot stores of GrayRow: $40 keeps
;;; the snapshot at $41:0000 (title menus restore it); $3C puts each colour
;;; byte on the gray copy byte that the next store of its group replaces, so
;;; a pause in play writes no snapshot ($41:0000 is art RAM in play).
GraySnapBank: php
              rep #0x30
              and ##0x00ff
              sta long:gsbBank
              ldx ##0
gsbStore:     sep #0x20
              lda long:gsbBank
              sta long:grayUnroll+GRAY_SNAP_BANK,x
              rep #0x20
              txa
              clc
              adc ##GRAY_UNROLL_STEP
              tax
              cpx ##GRAY_UNROLL_STEP*160
              bcc gsbStore
              plp
              rtl
gsbBank:      .word 0

;;; In-game pause: no gray catalog in RAM. Each hardware palette gets the
;;; record tools/frontend/gray_pair.py would build for it, from the colors on
;;; the screen: lightness 3R + 6G + B; 0 is black, up to 60 slot 15, up to
;;; 120 slot 14, brighter slot 13. A record is the 256-byte pair table, then
;;; the 32-byte palette of menu grays (MENU_COL). 16 records of 288 bytes at
;;; $00:2000 (the paused window, src/iigs/ui_overlays.s); slot n is bound to
;;; record n. MENU_COL must already hold the steel ramp (BuildMenuPal).
PlayGrayTables:
              php
              rep #0x30
              phb
              pea #0x0000
              plb
              plb                         ; DBR = 0: the records are stored abs,x/y
              lda ##0
              sta long:pgSlot
              sta long:pgPal
              lda ##PLAY_GRAY
              sta long:pgRec
pgSlotNext:   ldy ##0                     ; Y = 2 * color
pgColor:      tya
              clc
              adc long:pgPal
              tax
              lda long:SHR_PAL,x          ; $0RGB
              sta long:pgWord
              and ##0x000f                ; blue
              sta long:pgLight
              lda long:pgWord
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0x000f                ; green
              asl a
              sta long:pgTemp
              asl a
              clc
              adc long:pgTemp             ; 6 green
              adc long:pgLight
              sta long:pgLight
              lda long:pgWord
              xba
              and ##0x000f                ; red
              sta long:pgTemp
              asl a
              clc
              adc long:pgTemp             ; 3 red
              adc long:pgLight            ; lightness 0..150
              beq pgBlack
              cmp ##61
              bcc pgDark
              cmp ##121
              bcc pgMid
              lda ##13
              bra pgSlotSet
pgBlack:      lda ##0
              bra pgSlotSet
pgDark:       lda ##15
              bra pgSlotSet
pgMid:        lda ##14
pgSlotSet:    sta long:pgGray
              asl a
              tax
              lda long:MENU_COL,x         ; the menu gray of this slot
              pha
              tya
              clc
              adc long:pgRec
              tax
              pla
              sta abs:256,x               ; the record's palette, word 'color'
              tya
              lsr a
              tax                         ; X = color
              lda long:pgGray
              sep #0x20
              sta long:pgLow,x
              asl a
              asl a
              asl a
              asl a
              sta long:pgHigh,x
              rep #0x20
              iny
              iny
              cpy ##32
              bcs pgColorsDone
              jmp abs:.word0 (pgColor)
pgColorsDone: lda long:pgRec              ; the pair table: high nibble, then low
              tay
              sep #0x20
              ldx ##0
pgHighNext:   lda long:pgHigh,x
              sta long:pgHi
              phx
              ldx ##0
pgLowNext:    lda long:pgLow,x
              ora long:pgHi
              sta abs:0,y
              iny
              inx
              cpx ##16
              bcc pgLowNext
              plx
              inx
              cpx ##16
              bcc pgHighNext
              rep #0x20
              lda long:pgSlot
              tax
              lda long:pgRec
              ldy ##0
              jsl long:BindAddr           ; slot X: record A, bank 0
              lda long:pgRec
              clc
              adc ##288
              sta long:pgRec
              lda long:pgPal
              clc
              adc ##32
              sta long:pgPal
              lda long:pgSlot
              inc a
              sta long:pgSlot
              cmp ##16
              bcs pgDone
              jmp abs:.word0 (pgSlotNext)
pgDone:       plb
              plp
              rtl
pgSlot:       .word 0
pgPal:        .word 0
pgRec:        .word 0
pgWord:       .word 0
pgLight:      .word 0
pgTemp:       .word 0
pgGray:       .word 0
pgHi:         .word 0
pgLow:        .space 16
pgHigh:       .space 16

;;; A = first row, X = exclusive end. Whole rows, from the gray copy.
GrayCopyRows: php
              rep #0x30
              sta long:grayLo
              txa
              sta long:grayHi
copyLoop:     lda long:grayLo
              cmp long:grayHi
              bcs copyDone
              jsr abs:.word0 (grayPixRow)
              lda long:grayLo
              inc a
              sta long:grayLo
              bra copyLoop
copyDone:     plp
              rtl

;;; A = one row of the gray copy, onto the screen, still on palette 15.
PublishGrayRow: php
              rep #0x30
              jsr abs:.word0 (grayPixRow)
              plp
              rtl

 ;;; Restore once, without the former four-rows-per-frame wipe.
CloseRestore: php
              rep #0x30
              jsl long:WaitBlank
              phb
              ldx ##0x7e00
              ldy ##0x9e00
              lda ##511
              .byte 0x54, 0xe1, 0x41
              ldx ##0x7d00
              ldy ##0x9d00
              lda ##199
              .byte 0x54, 0xe1, 0x41
              ldx ##0
              ldy ##0x2000
              lda ##31999
              .byte 0x54, 0xe1, 0x41
              ldx ##0x8410
              ldy ##0x8000
              lda ##63
              .byte 0x54, 0x41, 0x41
              plb
              plp
              rtl

;;; A = row. Offset in grayTmp, screen address in X, row in grayTmp2.
row160:       sta long:grayTmp2
              pha
              asl a
              asl a
              asl a
              asl a
              asl a
              sta long:grayTmp
              pla
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc long:grayTmp
              sta long:grayTmp
              clc
              adc ##0x2000
              tax
              lda long:grayTmp
              rts

snapPix:      jsr abs:.word0 (row160)
              phb
              phx
              tax
              pla
              tay
              lda ##159
              .byte 0x54, 0xe1, 0x41
              plb
              rts

snapRowScb:   jsr abs:.word0 (snapPix)
              lda long:grayTmp2
              tax
              sep #0x20
              lda long:SNAP_SCB,x
              sta long:SHR_SCB,x
              rep #0x20
              rts

grayPixRow:   jsr abs:.word0 (row160)
              phb
              phx
              tax
              pla
              tay
              lda ##159
              .byte 0x54, 0xe1, 0x3d
              plb
              lda long:grayTmp2
              tax
              sep #0x20
              lda #15
              sta long:SHR_SCB,x
              rep #0x20
              rts

ClearGrayRows: php
              rep #0x30
              sep #0x20
              ldx ##0
              lda #0
clearDoneByte: sta long:ROW_DONE,x
              inx
              cpx ##200
              bcc clearDoneByte
              rep #0x20
              lda ##0
              sta long:GRAY_STEEL_ON
              plp
              rtl

