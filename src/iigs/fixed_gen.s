;;; Load-time art generator (tools/fixed_units.py is the byte-level model).
;;;
;;; A shared unit loaded raw at FIXED_GEN for each floor load. The floor
;;; loader calls GenUnit with JSL once this unit is in, then after
;;; every following unit until the call returns carry clear. The sound
;;; effects load later and overwrite this code; no resident RAM is used.
;;; The generator and its units are the episode-disk part of a
;;; floor load; it finishes inside that part, before the effects. The sight
;;; tables and the upper matrix half come from the sight unit (sight_gen.s)
;;; in the floor-disk part, which may load before or after this one.
;;;
;;; Scratch in sound-effect RAM; memmap.inc selects each campaign's addresses:
;;;   SFX_BASE   load buffer: column chunk, group blob (u16 2c), templates
;;;   GEN_USED   used-column bitmap, bounded by GEN_BITMAP_BYTES
;;;   POINTERS   64 command pointers of the current shape
;;;   STRIPPOS   64 strip positions of the current shape ($FFFF = none)
;;;   GEN_DUMMY  128-byte sink for writes of aliased wall lights
;;;   GEN_PAGES  page table (dead after the program step), then the decode stage
;;;   GEN_PROG   floor program
;;; Direct page $B0-$DF of page 0 (unused by the floor loader).

#include "memmap.inc"
SRC           .equ SFX_BASE
DUMMY         .equ GEN_DUMMY
PROG          .equ GEN_PROG
PAGES         .equ GEN_PAGES
WALL_PTRS     .equ WALL_LIGHT_POINTERS
CACHE         .equ WALL_COLUMNS
HEADERS       .equ SPRITE_CMDS
CHUNK         .equ 384
SPRITE_TABLES .equ 0x0810           ; PROG offset of the sprite light tables
WALL_TABLES   .equ 0x0010


              .section fixedgen, text, root, noreorder
              .public GenUnit
;;; JSL with any register widths. Carry set: call again after the next unit.
GenUnit:      php
              rep #0x30
              phb
              phd
              lda ##0
              tcd
              pea #0x3939
              plb
              plb
              lda abs:.word0 (genState)
              asl a
              tax
              jsr (abs:.word0 (genSteps),x)
              lda abs:.word0 (genActive)  ; before the caller's data bank returns
              pld
              plb
              cmp ##0
              bne genMore
              plp
              clc
              rtl
genMore:      plp
              sec
              rtl
genSteps:     .word .word0 (stepProgram), .word0 (stepGroupArt), .word0 (stepGroupCommands), .word0 (stepColumns)

;;; ---------------------------------------------------------------- program
stepProgram:  lda ##1
              sta abs:.word0 (genActive)
              lda long:PROG+2
              sta abs:.word0 (wallAt)
              lda long:PROG+10
              sta abs:.word0 (columns)
              ldx ##0                     ; clear the used bitmap
clearUsed:    stz abs:USED,x
              inx
              inx
              cpx ##GEN_BITMAP_BYTES
              bcc clearUsed
              stz abs:.word0 (page)                ; mark the columns of the used pages
markPage:     jsr abs:.word0 (pageUsed)
              bcc markNext
              lda abs:.word0 (page)
              xba
              lsr a                       ; page * 128
              tax
              ldy ##64
markColumn:   lda long:PAGES,x
              jsr abs:.word0 (setUsed)
              inx
              inx
              dey
              bne markColumn
markNext:     inc abs:.word0 (page)
              lda abs:.word0 (page)
              cmp ##WALL_PAGE_COUNT
              bcc markPage
              ldx ##0                     ; ranks*16 into the load buffer
              stz dp:G_T0
              stz abs:.word0 (gid)
rankLoop:     lda dp:G_T0
              sta long:SRC,x
              lda abs:.word0 (gid)
              jsr abs:.word0 (testUsed)
              beq rankNext
              lda dp:G_T0
              clc
              adc ##16
              sta dp:G_T0
