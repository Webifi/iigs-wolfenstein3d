;;; WOLF.BOOT stage-2 loader. boot.s enters in emulation mode with
;;; X = the boot drive's ProDOS unit. The loader checks required RAM banks,
;;; reads each disk header into HDR, and loads its segments to 24-bit addresses.
;;; B1 segments decode through BOOT_STAGE; raw segments copy from the block buffer.
;;;
;;; Store-only disks are loaded only when the store banks are present. Otherwise
;;; boot ends at HDR_RESDISKS and floor loading reads the store on demand. Each
;;; disk must match the requested number and the first disk's set identifier.
;;; BOOTINFO records the drive, settings location, RAM map and store mode before
;;; the loader jumps to HDR_ENTRY in native mode.
;;;
;;; Title SCBs and palettes load before the interlaced pixel blocks. The game
;;; retains that display until BootPicture handles it during frontend startup.
;;;
;;; Disk header (block 1, tools/mkdisk.py):
;;;   0   "WOLFGS"
;;;   6   disk number, 1 based
;;;   7   number of disks
;;;   8   number of segments on this disk
;;;   10  entry point, 3 bytes
;;;   13  progress-step ninth bits: bit0 disk store, bit1 RAM store
;;;   14  blocks per bar cell when the store stays on disk
;;;   15  blocks per bar cell when the store loads (its banks are RAM)
;;;   16  segments, 8 bytes each: address (3), flags (1), first block (2),
;;;       count (2). Flag SEG_B1: the blocks are the B1 stream of the
;;;       segment (tools/b1.py: its length, then B1), read to STAGE and
;;;       decoded. Flag SEG_PIC: the 64 blocks of the title picture (an
;;;       image of the screen memory), in the order of HDR_ORDER. The last
;;;       disk has the block of WOLF.SETTINGS as a segment to SETTINGS_IN,
;;;       then WOLF.SETX as a raw segment over the name block in bank 2
;;;   368 the disk of each floor, a byte per floor (tools/mkdisk.py). The
;;;       store runs of the disk follow the segments: 8 bytes each, the first
;;;       store block, the count, the first disk block, the disk and bit 16 of
;;;       the store block; a zero count ends them
;;;   432 disk-set identifier, four bytes shared by every disk in the set
;;;   436 disk 1: the block of WOLF.SETTINGS
;;;   438 the last disk with data below the store, the banks of the store
;;;   448 HDR_ORDER: the picture block of each block of the SEG_PIC segment
;;;
;;; BOOTINFO for the game (frontend.inc), 100 bytes:
;;;   0   "DB"
;;;   2   the ProDOS unit of the boot drive
;;;   3   its SmartPort unit
;;;   4   the ProDOS block driver of the slot, 2 bytes
;;;   6   the SmartPort entry of the slot, 2 bytes
;;;   8   the block of WOLF.SETTINGS on disk 1, 2 bytes
;;;   10  home disk in bits 0-6; bit 7 means the play cache was loaded
;;;   12  disk-set identifier, 4 bytes
;;;   16  the mode: 1 the store is in RAM (8 MB), 0 the game reads it
;;;   17  the last disk with data below the store, 18 the number of disks,
;;;   19  the banks of the store
;;;   20  the RAM banks $00-$7F: a bit each (bank b: byte b >> 3, bit b & 7)
;;;   36  the disk of each floor, from the header (64 bytes)



SEG_PIC       .equ    1               ; segment flag: the title picture
SEG_B1        .equ    2               ; segment flag: a B1 stream
STAGE         .equ    BOOT_STAGE        ; the blocks of a B1 segment (a bank of
                                      ;   the level window, free at boot)

SCREEN        .equ    SHR        ; the super hi-res screen: 200 rows of
SCB           .equ    SHR_SCB        ;   160 bytes, the palette of each row
PALETTES      .equ    SHR_PAL        ; 16 palettes of 16 colors

STRIP_ROW     .equ    191             ; the load strip: rows 191-199 of the
STRIP_PAL     .equ    15              ;   title, palette 15 (tools/gscolor.py)
STRIP         .equ    STRIP_ROW * 160 ; its first screen byte
PIXELS_END    .equ    200 * 160       ; the end of the pixels
ICON_OFS      .equ    STRIP + 2       ; the disk icon at x 4
COUNT_OFS     .equ    STRIP + 160 + 10 ; the disk number at x 20, row 192
PROMPT_OFS    .equ    STRIP + 160 + 30 ; INSERT DISK n at x 60
TEXT_START    .equ    STRIP + 160 + 22 ; rows 192-198 from x 44: the bar
TEXT_ROWS     .equ    7               ;   or the prompt

#include "memmap.inc"
#include "loadbar.inc"

              .section loader, text, root, noreorder
              .public loaderStart
loaderStart:  sei
              cld
              stx     dp:PD_UNIT
              txa                           ; the ProDOS entry of the boot
              lsr     a                     ;   slot: $Cn00 + ($CnFF)
              lsr     a
              lsr     a
              lsr     a
              ora     #0xc0
              sta     abs:drvAddr+1
              sta     abs:spAddr+1
              sta     dp:LOADER_TMP+1
              lda     #0xff
              sta     dp:LOADER_TMP
              ldy     #0
              lda     (LOADER_TMP),y
              sta     abs:drvAddr
              clc                           ; the SmartPort entry is 3 bytes
              adc     #3                    ;   after it
              sta     abs:spAddr
              lda     dp:PD_UNIT            ; SmartPort unit 1 or 2: the drive
              asl     a                     ;   bit of the ProDOS unit
              lda     #0
              rol     a
              inc     a
              sta     abs:spUnit
              clc
              xce                           ; native mode: A 8 bits, X and Y
              rep     #0x10                 ;   16 bits from here on
              jsr     abs:checkMemory
              bcc     1$
              jmp     abs:cannotRun
