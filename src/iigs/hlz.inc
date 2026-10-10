;;; HLZ store decoder: LZ77 with canonical Huffman codes. tools/hlz.py holds the
;;; format, the encoder and the reference decoder; tools/check_hlz.py runs this
;;; code in emu816 against it. The two unrolled blocks between ">>>" and "<<<"
;;; lines come from tools/gen_hlz_copies.py (--update rewrites them, --check
;;; compares them).
;;;
;;; Two resident sections (wolf.scm):
;;;   hlzcode  SEG_HLZ: resident dispatch, loop setup and decode loop,
;;;            outside the art and menu cache windows.
;;;   hlzsetup SEG_HLZ_SETUP: per-unit header reader and table builder,
;;;            called with JSL hlzSetup; placement comes from SEG_HLZ_SETUP.
;;; CodecDispatch accepts a JSL from levelio.s. Marker 3 selects HLZ;
;;; other units enter DecodeFloorUnit (load_fast.inc), adapting the return
;;; stack to that decoder's JSR/RTS convention.
;;;
;;; RAM while a unit decodes:
;;;   - its two 1 KB lookup tables follow the buffered packed input in the
;;;     stage bank. StreamTables keeps them after any prefetched neighbours.
;;;     The store builder bounds each unit plus HLZ_TABLES; the floppy reader
;;;     applies the same bound to a coalesced run and rejects output overlap.
;;;   - the 598 code lengths go to the start of the unit's own output first
;;;     (the builder takes HLZ only for outputs of HLZ_MIN_BYTES or more).
;;;   - direct page: D = 0, the HLZ_* cells of LOADER_DP.
;;;
;;; Decode loop: 16-bit A/X/Y, Y = the output offset, DBR = the output bank.
;;; The bit stream is stored backward and read top bit first: [HLZ_BP] is a word
;;; whose high byte is the current byte and whose low byte is the next one.
;;; Which of eight copies of the loop runs is the bit offset (0-7) in the current
;;; byte. A table entry gives the symbol and its code length; JMP (table,X) goes
;;; to the copy for the next bit offset, through the 0-2 DEC HLZ_BP in front of
;;; it. The codes of one length fill one run of a table (no bit reversal).
;;; A literal is stored as a 16-bit word: its second byte is junk that the next
;;; output byte replaces. The junk can land on the two bytes after the output
;;; (saved first, put back at the end) and, for an output that ends at a bank
;;; end, on output bytes 0 and 1 (the payload header has them; written again).
;;; The symbols, from tools/hlz.py:
;;;   literal/length: 0-255 literal, 256 end, 257-288 length 3-34, 289 length
;;;   35 + byte, 290 length = word, 291-323 repeat length 2-34, 324 repeat
;;;   35 + byte, 325 repeat length = word; offset: 0-15 offset 1-16, 16-271
;;;   offset (symbol - 16) * 256 + byte. Bytes and words come from the byte
;;;   stream ([HLZ_RP]); a match's offset byte comes before its length bytes.
;;; Literal/length entry: low byte = the literal, or the length - 1, or $FE/$FF
;;; for a byte/word length; high byte = 2n (literal), 2n+32 (new match), 2n+64
;;; (end), 2n+96 (repeat match); n = the code length (1-9).
;;; Offset entry: low byte = 2n, +$40 when a byte follows; high byte = the
;;; offset (1-16) or (symbol - 16).
;;; levelio.s includes this file at its end (WOLF_REGISTERED); it uses that
;;; file's memmap.inc, loader_api.inc and externs (loadMixed, stageBank,
;;; stageStart, DecodeFloorUnit).

HLZ_MARKER    .equ 3
HLZ_TABLE     .equ 1024             ; bytes in one lookup table (512 entries)
HLZ_LITERALS  .equ 326              ; literal/length symbols
HLZ_LENGTHS   .equ 598              ; all code lengths in the header

;;; One fragment each: no noreorder, which would chain them to levelio.
              .section hlzcode, text, root
              .public CodecDispatch
              .extern StreamTables

;;; JSL from levelio.s nextUnit: 16-bit A/X/Y, DBR = 0, D = 0.
;;; Returns 8-bit A, 16-bit X/Y, DBR = 0 (the contract of DecodeFloorUnit).
;;; Fast codecs (bit 14 of the record) come from an EP06+ floor or aux list
;;; (ReadFloorFormat sets loadMixed) or from a WOLFMS03 music list, which has
;;; the same record flags. The music path does not set loadMixed itself;
;;; set it here for WOLFMS03 so DecodeFloorUnit interprets the fast-codec
;;; flags instead of treating LZSA1/LZ16 song units as B1.
CodecDispatch:
              lda long:loadMixed
              bne hlzFlags
              lda long:loadMusic
              beq hlzOther
              lda abs:EPDIR+6             ; the music list's format word
              cmp ##0x3330                ; WOLFMS03
              bne hlzOther
              lda ##1
              sta long:loadMixed
hlzFlags:     ldx dp:LV_RECORD
              lda abs:2,x                 ; DBR = 0: the unit's directory record
              bit ##0x4000
              beq hlzOther
              lda long:stageStart
              sta dp:HLZ_PTR
              lda long:stageBank
              sta dp:HLZ_PTR+2
              ldy ##2
              lda [HLZ_PTR],y
              and ##0x00ff
              cmp ##HLZ_MARKER
              beq hlzUnit
