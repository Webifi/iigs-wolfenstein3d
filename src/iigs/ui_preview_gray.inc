#include "memmap.inc"
#include "gray.inc"
#include "menu.inc"
              .public BindPreviewLump
              .extern BindIndexed, BindAddr, nativeRecord, nativeBank, previewLast
              .section uiextra, text, root, noreorder
;;; previewLast is the lump whose two palettes were written to slots 13 and 14.
BindPreviewLump:
              lda long:previewLast
              bmi prevPool
              sec
              sbc ##LUMP_PORTRAIT0
              cmp ##4
              bcs prevMenuPicture
prevPool:
              lda long:nativeRecord
              clc
              adc ##FLOOR_PREVIEW_GRAY
              pha
              pha
              lda long:nativeBank
              tay
              pla
              ldx ##13
              jsl long:BindAddr
              pla
              clc
              adc ##288
              pha
              lda long:nativeBank
              tay
              pla
              ldx ##14
              jsl long:BindAddr
              rtl
prevMenuPicture:
              lda long:previewLast
              sec
              sbc ##EPISODE_PREVIEW_BASE
              cmp ##GRAY_PREVIEW_COUNT
              bcs prevNo
              asl a
              asl a
              asl a
              clc
              adc ##OFF_EPISODE_PREV
              sta long:prevBase
              tax
              lda ##13
              jsl long:BindIndexed
              lda long:prevBase
              clc
              adc ##4
              tax
              lda ##14
              jsl long:BindIndexed
prevNo:       rtl

prevBase:     .word 0
