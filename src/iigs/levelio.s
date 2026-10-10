;;; Read a floor through the boot store map, reusing the resident loader's
;;; firmware and B1 routines. No game or picture work runs while art changes.
#include "memmap.inc"
#include "loader_api.inc"
#include "logic.inc"
              .extern OverlayB1Clobbered
              .section levelio, text, root, noreorder
              .public LoadFloorData, ProbeFloorData, LoadMusicData, LoadAuxData, LoadTitleData
              .public loadTitle, loadKeep, loadReadCredit
              .public loadFloor, loadArtSteps, loadMusic
              .public loadWide, loadProbe, probeChecking, selectDisk, badFloor, loadedDisk
              .extern directoryBlock, storeBlock, storeDataBlock, recordBlockHigh, UnitDone
              .extern loadMixed, ReadFloorFormat, DecodeFloorUnit, DecodeWorkSize
              .extern selectFloorDirectory, validLoadIndex, loadAux
              .extern SelectStage, stageBank, stageStart, ReadFloppyUnit
              .extern bootComplete, UiReadProgress, UiDiskPrompt, ProgressAdd, ProgressPlan, ProgressRemaining, progressExtra

#include "levelio.inc"

;;; The probe checks every required disk without prompting or replacing assets.
ProbeFloorData:ora ##0x8000
              bra LoadFloorData
LoadTitleData: ora ##LOAD_TITLE_FLAG      ; include the title-art prefix of an auxiliary list
LoadAuxData:   ora ##0x3000              ; auxiliary group, caller's screen retained
;;; JSL, A = zero-based floor index in this campaign. Carry clear on
;;; success. Game context is restored.
;;; Bit 13 of A: keep the caller's screen. After boot, progress uses the modal only.
LoadFloorData: php
              sei
              rep #0x30
              phb
              phd
              phx
              phy
              sta long:loadFloor
              and ##0x8000
              sta long:loadProbe
              lda long:loadFloor
              and ##0x4000
              sta long:loadMusic
              lda long:loadFloor
              and ##0x2000
              sta long:loadKeep
              lda long:loadFloor
              and ##0x1000
              sta long:loadAux
              lda long:loadFloor
              and ##LOAD_TITLE_FLAG
              sta long:loadTitle
              lda long:loadFloor
              and ##0x07ff
              sta long:loadFloor
              tsx
              txa
              sta long:loadStack
              lda ##0
              tcd
              sep #0x20
              pha
              plb
              lda long:SHADOW
              sta abs:loadShadow
              and #0xbf
              sta long:SHADOW
              rep #0x30
              ldx ##0x1ff
              txs
              stz abs:loadError
              stz abs:loadedDisk
              stz abs:probeChecking
              stz abs:loadWide
              stz abs:loadMixed
              stz dp:BOOT_DEST
              stz dp:BOOT_DEST+2
              stz dp:BOOT_SEGADDR
              stz dp:BOOT_SEGADDR+2
              jsr abs:validLoadIndex
              bcc validFloor
invalidRequest:
              jmp abs:badFloor
validFloor:   jsr abs:SelectStage
              lda abs:BOOT_BOOTINFO
              cmp ##0x4244
              beq bootAvailable
              jmp abs:badFloor
bootAvailable:
              sep #0x20
              lda abs:BOOT_BOOTINFO+2
              sta dp:BOOT_PD_UNIT
              lda abs:BOOT_BOOTINFO+18
              sta dp:BOOT_NDISKS
              stz dp:BOOT_CELLS
              lda long:bootComplete
              sta abs:BOOT_runtimeUI
              bne probeScreenKept
              lda abs:loadProbe+1
              ora abs:loadKeep+1
              bne probeScreenKept
              lda abs:loadMusic+1
              ora abs:loadKeep+1
              bne musicStrip
              jsr abs:BOOT_screenOn
              bra probeScreenKept
musicStrip:   ldx ##16
              rep #0x20
