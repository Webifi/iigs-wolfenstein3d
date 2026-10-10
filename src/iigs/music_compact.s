#include "memmap.inc"
#include "progress.inc"
;;; WDP2 cold load: upload raw waves, then expand the compact command head.
;;; DBR=$3E. The wave upload stays under StartMusic's sei. The command head
;;; is RAM only, so interrupts are open for that copy. Returns with A 16-bit
;;; and interrupts off again. No DOC readback.
              .section soundcode, text, root, noreorder
              .public ExpandMusic
              .extern DrainDocInterrupts

ExpandMusic:  rep #0x30
              lda abs:10
              sta long:compactSource
              lda abs:14
              sta long:compactLength
              lda abs:6
              sta long:compactWaveLeft
              cmp ##4096
              bcc compactFirstChunk
              lda ##4096
compactFirstChunk:
              sta long:compactWaveChunk
              tax
              ldy abs:8
              sep #0x20
compactReady: lda long:SOUNDCTL
              bmi compactReady
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x60
              sta long:SOUNDCTL
              lda abs:4
              sta long:SOUNDADRL
              lda abs:5
              sta long:SOUNDADRH
compactWave:  lda long:SOUNDCTL
              bmi compactWave
              lda abs:0,y
              sta long:SOUNDDATA
              iny
              dex
              bne compactWave
              rep #0x20
              jsl long:Progress6
              lda long:compactWaveLeft
              sec
              sbc long:compactWaveChunk
              sta long:compactWaveLeft
              beq compactWaveDone
              cmp ##4096
              bcc compactNextChunk
              lda ##4096
compactNextChunk:
              sta long:compactWaveChunk
              tax
              sep #0x20
              bra compactWave
compactWaveDone:   sep #0x20
compactMode:  lda long:SOUNDCTL
              bmi compactMode
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x20
              sta long:SOUNDCTL
              lda #0
              sta long:SOUNDADRH
              jsl long:DrainDocInterrupts
              cli
              rep #0x20
              lda long:compactSource
              tax
              lda ##2048
              sta long:compactProgressNext
              ldy ##0
compactToken: tya
              cmp long:compactProgressNext
              bcc compactProgressKept
              jsl long:Progress3
              lda long:compactProgressNext
              clc
              adc ##2048
              bcc compactProgressLimit
              lda ##65535
compactProgressLimit:
              sta long:compactProgressNext
              tya
compactProgressKept:
              cmp long:compactLength
              bcc compactMore
              rep #0x30
              sei
              rtl
compactMore:  sep #0x20
              lda abs:0,x
              inx
              cmp #128
              bcs compactMatch
              rep #0x20
              and ##127
              inc a
              pha
              lda 1,s
              dec a
              .byte 0x54, 0x3e, 0x3e         ; MVN: literal run, bank $3E to itself
              pla
              bra compactToken
compactMatch: rep #0x20
              and ##127
              clc
              adc ##3
              pha
              lda abs:0,x
              inx
              inx
              sta long:compactDistance
              phx
              tya
              sec
              sbc long:compactDistance
              tax
              lda 3,s
              dec a
              .byte 0x54, 0x3e, 0x3e         ; MVN: match, forward so overlap repeats
              plx
              pla
              bra compactToken

              .section sounddata, data, root
compactSource: .space 2
compactLength: .space 2
compactDistance: .space 2

              .section sounddata, data, root
compactWaveLeft: .word 0
compactWaveChunk: .word 0
compactProgressNext:.word 0
