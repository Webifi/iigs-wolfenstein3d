;;; Compose previews into the paused frame, then publish their
;;; pixels and palettes from the start of vertical blank. Native preview
;;; palettes already preserve the shared dark slots used by the gray cache.
#include "memmap.inc"
              .public PreviewPresent
              .extern updateSCB, UpdateFinish, UpdateTarget, fadeBase, WaitBlank

PreviewPresent:
              jsl long:WaitBlank
previewPublish:
              phb
              ldx ##.word0 (fadeBase+416)
              ldy ##0x9fa0
              lda ##63
              .byte 0x54, 0xe1, 0x3f
              lda dp:UD_ROW                 ; absolute source offset in the paused frame
              sta dp:UD_BUF
              lda dp:UD_H                 ; rectangle height
              sta dp:UD_N
              lda dp:UC_Y
              sta long:previewRow
previewCopyRow:
              ldx dp:UD_BUF
              lda dp:UD_ROW
              clc
              adc ##0x2000
              tay
              lda dp:UD_W                 ; rectangle width in bytes
              dec a
              .byte 0x54, 0xe1, 0x3c
              lda long:previewRow
              tax
              sep #0x20
              lda long:updateSCB,x
              sta long:SHR_SCB,x
              rep #0x20
              lda long:previewRow
              inc a
              sta long:previewRow
              lda dp:UD_ROW
              clc
              adc ##160
              sta dp:UD_ROW
              lda dp:UD_BUF
              clc
              adc ##160
              sta dp:UD_BUF
              dec dp:UD_N
              bne previewCopyRow
previewCopyDone:
              plb
              lda ##0x2000
              ldx ##0xe1
              jsr abs:.word0 (UpdateTarget)
              jmp long:UpdateFinish
previewRow:   .word 0
