;;; Benchmark-only accelerator identification and clock measurement. No video
;;; counter reads (which trigger ZipGS delays), and no card speed changes.
;;; Two DOC-timed loops cancel common I/O cost. AppleSqueezer needs longer
;;; loops so both outlast its sound-I/O slowdown interval.
#include "memmap.inc"
              .section cpuinfo, text, root, noreorder
              .public CpuMeasure, CpuText, cpuCard, cpuCache, cpuKHz
              .extern benchOut
CLOCK_KHZ     .equ 787857012           ; 69.8808 Hz * 672 / 1000 * 2^24

CpuMeasure:   php
              sei
              rep #0x30
              phb
              phk
              plb
              ldx ##254
cpuSaveDP:    lda long:TW_DP,x
              sta abs:.word0 (cpuFirmwareDP),x
              dex
              dex
              bpl cpuSaveDP
              jsr abs:.word0 (cpuDetect)
              jsr abs:.word0 (cpuTwBegin)
              lda abs:.word0 (cpuCard)
              cmp ##4
              bne clockShort
              lda ##256
              bra clockFirst
clockShort:   lda ##8
clockFirst:   jsr abs:.word0 (clockPass)
              lda abs:.word0 (clockA)
              sta abs:.word0 (clockQ)
              lda abs:.word0 (clockA+2)
              sta abs:.word0 (clockQ+2)
              lda abs:.word0 (cpuCard)
              cmp ##4
              bne clockShort2
              lda ##768
              bra clockSecond
clockShort2:  lda ##40
clockSecond:  jsr abs:.word0 (clockPass)
              lda abs:.word0 (clockA)
              sec
              sbc abs:.word0 (clockQ)
              sta abs:.word0 (clockB)
              lda abs:.word0 (clockA+2)
              sbc abs:.word0 (clockQ+2)
              sta abs:.word0 (clockB+2)
              bmi clockInvalid
              ora abs:.word0 (clockB)
              beq clockInvalid
              lda abs:.word0 (cpuCard)
              cmp ##4
              bne clockOrdinaryNumerator
              lsr abs:.word0 (clockB+2)
              ror abs:.word0 (clockB)
              lsr abs:.word0 (clockB+2)
              ror abs:.word0 (clockB)
              lda ##.word0 (CLOCK_KHZ*4)
              sta abs:.word0 (clockA)
              lda ##((CLOCK_KHZ*4) >> 16)
              bra clockNumerator
clockOrdinaryNumerator:
              lda ##.word0 CLOCK_KHZ
              sta abs:.word0 (clockA)
              lda ##(CLOCK_KHZ >> 16)
clockNumerator:
              sta abs:.word0 (clockA+2)
              jsr abs:.word0 (cpuDivide)
              lda abs:.word0 (clockA+2)
              bne clockInvalid
              lda abs:.word0 (clockA)
              bra clockResult
clockInvalid: lda ##0
clockResult:  sta abs:.word0 (cpuKHz)
              jsr abs:.word0 (cpuTwEnd)
              ldx ##254
cpuRestoreDP: lda abs:.word0 (cpuFirmwareDP),x
              sta long:TW_DP,x
              dex
              dex
              bpl cpuRestoreDP
              plb
              plp
              rtl

clockPass:    sta abs:.word0 (clockIterations)
              sep #0x20
              jsr abs:.word0 (clockRamp)
              sta abs:.word0 (clockLast)
clockEdge:    jsr abs:.word0 (clockRamp)
              cmp abs:.word0 (clockLast)
              beq clockEdge
              sta abs:.word0 (clockLast)
              stz abs:.word0 (clockSteps)
              ldx ##0
clockOuter:   ldy abs:.word0 (clockIterations)
clockInner:   nop
              nop
              nop
              nop
              nop
              nop
              nop
              nop
              dey
              bne clockInner
              inx
              jsr abs:.word0 (clockRamp)
              cmp abs:.word0 (clockLast)
              beq clockOuter
              pha
              sec
              sbc abs:.word0 (clockLast)
              clc
              adc abs:.word0 (clockSteps)
              sta abs:.word0 (clockSteps)
              pla
              sta abs:.word0 (clockLast)
              lda abs:.word0 (clockSteps)
              cmp #17
              bcc clockOuter
              rep #0x20
              and ##255
              xba
              sta abs:.word0 (clockA+2)
              stz abs:.word0 (clockA)
              stx abs:.word0 (clockB)
              stz abs:.word0 (clockB+2)
              jmp abs:.word0 (cpuDivide)
