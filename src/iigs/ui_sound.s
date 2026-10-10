;;; Menu sound interface. UI_SOUND selects the sound-module calls;
;;; otherwise the same entry points are silent stubs. SoundPresent reports
;;; which implementation was compiled.
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public SoundPlay, SoundPresent, SoundVolGet, SoundVolSet, MusicVolGet, MusicVolSet
              .public SoundRecordLoad, SoundRecordStore, SoundLevels
              .public SoundStop
#if UI_SOUND
              .extern PlaySound, SetSoundVolume, SetMusicVolume, soundVolume, musicVolume
              .extern LoadAudioSettings, StopMusic, StopEffects

SoundPresent: lda ##1
              rts
;;; A = sound event ID (sound_ids.inc).
SoundPlay:    jsl long:PlaySound
              rts
SoundStop:    jsl long:StopMusic
              jsl long:StopEffects
              rts
SoundVolGet:  lda long:soundVolume
              rts
MusicVolGet:  lda long:musicVolume
              rts
;;; A = 0..15: update the volume immediately; zero mutes the channel.
SoundVolSet:  jsl long:SetSoundVolume
              rts
MusicVolSet:  jsl long:SetMusicVolume
              rts

;;; The levels of the settings block, in the last 16 bytes of the image
;;; (SOUND_CONTROLS.md): "WSD1", the effects and music bytes, the same two
;;; bytes XOR $A55A, eight zero bytes. The sound code reads them back.
SoundRecordLoad:
              jsl long:LoadAudioSettings
              rts
SoundRecordStore:
              lda long:musicVolume
              and ##15
              xba
              sta dp:U_T2
              lda long:soundVolume
              and ##15
              ora dp:U_T2
              sta dp:U_T2
              lda ##0x5357
              sta long:SETTINGS_IN + 496
              lda ##0x3144
              sta long:SETTINGS_IN + 498
              lda dp:U_T2
              sta long:SETTINGS_IN + 500
              eor ##0xa55a
              sta long:SETTINGS_IN + 502
              lda ##0
              sta long:SETTINGS_IN + 504
              sta long:SETTINGS_IN + 506
              sta long:SETTINGS_IN + 508
              sta long:SETTINGS_IN + 510
              rts
;;; A = the two levels in one number, for the test whether they changed.
SoundLevels:  lda long:musicVolume
              and ##15
              asl a
              asl a
              asl a
              asl a
              sta dp:U_T2
              lda long:soundVolume
              and ##15
              clc
              adc dp:U_T2
              rts
#else
SoundPresent: lda ##0
              rts
SoundPlay:    rts
SoundStop:    rts
SoundVolGet:  lda abs:.word0 (stubSound)
              rts
MusicVolGet:  lda abs:.word0 (stubMusic)
              rts
SoundVolSet:  sta abs:.word0 (stubSound)
              rts
MusicVolSet:  sta abs:.word0 (stubMusic)
              rts
SoundRecordLoad:
SoundRecordStore:
              rts
SoundLevels:  lda ##0
              rts
              .section menudata, data, root
stubSound:    .word 15
stubMusic:    .word 15
#endif
