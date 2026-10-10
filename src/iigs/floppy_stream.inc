;;; Read floppy units before decoding. Adjacent packed units share the current
;;; load-time stage. Reserve 2 KB after the buffered input for HLZ's tables.
;;; No buffer uses the play cache. Hard disks keep the ordinary block loop.
;;;
;;; ReadFloppyUnit: JSR with A/X/Y 16-bit, DBR = 0 and D = 0. LV_BLOCK_HI:
;;; LV_BLOCK and LV_COUNT describe the unit; BOOT_DEST is its read destination.
;;; Carry clear consumes the unit and credits its progress; carry set leaves
;;; it for the ordinary block loop. X/Y are scratch. Only packed floor units
;;; at stage offset zero may start a prefetched run.
              .section floppystream, text, root
              .public ReadFloppyUnit, StreamTables
STREAM_GAP    .equ 1024/512
STREAM_TABLES .equ 2048/512

ReadFloppyUnit:
              lda dp:BOOT_PD_UNIT
              and ##0x70
              cmp ##0x50
              beq floppyUnit
              sec
              rts
floppyUnit:   lda dp:LV_COUNT
              sta abs:streamUnitBlocks
              lda dp:LV_BLOCK
              sta abs:streamUnitBlock
              lda dp:LV_BLOCK_HI
              sta abs:streamUnitHigh
              lda dp:LV_FLAGS
              beq streamPlain
              lda abs:stageStart
              ora abs:loadAux
              ora abs:loadMusic
              bne streamPlain
              lda abs:streamBlocks
              beq streamNew
              lda dp:LV_BLOCK_HI
              cmp abs:streamHigh
              bne streamNew
              lda dp:LV_RECORD
              cmp abs:streamLast
              beq streamHitCheck
              bcs streamNew
streamHitCheck:
              lda dp:LV_BLOCK
              sec
              sbc abs:streamFirst
              bcc streamNew
              tax
              clc
              adc dp:LV_COUNT
              cmp abs:streamBlocks
              beq streamHit
              bcs streamNew
streamHit:    txa
              xba
              asl a
              sta abs:stageStart
              lda abs:stageBank
              cmp abs:streamBank
              beq streamHitReady
              sep #0x20
              sta abs:streamMove+1
              lda abs:streamBank
              sta abs:streamMove+2
              rep #0x20
              ldx abs:stageStart
              ldy ##0
              lda abs:streamUnitBlocks
              xba
              asl a
              dec a
              phb
streamMove:   .byte 0x54, 0, 0
              plb
              stz abs:stageStart
streamHitReady:
              jmp abs:streamReadDone
streamPlain:  stz abs:streamBlocks
              jsr abs:streamRead
              jmp abs:streamReadDone
streamNew:    stz abs:streamBlocks
              jsl long:streamPlan
              jsr abs:streamRead
streamReadDone:
              lda abs:streamUnitBlock
              clc
              adc abs:streamUnitBlocks
              sta dp:LV_BLOCK
              lda abs:streamUnitHigh
              adc ##0
              sta dp:LV_BLOCK_HI
              stz dp:LV_COUNT
              lda dp:LV_DONE
              clc
              adc abs:streamUnitBlocks
              sta dp:LV_DONE
              lda long:bootComplete
              beq streamBootCredit
              lda abs:streamUnitBlocks
              asl a
              sta abs:streamCredit
              asl a
              asl a
              asl a
              clc
              adc abs:streamCredit         ; floppy read work: 18 per block
              jsl long:ProgressAdd
streamDone:   clc
              rts
streamBootCredit:
              lda abs:loadKeep
              bne streamDone
              lda abs:streamUnitBlocks
              sta abs:streamCredit
streamBootStep:
              dec dp:LV_NEXTCELL
              bne streamBootNext
              lda dp:LV_STEP
              sta dp:LV_NEXTCELL
              sep #0x20
              lda dp:BOOT_CELLS
              cmp #34
              bcs streamBootFull
              inc dp:BOOT_CELLS
              lda #BOOT_BAR_FULL
              sta dp:BOOT_CCOLOR
              lda dp:BOOT_CELLS
              jsr abs:BOOT_drawCell
streamBootFull:
              rep #0x20
streamBootNext:
              dec abs:streamCredit
              bne streamBootStep
              bra streamDone

;;; Plan from LV_RECORD without moving the directory cursor. Coalesce only
;;; packed records within one disk-map run and floor run, with gaps of at most
;;; STREAM_GAP blocks. Stop before an output could overwrite staged input.
;;; Reserve STREAM_TABLES blocks beyond the input; the floor-stage capacity
;;; also fits the larger effects stage. LV_COUNT becomes the full read span.
streamFindRun:jsr abs:findRun
              rtl
              .section streamplan, text, root
streamPlan:   lda ##FLOOR_STAGE_SIZE/512-STREAM_TABLES
              ldx abs:stageBank
              cpx ##.byte2 BOOT_STAGE
              bne streamLimit
              lda ##BOOT_STAGE_SIZE/512-STREAM_TABLES
streamLimit:  sta abs:streamCapacity
              cmp dp:LV_COUNT
              bcs streamPlanCheck1
              rtl
streamPlanCheck1:
              jsl long:streamFindRun
              bcc streamPlanCheck2
              rtl
streamPlanCheck2:
              lda abs:0,x
              clc
              adc abs:2,x
              bcc streamPlanCheck3
              rtl
streamPlanCheck3:
              sta abs:streamRunEnd
              lda dp:LV_BLOCK
              sta abs:streamFirst
              clc
              adc dp:LV_COUNT
              bcc streamPlanCheck4
              rtl