rankNext:     inx
              inx
              inc abs:.word0 (gid)
              lda abs:.word0 (gid)
              cmp abs:.word0 (columns)
              bcc rankLoop
              stz abs:.word0 (page)                ; the column cache, all 106 pages
cachePage:    lda abs:.word0 (page)
              xba
              tay                         ; Y = page * 256: cache offset
              lsr a
              tax                         ; X = page * 128: page table offset
              jsr abs:.word0 (pageUsed)
              bcs cacheUsed
              lda ##64
              sta dp:G_CNT
              bra cacheZeroNext
cacheUsed:    lda ##64
              sta dp:G_CNT
cacheColumn:  phx
              lda long:PAGES,x
              asl a
              tax
              lda long:SRC,x
              tyx
              sta long:CACHE,x
              lda abs:.word0 (page)
              xba
              sta long:CACHE+2,x
              plx
              inx
              inx
              iny
              iny
              iny
              iny
              dec dp:G_CNT
              bne cacheColumn
              bra cacheNext
cacheZeroNext:
              tyx
              lda ##0
              sta long:CACHE,x
              sta long:CACHE+2,x
              iny
              iny
              iny
              iny
              dec dp:G_CNT
              bne cacheZeroNext
cacheNext:    inc abs:.word0 (page)
              lda abs:.word0 (page)
              cmp ##WALL_PAGE_COUNT
              bcc cachePage
              lda abs:.word0 (wallAt)              ; the wall walk state
              clc
              adc ##WALL_BITMAP_BYTES+4
              sta abs:.word0 (rangePtr)
              lda abs:.word0 (wallAt)
              tax
              stz abs:.word0 (wallLoaded)
              lda long:PROG+WALL_BITMAP_BYTES+2,x          ; ranges
              cmp ##0xffff                ; packed walls: the pointer table is loaded
              bne wallRanges
              sta abs:.word0 (wallLoaded)
              lda ##0
wallRanges:   sta dp:G_T0
              asl a
              asl a
              clc
              adc dp:G_T0                ; * 5
              clc
              adc abs:.word0 (rangePtr)
              sta abs:.word0 (rangeEnd)
              tax
              lda long:PROG,x             ; aliases
              asl a
              asl a
              inx
              inx
              stx abs:.word0 (aliasPtr)
              clc
              adc abs:.word0 (aliasPtr)
              sta abs:.word0 (aliasEnd)
              stz abs:.word0 (slotsLeft)
              stz abs:.word0 (entry)
              stz abs:.word0 (chunk)
              lda long:PROG+4
              tax
              lda long:PROG,x
              sta abs:.word0 (groupsLeft)
              inx
              inx
              stx abs:.word0 (groupPtr)
              lda abs:.word0 (groupsLeft)
              beq programToColumns
              lda ##1
              sta abs:.word0 (genState)
              rts
programToColumns:
              lda ##3
              sta abs:.word0 (genState)
              rts

;;; Carry set when bit (page) of the wall bitmap is set.
pageUsed:     phx
              lda abs:.word0 (page)
              lsr a
              lsr a
              lsr a
              clc
              adc abs:.word0 (wallAt)
              tax
              lda long:PROG,x
              sta dp:G_T1
              lda abs:.word0 (page)
              and ##7
              tax
              lda abs:.word0 (bitMask),x
              and ##255
              and dp:G_T1
              plx
              cmp ##1
              rts

;;; A = column id: set / test its used bit.
setUsed:      phx
              pha
              and ##7
              tax
              lda abs:.word0 (bitMask),x
              and ##255
              sta dp:G_T1
              pla
              lsr a
              lsr a
              lsr a
              tax
              sep #0x20
              lda abs:USED,x
              ora dp:G_T1
              sta abs:USED,x
              rep #0x20
              plx
              rts
