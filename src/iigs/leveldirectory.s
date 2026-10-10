#include "loader_api.inc"
#include "levelio.inc"
#include "memmap.inc"
#include "logic.inc"
ROOT          .equ STORE_ROOT         ; the store root, loaded by the boot
ROOT_BLOCKS   .equ STORE_ROOT_BLOCKS
CACHE_BANK    .equ STORE_CACHE >> 16
              .section leveldirectory, text, root, noreorder
              .public selectFloorDirectory
              .public validLoadIndex, loadAux
              .public directoryBlock, storeBlock, storeDataBlock, recordBlockHigh, UnitDone, homeDisk
              .extern loadFloor, loadArtSteps, loadMusic, loadTitle
              .extern loadWide, loadProbe, probeChecking, selectDisk, badFloor, loadedDisk
              .extern bootComplete, ProgressAdd, loadKeep, loadReadCredit
loadAux:      .word 0

validLoadIndex:
              lda abs:loadAux
              bne loadIndexOK           ; the header validates the auxiliary index
              lda abs:loadFloor
              ldx abs:loadMusic
              beq ordinaryFloorLimit
              cmp ##28
              rts
ordinaryFloorLimit:
              cmp ##60
              rts
loadIndexOK:  clc
              rts
;;; EP03 loads only the chosen floor's record page into the second half
;;; of EPDIR. The root and music directory still occupy their EP02 blocks.
selectFloorDirectory:
              lda abs:loadAux
              beq ordinaryFloorDirectory
              jmp abs:auxiliaryDirectory
ordinaryFloorDirectory:
              lda abs:EPDIR+8
              cmp ##61
              bcs directoryInvalid
              cmp abs:loadFloor
              beq directoryInvalid
              bcc directoryInvalid
              lda abs:EPDIR+6
              cmp ##0x3230                ; WOLFEP02: exact logic bank
              bne indexedDirectory
              lda abs:EPDIR+8
              cmp ##10
              bne directoryInvalid
              ldx abs:loadFloor
              lda abs:EPDIR+52,x
              and ##255
              sta abs:loadArtSteps
              lda abs:loadFloor
              asl a
              tax
              lda abs:EPDIR+12,x
              cmp ##960
              bcs directoryInvalid
              bit ##7
              bne directoryInvalid
              clc
              adc ##EPDIR+64
              sta dp:LV_RECORD
              lda abs:EPDIR+32,x
              sta dp:LV_LEFT
              clc
              rts

directoryInvalid:
              sec
              rts
indexedDirectory:
              cmp ##0x3830
              beq doubleDirectory
              cmp ##0x3730
              beq doubleDirectory
              cmp ##0x3630
              beq doubleDirectory
              cmp ##0x3530                ; EP05 adds logical block bit 16
              beq doubleDirectory
              cmp ##0x3430                ; EP04 uses two record pages
              beq doubleDirectory
              cmp ##0x3330                ; EP03 uses one record page
              bne directoryInvalid
              lda ##1
              bra directoryPagesReady
doubleDirectory:
              lda ##2
directoryPagesReady:
              sta abs:directoryPages
              lda abs:loadFloor
              asl a
              sta dp:LV_LEFT
              asl a
              clc
              adc dp:LV_LEFT
              tax
              lda abs:EPDIR+16,x          ; the art steps; the high byte: the
              and ##255                   ; records of the episode-disk run
              sta abs:loadArtSteps
              lda abs:EPDIR+17,x
              and ##255
              sta abs:loadSplit
              lda abs:EPDIR+14,x
              beq directoryInvalid
              cmp ##129
              bcs directoryInvalid
              ldy abs:directoryPages
              cpy ##2
              beq floorCountReady
              cmp ##65
              bcs directoryInvalid
floorCountReady:
              sta dp:LV_LEFT
              lda abs:EPDIR+12,x
              cmp ##3
              bcc directoryInvalid
              sta dp:LV_BLOCK
              lda abs:EPDIR+402           ; AX03: the records sit anywhere
              cmp ##0x3330
              bne fixedFloorPage
              lda dp:LV_LEFT
              cmp ##65
              lda ##1
              bcc compactFloorPages
              inc a
