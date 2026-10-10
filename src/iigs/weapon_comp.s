;;; Load-time weapon drawer compiler (tools/weapon_units.py is the model).
;;;
;;; A shared unit loaded raw at $1D:F800 in a weapon view group. The loader
;;; calls WeaponComp once when this unit is in, then after the view's mask
;;; unit ($1D:6400, weapon_units.mask_unit), when it compiles all 20 poses
;;; and returns carry clear. buildPose makes each pose list (the pose_unit
;;; format of tools/weapon_units.py) at $1D:B000 from the mask; then each
;;; pose becomes the same code as registered_views.literal_weapon: word
;;; stores grouped by value (ascending), then byte stores grouped by value,
;;; then RTL. Code goes to the next free place in the two weapon regions;
;;; the entry table at $09:C800 gets its address.
;;;
;;; Bank $1D scratch: $0000 and $2000 word sort buffers, $4000 counts,
;;; $4400 and $5400 byte sort buffers; $6400 the view's mask; $8000 source
;;; indexes; $AC00 the floor's light table (A/B per index); $B000 the pose.
;;; buildPose uses $0000-$2AA7 (pixels by row), $2C00 (row positions) and
;;; $3000 (singles) before the compiler reuses them.

#include "memmap.inc"
QBUF          .equ 0x0000
ENTRIES       .equ WEAPON_ENTRIES


              .section weaponcomp, text, root, noreorder
              .public WeaponComp
WeaponComp:   php
              rep #0x30
              phb
              phd
              lda ##0
              tcd
              pea #0x1d1d
              plb
              plb
              lda abs:.word0 (wState)
              bne compileNext
              lda ##0x3500                ; first call: the regions are empty
              sta abs:.word0 (region1)
              lda ##0xca00
              sta abs:.word0 (region2)
              stz abs:.word0 (pose)
              inc abs:.word0 (wState)
              bra wMore
compileNext:  jsr abs:.word0 (buildPose)
              jsr abs:.word0 (compilePose)
              inc abs:.word0 (pose)
              lda abs:.word0 (pose)
              cmp ##20
              bcc compileNext
              stz abs:.word0 (wState)
              pld
              plb
              plp
              clc
              rtl
wMore:        pld
              plb
              plp
              sec
              rtl

;;; The pose list of pose (weapon_units.build_pose): pass 1 counts the pixels
;;; of each row, pass 2 writes (address, offset) in row order to QBUF (columns
;;; ascending within a row), then neighbours in a row become word stores.
buildPose:    ldx ##398
              lda ##0
bpClear:      sta abs:ROWS,x
              dex
              dex
              bpl bpClear
              jsr abs:.word0 (bpStart)
p1Column:     lda abs:0,x
              inx
              and ##255
              sta dp:B_RUNS
              beq p1NextColumn
p1Run:        lda abs:1,x
              and ##255
              asl a
              sta dp:B_Y1
              lda abs:0,x
              and ##255
              asl a
              inx
              inx
              inx
              inx
              stx dp:B_X
              tax
              cpx dp:B_Y1
              bcs p1RunDone
p1Pixel:      inc abs:ROWS,x
              inx
              inx
              cpx dp:B_Y1
              bcc p1Pixel
p1RunDone:    ldx dp:B_X
              dec dp:B_RUNS
              bne p1Run
p1NextColumn: dec dp:B_COLS
              bne p1Column
              ldx ##0                     ; counts -> positions in QBUF
              lda ##QBUF
              sta dp:B_POS
bpPrefix:     lda abs:ROWS,x
              asl a
              asl a
              sta dp:W_T
              lda dp:B_POS
              sta abs:ROWS,x
              clc
              adc dp:W_T
              sta dp:B_POS
              inx
              inx
              cpx ##400
              bcc bpPrefix
              sta dp:B_END
              jsr abs:.word0 (bpStart)
p2Column:     lda abs:0,x
              inx
              and ##255
              sta dp:B_RUNS
              beq p2NextColumn
