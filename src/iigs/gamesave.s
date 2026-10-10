#include "memmap.inc"
#include "campaign.inc"
#include "progress.inc"
#include "picture_config.inc"
;;; Eight files on the home disk, WOLF.SAVE0 through WOLF.SAVE7.
;;; SAVE_BLOCKS selects the disk allocation (tools/mkdisk.py SAVE_DATA).
;;; A file contains the header, the
;;; object list, the length of the world stream, the stream, and zeros.
;;; The stream describes bank $30 against the fresh floor that StartFloor
;;; builds before a load (tools/save_format.py is the same format in
;;; Python). Its sections, a bit stream with the low bit first:
;;;   K  the cells a pushwall can write: TILEMAP, MAP0, and MAP1 at a start;
;;;   S  the static slots: same, taken, a dropped item, or raw;
;;;   D  the doors: position, action and tics of a changed door;
;;;   A  the area tables: AREABYPLAYER bits, then changed bytes;
;;;   R  ACTORAT: the fresh actor marks are cleared and a K cell takes its
;;;      new tile, then the cells that still differ;
;;;   G  any other changed word, offset and value (none on a real floor).
;;; The header, objects and stream must fit GS_BLOCKS disk blocks; tools/check_save_bound.py
;;; checks the bound for the selected floors. Floor setup captures its lists
;;; into GS_BASE; the stream is built in GS_WORLD and the
;;; bits that steer it are kept in GS_MARK, GS_SIDES, GS_KBITS and GS_TBITS.
;;; A load reads the file from the home disk before the floor loads (it is in
;;; the drive at the menu): the header into gsHeader, the rest into GS_HOLD.
;;; The floor load then asks for its own disks, and the world goes in from
;;; RAM. GS_HOLD is the sprite projection storage of the paused menu frame
;;; (memmap SAVE_HOLD): no floor load writes it, and PrepareSprites rebuilds
;;; it after the load (projectionCold). The header NeedHomeDisk already read
;;; holds the first block and the stride; the settings block is not part of
;;; this file.
#include "frontend.inc"
#include "logic.inc"
#include "game.inc"
#include "logic_dp.inc"
#include "sight.inc"
              .section flowcode, text, root, noreorder
              .public SaveWorldCore, LoadWorldRead, LoadWorldApply, gsPhaseSave, gsPhaseLoad, gsPhaseDone
              .public saveOpenWord
              .extern SaveProgressSize, SaveNeedHomeDisk, SaveReleaseDisk, SaveFindHome, SaveBusyShow, SaveBusyBar, SaveBusyHide, SaveUiTime, SaveSoundStop, SaveShowNote
              .extern blkCmd, blkBuf, blkNum, UiDrain, UiFwKeep
              .extern strProtected, strWriteError, floorSongs
              .extern UiGetTime, SelectMusic, SyncSaved, gsBuild, gsApply, gsFast, gsSkip
              .extern gsLoadFirst, gsTakeBlock, gsCall, gsEmitBlock, gsWorldLen
              .extern diskHeld
              .extern levelStart, floorSong, currentSong, ratioTable, levelIndex
              .extern levelHeld, levelHeldOn, levelPauseAt, levelPauseOn
              .extern levelSeed, LogicSetupLevel, songPending, projectionCold, StaticSpriteVariant

#ifdef WOLF_SPEAR
GS_MARKC      .equ 0xc0e2                 ; fourteen ratio records
#else
GS_MARKC      .equ 0xc0e1                 ; compact world stream with eight ratio records
#endif
GS_SUM        .equ 2
GS_ELAPSED    .equ 4
GS_SONG       .equ 8
GS_RATIOS     .equ 10
#ifdef WOLF_SPEAR
GS_RATIOSN    .equ CAMPAIGN_RATIO_BYTES
#else
GS_RATIOSN    .equ 64
#endif
#ifdef WOLF_SPEAR
GS_FIX        .equ GS_RATIOS+GS_RATIOSN
#else
GS_FIX        .equ 74
#endif
GS_FIXN       .equ 72                     ; 36 words
GS_LASTSTAT   .equ GS_FIX                 ; gsFixTab's first word is V_laststat
#ifdef WOLF_SPEAR
GS_BUTTONS    .equ GS_FIX+GS_FIXN
#else
GS_BUTTONS    .equ 146
#endif
GS_BUTTONN    .equ 32
#ifdef WOLF_SPEAR
GS_OBJ        .equ GS_BUTTONS+GS_BUTTONN
#else
GS_OBJ        .equ 178
#endif
GS_OBJN       .equ 9600
#ifdef WOLF_SPEAR
GS_NWORLD     .equ GS_OBJ+GS_OBJN                   ; the stream's length in bytes
GS_WORLDAT    .equ GS_NWORLD+2                   ; the stream
#else
GS_NWORLD     .equ 9778                   ; the stream's length in bytes
GS_WORLDAT    .equ 9780                   ; the stream
#endif
#ifdef WOLF_SPEAR
GS_BLOCKS     .equ SAVE_BLOCKS
GS_BYTES      .equ SAVE_BLOCKS*512
#else
GS_BLOCKS     .equ 24
GS_BYTES      .equ 12288
#endif
GS_WORLDMAX   .equ GS_BYTES-GS_WORLDAT
GS_BUSY       .equ 140                    ; two seconds at 70 Hz
GS_SNAPN      .equ 0x6600
#ifdef WOLF_SPEAR
GS_ACT_MAX    .equ GS_ACTS_SIZE/4
#else
GS_ACT_MAX    .equ 320                    ; measured peak 265 (floor 58, hard)
#endif
GS_MAP_MAX    .equ 128                    ; measured peak 119 (floor 51)
GS_DOOR_MAX   .equ 64
GS_PUSHABLE   .equ 98                     ; info plane pushwall (lagent.s:784)
GS_DRCLOSED   .equ 1                      ; DR_CLOSED (lact.s:37)
GS_CODEEND    .equ 253                    ; ACTORAT codes: 0-149 an object,
GS_CODERAW    .equ 254                    ;   254 a raw word, 255 zero
GS_CODEZERO   .equ 255
GS_SIDEBIT    .equ (GS_SIDES-GS_MARK)*8       ; gsBitTest index of GS_SIDES
GS_HOLD       .equ SAVE_HOLD              ; file bytes GS_OBJ on, between read and apply
;;; Granted workspace is $010000-$011FFF only: the capture lists, the four
;;; bit maps (GS_MARK, GS_KBITS, GS_TBITS, GS_SIDES) and the stream.
GS_OWN        .equ 8192

;;; A = slot 0-7. Carry set when the world was not written; the player has
;;; been told why, except when the home disk was declined.
;;; The 3.5 driver stops the tick clock while the song and a gunshot still
;;; own the DOC. Those waits then hold the menu off the slot list. Both are
;;; silenced for the whole call, so the settings write after this returns
;;; still finds the DOC idle. FloorMusic brings the song back on the way
;;; into the floor.
SaveWorldCore: jsr abs:.word0 (gsQuiet)
              jsr abs:.word0 (gsPrepare)
              bcc gsSaveBuild
              jsl long:SaveReleaseDisk
              sec
              rtl
gsSaveBuild:  jsl long:gsBuild
              bcc gsPhaseSave
              lda ##.word0 (strWriteError)
              sta dp:U_STR
              jsl long:SaveShowNote
              jsl long:SaveReleaseDisk
              sec
              rtl
gsPhaseSave:  lda ##2
              sta abs:.word0 (gsCmd)
              jsr abs:.word0 (gsXfer)
              bcc gsSaveEnd
              jsl long:SaveReleaseDisk
              sec
gsSaveEnd:    rtl

;;; A = slot 0-7. At the menu, before the floor loads: the whole file from
;;; the home disk, summed, the header into gsHeader and the rest into GS_HOLD. The
;;; play disk is not asked back here: the floor load asks for its own disks,
;;; and LoadWorldApply asks for the floor disk (ReleaseDisk) when the home disk is
;;; still in the drive. Carry set when the file could not be read or is not
;;; this game's; the note is shown (gsLoadNoted) and the play disk, if one
;;; went out, is asked back.
LoadWorldRead: jsr abs:.word0 (gsQuiet)
              stz abs:.word0 (gsLoadNoted)
              jsr abs:.word0 (gsPrepare)
              bcs gsLoadFail
gsPhaseLoad:  lda ##1
              sta abs:.word0 (gsCmd)
              lda ##0
              sta abs:.word0 (gsBadSum)
              sta abs:.word0 (gsRun)
              jsr abs:.word0 (gsXfer)
              bcs gsReadFail
              lda abs:.word0 (gsKind)
              cmp ##2
              beq gsMissing
              lda long:gsWorldLen
              cmp ##GS_WORLDMAX+1
              bcs gsMissing
              lda abs:.word0 (gsRun)
              cmp abs:.word0 (gsSavedSum)
              beq gsReadDone
              lda ##1
              sta abs:.word0 (gsBadSum)
gsReadDone:   clc
              rtl

;;; StartFloor has built the fresh floor. The world goes in from GS_HOLD;
;;; no disk. A checksum mismatch still applies the world, then gsPenalty. Then the
;;; floor disk, only when the home disk is still in the drive (a load of the floor
;;; in play reads no floor; gsReleaseLoad), before the world is published. Carry
;;; set when the stream does not decode: the fresh floor is built again and the
;;; note is shown (gsLoadNoted).
LoadWorldApply:
gsPhaseApply: jsl long:gsApply
              bcs gsReadAgain
              jsr abs:.word0 (gsReleaseLoad)
              jsl long:SyncSaved
gsWorldRestored:
              clc
              rtl

;;; The fresh floor StartFloor built, with the same rndindex, so a stream
;;; that does not decode leaves no half-applied world under the menu.
gsReadAgain:  lda long:levelSeed
              jsl long:LogicSetupLevel
              lda ##.word0 (gsStrRead)
              sta dp:U_STR
              jsl long:SaveShowNote
              jsr abs:.word0 (gsReleaseLoad)
              lda ##1
              sta abs:.word0 (gsLoadNoted)
              sec
              rtl
gsReadFail:   lda ##.word0 (gsStrRead)
              bra gsLoadNote
gsMissing:    lda ##.word0 (gsStrMissing)
gsLoadNote:   sta dp:U_STR
              jsl long:SaveShowNote
gsLoadFail:   jsl long:SaveReleaseDisk
              lda ##1
              sta abs:.word0 (gsLoadNoted)
              sec
              rtl

;;; The song and a gunshot stop for the disk. A floor song that stays in
;;; bank $3E (currentSong) is marked to start again from RAM when the menu
;;; leaves (FloorMusic), so no song is read back from a floor disk. A (the
;;; slot) is kept.
gsQuiet:      pha
              jsl long:SaveSoundStop
              lda long:currentSong
              cmp long:floorSong
              bne gsQuietDone
              lda ##1
              sta long:songPending
gsQuietDone:  pla
              rts

;;; The home disk, then the block the header recorded for this slot.
gsPrepare:    and ##7
              sta abs:.word0 (gsSlot)
              jsl long:SaveNeedHomeDisk
              bcc gsDisk
              sec
              rts
gsDisk:       lda long:HDR_SAVE
              bne gsLocated
              lda ##.word0 (gsStrMissing)
              sta dp:U_STR
              jsl long:SaveShowNote
              sec
              rts
gsLocated:    ldx abs:.word0 (gsSlot)
              lda ##0
gsMul:        dex
              bmi gsMulDone
              clc
              adc long:HDR_STRIDE
              bra gsMul
gsMulDone:    clc
              adc long:HDR_SAVE
              sta abs:.word0 (gsBlk)
              clc
              rts

;;; gsBlocks blocks, one firmware check before the first and one copy
;;; after the last. A load reads the first block, then follows its mark.
;;; A floppy raises the sign up front. Anything else waits until the step
;;; passes two seconds.
gsXfer:       lda ##0
              sta abs:.word0 (gsBusy)
              stz dp:U_DONE
              lda abs:.word0 (gsBlk)
              sta dp:U_BLK
              jsl long:SaveUiTime
              sta dp:U_START
              lda dp:U_UNIT
              and ##0x70
              cmp ##0x50
              bne gsXferKind