clockRamp:    lda long:SOUNDCTL
              bmi clockRamp
              lda long:SYSTEM_VOLUME
              and #15
              ora #0x20
              sta long:SOUNDCTL
              lda #0x7f
              sta long:SOUNDADRL
              jsr abs:.word0 (clockRead)
clockRead:    lda long:SOUNDCTL
              bmi clockRead
              lda long:SOUNDDATA
              rts

;;; The result records are in the menu bank; this formatter keeps its own
;;; strings and scratch in its code bank and writes no more than 16 bytes per row.
CpuText:      phb
              phk
              plb
              ldx ##112
              lda abs:.word0 (cpuCard)
              asl a
              tay
              lda abs:.word0 (cpuNames),y
              tay
              jsr abs:.word0 (cpuCopy)
              ldx ##128
              lda abs:.word0 (cpuKHz)
              beq cpuUnknown
              clc
              adc ##5
              sta abs:.word0 (clockA)
              stz abs:.word0 (clockA+2)
              lda ##10
              sta abs:.word0 (clockB)
              stz abs:.word0 (clockB+2)
              phx
              jsr abs:.word0 (cpuDivide)
              plx
              lda abs:.word0 (clockA)
              sta abs:.word0 (decimalValue)
              lda ##1
              sta abs:.word0 (decimalPoint)
              jsr abs:.word0 (cpuDecimal)
              ldy ##.word0 (cpuMHz)
              bra cpuSpeedText
cpuUnknown:   ldy ##.word0 (cpuNA)
cpuSpeedText: jsr abs:.word0 (cpuCopy)
              ldx ##144
              lda abs:.word0 (cpuCache)
              beq cpuCacheNone
              sta abs:.word0 (decimalValue)
              stz abs:.word0 (decimalPoint)
              jsr abs:.word0 (cpuDecimal)
              ldy ##.word0 (cpuKB)
              bra cpuCacheText
cpuCacheNone: ldy ##.word0 (cpuNA)
cpuCacheText: jsr abs:.word0 (cpuCopy)
              plb
              rtl
cpuCopy:      sep #0x20
cpuCopyByte:  lda abs:0,y
              sta long:benchOut,x
              beq cpuCopyDone
              iny
              inx
              bra cpuCopyByte
cpuCopyDone:  rep #0x20
              rts
cpuDecimal:   ldy ##0
              stz abs:.word0 (decimalStarted)
decimalDigit: stz abs:.word0 (decimalDigitValue)
              lda abs:.word0 (decimalValue)
decimalSubtract:
              cmp abs:.word0 (decimalPowers),y
              bcc decimalHave
              sbc abs:.word0 (decimalPowers),y
              inc abs:.word0 (decimalDigitValue)
              bra decimalSubtract
decimalHave:  sta abs:.word0 (decimalValue)
              lda abs:.word0 (decimalDigitValue)
              ora abs:.word0 (decimalStarted)
              bne decimalWrite
              cpy ##8
              beq decimalWrite
              lda abs:.word0 (decimalPoint)
              beq decimalSkip
              cpy ##4
              bcc decimalSkip
decimalWrite: inc abs:.word0 (decimalStarted)
              lda abs:.word0 (decimalDigitValue)
              clc
              adc ##48
              sep #0x20
              sta long:benchOut,x
              rep #0x20
              inx
              cpy ##4
              bne decimalSkip
              lda abs:.word0 (decimalPoint)
              beq decimalSkip
              sep #0x20
              lda #'.'
              sta long:benchOut,x
              rep #0x20
              inx
decimalSkip:  iny
              iny
              cpy ##10
              bcc decimalDigit
              rts

cpuCard:      .word 0
cpuCache:     .word 0
cpuKHz:       .word 0
clockQ:       .long 0
              .byte 0
clockA:       .word 0,0
clockB:       .word 0,0
clockR:       .word 0,0
clockIterations: .word 0
clockLast:    .byte 0
clockSteps:   .byte 0
decimalValue: .word 0
decimalPoint: .word 0
decimalStarted:.word 0
decimalDigitValue:.word 0
decimalPowers:.word 10000,1000,100,10,1
cpuNames:     .word .word0 (cpuNative),.word0 (cpuZip),.word0 (cpuTW),.word0 (cpuTW),.word0 (cpuAS)
cpuNative:    .asciz "None detected"
cpuZip:       .asciz "ZipGS"
cpuTW:        .asciz "TransWarp GS"
cpuAS:        .asciz "AppleSqueezer"
cpuMHz:       .asciz " MHz"
cpuKB:        .asciz " KB"
cpuNA:        .asciz "N/A"

