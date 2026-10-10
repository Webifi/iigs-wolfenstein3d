;;; Paused menu frame: $3C:0000-7CFF. The gray catalog is build-limited
;;; to bank $3B. Original pixels remain in $41 and clean gray in $3D.
;;; A complete list is drawn once in fast RAM, including its preview hook.
#include "memmap.inc"
              .public FramePresent, FrameFadePresent, NormalizeGray, framePending, frameEntry
              .extern PalBlack, fadeBase
framePending: .word 0
frameEntry:   .word 0
frameCopyEnd: .word 32000
frameEndRow:  .word 200
frameRow:     .word 0
frameOffset:  .word 0
frameGraySlot: .word 15
frameUsed:    .space 16

FrameClipAll: stz dp:UC_FIRST
              stz dp:UC_Y
              lda ##32000
              sta dp:UC_END
              lda ##200
              sta dp:UC_BOTTOM
              rts

FrameBegin:   lda ##1
              sta long:projectionCold
              lda long:pageBottom
              pha
              lda long:frameEntry
              tax
              pla
              cpx ##0
              beq frameBeginExtent
              lda ##200
frameBeginExtent:
              sta long:frameEndRow
              asl a
              asl a
              clc
              adc long:frameEndRow
              asl a
              asl a
              asl a
              asl a
              asl a
              sta long:frameCopyEnd
              lda long:frameEntry
              bne frameBackgroundReady
              jsr abs:.word0 (FrameBackground)
frameBackgroundReady:
              ldx ##0
              sep #0x20
              lda #15
frameInitScb: sta long:updateSCB,x
              inx
              cpx ##200
              bcc frameInitScb
              rep #0x20
              jsr abs:.word0 (FrameClipAll)
              stz dp:UD_BASE
              lda ##1
              sta long:composing
              sta long:screenBlack
              lda ##0
              ldx ##0x3c
              jsr abs:.word0 (UpdateTarget)
              rts

;;; Re-encode the already-dim picture under one palette before the heading
;;; palettes are reused. At entry, use a palette no source row references.
;;; On later pages only the old heading/picture rows need normalization.
NormalizeGray: php
              rep #0x30
              phb
              lda ##15
              sta long:frameGraySlot
              lda long:frameEntry
              beq frameNormalizeRows
              sep #0x20
              lda #0x41
              pha
              plb
              ldx ##15
              lda #0
frameClearUsed: sta long:frameUsed,x
              dex
              bpl frameClearUsed
              ldx ##0
frameCountUsed: lda long:SHR_SCB,x
              and #15
              rep #0x20
              and ##255
              tay
              sep #0x20
              lda #1
              sta abs:.word0 (frameUsed),y
              inx
              cpx ##200
              bcc frameCountUsed
              ldx ##15
frameFindFree: lda long:frameUsed,x
              beq frameFreePalette
              dex
              bpl frameFindFree
              rep #0x20
              ; Defensive fallback for an unanticipated all-16-palette source.
              ; Shipped title/game sources have at least one unused palette.
              jsl long:PalBlack
              bra frameNormalizeRows
frameFreePalette:
              rep #0x20
              txa
              sta long:frameGraySlot
              jsr abs:.word0 (FrameWriteGrayPalette)
frameNormalizeRows:
              sep #0x20
              lda #0x3d
              pha
              plb
              rep #0x20
              lda ##0
              sta long:frameRow
              sta long:frameOffset
frameNormalizeRow:
              lda long:frameEntry
              beq frameNormalizeExisting
              lda long:framePending
              beq frameNormalizeCopy
              lda long:frameRow
              tax
              lda long:SHR_SCB,x
              and ##15
              cmp ##15
              bne frameNormalizeNext
              bra frameNormalizeCopy
frameNormalizeExisting:
              lda long:frameRow
              tax
              sep #0x20
              lda long:SHR_SCB,x
              and #15
              cmp long:frameGraySlot
              rep #0x20
              beq frameNormalizeNext
