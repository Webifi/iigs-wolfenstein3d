#include "memmap.inc"
              .section soundcode, text, root, noreorder
              .public ExpandMusic

CTL .equ SOUNDCTL
DATA .equ SOUNDDATA
ADR .equ SOUNDADRL

;;; StartMusic owns the GLU with interrupts off and DBR=$3E.
;;; Cold waves go directly to DOC; only the hot event stream stays in RAM.
ExpandMusic:  rep #0x30
              lda abs:4
              sta long:unpackDest
              clc
              adc abs:6
              sta long:unpackWaveEnd
              lda abs:8
              clc
              adc ##32
              sta long:unpackHotOffset
              lda abs:10
              sta long:unpackPacked
              lda abs:12
              sta long:unpackLength
              lda abs:16
              sta long:unpackTreeLength
              clc
              adc long:unpackHotOffset
              sta long:unpackHotOffset
              ldx ##0
              ldy ##32
copyTree:     lda abs:0,y
              sta long:unpackTree,x
              iny
              iny
              inx
              inx
              cpx abs:16
              bcc copyTree
              lda ##0
              sta long:unpackBits
              sta long:unpackPrevious
waveToken:    lda long:unpackDest
              cmp long:unpackWaveEnd
              bcc waveMore
              jmp abs:.word0 (relocateHot)
waveMore:     sep #0x20
              jsr abs:.word0 (packedByte)
              bmi waveMatchToken
              jmp abs:.word0 (waveLiteral)
waveMatchToken:
              and #127
              rep #0x20
              and ##255
              clc
              adc ##3
              sta long:unpackCount
              sep #0x20
              jsr abs:.word0 (packedByte)
              sta long:unpackDistance
              jsr abs:.word0 (packedByte)
              sta long:unpackDistance+1
              rep #0x20
              lda long:unpackDistance
              cmp long:unpackCount
              bcc seedLength
              lda long:unpackCount
seedLength:   sta long:unpackSeedLength
              lda long:unpackDest
              sec
              sbc long:unpackDistance
              sta long:unpackSource
              ldx ##0
              sep #0x20
readModeWait: lda long:CTL
              bmi readModeWait
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x40
              sta long:CTL
              rep #0x20
              lda long:unpackSource
              cmp abs:4
              beq seedZero
              dec a
              sta long:unpackSource
              sep #0x20
              jsr abs:.word0 (docByte)
              bra seedPrevious
seedZero:     sep #0x20
              lda #0
seedPrevious: sta long:unpackReadPrevious
seedByte:     jsr abs:.word0 (docByte)
              sta long:unpackSample
              sec
              sbc long:unpackReadPrevious
              sta long:unpackSeed,x
              lda long:unpackSample
              sta long:unpackReadPrevious
              inx
              rep #0x20
              txa
              cmp long:unpackSeedLength
              sep #0x20
              bcc seedByte
              jsr abs:.word0 (waveWriteMode)
              ldx ##0
              bra matchWrite

docByte:      lda long:CTL
              bmi seedByte
              rep #0x20
              lda long:unpackSource
              sta long:ADR
              inc a
              sta long:unpackSource
              sep #0x20
seedLatch:    lda long:CTL
              bmi seedLatch
              lda long:DATA
seedRead:     lda long:CTL
              bmi seedRead
              lda long:DATA
              rts
matchWrite:   lda long:CTL
              bmi matchWrite
              lda long:unpackSeed,x
              clc
              adc long:unpackPrevious
              sta long:unpackPrevious
              sta long:DATA
              inx
              rep #0x20
              txa
              cmp long:unpackSeedLength
              bcc seedIndex
              ldx ##0
seedIndex:    sep #0x20
              lda long:unpackCount
              dec a
              sta long:unpackCount
              bne matchWrite
              rep #0x20
              jmp abs:.word0 (waveToken)
