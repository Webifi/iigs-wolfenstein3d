#include "memmap.inc"
              .public PreviewCore
              .extern listPictures
              .extern BeginUpdate, EndUpdate, DrawWordBlock, fadeBase, updatePalette, updateSCB, BindPreviewLump
PreviewCore:   lda dp:UL_CUR
              ldx abs:.word0 (listPictures)
              cpx ##4
              beq previewEpisode
              cpx ##1
              beq previewPortrait
              clc
              asl a
              tay
              lda abs:.word0 (selectedFloorList)
              sta dp:U_T6
              lda (U_T6),y
              ora ##0x8000
              bra previewLoad
previewPortrait: clc
              adc ##LUMP_PORTRAIT0
              bra previewLoad
previewEpisode: clc
              adc ##EPISODE_PREVIEW_BASE
previewLoad:  cmp abs:.word0 (previewLast)
              bne previewChanged
              rtl
previewChanged: pha
              lda abs:.word0 (previewLast)
              sta long:previewOld
              pla
              sta abs:.word0 (previewLast)
              bit ##0x8000
              bne previewFloorRecord
              jsl long:LoadPreviewLump
              bra previewRecordReady
previewFloorRecord:
;;; Floor records occupy fixed 4 KB slots in the title-only art overlay.
              and ##15
              xba
              asl a
              asl a
              asl a
              asl a
              sta long:nativeRecord
              lda abs:.word0 (previewLast)
              and ##0x7fff
              lsr a
              lsr a
              lsr a
              lsr a
              clc
              adc ##.byte2 FLOOR_PREVIEWS
              sta long:nativeBank
previewRecordReady:
              lda long:nativeRecord
              sta dp:W_PTR
              lda long:nativeBank
              sta dp:W_PTR+2
              ldy ##0
              lda [0xb0],y
              sta dp:U_X
              iny
              iny
              lda [0xb0],y
              sta dp:U_Y
              iny
              iny
              lda [0xb0],y
              sta dp:U_W
              iny
              iny
              lda [0xb0],y
              sta dp:U_H
              lda long:previewOld
              cmp ##0xffff
              bne previewBoundsReady
              stz dp:U_X
              lda ##320
              sta dp:U_W
              ldy ##8
              lda [0xb0],y
              sta dp:U_Y
              ldx abs:.word0 (listPictures)
              dex
              txa
              asl a
              tax
              lda long:previewHeights,x
              sta dp:U_H
previewBoundsReady:
previewCompose:
              jsl long:BeginUpdate
previewColors:
              ldy ##10
              ldx ##416
previewPal:   lda [0xb0],y
              sta abs:.word0 (fadeBase),x
              iny
              iny
              inx
              inx
              cpx ##480
              bcc previewPal
              lda dp:U_Y
              ldy ##8
              sec
              sbc [0xb0],y
              clc
              adc ##74
              tay
              ldx dp:U_Y
              lda dp:U_H
              sta dp:U_T0
              sep #0x20
previewScb:   lda [0xb0],y
              sta long:updateSCB,x
              iny
              inx
              dec dp:U_T0
              bne previewScb
              rep #0x20
              ldy ##2
              lda [0xb0],y
              asl a
              asl a
              clc
              adc [0xb0],y
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:W_BASE
              ldy ##0
              lda [0xb0],y
              lsr a
              clc
              adc dp:W_BASE
              sta dp:W_BASE
              lda dp:W_PTR
              clc
              adc ##138
              tax
              stz dp:U_C
              jsl long:DrawWordBlock
previewWait:  lda long:framePending
              beq previewLive
              jsl long:EndUpdate
              jsl long:BindPreviewLump
              rtl
previewLive:  jsl long:PreviewPresent
              jsl long:BindPreviewLump
              rtl
previewOld: .word 0xffff
previewHeights: .word 52,56,64
              .word 48
              .extern PreviewPresent, framePending
              .extern nativeRecord, nativeBank
