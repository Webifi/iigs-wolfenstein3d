#!/usr/bin/env python3
"""Inspect DOS inputs for the Apple IIgs image builder (Python 3.9 or newer)."""
import argparse
import json
from pathlib import Path
import struct

from dos_data import DosData, detect
from game_profile import PROFILES
from music_pack import MusicPack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('profiles', help='list the separate game-data profiles')
    discover = commands.add_parser('discover', help='find installed campaigns, including shared Spear mission assets')
    discover.add_argument('--data', required=True, type=Path)
    discover.add_argument('--out', type=Path)
    inspect = commands.add_parser('inspect', help='decode and check the supplied DOS data')
    inspect.add_argument('--data', required=True, type=Path, help='folder containing the original DOS files')
    inspect.add_argument('--profile', default='auto', help='built-in profile name or custom TOML file')
    inspect.add_argument('--shared-data', type=Path, help='original Spear folder used alongside a mission pack')
    inspect.add_argument('--music-pack', type=Path, help='also check a prepared music pack for this game')
    inspect.add_argument('--out', type=Path, help='write the JSON report to this file')
    campaign = commands.add_parser('inspect-campaign', help='validate campaign routes and source resource requirements')
    campaign.add_argument('--data', required=True, type=Path)
    campaign.add_argument('--profile', default='auto', help='built-in source profile or custom TOML')
    campaign.add_argument('--shared-data', type=Path)
    campaign.add_argument('--native-capabilities', type=Path, help='engine-owned capability TOML; does not prove allocation or gameplay')
    campaign.add_argument('--require-supported', action='store_true', help='fail on unsupported native capabilities or source meanings')
    campaign.add_argument('--out', type=Path)
    music = commands.add_parser('inspect-music', help='check prepared music without DOS data or synthesizer tools')
    music.add_argument('--profile', default='shareware', help='built-in profile name or custom TOML file')
    music.add_argument('--music-pack', required=True, type=Path, help='pack folder, pack.toml or legacy manifest.json')
    music.add_argument('--out', type=Path, help='write the JSON report to this file')
    args = parser.parse_args()
    try:
        if args.command == 'profiles':
            result = [dict(profile=p.key, title=p.title, files=p.files, floors=p.floors,
                           public_game_data=p.public_game_data) for p in PROFILES.values()]
        elif args.command == 'discover':
            from source_discovery import discover as discover_sources
            result = discover_sources(args.data)
        elif args.command == 'inspect-music':
            result = MusicPack(args.music_pack, args.profile).inspect()
        elif args.command == 'inspect-campaign':
            from campaign_manifest import compile_manifest, require_supported
            selected = detect(args.data, args.shared_data) if args.profile == 'auto' else args.profile
            result = compile_manifest(DosData(args.data, selected, args.shared_data), args.native_capabilities)
        else:
            selected = detect(args.data, args.shared_data) if args.profile == 'auto' else args.profile
            result = DosData(args.data, selected, args.shared_data).inspect()
            if args.music_pack:
                result['prepared_music'] = MusicPack(args.music_pack, selected).inspect()
        text = json.dumps(result, indent=2) + '\n'
        if getattr(args, 'out', None):
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding='utf-8')
        else:
            print(text, end='')
        if args.command == 'inspect-campaign' and args.require_supported:
            require_supported(result)
    except (OSError, ValueError, IndexError, struct.error) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