testUsed:     phx
              pha
              and ##7
              tax
              lda abs:.word0 (bitMask),x
              and ##255
              sta dp:G_T1
              pla
              lsr a
              lsr a
              lsr a
              tax
              lda abs:USED,x
              and dp:G_T1
              and ##255
              plx
              cmp ##0                     ; Z: unused (PLX changed the flags)
              rts
bitMask:      .byte 1, 2, 4, 8, 16, 32, 64, 128

;;; ---------------------------------------------------------- expand four
;;; G_CNT texels of doubled indexes at $39:(x4Source) through the four
;;; light tables at PROG+(x4Tables) into x4Dest0..3 (24-bit each).
expand4:      lda abs:.word0 (x4Source)
              sta long:x4Load+1
              lda abs:.word0 (x4Tables)
              sta long:x4Lda0+1
              clc
              adc ##512
              sta long:x4Lda1+1
              adc ##512
              sta long:x4Lda2+1
              adc ##512
              sta long:x4Lda3+1
              lda abs:.word0 (x4Dest0)
              sta long:x4Sta0+1
              lda abs:.word0 (x4Dest1)
              sta long:x4Sta1+1
              lda abs:.word0 (x4Dest2)
              sta long:x4Sta2+1
              lda abs:.word0 (x4Dest3)
              sta long:x4Sta3+1
              sep #0x20
              lda abs:.word0 (x4Dest0+2)
              sta long:x4Sta0+3
              lda abs:.word0 (x4Dest1+2)
              sta long:x4Sta1+3
              lda abs:.word0 (x4Dest2+2)
              sta long:x4Sta2+3
              lda abs:.word0 (x4Dest3+2)
              sta long:x4Sta3+3
              rep #0x20
              lda dp:G_CNT
              beq x4Done
              asl a
              sta long:x4End+1
              pea #0x3a3a
              plb
              plb
              ldx ##0
x4Load:       lda long:SRC,x
              tay
x4Lda0:       lda abs:0x0000,y
x4Sta0:       sta long:0x000000,x
x4Lda1:       lda abs:0x0000,y
x4Sta1:       sta long:0x000000,x
x4Lda2:       lda abs:0x0000,y
x4Sta2:       sta long:0x000000,x
x4Lda3:       lda abs:0x0000,y
x4Sta3:       sta long:0x000000,x
              inx
              inx
x4End:        cpx ##0x0000
              bne x4Load
              pea #0x3939
              plb
              plb
x4Done:       rts

;;; G_CNT index bytes at PROG+(G_X) through the light table at
;;; PROG+(G_T2) into [G_DST].
expand1:      lda dp:G_CNT
              beq x1Done
              ldx dp:G_X
x1Loop:       lda long:SRC,x
              and ##255
              asl a
              clc
              adc dp:G_T2
              phx
              tax
              lda long:PROG,x
              plx
              sta [G_DST]
              inc dp:G_DST
              inc dp:G_DST
              inx
              dec dp:G_CNT
              bne x1Loop
x1Done:       rts

;;; ------------------------------------------------------- group art step
;;; Group entry: u8 id, u16 blob, 4 x addr24 areas, 4 x addr24 strips,
;;; u16 strip texels, then the member list. With strips, their unit loads
;;; at SRC + 2 x blob right after the blob: the art waits for it.
stepGroupArt: ldx abs:.word0 (groupPtr)
              lda long:PROG+27,x
              beq artNow
              lda abs:.word0 (stripIn)
              bne artNow
              inc abs:.word0 (stripIn)
              rts
artNow:       stz abs:.word0 (stripIn)
              lda long:PROG+1,x
              sta abs:.word0 (blobLen)
              ldy ##0