;;; Not HLZ: make the JSL return a JSR return and go on in bank 0.
hlzOther:     pla                         ; the return address
              sep #0x20
              plb                         ; its bank (0) into DBR
              rep #0x20
              pha
              jmp long:DecodeFloorUnit

;;; ------------------------------------------------------------------ setup
hlzUnit:      jsl long:StreamTables      ; tables follow the buffered read run
              sta dp:HLZ_TAB
              lda dp:HLZ_PTR+2
              sta dp:HLZ_TAB+2
              phk                         ; DBR = this bank until the loop
              plb
              lda dp:BOOT_SEGADDR         ; the output: length scratch, bytes 0-1
              sta dp:HLZ_DST
              lda dp:BOOT_SEGADDR+2
              sta dp:HLZ_DST+2
              lda [HLZ_PTR]               ; the output end, 24 bits
              clc
              adc dp:BOOT_SEGADDR
              sta dp:HLZ_END
              lda dp:BOOT_SEGADDR+2
              and ##0x00ff
              adc ##0
              tax
              lda [HLZ_PTR]
              bne hlzEndBank
              inx                         ; length 0: 65536 bytes
hlzEndBank:   stx dp:HLZ_END+2
              lda [HLZ_END]               ; the two bytes after the output
              sta abs:.word0 (hlzSave)
              lda dp:BOOT_SEGADDR         ; progress, as lzsaStart does
              clc
              adc ##2048
              bcc hlzFirstLimit
              lda ##0xffff
hlzFirstLimit:sta dp:B1_NEXT
              stz dp:LOADER_TMP
              lda long:BOOT_b1Notify+1    ; the loader's progress call
              sta abs:.word0 (hlzNotify+1)
              lda long:BOOT_b1Notify+2
              sta abs:.word0 (hlzNotify+2)
              sep #0x20
              lda dp:BOOT_SEGADDR+2       ; matches copy inside the output bank
              sta abs:.word0 (hlzMvn+1)
              sta abs:.word0 (hlzMvn+2)
              sta abs:.word0 (hlzRepMvn+1)
              sta abs:.word0 (hlzRepMvn+2)
              rep #0x20
              ldx ##0                     ; the table bases into the 16 lookups
hlzPatch:     ldy abs:.word0 (hlzSites),x
              lda dp:HLZ_TAB
              cpx ##16
              bcc hlzPatchLow
              clc
              adc ##HLZ_TABLE             ; the offset table
hlzPatchLow:  sta abs:1,y
              sep #0x20
              lda dp:HLZ_TAB+2
              sta abs:3,y
              rep #0x20
              inx
              inx
              cpx ##32
              bcc hlzPatch
              ldy ##5                     ; the byte stream
              lda [HLZ_PTR],y
              clc
              adc dp:HLZ_PTR
              sta dp:HLZ_RP
              dec a                       ; the bit stream ends there and is read
              dec a                       ; backward: HLZ_BP = its last byte - 1
              sta dp:HLZ_BP
              lda dp:HLZ_PTR+2
              sta dp:HLZ_RP+2
              sta dp:HLZ_BP+2
              jsl long:hlzSetup           ; the tables; A = 2 * the bit offset
              tax
              lda ##1
              sta dp:HLZ_PREV
              sep #0x20
              lda dp:BOOT_SEGADDR+2       ; DBR = the output bank
              pha
              plb
              rep #0x20
              ldy dp:BOOT_SEGADDR
              jmp (abs:.word0 (hlzAdvL),x)

