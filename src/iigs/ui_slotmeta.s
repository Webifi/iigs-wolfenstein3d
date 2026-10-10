;;; Save-name metadata only; frontend owns the editor and key dispatch.
#include "frontend.inc"
              .section uiextra, text, root, noreorder
              .public SlotCount, SlotName, SlotNameStore, SlotQuick, SlotQuickSet, ExtCheck, ExtSum, slotExt
              .extern slotNameBuf
SlotCount:    php
              rep #0x30
              lda ##SLOTS
              plp
              rtl

;;; Copy slot A's 32-byte name into slotNameBuf. A = 0 when the name is empty.
SlotName:     php
              phb
              phk
              plb
              rep #0x30
              phx
              phy
              cmp ##10
              bcc nameLive
              jmp abs:.word0 (nameNone)
nameLive:     asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc ##SX_NAMES
              tax
              lda long:slotExt,x
              sta long:slotNameBuf
              lda long:slotExt + 2,x
              sta long:slotNameBuf + 2
              lda long:slotExt + 4,x
              sta long:slotNameBuf + 4
              lda long:slotExt + 6,x
              sta long:slotNameBuf + 6
              lda long:slotExt + 8,x
              sta long:slotNameBuf + 8
              lda long:slotExt + 10,x
              sta long:slotNameBuf + 10
              lda long:slotExt + 12,x
              sta long:slotNameBuf + 12
              lda long:slotExt + 14,x
              sta long:slotNameBuf + 14
              lda long:slotExt + 16,x
              sta long:slotNameBuf + 16
              lda long:slotExt + 18,x
              sta long:slotNameBuf + 18
              lda long:slotExt + 20,x
              sta long:slotNameBuf + 20
              lda long:slotExt + 22,x
              sta long:slotNameBuf + 22
              lda long:slotExt + 24,x
              sta long:slotNameBuf + 24
              lda long:slotExt + 26,x
              sta long:slotNameBuf + 26
              lda long:slotExt + 28,x
              sta long:slotNameBuf + 28
              lda long:slotExt + 30,x
              sta long:slotNameBuf + 30
              sep #0x20
              lda #0
              sta long:slotNameBuf + 31
              rep #0x20
              lda long:slotNameBuf
              and ##255
              beq nameNone
              lda ##1
              bra nameOut
nameNone:     ldx ##0
              lda ##0
nameWipe:     sta long:slotNameBuf,x
              inx
              inx
              cpx ##32
              bcc nameWipe
nameOut:      ply
              plx
              plb
              plp
              rtl

;;; Store the 32 bytes at X (current data bank) as slot A's name. A zero or
;;; byte 31 ends it, and the rest of the field is zero. Slots past 7 are ignored.
SlotNameStore:php
              rep #0x30
              phy
              phx
              pha
              sep #0x20
              phb
              pla
              sta long:nameBank
              rep #0x20
              phk
              plb
              pla
              sta abs:.word0 (nameSlot)
              lda 1,s
              sta abs:.word0 (nameSrc)
              lda abs:.word0 (nameSlot)
              cmp ##8
              bcc nameStoreLive
              jmp abs:.word0 (nameStoreOut)
nameStoreLive:ldx abs:.word0 (nameSrc)
              ldy ##.word0 (slotStoreBuf)
              sep #0x20
              lda long:nameBank
              sta abs:.word0 (storeMvn + 2)
              rep #0x20
              lda ##31
storeMvn:     .byte 0x54, 0x0f, 0x00
              phk
              plb
              sep #0x20
              ldy ##0
nameScan:     cpy ##31
              bcs nameZero
              lda abs:.word0 (slotStoreBuf),y
              beq nameZero
              iny
              bra nameScan
nameZero:     lda #0
nameFill:     cpy ##32
              bcs nameFilled
              sta abs:.word0 (slotStoreBuf),y
              iny
              bra nameFill
