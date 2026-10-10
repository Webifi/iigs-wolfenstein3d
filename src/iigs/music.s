#include "memmap.inc"
#include "progress.inc"
;;; Compiled music stream playback on 24 DOC oscillators.
;;; GLU transfers poll BUSY; foreground entry points preserve IRQ state.
              .section soundcode, text, root, noreorder
              .public StartMusic, StopMusic, MusicWake, ScaleMusicVolume, SetMusicVolume
              .extern musicVolume, musicActive, musicLoaded, DrainDocInterrupts, ExpandMusic, ExpandMusicBlocks, j13Timer
REG_FREQLO .equ 0
REG_FREQHI .equ 0x20
REG_VOLUME .equ 0x40
REG_POINTER .equ 0x80
REG_CONTROL .equ 0xa0
REG_SIZE .equ 0xc0

;;; Same BUSY-serialized transfer as docSend, with no call/return shuffling.
;;; The shortest halt/restart path below retains docSend for reset spacing.
SEND          .macro
              xba
1$:           lda long:SOUNDCTL
              bmi 1$
              pla
              sta long:SOUNDADRL
              xba
              sta long:SOUNDDATA
              xba
              lda #0
              xba
              .endm

READY         .macro
1$:           lda long:SOUNDCTL
              bmi 1$
              .endm

StartMusic:   php
              sei
              rep #0x30
              pha
              phx
              phy
              phb
              lda long:musicVolume
              bne startRequested
              jmp abs:.word0 (startDone)
startRequested:
              sep #0x20
              lda #0x3e
              pha
              plb
              rep #0x20
              lda abs:0
              cmp ##0x4457
              bne badMusic
              lda abs:2
              cmp ##0x3350
              bne checkRawPack
              jsr abs:.word0 (haltForExpand)
              jsl long:ExpandMusicBlocks
              bra musicExpanded
checkRawPack:
              cmp ##0x3250
              bne checkHotMagic
              jsr abs:.word0 (haltForExpand)
              jsl long:ExpandMusic
musicExpanded:
              lda ##1
              sta long:musicLoaded
              lda abs:2
checkHotMagic:
              cmp ##0x324d
              bne badMusic
              lda abs:4
              cmp ##MB_STREAM
              bne badMusic
              sep #0x20
              lda abs:13
              cmp #24
              beq startValid
badMusic:     jmp abs:.word0 (startDone)
startValid:   jsr abs:.word0 (haltMusicVoices)
              jsl long:ScaleMusicVolume
              rep #0x30
              lda long:musicLoaded
              beq uploadUncached
              jmp abs:.word0 (waveUploaded)
uploadUncached:
              lda abs:10
              sta long:legacyWaveLeft
              cmp ##4096
              bcc legacyFirstChunk
              lda ##4096
legacyFirstChunk:
              sta long:legacyWaveChunk
              tax
              ldy abs:8
              sep #0x20
uploadReady:  lda long:SOUNDCTL
              bmi uploadReady
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x60
              sta long:SOUNDCTL
              lda #0
              sta long:SOUNDADRL
              lda abs:12
              sta long:SOUNDADRH
uploadWave:   lda long:SOUNDCTL
              bmi uploadWave
              lda abs:0,y
              sta long:SOUNDDATA
              iny
              dex
              bne uploadWave
              rep #0x20
              jsl long:Progress6
              lda long:legacyWaveLeft
              sec
              sbc long:legacyWaveChunk
              sta long:legacyWaveLeft
              beq uploadWaveDone
              cmp ##4096
              bcc legacyNextChunk
              lda ##4096
legacyNextChunk:
              sta long:legacyWaveChunk
              tax
              sep #0x20
              bra uploadWave
uploadWaveDone:   sep #0x20
              rep #0x20
              lda ##1
              sta long:musicLoaded
waveUploaded: lda ##.word0 (legacyMusicWake)
              sta long:MusicWake+1
              sep #0x20
              lda #0x3d
              sta long:MusicWake+3
              lda abs:21
              and #0x80
              beq wakeTargetReady
              rep #0x20
              lda abs:28
              beq wakeTargetReady
              lda ##0x0300
              sta long:MusicWake+1
              sep #0x20
              lda #0x3e
              sta long:MusicWake+3
