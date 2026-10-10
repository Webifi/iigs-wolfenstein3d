;;; The cold title song avoids disk prompts in the automatic title loop.
;;; The last floor's cold bank survives menus so returning to play needs no I/O.
#include "memmap.inc"
#include "game.inc"
#include "progress.inc"
#include "logic.inc"
              .section gamecode, text, root, noreorder
              .public SelectMusic, FloorMusic, CacheFloorMusic
              .public PrepareMusic, StartPreparedMusic
              .public currentSong, floorSong, songPending
              .extern levelIndex, StopMusic, StartMusic, musicLoaded
              .extern LoadMusicData, UiFwKeep, UiLoadSign
              .extern EnsureGameplayAssets

;;; A/X/Y, DBR and D survive. Native 16-bit A/X on entry.
FloorMusic:   pha
              lda long:floorSong
              jsl long:PrepareMusic
;;; A compressed song can invalidate game art. Finish every firmware read
;;; before starting the DOC clock and voices for this floor.
              jsl long:EnsureGameplayAssets
              jsl long:StartPreparedMusic
              pla
              rtl
SelectMusic:  jsl long:PrepareMusic
              jmp long:StartPreparedMusic

;;; Prepare a changed song without starting it over later blocking I/O.
;;; The caller publishes the new page/view, then calls StartPreparedMusic.
PrepareMusic: php
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              pha
              pea #0x0202
              plb
              plb
              lda ##0x1000
              tcd
              pla
              cmp abs:.word0 (currentSong)
              bne changeSong
              jmp abs:.word0 (songReturn)
changeSong:   sta abs:.word0 (wantedSong)
              stz abs:.word0 (songPending)
              jsl long:StopMusic
              lda ##3
              jsl long:UiLoadSign
              lda abs:.word0 (wantedSong)
              cmp abs:.word0 (floorSong)
              bne registeredDiskSong
              ldx abs:.word0 (floorColdPending)
              beq registeredDiskSong
              stz abs:.word0 (floorColdPending)
              jmp abs:.word0 (songReady)
registeredDiskSong:
              stz abs:.word0 (floorColdPending)
              jmp abs:.word0 (diskSong)
diskSong:     php
              sei
              ldx ##0x8200
              ldy ##0x4600
              lda ##0x1dff
              .byte 0x54, 0x3f, 0xe1
              lda long:wantedSong
              jsl long:LoadMusicData
              php
              jsl long:UiFwKeep
              ldx ##0x4600
              ldy ##0x8200
              lda ##0x1dff
              .byte 0x54, 0xe1, 0x3f
              plp
              bcc diskSongOK
              plp
              jmp abs:.word0 (songReturn)
diskSongOK:   plp
songReady:    jsl long:Progress22
              pea #0x0202
              plb
              plb
              lda abs:.word0 (wantedSong)
              sta abs:.word0 (currentSong)
              lda ##0
              sta long:musicLoaded
              inc abs:.word0 (songPending)
              lda ##4
              jsl long:UiLoadSign
songReturn:   pld
              plb
              ply
              plx
              pla
              plp
              rtl

;;; A/X/Y, DBR, D and flags survive; an unchanged song keeps its position.
StartPreparedMusic:
              php
              rep #0x30
              pha
              lda long:songPending
              beq preparedMusicDone
              lda ##0
              sta long:songPending
              jsl long:StartMusic
preparedMusicDone:
              pla
              plp
              rtl

;;; Bank $3E holds the newly read cold floor song. Called before StartMusic.
CacheFloorMusic:
              php
              rep #0x30
              pha
              phx
              phy
              phb
              lda long:levelIndex
              asl a
              tax
              lda long:floorSongs,x
              sta long:floorSong
              lda ##0xffff
              sta long:currentSong
              lda ##1
              sta long:floorColdPending
floorCached:  plb
              ply
              plx
              pla
              plp
              rts

              .section gamedata, data, root
currentSong:  .word 0xffff
floorSong:    .word 0xffff
floorColdBytes:.word 0
floorColdPending:.word 0
wantedSong:   .word 0xffff
songPending:  .word 0
              .public floorSongs
floorSongs:
#include "music_floors.inc"