;;; The 3.5-inch driver stops the tick clock for the whole call, so the
;;; two-second check never sees a floppy transfer. Raise the sign first.
              jsl long:UiDrain
              lda abs:.word0 (gsCmd)
              cmp ##2
              beq gsFloppySave
              lda ##0
              bra gsFloppyShow
gsFloppySave: lda ##1
gsFloppyShow: jsl long:SaveBusyShow
              lda ##1
              sta abs:.word0 (gsBusy)
              jsl long:SaveBusyBar
gsXferKind:   lda abs:.word0 (gsCmd)
              cmp ##1
              bne gsXferSave
              jsl long:gsLoadFirst
              bcc gsSizeKnown
              jmp abs:.word0 (gsXferFail)
gsSizeKnown:  jsl long:SaveProgressSize
              jsl long:SaveBusyBar
              bra gsXferBlk
gsXferSave:   lda abs:.word0 (gsBlocks)
              sta dp:U_CNT
              sta dp:U_TOTAL
gsXferBlk:    lda dp:U_CNT
              bne gsXferOne
              jmp abs:.word0 (gsXferStop)
gsXferOne:    lda ##3
              ldx dp:U_DONE
              bne gsSkipMid
              lda ##2
gsSkipMid:    ldx dp:U_CNT
              cpx ##1
              bne gsSkipSet
              lda ##1
gsSkipSet:    sta long:gsSkip
              lda abs:.word0 (gsCmd)
              cmp ##1
              beq gsDrvCall
              jsl long:gsEmitBlock
gsDrvCall:    jsl long:gsCall
              bcc gsDrvOk
              jmp abs:.word0 (gsXferFail)
gsDrvOk:      lda abs:.word0 (gsCmd)
              cmp ##1
              bne gsStep
              jsl long:gsTakeBlock
gsStep:       inc dp:U_BLK
              inc dp:U_DONE
              dec dp:U_CNT
              jsl long:SaveBusyBar
              lda dp:U_DONE
              and ##7
              bne gsClock
              lda dp:U_CNT
              beq gsClock
              jsl long:UiDrain
              lda abs:.word0 (gsBusy)
              beq gsClock
              jsl long:SaveBusyBar
              bra gsXferMore
;;; Eight blocks can still be under two seconds when the last blocks cross
;;; it. Read the clock after every block and raise the sign as soon as it does.
gsClock:      lda abs:.word0 (gsBusy)
              bne gsClockNext
              jsl long:SaveUiTime
              sec
              sbc dp:U_START
              cmp ##GS_BUSY
              bcc gsClockNext
              jsl long:UiDrain
              lda abs:.word0 (gsCmd)
              cmp ##2
              beq gsShowSave
              lda ##0
              bra gsShow
gsShowSave:   lda ##1
gsShow:       jsl long:SaveBusyShow
              lda ##1
              sta abs:.word0 (gsBusy)
              jsl long:SaveBusyBar
gsClockNext:  lda dp:U_CNT
              bne gsXferMore
gsXferStop:   jsl long:UiDrain
gsPhaseDone:  jsl long:SaveBusyHide
              clc
              rts
gsXferMore:   jmp abs:.word0 (gsXferBlk)

gsXferFail:   pha
              lda long:gsSkip
              and ##2
              beq gsFailHide
              jsl long:UiFwKeep
gsFailHide:   jsl long:SaveBusyHide
              pla
              cmp ##0x2b
              bne gsFailKind
              lda ##.word0 (strProtected)
              bra gsFailNote
gsFailKind:   lda abs:.word0 (gsCmd)
              cmp ##1
              beq gsFailRead
              lda ##.word0 (strWriteError)
              bra gsFailNote
gsFailRead:   lda ##.word0 (gsStrRead)
gsFailNote:   sta dp:U_STR
              jsl long:SaveShowNote
              sec
              rts

              .section menudata, data, root
gsSlot:       .word 0
gsBlk:        .word 0
gsBusy:       .word 0
gsCmd:        .word 0
gsKind:       .word 0                     ; 0 this game's file, 2 any other mark
gsBlocks:     .word 0
gsHead:       .word 0                     ; low 16 of the header scratch
              .public gsLoadNoted, gsKind, gsBlocks, gsHead
              .public gsBaseOk
gsLoadNoted:  .word 0
gsBaseOk:     .word 0                     ; 0: fresh-floor lists did not fit
gsBadSum:     .word 0
gsRun:        .word 0                     ; word sum, sum field counted as 0
gsSavedSum:   .word 0
gsStrMissing: .asciz "That saved game cannot be loaded."
gsStrRead:    .asciz "The disk could not be read."

;;; The renderer's map, doors, and pushwall follow the restored bank.
;;; JSL. Direct page and the data bank come back. V_sound is cleared so the
;;; publish does not start a sound.
              .section savecode, text, root, noreorder
              .public SyncSaved, gsBuild, gsApply, gsLoadFirst, gsTakeBlock, gsCall
              .public gsEmitBlock, gsCapture
              .extern doorOrient, doorCells, doorPosition, doorBytes, pwallPosition
              .extern wallDirty, hudDirty, LogicMarkObjects, UseLogicActorVisibility, StopMusic, StartMusic
              .extern LogicPublish, UpdateHUD, RebuildSavedSight, RecountLineRegions, ResetLogicTimers
              .extern UiFwKeep, gsSkip, gsFast, blkCmd, blkBuf, blkNum
              .extern gsWorldOut, gsWorldIn, gsPlaneOf

;;; In savecode (room in both builds; bank 2 like LoadWorldApply, which calls it).
;;; After a Load. When the floor load read its own disks, the home disk is out of the
;;; drives: the disk that went out for the save is not asked back, and the play asks for
;;; its floor disk when it reads a block there (as after a Load at the title). When the
;;; home disk is still in (a Load of the floor in play reads no floor), SaveReleaseDisk.
gsReleaseLoad:lda long:diskHeld
              beq gsReleaseDone
              jsl long:SaveFindHome
              bcc gsReleaseAsk
              lda ##0
              sta long:diskHeld
gsReleaseDone:rts
gsReleaseAsk: jsl long:SaveReleaseDisk
              rts

              .section savecode3, text, root
SyncSaved:    php
              phb
              phd
              rep #0x30
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
              lda ##0x1000
              tcd
              lda ##0xffff
              sta long:LOGIC_BASE+V_sound
              jsl long:ResetLogicTimers
              jsl long:RecountLineRegions
              lda long:LOGIC_BASE+V_doornum
              asl a
              sta abs:.word0 (doorBytes)
;;; The sorted active list lives outside bank $30 and starts empty on a floor.
              ldx ##0
              ldy ##0
gsActiveDoor: cpx abs:.word0 (doorBytes)
              bcs gsActiveDone
              lda long:LOGIC_BASE+DOORACT,x
              cmp ##1                      ; DR_CLOSED
              beq gsActiveNext
              txa
              phx
              tyx
              sta long:ACTIVE_DOORS,x
              plx
              iny
              iny
gsActiveNext: inx
              inx
              bra gsActiveDoor
gsActiveDone: tyx
              lda ##0xffff
              sta long:ACTIVE_DOORS,x
              ldx ##126
gsDoorCopy:   lda long:LOGIC_BASE+DOORVERT,x
              sta abs:.word0 (doorOrient),x
              lda long:LOGIC_BASE+DOORTILE,x
              sta abs:.word0 (doorCells),x
              lda long:LOGIC_BASE+DOORPOS,x
              xba
              and ##255
              sta abs:.word0 (doorPosition),x
              dex
              dex
              bpl gsDoorCopy
              ldx ##4095
gsMap:        lda long:LOGIC_BASE+TILEMAP,x
              and ##255
              beq gsMapStore
              bit ##0x80
              bne gsMapStore
              and ##63
gsMapStore:   sta dp:MULW
              sep #0x20
              sta long:MAP,x
              lda #0
              sta long:OBJECT_MARKERS,x
              rep #0x20
              txa
              asl a
              tax
              lda dp:MULW
              sta long:TILE_MIRROR,x
              lda ##0
              sta long:VIS_STAMPS,x
              txa
              lsr a
              tax
              dex
              txa
              and ##255
              bne gsMapProgress
              jsl long:Progress2
gsMapProgress:txa
              bpl gsMap
              ldy ##0
gsOpen:       tya
              cmp long:LOGIC_BASE+V_doornum
              bcs gsOpenDone
              asl a
              tax
              lda long:LOGIC_BASE+DOORACT,x
              beq gsOpenStamp
              lda long:LOGIC_BASE+DOORPOS,x
              cmp ##0xffff
              bne gsOpenNext
gsOpenStamp:  lda long:LOGIC_BASE+DOORTILE,x
              asl a
              tax
saveOpenWord: lda ##0x8000
              sta long:TILE_MIRROR,x
gsOpenNext:   iny
              bra gsOpen
gsOpenDone:
#if WOLF_PREPARED
              .extern InitWallRuns
              jsl long:InitWallRuns
#endif
              lda long:LOGIC_BASE+V_pwallstate
              beq gsPwallOff
              lda long:LOGIC_BASE+V_pwallpos
              asl a
              asl a
              bra gsPwallOn
gsPwallOff:   lda ##0
gsPwallOn:    sta abs:.word0 (pwallPosition)
              lda ##1
              sta abs:.word0 (wallDirty)
              sta dp:FIRST
              jsl long:LogicMarkObjects
              jsl long:RebuildSavedSight
              jsr abs:.word0 (UseLogicActorVisibility)
              jsr abs:.word0 (LogicPublish)
              lda ##1
              sta abs:.word0 (hudDirty)
              jsr abs:.word0 (UpdateHUD)
              pld
              plb
              plp
              rtl

              .section savecode, text, root, noreorder
;;; JSL from the menu. Direct page is UI_DP. U_T0-U_T5 are scratch; the
;;; block transfer starts after this returns. Carry set when the world
;;; cannot be written: the fresh lists did not fit, or the stream did not.
;;; plp would put the caller's carry back, so it is set again afterwards.
gsBuild:      php
              rep #0x30
              phb
              phk
              plb
              jsr abs:.word0 (gsBuildBody)
              lda ##0
              bcc gsBuildFlag
              lda ##1
gsBuildFlag:  plb
              plp
              cmp ##1
              beq gsBuildSec
              clc
              rtl
gsBuildSec:   sec
              rtl

;;; JSL, after StartFloor. The objects and the stream come from GS_HOLD.
;;; Carry set when the mark is not this game's or the stream does not
;;; decode. A bad sum still applies, then the penalty. The stream is
;;; decoded before the header words are put back, so a stream that fails
;;; leaves only bank $30 to rebuild.
gsApply:      php
              rep #0x30
              phb
              phk
              plb
              lda long:gsKind
              cmp ##2
              beq gsApplyMiss
              ldx ##.word0 (GS_HOLD)
              ldy ##OBJLIST
              lda ##GS_OBJN-1
              .byte 0x54, LOGICBANK, GS_HOLD>>16      ; MVN: the objects into bank $30
#ifdef WOLF_SPEAR
              ldx ##.word0 (SAVE_WORLD_HOLD)
#else
              ldx ##.word0 (GS_HOLD+GS_WORLDAT-GS_OBJ)
#endif
              ldy ##.word0 (GS_WORLD)
              lda ##GS_WORLDMAX-1
              .byte 0x54, GS_WORLD>>16, GS_HOLD>>16   ; MVN: the stream into GS_WORLD
              phk
              plb
              lda ##1
              sta long:projectionCold     ; the hold was projection storage: rebuild it
              jsr abs:.word0 (gsWorldIn)
              bcs gsApplyMiss
              jsr abs:.word0 (gsFixIn)
              jsr abs:.word0 (gsButtonsIn)
              lda long:gsBadSum
              beq gsApplySong
              jsr abs:.word0 (gsPenalty)
gsApplySong:  jsr abs:.word0 (gsRestore)
              plb
              plp
              clc
              rtl
gsApplyMiss:  plb
              plp
              sec
              rtl