wakeTargetReady:
              rep #0x20
              lda ##.word0 (batchWake)
              sta long:preparedDispatch+1
              lda abs:21
              and ##16
              beq ordinaryPrepared
              lda ##.word0 (threadWake)
              sta long:preparedDispatch+1
ordinaryPrepared:
              lda abs:21
              and ##2
              beq ordinaryBatches
              lda ##.word0 (fastPairNext)
              bra batchTargetReady
ordinaryBatches:
              lda ##.word0 (batchNext)
batchTargetReady:
              sta long:batchDispatch+1
              ldx ##4
              sep #0x20
initVoice:    lda abs:31
              and #4
              beq initLegacyLevel
              lda #0
              bra initStoreLevel
initLegacyLevel:
              lda #127
initStoreLevel:
              sta abs:MB_LEVEL,x
              lda #0
              sta abs:MB_VDESC,x
              sta abs:MB_VCTL,x
              inx
              cpx ##28
              bcc initVoice
              ldx ##0x5d
              lda #0
              jsr abs:.word0 (musicRegister)
              ldx ##0xdd
              jsr abs:.word0 (musicRegister)
              ldx ##0x9d
              lda #0xff
              jsr abs:.word0 (musicRegister)
              rep #0x20
              stz abs:MB_SPTR
              stz abs:MB_V
              lda ##1
              sta long:musicActive
              sep #0x20
              jsl long:MusicWake
startDone:    rep #0x30
              plb
              ply
              plx
              pla
              plp
              rtl

;;; The 128-entry exponent scale is rebuilt only on explicit volume changes.
;;; Header byte 20 is the song's level lift in 1/8-octave steps. The stream keeps
;;; its exponents; each note plays that many steps louder, so the main parts sit
;;; in the upper register range. An exponent under the lift writes register 255.
ScaleMusicVolume:
              php
              rep #0x30
              pha
              phx
              phy
              phb
              sep #0x20
              lda #0x3e
              pha
              plb
              rep #0x20
              lda long:musicVolume
              and ##15
              asl a
              tax
              lda long:masterShift,x
              sta abs:MB_T0
              lda abs:20
              and ##255
              eor ##0xffff
              sec
              adc abs:MB_T0
              sta abs:MB_T0
              ldx ##0
scaleNext:    lda abs:MB_T0
              bmi scaleFull
              lsr a
              lsr a
              lsr a
              cmp ##16
              bcs scaleZero
              tay
              lda abs:MB_T0
              and ##7
              asl a
              phx
              tax
              lda long:mantissa,x
              plx
scaleShift:   dey
              bmi scaleRound
              lsr a
              bra scaleShift
scaleRound:   clc
              adc ##128
              xba
              and ##255
              bra scaleStore
scaleFull:    lda ##255
              bra scaleStore
scaleZero:    lda ##0
scaleStore:   sep #0x20
              sta abs:MB_VSCALE,x
              rep #0x20
              inc abs:MB_T0
              inx
              cpx ##128
              bcc scaleNext
              sep #0x20
              lda abs:31
              and #4
              beq pairScaleDone
              ldx ##0
scalePair:    lda abs:0x100,x
              tay
              lda abs:MB_VSCALE,y
              sta abs:0x200,x
              lda abs:0x180,x
              tay
              lda abs:MB_VSCALE,y
              sta abs:0x280,x
              inx
              cpx ##128
              bcc scalePair
pairScaleDone:
              rep #0x30
              plb
              ply
              plx
              pla
              plp
              rtl

SetMusicVolume:
              php
              sei
              rep #0x30
              pha
              phx
              phy
              phb
              and ##15
              cmp long:musicVolume
              beq volumeDone
              sta long:musicVolume
              cmp ##0
              bne volumeOn
              jsl long:StopMusic
              bra volumeDone
volumeOn:     lda long:musicActive
              bne volumeChange
              jsl long:StartMusic
              bra volumeDone