p2Run:        lda abs:1,x
              and ##255
              asl a
              sta dp:B_Y1
              lda abs:2,x
              sta dp:B_SRC
              lda abs:0,x
              and ##255
              inx
              inx
              inx
              inx
              stx dp:B_X
              sta dp:W_T                  ; y0
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:W_N                  ; y0 * 32
              asl a
              asl a                       ; y0 * 128
              clc
              adc dp:W_N
              adc dp:B_COL
              sta dp:B_ADDR               ; y0 * 160 + the screen column
              lda dp:W_T
              asl a
              tax
              cpx dp:B_Y1
              bcs p2RunDone
p2Pixel:      lda abs:ROWS,x
              tay
              clc
              adc ##4
              sta abs:ROWS,x
              lda dp:B_ADDR
              sta abs:0,y
              clc
              adc ##160
              sta dp:B_ADDR
              lda abs:MASK+2,x            ; 2 * texel + (y & 1)
              clc
              adc dp:B_SRC
              sta abs:2,y
              inx
              inx
              cpx dp:B_Y1
              bcc p2Pixel
p2RunDone:    ldx dp:B_X
              dec dp:B_RUNS
              bne p2Run
p2NextColumn: inc dp:B_COL
              dec dp:B_COLS
              bne p2Column
              ldy ##POSE+4                ; pairs: words to POSE, singles to STEMP
              lda ##STEMP
              sta dp:B_S
              stz dp:B_NW
              stz dp:B_NS
              ldx ##QBUF
bpPair:       cpx dp:B_END
              bcs bpPaired
              txa
              clc
              adc ##4
              cmp dp:B_END
              bcs bpSingle
              lda abs:0,x
              inc a
              cmp abs:4,x
              bne bpSingle
              lda abs:0,x
              sta abs:0,y
              lda abs:2,x
              sta abs:2,y
              lda abs:6,x
              sta abs:4,y
              tya
              clc
              adc ##6
              tay
              txa
              clc
              adc ##8
              tax
              inc dp:B_NW
              bra bpPair
bpSingle:     phy
              ldy dp:B_S
              lda abs:0,x
              sta abs:0,y
              lda abs:2,x
              sta abs:2,y
              tya
              clc
              adc ##4
              sta dp:B_S
              ply
              inx
              inx
              inx
              inx
              inc dp:B_NS
              bra bpPair
bpPaired:     lda dp:B_NW
              sta abs:POSE
              lda dp:B_NS
              sta abs:POSE+2
              beq bpDone
              asl a
              asl a
              dec a
              ldx ##STEMP
              .byte 0x54, 0x1d, 0x1d      ; MVN: the singles after the words
bpDone:       rts

;;; X = the pose's data in MASK (after its column count), B_COLS, B_COL.
bpStart:      lda abs:.word0 (pose)
              asl a
              tax
              lda abs:MASK+402,x
              clc
              adc ##MASK
              tax
              lda abs:0,x
              and ##255
              sta dp:B_COLS
              inx
              lda abs:MASK
              sta dp:B_COL
              rts

;;; A = weapon-pixel offset -> A = its colour byte for this floor.
colorOf:      phx
              tax
              lda abs:WIDX,x
              and ##255
              asl a
              sta dp:W_T
              txa
              and ##1
              ora dp:W_T
              tax
              lda abs:WTAB,x
              and ##255
              plx
              rts

compilePose:  lda abs:POSE
              sta abs:.word0 (nWords)
              lda abs:POSE+2
              sta abs:.word0 (nSingles)
              ldx ##POSE+4                ; word stores -> (value, address) records
              ldy ##BUF_A
              lda abs:.word0 (nWords)
              sta dp:W_I
              beq wordsBuilt
wordRecord:   lda abs:0,x
              sta abs:2,y
              lda abs:4,x
              jsr abs:.word0 (colorOf)
              xba
              sta dp:W_PREV
              lda abs:2,x
              jsr abs:.word0 (colorOf)
              ora dp:W_PREV
              sta abs:0,y
              txa
              clc
              adc ##6
              tax
              iny
              iny
              iny
              iny
              dec dp:W_I
              bne wordRecord