cpuDetect:      php
              sei                           ; (no write between the unlock
              sep     #0x20                 ;   writes)
              lda     #0
              sta     long:cpuCard
              sta     long:(cpuCard+1)
              sta     long:cpuCache
              sta     long:(cpuCache+1)
              lda     long:AS_PRESENT
              cmp     #1
              bne     cpuOtherCard
              lda     #4
              sta     long:cpuCard
              plp
              rts
cpuOtherCard:
              jsr     abs:.word0 bmUnlock
              lda     long:ZIPSLOT
              pha
              eor     #0xff                 ; bits 0-3 (4-7 can follow the
              sta     long:ZIPSLOT          ;   disk motors)
              eor     long:ZIPSLOT
              and     #0x0f
              bne     1$
              lda     1,s
              sta     long:ZIPSLOT
              eor     long:ZIPSLOT
              and     #0x0f
              bne     1$
              lda     #1
              sta     long:cpuCard
              lda     long:ZIPSTAT          ; the cache
              rep     #0x20
              and     ##3
              tax
              sep     #0x20
              lda     long:bmCacheKB,x
              sta     long:cpuCache
1$:           pla
              sta     long:ZIPSLOT
              lda     #0xa5
              sta     long:ZIPLOCK
              lda     long:TW_ID
              cmp     #'T'
              bne     9$
              lda     long:(TW_ID+1)
              cmp     #'W'
              bne     9$
              lda     long:(TW_ID+2)
              cmp     #'G'
              bne     9$
              lda     long:(TW_ID+3)
              cmp     #'S'
              bne     9$
              lda     long:cpuCard
              ora     #2
              sta     long:cpuCard
              rep     #0x30                 ; the cache (its firmware: native
              phb                           ;   mode, 16-bit registers)
              phd
              lda     ##0x0a00
              tcd
              jsl     long:TW_CACHESIZE
              pld
              plb
              sta     long:cpuCache
9$:           plp
              rts
bmCacheKB:    .byte   8, 16, 32, 64


bmUnlock:     lda #0x5a
              sta long:ZIPLOCK
              sta long:ZIPLOCK
              sta long:ZIPLOCK
              sta long:ZIPLOCK
              rts

cpuDivide:     stz abs:.word0 (clockR)
              stz abs:.word0 (clockR + 2)
              ldy ##32
divideBit:    asl abs:.word0 (clockA)
              rol abs:.word0 (clockA + 2)
              rol abs:.word0 (clockR)
              rol abs:.word0 (clockR + 2)
              lda abs:.word0 (clockR + 2)
              cmp abs:.word0 (clockB + 2)
              bcc divideNext
              bne divideSub
              lda abs:.word0 (clockR)
              cmp abs:.word0 (clockB)
              bcc divideNext
divideSub:    lda abs:.word0 (clockR)
              sec
              sbc abs:.word0 (clockB)
              sta abs:.word0 (clockR)
              lda abs:.word0 (clockR + 2)
              sbc abs:.word0 (clockB + 2)
              sta abs:.word0 (clockR + 2)
              inc abs:.word0 (clockA)
divideNext:   dey
              bne divideBit
              rts


;;; Calibrate the selected fast clock even when TWGS normally slows while
;;; I is set. Restore the exact entry configuration before timed frames.
;;; Firmware gets a saved/restored scratch page, native mode and 16-bit A/X/Y.
cpuTwBegin:   lda abs:.word0 (cpuCard)
              bit ##2
              beq cpuTwDone
              phd
              phb
              lda ##0x0a00
              tcd
              jsl long:TW_GETCONFIG
              sta long:cpuTwConfig
              jsl long:TW_DISABLEIRQ
              plb
              pld
cpuTwDone:    rts
cpuTwEnd:     lda abs:.word0 (cpuCard)
              bit ##2
              beq cpuTwDone
              phd
              phb
              lda ##0x0a00
              tcd
              lda long:cpuTwConfig
              jsl long:TW_SETCONFIG
              plb
              pld
              rts
cpuTwConfig:  .word 0
cpuFirmwareDP:.space 256,0