1$:           jsr     abs:screenOn
              lda     #1
              sta     dp:DISKNUM
              stz     dp:CELLS
              jsr     abs:readHeader
              php
              jsr     abs:drawStrip
              plp
              bcc     2$
              jsr     abs:waitDisk          ; not disk 1: ask for it
2$:           jsr     abs:storeMode         ; then the step for that boot
              jsr     abs:loadStep
              sta     dp:STEPLEFT
              sep     #0x20

;;; The segments of the disk DISKNUM, its header in HDR.
diskLoop:     lda     abs:HDR_SEGS
              sta     dp:SEGS
              ldx     ##HDR_SEG
              stx     dp:SEGPTR
segLoop:      lda     dp:SEGS
              bne     1$
              jmp     abs:diskDone
1$:           ldy     ##2                   ; the store, when the game reads it
              lda     (SEGPTR),y
              cmp     #.byte2 SLOW_RAM      ; slow RAM assets are always resident
              bcs     11$
              cmp     #STORE_BANK
              bcc     11$
              lda     dp:STOREMODE
              bne     11$
              jmp     abs:segDone
11$:          ldy     ##0
              lda     (SEGPTR),y            ; the address
              sta     dp:SEGADDR
              sta     dp:DEST
              iny
              lda     (SEGPTR),y
              sta     dp:SEGADDR+1
              sta     dp:DEST+1
              iny
              lda     (SEGPTR),y
              sta     dp:SEGADDR+2
              sta     dp:DEST+2
              iny
              lda     (SEGPTR),y
              sta     dp:SEG_FLAGS
              rep     #0x20
              ldy     ##4
              lda     (SEGPTR),y            ; the first block
              sta     dp:PD_BLOCK
              ldy     ##6
              lda     (SEGPTR),y            ; the count
              sta     dp:BLKLEFT
              stz     dp:BLKNUM
              sep     #0x20
              lda     dp:SEG_FLAGS              ; a B1 segment: its blocks to STAGE
              and     #SEG_B1
              beq     blockLoop
              ldx     ##.word0 STAGE
              stx     dp:DEST
              lda     #.byte2 STAGE
              sta     dp:DEST+2

blockLoop:    ldx     dp:BLKLEFT
              beq     segDone
              ldx     ##BUF
              stx     dp:PD_BUF
              jsr     abs:readBlock
              bcc     1$
              jmp     abs:readError
1$:           lda     dp:SEG_FLAGS
              and     #SEG_PIC
              beq     2$
              jsr     abs:picBlock
2$:           jsr     abs:copyBlock
              jsr     abs:stepBar
              rep     #0x20
              inc     dp:PD_BLOCK
              inc     dp:BLKNUM
              dec     dp:BLKLEFT
              sep     #0x20
              bra     blockLoop

segDone:      lda     dp:SEG_FLAGS              ; a B1 segment: decoded to its place
              and     #SEG_B1
              beq     1$
              jsr     abs:b1Seg
1$:           rep     #0x20
              lda     dp:SEGPTR
              clc
              adc     ##8
              sta     dp:SEGPTR
              sep     #0x20
              dec     dp:SEGS
              jmp     abs:segLoop

diskDone:     lda     dp:DISKNUM            ; the last disk stays in
              cmp     dp:LASTDISK
              bcs     allLoaded
              inc     dp:DISKNUM
              jsr     abs:waitDisk          ; the other drive may already have it
              jmp     abs:diskLoop

allLoaded:    lda     #BAR_FULL             ; the cells of the load all full
              sta     dp:CCOLOR
1$:           lda     dp:CELLS
              cmp     #LOAD_CELLS
              bcs     2$
              inc     dp:CELLS
              jsr     abs:drawCell
              bra     1$
2$:           lda     #'D'                  ; BOOTINFO
              sta     abs:BOOTINFO
              lda     #'B'
              sta     abs:BOOTINFO+1
              lda     dp:PD_UNIT
              sta     abs:BOOTINFO+2
              lda     abs:spUnit
              sta     abs:BOOTINFO+3
              ldx     abs:drvAddr
              stx     abs:BOOTINFO+4
              ldx     abs:spAddr
              stx     abs:BOOTINFO+6
              ldx     abs:settingsBlock
              stx     abs:BOOTINFO+8
              lda     abs:HDR_HOME_DISK
              sta     abs:BI_HOME_DISK
              stz     abs:BOOTINFO+11
              ldx     abs:HDR_BUILD
              stx     abs:BOOTINFO+12
              ldx     abs:HDR_BUILD+2
              stx     abs:BOOTINFO+14
              lda     dp:STOREMODE
              sta     abs:BOOTINFO+16
              lda     abs:HDR_RESDISKS
              sta     abs:BOOTINFO+17
              lda     dp:NDISKS
              sta     abs:BOOTINFO+18
              lda     abs:HDR_STOREBANKS
              sta     abs:BOOTINFO+19
              ldx     ##HDR_FLOOR_DISKS_SIZE-1 ; the disk of each floor
3$:           lda     abs:HDR_FLOOR_DISKS,x
              sta     abs:BI_FLOOR_DISKS,x
              dex
              bpl     3$
              ldx     abs:HDR_ENTRY
              stx     abs:jmlInst+1
              lda     abs:HDR_ENTRY+2
              sta     abs:jmlInst+3
              rep     #0x30
jmlInst:      .byte   0x5c, 0x00, 0x00, 0x00 ; jml

;;; ---------------------------------------------------------------------------
;;; The memory check.
;;; ---------------------------------------------------------------------------