artAreas:     lda long:PROG+3,x
              sta abs:.word0 (areas),y
              lda long:PROG+5,x
              and ##255
              sta abs:.word0 (areas+2),y
              lda long:PROG+15,x
              sta abs:.word0 (strips),y
              lda long:PROG+17,x
              and ##255
              sta abs:.word0 (strips+2),y
              inx
              inx
              inx
              iny
              iny
              iny
              iny
              cpy ##16
              bcc artAreas
              ldx abs:.word0 (groupPtr)
              lda long:PROG+27,x
              sta abs:.word0 (stripLen)
              txa
              clc
              adc ##29
              sta abs:.word0 (memberPtr)
              lda abs:.word0 (blobLen)
              asl a
              sta abs:.word0 (stripSrc)    ; SRC offset of the strip unit
              stz abs:.word0 (x4Source)
              lda ##PROG_LOW+SPRITE_TABLES
              sta abs:.word0 (x4Tables)
              ldx ##0
artDests:     lda abs:.word0 (areas),x
              sta abs:.word0 (x4Dests),x
              lda abs:.word0 (areas+2),x
              sta abs:.word0 (x4Dests+2),x
              inx
              inx
              inx
              inx
              cpx ##16
              bcc artDests
              jsr abs:.word0 (copyDests)
              lda abs:.word0 (blobLen)
              sta dp:G_CNT
              jsr abs:.word0 (expand4)
              ldy ##0                     ; strip copies; a repeat is shared
artStrips:    cpy ##0
              beq artStripCopy
              lda abs:.word0 (strips),y
              cmp abs:.word0 (strips-4),y
              bne artStripCopy
              lda abs:.word0 (strips+2),y
              cmp abs:.word0 (strips-2),y
              beq artStripNext
artStripCopy: lda abs:.word0 (strips),y
              sta dp:G_DST
              lda abs:.word0 (strips+2),y
              sta dp:G_DST+2
              lda abs:.word0 (stripSrc)
              sta dp:G_X
              lda abs:.word0 (stripLen)
              sta dp:G_CNT
              tya
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a                       ; light * 512 (Y = light * 4)
              clc
              adc ##SPRITE_TABLES
              sta dp:G_T2
              phy
              jsr abs:.word0 (expand1)
              ply
artStripNext: iny
              iny
              iny
              iny
              cpy ##16
              bcc artStrips
              lda ##2
              sta abs:.word0 (genState)
              rts

copyDests:    lda abs:.word0 (x4Dests)
              sta abs:.word0 (x4Dest0)
              lda abs:.word0 (x4Dests+2)
              sta abs:.word0 (x4Dest0+2)
              lda abs:.word0 (x4Dests+4)
              sta abs:.word0 (x4Dest1)
              lda abs:.word0 (x4Dests+6)
              sta abs:.word0 (x4Dest1+2)
              lda abs:.word0 (x4Dests+8)
              sta abs:.word0 (x4Dest2)
              lda abs:.word0 (x4Dests+10)
              sta abs:.word0 (x4Dest2+2)
              lda abs:.word0 (x4Dests+12)
              sta abs:.word0 (x4Dest3)
              lda abs:.word0 (x4Dests+14)
              sta abs:.word0 (x4Dest3+2)
              rts

;;; --------------------------------------------------- group command step
;;; Templates are in the load buffer: u16 members, then per member u16
;;; shape, 68 header bytes, pool low, pool high, 64 first-equal columns,
;;; 64 columns of (u8 runs, runs x (a, b, u16 offset)).
stepGroupCommands:
              lda abs:0
              sta dp:G_MEMBERS
              lda ##2
              sta dp:G_TMPL
              ldx abs:.word0 (memberPtr)
              stx dp:G_AT
memberLoop:   ldx dp:G_AT
              lda long:PROG,x
              sta dp:G_FRAME
              lda long:PROG+2,x
              sta dp:G_DST
              lda long:PROG+4,x
              and ##255
              sta dp:G_DST+2
              sta abs:.word0 (commandBank)
              stz dp:G_CUR
              lda long:PROG+5,x
              sta dp:G_CNT               ; strips of this member
              txa
              clc
              adc ##7
              sta dp:G_AT
              ldx ##126                   ; no strip in any column
              lda ##0xffff
