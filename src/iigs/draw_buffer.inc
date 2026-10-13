;;; Optional fast-RAM painting. Cold setters restore every original instruction
;;; when disabled; direct painting has no flag test. Buffered stores use the
;;; ordinary prepared spans. A row-order copy publishes their vertical hull.
#include "memmap.inc"
#include "campaign.inc"
#include "frontend.inc"
              .extern preparedAll, deferDone, deferOp, paintListDone, bufferFinishHook
              .extern drawWeaponPose, weaponPoseBank, weaponPoseCall, weaponDrawerEntries
              .extern viewWidth, viewLeft, viewTop, viewBottom, viewScaleExit, viewScaleBottom, rowX160
              .extern weapon, weaponReady, weaponFrame, weaponViewIndex, levelState
              .extern weaponMaskTable, oldWeaponMaskTable, flatOp, flatCode
              .extern vsyncOn, VsyncSet, J13SettingsLoad, J13SettingsStore
              .public BufferVsyncSet, BufferLoad, BufferStore, BufferToggle, bufferOn
              .public BufferReady, BufferDeferred, BufferFinish, bufferSlamStart, bufferSlamEnd

;;; Dedicated direct-page scratch in the resident bank-zero code tail.
BP            .equ 0                    ; prepared-list pointer (bank zero)
CP            .equ 4                    ; scaler or weapon-code pointer
SZ            .equ 8
CT            .equ 10
CB            .equ 12
COLN          .equ 14
LT            .equ 16
LB            .equ 18
LASTCOL       .equ 20
MINROW        .equ 22                   ; byte offsets, exclusive bottom
MAXROW        .equ 24
TEMP          .equ 26
INDEX         .equ 28
ODD           .equ 30
STOPX         .equ 32
DEFERRED      .equ 34
DEFCOL        .equ 36
VIEWMIN       .equ 38
VIEWMAX       .equ 40
              .section bufferirq, text, root
bufferDP:     .space 42
bufferOn:     .word 0
bufferValid:  .word 0
bufferPatch:  .word 0
#include "buffer_weapon.inc"
#include "buffer_scalers.inc"

              .section buffertail, text, root
bufferBridge: jmp long:BufferReady
bufferDeferBridge: jmp long:BufferDeferred

              .section buffersave, text, root
BufferVsyncSet:
              php
              rep #0x30
              and ##1
              sta long:vsyncOn
              jsr abs:.word0 (bufferHooks)
              plp
              rtl
BufferToggle: lda long:bufferOn
              eor ##1
BufferSet:    php
              rep #0x30
              and ##1
              cmp long:bufferOn
              beq bufferSetDone
              sta long:bufferOn
              jsl long:bufferPatchAll
              lda ##0
              sta long:bufferValid
              jsr abs:.word0 (bufferHooks)
bufferSetDone:plp
              rtl
BufferLoad:   jsl long:J13SettingsLoad
              lda long:SETTINGS_IN+S_VSYNC
              jsl long:BufferVsyncSet
              jmp long:WallPaintLoad
BufferStore:  jsl long:J13SettingsStore
              sep #0x20
              lda long:vsyncOn
              sta long:SETTINGS_IN+S_VSYNC
              rep #0x20
              jmp long:WallPaintStore
bufferHooks:  lda long:bufferOn
              beq bufferHooksDirect
              lda ##.word0 (bufferBridge)
              sta long:preparedAll+1
              lda ##.word0 (bufferDeferBridge)
              sta long:deferDone+1
              lda ##.word0 (BufferFinish)
              sta long:bufferFinishHook+1
              lda ##.byte2 (BufferFinish)
              sep #0x20
              sta long:bufferFinishHook+3
              lda #0x4c
              sta long:preparedAll
              sta long:deferDone
              rep #0x20
              rts
bufferHooksDirect:
              lda ##.word0 (drawWeaponPose)
              sta long:bufferFinishHook+1
              lda ##.byte2 (drawWeaponPose)
              sep #0x20
              sta long:bufferFinishHook+3
              rep #0x20
              lda ##0x20e2
              sta long:preparedAll
              sta long:deferDone
              sep #0x20
              lda #0x6b
              sta long:preparedAll+2
              sta long:deferDone+2
              rep #0x20
              lda long:vsyncOn
              beq bufferHooksDone
              lda ##.word0 (vsyncB)
              sta long:preparedAll+1
              sep #0x20
              lda #0x4c
              sta long:preparedAll
              rep #0x20