gsBuildBody:  jsr abs:.word0 (gsZero)
              lda ##GS_MARKC
              sta long:gsHeader
              jsr abs:.word0 (gsStamp)
              jsr abs:.word0 (gsFixOut)
              jsr abs:.word0 (gsButtonsOut)
              lda long:gsBaseOk
              beq gsBuildFail
              jsr abs:.word0 (gsWorldOut)
              bcs gsBuildFail
              lda ##0
              sta long:gsKind
              jsr abs:.word0 (gsFileSum)
              lda ##GS_BLOCKS
              sta long:gsBlocks
              clc
              rts
gsBuildFail:  sec
              rts

gsZero:       ldx ##0
              lda ##0
gsZeroWord:   sta long:gsHeader,x
              inx
              inx
              cpx ##GS_OBJ
              bcc gsZeroWord
              rts

gsStamp:      lda long:levelPauseOn
              beq gsStampLive
              lda long:levelPauseAt+2
              tax
              lda long:levelPauseAt
              bra gsStampSub
gsStampLive:  jsl long:UiGetTime
gsStampSub:   sec
              sbc long:levelStart
              sta long:gsHeader+GS_ELAPSED
              txa
              sbc long:levelStart+2
              sta long:gsHeader+GS_ELAPSED+2
              lda long:floorSong
              cmp ##0xffff
              bne gsSongKeep
              lda long:levelIndex
              cmp ##CAMPAIGN_FLOORS
              bcc gsSongIdx
              lda ##0
gsSongIdx:    asl a
              tax
              lda long:floorSongs,x
gsSongKeep:   sta long:gsHeader+GS_SONG
              ldx ##0
gsRatioOut:   lda long:ratioTable,x
              sta long:gsHeader+GS_RATIOS,x
              inx
              inx
              cpx ##GS_RATIOSN
              bcc gsRatioOut
              rts

gsFixOut:     ldx ##0
gsFixWord:    phx
              lda abs:.word0 (gsFixTab),x
              tax
              lda long:LOGIC_BASE,x
              sta dp:U_T5
              plx
              lda dp:U_T5
              sta long:gsHeader+GS_FIX,x
              inx
              inx
              cpx ##GS_FIXN
              bcc gsFixWord
              rts

gsButtonsOut: ldx ##V_buttonstate
              lda ##.word0 (gsHeader)
              clc
              adc ##GS_BUTTONS
              tay
              lda ##GS_BUTTONN-1
              .byte 0x54, 0x02, 0x30
              phk
              plb
              rts

gsButtonsIn:  lda ##.word0 (gsHeader)
              clc
              adc ##GS_BUTTONS
              tax
              ldy ##V_buttonstate
              lda ##GS_BUTTONN-1
              .byte 0x54, 0x30, 0x02
              phk
              plb
              rts

gsFixIn:      ldx ##0
gsFixPut:     phx
              lda abs:.word0 (gsFixTab),x
              sta dp:U_T0
              lda long:gsHeader+GS_FIX,x
              sta dp:U_T5
              lda dp:U_T0
              tax
              lda dp:U_T5
              sta long:LOGIC_BASE,x
              plx
              inx
              inx
              cpx ##GS_FIXN
              bcc gsFixPut
              rts

;;; A checksum mismatch preserves the decoded world but resets score, lives,
;;; weapons and ammunition to these penalty values.
gsPenalty:    lda ##0
              sta long:LOGIC_BASE+V_score
              sta long:LOGIC_BASE+V_score_hi
              lda ##1
              sta long:LOGIC_BASE+V_lives
              sta long:LOGIC_BASE+V_weapon
              sta long:LOGIC_BASE+V_chosenweapon
              sta long:LOGIC_BASE+V_bestweapon
              lda ##8
              sta long:LOGIC_BASE+V_ammo
              rts

;;; Ratios back to the tally, the clock so the elapsed tics continue, and
;;; the floor song restarted the way StartMusic restarts it: from bank $3E
;;; when that is the song there (the floor load just put it there), else
;;; read again.
gsRestore:    phk
              plb
              ldx ##0
gsRatioIn:    lda long:gsHeader+GS_RATIOS,x
              sta long:ratioTable,x
              inx
              inx
              cpx ##GS_RATIOSN
              bcc gsRatioIn
              lda long:gsHeader+GS_ELAPSED
              sta long:levelHeld
              lda long:gsHeader+GS_ELAPSED+2
              sta long:levelHeld+2
              lda ##1
              sta long:levelHeldOn
              lda long:gsHeader+GS_SONG
              cmp ##0xffff
              bne gsPlay
              lda long:levelIndex
              cmp ##CAMPAIGN_FLOORS
              bcc gsPlayIdx
              lda ##0
gsPlayIdx:    asl a
              tax
              lda long:floorSongs,x
gsPlay:       sta long:floorSong
              cmp long:currentSong
              bne gsPlayDisk
              jsl long:StopMusic          ; bank $3E holds it: from its start, no read
              jsl long:StartMusic
              rts
gsPlayDisk:   lda ##0xffff
              sta long:currentSong
              lda long:floorSong
              jsl long:SelectMusic
              rts

;;; Words a fresh floor writes over. CheckLine reads the player tile before
;;; the player thinks again, so the two tile bytes travel with the pushwall.
;;; V_laststat is first: the stream's static section reads it from the
;;; header (GS_LASTSTAT) before these words go back.
gsFixTab:     .word V_laststat, V_rndindex, V_pwallstate, V_pwallpos, V_pwallx
              .word V_pwally, V_pwalldir, V_keys, V_secretcount, V_anglefrac
              .word V_facecount, V_bonuscount, V_damagecount, V_damageflash
              .word V_gatling, V_thrustspeed, V_thrustspeed_hi, V_madenoise
              .word V_events, V_spotstamp, V_playstate, V_faceframe
              .word V_attackframe, V_attackcount, V_weaponframe, V_gotgatgun
              .word V_victoryflag, V_objfreelist, V_lastobj, V_killerobj
              .word V_lastattacker, V_controlx, V_controly, V_controlstrafe
              .word V_plux, V_pluy

;;; Block 0 is in BUF. Only this game's mark is read; kind 2 reads no
;;; more blocks and leaves the world alone.
gsClassify:   lda long:BUF
              cmp ##GS_MARKC
              beq gsClassOk
              lda ##2
              sta long:gsKind
              lda ##0
              sta long:gsBlocks
              rts
gsClassOk:    lda ##0
              sta long:gsKind
              lda ##GS_BLOCKS
              sta long:gsBlocks
              jsr abs:.word0 (gsAcceptBody)
              rts

;;; JSL. The first block of a load. Carry set on a disk error, with A the
;;; error byte. A mark this game did not write returns ready and kind 2,
;;; after putting the firmware state back, so the caller can say the file
;;; is missing without reading the rest.
gsLoadFirst:  lda ##2
              sta long:gsSkip
              jsl long:gsCall
              bcs gsLoadRet
              phb
              phk
              plb
              jsr abs:.word0 (gsClassify)
              lda long:gsKind
              cmp ##2
              bne gsLoadCont
              plb
              jsl long:UiFwKeep
              stz dp:U_CNT
              stz dp:U_TOTAL
              clc
              rtl
gsLoadCont:   inc dp:U_BLK
              lda ##1
              sta dp:U_DONE
              lda long:gsBlocks
              sta dp:U_TOTAL
              dec a
              sta dp:U_CNT
              plb
              clc
gsLoadRet:    rtl

;;; JSL. One driver call for the block in U_BLK. Carry and A come back
;;; from gsFast.
gsCall:       lda abs:.word0 (gsCmd)
              and ##255
              sta dp:U_T0
              lda dp:U_UNIT
              and ##255
              xba
              ora dp:U_T0
              sta long:blkCmd
              lda ##BUF
              sta long:blkBuf
              lda dp:U_BLK
              sta long:blkNum
              jsl long:gsFast
              rtl

;;; JSL. Checksum this block, and keep or apply its words.
;;; Block 0 was accepted by gsClassify. U_DONE is this block's index.
gsTakeBlock:  php
              rep #0x30
              phb
              phk
              plb
              jsr abs:.word0 (gsAcceptBody)
              plb
              plp
              rtl

;;; 256 words in BUF. The sum field is recorded and added as zero.
gsAcceptBody: ldy ##0
abLoop:       lda dp:U_DONE
              xba
              asl a
              sta abs:.word0 (gsOff)
              tya
              clc
              adc abs:.word0 (gsOff)
              sta abs:.word0 (gsOff)
              tyx
              lda long:BUF,x
              sta dp:U_T5
              lda abs:.word0 (gsOff)
              cmp ##GS_SUM
              beq abSum
              lda long:gsRun
              clc
              adc dp:U_T5
              sta long:gsRun
              bra abPlace
abSum:        lda dp:U_T5
              sta long:gsSavedSum
abPlace:      phy
              jsr abs:.word0 (gsTakeWord)
              ply
              iny
              iny
              cpy ##512
              bcc abLoop
              rts

;;; Even file offset in gsOff, word in U_T5. The header goes to gsHeader,
;;; every later word to GS_HOLD (objects, the length, the stream).
gsTakeWord:   lda abs:.word0 (gsOff)
              cmp ##GS_OBJ
              bcs twHold
              tax
              lda dp:U_T5
              sta abs:.word0 (gsHeader),x
              rts
twHold:       cmp ##GS_NWORLD
              bne twKeep
              ldx dp:U_T5
              stx abs:.word0 (gsWorldLen)
twKeep:
#ifdef WOLF_SPEAR
              cmp ##GS_WORLDAT
              bcs twWorld
#endif
              tax
              lda dp:U_T5
              sta long:GS_HOLD-GS_OBJ,x
              rts
#ifdef WOLF_SPEAR
twWorld:      tax
              lda dp:U_T5
              sta long:SAVE_WORLD_HOLD-GS_WORLDAT,x
              rts
#endif

;;; JSL. Fill BUF with the 512 file bytes at block U_DONE.
gsEmitBlock:  php
              rep #0x30
              sei
              phb
              phk
              plb
              lda dp:U_DONE
              xba
              asl a
              sta abs:.word0 (gsOff)
              cmp ##0x200
              bcc emSet
              cmp ##0x2600
              bcc emObj
emSet:        ldy ##0
emLoop:       ldx abs:.word0 (gsOff)
              phy
              jsr abs:.word0 (gsFileWord)
              ply
              tyx
              sta long:BUF,x
              inc abs:.word0 (gsOff)
              inc abs:.word0 (gsOff)
              iny
              iny
              cpy ##512
              bcc emLoop
emExit:       plb
              plp
              rtl

;;; A whole block of the object list. The source index stays even.
emObj:        lda abs:.word0 (gsOff)
              sec
              sbc ##GS_OBJ
              sta abs:.word0 (gsB)
              lda ##0
              sta abs:.word0 (gsYc)
eoLoop:       ldx abs:.word0 (gsB)
              lda long:LOGIC_BASE+OBJLIST,x
              inx
              inx
              stx abs:.word0 (gsB)
              ldx abs:.word0 (gsYc)
              sta long:BUF,x
              inx
              inx
              stx abs:.word0 (gsYc)
              cpx ##512
              bcc eoLoop
              jmp abs:.word0 (emExit)

;;; X = even file offset. A = that word of the file.
gsFileWord:   cpx ##GS_OBJ
              bcs fwObj
              lda abs:.word0 (gsHeader),x
              rts
fwObj:        cpx ##GS_NWORLD
              bcs fwLen
              txa
              sec
              sbc ##GS_OBJ
              tax
              lda long:LOGIC_BASE+OBJLIST,x
              rts
fwLen:        bne fwWorld
              lda abs:.word0 (gsWorldLen)
              rts
fwWorld:      txa
              sec
              sbc ##GS_WORLDAT
              cmp abs:.word0 (gsWorldLen)
              bcs fwZero
              tax
              lda long:GS_WORLD,x
              rts
fwZero:       lda ##0
              rts

;;; Word sum of the file without the sum field: the header, the objects,
;;; the length and the stream. The rest of the file is zero. gsWorldOut
;;; zeroed the byte after an odd stream.
gsFileSum:    php
              sei
              ldx ##0
              lda ##0
fsHead:       cpx ##GS_SUM
              beq fsHeadNext
              clc
              adc abs:.word0 (gsHeader),x
fsHeadNext:   inx
              inx
              cpx ##GS_OBJ
              bcc fsHead
              ldx ##0