compactFloorPages:
              sta abs:directoryPages
              bra floorPageRead
fixedFloorPage:
              lda dp:LV_BLOCK
              sec
              sbc ##3
              ldy abs:directoryPages
              cpy ##2
              bne singleFloorPage
              lsr a
              bcs floorPageInvalid
singleFloorPage:
              cmp abs:EPDIR+8
              bcs floorPageInvalid
floorPageRead:
              jsr abs:readRecordPages
              lda ##EPDIR
              sta dp:LV_RECORD
              jsr abs:planRuns
              clc
              rts
floorPageInvalid:
              sec
              rts

;;; AX01/AX02 groups use the same one/two-page scratch as floor records.
auxiliaryDirectory:
              lda abs:EPDIR+6
              cmp ##0x3830
              beq doubleAuxiliary
              cmp ##0x3730
              beq doubleAuxiliary
              cmp ##0x3630
              beq doubleAuxiliary
              cmp ##0x3330
              beq singleAuxiliary
              cmp ##0x3430
              beq doubleAuxiliary
              cmp ##0x3530
              beq doubleAuxiliary
              jmp abs:auxiliaryInvalid
doubleAuxiliary:
              lda ##2
              bra auxPagesReady
singleAuxiliary:
              lda ##1
auxPagesReady:sta abs:directoryPages
              lda abs:EPDIR+400
              cmp ##0x5841
              bne auxiliaryInvalid
              lda abs:EPDIR+402
              cmp ##0x3330
              bne fixedAuxiliary
              jmp abs:compactAuxiliary
fixedAuxiliary:
              lda abs:directoryPages
              xba
              ora ##0x3030
              cmp abs:EPDIR+402
              bne auxiliaryInvalid
              lda abs:EPDIR+8
              beq auxiliaryInvalid
              cmp ##61
              bcs auxiliaryInvalid
              ldx abs:directoryPages
              cpx ##2
              bne auxRootSizeReady
              asl a
auxRootSizeReady:
              clc
              adc ##3
              cmp abs:EPDIR+404
              beq auxRootReady
              bcs auxiliaryInvalid
auxRootReady:
              lda abs:loadFloor
              cmp abs:EPDIR+406
              bcs auxiliaryInvalid
              ldx abs:directoryPages
              cpx ##2
              bne auxOffsetReady
              asl a
              bcs auxiliaryInvalid
auxOffsetReady:
              clc
              adc abs:EPDIR+404
              bcs auxiliaryInvalid
              sta dp:LV_BLOCK
              jsr abs:readRecordPages
              lda abs:EPDIR+2
              bne auxiliaryInvalid
              lda abs:EPDIR
              beq auxiliaryInvalid
              cmp ##128
              bcs auxiliaryInvalid
              ldy abs:directoryPages
              cpy ##2
              beq auxCountReady
              cmp ##64
              bcs auxiliaryInvalid
auxCountReady:
              sta dp:LV_LEFT
              lda ##EPDIR+4
              sta dp:LV_RECORD
              stz abs:loadArtSteps
              clc
              rts
auxiliaryInvalid:
              sec
              rts

;;; AX03: the group's entry in the RAM root gives the block of its list, the
;;; list's offset in it / 4 and bit 7 when it continues into the next block.
compactAuxiliary:
              lda abs:loadFloor
              cmp abs:EPDIR+406
              bcs compactInvalid
              sta dp:LV_LEFT
              asl a
              clc
              adc dp:LV_LEFT
              adc abs:EPDIR+404
              tax
              lda long:ROOT,x
              sta dp:LV_BLOCK
              lda long:ROOT+2,x
              and ##255
              ldy ##1
              bit ##0x80
              beq compactPages
              iny
compactPages: sty abs:directoryPages
              and ##0x7f
              asl a
              asl a
              sta dp:LV_RECORD
              jsr abs:readRecordPages
              ldx dp:LV_RECORD
              lda abs:EPDIR,x
              beq compactInvalid
              cmp ##128
              bcs compactInvalid
              sta dp:LV_LEFT
