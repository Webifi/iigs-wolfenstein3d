#include "memmap.inc"
#include "progress.inc"
;;; WDP3 cold loader. LZ waveform blocks expand into a reusable
;;; window at $3E:0000, then upload. The command head expands last.
;;; DBR=$3E. Wave upload stays under StartMusic's sei. After the DOC is
;;; back in register mode and pending alarms are drained, the command-head
;;; move and decode run with interrupts on. Returns with A 16-bit and
;;; interrupts off. No DOC readbacks.
;;;
;;; Only decoder kind 2 (plain byte LZ, header u16 at 22) is assembled. The
;;; Huffman decoders of kinds 0 and 1 and their 1,536-byte tree buffer need
;;; -D WDP3_HUFFMAN=1 and WDP3_HUFFMAN=1 in the environment of the asset
;;; checks: no installed bank uses them and they cost about 1.9 KB of bank $3D.
              .section soundcode, text, root, noreorder
              .public ExpandMusicBlocks
              .extern DrainDocInterrupts

ExpandMusicBlocks:
              rep #0x30
              lda abs:4
              sta long:blockDocBase
              lda abs:6
              sta long:blockRemaining
              lda abs:8
              sta long:blockInput
              lda abs:12
              sta long:blockHotPacked
              lda abs:14
              sta long:blockHotLength
              lda abs:18
              sta long:blockSize
              lda abs:20
              sta long:blockHotOffset
#if WDP3_HUFFMAN
              lda abs:22
              sta long:blockFast
              ldx ##0
              ldy ##32
blockTreeCopy:
              lda abs:0,y
              sta long:blockTree,x
              iny
              iny
              inx
              inx
              cpx abs:16
              bcc blockTreeCopy
              lda ##0
              sta long:blockBits
#else
              lda ##0
#endif
              sta long:blockPrevious
              lda long:blockInput
              tay
              sep #0x20
blockMode:    lda long:SOUNDCTL
              bmi blockMode
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x60
              sta long:SOUNDCTL
              rep #0x20
              lda long:blockDocBase
              sta long:SOUNDADRL
nextWaveBlock:
              lda long:blockRemaining
              cmp long:blockSize
              bcc shortWaveBlock
              lda long:blockSize
shortWaveBlock:
              sta long:blockLength
              jsr abs:.word0 (decodeBlock)
              phy
              ldx ##0
              lda long:blockLength
              tay
              beq uploadDone
              sep #0x20
uploadBlock:  lda long:SOUNDCTL
              bmi uploadBlock
              lda abs:0,x
              clc
              adc long:blockPrevious
              sta long:blockPrevious
              sta long:SOUNDDATA
              inx
              dey
              bne uploadBlock
uploadDone:   rep #0x20
              jsl long:Progress3
              ply
              lda long:blockRemaining
              sec
              sbc long:blockLength
              sta long:blockRemaining
              bne nextWaveBlock
              sep #0x20
blockRegisterMode:
              lda long:SOUNDCTL
              bmi blockRegisterMode
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x20
              sta long:SOUNDCTL
              lda #0
              sta long:SOUNDADRH
              jsl long:DrainDocInterrupts
              cli
              rep #0x20
              lda ##0
              sec
              sbc long:blockHotPacked
              sta long:blockInput
              lda long:blockHotPacked
              beq blockHotReady
              lda long:blockHotOffset
              clc
              adc long:blockHotPacked
              dec a
              tax
              ldy ##0xffff
              lda long:blockHotPacked
              dec a
              .byte 0x44, 0x3e, 0x3e         ; MVP: packed head up to $FFFF
blockHotReady:
              lda long:blockHotLength
              sta long:blockLength
              lda long:blockInput
              tay
#if WDP3_HUFFMAN
              lda ##0
              sta long:blockBits
#endif
              jsr abs:.word0 (decodeBlock)
              rep #0x30
              sei
              rtl

;;; Decode exactly blockLength output bytes, preserving continuous input bits.
;;; Kind 2 stores raw tokens. MVN copies each run and is interruptible.
#if WDP3_HUFFMAN
decodeBlock:  lda long:blockFast
              cmp ##2
              beq decodeRaw
              jmp abs:.word0 (blockTokens)
#else
decodeBlock:
#endif
decodeRaw:    lda ##2048
              sta long:blockProgressNext
              ldx ##0
rawToken:     txa
              cmp long:blockProgressNext
              bcc rawProgressKept
              jsl long:Progress3
              lda long:blockProgressNext
              clc
              adc ##2048
              bcc rawProgressNext
              lda ##65535
rawProgressNext:
              sta long:blockProgressNext
              txa
rawProgressKept:
              cmp long:blockLength
              bcc rawMore
              rts
rawMore:      sep #0x20
              lda abs:0,y
              iny
              cmp #128
              bcs rawMatch
              rep #0x20
              and ##127
              inc a
              sta long:blockCount
              phx
              tyx
              ply
              lda long:blockCount
              dec a
              .byte 0x54, 0x3e, 0x3e         ; MVN: literal run, bank $3E to itself
              phx
              tyx
              ply
              bra rawToken