volumeChange: jsl long:ScaleMusicVolume
              sei
              sep #0x20
              lda #0x3e
              pha
              plb
              ldy ##4
              lda abs:31
              and #4
              beq heldVolume
heldPair:     lda abs:MB_LEVEL,y
              tax
              lda abs:0x200,x
              pha
              tya
              ora #REG_VOLUME
              tax
              pla
              jsr abs:.word0 (musicRegister)
              iny
              lda abs:MB_LEVEL-1,y
              tax
              lda abs:0x280,x
              pha
              tya
              ora #REG_VOLUME
              tax
              pla
              jsr abs:.word0 (musicRegister)
              iny
              cpy ##28
              bcc heldPair
              bra volumeDone
heldVolume:   lda abs:MB_LEVEL,y
              tax
              lda abs:MB_VSCALE,x
              pha
              tya
              ora #REG_VOLUME
              tax
              pla
              jsr abs:.word0 (musicRegister)
              iny
              cpy ##28
              bcc heldVolume
volumeDone:   rep #0x30
              plb
              ply
              plx
              pla
              plp
              rtl

StopMusic:    php
              sei
              rep #0x30
              pha
              phx
              phy
              lda ##0
              sta long:musicActive
              sta long:j13Timer
              lda ##.word0 (inactiveMusicWake)
              sta long:MusicWake+1
              sep #0x20
              lda #0x3d
              sta long:MusicWake+3
              ldx ##0xbd
              lda #3
              jsr abs:.word0 (musicRegister)
              jsr abs:.word0 (haltMusicVoices)
              jsl long:DrainDocInterrupts
              rep #0x30
              ply
              plx
              pla
              plp
              rtl
;;; The fast IRQ calls the patched wake entry without testing musicActive.
;;; Disable that entry and its alarm before opening interrupts over RAM decoding.
haltForExpand:
              jsl long:StopMusic
              rep #0x30
              rts
haltMusicVoices:
              sep #0x20
              ldx ##0xa4
haltVoice:    lda #3
              jsr abs:.word0 (musicRegister)
              inx
              cpx ##0xbc
              bcc haltVoice
              rts
musicRegister:pha
registerReady:lda long:SOUNDCTL
              bmi registerReady
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x20
              sta long:SOUNDCTL
              txa
              sta long:SOUNDADRL
              pla
              sta long:SOUNDDATA
              rts

;;; Start/Stop select the active entry or inert return under SEI.
;;; Full banks may use the caller-owned DBR contract recorded in header[30].
MusicWake:    jmp long:inactiveMusicWake
inactiveMusicWake:
              rtl
legacyMusicWake:
              phb
activeWake:   sep #0x20
              lda #0x3e
              pha
              plb
              lda #0
              xba
              ldy abs:MB_SPTR
              lda abs:MB_STREAM,y
              iny
              cmp #0xe0
              bcc alarmRun
              cmp #0xf0
              and #15
              tax
              READY
              lda #29
              sta long:SOUNDADRL
              lda abs:MB_WLO,x
              sta long:SOUNDDATA
              bcs alarmRun
              READY
              lda #61
              sta long:SOUNDADRL
              lda abs:MB_WHI,x
              sta long:SOUNDDATA
alarmRun: READY
              lda #189
              sta long:SOUNDADRL
              lda #10
              sta long:SOUNDDATA
              lda abs:21
              beq next
preparedDispatch:
              jmp abs:.word0 (batchWake)
threadWake:   jsl long:MUSIC_BASE+0x300
              jmp abs:.word0 (wakeEnd)
next:         lda abs:MB_STREAM,y
              cmp #0xd0
              bcc dispatch
              beq extended
              cmp #0xe0
              bne wakeEnd
              ldy ##0
wakeEnd:      sty abs:MB_SPTR
              rep #0x30
              plb
              rtl
dispatch:     iny
              lsr a
              and #0x78
              tax
              lda abs:(MB_STREAM-1),y
              and #15
              clc
              adc #4
              sta abs:MB_V
              jmp (.kbank cmds,x)
extended:     iny
              lda abs:MB_STREAM,y
              iny
              lsr a
              and #0x78
              tax
              lda abs:(MB_STREAM-1),y
              and #15
              clc
              adc #20
              sta abs:MB_V
              jmp (.kbank cmds,x)