;;; Probe banks $02-$7F before loading any assets. High-to-low writes and
;;; reads reject lower-bank aliases without mistaking the immediately prior
;;; write for a read. Two independent offsets tolerate an isolated bad byte.
;;; Only $02-$41 are required; additional real banks may hold the level store.
checkMemory:  stz     dp:PTR
              stz     dp:PTR+1
              lda     #0x7f
1$:           sta     dp:PTR+2
              eor     #0xff
              sta     [PTR]
              eor     #0xff
              dec     a
              cmp     #2
              bcs     1$
              ldx     ##15                  ; BI_BANKS: $00-$01 (the board)
0$:           stz     abs:BI_BANKS,x
              dex
              bpl     0$
              lda     #3
              sta     abs:BI_BANKS
              lda     #0x7f
2$:           sta     dp:PTR+2
              eor     #0xff
              cmp     [PTR]
              bne     4$
              lda     dp:PTR+2              ; a RAM bank: its bit
              jsr     abs:bankBit
              lda     abs:BI_BANKS,x
              ora     dp:LOADER_TMP
              sta     abs:BI_BANKS,x
4$:           lda     dp:PTR+2
              dec     a
              cmp     #2
              bcs     2$
              ldx     ##0x5a5a              ; the second probe
              stx     dp:PTR
              lda     #0x7f
3$:           sta     dp:PTR+2
              jsr     abs:p2Word
              sta     [PTR]
              sep     #0x20
              lda     dp:PTR+2
              dec     a
              cmp     #2
              bcs     3$
              lda     #0x7f
7$:           sta     dp:PTR+2
              jsr     abs:p2Word
              cmp     [PTR]
              sep     #0x20
              bne     9$
              lda     dp:PTR+2
              jsr     abs:bankBit
              lda     abs:BI_BANKS,x
              ora     dp:LOADER_TMP
              sta     abs:BI_BANKS,x
9$:           lda     dp:PTR+2
              dec     a
              cmp     #2
              bcs     7$
              lda     #2                    ; the fixed banks
5$:           jsr     abs:isBank
              bcc     8$
              inc     a
              cmp     #0x42
              bcc     5$
              clc
              rts
8$:           sec
              rts

;;; p2Word: C = the word of the second probe for bank A; A is 16 bits
;;; after it. Its two bytes are never equal, so a bank with no RAM, which
;;; gives one value on both reads, fails.
p2Word:       rep     #0x20
              and     ##0x00ff
              eor     ##0xa55a
              rts

;;; isBank: carry set when bank A is RAM (BI_BANKS). A stays.
isBank:       jsr     abs:bankBit
              pha
              lda     abs:BI_BANKS,x
              and     dp:LOADER_TMP
              cmp     #1                    ; (carry: not 0)
              pla
              rts

;;; bankBit: X = the byte of bank A in BI_BANKS, LOADER_TMP = its bit. A stays.
;;; (TAX with an 8-bit A copies B too: the index is made in 16 bits.)
bankBit:      pha
              rep     #0x20
              and     ##0x0007
              tax
              sep     #0x20
              lda     abs:bitOf,x
              sta     dp:LOADER_TMP
              lda     1,s
              rep     #0x20
              and     ##0x00ff
              lsr     a
              lsr     a
              lsr     a
              tax
              sep     #0x20
              pla
              rts

;;; storeMode: STOREMODE = 1 when the banks of the store are RAM, then
;;; LASTDISK = the number of disks; else the last disk with other data.
storeMode:    stz     dp:STOREMODE
              lda     abs:HDR_STOREBANKS
              beq     3$
              clc
              adc     #STORE_BANK
              bcs     3$
              cmp     #0x81
              bcs     3$
              sta     dp:LOADER_TMP+1
              lda     #STORE_BANK
1$:           jsr     abs:isBank
              bcc     3$
              inc     a
              cmp     dp:LOADER_TMP+1
              bcc     1$
              inc     dp:STOREMODE
3$:           lda     dp:STOREMODE
              beq     4$
              lda     dp:NDISKS
              bra     5$
4$:           lda     abs:HDR_RESDISKS
5$:           sta     dp:LASTDISK
              ldx     abs:HDR_SETTINGS      ; (on the home disk; every header has it)
              stx     abs:settingsBlock
              rts

;;; cannotRun: the text screen that says why the game cannot run. A = the
;;; first bank that is not RAM: the IIgs has about A / 16 MB.
cannotRun:    lsr     a
              lsr     a
              lsr     a
              lsr     a
              bne     1$
              ldx     ##msgLess             ; less than 1 MB
              stx     dp:LOADER_TMP
              ldx     ##msgHasNum
              bra     2$
1$:           ora     #'0'
              sta     abs:msgHasNum
              ldx     ##msgMB
              stx     dp:LOADER_TMP
              ldx     ##msgHasNum+1
2$:           ldy     ##0                   ; the size and the end of the line
3$:           lda     (LOADER_TMP),y
              sta     abs:0,x
              beq     4$
              inx
              iny
              bra     3$
4$:           jsr     abs:textScreen
              sep     #0x10
              ldx     #.byte0 msgSorry
              ldy     #.byte1 msgSorry
              jsr     abs:printAt
              ldx     #.byte0 msgSorry2
              ldy     #.byte1 msgSorry2
              jsr     abs:printAt
              ldx     #.byte0 msgNeeds
              ldy     #.byte1 msgNeeds
              jsr     abs:printAt
              ldx     #.byte0 msgHas
              ldy     #.byte1 msgHas
              jsr     abs:printAt
              ldx     #.byte0 msgAdd
              ldy     #.byte1 msgAdd
              jsr     abs:printAt
              ldx     #.byte0 msgAdd2
              ldy     #.byte1 msgAdd2
              jsr     abs:printAt
hang:         bra     hang