bufferHooksDone:rts

;;; Patch complete scaler bodies, even beyond a persistent view exit.
;;; The generator supplies the row counts; no opcode-like data is searched.
              .section bufferirq, text, root
bufferPatchAll:
              phb
              phd
              lda ##.word0 (bufferDP)
              tcd
              lda ##.byte2 (SEG_SCALE3)
              sta dp:CP+2
              stz dp:INDEX
bufferPatchBank:
              lda ##BUFFER_SCALER_HEAD+4                ; first STA operand after the stub header
              sta dp:CP
bufferPatchFunction:
              ldx dp:INDEX
              lda long:bufferScaleRows,x
              and ##255
              beq bufferPatchBankEnd
              inc dp:INDEX
              sta dp:CT
bufferPatchRow:
              lda long:bufferOn
              beq bufferPatchRowOff
              lda [CP]
              clc
              adc ##.word0 (DRAW_BUFFER-SHR)
              bra bufferPatchOperand
bufferPatchRowOff:
              lda [CP]
              sec
              sbc ##.word0 (DRAW_BUFFER-SHR)
bufferPatchOperand:
              sta [CP]
              lda long:bufferOn
              beq bufferPatchBankOff
              lda ##.byte2 (DRAW_BUFFER)
              bra bufferPatchDestBank
bufferPatchBankOff:
              lda ##.byte2 (SHR)
bufferPatchDestBank:
              ldy ##2
              sep #0x20
              sta [CP],y
              rep #0x20
              lda dp:CP
              clc
              adc ##7
              sta dp:CP
              dec dp:CT
              bne bufferPatchRow
              inc dp:CP                 ; terminal RTL
              bra bufferPatchFunction
bufferPatchBankEnd:
              inc dp:INDEX
              inc dp:CP+2
              lda dp:CP+2
              cmp ##.byte2 (SEG_SCALE5)+1
              bcc bufferPatchBank
              lda ##.word0 (flatCode+1)
              sta dp:CP
              lda ##.byte2 (flatCode)
              sta dp:CP+2
              lda long:bufferOn
              beq bufferFlatOff
              lda ##.word0 (DRAW_BUFFER-160*160)
              ldx ##.byte2 (DRAW_BUFFER-160*160)
              bra bufferFlatBase
bufferFlatOff:lda ##.word0 (SHR-160*160)
              ldx ##.byte2 (SHR-160*160)
bufferFlatBase:
              stx dp:CB
              ldx ##160
bufferFlatPatch:
              sta [CP]
              pha
              lda dp:CB
              ldy ##2
              sep #0x20
              sta [CP],y
              rep #0x20
              lda dp:CP
              clc
              adc ##4
              sta dp:CP
              pla
              clc
              adc ##160
              bcc bufferFlatNext
              inc dp:CB
bufferFlatNext:dex
              bne bufferFlatPatch
              lda long:bufferValid
              beq bufferPatchNoWeapon
              jsl long:bufferPatchWeapons
bufferPatchNoWeapon:
              pld
              plb
              rtl

;;; Pose code is rebuilt by a view or floor load. FIRST rechecks
;;; its literal stores; already redirected routines, including aliases, stay put.
bufferPatchWeapons:
              phd
              lda ##.word0 (bufferDP)
              tcd
              stz dp:INDEX
bufferWeaponNext:
              ldx dp:INDEX
              lda long:weaponDrawerEntries,x
              sta dp:CP
              lda long:weaponDrawerEntries+2,x
              and ##255
              sta dp:CP+2
              bne bufferWeaponPresent
              jmp abs:.word0 (bufferWeaponDone)
bufferWeaponPresent:
              lda long:weaponDrawerEntries+2,x
              xba
              and ##255
              cmp long:bufferOn
              bne bufferWeaponNeedsPatch
              jmp abs:.word0 (bufferWeaponDone)