musicStripPal:lda abs:BOOT_stripPal,x
              sta long:SHR_PAL+0x1e0,x
              dex
              dex
              bpl musicStripPal
              sep #0x20
              ldx ##176
              lda #15
musicStripRows:sta long:SHR_SCB,x
              inx
              cpx ##200
              bcc musicStripRows
probeScreenKept:
              rep #0x20
              lda abs:loadMusic
              beq readFloorDirectory
              jmp abs:readMusicDirectory
readFloorDirectory:
              stz dp:LV_BLOCK
              lda ##EPDIR
              sta dp:LV_BUFFER
              jsr abs:directoryBlock
              inc dp:LV_BLOCK
              lda ##EPDIR+512
              sta dp:LV_BUFFER
              jsr abs:directoryBlock
              lda abs:EPDIR
              cmp ##0x4f57
              beq validField0
              jmp abs:badFloor
validField0:
              lda abs:EPDIR+2
              cmp ##0x464c
              beq validField1
              jmp abs:badFloor
validField1:
              lda abs:EPDIR+4
              cmp ##0x5045
              beq validField2
              jmp abs:badFloor
validField2:
              jsr abs:ReadFloorFormat
floorWidthReady:
              jsr abs:selectFloorDirectory
              bcc validField3
              jmp abs:badFloor
validField3:
              ldy dp:LV_RECORD
              lda dp:LV_LEFT
              bne validField4
              jmp abs:badFloor
validField4:
              cmp ##129
              bcc validField5
              jmp abs:badFloor
validField5:
              sta dp:LV_LEFT
              asl a
              asl a
              asl a
              clc
              adc dp:LV_RECORD
              cmp ##EPDIR+1025
              bcc validField6
              jmp abs:badFloor
validField6:
              lda abs:loadProbe
              beq countFloorUnits
              inc abs:probeChecking
              jmp abs:probeUnit
countFloorUnits:
              ldx dp:LV_LEFT
              stz dp:LV_TOTAL
              stz abs:loadDecodeWork
countUnits:   lda abs:loadWide
              beq countLegacyUnit
              phy
              jsr abs:DecodeWorkSize
              ply
              bra countDecodeReady
countNoDecode:lda ##0
              bra countDecodeReady
countLegacyUnit:
              lda abs:2,y
              xba
              and ##0x00fe
countDecodeReady:
              clc
              adc abs:loadDecodeWork
              sta abs:loadDecodeWork
              lda abs:6,y
              clc
              adc dp:LV_TOTAL
              sta dp:LV_TOTAL
              tya
              clc
              adc ##8
              tay
              dex
              bne countUnits
              lda ##1
              sta dp:LV_STEP
              lda dp:LV_TOTAL
countStep:    cmp ##34
              bcc stepReady
              sbc ##34
              inc dp:LV_STEP
              bra countStep
stepReady:    lda long:bootComplete
              bne stepRuntime
              jmp abs:stepLegacy
stepRuntime:
              lda ##.word0 ProgressAdd
              sta abs:BOOT_b1Notify+1
              sep #0x20
              lda #.byte2 ProgressAdd
              sta abs:BOOT_b1Notify+3
              rep #0x20
              lda ##4
              sta dp:LV_STEP
              lda ##1
              sta abs:loadReadCredit
              lda dp:LV_TOTAL
              lsr a
              lsr a
              sta abs:loadReadWork
              lda dp:BOOT_PD_UNIT
              and ##0x70
              cmp ##0x50
              bne loadPlanTail
              lda ##1
              sta dp:LV_STEP
              lda ##18
              sta abs:loadReadCredit
              lda dp:LV_TOTAL
              asl a
              sta abs:loadReadWork
              asl a
              asl a
              asl a
              clc
              adc abs:loadReadWork
              sta abs:loadReadWork
loadPlanTail: lda abs:loadMusic
              bne loadSongBudget
              lda abs:loadArtSteps
              sta abs:loadTailWork
              asl a
              asl a
              asl a
              sec
              sbc abs:loadTailWork
              clc
              adc ##740
              bra loadTotalBudget