frameNormalizeCopy:
              lda long:frameOffset
              tax
              jsr abs:.word0 (FrameCopyRow)
              lda long:frameRow
              tax
              sep #0x20
              lda long:frameGraySlot
              sta long:SHR_SCB,x
              rep #0x20
frameNormalizeNext:
              lda long:frameOffset
              clc
              adc ##160
              sta long:frameOffset
              lda long:frameRow
              inc a
              sta long:frameRow
              cmp ##200
              bcc frameNormalizeRow
              lda long:frameEntry
              beq frameNormalized
              lda ##15
              jsr abs:.word0 (FrameWriteGrayPalette)
              lda long:framePending
              bne frameNormalized
              ldx ##0
              sep #0x20
              lda #15
frameStandardScb:
              sta long:SHR_SCB,x
              inx
              cpx ##200
              bcc frameStandardScb
              rep #0x20
              lda ##0
              sta long:frameEntry
frameNormalized:
              plb
              plp
              rtl

;;; A = unused palette slot. The pixel indices are already prepared.
FrameWriteGrayPalette:
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc ##0x9e00
              tay
              phb
              sep #0x20
              lda #0xe1
              pha
              plb
              rep #0x20
              ldx ##0
frameGrayColor:
              lda long:MENU_COL,x
              sta abs:0,y
              inx
              inx
              iny
              iny
              cpx ##32
              bcc frameGrayColor
              plb
              rts

;;; Publish body rows directly into the common palette. Only rows that need
;;; colored title/picture palettes require a gray staging copy. This frees old
;;; palette slots without copying the whole screen twice.
FramePresent: lda long:framePending
              bne framePresentGo
              rtl
framePresentGo:
              lda long:frameEntry
              beq frameBodyStart
              jsl long:NormalizeGray
frameBodyStart:
              phb
              lda ##0
              sta long:frameRow
              sta long:frameOffset
frameBodyRow:
              lda long:frameRow
              tax
              sep #0x20
              lda long:updateSCB,x
              cmp #15
              beq frameBodyFinal
              lda long:SHR_SCB,x
              and #15
              cmp #15
              beq frameBodyNext8
              lda #0x3d
              bra frameBodyBank
frameBodyFinal:
              lda #0x3c
frameBodyBank:
              pha
              plb
              rep #0x20
              lda long:frameOffset
              tax
              jsr abs:.word0 (FrameCopyRow)
              lda long:frameRow
              tax
              sep #0x20
              lda #15
              sta long:SHR_SCB,x
frameBodyNext8:
              rep #0x20
              jsr abs:.word0 (FrameNextRow)
              bcc frameBodyRow
              plb
              jsl long:WaitBlank
              phb
              ldx ##.word0 (fadeBase)
              ldy ##0x9e00
              lda ##511
              .byte 0x54, 0xe1, 0x3f
              sep #0x20
              lda #0x3c
              pha
              plb
              rep #0x20
              lda ##0
              sta long:frameRow
              sta long:frameOffset
framePresentRow:
              lda long:frameRow
              tax
              sep #0x20
              lda long:updateSCB,x
              cmp #15
              rep #0x20
              beq framePresentNext
              lda long:frameOffset
              tax
              jsr abs:.word0 (FrameCopyRow)
              lda long:frameRow
              tax
              sep #0x20
              lda long:updateSCB,x
              sta long:SHR_SCB,x
              rep #0x20
framePresentNext:
              jsr abs:.word0 (FrameNextRow)
              bcc framePresentRow
framePixelsDone:
              plb
              jsr abs:.word0 (FrameFinish)
              rtl

;;; The caller has faded to black. Copy the complete composed page and its
;;; row controls, keeping all hardware colors black until the caller fades in.
FrameFadePresent:
              phb
              ldx ##0
              ldy ##0x2000
              lda ##31999
              .byte 0x54, 0xe1, 0x3c
              ldx ##.word0 (updateSCB)
              ldy ##0x9d00
              lda ##199
              .byte 0x54, 0xe1, 0x41
              plb
              jsr abs:.word0 (FrameFinish)
              lda ##1
              sta long:screenBlack
              rtl

