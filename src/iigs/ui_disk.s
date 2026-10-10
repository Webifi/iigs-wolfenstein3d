;;; Home disk access for the front end: find a disk of this set in either drive,
;;; ask for it when it is out, read picture lumps into bank $3F staging, stream
;;; the title and show the busy sign for any step that runs past a second (0.4 second from a floppy).
;;; Settings and saved games stay on the home disk named by BI_HOME_DISK,
;;; which is in the drive when boot ends. No edition-specific disk number
;;; is assumed. The slot names live
;;; in the settings image the loader already read, so the Save and Load screens
;;; do not ask for a disk. A slot transfer on one drive ejects the play disk,
;;; asks for the home disk, then asks for that play disk again. Two drives leave
;;; the home disk where it is.
;;; Block calls go through UiBlock in bank 0 (ui_bridge.s). Picture chunks are
;;; resident from boot; their copy/decode never enters firmware or masks IRQs.
#include "memmap.inc"
#include "frontend.inc"
#include "logic.inc"
#include "campaign.inc"
              .extern EnsureUIAssets
              .section menucode, text, root, noreorder
              .extern ProgressAdd, ProgressPlan, ProgressFinish, ProgressPixels, ProgressRatio, progressTotal, progressDone, progressExtra
              .public busyKind
              .extern bootComplete, MenuDimOpen, MenuDimClose, MenuPrepare, MenuReveal
              .public DiskInit, FindHomeDisk, NeedHomeDisk, ReleaseDisk, ReadBlocks, LoadLump, diskHeld
              .extern homeDisk
              .public strInsert
              .public BusyShow, BusyBar, BusyHide, UiTime, UiDiv16, UiMul16, ReadBlockTo
              .extern viewKeep, currentSong, floorSong
              .public CheckDisk, ReadHeader, StreamScreen, busyShown, BusyForget, StartSign, StartSignStep, SignUp, UiLoadSign, UiLoadDone, FetchMainMenu
              .extern UiBlock, blkCmd, blkUnit, blkBuf, blkNum, blkDriver, blkFast, UiEject, spEntry
              .extern UiGetTime, UiDrain, lumpTable, PollKey, IsFloppy, screenBlack, UiInitFlash, levelIndex
              .extern BeginUpdate, EndUpdate, busyProgress
              .extern CopyMenuBlocks, PalBlack, menuDim, GrayRect
              .extern DrawList, FillRect, SaveBox, RestoreBox, DrawStrCenter, DrawBusyText, WaitBlank, fadeBase, StreamCachedPicture

U_SAVED       .equ 0x60                   ; the variables U_X to U_ENT of the menu page: all the sign code uses
BUSY_TICS     .equ 70                     ; a read from the hard disk that takes a second gets the sign
BUSY_TICS_FLOPPY .equ 28                  ;   and one from a floppy (a block takes a tenth of a second) after 0.4 seconds

;;; A = low word of the tic count (the DOC clock polls here as well)
UiTime:       jsl long:UiGetTime
              rts

;;; Carry clear when the boot loader left usable drive information.
DiskInit:     lda long:BOOTINFO
              cmp ##0x4244
              bne noInfo
              lda long:BI_DRIVER
              sta long:blkDriver
              lda long:BOOTINFO + 6
              sta long:spEntry
              clc
              rts
noInfo:       sec
              rts

;;; Read block U_BLK of drive U_UNIT to the bank 0 buffer U_BUF. Up to three
;;; tries, because the first read after a disk change reports the change.
ReadBlockTo:  stz abs:.word0 (readFast)
              jsr abs:.word0 (ReadBlockRaw)
              bcs readRawFail
              jsl long:UiDrain
              clc
readRawFail:  rts

;;; The same without the check for ADB data and with the flags of ReadBlocks for the firmware state.
ReadBlockRaw: ldy ##3
readTry:      phy
              lda dp:U_UNIT
              and ##255
              xba
              ora ##1
              sta long:blkCmd
              lda dp:U_BLK
              sta long:blkNum
              lda dp:U_BUF
              sta long:blkBuf
              lda abs:.word0 (readFast)
              sta long:blkFast
              jsl long:UiBlock
              ply
              bcc readOk
              dey
              bne readTry
              sec
              rts
readOk:       clc
              rts

