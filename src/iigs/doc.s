;;; A silent DOC ramp provides the 70 Hz game clock, independent of
;;; video refresh. Register reads avoid a timer interrupt on the stock CPU.
;;; Oscillator 31 is reserved; the other voices remain halted until needed.

#include "memmap.inc"
              .rtmodel version, "1"
              .rtmodel core, "*"




DOC_OSCS      .equ    32              ; scan rate 894886 Hz / (32 + 2) = 26320 Hz
TIMER_OSC     .equ    31
TIMER_PAGE    .equ    0xff            ; DOC RAM page of the ramp
TIMER_FREQ    .equ    174             ; 26320 Hz * 174 / 65536 = 69.88 steps a second
ALARM_OSC     .equ    30
ALARM_FREQ    .equ    249             ; one pass: 131072 / 249 = 526 samples = 20 ms
ALARM_CTL     .equ    0x0a            ; one-shot, interrupt on, running

;;; One byte of IIGS_DocUpload. 8-bit A.
UPBYTE        .macro
1$:           lda     long:SOUNDCTL
              bmi     1$
              lda     [.tiny _Dp],y
              sta     long:SOUNDDATA
              iny
              .endm

              .section gamedata, data, root
tmSteps:      .space  4               ; ramp steps since IIGS_InitDocTimer
tmLast:       .space  2               ; the ramp byte of the last read
upDoc:        .space  2               ; IIGS_DocUpload: the DOC address
upCount:      .space  2               ;   and the bytes of a page

;;; ***************************************************************************
;;;
;;; IIGS_InitDocTimer - halt all oscillators and start the timer oscillator.
;;;
;;; ***************************************************************************

              .section code, text
              .public IIGS_InitDocTimer
IIGS_InitDocTimer:
              php
              sei
              sep     #0x20
              ldx     ##0xa0                ; control: halt all 32 oscillators
1$:           lda     #1
              jsr     abs:.word0 (docSet)
              inx
              cpx     ##0xc0
              bne     1$

              ;; the ramp: byte i = i, byte 0 = 255 because 0 halts the oscillator
2$:           lda     long:SOUNDCTL
              bmi     2$
              lda     long:SYSTEM_VOLUME         ; the Control Panel volume (system shadow): never force 15
              and     #0x0f
              ora     #0x60                 ; RAM, auto increment
              sta     long:SOUNDCTL
              lda     #0
              sta     long:SOUNDADRL
              lda     #TIMER_PAGE
              sta     long:SOUNDADRH
              lda     #255
              jsr     abs:.word0 (docWrite)
              lda     #1
3$:           jsr     abs:.word0 (docWrite)
              inc     a
              bne     3$

              ldx     ##0xe1                ; oscillators enabled
              lda     #(DOC_OSCS - 1) * 2
              jsr     abs:.word0 (docSet)
              ldx     ##TIMER_OSC           ; frequency
              lda     #TIMER_FREQ
              jsr     abs:.word0 (docSet)
              ldx     ##(0x20 + TIMER_OSC)
              lda     #0
              jsr     abs:.word0 (docSet)
              ldx     ##(0x40 + TIMER_OSC)  ; volume 0
              lda     #0
              jsr     abs:.word0 (docSet)
              ldx     ##(0x80 + TIMER_OSC)  ; wavetable pointer
              lda     #TIMER_PAGE
              jsr     abs:.word0 (docSet)
              ldx     ##(0xc0 + TIMER_OSC)  ; 256-byte table, resolution 7
              lda     #0x07
              jsr     abs:.word0 (docSet)
              ldx     ##(0xa0 + TIMER_OSC)  ; free run, no interrupt, run
              lda     #0
              jsr     abs:.word0 (docSet)
              ldx     ##ALARM_OSC           ; the alarm: halted until
              lda     #ALARM_FREQ           ;   IIGS_Alarm
              jsr     abs:.word0 (docSet)
              ldx     ##(0x20 + ALARM_OSC)
              lda     #0
              jsr     abs:.word0 (docSet)
              ldx     ##(0x40 + ALARM_OSC)
              lda     #0
              jsr     abs:.word0 (docSet)
              ldx     ##(0x80 + ALARM_OSC)
              lda     #TIMER_PAGE
              jsr     abs:.word0 (docSet)
              ldx     ##(0xc0 + ALARM_OSC)  ; 256-byte table, resolution 0
              lda     #0
              jsr     abs:.word0 (docSet)

              jsr     abs:.word0 (readRamp)
              rep     #0x20
              and     ##0x00ff
              sta     abs:.word0 (tmLast)
              stz     abs:.word0 (tmSteps)
              stz     abs:.word0 (tmSteps+2)
              plp
              rtl