fsObj:        clc
              adc long:LOGIC_BASE+OBJLIST,x
              inx
              inx
              clc
              adc long:LOGIC_BASE+OBJLIST,x
              inx
              inx
              cpx ##GS_OBJN
              bcc fsObj
              clc
              adc abs:.word0 (gsWorldLen)
              ldx ##0
fsWorld:      cpx abs:.word0 (gsWorldLen)
              bcs fsDone
              clc
              adc long:GS_WORLD,x
              inx
              inx
              bra fsWorld
fsDone:       sta abs:.word0 (gsHeader+GS_SUM)
              plp
              rts


;;; A = column cell. A = its fresh TILEMAP byte, as setup leaves it: an
;;; ambush cell is empty; a door cell is $80 + its door, with $40 when a
;;; later door has it as a side; any other cell is the raw wall (107 and up
;;; empty), with $40 when it is beside a door. gsDoorBits made the maps.
gsTileByte:   sta abs:.word0 (gsCell)
              jsr abs:.word0 (gsRawOfCell)
              cmp ##106
              bne tbLive
              lda ##0
              rts
tbLive:       sta abs:.word0 (gsRaw)
              lda abs:.word0 (gsCell)
              jsr abs:.word0 (gsBitTest)
              bne tbDoor
tbNotDoor:    lda abs:.word0 (gsRaw)
              cmp ##107
              bcc tbBase
              lda ##0
tbBase:       sta abs:.word0 (gsWall)
              lda abs:.word0 (gsCell)
              clc
              adc ##GS_SIDEBIT
              jsr abs:.word0 (gsBitTest)
              beq tbDone
              lda abs:.word0 (gsWall)
              ora ##0x40
              rts
tbDoor:       ldx ##0
tbFind:       cpx abs:.word0 (gsDoorN)
              bcs tbNotDoor
              phx
              txa
              asl a
              asl a
              tax
              lda long:GS_DOORS,x
              plx
              cmp abs:.word0 (gsCell)
              beq tbFound
              inx
              bra tbFind
tbFound:      stx abs:.word0 (gsDn)
              txa
              ora ##0x80
              sta abs:.word0 (gsWall)
tbSide:       inx
              cpx abs:.word0 (gsDoorN)
              bcs tbDone
              jsr abs:.word0 (gsSideHit)
              bcc tbSide
              lda abs:.word0 (gsWall)
              ora ##0x40
              sta abs:.word0 (gsWall)
              bra tbSide
tbDone:       lda abs:.word0 (gsWall)
              rts

;;; GS_MARK: the door cells. GS_SIDES: the cells beside a door.
gsDoorBits:   ldx ##0
              lda ##0
dbClear:      sta long:GS_MARK,x
              sta long:GS_SIDES,x
              inx
              inx
              cpx ##512
              bcc dbClear
              ldy ##0
dbDoor:       cpy abs:.word0 (gsDoorN)
              bcs dbDone
              tya
              asl a
              asl a
              tax
              lda long:GS_DOORS,x
              sta abs:.word0 (gsHold)
              jsr abs:.word0 (gsMarkCell)
              lda long:GS_DOORS+2,x
              and ##255
              beq dbHoriz
              lda abs:.word0 (gsHold)
              beq dbPlus
              dec a
              jsr abs:.word0 (dbSide)
dbPlus:       lda abs:.word0 (gsHold)
              inc a
              cmp ##4096
              bcs dbNext
              jsr abs:.word0 (dbSide)
              bra dbNext
dbHoriz:      lda abs:.word0 (gsHold)
              cmp ##64
              bcc dbHplus
              sec
              sbc ##64
              jsr abs:.word0 (dbSide)
dbHplus:      lda abs:.word0 (gsHold)
              clc
              adc ##64
              cmp ##4096
              bcs dbNext
              jsr abs:.word0 (dbSide)
dbNext:       iny
              bra dbDoor
dbDone:       rts
dbSide:       phy
              clc
              adc ##GS_SIDEBIT
              jsr abs:.word0 (gsBitSet)
              ply
              rts

;;; A = cell, or anything past 4095. X and Y come back.
gsMarkCell:   cmp ##4096
              bcs mcRet
              phx
              phy
              pha
              lsr a
              lsr a
              lsr a
              tax
              pla
              and ##7
              tay
              lda ##1
mcShift:      dey
              bmi mcHave
              asl a
              bra mcShift
mcHave:       sep #0x20
              ora long:GS_MARK,x
              sta long:GS_MARK,x
              rep #0x20
              ply
              plx
mcRet:        rts

;;; Carry set when door X has gsCell as a side. X is kept.
gsSideHit:    phx
              txa
              asl a
              asl a
              tax
              lda long:GS_DOORS,x
              sta abs:.word0 (gsTmp)
              lda long:GS_DOORS+2,x
              and ##255
              beq shHoriz
              lda abs:.word0 (gsTmp)
              dec a
              cmp abs:.word0 (gsCell)
              beq shYes
              inc a
              inc a
              cmp abs:.word0 (gsCell)
              beq shYes
              bra shNo
shHoriz:      lda abs:.word0 (gsTmp)
              sec
              sbc ##64
              cmp abs:.word0 (gsCell)
              beq shYes
              clc
              adc ##128
              cmp abs:.word0 (gsCell)
              beq shYes
shNo:         plx
              clc
              rts
shYes:        plx
              sec
              rts

;;; Raw plane-0 byte of column cell gsCell.
gsRawOfCell:  lda abs:.word0 (gsCell)
              jsr abs:.word0 (gsPlaneOf)
              tax
              sep #0x20
              lda long:RAW0_ADDRESS,x
              rep #0x20
              and ##255
              rts

;;; ------------------------------------------------------------- stream
;;; The world stream. tools/save_format.py encode and decode are the same
;;; steps; tools/check_save_bound.py bounds every section on all 60 floors.
;;; The loops keep their counters in U_T0-U_T5 (scratch while the menu
;;; saves or loads).
              .section savecode4, text, root
              .public gsWorldOut, gsWorldIn, gsPut, gsGet, gsBitTest, gsPlaneOf, gsGEntry

;;; The stream is least significant bit first. gsBitAcc takes each bit at
;;; bit 15, so a byte is whole in its high half after eight; gsBitN counts
;;; the bits that byte still needs. gsBitPtr is the next byte of GS_WORLD.
;;; A full stream sets gsBitOver and keeps no more bytes.
;;; A = value, Y = bits (1-16). X is not kept.
gsPut:        sta abs:.word0 (gsBitV)
gpLoop:       lsr abs:.word0 (gsBitV)
              ror abs:.word0 (gsBitAcc)
              dec abs:.word0 (gsBitN)
              bne gpNext
              lda abs:.word0 (gsBitAcc)
              xba
              ldx abs:.word0 (gsBitPtr)
              cpx ##GS_WORLDMAX
              bcs gpOver
              sep #0x20
              sta long:GS_WORLD,x
              rep #0x20
              inc abs:.word0 (gsBitPtr)
gpRefill:     lda ##8
              sta abs:.word0 (gsBitN)
gpNext:       dey
              bne gpLoop
              rts
gpOver:       lda ##1
              sta abs:.word0 (gsBitOver)
              bra gpRefill

;;; Y = bits (1-16). A = value, flags from A. Each bit goes in at bit 15 of
;;; gsBitV, then the value is shifted down. Past the stream every bit is
;;; one and gsBitOver is set, so every loop of the reader ends.
gsGet:        sty abs:.word0 (gsBitCnt)
ggLoop:       lda abs:.word0 (gsBitN)
              bne ggHave
              ldx abs:.word0 (gsBitPtr)
              cpx abs:.word0 (gsWorldLen)
              bcs ggOver
              lda long:GS_WORLD,x
              and ##255
              sta abs:.word0 (gsBitAcc)
              inc abs:.word0 (gsBitPtr)
              lda ##8
              sta abs:.word0 (gsBitN)
ggHave:       dec abs:.word0 (gsBitN)
              lsr abs:.word0 (gsBitAcc)
ggBit:        ror abs:.word0 (gsBitV)
              dey
              bne ggLoop
              lda ##16
              sec
              sbc abs:.word0 (gsBitCnt)
              tay
              lda abs:.word0 (gsBitV)
ggShift:      dey
              bmi ggDone
              lsr a
              bra ggShift
ggDone:       cmp ##0
              rts
ggOver:       lda ##1
              sta abs:.word0 (gsBitOver)
              sec
              bra ggBit

;;; A = a bit from GS_MARK on: a cell a door touches (0-4095), a K plane
;;; (4096 + plane), a T cell (8192 + cell). X and Y are not kept.
gsBitSet:     pha
              and ##7
              tax
              lda abs:.word0 (gsBitMasks),x
              sta abs:.word0 (gsBitT)
              pla
              lsr a
              lsr a
              lsr a
              tax
              sep #0x20
              lda abs:.word0 (gsBitT)
              ora long:GS_MARK,x
              sta long:GS_MARK,x
              rep #0x20
              rts
;;; Zero flag clear when the bit is set. Y is kept.
gsBitTest:    pha
              and ##7
              tax
              lda abs:.word0 (gsBitMasks),x
              and ##255
              sta abs:.word0 (gsBitT)
              pla
              lsr a
              lsr a
              lsr a
              tax
              lda long:GS_MARK,x
              and abs:.word0 (gsBitT)
              rts

;;; A = cell x*64+y. A = plane y*64+x. The same swap goes back.
gsPlaneOf:    pha
              and ##63
              xba
              lsr a
              lsr a
              sta abs:.word0 (gsPofT)
              pla
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              ora abs:.word0 (gsPofT)
              rts

;;; X = plane. A = that raw byte. X is kept. Byte reads: RAW1 ends at the
;;; I/O page.
gsRaw0At:     sep #0x20
              lda long:RAW0_ADDRESS,x
              rep #0x20
              and ##255
              rts
gsRaw1At:     sep #0x20
              lda long:RAW1_ADDRESS,x
              rep #0x20
              and ##255
              rts

;;; K, by plane: the start of every pushwall and up to three cells each
;;; way, until a wall that is not a pushwall start. A door or an empty cell
;;; does not stop the walk. T is cleared. tools/save_format.py kplanes.
gsKBuild:     ldx ##0
              lda ##0
kbClear:      sta long:GS_KBITS,x
              inx
              inx
              cpx ##GS_KBITS_SIZE+GS_TBITS_SIZE
              bcc kbClear
              ldx ##0
              sep #0x20
kbScan:       lda long:RAW1_ADDRESS,x
              cmp #GS_PUSHABLE
              beq kbStart
kbNext:       inx
              cpx ##4096
              bcc kbScan
              rep #0x20
              rts
kbStart:      rep #0x20
              stx abs:.word0 (gsKs)
              txa
              and ##63
              sta abs:.word0 (gsKx0)
              sta abs:.word0 (gsKx)
              txa
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta abs:.word0 (gsKy0)
              sta abs:.word0 (gsKy)
              jsr abs:.word0 (kbMark)
              stz abs:.word0 (gsKd)
kbDir:        lda abs:.word0 (gsKx0)
              sta abs:.word0 (gsKx)
              lda abs:.word0 (gsKy0)
              sta abs:.word0 (gsKy)
              lda ##3
              sta abs:.word0 (gsKj)
kbStep:       ldx abs:.word0 (gsKd)
              lda abs:.word0 (gsKx)
              clc
              adc abs:.word0 (kbDx),x
              sta abs:.word0 (gsKx)
              cmp ##64
              bcs kbDirNext
              lda abs:.word0 (gsKy)
              clc
              adc abs:.word0 (kbDy),x
              sta abs:.word0 (gsKy)
              cmp ##64
              bcs kbDirNext
              xba
              lsr a
              lsr a
              ora abs:.word0 (gsKx)
              tax
              sep #0x20
              lda long:RAW1_ADDRESS,x
              cmp #GS_PUSHABLE
              beq kbOpen
              lda long:RAW0_ADDRESS,x
              cmp #106
              bcs kbOpen
              cmp #90
              bcc kbWall
              cmp #102
              bcc kbOpen
kbWall:       rep #0x20
              bra kbDirNext
kbOpen:       rep #0x20
              jsr abs:.word0 (kbMark)
              dec abs:.word0 (gsKj)
              bne kbStep