;;; The header of drive U_UNIT: carry clear when it is disk diskWant of this
;;; build. diskSaw is that disk's number when the header is ours.
CheckDisk:    stz abs:.word0 (diskOther)
              lda ##1
              sta dp:U_BLK
              lda ##HDR
              sta dp:U_BUF
              jsr abs:.word0 (ReadBlockTo)
              bcs checkFail
              lda long:HDR
              cmp ##0x4f57                 ; "WOLFGS"
              bne checkFail
              lda long:HDR + 2
              cmp ##0x464c
              bne checkFail
              lda long:HDR + 4
              cmp ##0x5347
              bne checkFail
              lda ##1
              sta abs:.word0 (diskOther)   ; ours, but maybe not the disk we want
              lda long:HDR + 6
              and ##255
              sta abs:.word0 (diskSaw)
              cmp abs:.word0 (diskWant)
              bne checkFail
              lda long:HDR_BUILD
              cmp long:BI_BUILD
              bne checkFail
              lda long:HDR_BUILD + 2
              cmp long:BI_BUILD + 2
              bne checkFail
              stz abs:.word0 (diskOther)
              clc
              rts
checkFail:    sec
              rts

;;; Look for the home disk. findWant looks for diskWant, which NeedDisk has set.
FindHomeDisk: jsr abs:.word0 (HomeDisk)
              sta abs:.word0 (diskWant)
findWant:     stz abs:.word0 (diskSaw)
              stz abs:.word0 (otherUnits)
              lda long:BI_UNIT
              and ##255
              sta dp:U_UNIT
              jsr abs:.word0 (CheckDisk)
              jsr abs:.word0 (ProbeProgress)
              bcc foundDisk
              lda abs:.word0 (diskOther)
              sta abs:.word0 (otherUnits)    ; the first drive holds another disk of ours
              lda dp:U_UNIT
              eor ##0x80
              sta dp:U_UNIT
              jsr abs:.word0 (CheckDisk)
              jsr abs:.word0 (ProbeProgress)
              bcc foundDisk
              lda abs:.word0 (diskOther)
              beq noOther
              lda abs:.word0 (otherUnits)
              ora ##2                        ; the second drive too
              sta abs:.word0 (otherUnits)
noOther:      sec
              rts
ProbeProgress:
              php
              pha
              lda abs:.word0 (busyShown)
              beq probeProgressOut
              lda abs:.word0 (busyKind)
              bne probeProgressOut
              lda abs:.word0 (progressTotal)
              beq probeProgressOut
              lda ##8
              jsl long:ProgressAdd
probeProgressOut:
              pla
              plp
              rts
foundDisk:    clc
              rts

;;; The drives that hold another disk of this game go out, so the player
;;; sees which disk to put in. Only floppies: the unit says the 3.5-inch slot.
EjectOthers:  lda long:BI_UNIT
              and ##0x70
              cmp ##0x50
              bne ejectDone
              lda abs:.word0 (otherUnits)
              bit ##1
              beq ejectSecond
              lda long:BI_UNIT
              jsr abs:.word0 (ejectUnit)
ejectSecond:  lda abs:.word0 (otherUnits)
              bit ##2
              beq ejectDone
              lda long:BI_UNIT
              eor ##0x80
              jsr abs:.word0 (ejectUnit)
ejectDone:    stz abs:.word0 (otherUnits)
              rts
ejectUnit:    and ##0x80                     ; SmartPort unit 1 or 2 from the drive bit
              beq ejectOne
              lda ##2
              bra ejectCall
ejectOne:     lda ##1
ejectCall:    jsl long:UiEject
              rts

;;; The play disk goes back in after a home disk transfer. Nothing was ejected
;;; when the home disk was already in a drive, so this waits for no one. The disk
;;; asked for is the floor disk of the floor in play (homeDisk), which the
;;; play reads; the disk seen before the transfer can be the episode disk.
ReleaseDisk:  lda abs:.word0 (diskHeld)
              beq relOut
              stz abs:.word0 (diskEsc)
              lda long:homeDisk
              bne relAsk
              lda abs:.word0 (diskHeld)
relAsk:       jsr abs:.word0 (NeedDisk)
              stz abs:.word0 (diskHeld)
relOut:       clc
              rts