;;; The second word counts title-only records at the front. Ordinary view/pause
;;; loads start after them; a same-floor restart loads the whole list.
              lda abs:EPDIR+2,x
              beq compactAuxStart
              cmp dp:LV_LEFT
              bcs compactInvalid
              ldy abs:loadTitle
              bne compactAuxStart
              pha
              lda dp:LV_LEFT
              sec
              sbc abs:EPDIR+2,x
              sta dp:LV_LEFT
              pla
              asl a
              asl a
              asl a
              sta dp:LV_RECORD
              txa
              clc
              adc dp:LV_RECORD
              tax
compactAuxStart:
              txa
              clc
              adc ##EPDIR+4
              sta dp:LV_RECORD
              stz abs:loadArtSteps
              clc
              rts
compactInvalid:
              sec
              rts

readRecordPages:
              lda ##EPDIR
              sta dp:LV_BUFFER
              jsr abs:directoryBlock
              lda abs:directoryPages
              cmp ##2
              bne recordPagesReady
              inc dp:LV_BLOCK
              lda ##EPDIR+512
              sta dp:LV_BUFFER
              jsr abs:directoryBlock
recordPagesReady:
              rts
directoryPages:.word 1

;;; Translate one logical store block to its disk and physical block.
              .section leveldirectory, text, root, noreorder
directoryBlock:
              stz dp:LV_BLOCK_HI
              jsr abs:storeBlock
              lda long:bootComplete
              beq directoryDone
              lda dp:BOOT_PD_UNIT
              and ##0x70
              cmp ##0x50
              beq directoryFloppy
              lda ##1
              bra directoryCredit
directoryFloppy:lda ##11
directoryCredit:
              jsl long:ProgressAdd
directoryDone:rts

;;; EP05 reuses the high flag bit for logical block bit 16. The B1 stream
;;; carries its own exact output length, including the full-bank zero word.
recordBlockHigh:
              stz dp:LV_BLOCK_HI
              lda abs:loadWide
              beq recordBlockReady
              lda abs:2,x
              asl a
              rol dp:LV_BLOCK_HI
recordBlockReady:
              rts

;;; X/Y and the loader's header buffer are scratch; LV_BUFFER survives.
storeBlock:   jsr abs:rootLookup
              bcc storeDone
;;; Unit records name stored asset data, not the RAM-only root directory.
storeDataBlock:
              jsr abs:cacheLookup
              bcs storeFromDisk
storeDone:    rts
;;; Each disk header maps its store blocks (tools/mkdisk.py volume). If the
;;; current disk lacks this block, wantedDisk chooses the other floor part's
;;; disk during a two-part load, or the floor disk during play. Before any
;;; floor has loaded, auxiliary and music reads fall back to HDR_HOME_DISK.
storeFromDisk:lda abs:loadedDisk
              bne storeDiskKnown
              jsr abs:identifyDisk
              jsr abs:noteHomeDisk
storeDiskKnown:
              jsr abs:findRun
              bcc storeOnDisk
              jsr abs:wantedDisk
storeAsk:     cmp abs:loadedDisk
              beq storeNextDisk
              sep #0x20
              sta dp:BOOT_DISKNUM
              jsr abs:selectDisk
              rep #0x20
              jsr abs:findRun
              bcc storeOnDisk
storeNextDisk:jsr abs:titleDisk
              cmp abs:loadedDisk
              beq storeMissing
              bra storeAsk
storeMissing: sep #0x20
              bra storeError
storeOnDisk:  sta dp:BOOT_PD_BLOCK
              lda abs:probeChecking
              bne blockRead
              lda dp:LV_BUFFER
              sta dp:BOOT_PD_BUF
              sep #0x20
              jsr abs:BOOT_readBlock
              bcs storeError
              rep #0x20
              jmp abs:cacheKeep
blockRead:    rep #0x20
              rts