wordsBuilt:   ldy ##BUF_C                 ; byte stores -> records
              lda abs:.word0 (nSingles)
              sta dp:W_I
              beq singlesBuilt
singleRecord: lda abs:0,x
              sta abs:2,y
              lda abs:2,x
              jsr abs:.word0 (colorOf)
              sta abs:0,y
              inx
              inx
              inx
              inx
              iny
              iny
              iny
              iny
              dec dp:W_I
              bne singleRecord
singlesBuilt: lda abs:.word0 (nWords)     ; words: low byte, then high byte
              sta dp:W_N
              lda ##BUF_A
              sta dp:W_IN
              lda ##BUF_B
              sta dp:W_OUT
              stz dp:W_KEY
              jsr abs:.word0 (radixPass)
              lda ##BUF_B
              sta dp:W_IN
              lda ##BUF_A
              sta dp:W_OUT
              lda ##1
              sta dp:W_KEY
              jsr abs:.word0 (radixPass)
              lda abs:.word0 (nSingles)   ; singles: one pass into BUF_D
              sta dp:W_N
              lda ##BUF_C
              sta dp:W_IN
              lda ##BUF_D
              sta dp:W_OUT
              stz dp:W_KEY
              jsr abs:.word0 (radixPass)
              ;; size = 3*(word groups + words) + byte part + 1
              ldx ##BUF_A
              lda abs:.word0 (nWords)
              jsr abs:.word0 (countGroups)
              clc
              adc abs:.word0 (nWords)
              sta dp:W_SIZE
              asl a
              clc
              adc dp:W_SIZE
              inc a
              sta dp:W_SIZE
              lda abs:.word0 (nSingles)
              beq sizeReady
              ldx ##BUF_D
              jsr abs:.word0 (countGroups)
              asl a                       ; 2 bytes per byte-value load
              clc
              adc ##4                     ; SEP and REP
              adc dp:W_SIZE
              sta dp:W_SIZE
              lda abs:.word0 (nSingles)
              asl a
              clc
              adc abs:.word0 (nSingles)
              adc dp:W_SIZE
              sta dp:W_SIZE
sizeReady:    lda abs:.word0 (region1)    ; first fit: region 1, then region 2
              clc
              adc dp:W_SIZE
              bcs useRegion2
              cmp ##0x9000
              beq useRegion1
              bcs useRegion2
useRegion1:   lda abs:.word0 (region1)
              sta dp:W_DST
              lda ##0x08
              sta dp:W_DST+2
              lda abs:.word0 (region1)
              clc
              adc dp:W_SIZE
              sta abs:.word0 (region1)
              bra emitCode
useRegion2:   lda abs:.word0 (region2)
              clc
              adc dp:W_SIZE
              bcc region2Fits
              beq region2Fits             ; ends exactly at $0A:0000
              brk                         ; weapon code exceeds its regions
region2Fits:  lda abs:.word0 (region2)
              sta dp:W_DST
              lda ##0x09
              sta dp:W_DST+2
              lda abs:.word0 (region2)
              clc
              adc dp:W_SIZE
              sta abs:.word0 (region2)
emitCode:     lda abs:.word0 (pose)       ; entry: code address, bank word
              asl a
              asl a
              tax
              lda dp:W_DST
              sta long:ENTRIES,x
              lda dp:W_DST+2
              sta long:ENTRIES+2,x
              ldy ##0
              ldx ##BUF_A                 ; word groups: LDA #value, STA addr...
              lda abs:.word0 (nWords)
              sta dp:W_I
              beq emitSingles
              lda abs:0,x
              eor ##0xffff
              sta dp:W_PREV               ; differs from the first value
emitWord:     lda abs:0,x
              cmp dp:W_PREV
              beq emitWordStore
              sta dp:W_PREV
              lda ##0xa9
              jsr abs:.word0 (putByte)
              lda dp:W_PREV
              jsr abs:.word0 (putWord)