bufferWeaponNeedsPatch:
              lda long:bufferOn
              xba
              ora dp:CP+2
              sta long:weaponDrawerEntries+2,x
              lda ##3
              sta dp:SZ                 ; word LDA immediate
bufferWeaponOp:
              lda [CP]
              and ##255
              cmp ##0x6b
              beq bufferWeaponDone
              cmp ##0x8d
              beq bufferWeaponStore
              cmp ##0xa9
              beq bufferWeaponLoad
              cmp ##0xe2
              beq bufferWeaponByte
              lda ##3                   ; REP #$20
              sta dp:SZ
              bra bufferWeaponMode
bufferWeaponByte:
              lda ##2
              sta dp:SZ
bufferWeaponMode:
              lda ##2
              bra bufferWeaponAdvance
bufferWeaponStore:
              ldy ##1
              lda long:bufferOn
              beq bufferWeaponDirect
              lda [CP],y
              clc
              adc ##.word0 (DRAW_BUFFER-SHR)
              bra bufferWeaponWrite
bufferWeaponDirect:
              lda [CP],y
              sec
              sbc ##.word0 (DRAW_BUFFER-SHR)
bufferWeaponWrite:
              sta [CP],y
bufferWeaponStored:
              lda ##3
              bra bufferWeaponAdvance
bufferWeaponLoad:
              lda dp:SZ
bufferWeaponAdvance:
              clc
              adc dp:CP
              sta dp:CP
              bra bufferWeaponOp
bufferWeaponDone:
              lda dp:INDEX
              clc
              adc ##4
              sta dp:INDEX
              cmp ##20*4
              bcs bufferWeaponFinished
              jmp abs:.word0 (bufferWeaponNext)
bufferWeaponFinished:
              lda long:bufferOn
              beq bufferWeaponBankDirect
              lda ##.byte2 (DRAW_BUFFER)*257
              bra bufferWeaponBankSet
bufferWeaponBankDirect:
              lda ##.byte2 (SHR)*257
bufferWeaponBankSet:
              sta long:weaponPoseBank+1
              pld
              rtl

              .section buffergray, text, root
BufferReady:  rep #0x30
              tsc
              inc a
              sta long:bufferDP+BP
              phd
              phb
              lda ##.word0 (bufferDP)
              tcd
              stz dp:BP+2
              stz dp:DEFERRED
              lda ##0xffff
              sta dp:MINROW
              stz dp:MAXROW
              lda long:viewTop
              asl a
              tax
              lda long:rowX160,x
              sta dp:VIEWMIN
              lda long:viewBottom
              asl a
              tax
              lda long:rowX160,x
              sta dp:VIEWMAX
              lda long:GAME_DP+FIRST
              beq bufferReadyValid
              lda ##0
              sta long:bufferValid
              jsl long:bufferPatchWeapons
bufferReadyValid:
              lda long:bufferValid
              bne bufferReadyScan
              ldx ##.word0 (SHR)
              ldy ##.word0 (DRAW_BUFFER)
              lda ##DRAW_BUFFER_SIZE-1
              .byte 0x54, .byte2 (DRAW_BUFFER), .byte2 (SHR)
              lda ##1
              sta long:bufferValid
bufferReadyScan:
              jsl long:bufferScan
              plb
              pld
              sep #0x20
              rtl
BufferDeferred:
              rep #0x30
              tsc
              inc a
              sta long:bufferDP+BP
              phd
              phb
              lda ##.word0 (bufferDP)
              tcd
              lda ##1
              sta dp:DEFERRED
              lda long:GAME_DP+COL
              clc
              adc long:viewLeft
              sta dp:DEFCOL
              bra bufferReadyScan

BufferFinish: lda dp:FIRST
              bne bufferWeaponDirty
              lda long:weaponMaskTable
              cmp long:oldWeaponMaskTable
              beq bufferWeaponClean