clearStrips:  sta abs:STRIPPOS,x
              dex
              dex
              bpl clearStrips
              lda dp:G_CNT
              beq stripsSet
stripEntry:   ldx dp:G_AT
              lda long:PROG,x
              and ##255
              asl a
              tay
              lda long:PROG+1,x
              sta abs:STRIPPOS,y
              inx
              inx
              inx
              stx dp:G_AT
              dec dp:G_CNT
              bne stripEntry
stripsSet:    ldx dp:G_TMPL
              lda abs:70,x                ; pool low, high
              sta abs:.word0 (poolEnds)
              txa
              clc
              adc ##136
              sta dp:G_BODY              ; first column record
              stz dp:G_X                 ; x
columnLoop:   ldx dp:G_BODY
              lda abs:0,x
              and ##255
              sta dp:G_RUNS
              inx
              stx dp:G_T0                ; first run
              asl a
              asl a
              sec
              adc dp:G_BODY
              sta dp:G_BODY              ; next column record
              ldx dp:G_TMPL              ; y = first equal column
              txa
              clc
              adc dp:G_X
              adc ##72
              tax
              lda abs:0,x
              and ##255
              cmp dp:G_X
              beq newColumn
              asl a
              tay                         ; Y = 2y
              lda dp:G_X
              asl a
              tax                         ; X = 2x
              lda abs:STRIPPOS,y
              cmp abs:STRIPPOS,x
              bne newColumn
              lda abs:POINTERS,y
              sta abs:POINTERS,x
              jmp abs:.word0 (columnNext)
newColumn:    lda dp:G_X
              asl a
              tax
              ldy dp:G_CUR                ; Y = write offset in the command block
              tya
              clc
              adc dp:G_DST
              sta abs:POINTERS,x
              lda abs:STRIPPOS,x
              cmp ##0xffff
              beq bodyRuns
              asl a
              sta dp:G_T1                 ; 2 * strip position
              lda abs:.word0 (poolEnds)
              sta [G_DST],y
              iny
              iny
              lda abs:.word0 (strips)
              clc
              adc dp:G_T1
              sta [G_DST],y
              iny
              iny
              lda abs:.word0 (strips+4)
              clc
              adc dp:G_T1
              sta [G_DST],y
              iny
              iny
              lda abs:.word0 (strips+8)
              clc
              adc dp:G_T1
              sta [G_DST],y
              iny
              iny
              lda abs:.word0 (strips+12)
              clc
              adc dp:G_T1
              sta [G_DST],y
              iny
              iny
bodyRuns:     lda dp:G_RUNS
              beq columnEnd
              ldx dp:G_T0
runLoop:      lda abs:0,x                 ; a | b << 8
              sta [G_DST],y
              iny
              iny
              and ##255
              asl a
              sta dp:G_T1                 ; 2a
              lda abs:2,x
              asl a
              sec
              sbc dp:G_T1
              sta dp:G_T1                 ; 2 * offset - 2a
              lda abs:.word0 (areas)
              clc
              adc dp:G_T1
              sta [G_DST],y
              iny
              iny
              lda abs:.word0 (areas+4)
              clc
              adc dp:G_T1
              sta [G_DST],y
              iny
              iny
              lda abs:.word0 (areas+8)
              clc
              adc dp:G_T1
              sta [G_DST],y
              iny
              iny
              lda abs:.word0 (areas+12)
              clc
              adc dp:G_T1
              sta [G_DST],y
              iny
              iny
              inx
              inx
              inx
              inx
              dec dp:G_RUNS
              bne runLoop
columnEnd:    lda ##0
              sta [G_DST],y
              iny
              iny
              sty dp:G_CUR