kbDirNext:    lda abs:.word0 (gsKd)
              inc a
              inc a
              sta abs:.word0 (gsKd)
              cmp ##8
              bcc kbDir
              ldx abs:.word0 (gsKs)
              sep #0x20
              jmp abs:.word0 (kbNext)
kbMark:       lda abs:.word0 (gsKy)
              xba
              lsr a
              lsr a
              ora abs:.word0 (gsKx)
              clc
              adc ##4096
              jmp abs:.word0 (gsBitSet)
kbDx:         .word 0, 1, 0, 0xffff       ; north, east, south, west
kbDy:         .word 0xffff, 0, 1, 0

;;; Every K plane in order: gsKfn is called with the plane in gsKp and its
;;; cell in gsKc. The MAP0 list cursor starts at the first entry.
gsForK:       stz abs:.word0 (gsMapI)
              ldx ##0
fkByte:       stx abs:.word0 (gsKb)
              lda long:GS_KBITS,x
              and ##255
              beq fkByteNext
              sta abs:.word0 (gsKv)
              txa
              asl a
              asl a
              asl a
              sta abs:.word0 (gsKp)
fkBit:        lsr abs:.word0 (gsKv)
              bcc fkBitNext
              lda abs:.word0 (gsKp)
              jsr abs:.word0 (gsPlaneOf)
              sta abs:.word0 (gsKc)
              ldx ##0
              .byte 0xfc                  ; JSR (gsKfn,X)
              .word .word0 (gsKfn)
fkBitNext:    inc abs:.word0 (gsKp)
              lda abs:.word0 (gsKv)
              bne fkBit
fkByteNext:   ldx abs:.word0 (gsKb)
              inx
              cpx ##GS_KBITS_SIZE
              bcc fkByte
              rts

;;; A = plane, never below the last one asked. A = the fresh MAP0 byte: the
;;; capture list (sorted by plane), else the raw plane.
gsMapAt:      sta abs:.word0 (gsMq)
maSync:       lda abs:.word0 (gsMapI)
              cmp abs:.word0 (gsMapN)
              bcs maRaw
              asl a
              asl a
              tax
              lda long:GS_MAPS,x
              cmp abs:.word0 (gsMq)
              beq maHit
              bcs maRaw
              inc abs:.word0 (gsMapI)
              bra maSync
maHit:        lda long:GS_MAPS+2,x
              and ##255
              rts
maRaw:        ldx abs:.word0 (gsMq)
              jmp abs:.word0 (gsRaw0At)

;;; JSR from gsBuildBody. The stream into GS_WORLD and its length into
;;; gsWorldLen. Carry set when it did not fit (no floor reaches that:
;;; tools/check_save_bound.py). The scan runs with interrupts held off.
gsWorldOut:   php
              sei
              stz abs:.word0 (gsBitPtr)
              stz abs:.word0 (gsBitOver)
              lda ##8
              sta abs:.word0 (gsBitN)
              jsr abs:.word0 (gsKBuild)
              jsr abs:.word0 (gsDoorBits)
              lda ##.word0 (ekCell)
              sta abs:.word0 (gsKfn)
              jsr abs:.word0 (gsForK)
              jsr abs:.word0 (gsEncS)
              jsr abs:.word0 (gsEncD)
              jsr abs:.word0 (gsEncA)
              jsr abs:.word0 (gsEncR)
              jsr abs:.word0 (gsEncG)
              lda abs:.word0 (gsBitN)
              cmp ##8
              beq woFlushed
              tay
              lda ##0
              jsr abs:.word0 (gsPut)
woFlushed:    lda abs:.word0 (gsBitPtr)
              sta abs:.word0 (gsWorldLen)
              tax
              lda ##0
              sta long:GS_WORLD,x         ; an odd stream's last word sums with a zero
              plp
              lda abs:.word0 (gsBitOver)
              cmp ##1
              rts

;;; JSR from gsApply. The stream in GS_WORLD onto the fresh floor. Carry set
;;; when it does not decode; bank $30 is then part written.
gsWorldIn:    php
              sei
              stz abs:.word0 (gsBitPtr)
              stz abs:.word0 (gsBitN)
              stz abs:.word0 (gsBitOver)
              jsr abs:.word0 (gsKBuild)
              lda ##.word0 (dkCell)
              sta abs:.word0 (gsKfn)
              jsr abs:.word0 (gsForK)
              jsr abs:.word0 (gsDecS)
              jsr abs:.word0 (gsDecD)
              jsr abs:.word0 (gsDecA)
              jsr abs:.word0 (gsDecR)
              jsr abs:.word0 (gsDecG)
              plp
              lda abs:.word0 (gsBitOver)
              cmp ##1
              rts

;;; ------------------------------------------------------------- K
;;; Plane gsKp, cell gsKc. TILEMAP: an empty fresh cell takes 1 bit (same,
;;; or a byte follows); a wall or door takes 2 (same, zero, a byte). A
;;; changed tile sets T. MAP0: 1 bit, then a byte. MAP1 at a pushwall
;;; start: 2 bits (same, zero, a byte).
ekCell:       lda abs:.word0 (gsKc)
              jsr abs:.word0 (gsTileByte)
              and ##255
              sta abs:.word0 (gsKf)
              ldx abs:.word0 (gsKc)
              lda long:LOGIC_BASE+TILEMAP,x
              and ##255
              sta abs:.word0 (gsKl)
              ldy abs:.word0 (gsKf)
              bne ekWall
              cmp ##0
              beq ekEmpty
              lda ##1
              ldy ##1
              jsr abs:.word0 (gsPut)
              bra ekByte8
ekEmpty:      ldy ##1
              jsr abs:.word0 (gsPut)
              bra ekMap
ekWall:       cmp abs:.word0 (gsKf)
              beq ekSame2
              cmp ##0
              bne ekWallByte
              lda ##1
              ldy ##2
              jsr abs:.word0 (gsPut)
              bra ekMarkT
ekSame2:      lda ##0
              ldy ##2
              jsr abs:.word0 (gsPut)
              bra ekMap
ekWallByte:   lda ##2
              ldy ##2
              jsr abs:.word0 (gsPut)
ekByte8:      lda abs:.word0 (gsKl)
              ldy ##8
              jsr abs:.word0 (gsPut)
ekMarkT:      lda abs:.word0 (gsKc)
              clc
              adc ##8192
              jsr abs:.word0 (gsBitSet)
ekMap:        lda abs:.word0 (gsKp)
              jsr abs:.word0 (gsMapAt)
              sta abs:.word0 (gsKf)
              ldx abs:.word0 (gsKp)
              lda long:LOGIC_BASE+MAP0,x
              and ##255
              sta abs:.word0 (gsKl)
              cmp abs:.word0 (gsKf)
              beq ekMapSame
              lda ##1
              ldy ##1
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsKl)
              ldy ##8
              jsr abs:.word0 (gsPut)
              bra ekInfo
ekMapSame:    lda ##0
              ldy ##1
              jsr abs:.word0 (gsPut)
ekInfo:       ldx abs:.word0 (gsKp)
              jsr abs:.word0 (gsRaw1At)
              cmp ##GS_PUSHABLE
              bne ekDone
              sta abs:.word0 (gsKf)
              lda long:LOGIC_BASE+MAP1,x
              and ##255
              sta abs:.word0 (gsKl)
              cmp abs:.word0 (gsKf)
              beq ekInfoSame
              cmp ##0
              bne ekInfoByte
              lda ##1
              ldy ##2
              jmp abs:.word0 (gsPut)
ekInfoByte:   lda ##2
              ldy ##2
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsKl)
              ldy ##8
              jmp abs:.word0 (gsPut)
ekInfoSame:   lda ##0
              ldy ##2
              jmp abs:.word0 (gsPut)
ekDone:       rts

dkCell:       ldx abs:.word0 (gsKc)
              lda long:LOGIC_BASE+TILEMAP,x
              and ##255
              bne dkWall
              ldy ##1
              jsr abs:.word0 (gsGet)
              beq dkMap
              bra dkByte
dkWall:       ldy ##2
              jsr abs:.word0 (gsGet)
              beq dkMap
              cmp ##2
              beq dkByte
              bcs dkBad
              lda ##0
              bra dkStore
dkByte:       ldy ##8
              jsr abs:.word0 (gsGet)
dkStore:      ldx abs:.word0 (gsKc)
              sep #0x20
              sta long:LOGIC_BASE+TILEMAP,x
              rep #0x20
              lda abs:.word0 (gsKc)
              clc
              adc ##8192
              jsr abs:.word0 (gsBitSet)
dkMap:        ldy ##1
              jsr abs:.word0 (gsGet)
              beq dkInfo
              ldy ##8
              jsr abs:.word0 (gsGet)
              ldx abs:.word0 (gsKp)
              sep #0x20
              sta long:LOGIC_BASE+MAP0,x
              rep #0x20
dkInfo:       ldx abs:.word0 (gsKp)
              jsr abs:.word0 (gsRaw1At)
              cmp ##GS_PUSHABLE
              bne dkDone
              ldy ##2
              jsr abs:.word0 (gsGet)
              beq dkDone
              cmp ##2
              beq dkInfoByte
              bcs dkBad
              lda ##0
              bra dkInfoStore
dkInfoByte:   ldy ##8
              jsr abs:.word0 (gsGet)
dkInfoStore:  ldx abs:.word0 (gsKp)
              sep #0x20
              sta long:LOGIC_BASE+MAP1,x
              rep #0x20
dkDone:       rts
dkBad:        lda ##1
              sta abs:.word0 (gsBitOver)
              rts

;;; ------------------------------------------------------------- S
;;; A = a laststat value. gsSn = the larger of it and the fresh count, in
;;; slots, at most MAXSTATS.
gsStatCount:  sec
              sbc ##STATICS
              lsr a
              lsr a
              lsr a
              cmp abs:.word0 (gsFreshStat)
              bcs scMax
              lda abs:.word0 (gsFreshStat)
scMax:        cmp ##MAXSTATS+1
              bcc scOk
              lda ##MAXSTATS
scOk:         sta abs:.word0 (gsSn)
              rts

;;; A = item. A = the shape of the first STATINFO row with that item, as
;;; PlaceItemType searches. Carry set when there is none.
gsShapeOf:    sta abs:.word0 (gsTmp)
              ldx ##0
soLoop:       lda long:LOGIC_BASE+STATINFO+2,x
              cmp abs:.word0 (gsTmp)
              beq soHit
              inx
              inx
              inx
              inx
#ifdef WOLF_SPEAR
              cpx ##SPEAR_STATIC_COUNT*4
#else
              cpx ##49*4
#endif
              bcc soLoop
              sec
              rts
soHit:        lda long:LOGIC_BASE+STATINFO,x
              clc
              rts

;;; The next fresh static from the info plane at gsStPlane, as SpawnStatic
;;; builds it, into gsStBuf.
gsNextStatic: ldx abs:.word0 (gsStPlane)
              sep #0x20
nsScan:       cpx ##4096
              bcs nsNone
              lda long:RAW1_ADDRESS,x
              cmp #23
              bcc nsSkip
              cmp #75
              bcc nsFound
nsSkip:       inx
              bra nsScan
nsNone:       rep #0x20
              stx abs:.word0 (gsStPlane)
              stz abs:.word0 (gsStBuf)
              stz abs:.word0 (gsStBuf+2)
              bra nsPlain
nsFound:      rep #0x20
              and ##255
              pha
              txa
              inc a
              sta abs:.word0 (gsStPlane)
              dec a
              jsr abs:.word0 (gsPlaneOf)
              sta abs:.word0 (gsStBuf)
              pla
              sec
              sbc ##23
              asl a
              asl a
              tax
              lda long:LOGIC_BASE+STATINFO,x
              phx
              ldx abs:.word0 (gsStBuf)
              jsl long:StaticSpriteVariant
              plx
              sta abs:.word0 (gsStBuf+2)
              lda long:LOGIC_BASE+STATINFO+2,x
              cmp ##2
              bcc nsPlain
              sta abs:.word0 (gsStBuf+6)
              lda ##2
              sta abs:.word0 (gsStBuf+4)
              rts