bufferWeaponDirty:
              lda long:levelState
              bne bufferWeaponClean
              lda long:weapon
              asl a
              tax
              lda long:weaponReady,x
              clc
              adc long:weaponFrame
              sec
              sbc ##SPR_KNIFEREADY
              asl a
              asl a
              asl a
              clc
              adc long:weaponViewIndex
              tax
              lda long:bufferWeaponRows,x
              and ##255
              asl a
              tax
              lda long:rowX160,x
              cmp long:bufferDP+MINROW
              bcs bufferWeaponTopKept
              sta long:bufferDP+MINROW
bufferWeaponTopKept:
              lda long:weapon
              asl a
              tax
              lda long:weaponReady,x
              clc
              adc long:weaponFrame
              sec
              sbc ##SPR_KNIFEREADY
              asl a
              asl a
              asl a
              clc
              adc long:weaponViewIndex
              tax
              lda long:bufferWeaponRows+1,x
              and ##255
              asl a
              tax
              lda long:rowX160,x
              cmp long:bufferDP+MAXROW
              bcc bufferWeaponClean
              sta long:bufferDP+MAXROW
bufferWeaponClean:
              jsl long:drawWeaponPose
              lda long:vsyncOn
              beq bufferNoWait
              jsl long:bufferBeamWait
              rep #0x20
bufferNoWait: phd
              lda ##.word0 (bufferDP)
              tcd
              lda dp:MINROW
              cmp dp:MAXROW
              bcc bufferHasRows
              jmp abs:.word0 (bufferSlamEnd)
bufferHasRows:
              lda long:viewWidth
              and ##1
              sta dp:ODD
              lda long:viewWidth
              and ##0xfffe
              eor ##0xffff
              clc
              adc ##161                 ; unused prefix of the 160-byte row
              sta dp:TEMP
              asl a
              asl a                     ; eight instruction bytes per word
              clc
              adc ##.word0 (bufferRowCode)
              sta long:bufferRowJump+1
              lda long:viewLeft
              sec
              sbc dp:TEMP
              pha
              clc
              adc dp:MAXROW
              sta dp:STOPX
              pla
              clc
              adc dp:MINROW
bufferSlamStart:
              tax