;;; readError: a disk read error: the text screen says so, and the loader
;;; stops.
readError:    jsr     abs:textScreen
              sep     #0x10
              ldx     #.byte0 msgReadError
              ldy     #.byte1 msgReadError
              jsr     abs:printAt
              bra     hang

;;; textScreen: the 40 column text screen, cleared, with the title.
textScreen:   lda     abs:NEWVIDEO_00
              and     #0x7f
              sta     abs:NEWVIDEO_00
              sta     abs:TXTSET_00            ; text mode
              sta     abs:TXTPAGE1_00            ; page 1
              sta     abs:CLR80VID_00            ; 40 columns
              sta     abs:CLRALTCHAR_00            ; primary character set
              sep     #0x10
              jsr     abs:clearScreen
              ldx     #.byte0 msgTitle
              ldy     #.byte1 msgTitle
              jsr     abs:printAt
              rep     #0x10
              rts

;;; ---------------------------------------------------------------------------
;;; Disk access. The firmware runs in emulation mode; these routines switch
;;; to it and back (X and Y lose their high bytes).
;;; ---------------------------------------------------------------------------

;;; readBlock: block PD_BLOCK to PD_BUF; carry set on an error.
readBlock:    lda     #1
              sta     dp:PD_CMD
              sec
              xce
              jsr     abs:callDriver
              lda     #0
              rol     a                     ; the error, over the mode change
              clc
              xce
              rep     #0x10
              lsr     a
              rts
callDriver:   jmp     (abs:drvAddr)

;;; spCall: the SmartPort call A (0 STATUS, 4 CONTROL) for the boot drive,
;;; with the code in spCode and the list at spList; carry set on an error.
spCall:       sta     abs:spCmd
              sec
              xce
              jsr     abs:spJump
spCmd:        .byte   0
              .word   spParams
              lda     #0
              rol     a
              clc
              xce
              rep     #0x10
              lsr     a
              rts
spJump:       jmp     (abs:spAddr)

;;; Request eject with SmartPort CONTROL code 4. Drives without eject
;;; support retain the disk; the caller keeps checking for the requested disk.
ejectDisk:    lda     #4
              sta     abs:spCode
              stz     abs:spList            ; no control data
              stz     abs:spList+1
              lda     #4
              jmp     abs:spCall

;;; diskIn: carry set when a disk is in the drive (SmartPort STATUS, code
;;; 0: bit 4 of the status byte); also when the call fails.
diskIn:       stz     abs:spCode
              lda     #0
              jsr     abs:spCall
              bcs     1$
              lda     abs:spList
              and     #0x10
              beq     2$
1$:           sec
              rts
2$:           clc
              rts

;;; Read block 1 into HDR. Carry clear requires the expected disk number and
;;; set identifier. Disk 1 establishes buildId; later disks must match it.
;;; A valid header supplies NDISKS before the disk-number check.
readHeader:   ldx     ##HDR
              stx     dp:PD_BUF
              ldx     ##1
              stx     dp:PD_BLOCK
              jsr     abs:readBlock
              bcs     9$
              ldx     ##5
1$:           lda     abs:HDR,x
              cmp     abs:magic,x
              bne     9$
              dex
              bpl     1$
              lda     abs:HDR_DISKS
              sta     dp:NDISKS
              lda     abs:HDR_DISK
              cmp     dp:DISKNUM
              bne     9$
              ldx     abs:HDR_BUILD
              ldy     abs:HDR_BUILD+2
              cmp     #1
              bne     2$
              stx     abs:buildId
              sty     abs:buildId+2
              bra     3$
2$:           cpx     abs:buildId
              bne     9$
              cpy     abs:buildId+2
              bne     9$
3$:           clc
              rts
9$:           sec
              rts

;;; readHeader2: readHeader, once more after a failure: the first read
;;; after a disk change fails (the firmware reports the change), and the
;;; disk would go out as a wrong one (booting from disk 2: disk 1 went out
;;; again and again, the loader waited for ever).
readHeader2:  jsr     abs:readHeader
              bcc     1$
              jsr     abs:readHeader
1$:           rts

;;; b1Seg: the B1 stream at STAGE (its length, then B1: tools/b1.py) to
;;; SEGADDR (the segment of HDR at SEGPTR). The decoder of
;;; src/iigs/w_level65.s; the output ends at B1_END (it may be the end of
;;; the bank: 0), so the test is equality.
b1Seg:        lda     dp:SEGADDR+2          ; the banks into the code
              sta     abs:b1Lmvn+1
              sta     abs:b1Mmvn+1
              sta     abs:b1Mmvn+2
              lda     #.byte2 STAGE
              sta     abs:b1Lmvn+2
              sta     abs:b1Rdb+3
              sta     abs:b1Rdw+3
              rep     #0x30
              lda     long:STAGE            ; the end
              clc
              adc     dp:SEGADDR
              sta     dp:B1_END
              lda     ##0x8000
              sta     dp:B1_BITS
              lda     ##1
              sta     dp:B1_OFF
              ldx     ##(.word0 STAGE + 2)
              ldy     dp:SEGADDR
              tya
              clc
              adc ##2048
              bcc b1FirstLimit
              lda ##65535
b1FirstLimit: sta dp:B1_NEXT
              stz dp:LOADER_TMP
              jsr     abs:b1Lits
              phk                           ; (MVN set the data bank)
              plb
              sep     #0x20
              rts

b1Lits:       jsr     abs:b1Gamma           ; a literal run
              dec     a
b1Lmvn:       .byte   0x54, 0x00, 0x00      ; MVN: input -> output
              cpy     dp:B1_END
              beq     b1Done
              cpy dp:B1_NEXT
              bcc b1LiteralContinue
              jsr abs:b1Progress