nsPlain:      stz abs:.word0 (gsStBuf+4)
              stz abs:.word0 (gsStBuf+6)
              rts

;;; Every slot below the larger of the fresh and live laststat: 0 same,
;;; 1 taken (shape $FFFF), 2 a dropped item (cell 12, item 8, taken 1),
;;; 3 the four words.
gsEncS:       lda long:LOGIC_BASE+V_laststat
              jsr abs:.word0 (gsStatCount)
              stz abs:.word0 (gsSi)
              stz abs:.word0 (gsStPlane)
esSlot:       lda abs:.word0 (gsSi)
              cmp abs:.word0 (gsSn)
              bcc esHave
              rts
esHave:       cmp abs:.word0 (gsFreshStat)
              bcs esBlank
              jsr abs:.word0 (gsNextStatic)
              bra esLive
esBlank:      stz abs:.word0 (gsStBuf)
              stz abs:.word0 (gsStBuf+2)
              stz abs:.word0 (gsStBuf+4)
              stz abs:.word0 (gsStBuf+6)
esLive:       lda abs:.word0 (gsSi)
              asl a
              asl a
              asl a
              tax
              lda long:LOGIC_BASE+STATICS,x
              sta abs:.word0 (gsStLive)
              lda long:LOGIC_BASE+STATICS+2,x
              sta abs:.word0 (gsStLive+2)
              lda long:LOGIC_BASE+STATICS+4,x
              sta abs:.word0 (gsStLive+4)
              lda long:LOGIC_BASE+STATICS+6,x
              sta abs:.word0 (gsStLive+6)
              ldx ##6
esCmp:        lda abs:.word0 (gsStLive),x
              cmp abs:.word0 (gsStBuf),x
              bne esTaken
              dex
              dex
              bpl esCmp
              lda ##0
              ldy ##2
              jsr abs:.word0 (gsPut)
              jmp abs:.word0 (esNext)
esTaken:      lda abs:.word0 (gsStBuf+2)
              cmp ##0xffff
              beq esDrop
              lda abs:.word0 (gsStLive+2)
              cmp ##0xffff
              bne esDrop
              lda abs:.word0 (gsStLive)
              cmp abs:.word0 (gsStBuf)
              bne esDrop
              lda abs:.word0 (gsStLive+4)
              cmp abs:.word0 (gsStBuf+4)
              bne esDrop
              lda abs:.word0 (gsStLive+6)
              cmp abs:.word0 (gsStBuf+6)
              bne esDrop
              lda ##1
              ldy ##2
              jsr abs:.word0 (gsPut)
              bra esNext
esDrop:       lda abs:.word0 (gsStLive+4)
              cmp ##2
              bne esRaw
              lda abs:.word0 (gsStLive)
              cmp ##4096
              bcs esRaw
              lda abs:.word0 (gsStLive+6)
              cmp ##256
              bcs esRaw
              jsr abs:.word0 (gsShapeOf)
              bcs esRaw
              cmp abs:.word0 (gsStLive+2)
              beq esDropOk
              lda abs:.word0 (gsStLive+2)
              cmp ##0xffff
              bne esRaw
esDropOk:     lda ##2
              ldy ##2
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsStLive)
              ldy ##12
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsStLive+6)
              ldy ##8
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsStLive+2)
              cmp ##0xffff                ; carry set: taken
              lda ##0
              rol a
              ldy ##1
              jsr abs:.word0 (gsPut)
              bra esNext
esRaw:        lda ##3
              ldy ##2
              jsr abs:.word0 (gsPut)
              ldx ##0
esRawWord:    phx
              lda abs:.word0 (gsStLive),x
              ldy ##16
              jsr abs:.word0 (gsPut)
              plx
              inx
              inx
              cpx ##8
              bcc esRawWord
esNext:       inc abs:.word0 (gsSi)
              jmp abs:.word0 (esSlot)

gsDecS:       lda abs:.word0 (gsHeader+GS_LASTSTAT)
              jsr abs:.word0 (gsStatCount)
              stz abs:.word0 (gsSi)
dsSlot:       lda abs:.word0 (gsSi)
              cmp abs:.word0 (gsSn)
              bcc dsHave
              rts
dsHave:       asl a
              asl a
              asl a
              sta abs:.word0 (gsSo)
              ldy ##2
              jsr abs:.word0 (gsGet)
              beq dsNext
              cmp ##2
              beq dsDrop
              bcs dsRaw
              ldx abs:.word0 (gsSo)
              lda ##0xffff
              sta long:LOGIC_BASE+STATICS+2,x
              bra dsNext
dsDrop:       ldy ##12
              jsr abs:.word0 (gsGet)
              sta abs:.word0 (gsStLive)
              ldy ##8
              jsr abs:.word0 (gsGet)
              sta abs:.word0 (gsStLive+6)
              jsr abs:.word0 (gsShapeOf)
              bcc dsShape
              ldx ##1
              stx abs:.word0 (gsBitOver)
dsShape:      sta abs:.word0 (gsStLive+2)
              lda ##2
              sta abs:.word0 (gsStLive+4)
              ldy ##1
              jsr abs:.word0 (gsGet)
              beq dsWrite
              lda ##0xffff
              sta abs:.word0 (gsStLive+2)
              bra dsWrite
dsRaw:        ldx ##0
dsRawWord:    phx
              ldy ##16
              jsr abs:.word0 (gsGet)
              plx
              sta abs:.word0 (gsStLive),x
              inx
              inx
              cpx ##8
              bcc dsRawWord
dsWrite:      ldx abs:.word0 (gsSo)
              lda abs:.word0 (gsStLive)
              sta long:LOGIC_BASE+STATICS,x
              lda abs:.word0 (gsStLive+2)
              sta long:LOGIC_BASE+STATICS+2,x
              lda abs:.word0 (gsStLive+4)
              sta long:LOGIC_BASE+STATICS+4,x
              lda abs:.word0 (gsStLive+6)
              sta long:LOGIC_BASE+STATICS+6,x
dsNext:       inc abs:.word0 (gsSi)
              jmp abs:.word0 (dsSlot)

;;; The second half of the stream code lives in the Save memory, the first
;;; in the Data memory (src/iigs/wolf.scm): neither holds all of it.
              .section savecode5, text, root
;;; ------------------------------------------------------------- D
;;; A door is fresh at position 0, DR_CLOSED, tics 0. 1 bit, then the
;;; position, action and tics words.
gsEncD:       stz abs:.word0 (gsSi)
edDoor:       lda abs:.word0 (gsSi)
              cmp long:LOGIC_BASE+V_doornum
              bcc edHave
              rts
edHave:       asl a
              tax
              lda long:LOGIC_BASE+DOORPOS,x
              bne edDiff
              lda long:LOGIC_BASE+DOORTICS,x
              bne edDiff
              lda long:LOGIC_BASE+DOORACT,x
              cmp ##GS_DRCLOSED
              bne edDiff
              lda ##0
              ldy ##1
              jsr abs:.word0 (gsPut)
              bra edNext
edDiff:       lda ##1
              ldy ##1
              jsr abs:.word0 (gsPut)
              lda ##DOORPOS
              jsr abs:.word0 (edWord)
              lda ##DOORACT
              jsr abs:.word0 (edWord)
              lda ##DOORTICS
              jsr abs:.word0 (edWord)
edNext:       inc abs:.word0 (gsSi)
              bra edDoor
;;; A = table. Its word for door gsSi goes out.
edWord:       clc
              adc abs:.word0 (gsSi)
              adc abs:.word0 (gsSi)
              tax
              lda long:LOGIC_BASE,x
              ldy ##16
              jmp abs:.word0 (gsPut)

gsDecD:       stz abs:.word0 (gsSi)
ddDoor:       lda abs:.word0 (gsSi)
              cmp long:LOGIC_BASE+V_doornum
              bcc ddHave
              rts
ddHave:       ldy ##1
              jsr abs:.word0 (gsGet)
              beq ddNext
              lda ##DOORPOS
              jsr abs:.word0 (ddWord)
              lda ##DOORACT
              jsr abs:.word0 (ddWord)
              lda ##DOORTICS
              jsr abs:.word0 (ddWord)
ddNext:       inc abs:.word0 (gsSi)
              bra ddDoor
ddWord:       clc
              adc abs:.word0 (gsSi)
              adc abs:.word0 (gsSi)
              sta abs:.word0 (gsSo)
              ldy ##16
              jsr abs:.word0 (gsGet)
              ldx abs:.word0 (gsSo)
              sta long:LOGIC_BASE,x
              rts

;;; ------------------------------------------------------------- A
;;; AREABYPLAYER areas 0-36 as bits, then every byte of $6600-$6BFF that
;;; the bits and the fresh zeros do not give (index 11, value 8), ended by
;;; index $7FF.
gsEncA:       ldx ##0
eaBits:       phx
              lda long:LOGIC_BASE+AREABYPLAYER,x
              and ##1
              ldy ##1
              jsr abs:.word0 (gsPut)
              plx
              inx
              cpx ##37
              bcc eaBits
              ldx ##0
eaByte:       lda long:LOGIC_BASE+AREACONNECT,x
              and ##255
              beq eaNext
              cmp ##1
              bne eaPut
              cpx ##AREABYPLAYER-AREACONNECT
              bcc eaPut
              cpx ##AREABYPLAYER-AREACONNECT+37
              bcc eaNext
eaPut:        sta abs:.word0 (gsTmp)
              stx abs:.word0 (gsSi)
              txa
              ldy ##11
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsTmp)
              ldy ##8
              jsr abs:.word0 (gsPut)
              ldx abs:.word0 (gsSi)
eaNext:       inx
              cpx ##VARS-AREACONNECT
              bcc eaByte
              lda ##0x7ff
              ldy ##11
              jmp abs:.word0 (gsPut)

gsDecA:       ldx ##0
daBits:       phx
              ldy ##1
              jsr abs:.word0 (gsGet)
              plx
              sep #0x20
              sta long:LOGIC_BASE+AREABYPLAYER,x
              rep #0x20
              inx
              cpx ##37
              bcc daBits
daEntry:      ldy ##11
              jsr abs:.word0 (gsGet)
              cmp ##0x7ff
              beq daDone
              cmp ##VARS-AREACONNECT
              bcs daBad
              sta abs:.word0 (gsSo)
              ldy ##8
              jsr abs:.word0 (gsGet)
              ldx abs:.word0 (gsSo)
              sep #0x20
              sta long:LOGIC_BASE+AREACONNECT,x
              rep #0x20
              bra daEntry
daBad:        lda ##1
              sta abs:.word0 (gsBitOver)
daDone:       rts

;;; ------------------------------------------------------------- R
;;; ACTORAT against the fresh floor with its actor marks cleared; a cell
;;; whose tile the K section changed takes that tile when it is below $80.
;;; A cell that still differs: a gap nibble (15: skip 15 cells) and a code.
;;; U_T0 cell, U_T1 its plane, U_T2 the T byte, U_T3 the next cell of the
;;; capture list, U_T4 that entry's offset, U_T5 the expected word.
gsEncR:       lda ##0xffff
              sta abs:.word0 (gsRprev)
              stz dp:U_T0
              stz dp:U_T1
              stz dp:U_T4
              jsr abs:.word0 (erHold)
erCell:       lda dp:U_T0
              and ##7
              bne erFresh
              lda dp:U_T0
              lsr a
              lsr a
              lsr a
              tax
              lda long:GS_TBITS,x
              sta dp:U_T2
erFresh:      lda dp:U_T0
              cmp dp:U_T3
              bne erRaw
              ldx dp:U_T4
              lda long:GS_ACTS+2,x
              pha
              inx
              inx
              inx
              inx
              stx dp:U_T4
              jsr abs:.word0 (erHold)
              pla
              bra erClear
erRaw:        ldx dp:U_T1
              lda long:RAW0_ADDRESS,x
              and ##255
              cmp ##107
              bcc erClear
              lda ##0
erClear:      cmp ##OBJLIST
              bcc erPredict
              cmp ##OBJLIST+OBJSIZE*MAXACTORS
              bcs erPredict
              lda ##0
erPredict:    lsr dp:U_T2
              bcc erCompare
              tay
              ldx dp:U_T0
              lda long:LOGIC_BASE+TILEMAP,x
              and ##255
              cmp ##0x80
              bcc erCompare
              tya