bufferRowJump:jmp abs:.word0 (bufferRowCode)
bufferRowCode:
              lda long:DRAW_BUFFER+0,x
              sta long:SHR+0,x
              lda long:DRAW_BUFFER+2,x
              sta long:SHR+2,x
              lda long:DRAW_BUFFER+4,x
              sta long:SHR+4,x
              lda long:DRAW_BUFFER+6,x
              sta long:SHR+6,x
              lda long:DRAW_BUFFER+8,x
              sta long:SHR+8,x
              lda long:DRAW_BUFFER+10,x
              sta long:SHR+10,x
              lda long:DRAW_BUFFER+12,x
              sta long:SHR+12,x
              lda long:DRAW_BUFFER+14,x
              sta long:SHR+14,x
              lda long:DRAW_BUFFER+16,x
              sta long:SHR+16,x
              lda long:DRAW_BUFFER+18,x
              sta long:SHR+18,x
              lda long:DRAW_BUFFER+20,x
              sta long:SHR+20,x
              lda long:DRAW_BUFFER+22,x
              sta long:SHR+22,x
              lda long:DRAW_BUFFER+24,x
              sta long:SHR+24,x
              lda long:DRAW_BUFFER+26,x
              sta long:SHR+26,x
              lda long:DRAW_BUFFER+28,x
              sta long:SHR+28,x
              lda long:DRAW_BUFFER+30,x
              sta long:SHR+30,x
              lda long:DRAW_BUFFER+32,x
              sta long:SHR+32,x
              lda long:DRAW_BUFFER+34,x
              sta long:SHR+34,x
              lda long:DRAW_BUFFER+36,x
              sta long:SHR+36,x
              lda long:DRAW_BUFFER+38,x
              sta long:SHR+38,x
              lda long:DRAW_BUFFER+40,x
              sta long:SHR+40,x
              lda long:DRAW_BUFFER+42,x
              sta long:SHR+42,x
              lda long:DRAW_BUFFER+44,x
              sta long:SHR+44,x
              lda long:DRAW_BUFFER+46,x
              sta long:SHR+46,x
              lda long:DRAW_BUFFER+48,x
              sta long:SHR+48,x
              lda long:DRAW_BUFFER+50,x
              sta long:SHR+50,x
              lda long:DRAW_BUFFER+52,x
              sta long:SHR+52,x
              lda long:DRAW_BUFFER+54,x
              sta long:SHR+54,x
              lda long:DRAW_BUFFER+56,x
              sta long:SHR+56,x
              lda long:DRAW_BUFFER+58,x
              sta long:SHR+58,x
              lda long:DRAW_BUFFER+60,x
              sta long:SHR+60,x
              lda long:DRAW_BUFFER+62,x
              sta long:SHR+62,x
              lda long:DRAW_BUFFER+64,x
              sta long:SHR+64,x
              lda long:DRAW_BUFFER+66,x
              sta long:SHR+66,x
              lda long:DRAW_BUFFER+68,x
              sta long:SHR+68,x
              lda long:DRAW_BUFFER+70,x
              sta long:SHR+70,x
              lda long:DRAW_BUFFER+72,x
              sta long:SHR+72,x
              lda long:DRAW_BUFFER+74,x
              sta long:SHR+74,x
              lda long:DRAW_BUFFER+76,x
              sta long:SHR+76,x
              lda long:DRAW_BUFFER+78,x
              sta long:SHR+78,x
              lda long:DRAW_BUFFER+80,x
              sta long:SHR+80,x
              lda long:DRAW_BUFFER+82,x
              sta long:SHR+82,x
              lda long:DRAW_BUFFER+84,x
              sta long:SHR+84,x
              lda long:DRAW_BUFFER+86,x
              sta long:SHR+86,x
              lda long:DRAW_BUFFER+88,x
              sta long:SHR+88,x
              lda long:DRAW_BUFFER+90,x
              sta long:SHR+90,x
              lda long:DRAW_BUFFER+92,x
              sta long:SHR+92,x
              lda long:DRAW_BUFFER+94,x
              sta long:SHR+94,x
              lda long:DRAW_BUFFER+96,x
              sta long:SHR+96,x
              lda long:DRAW_BUFFER+98,x
              sta long:SHR+98,x
              lda long:DRAW_BUFFER+100,x
              sta long:SHR+100,x
              lda long:DRAW_BUFFER+102,x
              sta long:SHR+102,x
              lda long:DRAW_BUFFER+104,x
              sta long:SHR+104,x
              lda long:DRAW_BUFFER+106,x
              sta long:SHR+106,x
              lda long:DRAW_BUFFER+108,x
              sta long:SHR+108,x
              lda long:DRAW_BUFFER+110,x
              sta long:SHR+110,x
              lda long:DRAW_BUFFER+112,x
              sta long:SHR+112,x
              lda long:DRAW_BUFFER+114,x
              sta long:SHR+114,x
              lda long:DRAW_BUFFER+116,x
              sta long:SHR+116,x
              lda long:DRAW_BUFFER+118,x
              sta long:SHR+118,x
              lda long:DRAW_BUFFER+120,x
              sta long:SHR+120,x
              lda long:DRAW_BUFFER+122,x
              sta long:SHR+122,x
              lda long:DRAW_BUFFER+124,x
              sta long:SHR+124,x
              lda long:DRAW_BUFFER+126,x
              sta long:SHR+126,x
              lda long:DRAW_BUFFER+128,x
              sta long:SHR+128,x
              lda long:DRAW_BUFFER+130,x
              sta long:SHR+130,x
              lda long:DRAW_BUFFER+132,x
              sta long:SHR+132,x
              lda long:DRAW_BUFFER+134,x
              sta long:SHR+134,x
              lda long:DRAW_BUFFER+136,x
              sta long:SHR+136,x
              lda long:DRAW_BUFFER+138,x
              sta long:SHR+138,x
              lda long:DRAW_BUFFER+140,x
              sta long:SHR+140,x
              lda long:DRAW_BUFFER+142,x
              sta long:SHR+142,x
              lda long:DRAW_BUFFER+144,x
              sta long:SHR+144,x
              lda long:DRAW_BUFFER+146,x
              sta long:SHR+146,x
              lda long:DRAW_BUFFER+148,x
              sta long:SHR+148,x
              lda long:DRAW_BUFFER+150,x
              sta long:SHR+150,x
              lda long:DRAW_BUFFER+152,x
              sta long:SHR+152,x
              lda long:DRAW_BUFFER+154,x
              sta long:SHR+154,x
              lda long:DRAW_BUFFER+156,x
              sta long:SHR+156,x
              lda long:DRAW_BUFFER+158,x
              sta long:SHR+158,x
              lda dp:ODD
              beq bufferRowDone
              sep #0x20
              lda long:DRAW_BUFFER+160,x
              sta long:SHR+160,x
              rep #0x20