FrameFinish:
              lda ##0x2000
              ldx ##0xe1
              jsr abs:.word0 (UpdateTarget)
              jsr abs:.word0 (FrameClipAll)
              lda ##0
              sta long:frameEntry
              sta long:framePending
              sta long:composing
              sta long:screenBlack
              sta long:menuPaletteDirty
              jsr abs:.word0 (MenuMark)
              rts

FrameNextRow: lda long:frameOffset
              clc
              adc ##160
              sta long:frameOffset
              lda long:frameRow
              inc a
              sta long:frameRow
              cmp long:frameEndRow
              rts

;;; DBR = source bank ($3C frame or $3D gray), X = row's byte offset.
;;; Word copies keep the period between new pixels and their SCB short.
FrameCopyRow:
              lda abs:0x0000,x
              sta long:SHR+0,x
              lda abs:0x0002,x
              sta long:SHR+2,x
              lda abs:0x0004,x
              sta long:SHR+4,x
              lda abs:0x0006,x
              sta long:SHR+6,x
              lda abs:0x0008,x
              sta long:SHR+8,x
              lda abs:0x000a,x
              sta long:SHR+10,x
              lda abs:0x000c,x
              sta long:SHR+12,x
              lda abs:0x000e,x
              sta long:SHR+14,x
              lda abs:0x0010,x
              sta long:SHR+16,x
              lda abs:0x0012,x
              sta long:SHR+18,x
              lda abs:0x0014,x
              sta long:SHR+20,x
              lda abs:0x0016,x
              sta long:SHR+22,x
              lda abs:0x0018,x
              sta long:SHR+24,x
              lda abs:0x001a,x
              sta long:SHR+26,x
              lda abs:0x001c,x
              sta long:SHR+28,x
              lda abs:0x001e,x
              sta long:SHR+30,x
              lda abs:0x0020,x
              sta long:SHR+32,x
              lda abs:0x0022,x
              sta long:SHR+34,x
              lda abs:0x0024,x
              sta long:SHR+36,x
              lda abs:0x0026,x
              sta long:SHR+38,x
              lda abs:0x0028,x
              sta long:SHR+40,x
              lda abs:0x002a,x
              sta long:SHR+42,x
              lda abs:0x002c,x
              sta long:SHR+44,x
              lda abs:0x002e,x
              sta long:SHR+46,x
              lda abs:0x0030,x
              sta long:SHR+48,x
              lda abs:0x0032,x
              sta long:SHR+50,x
              lda abs:0x0034,x
              sta long:SHR+52,x
              lda abs:0x0036,x
              sta long:SHR+54,x
              lda abs:0x0038,x
              sta long:SHR+56,x
              lda abs:0x003a,x
              sta long:SHR+58,x
              lda abs:0x003c,x
              sta long:SHR+60,x
              lda abs:0x003e,x
              sta long:SHR+62,x
              lda abs:0x0040,x
              sta long:SHR+64,x
              lda abs:0x0042,x
              sta long:SHR+66,x
              lda abs:0x0044,x
              sta long:SHR+68,x
              lda abs:0x0046,x
              sta long:SHR+70,x
              lda abs:0x0048,x
              sta long:SHR+72,x
              lda abs:0x004a,x
              sta long:SHR+74,x
              lda abs:0x004c,x
              sta long:SHR+76,x
              lda abs:0x004e,x
              sta long:SHR+78,x
              lda abs:0x0050,x
              sta long:SHR+80,x
              lda abs:0x0052,x
              sta long:SHR+82,x
              lda abs:0x0054,x
              sta long:SHR+84,x
              lda abs:0x0056,x
              sta long:SHR+86,x
              lda abs:0x0058,x
              sta long:SHR+88,x
              lda abs:0x005a,x
              sta long:SHR+90,x
              lda abs:0x005c,x
              sta long:SHR+92,x
              lda abs:0x005e,x
              sta long:SHR+94,x
              lda abs:0x0060,x
              sta long:SHR+96,x
              lda abs:0x0062,x
              sta long:SHR+98,x
              lda abs:0x0064,x
              sta long:SHR+100,x
              lda abs:0x0066,x
              sta long:SHR+102,x
              lda abs:0x0068,x
              sta long:SHR+104,x
              lda abs:0x006a,x
              sta long:SHR+106,x
              lda abs:0x006c,x
              sta long:SHR+108,x
              lda abs:0x006e,x
              sta long:SHR+110,x
              lda abs:0x0070,x
              sta long:SHR+112,x
              lda abs:0x0072,x
              sta long:SHR+114,x
              lda abs:0x0074,x
              sta long:SHR+116,x
              lda abs:0x0076,x
              sta long:SHR+118,x
              lda abs:0x0078,x
              sta long:SHR+120,x
              lda abs:0x007a,x
              sta long:SHR+122,x
              lda abs:0x007c,x
              sta long:SHR+124,x
              lda abs:0x007e,x
              sta long:SHR+126,x
              lda abs:0x0080,x
              sta long:SHR+128,x
              lda abs:0x0082,x
              sta long:SHR+130,x
              lda abs:0x0084,x
              sta long:SHR+132,x
              lda abs:0x0086,x
              sta long:SHR+134,x
              lda abs:0x0088,x
              sta long:SHR+136,x
              lda abs:0x008a,x
              sta long:SHR+138,x
              lda abs:0x008c,x
              sta long:SHR+140,x
              lda abs:0x008e,x
              sta long:SHR+142,x
              lda abs:0x0090,x
              sta long:SHR+144,x
              lda abs:0x0092,x
              sta long:SHR+146,x
              lda abs:0x0094,x
              sta long:SHR+148,x
              lda abs:0x0096,x
              sta long:SHR+150,x
              lda abs:0x0098,x
              sta long:SHR+152,x
              lda abs:0x009a,x
              sta long:SHR+154,x
              lda abs:0x009c,x
              sta long:SHR+156,x
              lda abs:0x009e,x
              sta long:SHR+158,x
              rts