b1LiteralContinue:
              asl     dp:B1_BITS            ; after literals: 0 = the last offset
              bne     1$
              jsr     abs:b1Refill
1$:           bcs     b1New
              jsr     abs:b1Gamma
              bra     b1Copy
b1New:        jsr     abs:b1Gamma           ; a new offset: the high part,
              dec     a
              xba
              sep     #0x20
b1Rdb:        lda     long:0x000000,x       ;   the low byte
              rep     #0x20
              inx
              lsr     a
              inc     a
              sta     dp:B1_OFF
              jsr     abs:b1GammaC          ; the length - 1
              inc     a
b1Copy:       dec     a                     ; a match
              sta     dp:B1_CNT
              stx     dp:B1_INP
              tya
              sec
              sbc     dp:B1_OFF
              tax
              lda     dp:B1_CNT
b1Mmvn:       .byte   0x54, 0x00, 0x00      ; MVN: output -> output
              ldx     dp:B1_INP
              cpy     dp:B1_END
              beq     b1Done
              cpy dp:B1_NEXT
              bcc b1MatchContinue
              jsr abs:b1Progress
b1MatchContinue:
              asl     dp:B1_BITS            ; after a match: 0 = literals
              bne     2$
              jsr     abs:b1Refill
2$:           bcc     b1Lits
              bra     b1New
b1Done:       jsr abs:b1Progress
              rts
b1Progress:   pha
              phx
              tya
              sec
              sbc dp:SEGADDR
              bne b1WorkSize
              lda ##128
              bra b1WorkCredit
b1WorkSize:   xba
              and ##255
              lsr a
b1WorkCredit: tax
              sec
              sbc dp:LOADER_TMP
              stx dp:LOADER_TMP
b1Notify:     jsl long:b1NoProgress
              tya
              clc
              adc ##2048
              bcc b1NextLimit
              lda ##65535
b1NextLimit:  sta dp:B1_NEXT
              plx
              pla
              rts
b1NoProgress: rtl

b1Gamma:      lda     ##1
b1G0:         asl     dp:B1_BITS
              bne     b1G1
              jsr     abs:b1Refill
b1G1:         bcs     b1G3
              asl     dp:B1_BITS
              bne     b1G2
              jsr     abs:b1Refill
b1G2:         rol     a
              bra     b1G0
b1G3:         rts
b1GammaC:     lda     ##1
              bra     b1G1

b1Refill:     pha
b1Rdw:        lda     long:0x000000,x
              inx
              inx
              sec
              rol     a
              sta     dp:B1_BITS
              pla
              rts

copyBlock:    lda     dp:DEST+2
              pha
              plb
              rep     #0x30
              ldx     ##0
              ldy     dp:DEST
copyWords:
#include "loader_copy.inc"
              txa
              clc
              adc ##64
              tax
              tya
              clc
              adc ##64
              tay
              cpx ##512
              bcs copyWordsDone
              jmp abs:copyWords
copyWordsDone:phk
              plb
              lda     dp:DEST
              clc
              adc     ##512
              sta     dp:DEST
              sep     #0x20
              lda     dp:DEST+2
              adc     #0
              sta     dp:DEST+2
              rts

;;; picBlock: a block of the title picture: DEST is its place in the
;;; picture record, and it goes to the screen too, except for the pixels of
;;; the load strip.
picBlock:     rep     #0x30
              ldx     dp:BLKNUM
              lda     abs:HDR_ORDER,x       ; the picture block
              and     ##0x003f
              asl     a
              xba                           ; * 512
              sta     dp:PICOFS
              clc
              adc     dp:SEGADDR
              sta     dp:DEST
              sep     #0x20
              lda     dp:SEGADDR+2
              adc     #0
              sta     dp:DEST+2
              rep     #0x20
              lda     dp:PICOFS             ; the part above the strip
              cmp     ##STRIP
              bcs     2$
              ldx     ##BUF
              tay
              clc
              adc     ##512
              cmp     ##STRIP
              bcc     1$
              lda     ##STRIP
1$:           sec
              sbc     dp:PICOFS
              jsr     abs:toScreen
2$:           lda     dp:PICOFS             ; the part after the pixels: the
              clc                           ;   row palettes and the palettes
              adc     ##512
              cmp     ##PIXELS_END + 1
              bcc     4$
              lda     dp:PICOFS
              cmp     ##PIXELS_END
              bcs     3$
              lda     ##PIXELS_END
3$:           tay                           ; the screen offset
              sec
              sbc     dp:PICOFS
              clc
              adc     ##BUF
              tax                           ; the part of BUF
              lda     dp:PICOFS
              clc
              adc     ##512
              sty     dp:LOADER_TMP
              sec
              sbc     dp:LOADER_TMP                ; the length
              jsr     abs:toScreen
4$:           sep     #0x20
              rts

;;; toScreen: C bytes (16 bits) from X in bank 0 to screen offset Y.
;;; In and out: A and X, Y 16 bits.
toScreen:     dec     a
              pha
              tya
              clc
              adc     ##.word0 SCREEN
              tay
              pla
              .byte   0x54, 0xe1, 0x00      ; mvn to bank $E1 from bank 0
              phk
              plb
              rts

;;; ---------------------------------------------------------------------------
;;; The screen.
;;; ---------------------------------------------------------------------------

;;; screenOn: the super hi-res screen on, black: all pixels, row palettes
;;; and colors 0; the strip rows take palette STRIP_PAL, with the strip
;;; colors (a prompt before the title picture: another disk in the drive
;;; at boot).
screenOn:     lda     abs:SHADOW_00
              ora     #0x18                 ; block both bank $01 video aliases
              sta     abs:SHADOW_00            ; before loading any RAM segments
              lda     abs:NEWVIDEO_00
              ora     #0x40                 ; linear memory before the writes
              sta     abs:NEWVIDEO_00
              rep     #0x30
              lda     ##0
              sta     long:SCREEN
              ldx     ##.word0 SCREEN
              ldy     ##.word0 SCREEN + 2
              lda     ##0x8000 - 3          ; $E1:2002-$9FFF, each byte from
              .byte   0x54, 0xe1, 0xe1      ;   2 bytes before it: zeros
              phk
              plb
              ldx     ##16