bufferRowDone:txa
              clc
              adc ##160
              tax
              cpx dp:STOPX
              bcs bufferSlamEnd
              jmp abs:.word0 (bufferRowJump)
bufferSlamEnd:pld
              rtl

;;; Decode the already prepared records without altering them. World records
;;; expose their first/last scaler row. Flat records carry their end offset.
;;; Records of one column are consecutive; publish its hull with two compares.
              .section buffersound, text, root
bufferScan:   jsr abs:.word0 (bufferIsFull)
              bcc bufferScanNeeded
              rtl
bufferScanNeeded:
              lda ##0xffff
              sta dp:LASTCOL
              sta dp:LT
              stz dp:LB
bufferScanNext:
              lda [BP]
              cmp ##.word0 (paintListDone-1)
              bne bufferNotEnd
              jmp abs:.word0 (bufferScanDone)
bufferNotEnd: cmp ##.word0 (deferOp-1)
              bne bufferNotDefer
              lda dp:DEFERRED
              beq bufferSkipDefer
              jmp abs:.word0 (bufferScanDone)
bufferSkipDefer:
              lda ##4
              jmp abs:.word0 (bufferAdvance)
bufferNotDefer:
              cmp ##.word0 (flatOp-1)
              bne bufferTexture
              jmp abs:.word0 (bufferFlat)
bufferTexture:
              cmp ##8                   ; CUTOP-1
              beq bufferCut
              lda ##10
              sta dp:SZ
              ldy ##8
              lda [BP],y
              inc a
              sta dp:CP
              ldy ##6
              lda [BP],y
              sta dp:COLN
              ldy ##2
              lda [BP],y
              and ##255
              sta dp:CP+2
              sec
              sbc ##.byte2 (SEG_SCALE3)
              xba
              sta dp:TEMP
              lda dp:CP
              xba
              and ##255
              ora dp:TEMP
              tax
              lda long:bufferScalePage,x
              and ##255
              asl a
              tax
bufferFindExit:
              lda long:viewScaleExit,x
              cmp dp:CP
              bcs bufferHaveExit
              inx
              inx
              bra bufferFindExit
bufferHaveExit:
              lda long:viewScaleBottom,x
              asl a
              tax
              lda long:rowX160,x
              sta dp:CB
              bra bufferTextureTop
bufferCut:    lda ##12
              sta dp:SZ
              ldy ##2
              lda [BP],y
              and ##255
              sta dp:CP+2
              ldy ##4
              lda [BP],y
              sec
              sbc ##3
              sta dp:CP
              lda [CP]
              sec
              sbc ##.word0 (DRAW_BUFFER)
              clc
              adc ##160
              sta dp:CB
              ldy ##8
              lda [BP],y
              sta dp:COLN
              ldy ##10
              lda [BP],y
              inc a
              sta dp:CP
bufferTextureTop:
              ldy ##4
              lda [CP],y
              sec
              sbc ##.word0 (DRAW_BUFFER)
              sta dp:CT
              bra bufferSpan
bufferFlat:   lda ##8
              sta dp:SZ
              ldy ##4
              lda [BP],y                ; end row * 160 + column
              sta dp:TEMP
              xba
              and ##255
              tax
              lda long:bufferModulo,x
              and ##255
              sta dp:COLN
              lda dp:TEMP
              and ##255
              clc
              adc dp:COLN
bufferModuloReduce:
              cmp ##160
              bcc bufferModuloReady
              sbc ##160
              bra bufferModuloReduce