;;; The end code. Y = the output end + 1 (the code's junk store moved it).
hlzEnd:       dey
              jsr abs:.word0 (hlzProgress)
              ldy ##3
              lda [HLZ_PTR],y             ; output bytes 0 and 1
              sta [HLZ_DST]
              lda long:hlzSave
              sta [HLZ_END]
              sep #0x20
              lda #0
              pha
              plb
              rtl

;;; ---------------------------------------------------------------- matches
;;; Repeat match (from an R stub, which then goes on with its literal copy): the
;;; previous offset. The match starts at Y-1, where its length code is.
hlzRep:       dey
              tya
              sec
              sbc dp:HLZ_PREV
              tax                         ; the source, in the output bank
              lda abs:0,y                 ; the length code: the length - 1,
              and ##0x00ff                ; $FE (35 + a byte) or $FF (a word)
              cmp ##0x00fe
              bcs hlzRepLong
hlzRepMvn:    .byte 0x54, 0x00, 0x00      ; MVN (both banks patched)
              cpy dp:B1_NEXT
              bcs hlzRepStep
              rts
hlzRepStep:   jmp abs:.word0 (hlzProgress)
hlzRepLong:   jsr abs:.word0 (hlzLength)
              bra hlzRepMvn
;;; New match: A = the offset entry. Returns X = 2n of the offset code.
hlzNew:       sta dp:HLZ_OFF
              bit ##0x0040
              bne hlzFar
              xba
              and ##0x00ff                ; offset 1-16
              bra hlzSetPrev
hlzFar:       and ##0xff00                ; offset = high * 256 + a byte
              sta dp:HLZ_T
              lda [HLZ_RP]
              inc dp:HLZ_RP
              and ##0x00ff
              ora dp:HLZ_T
hlzSetPrev:   sta dp:HLZ_PREV
              dey
              tya
              sec
              sbc dp:HLZ_PREV
              tax
              lda abs:0,y
              and ##0x00ff
              cmp ##0x00fe
              bcs hlzNewLong
hlzMvn:       .byte 0x54, 0x00, 0x00      ; MVN (both banks patched)
              cpy dp:B1_NEXT
              bcs hlzNewStep
hlzDone:      lda dp:HLZ_OFF
              and ##0x003e
              tax
              rts
hlzNewStep:   jsr abs:.word0 (hlzProgress)
              bra hlzDone
hlzNewLong:   jsr abs:.word0 (hlzLength)
              bra hlzMvn
;;; A = $FE or $FF, a length code: A = the MVN count from the byte stream.
hlzLength:    cmp ##0x00ff
              beq hlzWord
              lda [HLZ_RP]                ; length 35 + a byte
              inc dp:HLZ_RP
              and ##0x00ff
              clc
              adc ##34
              rts
hlzWord:      lda [HLZ_RP]                ; length = a word
              inc dp:HLZ_RP
              inc dp:HLZ_RP
              dec a
              rts

;;; The loader's b1Progress (loader.s) for code in this bank: credit the 512-byte
;;; steps decoded so far, set the next limit. Y = the output position.
hlzProgress:  pha
              phx
              tya
              sec
              sbc dp:BOOT_SEGADDR
              bne hlzWorkSize
              lda ##128
              bra hlzWorkCredit
hlzWorkSize:  xba
              and ##0x00ff
              lsr a
hlzWorkCredit:tax
              sec
              sbc dp:LOADER_TMP
              stx dp:LOADER_TMP
hlzNotify:    jsl long:0x000000           ; patched: the loader's notify call
              tya
              clc
              adc ##2048
              bcc hlzNextLimit
              lda ##0xffff
hlzNextLimit: sta dp:B1_NEXT
              plx
              pla
              rts
hlzSave:      .word 0                     ; the two bytes after the output

;;; >>> loop: generated by tools/gen_hlz_copies.py, do not edit by hand
;;; ---------------------------------------------------------- decode loop
;;; Copy k reads the next 9 bits from bit k of the current byte. Entry hlzLk:
;;; no DEC, hlzLka: one DEC, hlzLkb: two DEC of HLZ_BP first.
hlzL0b:       dec dp:HLZ_BP
hlzL0a:       dec dp:HLZ_BP
hlzL0:        lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzLT0:       lda long:0x000000,x       ; the literal/length table
              sta abs:0,y                ; a literal (after a code: junk)
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hlzAdvL+0),x)
hlzL1b:       dec dp:HLZ_BP
hlzL1a:       dec dp:HLZ_BP
hlzL1:        lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzLT1:       lda long:0x000000,x       ; the literal/length table
              sta abs:0,y                ; a literal (after a code: junk)
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hlzAdvL+2),x)
hlzL2b:       dec dp:HLZ_BP
hlzL2a:       dec dp:HLZ_BP
hlzL2:        lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzLT2:       lda long:0x000000,x       ; the literal/length table
              sta abs:0,y                ; a literal (after a code: junk)
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hlzAdvL+4),x)
hlzL3b:       dec dp:HLZ_BP
hlzL3a:       dec dp:HLZ_BP
hlzL3:        lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzLT3:       lda long:0x000000,x       ; the literal/length table
              sta abs:0,y                ; a literal (after a code: junk)
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hlzAdvL+6),x)
hlzL4b:       dec dp:HLZ_BP
hlzL4a:       dec dp:HLZ_BP
hlzL4:        lda [HLZ_BP]
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzLT4:       lda long:0x000000,x       ; the literal/length table
              sta abs:0,y                ; a literal (after a code: junk)
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hlzAdvL+8),x)
hlzL5b:       dec dp:HLZ_BP
hlzL5a:       dec dp:HLZ_BP
hlzL5:        lda [HLZ_BP]
              lsr a
              and ##0x03fe
              tax
hlzLT5:       lda long:0x000000,x       ; the literal/length table
              sta abs:0,y                ; a literal (after a code: junk)
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hlzAdvL+10),x)
hlzL6b:       dec dp:HLZ_BP
hlzL6a:       dec dp:HLZ_BP
hlzL6:        lda [HLZ_BP]
              and ##0x03fe
              tax
hlzLT6:       lda long:0x000000,x       ; the literal/length table
              sta abs:0,y                ; a literal (after a code: junk)
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hlzAdvL+12),x)
hlzL7b:       dec dp:HLZ_BP
hlzL7a:       dec dp:HLZ_BP
hlzL7:        lda [HLZ_BP]
              asl a
              and ##0x03fe
              tax
hlzLT7:       lda long:0x000000,x       ; the literal/length table
              sta abs:0,y                ; a literal (after a code: junk)
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hlzAdvL+14),x)
;;; A new match (its length code is the junk byte at Y-1): copy k reads the
;;; offset code from bit k.
hlzM0b:       dec dp:HLZ_BP
hlzM0a:       dec dp:HLZ_BP
hlzM0:        lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzDT0:       lda long:0x000000,x       ; the offset table
              jsr abs:.word0 (hlzNew)
              jmp (abs:.word0 (hlzAdvL+0),x)
