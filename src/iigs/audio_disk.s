;;; Firmware returns by RTS in bank 0. Keep this small bridge beside the IRQ;
;;; its buffers and boot-drive record are the loader's existing platform area.
#include "memmap.inc"
              .section irqcode, text, root, noreorder
              .public SaveAudioSettings
              .extern soundVolume, musicVolume, settingsSaveStatus
SaveAudioSettings:
              php
              sei
              rep #0x30
              pha
              phx
              phy
              phd
              phb
              lda ##0
              tcd
              lda dp:PD_CMD
              pha
              lda dp:PD_BUF
              pha
              lda dp:PD_BLOCK
              pha
              sep #0x20
              lda #0
              pha
              plb
              lda long:SHADOW
              sta abs:.word0 (saveShadow)
              and #0xbf
              sta long:SHADOW
              rep #0x20
              lda ##4
              sta long:settingsSaveStatus
              lda abs:BOOTINFO
              cmp ##0x4244
              bne invalidBootInfo
              lda abs:BI_DRIVER
              cmp ##0xc100
              bcc invalidBootInfo
              cmp ##0xc800
              bcs invalidBootInfo
              sta abs:.word0 (saveDriver)
              lda abs:BI_SETBLOCK
              beq invalidBootInfo
              bra validBootInfo
invalidBootInfo:
              jmp abs:.word0 (saveExit)
validBootInfo: lda ##2
              sta long:settingsSaveStatus
              sep #0x20
              lda abs:BI_UNIT
              sta dp:PD_UNIT
              stz abs:.word0 (otherDrive)
trySettingsDisk:
              rep #0x20
              lda ##0x7800
              sta dp:PD_BUF
              lda ##1
              sta dp:PD_BLOCK
              sep #0x20
              lda #1
              sta dp:PD_CMD
              jsr abs:.word0 (settingsBlockIO)
              bcs tryOtherDrive
              lda abs:HDR
              cmp ##0x4f57
              bne tryOtherDrive
              lda abs:HDR+2
              cmp ##0x464c
              bne tryOtherDrive
              lda abs:HDR+4
              cmp ##0x5347
              bne tryOtherDrive
              lda abs:HDR_DISK
              eor abs:BI_HOME_DISK
              and ##0x7f                   ; the home disk (BI_HOME_DISK bit 7: the play cache mark)
              bne tryOtherDrive
              lda abs:HDR_BUILD
              cmp abs:BI_BUILD
              bne tryOtherDrive
              lda abs:HDR_BUILD+2
              cmp abs:BI_BUILD+2
              bne tryOtherDrive
              lda abs:HDR_SETTINGS
              cmp abs:BI_SETBLOCK
              beq settingsDiskFound
tryOtherDrive:sep #0x20
              lda abs:.word0 (otherDrive)
              beq anotherDrive
              jmp abs:.word0 (saveExit)
anotherDrive: inc abs:.word0 (otherDrive)
              lda dp:PD_UNIT
              eor #0x80
              sta dp:PD_UNIT
              bra trySettingsDisk
settingsDiskFound:
              sta dp:PD_BLOCK
              lda ##0x7a00
              sta dp:PD_BUF
              sep #0x20
              lda #1
              sta dp:PD_CMD
              jsr abs:.word0 (settingsBlockIO)
              bcs saveExit
              lda ##0x5357
              sta abs:BUF+S_AUDIO
              lda ##0x3144
              sta abs:BUF+S_AUDIO+2
              lda long:musicVolume
              xba
              ora long:soundVolume
              sta abs:BUF+S_AUDIO+4
              eor ##0xa55a
              sta abs:BUF+S_AUDIO+6
              stz abs:BUF+S_AUDIO+8
              stz abs:BUF+S_AUDIO+10
              stz abs:BUF+S_AUDIO+12
              stz abs:BUF+S_AUDIO+14
              lda ##3
              sta long:settingsSaveStatus
              sep #0x20
              lda #2
              sta dp:PD_CMD
              jsr abs:.word0 (settingsBlockIO)
              bcs saveExit
              ldx ##14
savedRecord:  lda abs:BUF+S_AUDIO,x
              sta abs:AUDIO_SETTINGS,x
              dex
              dex
              bpl savedRecord
              lda ##0
              sta long:settingsSaveStatus
saveExit:     sep #0x20
              lda abs:.word0 (saveShadow)
              sta long:SHADOW
              rep #0x30
              pla
              sta dp:PD_BLOCK
              pla
              sta dp:PD_BUF
              pla
              sta dp:PD_CMD
              plb
              pld
              ply
              plx
              pla
              lda long:settingsSaveStatus
              plp
              rtl

settingsBlockIO:
              rep #0x10
              tsx
              stx abs:.word0 (nativeSaveStack)
              sep #0x30
              sec
              xce
              jsr abs:.word0 (settingsFirmware)
              sta abs:.word0 (firmwareError)
              lda #0
              rol a
              sta abs:.word0 (firmwareCarry)
              clc
              xce
              rep #0x30
              ldx abs:.word0 (nativeSaveStack)
              txs
              lda abs:.word0 (firmwareCarry)
              and ##255
              lsr a
              rts
settingsFirmware:
              jmp (abs:.word0 (saveDriver))
saveDriver:   .word 0
nativeSaveStack:.word 0
saveShadow:   .byte 0
otherDrive:   .byte 0
firmwareError:.byte 0
firmwareCarry:.word 0


              .public copyPointer
copyPointer:  .byte 0,0,0