erCompare:    sta dp:U_T5
              lda dp:U_T0
              asl a
              tax
              lda long:LOGIC_BASE+ACTORAT,x
              cmp dp:U_T5
              beq erNext
              jsr abs:.word0 (erEntry)
erNext:       inc dp:U_T0
              lda dp:U_T0
              cmp ##4096
              bcs erDone
              and ##63
              beq erWrap
              lda dp:U_T1
              clc
              adc ##64
              sta dp:U_T1
              jmp abs:.word0 (erCell)
erWrap:       lda dp:U_T0
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:U_T1
              jmp abs:.word0 (erCell)
erDone:       lda ##0
              ldy ##4
              jsr abs:.word0 (gsPut)
              lda ##GS_CODEEND
              ldy ##8
              jmp abs:.word0 (gsPut)
;;; A = the live word of cell U_T0.
erEntry:      sta abs:.word0 (gsRl)
              lda dp:U_T0
              clc
              sbc abs:.word0 (gsRprev)
erGap:        sta abs:.word0 (gsRg)
              cmp ##15
              bcc erGapPut
              lda ##15
              ldy ##4
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsRg)
              sec
              sbc ##15
              bra erGap
erGapPut:     ldy ##4
              jsr abs:.word0 (gsPut)
              lda dp:U_T0
              sta abs:.word0 (gsRprev)
              lda abs:.word0 (gsRl)
              bne erNonZero
              lda ##GS_CODEZERO
              ldy ##8
              jmp abs:.word0 (gsPut)
erNonZero:    sec
              sbc ##OBJLIST
              bcc erRawCode
              cmp ##OBJSIZE*MAXACTORS
              bcs erRawCode
              bit ##OBJSIZE-1
              bne erRawCode
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              ldy ##8
              jmp abs:.word0 (gsPut)
erRawCode:    lda ##GS_CODERAW
              ldy ##8
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsRl)
              ldy ##16
              jmp abs:.word0 (gsPut)
erHold:       lda dp:U_T4
              lsr a
              lsr a
              cmp abs:.word0 (gsActN)
              bcs erHoldNone
              ldx dp:U_T4
              lda long:GS_ACTS,x
              sta dp:U_T3
              rts
erHoldNone:   lda ##4096
              sta dp:U_T3
              rts

gsDecR:       stz dp:U_T0
drCell:       lda dp:U_T0
              and ##7
              bne drHave
              lda dp:U_T0
              lsr a
              lsr a
              lsr a
              tax
              lda long:GS_TBITS,x
              sta dp:U_T2
drHave:       lda dp:U_T0
              asl a
              tax
              lda long:LOGIC_BASE+ACTORAT,x
              cmp ##OBJLIST
              bcc drPredict
              cmp ##OBJLIST+OBJSIZE*MAXACTORS
              bcs drPredict
              lda ##0
              sta long:LOGIC_BASE+ACTORAT,x
drPredict:    lsr dp:U_T2
              bcc drNextCell
              phx
              ldx dp:U_T0
              lda long:LOGIC_BASE+TILEMAP,x
              plx
              and ##255
              cmp ##0x80
              bcs drNextCell
              sta long:LOGIC_BASE+ACTORAT,x
drNextCell:   inc dp:U_T0
              lda dp:U_T0
              cmp ##4096
              bcc drCell
              stz dp:U_T0
drGap:        ldy ##4
              jsr abs:.word0 (gsGet)
              sta abs:.word0 (gsRg)
              clc
              adc dp:U_T0
              sta dp:U_T0
              cmp ##4097
              bcs drBad
              lda abs:.word0 (gsRg)
              cmp ##15
              beq drGap
              ldy ##8
              jsr abs:.word0 (gsGet)
              cmp ##GS_CODEEND
              beq drDone
              ldx dp:U_T0
              cpx ##4096
              bcs drBad
              cmp ##GS_CODEZERO
              beq drZero
              cmp ##GS_CODERAW
              beq drRawWord
              cmp ##MAXACTORS
              bcs drBad
              xba
              lsr a
              lsr a
              clc
              adc ##OBJLIST
              bra drPut
drZero:       lda ##0
              bra drPut
drRawWord:    ldy ##16
              jsr abs:.word0 (gsGet)
drPut:        pha
              lda dp:U_T0
              asl a
              tax
              pla
              sta long:LOGIC_BASE+ACTORAT,x
              inc dp:U_T0
              bra drGap
drBad:        lda ##1
              sta abs:.word0 (gsBitOver)
drDone:       rts

;;; ------------------------------------------------------------- G
;;; Bytes the sections above do not describe: TILEMAP, MAP0 and MAP1 away
;;; from K, the static slots past gsSn, the door slots past the doors and
;;; the door cell, side and lock words. None on a real floor. An entry is
;;; the even offset and the live word.
gsEncG:       lda ##0xffff
              sta abs:.word0 (gsGLast)
              jsr abs:.word0 (gsTileG)
              jsr abs:.word0 (gsMap0G)
              jsr abs:.word0 (gsMap1G)
              lda abs:.word0 (gsSn)
              asl a
              asl a
              asl a
              clc
              adc ##STATICS
              tax
egStat:       cpx ##DOORPOS
              bcs egDoors
              lda long:LOGIC_BASE,x
              beq egStatNext
              jsr abs:.word0 (gsGEntry)
egStatNext:   inx
              inx
              bra egStat
egDoors:      stz abs:.word0 (gsSi)
egDoor:       lda abs:.word0 (gsSi)
              cmp abs:.word0 (gsDoorN)
              bcs egdBlank
              asl a
              asl a
              tax
              lda long:GS_DOORS,x
              sta abs:.word0 (gsEd)
              lda long:GS_DOORS+2,x
              and ##255
              sta abs:.word0 (gsEd+2)
              lda long:GS_DOORS+2,x
              xba
              and ##255
              sta abs:.word0 (gsEd+4)
              bra egdOwn
egdBlank:     stz abs:.word0 (gsEd)
              stz abs:.word0 (gsEd+2)
              stz abs:.word0 (gsEd+4)
egdOwn:       lda abs:.word0 (gsSi)
              cmp long:LOGIC_BASE+V_doornum
              bcc egdFixed
              stz abs:.word0 (gsEd+6)
              lda ##DOORPOS
              jsr abs:.word0 (egdCheck)
              lda ##DOORACT
              jsr abs:.word0 (egdCheck)
              lda ##DOORTICS
              jsr abs:.word0 (egdCheck)
egdFixed:     lda abs:.word0 (gsEd)
              sta abs:.word0 (gsEd+6)
              lda ##DOORTILE
              jsr abs:.word0 (egdCheck)
              lda abs:.word0 (gsEd+2)
              sta abs:.word0 (gsEd+6)
              lda ##DOORVERT
              jsr abs:.word0 (egdCheck)
              lda abs:.word0 (gsEd+4)
              sta abs:.word0 (gsEd+6)
              lda ##DOORLOCK
              jsr abs:.word0 (egdCheck)
              inc abs:.word0 (gsSi)
              lda abs:.word0 (gsSi)
              cmp ##64
              bcc egDoor
              lda ##0xffff
              ldy ##16
              jmp abs:.word0 (gsPut)
;;; A = table. Door gsSi's word against gsEd+6.
egdCheck:     clc
              adc abs:.word0 (gsSi)
              adc abs:.word0 (gsSi)
              tax
              lda long:LOGIC_BASE,x
              cmp abs:.word0 (gsEd+6)
              beq egdSame
              jmp abs:.word0 (gsGEntry)
egdSame:      rts

;;; TILEMAP away from K, against gsTileByte's fresh byte. U_T0 cell, U_T1
;;; plane, U_T2 and U_T3 the door and side bytes, U_T5 the fresh byte.
gsTileG:      stz dp:U_T0
              stz dp:U_T1
tgCell:       lda dp:U_T0
              and ##7
              bne tgHave
              lda dp:U_T0
              lsr a
              lsr a
              lsr a
              tax
              lda long:GS_MARK,x
              sta dp:U_T2
              lda long:GS_SIDES,x
              sta dp:U_T3
tgHave:       lsr dp:U_T2
              bcs tgDoor
              ldx dp:U_T1
              lda long:RAW0_ADDRESS,x
              and ##255
              cmp ##106
              beq tgAmbush
              bcc tgWall
              lda ##0
tgWall:       lsr dp:U_T3
              bcc tgFresh
              ora ##0x40
              bra tgFresh
tgAmbush:     lsr dp:U_T3
              lda ##0
              bra tgFresh
tgDoor:       lsr dp:U_T3
              lda dp:U_T0
              jsr abs:.word0 (gsTileByte)
              and ##255
tgFresh:      sta dp:U_T5
              ldx dp:U_T0
              lda long:LOGIC_BASE+TILEMAP,x
              and ##255
              cmp dp:U_T5
              beq tgNext
              lda dp:U_T1
              clc
              adc ##4096
              jsr abs:.word0 (gsBitTest)
              bne tgNext
              lda dp:U_T0
              jsr abs:.word0 (gsGWord)
tgNext:       inc dp:U_T0
              lda dp:U_T0
              cmp ##4096
              bcs tgDone
              and ##63
              beq tgWrap
              lda dp:U_T1
              clc
              adc ##64
              sta dp:U_T1
              jmp abs:.word0 (tgCell)
tgWrap:       lda dp:U_T0
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:U_T1
              jmp abs:.word0 (tgCell)
tgDone:       rts

;;; MAP0 away from K: the capture list, else the raw plane. Two planes at a
;;; time while no listed plane is near. U_T0 plane, U_T3 the next listed.
gsMap0G:      stz abs:.word0 (gsMapI)
              stz dp:U_T0
              jsr abs:.word0 (m0Hold)
m0Pair:       lda dp:U_T0
              inc a
              cmp dp:U_T3
              bcs m0One
              ldx dp:U_T0
              lda long:RAW0_ADDRESS,x
              cmp long:LOGIC_BASE+MAP0,x
              bne m0One
              inx
              inx
              stx dp:U_T0
              cpx ##4096
              bcc m0Pair
              rts
m0One:        ldx dp:U_T0
              cpx dp:U_T3
              bne m0Raw
              lda abs:.word0 (gsMapI)
              asl a
              asl a
              tax
              lda long:GS_MAPS+2,x
              and ##255
              sta dp:U_T5
              inc abs:.word0 (gsMapI)
              jsr abs:.word0 (m0Hold)
              bra m0Cmp
m0Raw:        lda long:RAW0_ADDRESS,x
              and ##255
              sta dp:U_T5
m0Cmp:        ldx dp:U_T0
              lda long:LOGIC_BASE+MAP0,x
              and ##255
              cmp dp:U_T5
              beq m0Next
              txa
              clc
              adc ##4096
              jsr abs:.word0 (gsBitTest)
              bne m0Next
              lda dp:U_T0
              clc
              adc ##MAP0
              jsr abs:.word0 (gsGWord)
m0Next:       inc dp:U_T0
              lda dp:U_T0
              cmp ##4096
              bcc m0Pair
              rts
m0Hold:       lda abs:.word0 (gsMapI)
              cmp abs:.word0 (gsMapN)
              bcs m0HoldNone
              asl a
              asl a
              tax
              lda long:GS_MAPS,x
              sta dp:U_T3
              rts
m0HoldNone:   lda ##4096
              sta dp:U_T3
              rts

;;; MAP1 away from the K pushwall starts: the raw plane, a word at a time.
gsMap1G:      ldx ##0
m1Word:       lda long:RAW1_ADDRESS,x
              cmp long:LOGIC_BASE+MAP1,x
              bne m1Diff
m1Next:       inx
              inx
              cpx ##4096
              bcc m1Word
              rts
m1Diff:       stx dp:U_T0
              jsr abs:.word0 (m1Byte)
              lda dp:U_T0
              inc a
              tax
              jsr abs:.word0 (m1Byte)
              ldx dp:U_T0
              bra m1Next