loadSongBudget:lda ##500
loadTotalBudget:
              clc
              adc abs:loadReadWork
              adc abs:loadDecodeWork
              clc
              adc long:progressExtra
              jsl long:ProgressRemaining
stepLegacy:   lda dp:LV_STEP
              sta dp:LV_NEXTCELL
              stz dp:LV_DONE
              sep #0x20
              lda abs:BOOT_runtimeUI
              ora abs:loadKeep+1
              bne noLoadStrip
              jsr abs:BOOT_drawStrip
              ldx ##180
              lda #15
loadLabelRows:sta long:SHR_SCB,x
              inx
              cpx ##187
              bcc loadLabelRows
              ldx ##180*160+65
              stx dp:BOOT_XOFS
              ldy ##BOOT_LOADINGTEXT
              jsr abs:BOOT_drawText
noLoadStrip:  rep #0x20
              jmp abs:nextUnit
musicBad:     jmp abs:badFloor
readMusicDirectory:
              lda ##2
              sta dp:LV_BLOCK
              lda ##EPDIR
              sta dp:LV_BUFFER
              jsr abs:directoryBlock
              lda abs:EPDIR
              cmp ##0x4f57
              bne musicBad
              lda abs:EPDIR+2
              cmp ##0x464c
              bne musicBad
              lda abs:EPDIR+4
              cmp ##0x534d
              bne musicBad
              lda abs:EPDIR+6
              cmp ##0x3330                ; WOLFMS03: two records (halves) per song
              bne singleMusicRecords
              jmp abs:musicHalves
singleMusicRecords:
              cmp ##0x3230
              bne legacyMusicDirectory
              inc abs:loadWide
              bra musicDirectoryReady
legacyMusicDirectory:
              cmp ##0x3130
              bne badFloor
musicDirectoryReady:
              lda abs:loadFloor
              asl a
              asl a
              asl a
              clc
              adc ##EPDIR+64
              sta dp:LV_RECORD
              tay
              lda abs:0,y
              bne badFloor
              lda abs:2,y
              and ##0x7fff
              cmp ##0x3e
              bne badFloor
              lda abs:6,y
              beq badFloor
              cmp ##129
              bcs badFloor
              lda ##1
              sta dp:LV_LEFT
              jmp abs:countFloorUnits
musicHalves:  inc abs:loadWide
              lda abs:loadFloor
              asl a
              asl a
              asl a
              asl a
              clc
              adc ##EPDIR+64
              sta dp:LV_RECORD
              tay
              lda abs:0,y
              bne badFloor
              lda abs:2,y                 ; the first half starts the song bank, raw or
              and ##0x00ff                ; packed: a packed half decodes from BOOT_STAGE
              cmp ##MUSIC_BASE>>16        ; like the second one (SelectStage)
              bne badFloor
              lda abs:6,y
              beq badFloor
              lda abs:14,y                ; the second half, when there is one
              beq musicOneHalf
              lda ##2
              bra musicCount
musicOneHalf: lda ##1
musicCount:   sta dp:LV_LEFT
              jmp abs:countFloorUnits
badFloor:     lda ##1
              sta abs:loadError
              jmp abs:loadReturn

probeUnit:    ldx dp:LV_RECORD
              jsr abs:recordBlockHigh
              lda abs:4,x
              sta dp:LV_BLOCK
              lda abs:6,x
              beq badFloor
              sta dp:LV_COUNT
probeBlock:   jsr abs:storeBlock
              inc dp:LV_BLOCK
              bne probeBlockNoWrap
              inc dp:LV_BLOCK_HI
probeBlockNoWrap:
              dec dp:LV_COUNT
              bne probeBlock
              lda dp:LV_RECORD
              clc
              adc ##8
              sta dp:LV_RECORD
              dec dp:LV_LEFT
              bne probeUnit
              jmp abs:loadReturn