hlzM1b:       dec dp:HLZ_BP
hlzM1a:       dec dp:HLZ_BP
hlzM1:        lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzDT1:       lda long:0x000000,x       ; the offset table
              jsr abs:.word0 (hlzNew)
              jmp (abs:.word0 (hlzAdvL+2),x)
hlzM2b:       dec dp:HLZ_BP
hlzM2a:       dec dp:HLZ_BP
hlzM2:        lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzDT2:       lda long:0x000000,x       ; the offset table
              jsr abs:.word0 (hlzNew)
              jmp (abs:.word0 (hlzAdvL+4),x)
hlzM3b:       dec dp:HLZ_BP
hlzM3a:       dec dp:HLZ_BP
hlzM3:        lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzDT3:       lda long:0x000000,x       ; the offset table
              jsr abs:.word0 (hlzNew)
              jmp (abs:.word0 (hlzAdvL+6),x)
hlzM4b:       dec dp:HLZ_BP
hlzM4a:       dec dp:HLZ_BP
hlzM4:        lda [HLZ_BP]
              lsr a
              lsr a
              and ##0x03fe
              tax
hlzDT4:       lda long:0x000000,x       ; the offset table
              jsr abs:.word0 (hlzNew)
              jmp (abs:.word0 (hlzAdvL+8),x)
hlzM5b:       dec dp:HLZ_BP
hlzM5a:       dec dp:HLZ_BP
hlzM5:        lda [HLZ_BP]
              lsr a
              and ##0x03fe
              tax
hlzDT5:       lda long:0x000000,x       ; the offset table
              jsr abs:.word0 (hlzNew)
              jmp (abs:.word0 (hlzAdvL+10),x)
hlzM6b:       dec dp:HLZ_BP
hlzM6a:       dec dp:HLZ_BP
hlzM6:        lda [HLZ_BP]
              and ##0x03fe
              tax
hlzDT6:       lda long:0x000000,x       ; the offset table
              jsr abs:.word0 (hlzNew)
              jmp (abs:.word0 (hlzAdvL+12),x)
hlzM7b:       dec dp:HLZ_BP
hlzM7a:       dec dp:HLZ_BP
hlzM7:        lda [HLZ_BP]
              asl a
              and ##0x03fe
              tax
hlzDT7:       lda long:0x000000,x       ; the offset table
              jsr abs:.word0 (hlzNew)
              jmp (abs:.word0 (hlzAdvL+14),x)
;;; A repeat match (the previous offset), then the literal copy k.
hlzR0b:       dec dp:HLZ_BP
hlzR0a:       dec dp:HLZ_BP
hlzR0:        jsr abs:.word0 (hlzRep)
              jmp abs:.word0 (hlzL0)
hlzR1b:       dec dp:HLZ_BP
hlzR1a:       dec dp:HLZ_BP
hlzR1:        jsr abs:.word0 (hlzRep)
              jmp abs:.word0 (hlzL1)
hlzR2b:       dec dp:HLZ_BP
hlzR2a:       dec dp:HLZ_BP
hlzR2:        jsr abs:.word0 (hlzRep)
              jmp abs:.word0 (hlzL2)
hlzR3b:       dec dp:HLZ_BP
hlzR3a:       dec dp:HLZ_BP
hlzR3:        jsr abs:.word0 (hlzRep)
              jmp abs:.word0 (hlzL3)
hlzR4b:       dec dp:HLZ_BP
hlzR4a:       dec dp:HLZ_BP
hlzR4:        jsr abs:.word0 (hlzRep)
              jmp abs:.word0 (hlzL4)
hlzR5b:       dec dp:HLZ_BP
hlzR5a:       dec dp:HLZ_BP
hlzR5:        jsr abs:.word0 (hlzRep)
              jmp abs:.word0 (hlzL5)
hlzR6b:       dec dp:HLZ_BP
hlzR6a:       dec dp:HLZ_BP
hlzR6:        jsr abs:.word0 (hlzRep)
              jmp abs:.word0 (hlzL6)
hlzR7b:       dec dp:HLZ_BP
hlzR7a:       dec dp:HLZ_BP
hlzR7:        jsr abs:.word0 (hlzRep)
              jmp abs:.word0 (hlzL7)
