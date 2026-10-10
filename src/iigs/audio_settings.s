#include "memmap.inc"
#include "sound_ids.inc"
              .section soundcode, text, root, noreorder
              .public LoadAudioSettings, AudioSettingKey
              .extern soundVolume, musicVolume, SetSoundVolume, SetMusicVolume
              .extern PlaySound, StartBonusFlash, StartDamageFlash, SaveAudioSettings

;;; The last sixteen bytes leave the rest of WOLF.SETTINGS to other options.
LoadAudioSettings:
              php
              rep #0x20
              pha
              lda long:AUDIO_SETTINGS
              cmp ##0x5357
              bne defaults
              lda long:AUDIO_SETTINGS+0x2
              cmp ##0x3144
              bne defaults
              lda long:AUDIO_SETTINGS+0x4
              eor ##0xa55a
              cmp long:AUDIO_SETTINGS+0x6
              bne defaults
              lda long:AUDIO_SETTINGS+0x4
              bit ##0xf0f0
              bne defaults
              and ##255
              sta long:soundVolume
              lda long:AUDIO_SETTINGS+0x4
              xba
              and ##255
              sta long:musicVolume
defaults:     pla
              plp
              rtl

;;; Called only for a key action, never from the idle frame path. DBR is 2.
AudioSettingKey:
              php
              rep #0x30
              pha
              phx
              phy
              and ##255
              cmp ##'B'
              beq quieterEffects
              cmp ##'V'
              beq louderEffects
              cmp ##'N'
              beq quieterMusic
              cmp ##'M'
              beq louderMusic
              cmp ##'K'
              beq saveAudio
              ply
              plx
              pla
              plp
              clc
              rtl
quieterEffects:
              lda long:soundVolume
              beq settingHandled
              dec a
              bra changeEffects
louderEffects:
              lda long:soundVolume
              cmp ##15
              bcs settingHandled
              inc a
changeEffects:jsl long:SetSoundVolume
              lda ##SELECTITEMSND
              jsl long:PlaySound
              bra settingHandled
quieterMusic: lda long:musicVolume
              beq settingHandled
              dec a
              bra changeMusic
louderMusic:  lda long:musicVolume
              cmp ##15
              bcs settingHandled
              inc a
changeMusic:  jsl long:SetMusicVolume
              bra settingHandled
saveAudio:    jsl long:SaveAudioSettings
              cmp ##0
              bne saveFailed
              jsl long:StartBonusFlash
              bra settingHandled
saveFailed:   lda ##18
              jsl long:StartDamageFlash
settingHandled:
              ply
              plx
              pla
              plp
              sec
              rtl

              .section sounddata, data, root
              .public settingsSaveStatus
settingsSaveStatus:.word 65535