columnNext:   inc dp:G_X
              lda dp:G_X
              cmp ##64
              bcs columnsDone
              jmp abs:.word0 (columnLoop)
columnsDone:  jsr abs:.word0 (writeHeader)
              lda dp:G_BODY
              sta dp:G_TMPL              ; next member template
              dec dp:G_MEMBERS
              beq membersDone
              jmp abs:.word0 (memberLoop)
membersDone:  lda dp:G_AT
              sta abs:.word0 (groupPtr)
              dec abs:.word0 (groupsLeft)
              beq groupsDone
              lda ##1
              sta abs:.word0 (genState)
              rts
groupsDone:   lda ##3
              sta abs:.word0 (genState)
              rts

;;; A -> [G_DST], G_DST += 2 (a command block stays inside its bank).
putWord:      sta [G_DST]
              inc dp:G_DST
              inc dp:G_DST
              rts

;;; Frame header at HEADERS + frame * 202: 64 pointers, 68 template bytes,
;;; the command bank word, the four light banks.
writeHeader:
              lda dp:G_FRAME
              ldx ##202
              jsr abs:.word0 (multiply)
              tax
              ldy ##0
headPointers: lda abs:POINTERS,y
              sta long:HEADERS,x
              inx
              inx
              iny
              iny
              cpy ##128
              bcc headPointers
              ldy dp:G_TMPL
              lda ##34
              sta dp:G_CNT
headFixed:    lda abs:2,y
              sta long:HEADERS,x
              inx
              inx
              iny
              iny
              dec dp:G_CNT
              bne headFixed
              lda abs:.word0 (commandBank)
              sta long:HEADERS,x
              sep #0x20
              lda abs:.word0 (areas+2)
              sta long:HEADERS+2,x
              lda abs:.word0 (areas+6)
              sta long:HEADERS+3,x
              lda abs:.word0 (areas+10)
              sta long:HEADERS+4,x
              lda abs:.word0 (areas+14)
              sta long:HEADERS+5,x
              rep #0x20
              rts

;;; A = A * X (16-bit result).
multiply:     sta dp:G_T1
              stx dp:G_T2
              lda ##0
mulLoop:      lsr dp:G_T2
              bcc mulSkip
              clc
              adc dp:G_T1
mulSkip:      asl dp:G_T1
              ldx dp:G_T2
              bne mulLoop
              rts

;;; ---------------------------------------------------------- column step
stepColumns:  lda abs:.word0 (chunk)
              ldx ##CHUNK
              jsr abs:.word0 (multiply)
              sta abs:.word0 (gid)                 ; first id of this chunk
              lda abs:.word0 (columns)
              sec
              sbc abs:.word0 (gid)
              cmp ##CHUNK
              bcc chunkCount
              lda ##CHUNK
chunkCount:   sta abs:.word0 (chunkLeft)
              stz abs:.word0 (x4Source)
              lda ##PROG_LOW+WALL_TABLES
              sta abs:.word0 (x4Tables)
columnId:     lda abs:.word0 (gid)
              jsr abs:.word0 (testUsed)
              bne columnUsed
              jmp abs:.word0 (columnSkip)
columnUsed:   ldy ##0                     ; four lights
lightLoop:    lda abs:.word0 (entry)
              asl a
              asl a
              tax                         ; X = entry * 4
              lda abs:.word0 (wallLoaded)
              beq lightPlaced
              lda long:WALL_PTRS,x        ; packed walls: the loaded address
              sta abs:.word0 (x4Dests),y
              lda long:WALL_PTRS+2,x
              xba
              sta abs:.word0 (x4Dests+2),y
              jmp abs:.word0 (lightNext)