emitWordStore:lda ##0x8d
              jsr abs:.word0 (putByte)
              lda abs:2,x
              clc
              adc ##0x2000
              jsr abs:.word0 (putWord)
              inx
              inx
              inx
              inx
              dec dp:W_I
              bne emitWord
emitSingles:  lda abs:.word0 (nSingles)
              sta dp:W_I
              beq emitEnd
              lda ##0x20e2                ; SEP #$20
              jsr abs:.word0 (putWord)
              ldx ##BUF_D
              lda abs:0,x
              eor ##0xffff
              sta dp:W_PREV
emitSingle:   lda abs:0,x
              cmp dp:W_PREV
              beq emitSingleStore
              sta dp:W_PREV
              xba
              ora ##0xa9                  ; LDA #value
              jsr abs:.word0 (putWord)
emitSingleStore:
              lda ##0x8d
              jsr abs:.word0 (putByte)
              lda abs:2,x
              clc
              adc ##0x2000
              jsr abs:.word0 (putWord)
              inx
              inx
              inx
              inx
              dec dp:W_I
              bne emitSingle
              lda ##0x20c2                ; REP #$20
              jsr abs:.word0 (putWord)
emitEnd:      lda ##0x6b                  ; RTL
              jsr abs:.word0 (putByte)
              cpy dp:W_SIZE
              beq emitDone
              brk                         ; emitted size differs from the plan
emitDone:     rts

putByte:      sep #0x20
              sta [W_DST],y
              rep #0x20
              iny
              rts
putWord:      sta [W_DST],y
              iny
              iny
              rts

;;; A = record count, X = buffer: A = number of distinct values in order.
countGroups:  sta dp:W_I
              lda ##0
              ldy dp:W_I
              beq groupsCounted
              sta dp:W_T
              lda abs:0,x
              eor ##0xffff
              sta dp:W_PREV
groupLoop:    lda abs:0,x
              cmp dp:W_PREV
              beq groupSame
              sta dp:W_PREV
              inc dp:W_T
groupSame:    inx
              inx
              inx
              inx
              dey
              bne groupLoop
              lda dp:W_T
groupsCounted:rts

;;; Stable counting sort of W_N 4-byte records W_IN -> W_OUT by the byte at
;;; offset W_KEY (0 low, 1 high) of the record's value.
radixPass:    ldx ##510
              lda ##0
clearCounts:  sta abs:COUNTS,x
              dex
              dex
              bpl clearCounts
              lda dp:W_N
              beq radixDone
              sta dp:W_I
              lda dp:W_IN
              clc
              adc dp:W_KEY
              tax
countKeys:    lda abs:0,x
              and ##255
              asl a
              tay
              lda abs:COUNTS,y
              clc
              adc ##4
              sta abs:COUNTS,y
              inx
              inx
              inx
              inx
              dec dp:W_I
              bne countKeys
              ldx ##0                     ; counts -> output offsets
              lda dp:W_OUT
prefix:       ldy abs:COUNTS,x
              sta abs:COUNTS,x
              sty dp:W_T
              clc
              adc dp:W_T
              inx
              inx
              cpx ##512
              bcc prefix
              lda dp:W_N
              sta dp:W_I
              ldx dp:W_IN
place:        txa
              clc
              adc dp:W_KEY
              tay
              lda abs:0,y
              and ##255
              asl a
              tay
              lda abs:COUNTS,y
              phy
              tay
              lda abs:0,x
              sta abs:0,y
              lda abs:2,x
              sta abs:2,y
              ply
              lda abs:COUNTS,y
              clc
              adc ##4
              sta abs:COUNTS,y
              inx
              inx
              inx
              inx
              dec dp:W_I
              bne place
radixDone:    rts

wState:       .word 0
pose:         .word 0
region1:      .word 0
region2:      .word 0
nWords:       .word 0
nSingles:     .word 0