streamPlanCheck4:
              cmp abs:streamRunEnd
              beq streamInitial
              bcc streamPlanCheck5
              rtl
streamPlanCheck5:
streamInitial:sta abs:streamEnd
              lda dp:LV_COUNT
              sta abs:streamBlocks
              lda dp:LV_BLOCK_HI
              sta abs:streamHigh
              lda abs:stageBank
              sta abs:streamBank
              ldx dp:LV_RECORD
              stx abs:streamLast
              lda dp:LV_LEFT
              sta abs:streamLeft
streamNeighbour:
              dec abs:streamLeft
              beq streamPlanned
              cpx abs:runSwitch
              beq streamPlanned
              txa
              clc
              adc ##8
              tax
              lda abs:2,x
              bit ##0x100
              beq streamPlanned
              and ##255
              cmp abs:streamBank
              bne streamOtherBank
              lda abs:streamCapacity
              clc
              adc ##STREAM_TABLES
              xba
              asl a
              beq streamPlanned          ; all of BOOT_STAGE is scratch
              cmp abs:0,x
              beq streamOtherBank
              bcs streamPlanned          ; the output would cover the buffer
streamOtherBank:
              lda abs:loadWide
              beq streamLowBlock
              lda abs:2,x
              asl a
              lda ##0
              rol a
              cmp abs:streamHigh
              bne streamPlanned
streamLowBlock:
              lda abs:4,x
              sec
              sbc abs:streamEnd
              bcc streamPlanned
              cmp ##STREAM_GAP+1
              bcs streamPlanned
              lda abs:4,x
              clc
              adc abs:6,x
              bcs streamPlanned
              cmp abs:streamRunEnd
              beq streamFitsRun
              bcs streamPlanned
streamFitsRun:sta abs:streamProposed
              sec
              sbc abs:streamFirst
              cmp abs:streamCapacity
              beq streamFitsStage
              bcs streamPlanned
streamFitsStage:
              sta abs:streamBlocks
              sta dp:LV_COUNT
              lda abs:streamProposed
              sta abs:streamEnd
              stx abs:streamLast
              bra streamNeighbour
streamPlanned:rtl

;;; Look up the caches before a contiguous disk run. A hit takes the ordinary
;;; store path, which still serves both caches. A run of misses needs no cache
;;; search or disk-map search between firmware calls. cacheKeep still runs.
              .section floppystream, text, root
streamRead:   lda ##BOOT_BUF
              sta dp:LV_BUFFER
              stz abs:streamDirect
              lda dp:LV_BLOCK
              sta abs:streamReadFirst
              lda dp:LV_COUNT
              sta abs:streamReadCount
              jsr abs:findRun
              bcs streamSlow
              sta abs:streamPhysical
              lda abs:0,x
              clc
              adc abs:2,x
              bcs streamSlow
              sta abs:streamRunEnd
              lda dp:LV_BLOCK
              clc
              adc dp:LV_COUNT
              bcs streamSlow
              cmp abs:streamRunEnd
              beq streamScan
              bcs streamSlow
streamScan:   jsr abs:cacheLookup
              bcc streamSlow
              inc dp:LV_BLOCK
              dec dp:LV_COUNT
              bne streamScan
              inc abs:streamDirect
streamSlow:   lda abs:streamReadFirst
              sta dp:LV_BLOCK
              lda abs:streamReadCount
              sta dp:LV_COUNT
streamReadBlock:
              lda abs:streamDirect
              beq streamMappedRead
              lda abs:streamPhysical
              jsr abs:storeOnDisk
              inc abs:streamPhysical
              bra streamCopy
streamMappedRead:
              jsr abs:storeBlock
streamCopy:   sep #0x20
              jsr abs:BOOT_copyBlock
              rep #0x20
              inc dp:LV_BLOCK
              bne streamNextBlock
              inc dp:LV_BLOCK_HI
streamNextBlock:
              dec dp:LV_COUNT
              bne streamReadBlock
              rts

;;; HLZ lookup tables follow all prefetched input, not the current unit.
;;; JSL, A/X/Y 16-bit, DBR = 0, D = 0. Return the table offset in A.
StreamTables: lda long:streamBlocks
              beq streamUnitTables
              lda long:stageBank
              cmp long:streamBank
              bne streamUnitTables
              lda long:streamBlocks
              xba
              asl a
              rtl
streamUnitTables:
              lda abs:6,x
              xba
              asl a
              clc
              adc dp:HLZ_PTR
              rtl

;;; B1 expects input at BOOT_STAGE's start. Move a prefetched unit down
;;; before decoding; the forward copy cannot reach a later unit.
;;; The fast codecs consume stageStart directly and need no relocation.
StreamB1:     lda abs:streamBlocks
              beq streamB1Ready
              lda abs:stageStart
              beq streamB1Ready
              tax
              ldy ##.word0 BOOT_STAGE
              lda abs:streamUnitBlocks
              xba
              asl a
              dec a
              phb
              .byte 0x54, .byte2 BOOT_STAGE, .byte2 BOOT_STAGE
              plb
streamB1Ready:rts

streamBlocks:     .word 0
streamFirst:      .word 0
streamHigh:       .word 0
streamBank:       .word 0
streamLast:       .word 0
streamEnd:        .word 0
streamCapacity:   .word 0
streamProposed:   .word 0
streamLeft:       .word 0
streamRunEnd:     .word 0
streamUnitBlocks: .word 0
streamUnitBlock:  .word 0
streamUnitHigh:   .word 0
streamCredit:     .word 0
streamReadFirst:  .word 0
streamReadCount:  .word 0
streamPhysical:   .word 0
streamDirect:     .word 0
