;;; Firmware block calls for the front end. The slot driver requires bank 0
;;; code, D=0 and an emulation-mode page-1 stack. UiBlock restores the native
;;; stack, D, DBR and SHADOW after the call. Fill blk* parameters with long
;;; stores before JSL UiBlock; it returns A=error byte and carry set on error.

#include "memmap.inc"
              .section irqcode, text, root, noreorder
              .public UiBlock, blkCmd, blkUnit, blkBuf, blkNum, blkDriver, blkFast, UiEject, spEntry, UiFwKeep, UiFwPut

;;; FWSTATE reserves 2 KB after the resident UI data. fwKeep initializes
;;; the snapshot at boot; mkdisk.py rejects load segments that overlap it.

;;; blkFast bit 0 skips fwPut before the call; bit 1 skips fwKeep after it.
;;; Consecutive blocks in one transfer skip both on intermediate calls to
;;; avoid copying slow bank-$E1 RAM between sectors. The first/last calls
;;; retain the restore/snapshot boundaries for the complete transfer.
UiBlock:      php
              sei
              rep #0x30
              phb
              phd
              lda long:blkFast
              and ##1
              bne putSkipped
              jsr abs:.word0 (fwPut)
putSkipped:   lda ##0
              tcd
              sep #0x20
              lda #0
              pha
              plb
              lda long:SHADOW
              sta abs:.word0 (saveShadow)
              and #0xbf
              sta long:SHADOW
              rep #0x20
              lda dp:PD_CMD
              sta abs:.word0 (save42)
              lda dp:PD_BUF
              sta abs:.word0 (save44)
              lda dp:PD_BLOCK
              sta abs:.word0 (save46)
              lda abs:.word0 (blkCmd)
              sta dp:PD_CMD
              lda abs:.word0 (blkBuf)
              sta dp:PD_BUF
              lda abs:.word0 (blkNum)
              sta dp:PD_BLOCK
              tsx
              stx abs:.word0 (nativeStack)
              sep #0x30
              sec
              xce
              jsr abs:.word0 (driverJump)
              sta abs:.word0 (fwError)
              lda #0
              rol a
              sta abs:.word0 (fwCarry)
              clc
              xce
              rep #0x30
              ldx abs:.word0 (nativeStack)
              txs
              lda abs:.word0 (save42)
              sta dp:PD_CMD
              lda abs:.word0 (save44)
              sta dp:PD_BUF
              lda abs:.word0 (save46)
              sta dp:PD_BLOCK
              sep #0x20
              lda abs:.word0 (saveShadow)
              sta long:SHADOW
              rep #0x30
              lda abs:.word0 (blkFast)
              and ##2
              bne keepSkipped
              jsr abs:.word0 (fwKeep)
keepSkipped:  pld
              plb
              plp
              lda long:fwCarry
              lsr a
              lda long:fwError
              and ##255
              rtl
driverJump:   jmp (abs:.word0 (blkDriver))

;;; Protect firmware vectors and disk-driver state at $E1:0000-$03FF and
;;; $E1:0C00-$0FFF. fwPut compares the first 512 bytes with the snapshot;
;;; any mismatch restores both 1 KB ranges. This is a corruption guard, not
;;; a full state comparison. fwKeep refreshes both ranges after firmware use.
fwPut:        php
              rep #0x30
              phb
              ldx ##0
fwCheck:      lda long:BANK_E1,x
              cmp long:FWSTATE,x
              bne fwBack
              inx
              inx
              cpx ##512
              bcc fwCheck
              plb
              plp
              rts
fwBack:       ldx ##.word0 (FWSTATE)
              ldy ##0
              lda ##1023
              .byte 0x54, 0xe1, FWBANK       ; MVN: bank $41 to bank $E1
              ldx ##.word0 (FWSTATE + 1024)
              ldy ##0x0c00
              lda ##1023
              .byte 0x54, 0xe1, FWBANK
              plb
              plp
              rts
fwKeep:       php
              rep #0x30
              phb
              ldx ##0
              ldy ##.word0 (FWSTATE)
              lda ##1023
              .byte 0x54, FWBANK, 0xe1       ; MVN: bank $E1 to bank $41
              ldx ##0x0c00
              ldy ##.word0 (FWSTATE + 1024)
              lda ##1023
              .byte 0x54, FWBANK, 0xe1
              plb
              plp
              rts
UiFwKeep:     jsr abs:.word0 (fwKeep)
              rtl
UiFwPut:      jsr abs:.word0 (fwPut)
              rtl


;;; SmartPort CONTROL, eject (code 4) of the drive in A (1 or 2): a disk of this
;;; game that is not the one asked for goes out, as the loader does.
UiEject:      php
              sei
              rep #0x30
              phb
              phd
              sep #0x20
              sta long:spUnit               ; DBR is still the caller's
              rep #0x20
              jsr abs:.word0 (fwPut)
              sep #0x20
              lda #0
              pha
              plb
              rep #0x20
              lda ##0
              tcd
              sep #0x20
              lda long:SHADOW
              sta abs:.word0 (saveShadow)
              and #0xbf
              sta long:SHADOW
              rep #0x20
              tsx
              stx abs:.word0 (nativeStack)
              sep #0x30
              sec
              xce
              jsr abs:.word0 (spJump)
              .byte 4                       ; CONTROL
              .word .word0 (spParams)
              clc
              xce
              rep #0x30
              ldx abs:.word0 (nativeStack)
              txs
              sep #0x20
              lda abs:.word0 (saveShadow)
              sta long:SHADOW
              rep #0x30
              jsr abs:.word0 (fwKeep)
              pld
              plb
              plp
              rtl
spJump:       jmp (abs:.word0 (spEntry))
spParams:     .byte 3
spUnit:       .byte 1
              .word .word0 (spList)
              .byte 4                       ; the eject code
spList:       .byte 0, 0, 0, 0
spEntry:      .word 0                       ; the slot's SmartPort entry, set by DiskInit

blkCmd:       .byte 0                     ; $42: 1 read, 2 write
blkUnit:      .byte 0                     ; $43: ProDOS unit, drive in bit 7
blkBuf:       .word 0                     ; $44: buffer in bank 0
blkNum:       .word 0                     ; $46: block
blkFast:      .word 0                     ; see UiBlock
blkDriver:    .word 0                     ; the slot's ProDOS block driver
save42:       .word 0
save44:       .word 0
save46:       .word 0
nativeStack:  .word 0
saveShadow:   .byte 0
fwError:      .byte 0
fwCarry:      .word 0