waveLiteral:  rep #0x20
              and ##255
              inc a
              sta long:unpackCount
              jsr abs:.word0 (waveWriteMode)
literalWrite: lda long:CTL
              bmi literalWrite
              jsr abs:.word0 (packedByte)
              clc
              adc long:unpackPrevious
              sta long:unpackPrevious
              sta long:DATA
              lda long:unpackCount
              dec a
              sta long:unpackCount
              bne literalWrite
              rep #0x20
              jmp abs:.word0 (waveToken)

waveWriteMode:
              sep #0x20
writeModeWait:lda long:CTL
              bmi writeModeWait
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x60
              sta long:CTL
              rep #0x20
              lda long:unpackDest
              sta long:ADR
              clc
              adc long:unpackCount
              sta long:unpackDest
              sep #0x20
              rts

relocateHot:  lda ##0
              sec
              sbc long:unpackPacked
              sta long:unpackInput
              dec a
              sta long:unpackBoundary
              lda long:unpackHotOffset
              clc
              adc long:unpackPacked
              dec a
              tay
              ldx ##0xffff
moveHot:      sep #0x20
              lda abs:0,y
              sta abs:0,x
              dey
              dex
              rep #0x20
              txa
              cmp long:unpackBoundary
              bne moveHot
              lda long:unpackInput
              tay
              lda ##0
              sta long:unpackBits
              ldx ##0
hotToken:     txa
              cmp long:unpackLength
              bcc hotMore
              rtl
hotMore:      sep #0x20
              jsr abs:.word0 (packedByte)
              bpl hotLiteral
              and #127
              rep #0x20
              and ##255
              clc
              adc ##3
              sta long:unpackCount
              sep #0x20
              jsr abs:.word0 (packedByte)
              sta long:unpackDistance
              jsr abs:.word0 (packedByte)
              sta long:unpackDistance+1
              rep #0x20
              lda long:unpackDistance
              phy
              txa
              sec
              sbc long:unpackDistance
              tay
              sep #0x20
hotMatch:     lda abs:0,y
              sta abs:0,x
              iny
              inx
              lda long:unpackCount
              dec a
              sta long:unpackCount
              bne hotMatch
              ply
              rep #0x20
              bra hotToken
hotLiteral:   rep #0x20
              and ##255
              inc a
              sta long:unpackCount
              sep #0x20
hotCopy:      jsr abs:.word0 (packedByte)
              sta abs:0,x
              inx
              lda long:unpackCount
              dec a
              sta long:unpackCount
              bne hotCopy
              rep #0x20
              bra hotToken

;;; The tree is copied before in-place expansion can overwrite its header.
packedByte:   phx
              ldx ##0
huffNode:     lda long:unpackBits
              bne huffBit
              lda abs:0,y
              iny
              sta long:unpackBitBuffer
              lda #8
              sta long:unpackBits
huffBit:      lda long:unpackBitBuffer
              asl a
              sta long:unpackBitBuffer
              lda long:unpackBits
              dec a
              sta long:unpackBits
              rep #0x20
              bcc huffLeft
              inx
              inx
huffLeft:     lda long:unpackTree,x
              bmi huffLeaf
              tax
              sep #0x20
              bra huffNode
huffLeaf:     sep #0x20
              plx
              ora #0
              rts

              .section sounddata, data
unpackDest:       .word 0
unpackWaveEnd:    .word 0
unpackHotOffset:  .word 0
unpackPacked:     .word 0
unpackLength:     .word 0
unpackCount:      .word 0
unpackDistance:   .word 0
unpackSeedLength: .word 0
unpackSource:     .word 0
unpackInput:      .word 0
unpackBoundary:   .word 0
unpackSeed:       .space 130

unpackTreeLength: .word 0
unpackBits:       .byte 0
unpackBitBuffer:  .byte 0
unpackPrevious:   .byte 0
unpackReadPrevious: .byte 0
unpackSample:     .byte 0
unpackTree:       .space 1020
