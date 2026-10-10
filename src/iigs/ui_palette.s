;;; Palette loads record their gray tables. This stays with the gray code,
;;; past the effect image, so the game bank does not carry it.
#include "frontend.inc"
              .section graycode, text, root, noreorder
              .public FloorToFadeCore, RevealFloorCore, StreamCachedPicture, cachedPictureDone
              .extern levelIndex, tintFloorOffsets, fadeBase, menuDim, screenBlack, WaitBlank
              .extern lumpTable, CopyMenuBlocks, streamLump, BindFullPicture, BindFloorSlots

;;; fadeBase gets palette 0 of this floor's tint (the menu's colors). The
;;; hardware stays black until FadeIn or RevealFloor.
FloorToFadeCore:  phb
              sep #0x20
              lda #2
              pha
              plb
              rep #0x30
              lda abs:.word0 (levelIndex)
              asl a
              tax
              lda abs:.word0 (tintFloorOffsets),x
              clc
              adc ##0x9000
              tax
              ldy ##.word0 (fadeBase)
              lda ##31
              .byte 0x54, 0x3f, 0x00         ; MVN: 32 bytes, bank 0 to bank $3F
              ldx ##32
              lda ##0
fadeClear:    sta abs:.word0 (fadeBase),x
              inx
              inx
              cpx ##512
              bcc fadeClear
              plb
              rtl

;;; The floor colors, at the blank, when this is not the gray game menu.
RevealFloorCore:  lda abs:.word0 (menuDim)
              bne floorHeld
              jsl long:WaitBlank
              ldx ##.word0 (fadeBase)
              ldy ##0x9e00
              lda ##511
              phb
              .byte 0x54, 0xe1, 0x3f         ; MVN: fadeBase to palette RAM
              plb
              stz abs:.word0 (screenBlack)
              jsl long:BindFloorSlots
floorHeld:    rtl

;;; Caller DBR is $3F and D is UI_DP. Cached pictures arrive under black
;;; palettes; only FadeIn publishes their completed pixels and scan-line bytes.
StreamCachedPicture:
              sta long:streamLump
              asl a
              asl a
              asl a
              tax
              lda abs:.word0 (lumpTable),x
              sta dp:U_T6
              clc
              adc ##62
              sta dp:U_BLK
              lda ##2
              sta dp:U_CNT
              lda ##0x9d00
              sta dp:U_DOFF
              lda ##0xe0
              sta dp:U_DBNK
              jsl long:CopyMenuBlocks
              lda dp:U_T6
              sta dp:U_BLK
              lda ##62
              sta dp:U_CNT
              lda ##0x2000
              sta dp:U_DOFF
              lda ##0xe1
              sta dp:U_DBNK
              jsl long:CopyMenuBlocks
              phb
              ldx ##0x9d00
              ldy ##0x9c00
              lda ##255
              .byte 0x54, 0xe1, 0xe0
              ldx ##0x9e00
              ldy ##0x9d00
              lda ##199
              .byte 0x54, 0xe1, 0xe0
              ldx ##0x9f00
              ldy ##.word0 (fadeBase)
              lda ##511
              .byte 0x54, 0x3f, 0xe0
              plb
              jsl long:BindFullPicture
cachedPictureDone:
              clc
              rtl