;;; Word k + n: the copy for bit offset k + n (with its DECs) after a code of
;;; n bits; +16 a new match, +32 the end, +48 a repeat match.
hlzAdvL:      .word .word0 (hlzL0), .word0 (hlzL1), .word0 (hlzL2), .word0 (hlzL3)
              .word .word0 (hlzL4), .word0 (hlzL5), .word0 (hlzL6), .word0 (hlzL7)
              .word .word0 (hlzL0a), .word0 (hlzL1a), .word0 (hlzL2a), .word0 (hlzL3a)
              .word .word0 (hlzL4a), .word0 (hlzL5a), .word0 (hlzL6a), .word0 (hlzL7a)
              .word .word0 (hlzL0b), .word0 (hlzM1), .word0 (hlzM2), .word0 (hlzM3)
              .word .word0 (hlzM4), .word0 (hlzM5), .word0 (hlzM6), .word0 (hlzM7)
              .word .word0 (hlzM0a), .word0 (hlzM1a), .word0 (hlzM2a), .word0 (hlzM3a)
              .word .word0 (hlzM4a), .word0 (hlzM5a), .word0 (hlzM6a), .word0 (hlzM7a)
              .word .word0 (hlzM0b), .word0 (hlzEnd), .word0 (hlzEnd), .word0 (hlzEnd)
              .word .word0 (hlzEnd), .word0 (hlzEnd), .word0 (hlzEnd), .word0 (hlzEnd)
              .word .word0 (hlzEnd), .word0 (hlzEnd), .word0 (hlzEnd), .word0 (hlzEnd)
              .word .word0 (hlzEnd), .word0 (hlzEnd), .word0 (hlzEnd), .word0 (hlzEnd)
              .word .word0 (hlzEnd), .word0 (hlzR1), .word0 (hlzR2), .word0 (hlzR3)
              .word .word0 (hlzR4), .word0 (hlzR5), .word0 (hlzR6), .word0 (hlzR7)
              .word .word0 (hlzR0a), .word0 (hlzR1a), .word0 (hlzR2a), .word0 (hlzR3a)
              .word .word0 (hlzR4a), .word0 (hlzR5a), .word0 (hlzR6a), .word0 (hlzR7a)
              .word .word0 (hlzR0b)
;;; The 24-bit table operands that the setup patches (8 literal, 8 offset).
hlzSites:     .word .word0 (hlzLT0), .word0 (hlzLT1), .word0 (hlzLT2), .word0 (hlzLT3)
              .word .word0 (hlzLT4), .word0 (hlzLT5), .word0 (hlzLT6), .word0 (hlzLT7)
              .word .word0 (hlzDT0), .word0 (hlzDT1), .word0 (hlzDT2), .word0 (hlzDT3)
              .word .word0 (hlzDT4), .word0 (hlzDT5), .word0 (hlzDT6), .word0 (hlzDT7)
;;; <<< loop: end of the generated block

;;; ------------------------------------------------------------ setup section
              .section hlzsetup, text, root
