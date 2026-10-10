"""Generate edition-specific New Game thumbnails with the linked native engine."""
import argparse
from frontend.floor_previews import build

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-shareware',action='store_true')
    build(parser.parse_args().export_shareware)