nextUnit:     ldx dp:LV_RECORD
              jsr abs:recordBlockHigh
              lda abs:0,x
              sta dp:BOOT_SEGADDR
              lda abs:2,x
              sta dp:BOOT_SEGADDR+2
              xba
              and ##1
              sta dp:LV_FLAGS
              lda abs:4,x
              sta dp:LV_BLOCK
              lda abs:6,x
              sta dp:LV_COUNT
              lda dp:LV_FLAGS
              beq rawUnit
              stz abs:stageStart
              lda dp:BOOT_SEGADDR+2
              and ##255
              cmp abs:stageBank
              bne stagedUnit
              lda dp:BOOT_SEGADDR
              bne stagedUnit
              lda dp:LV_COUNT             ; in place: the packed blocks end the bank
              xba
              asl a
              eor ##0xffff
              inc a
              sta abs:stageStart
stagedUnit:   lda abs:stageStart
              clc
              adc ##.word0 BOOT_STAGE
              sta dp:BOOT_DEST
              lda abs:stageBank
              bra destinationSet
rawUnit:      lda dp:BOOT_SEGADDR
              sta dp:BOOT_DEST
              lda dp:BOOT_SEGADDR+2
destinationSet:
              and ##255
              sta dp:BOOT_DEST+2
              ; A floppy read may retain adjacent packed units in its stage.
              ; Carry set leaves this unit for the ordinary block loop.
              jsr abs:ReadFloppyUnit
              bcs unitBlock
              jmp abs:unitDecode
unitBlock:    lda ##BOOT_BUF
              sta dp:LV_BUFFER
unitBlockRead:jsr abs:storeDataBlock       ; LV_BUFFER survives the read and copy
              sep #0x20
              jsr abs:BOOT_copyBlock
              rep #0x20
              inc dp:LV_BLOCK
              bne unitBlockNoWrap
              inc dp:LV_BLOCK_HI
unitBlockNoWrap:
              inc dp:LV_DONE
              dec dp:LV_NEXTCELL
              bne blockCount
              lda dp:LV_STEP
              sta dp:LV_NEXTCELL
              lda long:bootComplete
              beq bootCellProgress
              lda abs:loadReadCredit
              jsl long:ProgressAdd
              bra barKept
bootCellProgress:
              lda abs:loadKeep
              bne barKept
              sep #0x20
              lda dp:BOOT_CELLS
              cmp #34
              bcs barKept
              inc dp:BOOT_CELLS
              lda #BOOT_BAR_FULL
              sta dp:BOOT_CCOLOR
              lda dp:BOOT_CELLS
              jsr abs:BOOT_drawCell
barKept:      rep #0x20
blockCount:   dec dp:LV_COUNT
              bne unitBlockRead
unitDecode:   lda dp:LV_FLAGS
              beq unitLoaded
              jsl long:OverlayB1Clobbered
              jsl long:CodecDispatch      ; HLZ (hlz.inc), else DecodeFloorUnit
              nop                         ; 5 bytes like SEP+JSR: LevelIO keeps its layout
              rep #0x20
unitLoaded:   jsr abs:UnitDone          ; the load-time code hook and the run ends
              lda dp:LV_RECORD
              clc
              adc ##8
              sta dp:LV_RECORD
              dec dp:LV_LEFT
              beq floorLoaded
              jmp abs:nextUnit
floorLoaded:  lda long:bootComplete
              ora abs:loadKeep
              bne loadReturn
              sep #0x20
              lda #34
              sta dp:BOOT_CELLS
              jsr abs:BOOT_drawStrip
              rep #0x20
loadReturn:   sep #0x20
              lda abs:loadShadow
              sta long:SHADOW
              rep #0x30
              ldx abs:loadStack
              txs
              ply
              plx
              pld
              plb
              plp
              lda long:loadError
              beq loadOK
              sec
              rtl
loadOK:       clc
              rtl