cLevDn:       tax
              ora     #REG_VOLUME
              pha
              lda     abs:MB_LEVEL,x
              clc
              adc     #4
              bra     setLev
cLevDn2:      tax
              ora     #REG_VOLUME
              pha
              lda     abs:MB_LEVEL,x
              clc
              adc     #8
              bra     setLev
cLevUp:       tax
              ora     #REG_VOLUME
              pha
              lda     abs:MB_LEVEL,x
              sec
              sbc     #4
              bra     setLev
cLev:         tax
              ora     #REG_VOLUME
              pha
              lda     abs:MB_STREAM,y
              iny
setLev:       sta     abs:MB_LEVEL,x
              tax
              lda     abs:MB_VSCALE,x
              SEND
              brl     next

;;; 0x6v: halt (silence; the next note restarts the table).
cHalt:        tax
              ora     #REG_CONTROL
              pha
              lda     abs:MB_CTLH,x
              SEND
              brl     next

;;; A note: halt (the run below starts the table at its start), [table],
;;; [pitch], level, run; each register only when it changes (a register
;;; write is the cost of the music). 0x3v d p a: the table of descriptor d
;;; from now on; 0x7v p a: the voice's table again (a switch to its loop
;;; changed the pointer and size); 0xCv a: the same with the voice's pitch;
;;; 0x2v p a: the table as it is; 0xAv a: the pitch too. Bit 7 of a: a halt
;;; command stopped the voice (no halt); a level as the voice has: no write.
cNoteC:       sec
              bra     noteT
cNoteP:       tax
              lda     abs:MB_STREAM,y
              iny
              sta     abs:MB_VDESC,x
              txa
cNoteT:       clc                           ; (carry: no pitch follows; the
noteT:        sta     abs:MB_V              ;   table code keeps it)
              tax
              bcc     pitchedLevel
              lda     abs:MB_STREAM,y
              bra     testNoteHalt
pitchedLevel: lda     abs:(MB_STREAM+1),y
testNoteHalt:
              bmi     noteTab
              READY
              txa
              ora     #REG_CONTROL
              sta long:SOUNDADRL
              lda     abs:MB_CTLH,x
              sta long:SOUNDDATA
noteTab: READY
              txa
              ora     #REG_POINTER
              sta long:SOUNDADRL
              lda     abs:MB_VDESC,x
              tax                           ; X = the descriptor
              lda     abs:MB_DPTR,x
              sta long:SOUNDDATA
              READY
              lda     abs:MB_V
              ora     #REG_SIZE
              sta long:SOUNDADRL
              lda     abs:MB_DSIZ,x
              sta long:SOUNDDATA
              lda     abs:MB_DMODE,x
              ldx     abs:MB_V
              ora     abs:MB_CTLR,x
              sta     abs:MB_VCTL,x
              txa
              bcc     notePitch
              bra     noteLevel
cNote:        sta     abs:MB_V
              tax
              lda     abs:(MB_STREAM+1),y
              bmi     1$
              READY
              txa
              ora     #REG_CONTROL
              sta long:SOUNDADRL
              lda     abs:MB_CTLH,x
              sta long:SOUNDDATA
1$:           txa
notePitch:    ora     #REG_FREQLO
              pha
              lda     abs:MB_STREAM,y
              iny
              tax
              lda     abs:MB_PLO,x
              SEND
              READY
              lda     abs:MB_V
              ora     #REG_FREQHI
              sta long:SOUNDADRL
              lda     abs:MB_PHI,x
              sta long:SOUNDDATA
noteLevel:    ldx     abs:MB_V              ; (MB_V + 1 is 0)
              lda     abs:MB_STREAM,y
              iny
              and     #0x7f
              cmp     abs:MB_LEVEL,x
              beq     1$
              sta     abs:MB_LEVEL,x
              READY
              txa
              ora     #REG_VOLUME
              sta long:SOUNDADRL
              lda     abs:MB_LEVEL,x
              tax
              lda     abs:MB_VSCALE,x
              sta long:SOUNDDATA
              ldx     abs:MB_V