nameFilled:   rep #0x20
              lda abs:.word0 (nameSlot)
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc ##SX_NAMES
              tax
              lda abs:.word0 (slotStoreBuf)
              sta long:slotExt,x
              lda abs:.word0 (slotStoreBuf + 2)
              sta long:slotExt + 2,x
              lda abs:.word0 (slotStoreBuf + 4)
              sta long:slotExt + 4,x
              lda abs:.word0 (slotStoreBuf + 6)
              sta long:slotExt + 6,x
              lda abs:.word0 (slotStoreBuf + 8)
              sta long:slotExt + 8,x
              lda abs:.word0 (slotStoreBuf + 10)
              sta long:slotExt + 10,x
              lda abs:.word0 (slotStoreBuf + 12)
              sta long:slotExt + 12,x
              lda abs:.word0 (slotStoreBuf + 14)
              sta long:slotExt + 14,x
              lda abs:.word0 (slotStoreBuf + 16)
              sta long:slotExt + 16,x
              lda abs:.word0 (slotStoreBuf + 18)
              sta long:slotExt + 18,x
              lda abs:.word0 (slotStoreBuf + 20)
              sta long:slotExt + 20,x
              lda abs:.word0 (slotStoreBuf + 22)
              sta long:slotExt + 22,x
              lda abs:.word0 (slotStoreBuf + 24)
              sta long:slotExt + 24,x
              lda abs:.word0 (slotStoreBuf + 26)
              sta long:slotExt + 26,x
              lda abs:.word0 (slotStoreBuf + 28)
              sta long:slotExt + 28,x
              lda abs:.word0 (slotStoreBuf + 30)
              sta long:slotExt + 30,x
nameStoreOut: sep #0x20
              lda abs:.word0 (nameBank)
              pha
              plb
              rep #0x20
              plx
              ply
              plp
              rtl

;;; A = the quick slot, or 255 when none has been saved or loaded.
SlotQuick:    php
              phb
              phk
              plb
              rep #0x30
              sep #0x20
              lda long:slotExt + SX_QUICK
              rep #0x20
              and ##255
              plb
              plp
              rtl

;;; Remember slot A (0-7, or 255). Slots 8 and 9 stay unused.
SlotQuickSet: php
              phb
              phk
              plb
              rep #0x30
              cmp ##255
              beq quickStore
              cmp ##8
              bcs quickKeep
quickStore:   sep #0x20
              sta long:slotExt + SX_QUICK
              rep #0x20
quickKeep:    plb
              plp
              rtl

;;; A = the sum of bytes 10-511 of the name block.
ExtSum:       ldx ##SX_QUICK
              stz dp:U_T0
extWord:      lda long:slotExt,x
              pha
              and ##255
              clc
              adc dp:U_T0
              sta dp:U_T0
              pla
              xba
              and ##255
              clc
              adc dp:U_T0
              sta dp:U_T0
              inx
              inx
              cpx ##512
              bcc extWord
              lda dp:U_T0
              rtl

;;; A bad or missing name block becomes an empty valid one. The eight headers stay.
ExtCheck:     ldx ##0
extMagic:     sep #0x20
              lda long:slotExt,x
              cmp long:sxMagic,x
              rep #0x20
              beq extMagicOk
              jmp abs:.word0 (ExtReset)
extMagicOk:   inx
              cpx ##8
              bcc extMagic
              jsl long:ExtSum
              cmp long:slotExt + SX_SUM
              beq extSumOk
              jmp abs:.word0 (ExtReset)
extSumOk:     sep #0x20
              lda long:slotExt + SX_QUICK
              cmp #8
              bcc extCount
              cmp #255
              bne extBad8
extCount:     lda long:slotExt + SX_COUNT
              cmp #8
              bne extBad8
              ldx ##SX_PAD
extPad:       lda long:slotExt,x
              bne extBad8
              inx
              cpx ##SX_NAMES
              bcc extPad
              rep #0x20
              ldx ##SX_TAIL
extTail:      lda long:slotExt,x
              bne ExtReset
              inx
              inx
              cpx ##512
              bcc extTail
              rtl
extBad8:      rep #0x20
              jmp abs:.word0 (ExtReset)
ExtReset:     ldx ##0
              lda ##0
extClr:       sta long:slotExt,x
              inx
              inx
              cpx ##512
              bcc extClr
              ldx ##0
extPut:       sep #0x20
              lda long:sxMagic,x
              sta long:slotExt,x
              rep #0x20
              inx
              cpx ##8
              bcc extPut
              sep #0x20
              lda #0xff
              sta long:slotExt + SX_QUICK
              lda #8
              sta long:slotExt + SX_COUNT
              rep #0x20
              jsl long:ExtSum
              sta long:slotExt + SX_SUM
              rtl

slotStoreBuf:     .space 32
nameSlot:     .word 0
nameSrc:      .word 0
nameBank:     .word 0
sxMagic:      .ascii "WOLFSLT1"
              .section slotnames, data, root
slotExt:      .ascii "WOLFSLT1"
              .word 263
              .byte 255, 8, 0, 0, 0, 0
              .space 496
