;;; Bank-0 callers for the ROM text firmware and Applesoft.
#include "memmap.inc"
              .public UiQuitTextInit, UiQuitPrompt
              .extern UiQuitTextCopy
;;; Emulation-mode ROM calls use a bank-0 return address.
              .section irqcode, text, root, noreorder
UiQuitTextInit: sec
              xce
              ldx #0xff
              txs
              jsr abs:ROM_PR3
              clc
              xce
              rep #0x30
              jmp long:UiQuitTextCopy
UiQuitPrompt:   sec
              xce
              lda #21
              sta abs:ROM_CV
              jsr abs:ROM_VTAB
              lda #0
              sta abs:ROM_CH
              sta abs:ROM_OURCH
              jmp abs:ROM_BASIC