1$:           txa
              ora     #REG_CONTROL
              pha
              lda     abs:MB_VCTL,x
              jsr abs:.word0 (docSend)
              brl     next
cNoteS:       sta     abs:MB_V
              tax
              lda     abs:MB_STREAM,y
              bmi     noteLevel
              txa
              ora     #REG_CONTROL
              pha
              lda     abs:MB_CTLH,x
              jsr abs:.word0 (docSend)
              bra     noteLevel
;;; docSend: the address byte under the return, and A the data. Wait until
;;; $C03C bit 7 is clear, then store the address and the data with no poll
;;; between them. The caller loads both before the call, so that work hides
;;; in the previous byte's wait. 8-bit A. A and carry come back; N and Z
;;; do not. B returns zero.
docSend:      pha
docBusy:      lda     long:SOUNDCTL
              bmi     docBusy
              lda     4,s
              sta     long:SOUNDADRL
              pla
              sta     long:SOUNDDATA
              xba                           ; the data, while the return moves
              lda     2,s
              sta     3,s
              lda     1,s
              sta     2,s
              pla                           ; B still holds the data; A is the
              lda     #0                    ;   return's low byte, so clear B
              xba
              rts
;;; ---------------------------------------------------------------------------
;;; Infrequent stream commands: pitch changes, attack-table loops,
;;; waveform pages, and end-of-song handling.
;;; ---------------------------------------------------------------------------

;;; 0x4v p: pitch p. 0x5v p: its low byte only (the high byte is the same).
cPitch:       sta     abs:MB_V
              ora     #REG_FREQLO
              pha
              lda     abs:MB_STREAM,y
              iny
              tax
              lda     abs:MB_PLO,x
              SEND
              READY
              lda     abs:MB_V
              ora     #REG_FREQHI
              sta long:SOUNDADRL
              lda     abs:MB_PHI,x
              sta long:SOUNDDATA
              jmp abs:.word0 (next)
cPitchLo:     ora     #REG_FREQLO
              pha
              lda     abs:MB_STREAM,y
              iny
              tax
              lda     abs:MB_PLO,x
              SEND
              jmp abs:.word0 (next)

;;; 0xBv: the loop of the voice's attack table (its pointer and size).
cSwitch:      lda abs:(MB_STREAM-1),y
              cmp #0xbe
              beq cWavePage
              cmp #0xbf
              beq cRawControl
              lda abs:MB_V
switchVoice:  tax
              ora     #REG_POINTER
              pha
              lda     abs:MB_VDESC,x
              tax
              lda     abs:MB_LPTR,x
              SEND
              READY
              lda     abs:MB_V
              ora     #REG_SIZE
              sta long:SOUNDADRL
              lda     abs:MB_LSIZ,x
              sta long:SOUNDDATA
              jmp abs:.word0 (next)

;;; 0xBE v page: a phase-compatible waveform page, same size and pitch.
;;; Only the pointer changes; the voice keeps its accumulator and descriptor
;;; so a later note can restore the attack using the existing note command.
cWavePage:    lda     abs:MB_STREAM,y
              iny
              clc
              adc #4
              ora     #REG_POINTER
              pha
              lda     abs:MB_STREAM,y
              iny
              SEND
              jmp abs:.word0 (next)

;;; 0xBF v control: a muted voice's output channel. The next ordinary
;;; note still uses its normal channel; no permanent voice-table change.
cRawControl:  lda     abs:MB_STREAM,y
              iny
              cmp #128
              bcs extendedSwitch
              clc
              adc #4
              ora     #REG_CONTROL
              pha
              lda     abs:MB_STREAM,y
              iny
              SEND
              jmp abs:.word0 (next)

extendedSwitch:
              and #31
              clc
              adc #4
              sta abs:MB_V
              brl switchVoice