;;; JSL from hlzUnit. In: HLZ_BP = the bit stream (word: next byte, current
;;; byte), HLZ_DST = room for the code lengths (the unit's own output), HLZ_TAB =
;;; the literal/length table (the offset table follows it). Out: A = 2 * the bit
;;; offset of the first code, HLZ_BP for its byte. DBR is kept.
hlzSetup:     phb
              phk
              plb
              stz dp:HLZ_K
              ldx ##4                     ; the code-length lengths sent - 4
              jsr abs:.word0 (hGet)
              asl a
              clc
              adc ##8
              sta dp:HLZ_LAST             ; 2 * the lengths sent (hGet uses HLZ_N)
              ldx ##24
hClClear:     stz abs:.word0 (hClLen),x
              dex
              dex
              bpl hClClear
              ldy ##0
hClRead:      cpy dp:HLZ_LAST
              bcs hClBuild
              ldx ##3
              jsr abs:.word0 (hGet)
              ldx abs:.word0 (hClOrder),y
              sta abs:.word0 (hClLen),x
              iny
              iny
              bra hClRead
;;; The code-length code as a 128-entry table: symbol | dispatch << 8, the
;;; dispatch 2n for a length (0-9), 2n+32 for a run (10-12).
hClBuild:     ldx ##14
hClZero:      stz abs:.word0 (hCnt),x
              dex
              dex
              bpl hClZero
              ldy ##24
hClCount:     lda abs:.word0 (hClLen),y
              asl a
              tax
              inc abs:.word0 (hCnt),x
              dey
              dey
              bpl hClCount
              stz dp:HLZ_V                ; the table offset of each length's first code:
              ldx ##2                     ; after cnt(m) * 2^(8-m) bytes of every m < n
hClStart:     lda dp:HLZ_V
              sta dp:HLZ_NEXT,x
              lda abs:.word0 (hCnt),x
              ldy abs:.word0 (hClShift-2),x
hClShiftCnt:  asl a
              dey
              bne hClShiftCnt
              clc
              adc dp:HLZ_V
              sta dp:HLZ_V
              inx
              inx
              cpx ##16
              bcc hClStart
              ldy ##0                     ; Y = 2 * the symbol
hClPlace:     lda abs:.word0 (hClLen),y
              beq hClNext
              asl a
              tax                         ; 2n
              cpy ##20
              bcc hClLength
              ora ##32                    ; a run symbol
hClLength:    xba
              sta dp:HLZ_E
              tya
              lsr a
              ora dp:HLZ_E
              sta dp:HLZ_E
              lda dp:HLZ_NEXT,x
              sta dp:HLZ_V
              clc
              adc abs:.word0 (hClStep-2),x
              sta dp:HLZ_NEXT,x
              lda abs:.word0 (hClStep-2),x
              lsr a
              tax                         ; the entries of this code
              phy
              ldy dp:HLZ_V
              lda dp:HLZ_E
hClFill:      sta abs:.word0 (hClTab),y
              iny
              iny
              dex
              bne hClFill
              ply
hClNext:      iny
              iny
              cpy ##26
              bcc hClPlace
;;; The code lengths into [HLZ_DST] with the header copies hH0-hH7.
              ldy ##0
              lda dp:HLZ_K
              asl a
              tax
              jmp (abs:.word0 (hAdvH),x)
;;; A run symbol: A = the bit offset of its extra bits. Writes the run, then goes
;;; on with the header copy for the new bit offset.
hRun:         sta dp:HLZ_K
              dey
              lda [HLZ_DST],y             ; the run symbol (stored like a length)
              and ##0x00ff
              cmp ##11
              bcc hRunRepeat
              beq hRunZeros
              ldx ##7                     ; 12: 11-138 zeros
              jsr abs:.word0 (hGet)
              clc
              adc ##8
              bra hRunZeroCount
hRunZeros:    ldx ##3                     ; 11: 3-10 zeros
              jsr abs:.word0 (hGet)
hRunZeroCount:clc
              adc ##3
              tax
              lda ##0
              bra hRunPut
hRunRepeat:   ldx ##2                     ; 10: the last length 3-6 times
              jsr abs:.word0 (hGet)
              clc
              adc ##3
              tax
              dey
              lda [HLZ_DST],y
              and ##0x00ff
              iny
hRunPut:      sep #0x20
hRunByte:     sta [HLZ_DST],y
              iny
              dex
              bne hRunByte
              rep #0x20
              lda dp:HLZ_K
              asl a
              tax
              jmp (abs:.word0 (hAdvH),x)

;;; X = n (1-9): A = the next n bits, the first one on top. Y kept.
hGet:         stx dp:HLZ_N
              txa
              clc
              adc dp:HLZ_K
              pha                         ; k + n
              eor ##0xffff
              sec
              adc ##16                    ; 16 - k - n
              tax
              lda [HLZ_BP]
              cpx ##8
              bcc hGetSmall
              xba                         ; 8 of the shifts at once
              and ##0x00ff
              dex
              dex
              dex
              dex
              dex
              dex
              dex
              dex
hGetSmall:    cpx ##0
              beq hGetMask
hGetShift:    lsr a
              dex
              bne hGetShift
hGetMask:     sta dp:HLZ_V
              lda dp:HLZ_N
              asl a
              tax
              lda dp:HLZ_V
              and abs:.word0 (hMask-2),x
              sta dp:HLZ_V
              pla                         ; k + n: move past those bits
hGetByte:     cmp ##8
              bcc hGetDone
              dec dp:HLZ_BP
              sbc ##8
              bra hGetByte
hGetDone:     sta dp:HLZ_K
              lda dp:HLZ_V
              rts

;;; The end of the header (A = the bit offset), then the two lookup tables.
hHeaderDone:  sta dp:HLZ_K
              ldy ##0                     ; literal/length table: symbols 0-325
              lda ##HLZ_LITERALS
              sta dp:HLZ_LAST
              jsr abs:.word0 (hCountRuns)
hLiteral:     lda [HLZ_DST],y             ; literals: entry = symbol | 2n << 8
              and ##0x00ff
              bne hLiteralUsed
hLiteralNext: iny
              cpy ##256
              bcc hLiteral
              bra hLengths
hLiteralUsed: asl a
              tax                         ; 2n (carry clear)
              xba
              sty dp:HLZ_E
              ora dp:HLZ_E
              sty dp:HLZ_S
              ldy dp:HLZ_NEXT,x           ; this code's run of the table
              pha
              tya
              adc long:hRunBytes-2,x
              sta dp:HLZ_NEXT,x
              pla
              jsr (abs:.word0 (hFillAt-2),x)
              ldy dp:HLZ_S
              bra hLiteralNext
hLengths:     lda [HLZ_DST],y             ; the end and the match lengths
              and ##0x00ff
              bne hLengthUsed
hLengthNext:  iny
              cpy ##HLZ_LITERALS
              bcc hLengths
              bra hOffsets
hLengthUsed:  asl a
              sta dp:HLZ_N                ; 2n
              sty dp:HLZ_S
              tya
              cmp ##257
              bcc hEntryEnd
              ldx ##32                    ; new match: u = s - 255 (2-35)
              sbc ##255
              cmp ##36
              bcc hEntryLength
              ldx ##96                    ; repeat match: u = s - 290 (1-35)
              sbc ##35
hEntryLength: cmp ##34                    ; the length - 1, or $FE/$FF
              bcc hEntryMake
              adc ##0x00db                ; (carry set) u + $DC
              bra hEntryMake
hEntryEnd:    ldx ##64
              lda ##0
hEntryMake:   sta dp:HLZ_E
              txa
              clc
              adc dp:HLZ_N
              xba
              ora dp:HLZ_E
              jsr abs:.word0 (hPlaceRun)
              bra hLengthNext
hOffsets:     phk                         ; offset table: symbols 326-597
              plb
              lda dp:HLZ_TAB
              clc
              adc ##HLZ_TABLE
              sta dp:HLZ_TAB
              lda ##HLZ_LENGTHS
              sta dp:HLZ_LAST
              jsr abs:.word0 (hCountRuns)
hOffset:      lda [HLZ_DST],y
              and ##0x00ff
              bne hOffsetUsed
hOffsetNext:  iny
              cpy ##HLZ_LENGTHS
              bcc hOffset
              phk
              plb
              lda dp:HLZ_K
              asl a
              plb
              rtl
hOffsetUsed:  asl a
              sta dp:HLZ_N                ; 2n
              sty dp:HLZ_S
              tya
              sec
              sbc ##HLZ_LITERALS
              cmp ##16
              bcs hEntryFar
              inc a                       ; offset 1-16: entry = offset << 8 | 2n
              xba
              ora dp:HLZ_N
              bra hOffsetPlace
hEntryFar:    sbc ##16                    ; (carry set) high byte << 8 | 2n | $40
              xba
              ora dp:HLZ_N
              ora ##0x0040
hOffsetPlace: jsr abs:.word0 (hPlaceRun)
              bra hOffsetNext

;;; A = the entry of the symbol HLZ_S, HLZ_N = 2n: fill its run, next run.
;;; Returns Y = HLZ_S.
hPlaceRun:    ldx dp:HLZ_N
              ldy dp:HLZ_NEXT,x
              pha
              tya
              clc
              adc long:hRunBytes-2,x
              sta dp:HLZ_NEXT,x
              pla
              jsr (abs:.word0 (hFillAt-2),x)
              ldy dp:HLZ_S
              rts

;;; Count the code lengths of symbols Y .. HLZ_LAST-1 (lengths at [HLZ_DST]),
;;; set HLZ_NEXT[n] = the table offset of the first code of length n (after
;;; cnt(m) * 2^(10-m) bytes of every m < n), then DBR = the tables' bank.
;;; Y is kept. DBR = this bank on entry.
hCountRuns:   sty dp:HLZ_S
              ldx ##18
hCntZero:     stz abs:.word0 (hCnt),x
              dex
              dex
              bpl hCntZero
hCount:       lda [HLZ_DST],y
              and ##0x00ff
              asl a
              tax
              inc abs:.word0 (hCnt),x
              iny
              cpy dp:HLZ_LAST
              bcc hCount
              lda dp:HLZ_TAB
              ldx ##2
hStart:       sta dp:HLZ_NEXT,x
              sta dp:HLZ_V
              lda abs:.word0 (hCnt),x
              ldy abs:.word0 (hShift-2),x
hShiftCnt:    asl a
              dey
              bne hShiftCnt
              clc
              adc dp:HLZ_V
              inx
              inx
              cpx ##20
              bcc hStart
              sep #0x20
              lda dp:HLZ_TAB+2
              pha
              plb
              rep #0x20
              ldy dp:HLZ_S
              rts

;;; A = the entry, Y = the run's table offset (DBR = the tables' bank), X = 2n:
;;; n = 9 stores 1 word, 8 stores 2, ... 5 stores 16; n = 1-4 loop on 16.
hFillBig:     pha
              lda long:hRunBytes-2,x      ; 2^(10-n) bytes = blocks of 32
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:HLZ_V
              pla