2$:           lda     abs:stripPal,x
              sta     long:(PALETTES + 32 * STRIP_PAL),x
              dex
              dex
              bpl     2$
              sep     #0x20
              ldx     ##STRIP_ROW
              lda     #STRIP_PAL
1$:           sta     long:SCB,x
              inx
              cpx     ##200
              bcc     1$
              lda     abs:BORDER_00
              and     #0xf0
              sta     abs:BORDER_00
              lda     abs:NEWVIDEO_00
              ora     #0xc0
              sta     abs:NEWVIDEO_00
              rts

;;; drawStrip: the load strip: black, the disk icon, the disk number and
;;; the bar with CELLS full cells.
drawStrip:    ldx     ##STRIP
              lda     #0
1$:           sta     long:SCREEN,x
              inx
              cpx     ##PIXELS_END
              bcc     1$
              ldy     ##ICON_LIT
              jsr     abs:drawIcon
              jsr     abs:drawCount
              jmp     abs:drawBar

;;; loadStep: enter with A8, return A16 = blocks per cell (1..511).
;;; HDR_STEPHI holds the ninth bits: bit 0 for disk mode, bit 1 for RAM mode.
loadStep:     lda     dp:STOREMODE
              bne     1$
              lda     abs:HDR_STEPHI
              lsr     a
              lda     abs:HDR_STEP
              bra     2$
1$:           lda     abs:HDR_STEPHI
              lsr     a
              lsr     a
              lda     abs:HDR_STEP2
2$:           rep     #0x20
              and     ##255
              bcc     3$
              ora     ##256
3$:
              rts

;;; stepBar: after each block; one more full cell after loadStep blocks.
stepBar:      rep     #0x20
              dec     dp:STEPLEFT
              bne     2$
              sep     #0x20
              jsr     abs:loadStep
              sta     dp:STEPLEFT
              sep     #0x20
              lda     #BAR_FULL
              sta     dp:CCOLOR
              lda     dp:CELLS
              cmp     #LOAD_CELLS
              bcs     1$
              inc     dp:CELLS
              jmp     abs:drawCell
1$:           rts
2$:           sep     #0x20
              rts

;;; drawBar: all cells, the first CELLS of them full.
drawBar:      stz     dp:CELL
1$:           lda     dp:CELL
              cmp     dp:CELLS
              lda     #BAR_FULL
              bcc     2$
              lda     #BAR_EMPTY
2$:           sta     dp:CCOLOR
              lda     dp:CELL
              jsr     abs:drawCell
              inc     dp:CELL
              lda     dp:CELL
              cmp     #BAR_CELLS
              bcc     1$
              rts

;;; drawCell: cell A of the bar in CCOLOR. The cell starts at pixel
;;; BAR_X + 7 * cell: a pixel at its left (odd x) or its right (even x)
;;; shares a screen byte with it and stays black.
drawCell:     pha
              rep     #0x20
              and     ##0x00ff
              sta     dp:LOADER_TMP
              asl     a
              asl     a
              asl     a
              sec
              sbc     dp:LOADER_TMP
              clc
              adc     ##BAR_X
              lsr     a
              clc
              adc     ##BAR_ROW
              tax
              sep     #0x20
              lda     dp:CCOLOR
              sta     dp:E1
              sta     dp:E3
              pla
              lsr     a                     ; carry: an odd cell, an odd x
              lda     dp:CCOLOR
              bcs     1$
              and     #0xf0
              sta     dp:E3
              bra     2$
1$:           and     #0x0f
              sta     dp:E1
2$:           lda     #5
              sta     dp:ROW
3$:           lda     dp:E1
              sta     long:SCREEN,x
              lda     dp:CCOLOR
              sta     long:SCREEN+1,x
              lda     dp:E3
              sta     long:SCREEN+2,x
              rep     #0x20
              txa
              clc
              adc     ##160
              tax
              sep     #0x20
              dec     dp:ROW
              bne     3$
              rts

;;; clearText: rows 192-198 from x 44 on black: no bar, no prompt.
clearText:    ldx     ##TEXT_START
              lda     #TEXT_ROWS
              sta     dp:ROW
1$:           ldy     ##160 - 22
              lda     #0
2$:           sta     long:SCREEN,x
              inx
              dey
              bne     2$
              rep     #0x20
              txa
              clc
              adc     ##22
              tax
              sep     #0x20
              dec     dp:ROW
              bne     1$
              rts

;;; drawIcon: the disk icon from Y (ICON_LIT or ICON_DARK).
drawIcon:     ldx     ##ICON_OFS
              lda     #ICON_ROWS
              sta     dp:ROW
1$:           lda     #ICON_BYTES
              sta     dp:LOADER_TMP
2$:           lda     abs:0,y
              sta     long:SCREEN,x
              iny
              inx
              dec     dp:LOADER_TMP
              bne     2$
              rep     #0x20
              txa
              clc
              adc     ##160 - ICON_BYTES
              tax
              sep     #0x20
              dec     dp:ROW
              bne     1$
              rts

;;; drawCount: DISKNUM/NDISKS in the plain font colors.
drawCount:    stz     dp:DROP
              jsr     abs:setDrop
              ldx     ##COUNT_OFS
              stx     dp:XOFS
              lda     dp:DISKNUM
              jsr     abs:drawGlyph
              lda     #GLYPH_SLASH
              jsr     abs:drawGlyph
              lda     dp:NDISKS
              jmp     abs:drawGlyph