;;; X = plane. A changed byte that is not a K pushwall start: a G entry.
m1Byte:       stx dp:U_T1
              jsr abs:.word0 (gsRaw1At)
              sta dp:U_T5
              lda long:LOGIC_BASE+MAP1,x
              and ##255
              cmp dp:U_T5
              beq m1Same
              lda dp:U_T5
              cmp ##GS_PUSHABLE
              bne m1Out
              txa
              clc
              adc ##4096
              jsr abs:.word0 (gsBitTest)
              bne m1Same
m1Out:        lda dp:U_T1
              clc
              adc ##MAP1
              jmp abs:.word0 (gsGWord)
m1Same:       rts

;;; A = a bank $30 byte offset. Its word goes out as a G entry, once.
gsGWord:      and ##0xfffe
              cmp abs:.word0 (gsGLast)
              beq gwDone
              sta abs:.word0 (gsGLast)
              tax
              lda long:LOGIC_BASE,x
              jmp abs:.word0 (gsGEntry)
gwDone:       rts

;;; X = bank $30 offset, A = its word: one G entry. X comes back.
gsGEntry:     sta abs:.word0 (gsGw)
              stx abs:.word0 (gsGx)
              txa
              ldy ##16
              jsr abs:.word0 (gsPut)
              lda abs:.word0 (gsGw)
              ldy ##16
              jsr abs:.word0 (gsPut)
              ldx abs:.word0 (gsGx)
              rts

;;; An entry's offset must be even, in TILEMAP to OBJLIST, in STATICS to
;;; VARS, or in MAP0 and MAP1.
gsDecG:       ldy ##16
              jsr abs:.word0 (gsGet)
              cmp ##0xffff
              beq dgDone
              sta abs:.word0 (gsGo)
              lsr a
              bcs dgBad
              lda abs:.word0 (gsGo)
              cmp ##OBJLIST
              bcc dgOk
              cmp ##STATICS
              bcc dgBad
              cmp ##VARS
              bcc dgOk
              cmp ##MAP0
              bcc dgBad
              cmp ##MAP1+4096
              bcs dgBad
dgOk:         ldy ##16
              jsr abs:.word0 (gsGet)
              ldx abs:.word0 (gsGo)
              sta long:LOGIC_BASE,x
              bra gsDecG
dgBad:        lda ##1
              sta abs:.word0 (gsBitOver)
dgDone:       rts

              .section savecode2, text, root
;;; JSL from the end of setup. The live floor is the baseline. Lists that
;;; do not fit leave gsBaseOk clear and the floor cannot be saved; on the
;;; 60 floors they fit (tools/check_save_bound.py).
gsCapture:    php
              rep #0x30
              phb
              phk
              plb
              jsr abs:.word0 (gsOwnClear)
              lda ##0
              sta abs:.word0 (gsActN)
              sta abs:.word0 (gsMapN)
              sta abs:.word0 (gsDoorN)
              sta long:gsBaseOk
              lda long:LOGIC_BASE+V_laststat
              sec
              sbc ##STATICS
              lsr a
              lsr a
              lsr a
              sta abs:.word0 (gsFreshStat)
              jsr abs:.word0 (gsBlankTail)
              ldx ##0
capRow:       stx abs:.word0 (gsPlane)
              sep #0x20
              lda long:RAW0_ADDRESS,x
              rep #0x20
              and ##255
              sta abs:.word0 (gsRaw)
              sep #0x20
              lda long:LOGIC_BASE+MAP0,x
              rep #0x20
              and ##255
              cmp abs:.word0 (gsRaw)
              beq capDoor
              sta abs:.word0 (gsHold)
              jsr abs:.word0 (capPushMap)
              bcc capDoor
              jmp abs:.word0 (capFail)
capDoor:      lda abs:.word0 (gsRaw)
              cmp ##90
              bcc capRowNext
              cmp ##102
              bcs capRowNext
              jsr abs:.word0 (gsCellFromPlane)
              jsr abs:.word0 (capPushDoor)
              bcc capRowNext
              jmp abs:.word0 (capFail)
capRowNext:   ldx abs:.word0 (gsPlane)
              inx
              txa
              and ##255
              bne capProgressRow
              jsl long:Progress2
capProgressRow:
              cpx ##4096
              bcs capCols
              jmp abs:.word0 (capRow)
capCols:      lda ##0
              sta abs:.word0 (gsXc)
capX:         lda ##0
              sta abs:.word0 (gsYc)
capY:         lda abs:.word0 (gsXc)
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:.word0 (gsYc)
              sta abs:.word0 (gsCell)
              lda abs:.word0 (gsYc)
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:.word0 (gsXc)
              sta abs:.word0 (gsPlane)
              jsr abs:.word0 (capActOne)
              bcc capKept
              jmp abs:.word0 (capFail)
capKept:      inc abs:.word0 (gsYc)
              lda abs:.word0 (gsYc)
              cmp ##64
              bcc capY
              inc abs:.word0 (gsXc)
              lda abs:.word0 (gsXc)
              and ##3
              bne capProgressX
              jsl long:Progress3
capProgressX:
              lda abs:.word0 (gsXc)
              cmp ##64
              bcc capX
              lda ##1
              sta long:gsBaseOk
capFail:      plb
              plp
              rtl

capActOne:    lda abs:.word0 (gsCell)
              asl a
              tax
              lda long:LOGIC_BASE+ACTORAT,x
              sta abs:.word0 (gsHold)
              ldx abs:.word0 (gsPlane)
              sep #0x20
              lda long:RAW0_ADDRESS,x
              rep #0x20
              and ##255
              cmp ##107
              bcc capWall
              lda ##0
capWall:      cmp abs:.word0 (gsHold)
              beq capActOk
              jsr abs:.word0 (capPushAct)
              rts
capActOk:     clc
              rts

capPushAct:   ldx abs:.word0 (gsActN)
              cpx ##GS_ACT_MAX
              bcs capSec
              txa
              asl a
              asl a
              tax
              lda abs:.word0 (gsCell)
              sta long:GS_ACTS,x
              lda abs:.word0 (gsHold)
              sta long:GS_ACTS+2,x
              inc abs:.word0 (gsActN)
              clc
              rts
capPushMap:   ldx abs:.word0 (gsMapN)
              cpx ##GS_MAP_MAX
              bcs capSec
              txa
              asl a
              asl a
              tax
              lda abs:.word0 (gsPlane)
              sta long:GS_MAPS,x
              lda abs:.word0 (gsHold)
              sta long:GS_MAPS+2,x
              inc abs:.word0 (gsMapN)
              clc
              rts
capPushDoor:  ldx abs:.word0 (gsDoorN)
              cpx ##GS_DOOR_MAX
              bcs capSec
              txa
              asl a
              asl a
              tax
              lda abs:.word0 (gsCell)
              sta long:GS_DOORS,x
              lda abs:.word0 (gsRaw)
              sec
              sbc ##90
              lsr a
              pha
              lda ##0
              rol a
              eor ##1
              sta abs:.word0 (gsTmp)
              pla
              xba
              ora abs:.word0 (gsTmp)
              sta long:GS_DOORS+2,x
              inc abs:.word0 (gsDoorN)
              clc
              rts
capSec:       sec
              rts

;;; Slots past this floor's statics and doors, and the padding after the
;;; area tables. The stream reads those bytes as zero.
gsBlankTail:  lda long:LOGIC_BASE+V_laststat
              tax
btStat:       cpx ##DOORPOS
              bcs btDoorIx
              lda ##0
              sta long:LOGIC_BASE,x
              inx
              inx
              bra btStat
btDoorIx:     lda long:LOGIC_BASE+V_doornum
btDoor:       cmp ##64
              bcs btConn
              asl a
              tax
              lda ##0
              sta long:LOGIC_BASE+DOORPOS,x
              sta long:LOGIC_BASE+DOORTILE,x
              sta long:LOGIC_BASE+DOORVERT,x
              sta long:LOGIC_BASE+DOORLOCK,x
              sta long:LOGIC_BASE+DOORACT,x
              sta long:LOGIC_BASE+DOORTICS,x
              txa
              lsr a
              inc a
              bra btDoor
btConn:       ldx ##1370
btConnWord:   cpx ##AREABYPLAYER-AREACONNECT
              bcs btPad
              lda ##0
              sta long:LOGIC_BASE+AREACONNECT,x
              inx
              inx
              bra btConnWord
btPad:        ldx ##64
btPadWord:    cpx ##VARS-AREABYPLAYER
              bcs btDone
              lda ##0
              sta long:LOGIC_BASE+AREABYPLAYER,x
              inx
              inx
              bra btPadWord
btDone:       rts

;;; Write every granted byte before a list or the window is read.
gsOwnClear:   ldx ##0
              lda ##0
ocLoop:       sta long:GS_BASE,x
              inx
              inx
              cpx ##GS_OWN
              bcc ocLoop
              rts

;;; Column cell of row-major gsPlane.
gsCellFromPlane:
              lda abs:.word0 (gsPlane)
              and ##63
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              sta abs:.word0 (gsTmp)
              lda abs:.word0 (gsPlane)
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              ora abs:.word0 (gsTmp)
              sta abs:.word0 (gsCell)
              rts

              .section gamedata, data, root
              .public gsWorldLen
gsHeader:     .space GS_OBJ
gsActN:       .word 0
gsMapN:       .word 0
gsDoorN:      .word 0
gsFreshStat:  .word 0                     ; fresh statics, captured at setup
gsWorldLen:   .word 0                     ; stream bytes
gsMapI:       .word 0                     ; the MAP0 list cursor
gsCell:       .word 0
gsPlane:      .word 0
gsRaw:        .word 0
gsWall:       .word 0
gsHold:       .word 0
gsTmp:        .word 0
gsXc:         .word 0
gsYc:         .word 0
gsB:          .word 0
gsDn:         .word 0
gsOff:        .word 0
gsStPlane:    .word 0
gsGo:         .word 0
gsGw:         .word 0
gsGx:         .word 0
gsGLast:      .word 0
gsBitV:       .word 0
gsBitAcc:     .word 0
gsBitN:       .word 0
gsBitCnt:     .word 0
gsBitPtr:     .word 0
gsBitOver:    .word 0                     ; the stream overflowed or did not decode
gsBitT:       .word 0
gsPofT:       .word 0
gsKfn:        .word 0
gsKb:         .word 0
gsKv:         .word 0
gsKc:         .word 0
gsKp:         .word 0
gsKf:         .word 0
gsKl:         .word 0
gsKs:         .word 0
gsKx:         .word 0
gsKy:         .word 0
gsKx0:        .word 0
gsKy0:        .word 0
gsKd:         .word 0
gsKj:         .word 0
gsMq:         .word 0
gsSi:         .word 0
gsSn:         .word 0
gsSo:         .word 0
gsRl:         .word 0
gsRg:         .word 0
gsRprev:      .word 0
gsEd:         .space 8
gsBitMasks:   .byte 1, 2, 4, 8, 16, 32, 64, 128
gsStBuf:      .space 8
gsStLive:     .space 8
;;; Sight rows point at the restored actors. JSL. The chains are in the
;;; actor records; only the row heads and the visible head live outside
;;; the snapshot, and a fresh floor left them naming the actors it spawned.
;;; The linker places this section in bank 2, so the bank $0D clear is
;;; copied here: a near jsr would enter the data bank instead.
              .section flowcode, text, root, noreorder
              .public RebuildSavedSight

RebuildSavedSight:
              php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              lda ##0
              ldx ##128
gsClearSight: sta long:SIGHT_ROWS,x
              dex
              dex
              bpl gsClearSight
              sta long:SIGHT_VISIBLE
              ldx ##OBJLIST
              lda abs:O_NEXT,x
              tax
gsSight:      beq gsSightDone
              lda abs:O_SX,x
              cmp ##64
              bcs gsSightVis
              lda abs:O_SPREV,x
              bne gsSightVis
              phx
              lda abs:O_SX,x
              asl a
              tax
              pla
              sta long:SIGHT_ROWS,x
              tax
gsSightVis:   lda abs:O_FLAGS,x
              bit ##8                      ; FL_VISABLE, kept with the actor
              beq gsSightNext
              lda abs:O_VPREV,x
              bne gsSightNext
              txa
              sta long:SIGHT_VISIBLE
gsSightNext:  lda abs:O_NEXT,x
              tax
              bra gsSight
gsSightDone:  pld
              plb
              plp
              rtl
