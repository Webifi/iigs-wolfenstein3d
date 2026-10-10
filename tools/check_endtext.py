"""Check the selected quit-page conversion against every source text row."""
from endtext import convert, apple_row, ROWS, COLUMNS, SHADING, BOX
from wolfdata import source_data


def main():
    source = source_data()
    chunks = source.graphics()
    chunk = chunks[source.graphics_layout['roles']['quit_text']]
    data, keep = convert(chunk)
    page = chunk[7:4007:2]
    assert len(data) == ROWS*COLUMNS
    for row in range(25):
        chars = page[row*COLUMNS:(row+1)*COLUMNS]
        if row not in keep:
            assert set(chars) <= SHADING | BOX | {0, 0x20, 0xff}, row
    for output, original in enumerate(keep):
        chars = page[original*COLUMNS:(original+1)*COLUMNS]
        mapped = apple_row(chars)
        assert data[output*COLUMNS:(output+1)*COLUMNS] == mapped[::2]+mapped[1::2]
    assert convert(chunk[:4007]) == (data, keep)
    for bad in (chunk[:100], bytes(len(chunk)), chunk[:-1]+b'!'):
        try:
            convert(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid BLOAD accepted')
    print(f'{source.profile.key}: all source text and block-art rows retained; {len(keep)} ROM rows')


if __name__ == '__main__':
    main()