;;; setDrop: TAB16 for DROP: the screen byte of each 2 glyph pixels (the
;;; left one in the high bits), each red DROP steps darker on the ramp of
;;; palette 15 (black stays black).
setDrop:      sep     #0x10
              ldx     #15
1$:           txa
              lsr     a
              lsr     a
              tay
              lda     abs:LEVEL,y
              sec
              sbc     dp:DROP
              bcs     2$
              lda     #0
2$:           asl     a
              asl     a
              asl     a
              asl     a
              sta     dp:LOADER_TMP
              txa
              and     #3
              tay
              lda     abs:LEVEL,y
              sec
              sbc     dp:DROP
              bcs     3$
              lda     #0
3$:           ora     dp:LOADER_TMP
              sta     abs:TAB16,x
              dex
              bpl     1$
              rep     #0x10
              rts

;;; drawText: the glyphs at Y until $FF.
drawText:     sty     dp:STRPTR
1$:           lda     (STRPTR)
              cmp     #0xff
              beq     2$
              jsr     abs:drawGlyph
              rep     #0x20
              inc     dp:STRPTR
              sep     #0x20
              bra     1$
2$:           rts

;;; drawGlyph: glyph A at the screen offset XOFS through TAB16; XOFS moves
;;; past it.
drawGlyph:    rep     #0x30
              and     ##0x00ff
              asl     a
              tax
              lda     abs:GLYPHS,x
              sta     dp:GLYPH
              lda     dp:XOFS
              clc
              adc     ##.word0 SCREEN
              sta     dp:PTR
              sep     #0x30                 ; A, X and Y 8 bits
              lda     #.byte2 SCREEN
              sta     dp:PTR+2
              lda     (GLYPH)               ; the width
              sta     dp:GW
              jsr     abs:nextByte
              lda     #GLYPH_ROWS
              sta     dp:ROW
1$:           ldy     #0
2$:           lda     (GLYPH)               ; 4 pixels
              jsr     abs:nextByte
              pha
              lsr     a
              lsr     a
              lsr     a
              lsr     a
              tax
              lda     abs:TAB16,x
              sta     [PTR],y
              iny
              pla
              cpy     dp:GW
              bcs     3$                    ; an odd width ends here
              and     #0x0f
              tax
              lda     abs:TAB16,x
              sta     [PTR],y
              iny
              cpy     dp:GW
              bcc     2$
3$:           rep     #0x20
              lda     dp:PTR
              clc
              adc     ##160
              sta     dp:PTR
              sep     #0x20
              dec     dp:ROW
              bne     1$
              rep     #0x30
              lda     dp:GW
              and     ##0x00ff
              clc
              adc     dp:XOFS
              sta     dp:XOFS
              sep     #0x20
              rts
nextByte:     inc     dp:GLYPH
              bne     1$
              inc     dp:GLYPH+1
1$:           rts

;;; ---------------------------------------------------------------------------
;;; The next disk.
;;; ---------------------------------------------------------------------------

;;; Find DISKNUM in either drive of the slot and leave its header in HDR.
;;; A match selects that drive for later reads. Mismatched disks in the current
;;; drive are ejected. Boot mode maintains the SHR and text-page prompts;
;;; runtimeUI suppresses that drawing so the game owns the display.
waitDisk:     jsr     abs:otherDrive
              bcs     0$
              rts
0$:           lda     abs:runtimeUI
              beq     bootDiskPrompt
runtimeDiskWait: jsr abs:frame
              jsr     abs:diskIn
              bcc     runtimeOther
              jsr     abs:readHeader2
              bcc     runtimeDiskReady
              jsr     abs:ejectDisk
runtimeOther: jsr     abs:otherDrive
              bcs     runtimeDiskWait
runtimeDiskReady: rts
bootDiskPrompt: lda dp:DISKNUM
              ora     #0xb0
              sta     abs:msgInsertNum
              sep     #0x10
              ldx     #.byte0 msgInsert
              ldy     #.byte1 msgInsert
              jsr     abs:printAt
              rep     #0x10
              jsr     abs:clearText
              jsr     abs:drawCount
              stz     dp:FRAMES
              ldx     ##0
              stx     dp:PULSE
              jsr     abs:pulseStep
1$:           jsr     abs:frame
              inc     dp:FRAMES
              lda     dp:FRAMES
              and     #7
              bne     3$
              ldx     dp:PULSE              ; the next step of the pulse
              inx
              cpx     ##6
              bcc     2$
              ldx     ##0
2$:           stx     dp:PULSE
              jsr     abs:pulseStep
3$:           lda     dp:FRAMES
              and     #15
              bne     1$
              jsr     abs:diskIn
              bcc     5$
              jsr     abs:readHeader2
              bcc     4$
              jsr     abs:ejectDisk         ; the wrong disk
5$:           jsr     abs:otherDrive
              bcs     1$
4$:           sep     #0x10
              ldx     #.byte0 msgBlank
              ldy     #.byte1 msgBlank
              jsr     abs:printAt
              rep     #0x10
              jsr     abs:clearText
              ldy     ##ICON_LIT
              jsr     abs:drawIcon
              jmp     abs:drawBar

;;; otherDrive: carry clear when the other drive of the slot (ProDOS drive
;;; bit, SmartPort unit 3 - unit) holds disk DISKNUM: its header in HDR, its
;;; units the loader's from now on. Else the units stay, carry set.
otherDrive:   jsr     abs:swapDrive
              jsr     abs:diskIn
              bcc     8$
              jsr     abs:readHeader2
              bcs     8$
              rts