storeError:   lda abs:loadProbe+1
              beq loadDiskError
              rep #0x20
              jmp abs:badFloor
loadDiskError:
              lda abs:BOOT_runtimeUI
              beq bootReadError
              rep #0x20
              jmp abs:badFloor
bootReadError: jmp abs:BOOT_readError

;;; Carry clear when block LV_BLOCK_HI:LV_BLOCK is on the disk in the drive; A = its
;;; disk block. The runs follow the header's segments, 8 bytes each: the first store
;;; block, the count, the first disk block, the disk and the store block's bit 16.
findRun:      lda abs:loadedDisk
              beq runMissing
              lda abs:HDR_SEGS
              and ##255
              asl a
              asl a
              asl a
              clc
              adc ##HDR_SEG
              tax
runLoop:      cpx ##HDR_FLOOR_DISKS
              bcs runMissing
              lda abs:2,x
              beq runMissing
              lda abs:6,x
              xba
              and ##255
              sta dp:LV_MAP_HI
              lda dp:LV_BLOCK
              sec
              sbc abs:0,x
              sta dp:LV_OFFSET
              lda dp:LV_BLOCK_HI
              sbc dp:LV_MAP_HI
              bne runNext
              lda dp:LV_OFFSET
              cmp abs:2,x
              bcs runNext
              adc abs:4,x
              clc
              rts
runNext:      txa
              clc
              adc ##8
              tax
              bra runLoop
runMissing:   sec
              rts

;;; loadedDisk = the disk in the drive, its header in BOOT_HDR; 0 when no disk of this
;;; build is in the drive.
identifyDisk: stz abs:loadedDisk
              lda ##BOOT_HDR
              sta dp:BOOT_PD_BUF
              lda ##1
              sta dp:BOOT_PD_BLOCK
              sep #0x20
              jsr abs:BOOT_readBlock
              bcc identifyRead
              jsr abs:BOOT_readBlock      ; the first read after a disk change fails
              bcs identifyDone
identifyRead: rep #0x20
              lda abs:BOOT_HDR
              cmp ##0x4f57                ; "WOLFGS"
              bne identifyDone
              lda abs:BOOT_HDR+2
              cmp ##0x464c
              bne identifyDone
              lda abs:BOOT_HDR+4
              cmp ##0x5347
              bne identifyDone
              lda abs:BOOT_HDR_BUILD
              cmp abs:BOOT_BOOTINFO+12
              bne identifyDone
              lda abs:BOOT_HDR_BUILD+2
              cmp abs:BOOT_BOOTINFO+14
              bne identifyDone
              lda abs:HDR_DISK
              and ##255
              sta abs:loadedDisk
identifyDone: rep #0x20
              rts