;;; The end of a song: the next wake is its first again, or (a song that
;;; does not loop) no alarm after this one.
cmds:         ;; 13 live words, stride 8. Only the words touch cache.
              .word   .word0 cLevDn
              .space  6
              .word   .word0 cLev
              .space  6
              .word   .word0 cNote
              .space  6
              .word   .word0 cNoteP
              .space  6
              .word   .word0 cPitch
              .space  6
              .word   .word0 cPitchLo
              .space  6
              .word   .word0 cHalt
              .space  6
              .word   .word0 cNoteT
              .space  6
              .word   .word0 cLevDn2
              .space  6
              .word   .word0 cLevUp
              .space  6
              .word   .word0 cNoteS
              .space  6
              .word   .word0 cSwitch
              .space  6
              .word   .word0 cNoteC


;;; Build-time prepared batches preserve the ordered writes of every voice.
;;; Register auto-increment shares the address setup; BUSY is polled before
;;; every data transfer. The volume cache still supports live master changes.
batchWake:    lda abs:MB_STREAM,y
              iny
              sta abs:MB_T0
              ora #0
              bne batchDispatch
              jmp abs:.word0 (batchDone)
batchDispatch:jmp abs:.word0 (batchNext)
batchNext:    lda abs:MB_STREAM,y
              iny
              cmp #255
              beq batchInline
              tax
              lda abs:MB_PLO,x
              sta abs:MB_V
              lda abs:MB_PHI,x
              sta abs:MB_T0+1
              bra batchType
batchInline:  lda abs:MB_STREAM,y
              iny
              sta abs:MB_V
              lda abs:MB_STREAM,y
              iny
              sta abs:MB_T0+1
batchType:    lda abs:MB_V
              and #0xe0
              cmp #0x40
              beq batchVolumes
              lda abs:MB_T0+1
              tax
              READY
              lda abs:MB_V
              sta long:SOUNDADRL
batchData:    lda abs:MB_STREAM,y
              iny
              sta long:SOUNDDATA
              dex
              beq batchRegisterEnd
              READY
              bra batchData
batchVolumes:
              lda abs:MB_V
              and #31
              tax
              READY
              lda abs:MB_V
              sta long:SOUNDADRL
batchVolume:  lda abs:MB_STREAM,y
              iny
              sta abs:MB_LEVEL,x
              phx
              tax
              lda abs:MB_VSCALE,x
              plx
              sta long:SOUNDDATA
              inx
              dec abs:MB_T0+1
              beq batchEnd
              READY
              bra batchVolume
batchRegisterEnd:
              ; Also covers a generic control batch ending with a halt.
              nop
              nop
              nop
              nop
              nop
              nop
batchEnd:     dec abs:MB_T0
              beq batchDone
              jmp abs:.word0 (batchDispatch)
batchDone:    lda abs:MB_STREAM,y
              cmp #0xe0
              bne batchReturn
              ldy ##0
batchReturn:  jmp abs:.word0 (wakeEnd)

;;; Most batches are adjacent stereo mates. The stream supplies their DOC
;;; address directly; the uncommon count uses the existing descriptor path.
fastPairNext: lda abs:MB_STREAM,y
              iny
              cmp #224
              bne fastPairAddress
              jmp abs:.word0 (batchNext)
fastPairAddress:
              tax
              READY
              txa
              sta long:SOUNDADRL
              and #0xe0
              cmp #0x40
              beq fastPairVolumes
              lda abs:MB_STREAM,y
              iny
              sta long:SOUNDDATA
              READY
              lda abs:MB_STREAM,y
              iny
              sta long:SOUNDDATA
              jmp abs:.word0 (batchRegisterEnd)
fastPairVolumes:
              txa
              and #31
              tax
              lda abs:MB_STREAM,y
              iny
              sta abs:MB_LEVEL,x
              phx
              tax
              lda abs:MB_VSCALE,x
              plx
              sta long:SOUNDDATA
              inx
              READY
              lda abs:MB_STREAM,y
              iny
              sta abs:MB_LEVEL,x
              tax
              lda abs:MB_VSCALE,x
              sta long:SOUNDDATA
              jmp abs:.word0 (batchEnd)

masterShift: .word 128,31,23,19,15,13,11,9,7,6,5,4,3,2,1,0
mantissa: .word 65280,59862,54894,50338,46160,42329,38816,35594

              .section sounddata, data, root
legacyWaveLeft: .word 0
legacyWaveChunk: .word 0