;;; A = the home disk (BI_HOME_DISK without its bit 7, the boot's play cache mark).
HomeDisk:     lda long:BI_HOME_DISK
              and ##0x7f
              rts

;;; The home disk in a drive. Esc gives up (carry set) and ReleaseDisk asks for
;;; the play disk again. NeedDisk asks for the disk in A and does not eat a key
;;; when diskEsc is clear, so the menu key that follows the transfer stays.
NeedHomeDisk: lda ##1
              sta abs:.word0 (diskEsc)
              jsr abs:.word0 (HomeDisk)
NeedDisk:     sta abs:.word0 (diskWant)
              jsr abs:.word0 (findWant)
              bcc needDone
              lda long:BI_DISKS
              and ##255
              cmp ##2
              bcc needFail                 ; one volume: nothing to ask for
              jsr abs:.word0 (EjectOthers)
              jsr abs:.word0 (HomeDisk)
              cmp abs:.word0 (diskWant)
              bne needAsk                  ; not a home disk transfer
              lda abs:.word0 (diskSaw)
              beq needAsk
              cmp abs:.word0 (diskWant)
              beq needAsk
              sta abs:.word0 (diskHeld)    ; the disk the drive was holding
needAsk:      jsr abs:.word0 (promptOn)
              lda ##2
              jsr abs:.word0 (BusyShow)
needWait:     jsr abs:.word0 (UiTime)
              sta dp:U_T4
needPoll:     lda abs:.word0 (diskEsc)
              beq needNoKey
              jsr abs:.word0 (PollKey)
              cmp ##0xffff
              beq needNoKey
              cmp ##K_ESC
              beq needCancel
needNoKey:    jsr abs:.word0 (UiTime)
              sec
              sbc dp:U_T4
              cmp ##35
              bcc needPoll
              jsr abs:.word0 (findWant)
              bcc needFound
              jsr abs:.word0 (EjectOthers)
              bra needWait
needFound:    jsr abs:.word0 (promptOff)
              lda abs:.word0 (progressTotal)
              beq needHidePrompt
              lda ##0
              jsr abs:.word0 (BusyShow)
              lda ##0
              jsl long:ProgressAdd
              bra needDone
needHidePrompt:
              jsr abs:.word0 (BusyHide)
needDone:     clc
              rts
needCancel:   jsr abs:.word0 (promptOff)
              jsr abs:.word0 (BusyHide)
needFail:     sec
              rts

;;; INSERT DISK n on the text page (row 18, column 4), the line the loader and
;;; tools/test_media.py already watch. The busy sign draws the same words.
promptOn:     sep #0x20
              lda abs:.word0 (diskWant)
              clc
              adc #'0'
              sta abs:.word0 (strInsert + 12)
              ldx ##0
promptPut:    lda abs:.word0 (strInsert),x
              ora #0x80
              sta long:DISK_PROMPT,x
              inx
              cpx ##13
              bcc promptPut
              rep #0x20
              rts
promptOff:    sep #0x20
              ldx ##0
              lda #0xa0
promptBlank:  sta long:DISK_PROMPT,x
              inx
              cpx ##13
              bcc promptBlank
              rep #0x20
              rts

;;; Loading and disk prompts occupy a contained box over the paused picture.
              .extern BusyPanel, BusySaveRows, BusyRestoreRows, BusyBegin, BusyEndDraw, BusyReveal, BlackPixels
              .extern BusyHoldPal, BusyReleasePal
BusyShow:     sta abs:.word0 (busyKind)
              lda abs:.word0 (bootComplete)
              bne busyEnabled
              rts
busyEnabled:  jsl long:PsychedShow
              bcc busyOrdinary
              rts
busyOrdinary: lda abs:.word0 (busyShown)
              beq busyFirst
              jmp abs:.word0 (busyRedraw)
busyFirst:    jsl long:BusyHoldPal
              lda abs:.word0 (screenBlack)
              sta abs:.word0 (busyDark)
              beq busySnapshot
              jsl long:BlackPixels        ; discard an already faded-out page
busySnapshot:
              jsr abs:.word0 (BusyBounds)
              jsr abs:.word0 (SaveBox)
              jsl long:BusySaveRows
busyRedraw: jsr abs:.word0 (BusyBounds)
              jsl long:BusyBegin
              jsl long:BusyPanel
              lda abs:.word0 (busyKind)
              asl a
              tax
              lda abs:.word0 (busyText),x
              sta dp:U_STR
              lda ##160
              sta dp:U_X
              lda ##87
              ldx abs:.word0 (busyKind)
              cpx ##3
              bne busyLabelY
              lda ##90
busyLabelY:   sta dp:U_Y
              stz dp:U_FONT
              lda ##C_GRAY
              sta dp:U_C
              jsl long:DrawBusyText
              jsl long:BusyEndDraw
              jsl long:EndUpdate
              lda ##0
              sta long:busyProgress
              lda ##1
              sta abs:.word0 (busyShown)
              jsl long:BusyReveal
busySuppressed: rts

;;; The bar at U_DONE of U_TOTAL. Nothing shows when there is no sign.
BusyBar:      lda abs:.word0 (busyShown)
              beq barDone
              lda dp:U_DONE
              ldx dp:U_TOTAL
              jsr abs:.word0 (ProgressRatio)
              jsr abs:.word0 (ProgressPixels)
barDone:      rts

;;; The sign goes without the screen under it coming back: the next picture replaces it (a game that
;;; starts, a demo). The next BusyHide must not put old pixels over that picture.
BusyForget:   jsl long:PsychedForget
              jsl long:ProgressFinish
              jsl long:BusyReleasePal
              stz abs:.word0 (progressTotal)
              stz abs:.word0 (progressExtra)
              stz abs:.word0 (busyShown)
              stz abs:.word0 (busyDark)
busyForgot:   rts

;;; Main lettering and cursor are already resident.
FetchMainMenu: rts


StartSign:    pha
              phx
              txa
              cmp long:levelIndex
              bne startNone
              jsr abs:.word0 (SignUp)
startNone:    plx
              pla
              rts

              .extern PsychedShow, PsychedForget
              .public SignUpLong, BusyForgetLong
SignUpLong:   jsr abs:.word0 (SignUp)
              rtl
BusyForgetLong:
              jsr abs:.word0 (BusyForget)
              rtl

;;; The resident reset reserves setup, optional song upload and the first view.
SignUp:       stz abs:.word0 (progressDone)
              lda ##240
              pha
              lda long:currentSong
              cmp long:floorSong
              beq signSameSong
              pla
              clc
              adc ##260
              bra signBudget
signSameSong: pla
signBudget:   jsl long:ProgressPlan
              stz dp:U_DONE
              lda ##3
              sta dp:U_TOTAL
              lda ##0
              jmp abs:.word0 (BusyShow)

;;; Completion belongs to the outer load, after all preparation.
StartSignStep: jsl long:ProgressFinish
              rts

;;; Event-only loading signs: 1 ensures the sign, 2 leaves completion to the caller,
;;; 3/4 bracket a song; 5 begins floor I/O. Step 0 stays silent.
;;; The boot latch suppresses all signs until initial loading is complete.
UiLoadSign:   php
              rep #0x20
              pha
              cmp ##2
              beq loadSignFinished
              cmp ##0
              beq loadSignOff
              lda long:bootComplete
              bne loadSignEnabled
loadSignOff:  pla
              plp
              rtl
loadSignFinished:
              bra loadSignOff
loadSignEnabled: pla
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              phk
              plb
              sta abs:.word0 (signStep)
              ldx ##UI_DP
              ldy ##.word0 (signSave)
              lda ##U_SAVED - 1
              .byte 0x54, 0x3f, 0x00         ; MVN: bank 0 to bank $3F
              lda ##UI_DP
              tcd
              lda abs:.word0 (signStep)
              cmp ##5
              beq loadSignRead
              cmp ##3
              bcs loadSignSong
              cmp ##2
              bcc loadSignNew
              jsr abs:.word0 (BusyForget)
loadSignNew:  lda abs:.word0 (busyShown)
              bne loadSignUp
              jsr abs:.word0 (SignUp)
loadSignUp:   bra loadSignBack
loadSignRead: lda abs:.word0 (busyShown)
              bne loadSignBack
              jsr abs:.word0 (SignUp)
              lda ##8192
              jsl long:ProgressPlan
              bra loadSignBack
loadSignSong: bne songEnd
              lda abs:.word0 (busyShown)
              bne loadSignBack                ; the sign of a load is up: it stays
              lda ##1
              sta abs:.word0 (songSign)
              jsr abs:.word0 (SignUp)
              lda ##260
              jsl long:ProgressPlan
              bra loadSignBack
songEnd:      lda abs:.word0 (songSign)
              beq loadSignBack
              stz abs:.word0 (songSign)
              jsr abs:.word0 (BusyHide)
loadSignBack: ldx ##.word0 (signSave)
              ldy ##UI_DP
              lda ##U_SAVED - 1
              .byte 0x54, 0x00, 0x3f         ; MVN: bank $3F to bank 0
              pld
              plb
              ply
              plx
              pla
              plp
              rtl

;;; JSL from the game when the screen that follows is its own: the sign stays on the old one.
UiLoadDone:   php
              rep #0x30
              pha
              phb
              phk
              plb
              lda abs:.word0 (progressExtra)
              bne loadDonePending
              jsr abs:.word0 (BusyForget)
loadDonePending:
              plb
              pla
              plp
              rtl

BusyHide:     jsl long:ProgressFinish
              stz abs:.word0 (progressTotal)
              stz abs:.word0 (progressExtra)
              lda abs:.word0 (busyShown)
              beq hideDone
              lda abs:.word0 (busyDark)
              beq hideBox
              jsl long:PalBlack
hideBox: jsr abs:.word0 (BusyBounds)
              jsr abs:.word0 (RestoreBox)
              jsl long:BusyRestoreRows
              jsl long:BusyReleasePal
              stz abs:.word0 (busyShown)
hideDone:     rts

BusyBounds:   lda ##BOX_X
              sta dp:U_X
              lda ##BOX_Y
              sta dp:U_Y
              lda ##BOX_W
              sta dp:U_W
              lsr a
              sta dp:U_WB
              lda ##BOX_H
              sta dp:U_H
              rts

;;; A * X (both below 65536 / the other) as a 16-bit result in A.
UiMul16:      sta dp:U_T0
              stx dp:U_T1
              stz dp:U_T2
mulLoop:      lda dp:U_T1
              beq mulDone
              lsr a
              sta dp:U_T1
              bcc mulSkip
              lda dp:U_T2
              clc
              adc dp:U_T0
              sta dp:U_T2
mulSkip:      asl dp:U_T0
              bra mulLoop
mulDone:      lda dp:U_T2
              rts

;;; A / X: quotient in A, remainder in X (X not 0).
UiDiv16:      sta dp:U_T0
              stx dp:U_T1
              stz dp:U_T2                  ; remainder
              ldy ##16
divLoop:      asl dp:U_T0
              rol dp:U_T2
              lda dp:U_T2
              cmp dp:U_T1
              bcc divSkip
              sbc dp:U_T1
              sta dp:U_T2
              inc dp:U_T0
divSkip:      dey
              bne divLoop
              ldx dp:U_T2
              lda dp:U_T0
              rts

;;; Read U_CNT blocks from U_BLK of drive U_UNIT to bank U_DBNK at U_DOFF.
;;; The busy sign comes up if this runs past BUSY_TICS or BUSY_TICS_FLOPPY, unless U_NOSIGN.
ReadBlocks:   stz dp:U_DONE
              lda dp:U_CNT
              sta dp:U_TOTAL
              jsr abs:.word0 (UiTime)
              sta dp:U_START
              jsr abs:.word0 (IsFloppy)
              lda ##BUSY_TICS
              bcc readLimit
              lda ##BUSY_TICS_FLOPPY
readLimit:    sta abs:.word0 (busyLimit)
readNext:     lda dp:U_CNT
              bne readStart
              jmp abs:.word0 (readFinished)
readStart:    ldx ##0                       ; the firmware state is checked before the first block
              lda dp:U_DONE                 ;   and kept after the last
              beq readFirst
              ldx ##1
readFirst:    lda dp:U_CNT
              cmp ##1
              beq readLast
              txa
              ora ##2
              tax
readLast:     stx abs:.word0 (readFast)
              lda ##BUF
              sta dp:U_BUF
              jsr abs:.word0 (ReadBlockRaw)
              bcc readGot
              jmp abs:.word0 (readFailed)
readGot:      lda dp:U_DONE
              and ##7
              bne readNoDrain
              jsl long:UiDrain              ; the ADB data that came while the firmware had the interrupts
readNoDrain:  sep #0x20
              lda dp:U_DBNK
              sta abs:.word0 (copyMvn + 1)
              rep #0x20
              ldx ##BUF
              ldy dp:U_DOFF
              lda ##511
copyMvn:      .byte 0x54, 0x00, 0x00       ; MVN: destination bank patched, from bank 0
              phk
              plb
              sty dp:U_DOFF
              inc dp:U_BLK
              inc dp:U_DONE
              dec dp:U_CNT
              lda dp:U_NOSIGN
              beq readSign
              jmp abs:.word0 (readNext)
readSign:     lda abs:.word0 (busyShown)
              bne readBar
              lda dp:U_CNT                  ; no sign for the last block: it would only flash
              beq readGoOn
              jsr abs:.word0 (UiTime)
              sec
              sbc dp:U_START
              cmp abs:.word0 (busyLimit)
              bcs readShow
readGoOn:     jmp abs:.word0 (readNext)
readShow:     lda ##0
              jsr abs:.word0 (BusyShow)
readBar:      jsr abs:.word0 (BusyBar)
              jmp abs:.word0 (readNext)
readFinished: stz abs:.word0 (readFast)
              jsl long:UiDrain
              jsr abs:.word0 (BusyHide)
              clc
              rts
readFailed:   stz abs:.word0 (readFast)
              jsr abs:.word0 (BusyHide)
              sec
              rts

;;; Load menu lump A (LUMP_*) into the picture staging area, unless what is
;;; there is still that lump (a checksum says so). Bank $3F staging is shared,
;;; so skip decoding only when its current contents still match.
              .extern nativeLumps
              .extern PauseLump
              .public nativeRecord, nativeBank
LoadLump:
              jsl long:EnsureUIAssets
              jsl long:PauseLump             ; the in-game pause reads it into the bank-0 window
              bcs lumpCached
              rts
lumpCached:
              pha
              asl a
              asl a
              tax
              lda long:nativeLumps,x
              sta abs:.word0 (nativeRecord)
              lda long:nativeLumps+2,x
              sta abs:.word0 (nativeBank)
              pla
              ldx abs:.word0 (nativeBank)
              beq loadPackedLump
              clc
              rts
loadPackedLump: asl a
              asl a
              asl a
              tax
              lda abs:.word0 (lumpTable),x
              sta dp:U_BLK
              lda abs:.word0 (lumpTable + 2),x
              sta dp:U_CNT
              lda abs:.word0 (lumpTable + 4),x
              clc
              adc ##.word0 UI_STAGE
              sta dp:U_DOFF
              lda ##0x3f
              sta dp:U_DBNK
              jsl long:CopyMenuBlocks
              rts

StreamScreen: jsl long:StreamCachedPicture
              rts

;;; Read the disk header the last FindHomeDisk left in drive U_UNIT again.
ReadHeader:   lda ##1
              sta dp:U_BLK
              lda ##HDR
              sta dp:U_BUF
              jmp abs:.word0 (ReadBlockTo)

              .section menudata, data, root
              .public busyDark
busyKind:     .word 0
busyShown:    .word 0                     ; 1 while the sign is on (tools/wait_times.py reads it)
busyDark:     .word 0                     ; 1 when the sign came up on a black screen and has to put it back
busyLimit:    .word 0                     ; the tics a read may take before the sign
signSave:     .space U_SAVED              ; the U_ variables of the menu page while UiLoadSign has it
signStep:     .word 0
songSign:     .word 0                     ; 1 when UiLoadSign put the sign up for a song and has to take it off
readFast:     .word 0                     ; the flags of blkFast for the next block of ReadBlocks
lumpQuiet:    .word 0                     ; 1: LoadLump reads with no sign (the menu fetched ahead)
diskOther:    .word 0
otherUnits:   .word 0
diskSaw:      .word 0                 ; number in the drive we just looked at
diskWant:     .word 0                 ; the disk findWant is after
diskHeld:     .word 0                 ; play disk ejected for a home disk transfer
diskEsc:      .word 0                 ; 1: Esc cancels the ask
busyText:     .word .word0 (strLoading), .word0 (strSaving), .word0 (strInsert), .word0 (strHigh)
strLoading:   .asciz "LOADING"
strSaving:    .asciz "SAVING"
strInsert:    .asciz "INSERT DISK 1"
strHigh:      .asciz "NEW HIGH SCORE"

              .section menudata, data, root
nativeRecord: .word 0
nativeBank: .word 0

#include "ui_menu_disk.inc"