;;; A floor load sets the disk of the floor in play; the loads during its play read it:
;;; the floor disk, which holds every block of play (an episode disk lacks the floor's song).
noteHomeDisk: lda abs:loadAux
              ora abs:loadMusic
              ora abs:loadProbe
              bne homeKept
              jsr abs:floorDisks
              lda abs:diskF
              sta abs:homeDisk
homeKept:     rts

;;; A floor load asks for the floor's disk. With two parts: the floor disk when the episode
;;; disk is in the drive, else the episode disk (a cold load reads the episode disk first).
wantedDisk:   lda abs:loadAux
              ora abs:loadMusic
              bne wantedPlay
              jsr abs:floorDisks
              lda abs:diskE
              beq wantedFloorPart          ; one part
              cmp abs:loadedDisk
              bne wantedDone
wantedFloorPart:
              lda abs:diskF
              rts
wantedPlay:   lda abs:homeDisk
              bne wantedDone
;;; The title blocks are on the home disk (tools/mkdisk.py HDR_HOME_DISK), the disk in the
;;; drive after the boot. The game never asks for disk 1 after the boot.
titleDisk:    lda abs:BI_HOME_DISK
              and ##0x7f                   ; bit 7: the boot loaded the play cache
wantedDone:   rts

homeDisk:     .word 0

;;; After each unit, run the load-time code hook, then RunEnds to switch
;;; staging banks or clear finished scratch. Native A16/X16, DBR = 0, D = 0.
UnitDone:     jsr abs:GenHook
              jmp abs:RunEnds

;;; The root (store blocks 0-4, tools/episode_directory.py) stays in RAM at ROOT
;;; when the boot loaded it (an AX03 directory): its blocks need no disk.
rootLookup:   lda dp:LV_BLOCK_HI
              bne rootMiss
              lda dp:LV_BLOCK
              cmp ##ROOT_BLOCKS
              bcs rootMiss
              lda long:ROOT
              cmp ##0x4f57                ; "WO"
              bne rootMiss
              lda long:ROOT+402
              cmp ##0x3330                ; "03" of AX03
              bne rootMiss
              lda dp:LV_BLOCK
              xba
              asl a
              clc
              adc ##.word0 ROOT
              tax
              ldy dp:LV_BUFFER
              lda ##511
              .byte 0x54, 0x00, 0x00      ; mvn bank 0 to bank 0
              clc
              rts
rootMiss:     sec
              rts

;;; The store cache. With RAM banks from CACHE_BANK up (8 MB), each store block
;;; read from a disk stays in RAM, and a later read copies it from RAM. The table
;;; at CACHE_TABLE holds the slot of each block (0: not kept). Slot s is at bank
;;; CACHE_BANK + s/128, offset (s & 127) * 512; slots 0-63 hold the table.
CACHE_TABLE   .equ STORE_CACHE
CACHE_BLOCKS  .equ 16384
CACHE_FIRST   .equ 64

;;; Carry clear: the block is in RAM and is now at LV_BUFFER.
cacheLookup:
              jsr abs:playLookup
              bcs cacheStore
              rts
cacheStore:
              lda abs:cacheEnd
              bpl cacheSized
              jsr abs:cacheSize
cacheSized:   beq cacheMiss
              lda dp:LV_BLOCK_HI
              bne cacheMiss
              lda dp:LV_BLOCK
              cmp ##CACHE_BLOCKS
              bcs cacheMiss
              asl a
              tax
              lda long:CACHE_TABLE,x
              beq cacheMiss
              jsr abs:cacheSlot
              sep #0x20
              sta abs:cacheIn+2
              rep #0x20
              ldy dp:LV_BUFFER
              lda ##511
cacheIn:      .byte 0x54, 0x00, 0x00    ; mvn: the slot to bank 0
              clc
              rts
cacheMiss:    sec
              rts

;;; After a disk read: keep the block at LV_BUFFER while slots are free.
cacheKeep:    lda abs:cacheEnd
              beq cacheKept
              lda dp:LV_BLOCK_HI
              bne cacheKept
              lda dp:LV_BLOCK
              cmp ##CACHE_BLOCKS
              bcs cacheKept
              asl a
              tax
              lda abs:cacheNext
              cmp abs:cacheEnd
              bcs cacheKept
              sta long:CACHE_TABLE,x
              inc abs:cacheNext
              jsr abs:cacheSlot
              sep #0x20
              sta abs:cacheOut+1
              rep #0x20
              txy
              ldx dp:LV_BUFFER
              lda ##511
              phb
cacheOut:     .byte 0x54, 0x00, 0x00    ; mvn: bank 0 to the slot
              plb
cacheKept:    rts

;;; Slot A: X = its offset, A = its bank (from CACHE_BANK).
cacheSlot:    pha
              and ##127
              xba
              asl a
              tax
              pla
              asl a
              xba
              and ##255
              clc
              adc ##CACHE_BANK
              rts

;;; cacheEnd = 128 slots for each RAM bank from CACHE_BANK up (BI_BANKS), and
;;; an empty table. 0: no cache.
cacheSize:    stz abs:cacheEnd
              ldx ##CACHE_BANK >> 3
              lda ##1 << (CACHE_BANK & 7)
cacheTest:    sta abs:cacheMask
              lda abs:BOOT_BOOTINFO+20,x
              and abs:cacheMask
              beq cacheCounted
              lda abs:cacheEnd
              clc
              adc ##128
              sta abs:cacheEnd
              lda abs:cacheMask
              asl a
              cmp ##256
              bcc cacheTest
              lda ##1
              inx
              cpx ##16
              bcc cacheTest
cacheCounted: lda abs:cacheEnd
              beq cacheNone
              lda ##0
              sta long:CACHE_TABLE
              ldx ##0
              ldy ##2
              lda ##CACHE_FIRST*512-3
              phb
              .byte 0x54, CACHE_BANK, CACHE_BANK ; mvn: the zero fills the table
              plb
              lda abs:cacheEnd
cacheNone:    rts
cacheEnd:     .word 0xffff
cacheNext:    .word CACHE_FIRST
cacheMask:    .word 0

;;; The play cache: the store blocks that the loads during play read (the view weights,
;;; the in-game pause pages, the tally, the weapon units, their record lists) stay in
;;; PLAY_CACHE, 512-byte slots, from the first title menu on (ui_overlays.s PlayCacheFill),
;;; when the root holds a play table at ROOT+512 (tools/build_registered_episode.py
;;; play_cache): "PC02", then words: fill groups, cached slots, the offsets of the floor
;;; limits, of the fill groups, of the runs and of their end. A floor's limit is the first
;;; slot its art writes; its load keeps only the slots below. A run: first block, blocks,
;;; address, bank, first slot. playValid: the slots from 0 up that hold their blocks.
;;; Carry clear: the block is at LV_BUFFER.
PLAY_TABLE    .equ ROOT+512
              .public playValid
playLookup:   lda long:PLAY_TABLE
              cmp ##0x4350                ; "PC"
              bne playMiss
              lda abs:loadAux
              ora abs:loadMusic
              ora abs:loadProbe
              bne playServe
              lda abs:loadFloor           ; a floor load: its art takes the slots from its limit
              asl a
              adc long:PLAY_TABLE+8
              tax
              lda long:PLAY_TABLE,x
              cmp abs:playValid
              bcs playServe
              sta abs:playValid
              bra playServe
playMiss:     sec
              rts
playServe:    lda abs:playValid
              beq playMiss
              lda dp:LV_BLOCK_HI
              bne playMiss
              lda long:PLAY_TABLE+12      ; the runs, 10 bytes each
playRun:      tax
              cmp long:PLAY_TABLE+14
              bcs playMiss
              lda dp:LV_BLOCK
              sec
              sbc long:PLAY_TABLE,x       ; the block's place in the run
              bcc playNext
              cmp long:PLAY_TABLE+2,x
              bcs playNext
              tay
              adc long:PLAY_TABLE+8,x     ; its slot (carry clear)
              cmp abs:playValid
              bcs playMiss                ; a floor's art holds it now
              tya
              xba
              asl a                       ; * 512: a run stays inside one bank
              adc long:PLAY_TABLE+4,x
              pha
              lda long:PLAY_TABLE+6,x
              sep #0x20
              sta abs:playIn+2
              rep #0x20
              plx
              ldy dp:LV_BUFFER
              lda ##511
playIn:       .byte 0x54, 0x00, 0x00      ; mvn: the slot to bank 0
              clc
              rts
playNext:     txa
              clc
              adc ##10
              bra playRun
playValid:    .word 0

#include "load_fast.inc"

#include "shared_expand.inc"

;;; Bank-0 code in the IRQ tail: FloorDirectory is full.
              .section tailirq, text, root
;;; The floor's byte in BI_FLOOR_DISKS (tools/floppy_layout.py, tools/mkdisk.py): bits 4-6
;;; the episode disk - 1 (0: no episode part), bits 0-2 the floor disk - 1. Out: diskF,
;;; diskE (0: none).
floorDisks:   ldx abs:loadFloor
              lda abs:BI_FLOOR_DISKS,x
              tax
              and ##7
              inc a
              sta abs:diskF
              txa
              and ##0x70
              beq floorOnePart
              lsr a
              lsr a
              lsr a
              lsr a
              inc a
floorOnePart: sta abs:diskE
              rts
diskE:        .word 0
diskF:        .word 0

;;; Two-run floor loads.
ZERO_BANK     .equ LOGIC_ZERO >> 16
;;; After the first run's last unit the other run's stage; after the load's last unit
;;; LOGIC_ZERO is zero-filled: the stage of the floor-disk run and of the effects, and the
;;; sight unit's input (the logic image is zero there). Native A16/X16, DBR = 0, D = 0.
RunEnds:      lda dp:LV_RECORD
              cmp abs:runSwitch
              bne runNoSwitch
              lda abs:run2Stage
              jsr abs:SetStageBank
              lda dp:LV_RECORD
runNoSwitch:  cmp abs:runFill
              bne runEnded
              lda ##0
              sta long:LOGIC_ZERO
              ldx ##.word0 LOGIC_ZERO
              ldy ##.word0 LOGIC_ZERO+2
              lda ##LOGIC_ZERO_SIZE-3
              phb
              .byte 0x54, ZERO_BANK, ZERO_BANK ; mvn: the zero word over the rest
              plb
runEnded:     rts

;;; A two-part floor record list (tools/build_registered_episode.py): the
;;; episode-disk run (loadSplit records), then the floor-disk run. The run whose disk is
;;; in the drive goes first; with neither in, the episode-disk run. For the floor-disk run
;;; first the list turns around in EPDIR (that run, at most 64 records, through BOOT_BUF).
;;; Sets the first run's stage, the record after which the other run's stage follows
;;; (runSwitch) and the one after which LOGIC_ZERO is zero-filled (runFill: the last).
;;; Native A16/X16, DBR = 0, LV_RECORD = EPDIR, LV_LEFT = the records.
plannedOne:   rts
planRuns:     lda abs:loadSplit
              beq plannedOne
              cmp dp:LV_LEFT
              bcs plannedOne
              asl a
              asl a
              asl a
              sta abs:splitBytes          ; the episode-disk run, bytes
              lda dp:LV_LEFT
              asl a
              asl a
              asl a
              clc
              adc ##EPDIR-8
              sta abs:runFill             ; the last record
              jsr abs:floorDisks
              lda abs:diskE
              beq episodeFirst            ; no episode disk (one volume)
              lda abs:diskF
              cmp abs:loadedDisk
              bne episodeFirst            ; the floor disk is not in the drive
              lda dp:LV_LEFT              ; the floor-disk run first
              asl a
              asl a
              asl a
              sec
              sbc abs:splitBytes
              sta abs:runBytes            ; the floor-disk run, bytes
              dec a
              pha
              lda abs:splitBytes
              clc
              adc ##EPDIR
              tax
              ldy ##BOOT_BUF
              pla
              .byte 0x54, 0, 0            ; mvn: the floor-disk run to BOOT_BUF
              lda abs:splitBytes
              clc
              adc ##EPDIR-1
              tax
              adc abs:runBytes
              tay
              lda abs:splitBytes
              dec a
              .byte 0x44, 0, 0            ; mvp: the episode-disk run behind it
              ldx ##BOOT_BUF
              ldy ##EPDIR
              lda abs:runBytes
              dec a
              .byte 0x54, 0, 0            ; mvn: the floor-disk run to the front
              lda abs:runBytes
              clc
              adc ##EPDIR-8
              sta abs:runSwitch
              lda ##.byte2 FLOOR_STAGE
              sta abs:run2Stage
              lda ##.byte2 FLOOR_PART_STAGE
              jmp abs:SetStageBank
episodeFirst: lda abs:splitBytes
              clc
              adc ##EPDIR-8
              sta abs:runSwitch
              lda ##.byte2 FLOOR_PART_STAGE
              sta abs:run2Stage
              rts
loadSplit:    .word 0
splitBytes:   .word 0
runBytes:     .word 0
runSwitch:    .word 0
runFill:      .word 0
run2Stage:    .word 0

#include "floppy_stream.inc"