hFillBlock:   jsr abs:.word0 (hFill16)
              pha
              tya
              clc
              adc ##32
              tay
              pla
              dec dp:HLZ_V
              bne hFillBlock
              rts
hFill16:      sta abs:30,y
              sta abs:28,y
              sta abs:26,y
              sta abs:24,y
              sta abs:22,y
              sta abs:20,y
              sta abs:18,y
              sta abs:16,y
hFill8:       sta abs:14,y
              sta abs:12,y
              sta abs:10,y
              sta abs:8,y
hFill4:       sta abs:6,y
              sta abs:4,y
hFill2:       sta abs:2,y
hFill1:       sta abs:0,y
              rts

;;; >>> header: generated by tools/gen_hlz_copies.py, do not edit by hand
;;; The code lengths: copy k reads the next code-length code (7 bits from bit
;;; k) and writes a length 0-9 as a word (its junk byte is the next length).
;;; Y = lengths written; DBR = this bank.
hH0b:         dec dp:HLZ_BP
hH0a:         dec dp:HLZ_BP
hH0:          cpy ##HLZ_LENGTHS
              bcs hHDone0
              lda [HLZ_BP]
              xba
              and ##0x00fe
              tax
              lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8
              sta [HLZ_DST],y
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hAdvH+0),x)
hHDone0:      lda ##0
              jmp abs:.word0 (hHeaderDone)
hH1b:         dec dp:HLZ_BP
hH1a:         dec dp:HLZ_BP
hH1:          cpy ##HLZ_LENGTHS
              bcs hHDone1
              lda [HLZ_BP]
              asl a
              xba
              and ##0x00fe
              tax
              lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8
              sta [HLZ_DST],y
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hAdvH+2),x)
hHDone1:      lda ##1
              jmp abs:.word0 (hHeaderDone)
hH2b:         dec dp:HLZ_BP
hH2a:         dec dp:HLZ_BP
hH2:          cpy ##HLZ_LENGTHS
              bcs hHDone2
              lda [HLZ_BP]
              asl a
              asl a
              xba
              and ##0x00fe
              tax
              lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8
              sta [HLZ_DST],y
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hAdvH+4),x)
hHDone2:      lda ##2
              jmp abs:.word0 (hHeaderDone)
hH3b:         dec dp:HLZ_BP
hH3a:         dec dp:HLZ_BP
hH3:          cpy ##HLZ_LENGTHS
              bcs hHDone3
              lda [HLZ_BP]
              asl a
              asl a
              asl a
              xba
              and ##0x00fe
              tax
              lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8
              sta [HLZ_DST],y
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hAdvH+6),x)
hHDone3:      lda ##3
              jmp abs:.word0 (hHeaderDone)
