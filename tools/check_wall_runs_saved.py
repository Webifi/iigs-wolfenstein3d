"""Cold-save world proof, additionally checking every restored wall-run tag."""
import memmap
import check_saved_world as saved

saved.LUA = saved.LUA.replace('  say("RESTORED_CACHES 256 "..at//2)', memmap.fill('''  for x=0,63 do
    local first=0
    for y=0,63 do
      local cell=x*64+y
      local tile=r16(@MM:OLD_VISIBILITY+0x2000@+2*cell)
      if tile<1 or tile>=64 then first=y+1 end
      assert((r16(0x@wallRunCells@+2*cell)&63)==((y~first)&63), "restored vertical wall run "..cell)
    end
  end
  for y=0,63 do
    local first=0
    for x=0,63 do
      local cell=x*64+y
      local tile=r16(@MM:OLD_VISIBILITY+0x2000@+2*cell)
      if tile<1 or tile>=64 then first=x+1 end
      assert((r16(0x@wallRunCells@+2*cell)&0xfc0)==(((x~first)&63)<<6), "restored horizontal wall run "..cell)
    end
  end
  say("RESTORED_WALL_RUNS 4096")
  say("RESTORED_CACHES 256 "..at//2)'''))

if __name__ == '__main__':
    saved.main()