rawMatch:     rep #0x20
              and ##127
              clc
              adc ##3
              sta long:blockCount
              lda abs:0,y
              iny
              iny
              sta long:blockDistance
              phy
              txa
              sec
              sbc long:blockDistance
              phx
              tax
              ply
              lda long:blockCount
              dec a
              .byte 0x54, 0x3e, 0x3e         ; MVN: match, forward so overlap repeats
              phy
              plx
              ply
              bra rawToken
#if WDP3_HUFFMAN
blockTokens:  ldx ##0
blockToken:   txa
              cmp long:blockLength
              bcc blockMore
              rts
blockMore:    sep #0x20
              jsr abs:.word0 (blockByte)
              bpl blockLiteral
              and #127
              rep #0x20
              and ##255
              clc
              adc ##3
              sta long:blockCount
              sep #0x20
              jsr abs:.word0 (blockByte)
              sta long:blockDistance
              jsr abs:.word0 (blockByte)
              sta long:blockDistance+1
              rep #0x20
              phy
              txa
              sec
              sbc long:blockDistance
              tay
              sep #0x20
blockMatch:   lda abs:0,y
              sta abs:0,x
              iny
              inx
              lda long:blockCount
              dec a
              sta long:blockCount
              bne blockMatch
              ply
              rep #0x20
              bra blockToken
blockLiteral:
              rep #0x20
              and ##255
              inc a
              sta long:blockCount
              sep #0x20
blockCopy:    jsr abs:.word0 (blockByte)
              sta abs:0,x
              inx
              lda long:blockCount
              dec a
              sta long:blockCount
              bne blockCopy
              rep #0x20
              bra blockToken

blockByte:    lda long:blockFast
              cmp #2
              bne blockCodedByte
              lda abs:0,y
              iny
              ora #0
              rts
blockCodedByte:
              ora #0
              bne blockFastByte
              jmp abs:.word0 (blockSlowByte)
blockFastByte:
              phx
              rep #0x20
              jsr abs:.word0 (blockPeek)
              asl a
              tax
              lda long:blockTree,x
              bpl blockOverflow
              pha
              xba
              and ##15
              jsr abs:.word0 (blockAdvance)
              pla
              sep #0x20
              plx
              ora #0
              rts
blockOverflow:
              sta long:blockNodeOffset
              lda ##8
              jsr abs:.word0 (blockAdvance)
blockOverflowBit:
              jsr abs:.word0 (blockPeek)
              and ##128
              beq blockOverflowLeft
              lda ##2
blockOverflowLeft:
              clc
              adc long:blockNodeOffset
              tax
              lda long:blockTree,x
              pha
              lda ##1
              jsr abs:.word0 (blockAdvance)
              pla
              bmi blockFastLeaf
              sta long:blockNodeOffset
              bra blockOverflowBit
blockFastLeaf:
              sep #0x20
              plx
              ora #0
              rts
;;; Peek eight input bits; blockBits is the consumed-bit offset 0..7.
blockPeek:    lda abs:0,y
              xba
              pha
              lda long:blockBits
              and ##255
              tax
              pla
              cpx ##0
              beq blockPeekDone
blockPeekShift:
              asl a
              dex
              bne blockPeekShift
blockPeekDone:
              xba
              and ##255
              rts
blockAdvance:
              clc
              adc long:blockBits
              and ##255
              cmp ##8
              bcc blockAdvanceDone
              iny
              sec
              sbc ##8
blockAdvanceDone:
              sta long:blockBits
              rts

blockSlowByte:phx
              ldx ##0
blockNode:    lda long:blockBits
              bne blockBit
              lda abs:0,y
              iny
              sta long:blockBitBuffer
              lda #8
              sta long:blockBits
blockBit:     lda long:blockBitBuffer
              asl a
              sta long:blockBitBuffer
              lda long:blockBits
              dec a
              sta long:blockBits
              rep #0x20
              bcc blockLeft
              inx
              inx
blockLeft:    lda long:blockTree,x
              bmi blockLeaf
              tax
              sep #0x20
              bra blockNode
blockLeaf:    sep #0x20
              plx
              ora #0
              rts
#endif

              .section sounddata, data, root
blockProgressNext:.word 0
blockDocBase: .space 2
blockRemaining: .space 2
blockInput: .space 2
blockHotPacked: .space 2
blockHotLength: .space 2
blockHotOffset: .space 2
blockSize: .space 2
blockLength: .space 2
blockCount: .space 2
blockDistance: .space 2
blockPrevious: .space 2
#if WDP3_HUFFMAN
blockFast: .space 2
blockNodeOffset: .space 2
blockBits: .space 1
blockBitBuffer: .space 1
blockTree: .space 1536
#endif
