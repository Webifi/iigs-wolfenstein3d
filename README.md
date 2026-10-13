# Wolfenstein 3D for Apple IIgs based on original DOS release

> [!WARNING]
> This is a prerelease. Expect bugs and things that aren't finished.

The IIgs already has an excellent port of Wolfenstein 3D, so this is
probably pointless. But this is an attempt to get playable framerates on
a stock IIgs while keeping the gameplay from DOS all those years back.

The DOS engine was ported to 65816 assembly, then the expensive parts were
reworked around the IIgs. The original recorded demos were used to check
gameplay, with frame comparisons to catch rendering changes during optimization.

## What was done to make it faster

The main changes are:

- Draw straight to the screen. The original IIgs port draws into a buffer,
  then copies the whole view to screen memory each frame. This port normally
  draws there directly, avoiding that extra copy, but in slow scenes you
  can see the frame being painted.
- Do less wall math. The earlier IIgs and Mac ports use a BSP tree to
  find walls, then calculate where the ends of those walls appear on
  screen. That involves slow division on the 65816. This port starts from
  selected screen columns and searches the tile grid for the nearest wall,
  avoiding those wall-end calculations. It fills the gaps by interpolation
  and uses lookup tables for the expensive math.
- Precalculate the expensive parts. Lookup tables handle multiplication,
  ray setup and wall heights, while prepared drawing code handles scaling
  and clipping. Sight tables rule out enemy-to-player sight lines blocked
  by permanent walls before the slower map checks.
- Skip work that will not change the picture. Unchanged wall columns are
  reused, covered parts of sprites are skipped, and a completely unchanged
  view does not get repainted.

The price is a more bloated port: extra tables and prepared graphics take
more RAM and storage. Rebuilding some of that data during loading saves
disk space, but adds load time.

## Why does it look different?

Dither lookup tables mix the 16 colors in each level's palette into patterns
that approximate more colors. That can preserve a little more illusion of
detail than the original IIgs port, but the dithering can also make the
render grainier and uglier. Distance shading adds some depth.

The weapons use the original DOS sprites, drawn at the same resolution as
the rest of the view, like the DOS game. The earlier IIgs and Mac ports
draw a separate, higher-resolution weapon image over the scene. This port
keeps weapon edges on the same two-pixel boundaries as the world renderer.
Two pixels share each screen byte, so that avoids extra masking where the
weapon and background would otherwise share a byte.

## Display settings

These are under Options → Display & Sound. On first start the game runs a
quick speed test and picks a view size for your machine: 2/3 on a stock
IIgs, 3/4 with a ZipGS or TransWarp GS, and full with an AppleSqueezer GS.
You can change any of them and save.

- **View Size** (1/2, 2/3, 3/4, Full): smaller is faster. `-` and `=` change
  it while you play.
- **Depth Shading**: darkens things with distance. Turn it off if you'd
  rather have the flat look. `P` toggles it while you play.
- **Vsync**: waits for the vertical blank before painting. Less tearing if 
  your CPU is fast enough, but it costs speed. Off by default.
- **Painting**:
  - **Direct** (default) draws straight to the screen. It's the fastest on a
    stock IIgs, but in slow scenes you can see the frame being painted.
  - **Buffered** paints off-screen first, then copies it over, so it now paints
    top to bottom as fast as it can after the frame was rendered to the buffer
    left to right. With a small enough view and fast enough CPU, can be combined with Vsync, but again costs CPU cycles for the extra copy.
- **Fast walls** skips repainting the parts of a wall that come out the same
  color as what's already on screen, which saves the most when a wall fills
  the screen. On by default with an accelerator, off on a stock IIgs since the check can cost more than it saves on slower CPUs.
- **Fast transparency** (on by default): uses simplified versions of some of the
  more complex sprites like tables, chairs and vines, so they draw faster. Each
  transition from colored pixel to transparent requires setup and clipping every
  time that column is drawn, so fewer transitions reduce work. Turn it off for 
  the original artwork.

## Where it stands

The original campaigns are running, and the stock-speed results are okayish.
Some scenes still get too slow, especially with lots of enemies or items.

## System requirements

- Apple IIgs at 2.8 MHz or faster, with a 4 MB memory expansion card.
- ADB keyboard, or a J13 keyboard on ROM 00/01. Mouse optional.
- A bootable hard disk device is recommended. One 800K 3.5-inch floppy drive
  is supported if needed, but slow loading and frequent disk swaps make
  floppy use hard to recommend.

## Projects used

- [id Software's Wolfenstein 3D source](https://github.com/id-Software/wolf3d).
- Calypsi, Python, NumPy, Pillow and Tomli for the build tools.
- [Nuked-SC55](https://github.com/jcmoyer/Nuked-SC55) and Nuked-OPL3 for the audio tools.
- MAME for emulation and testing.

## Were AI coding agents used?

Of course. Who in their right mind would take the time to do something like
this without it today? Could I have done it without AI? Sure. Would I have?
Absolutely not.

## Wanna try?

You can grab the latest build of the shareware Wolfenstein 3D for IIgs from
[here](https://github.com/Webifi/iigs-wolfenstein3d/releases).

If you want to try the full Wolfenstein 3D or Spear of Destiny and you have
the data files from the original DOS releases, you can try [building your own release with them](BUILD.md).