8$:           jsr     abs:swapDrive
              sec
              rts
swapDrive:    lda     dp:PD_UNIT
              eor     #0x80
              sta     dp:PD_UNIT
              lda     #3
              sec
              sbc     abs:spUnit
              sta     abs:spUnit
              rts

;;; pulseStep: DROP for the step PULSE, then the prompt and the icon (lit
;;; while the text is bright).
pulseStep:    ldx     dp:PULSE
              lda     abs:PULSE_DROP,x
              sta     dp:DROP
              jsr     abs:setDrop
              ldx     ##PROMPT_OFS
              stx     dp:XOFS
              ldy     ##PROMPT
              jsr     abs:drawText
              lda     dp:DISKNUM
              jsr     abs:drawGlyph
              ldy     ##ICON_LIT
              lda     dp:DROP
              cmp     #2
              bcc     1$
              ldy     ##ICON_DARK
1$:           jmp     abs:drawIcon

;;; frame: the next vertical blank (bit 7 of RDVBLBAR_00 changes one way,
;;; then back).
frame:        lda     abs:RDVBLBAR_00
              bmi     frame
1$:           lda     abs:RDVBLBAR_00
              bpl     1$
              rts

;;; ---------------------------------------------------------------------------
;;; The text screen: 40 columns, page 1. These routines need X and Y of 8
;;; bits.
;;; ---------------------------------------------------------------------------

clearScreen:  ldx     #23
1$:           lda     abs:rowLo,x
              sta     dp:LOADER_TMP
              lda     abs:rowHi,x
              sta     dp:LOADER_TMP+1
              ldy     #39
              lda     #0xa0
2$:           sta     (LOADER_TMP),y
              dey
              bpl     2$
              dex
              bpl     1$
              rts

;;; printAt: the text at X (low) and Y (high): row, column, characters, 0.
printAt:      stx     dp:MSGPTR
              sty     dp:MSGPTR+1
              ldy     #0
              lda     (MSGPTR),y
              tax
              lda     abs:rowLo,x
              sta     dp:LOADER_TMP
              lda     abs:rowHi,x
              sta     dp:LOADER_TMP+1
              iny
              lda     (MSGPTR),y
              clc
              adc     dp:LOADER_TMP
              sta     dp:LOADER_TMP
              clc
              lda     dp:MSGPTR
              adc     #2
              sta     dp:MSGPTR
              bcc     1$
              inc     dp:MSGPTR+1
1$:           ldy     #0
2$:           lda     (MSGPTR),y
              beq     3$
              ora     #0x80
              sta     (LOADER_TMP),y
              iny
              bra     2$
3$:           rts

;;; ---------------------------------------------------------------------------
;;; Data.
;;; ---------------------------------------------------------------------------

rowLo:        .byte   0x00,0x80,0x00,0x80,0x00,0x80,0x00,0x80
              .byte   0x28,0xa8,0x28,0xa8,0x28,0xa8,0x28,0xa8
              .byte   0x50,0xd0,0x50,0xd0,0x50,0xd0,0x50,0xd0
rowHi:        .byte   0x04,0x04,0x05,0x05,0x06,0x06,0x07,0x07
              .byte   0x04,0x04,0x05,0x05,0x06,0x06,0x07,0x07
              .byte   0x04,0x04,0x05,0x05,0x06,0x06,0x07,0x07

magic:        .ascii  "WOLFGS"
bitOf:        .byte   1, 2, 4, 8, 16, 32, 64, 128
settingsBlock: .word  0                     ; WOLF.SETTINGS on the home disk

LEVEL:        .byte   0, 1, 3, 4            ; the color of each glyph value
stripPal:     .word   0x0000, 0x0333, 0x0555, 0x0777, 0x0bbb ; STRIP_COLORS of
              .word   0x0fff, 0x0666, 0x0999, 0x0ddd ;   tools/gscolor.py
buildId:      .space  4                     ; the build ID of disk 1
PULSE_DROP:   .byte   3, 2, 1, 0, 1, 2      ; the steps of the pulse
TAB16:        .space  16

drvAddr:      .word   0                     ; the ProDOS block driver
spAddr:       .word   0                     ; the SmartPort entry
spParams:     .byte   3                     ; the SmartPort parameters:
spUnit:       .byte   1                     ;   unit,
              .word   spList                ;   status or control list,
spCode:       .byte   0                     ;   status or control code
spList:       .byte   0, 0, 0, 0

msgTitle:     .byte   3, 8
              .asciz  "WOLF FOR THE APPLE IIGS"
msgSorry:     .byte   7, 4
              .asciz  "SORRY! THIS APPLE IIGS CANNOT"
msgSorry2:    .byte   8, 4
              .asciz  "RUN WOLF."
msgNeeds:     .byte   10, 4
              .asciz  "WOLF NEEDS 4 MB OF MEMORY."
msgHas:       .byte   11, 4
              .ascii  "THIS APPLE IIGS HAS "
msgHasNum:    .ascii  "0"                   ; then " MB." or, from msgHasNum,
              .space  16                    ;   "LESS THAN 1 MB."
msgMB:        .asciz  " MB."
msgLess:      .asciz  "LESS THAN 1 MB."
msgAdd:       .byte   14, 4
              .asciz  "ADD A MEMORY CARD, OR SET THE"
msgAdd2:      .byte   15, 4
              .asciz  "EMULATOR TO 4 MB OF MEMORY."
msgInsert:    .byte   18, 4
              .ascii  "INSERT DISK "
msgInsertNum: .ascii  "1"
              .byte   0
msgBlank:     .byte   18, 4
              .asciz  "             "
msgReadError: .byte   18, 4
              .asciz  "DISK READ ERROR"

#include "bootbar_font.inc"

runtimeUI:    .byte 0
