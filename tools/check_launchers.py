"""Static audit of every tool that starts MAME: the kit binary directly, headless and silent.

python3 tools/check_launchers.py

A tool that passes -rompath starts MAME. It must name the kit binary (tools/mame_kit.py), pass -video none and
-sound none, and give the child SDL_VIDEODRIVER=dummy, SDL_AUDIODRIVER=dummy and SDL_MAC_BACKGROUND_APP=1.
No tool may ask for a window, real audio, the app bundle, a wrapper or the open command.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
NEED = {
    'the kit binary (mame_kit.BINARY)': r'mame_kit\.BINARY|from timedemo import[^\n]*\bMAME\b|timedemo\.MAME',
    '-video none': r'''['"]-video['"]\s*,\s*['"]none['"]''',
    '-sound none': r'''['"]-sound['"]\s*,\s*['"]none['"]''',
    'SDL_VIDEODRIVER=dummy': r'''SDL_VIDEODRIVER['"\]\s]*=\s*['"]dummy['"]''',
    'SDL_AUDIODRIVER=dummy': r'''SDL_AUDIODRIVER['"\]\s]*=\s*['"]dummy['"]''',
    'SDL_MAC_BACKGROUND_APP=1': r'''SDL_MAC_BACKGROUND_APP['"\]\s]*=\s*['"]1['"]''',
}
NEVER = {
    'real audio': r'coreaudio',
    'a window': r'''['"]-window['"]|['"]-video['"]\s*,\s*['"](soft|accel|opengl|bgfx)['"]|['"]cocoa['"]''',
    'a wrapper of the binary': r'mame-bg',
    'the open command': r'''['"]open['"]\s*,|osascript|\bopen -a\b''',
    'a kit named by hand': r'''/iigs-doom-test-builds/mame-[A-Za-z0-9-]+/iigs\.app''',
}


def main():
    problems = []
    launchers = 0
    for path in sorted((ROOT / 'tools').glob('*.py')):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text()
        for what, pattern in NEVER.items():
            if re.search(pattern, text):
                problems.append(f'{path.name}: asks for {what}')
        if '-rompath' not in text:
            continue
        launchers += 1
        for what, pattern in NEED.items():
            if not re.search(pattern, text):
                problems.append(f'{path.name}: starts MAME without {what}')
    for line in problems:
        print(line)
    print(f'{launchers} launchers, {len(problems)} problems')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
