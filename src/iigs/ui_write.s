;;; Writing WOLF.SETTINGS and WOLF.SETX on the home disk. Only Save Settings and
;;; a saved game get here; closing a menu, quitting and the benchmark never
;;; write the disk. Both blocks go out on the one visit NeedHomeDisk started,
;;; and the drive is released only after both have been read back.
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public WriteSettings
              .extern NeedHomeDisk, ReleaseDisk, BusyShow, BusyHide, UiBlock, blkCmd, blkUnit, blkBuf
              .extern blkNum, UiDrain, CollectSettings, SettingsSum, SettingsSumAll
              .extern ShowNote, settingsKnown, BusyBar, ExtSum, slotExt

;;; Write settings (including save-slot headers) and the name block.
;;; Carry is set if disk acquisition or write verification fails; this path
;;; handles its own error display, so callers must not show a second error.
WriteSettings:
              jsr abs:.word0 (CollectSettings)
              jsr abs:.word0 (SettingsSumAll)
              sta long:SETTINGS_IN + S_SUM
              jsl long:ExtSum
              sta long:slotExt + SX_SUM
              jsr abs:.word0 (NeedHomeDisk)
              bcc writeDisk
              jmp abs:.word0 (writeCancel)
writeDisk:    lda dp:U_UNIT
              and ##0x70
              cmp ##0x50
              bcc writeNoSign
              cmp ##0x70
              bcs writeNoSign
              lda ##1
              jsr abs:.word0 (BusyShow)
writeNoSign:  lda ##4
              sta dp:U_TOTAL
              stz dp:U_DONE
              jsr abs:.word0 (findSetx)
              bcs writeMissing
              ldx ##SETTINGS_IN
              ldy ##BUF
              lda ##511
              .byte 0x54, 0x00, 0x00         ; MVN: the settings image to the block buffer
              phk
              plb
              lda long:HDR_SETTINGS
              sta dp:U_BLK
              lda ##BUF
              sta dp:U_BUF
              jsr abs:.word0 (writeChecked)
              bcs writeFailed
              ldx ##.word0 (slotExt)
              ldy ##BUF
              lda ##511
              .byte 0x54, 0x00, 0x02         ; MVN: bank 2 names to the block buffer
              phk
              plb
              lda abs:.word0 (setxBlock)
              sta dp:U_BLK
              lda ##BUF
              sta dp:U_BUF
              jsr abs:.word0 (writeChecked)
              bcs writeFailed
              jsr abs:.word0 (BusyHide)
              jsr abs:.word0 (SettingsSum)
              sta abs:.word0 (settingsKnown)
              jsr abs:.word0 (ReleaseDisk)
              clc
              rts
writeMissing: lda ##0x27
writeFailed:  pha
              jsr abs:.word0 (BusyHide)
              pla
              cmp ##0x2b
              bne writeError
              lda ##.word0 (strProtected)
              bra writeNote
writeError:   lda ##.word0 (strWriteError)
writeNote:    sta dp:U_STR
              jsr abs:.word0 (ShowNote)
writeCancel:  jsr abs:.word0 (ReleaseDisk)
              sec
              rts

;;; The disk-1 header is still in HDR. The name block is the raw segment whose
;;; address is slotExt. Carry set when that segment is not on this disk.
findSetx:     sep #0x20
              lda long:HDR + 8
              rep #0x20
              and ##255
              beq findNone
              tay
              ldx ##0
findLoop:     lda long:HDR + 16,x
              cmp ##.word0 (slotExt)
              bne findNext
              sep #0x20
              lda long:HDR + 18,x
              cmp #2
              bne findNext8
              lda long:HDR + 19,x
              bne findNext8
              rep #0x20
              lda long:HDR + 22,x
              cmp ##1
              bne findNext
              lda long:HDR + 20,x
              sta abs:.word0 (setxBlock)
              clc
              rts
findNext8:    rep #0x20
findNext:     txa
              clc
              adc ##8
              tax
              dey
              bne findLoop
findNone:     sec
              rts

;;; Write U_BLK from BUF and read it back. Carry set, A = the reason, on failure.
writeChecked: lda ##2
              jsr abs:.word0 (blockCall)
              bcs checkedFail
              inc dp:U_DONE
              jsr abs:.word0 (BusyBar)
              lda ##HDR
              sta dp:U_BUF
              lda ##1
              jsr abs:.word0 (blockCall)
              bcs checkedFail
              ldx ##0
writeCompare: lda long:BUF,x
              cmp long:HDR,x
              bne writeBad
              inx
              inx
              cpx ##512
              bcc writeCompare
              inc dp:U_DONE
              jsr abs:.word0 (BusyBar)
              clc
              rts
writeBad:     lda ##0x27
checkedFail:  sec
              rts

;;; Block command A (1 read, 2 write) for drive U_UNIT, block U_BLK, buffer U_BUF.
blockCall:    and ##255
              sta dp:U_T0
              lda dp:U_UNIT
              and ##255
              xba
              ora dp:U_T0
              sta long:blkCmd
              lda dp:U_BLK
              sta long:blkNum
              lda dp:U_BUF
              sta long:blkBuf
              jsl long:UiBlock
              pha
              php
              jsl long:UiDrain
              plp
              pla
              rts

              .section menudata, data, root
              .public strProtected, strWriteError
setxBlock:    .word 0
strProtected: .asciz "The disk is write protected."
strWriteError: .asciz "The disk could not be written."