bufferModuloReady:
              sta dp:COLN
              lda dp:TEMP
              sec
              sbc dp:COLN
              sta dp:CB
              ldy ##6
              lda [BP],y                ; entry-1 = flatCode+639-4*rows
              eor ##0xffff
              clc
              adc ##.word0 (flatCode+640)
              lsr a                     ; twice the row count
              tax
              lda long:rowX160,x
              sta dp:TEMP
              lda dp:CB
              sec
              sbc dp:TEMP
              sta dp:CT
bufferSpan:   lda dp:DEFERRED
              beq bufferSpanColumn
              lda dp:COLN
              cmp dp:DEFCOL
              bne bufferScanDone
bufferSpanColumn:
              lda dp:COLN
              cmp dp:LASTCOL
              beq bufferSameColumn
              jsr abs:.word0 (bufferPublish)
              bcs bufferScanDone
              lda dp:COLN
              sta dp:LASTCOL
              lda ##0xffff
              sta dp:LT
              stz dp:LB
bufferSameColumn:
              lda dp:CT
              cmp dp:LT
              bcs bufferTopKept
              sta dp:LT
bufferTopKept:lda dp:CB
              cmp dp:LB
              bcc bufferBottomKept
              sta dp:LB
bufferBottomKept:
              lda dp:SZ
bufferAdvance:clc
              adc dp:BP
              sta dp:BP
              jmp abs:.word0 (bufferScanNext)
bufferScanDone:
              jsr abs:.word0 (bufferPublish)
              rtl
bufferPublish:lda dp:LT
              cmp dp:MINROW
              bcs bufferMinKept
              sta dp:MINROW
bufferMinKept:lda dp:LB
              cmp dp:MAXROW
              bcc bufferMaxKept
              sta dp:MAXROW
bufferMaxKept:
bufferIsFull: lda dp:MINROW
              cmp dp:VIEWMIN
              bne bufferNotFull
              lda dp:MAXROW
              cmp dp:VIEWMAX
              rts
bufferNotFull:clc
              rts

;;; Enter with 16-bit A/X. VERTCNT advances once per two SHR rows, from
;;; $80 at row zero. Use the first counter value strictly past the hull top;
;;; equality also accepts an arrival already in that two-row window. If it
;;; has passed, polling waits for the next field. An empty hull uses the
;;; view top and still waits. Return with 8-bit A; Y holds the target counter.
;;; Only this entry polls; the row copy never does.
              .public bufferBeamWait, bufferBeamReady
bufferBeamWait:
              lda long:bufferDP+MINROW
              cmp long:bufferDP+MAXROW
              bcc bufferBeamHull
              lda long:bufferDP+VIEWMIN
bufferBeamHull:
              ldy ##0x80
bufferBeamDivide:
              iny
              sec
              sbc ##2*160
              bcs bufferBeamDivide
              tya
              sep #0x20
              sta long:bufferBeamCompare+1
bufferBeamPoll:
              lda long:VERTCNT
bufferBeamCompare:
              cmp #0
              bne bufferBeamPoll
bufferBeamReady:
              rtl

;;; viewBottom is exclusive. Round it up to VERTCNT's two-row boundary.
;;; A beam already below the view may proceed; otherwise wait for that row.
;;; Leave X/Y and the prepared-list stack untouched; return with 8-bit A.
vsyncViewWait:
              rep #0x20
              lda long:viewBottom
              inc a
              lsr a
              ora ##0x80
              sep #0x20
              sta long:vsyncViewCompare+1
vsyncViewPoll:
              lda long:VERTCNT
vsyncViewCompare:
              cmp #0
              bcc vsyncViewPoll
              jmp long:vsyncReady

              .section buffersave, text, root
              .public BufferChangeView
              .extern BufferMenuSound, ViewSelect
BufferChangeView:
              lda long:weaponViewIndex
              lsr a
              clc
              adc dp:U_MORE
              bmi bufferViewKeep
              cmp ##4
              bcs bufferViewKeep
              jsl long:ViewSelect
              asl a
              sta long:weaponViewIndex
              lda ##2
              jsl long:BufferMenuSound
bufferViewKeep:
              rtl


              .extern WallPaintLoad, WallPaintStore