hH4b:         dec dp:HLZ_BP
hH4a:         dec dp:HLZ_BP
hH4:          cpy ##HLZ_LENGTHS
              bcs hHDone4
              lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0x00fe
              tax
              lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8
              sta [HLZ_DST],y
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hAdvH+8),x)
hHDone4:      lda ##4
              jmp abs:.word0 (hHeaderDone)
hH5b:         dec dp:HLZ_BP
hH5a:         dec dp:HLZ_BP
hH5:          cpy ##HLZ_LENGTHS
              bcs hHDone5
              lda [HLZ_BP]
              lsr a
              lsr a
              lsr a
              and ##0x00fe
              tax
              lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8
              sta [HLZ_DST],y
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hAdvH+10),x)
hHDone5:      lda ##5
              jmp abs:.word0 (hHeaderDone)
hH6b:         dec dp:HLZ_BP
hH6a:         dec dp:HLZ_BP
hH6:          cpy ##HLZ_LENGTHS
              bcs hHDone6
              lda [HLZ_BP]
              lsr a
              lsr a
              and ##0x00fe
              tax
              lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8
              sta [HLZ_DST],y
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hAdvH+12),x)
hHDone6:      lda ##6
              jmp abs:.word0 (hHeaderDone)
hH7b:         dec dp:HLZ_BP
hH7a:         dec dp:HLZ_BP
hH7:          cpy ##HLZ_LENGTHS
              bcs hHDone7
              lda [HLZ_BP]
              lsr a
              and ##0x00fe
              tax
              lda abs:.word0 (hClTab),x  ; symbol | dispatch << 8
              sta [HLZ_DST],y
              iny
              xba
              and ##0x00ff
              tax
              jmp (abs:.word0 (hAdvH+14),x)
hHDone7:      lda ##7
              jmp abs:.word0 (hHeaderDone)
;;; A run symbol (10-12): its extra bits follow at bit k.
hS0b:         dec dp:HLZ_BP
hS0a:         dec dp:HLZ_BP
hS0:          lda ##0
              jmp abs:.word0 (hRun)
hS1b:         dec dp:HLZ_BP
hS1a:         dec dp:HLZ_BP
hS1:          lda ##1
              jmp abs:.word0 (hRun)
hS2b:         dec dp:HLZ_BP
hS2a:         dec dp:HLZ_BP
hS2:          lda ##2
              jmp abs:.word0 (hRun)
hS3b:         dec dp:HLZ_BP
hS3a:         dec dp:HLZ_BP
hS3:          lda ##3
              jmp abs:.word0 (hRun)
hS4b:         dec dp:HLZ_BP
hS4a:         dec dp:HLZ_BP
hS4:          lda ##4
              jmp abs:.word0 (hRun)
hS5b:         dec dp:HLZ_BP
hS5a:         dec dp:HLZ_BP
hS5:          lda ##5
              jmp abs:.word0 (hRun)
hS6b:         dec dp:HLZ_BP
hS6a:         dec dp:HLZ_BP
hS6:          lda ##6
              jmp abs:.word0 (hRun)
hS7b:         dec dp:HLZ_BP
hS7a:         dec dp:HLZ_BP
hS7:          lda ##7
              jmp abs:.word0 (hRun)
;;; Word k + n: the header copy for bit offset k + n after a code of n bits;
;;; +16 a run symbol.
hAdvH:        .word .word0 (hH0), .word0 (hH1), .word0 (hH2), .word0 (hH3)
              .word .word0 (hH4), .word0 (hH5), .word0 (hH6), .word0 (hH7)
              .word .word0 (hH0a), .word0 (hH1a), .word0 (hH2a), .word0 (hH3a)
              .word .word0 (hH4a), .word0 (hH5a), .word0 (hH6a), .word0 (hH0)
              .word .word0 (hH0), .word0 (hS1), .word0 (hS2), .word0 (hS3)
              .word .word0 (hS4), .word0 (hS5), .word0 (hS6), .word0 (hS7)
              .word .word0 (hS0a), .word0 (hS1a), .word0 (hS2a), .word0 (hS3a)
              .word .word0 (hS4a), .word0 (hS5a), .word0 (hS6a)
;;; <<< header: end of the generated block

;;; Constants (n = 1-9 unless noted) and setup state (this bank).
hClOrder:     .word 20, 22, 24, 0, 18, 16, 14, 12, 10, 8, 6, 4, 2   ; 2 * CL_ORDER
hClShift:     .word 7, 6, 5, 4, 3, 2, 1                          ; n = 1-7: 8 - n
hClStep:      .word 128, 64, 32, 16, 8, 4, 2                     ; n = 1-7: 2^(8-n)
hShift:       .word 9, 8, 7, 6, 5, 4, 3, 2, 1                    ; 10 - n
hRunBytes:    .word 512, 256, 128, 64, 32, 16, 8, 4, 2           ; 2^(10-n)
hFillAt:      .word .word0 (hFillBig), .word0 (hFillBig), .word0 (hFillBig), .word0 (hFillBig)
              .word .word0 (hFill16), .word0 (hFill8), .word0 (hFill4), .word0 (hFill2), .word0 (hFill1)
hMask:        .word 1, 3, 7, 15, 31, 63, 127, 255, 511
hClLen:       .space 26
hCnt:         .space 20
hClTab:       .space 256