;;; ***************************************************************************
;;;
;;; int32_t I_GetTime(void) - time in 1/70 second tics.
;;;
;;; ***************************************************************************

              .public I_GetTime
I_GetTime:    php
              sei
              sep     #0x20
              jsr     abs:.word0 (readRamp)
              rep     #0x20
              and     ##0x00ff
              tax
              sec                           ; steps since the last read
              sbc     abs:.word0 (tmLast)
              and     ##0x00ff
              clc
              adc     abs:.word0 (tmSteps)
              sta     abs:.word0 (tmSteps)
              bcc     1$
              inc     abs:.word0 (tmSteps+2)
1$:           stx     abs:.word0 (tmLast)
              lda     abs:.word0 (tmSteps)
              ldx     abs:.word0 (tmSteps+2)
              plp
              rtl

;;; ***************************************************************************
;;;
;;; IIGS_Alarm arms only oscillator 30. The shared dispatcher owns $E0.
              .public IIGS_Alarm
IIGS_Alarm:   php
              sei
              sep #0x20
              pha
1$:           lda long:SOUNDCTL
              bmi 1$
              lda long:SYSTEM_VOLUME
              and #0x0f
              ora #0x20
              sta long:SOUNDCTL
              lda #(0xa0 + ALARM_OSC)
              sta long:SOUNDADRL
              lda #ALARM_CTL
              jsr abs:.word0 (docWrite)
              pla
              plp
              rtl

;;; IIGS_AlarmOff: the alarm halted (its interrupt waits no more).
              .public IIGS_AlarmOff
IIGS_AlarmOff:
              php
              sei
              sep     #0x20
              rep     #0x10
              ldx     ##(0xa0 + ALARM_OSC)
              lda     #1
              jsr     abs:.word0 (docSet)
              plp
              rtl

;;; docSet: DOC register X = A. 8-bit A, 16-bit X.
docSet:       pha
1$:           lda     long:SOUNDCTL
              bmi     1$
              lda     long:SYSTEM_VOLUME
              and     #0x0f
              ora     #0x20                 ; registers, auto increment
              sta     long:SOUNDCTL
              txa
              sta     long:SOUNDADRL
              pla
              jsr     abs:.word0 (docWrite)
              rts

;;; The Sound GLU has one pending transfer. Address changes and the second
;;; read cannot use its latch until BUSY clears (Apple hardware reference).
docWrite:     pha
1$:           lda     long:SOUNDCTL
              bmi     1$
              pla
              sta     long:SOUNDDATA
              rts
docRead:
1$:           lda     long:SOUNDCTL
              bmi     1$
              lda     long:SOUNDDATA
              rts

;;; readRamp: A = the data register of the timer oscillator. 8-bit A.
readRamp:
1$:           lda     long:SOUNDCTL
              bmi     1$
              lda     long:SYSTEM_VOLUME
              and     #0x0f
              ora     #0x20
              sta     long:SOUNDCTL
              lda     #(0x60 + TIMER_OSC)
              sta     long:SOUNDADRL
              jsr     abs:.word0 (docRead)
              jsr     abs:.word0 (docRead)   ; first result is the old GLU latch
              rts