;;; Both drives are checked before showing the boot loader's disk prompt.
selectDisk:   cmp abs:loadedDisk
              beq diskReady
;;; SmartPort status/control may use the block-copy and segment pointers.
              rep #0x20
              lda dp:BOOT_DEST
              pha
              lda dp:BOOT_DEST+2
              pha
              lda dp:BOOT_SEGADDR
              pha
              lda dp:BOOT_SEGADDR+2
              pha
              sep #0x20
              jsr abs:checkDisk
              bcc diskSelected
              lda dp:BOOT_NDISKS
              cmp #1
              beq askDisk
              jsr abs:flipUnit
              jsr abs:checkDisk
              bcc diskSelected
              jsr abs:flipUnit
askDisk:      lda abs:loadProbe+1
              beq waitDisk
              rep #0x20
              jmp abs:badFloor
waitDisk:     lda abs:BOOT_runtimeUI
              beq waitBootDisk
              lda dp:BOOT_DISKNUM
              rep #0x20
              and ##255
              jsl long:UiDiskPrompt
              sep #0x20
waitBootDisk: jsr abs:BOOT_waitDisk
              lda abs:BOOT_runtimeUI
              beq diskPromptDone
              rep #0x20
              lda ##0
              jsl long:UiDiskPrompt
              sep #0x20
diskPromptDone:
              jsr abs:checkDisk
              bcs askDisk
diskSelected: rep #0x20
              pla
              sta dp:BOOT_SEGADDR+2
              pla
              sta dp:BOOT_SEGADDR
              pla
              sta dp:BOOT_DEST+2
              pla
              sta dp:BOOT_DEST
              sep #0x20
diskReady:    lda dp:BOOT_DISKNUM
              sta abs:loadedDisk
              rts

;;; The other SmartPort unit. The prompt that follows a miss has to come
;;; back to the drive the floor load was already using: an empty unit
;;; never ejects the disk that is actually in.
flipUnit:     lda dp:BOOT_PD_UNIT
              eor #0x80
              sta dp:BOOT_PD_UNIT
              asl a
              lda #0
              rol a
              inc a
              sta abs:BOOT_spUnit
              rts
checkDisk:    rep #0x20
              lda abs:BOOT_BOOTINFO+12
              sta abs:BOOT_buildId
              lda abs:BOOT_BOOTINFO+14
              sta abs:BOOT_buildId+2
              sep #0x20
              jsr abs:BOOT_readHeader2
              php
              rep #0x20
              pha
              lda abs:loadProbe
              bne checkProgressDone
              lda long:bootComplete
              beq checkProgressDone
              lda ##32
              jsl long:ProgressAdd
checkProgressDone:
              pla
              plp
              bcs wrongDisk
              rep #0x20
              lda abs:BOOT_HDR_BUILD
              cmp abs:BOOT_BOOTINFO+12
              bne wrongBuild
              lda abs:BOOT_HDR_BUILD+2
              cmp abs:BOOT_BOOTINFO+14
              bne wrongBuild
              sep #0x20
              clc
              rts
wrongBuild:   sep #0x20
wrongDisk:    sec
              rts

              .section floppystream, text, root
loadDecodeWork:.word 0
loadReadWork: .word 0
loadReadCredit:.word 0
loadTailWork: .word 0
loadArtSteps: .word 0
loadFloor:    .word 0
loadWide:     .word 0
loadProbe:    .word 0
loadMusic:    .word 0
loadKeep:     .word 0
loadTitle:    .word 0
probeChecking:.word 0
loadStack:    .word 0
loadError:    .word 0
loadShadow:   .byte 0
loadedDisk:   .word 0
              .section tailirq, text, root
LoadMusicData:pha
              lda ##8192
              jsl long:ProgressPlan
              pla
              ora ##0x6000              ; keep the boot picture until its final fade
              jmp abs:LoadFloorData
;;; The HLZ decoder: its own section in SEG_HLZ (wolf.scm), not in LevelIO.
#include "hlz.inc"