lightPlaced:  lda abs:.word0 (aliasPtr)
              cmp abs:.word0 (aliasEnd)
              bcs lightFresh
              phx
              tax
              lda long:PROG,x
              plx
              cmp abs:.word0 (entry)
              bne lightFresh
              phx                         ; alias: copy the target pointer
              ldx abs:.word0 (aliasPtr)
              lda long:PROG+2,x
              asl a
              asl a
              tax
              lda long:WALL_PTRS,x
              sta dp:G_T1
              lda long:WALL_PTRS+2,x
              plx
              sta long:WALL_PTRS+2,x
              lda dp:G_T1
              sta long:WALL_PTRS,x
              lda abs:.word0 (aliasPtr)
              clc
              adc ##4
              sta abs:.word0 (aliasPtr)
              lda ##.word0 DUMMY
              sta abs:.word0 (x4Dests),y
              lda ##.byte2 DUMMY
              sta abs:.word0 (x4Dests+2),y
              bra lightNext
lightFresh:   lda abs:.word0 (slotsLeft)
              bne slotReady
              phx
              ldx abs:.word0 (rangePtr)
              lda long:PROG,x
              sta abs:.word0 (slot)
              lda long:PROG+2,x
              and ##255
              sta abs:.word0 (slot+2)
              lda long:PROG+3,x
              sta abs:.word0 (slotsLeft)
              txa
              clc
              adc ##5
              sta abs:.word0 (rangePtr)
              plx
slotReady:    lda abs:.word0 (slot)
              sta long:WALL_PTRS,x
              sta abs:.word0 (x4Dests),y
              lda abs:.word0 (slot+2)
              sta abs:.word0 (x4Dests+2),y
              xba                       ; the painter consumes bank << 8 directly
              sta long:WALL_PTRS+2,x
              lda abs:.word0 (slot)
              clc
              adc ##128
              sta abs:.word0 (slot)
              dec abs:.word0 (slotsLeft)
lightNext:    inc abs:.word0 (entry)
              iny
              iny
              iny
              iny
              cpy ##16
              bcs lightsDone
              jmp abs:.word0 (lightLoop)
lightsDone:   jsr abs:.word0 (copyDests)
              lda ##64
              sta dp:G_CNT
              jsr abs:.word0 (expand4)
columnSkip:   lda abs:.word0 (x4Source)
              clc
              adc ##128
              sta abs:.word0 (x4Source)
              inc abs:.word0 (gid)
              dec abs:.word0 (chunkLeft)
              beq chunkDone
              jmp abs:.word0 (columnId)
chunkDone:    inc abs:.word0 (chunk)
              lda abs:.word0 (chunk)
              ldx ##CHUNK
              jsr abs:.word0 (multiply)
              cmp abs:.word0 (columns)
              bcc chunkMore
              stz abs:.word0 (genActive)
              stz abs:.word0 (genState)
chunkMore:    rts

;;; ------------------------------------------------------------- state
genState:     .word 0
genActive:    .word 0
wallAt:       .word 0
wallLoaded:   .word 0
columns:      .word 0
page:         .word 0
gid:          .word 0
rangePtr:     .word 0
rangeEnd:     .word 0
aliasPtr:     .word 0
aliasEnd:     .word 0
slot:         .word 0, 0
slotsLeft:    .word 0
entry:        .word 0
chunk:        .word 0
chunkLeft:    .word 0
groupsLeft:   .word 0
groupPtr:     .word 0
memberPtr:    .word 0
blobLen:      .word 0
stripLen:     .word 0
stripSrc:     .word 0
stripIn:      .word 0
poolEnds:     .word 0
commandBank:  .word 0
areas:        .word 0, 0, 0, 0, 0, 0, 0, 0
strips:       .word 0, 0, 0, 0, 0, 0, 0, 0
x4Source:     .word 0
x4Tables:     .word 0
x4Dests:      .word 0, 0, 0, 0, 0, 0, 0, 0
x4Dest0:      .word 0, 0
x4Dest1:      .word 0, 0
x4Dest2:      .word 0, 0
x4Dest3:      .word 0, 0