;;; A later page resets only the old/new row union. First entry already filled
;;; this frame alongside the gray conversion, so it needs no background copy.
FrameBackground:
              phb
              sep #0x20
              lda #0x3d
              pha
              plb
              rep #0x20
              ldx ##0
frameBackgroundBlock:
              lda abs:0x0000,x
              sta long:SPR_RECORDS,x
              lda abs:0x0002,x
              sta long:SPR_RECORDS+0x2,x
              lda abs:0x0004,x
              sta long:SPR_RECORDS+0x4,x
              lda abs:0x0006,x
              sta long:SPR_RECORDS+0x6,x
              lda abs:0x0008,x
              sta long:SPR_RECORDS+0x8,x
              lda abs:0x000a,x
              sta long:SPR_RECORDS+0xa,x
              lda abs:0x000c,x
              sta long:SPR_RECORDS+0xc,x
              lda abs:0x000e,x
              sta long:SPR_RECORDS+0xe,x
              lda abs:0x0010,x
              sta long:SPR_RECORDS+0x10,x
              lda abs:0x0012,x
              sta long:SPR_RECORDS+0x12,x
              lda abs:0x0014,x
              sta long:SPR_RECORDS+0x14,x
              lda abs:0x0016,x
              sta long:SPR_RECORDS+0x16,x
              lda abs:0x0018,x
              sta long:SPR_RECORDS+0x18,x
              lda abs:0x001a,x
              sta long:SPR_RECORDS+0x1a,x
              lda abs:0x001c,x
              sta long:SPR_RECORDS+0x1c,x
              lda abs:0x001e,x
              sta long:SPR_RECORDS+0x1e,x
              txa
              clc
              adc ##32
              tax
              cmp long:frameCopyEnd
              bcc frameBackgroundBlock
              plb
              rts
