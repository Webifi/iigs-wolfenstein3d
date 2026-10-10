"""Observe logic boundaries without instrumenting the emulated program."""

from memmap import world

EVENTS = {
    'logic': (0x3f6, (('playerTicBegin', 1), ('advanceTicBegin', 1),
                     ('worldDoorsDone', 2), ('finishLogic', 3),
                     ('refreshObjects', 4), ('logicObjectsDone', 5),
                     ('ticFinished', 6), ('worldRunBegin', 7), ('worldRunDone', 8))),
    'world': (0x3f8, (('worldDoors', 1),)),
    'queue': (0x3f9, (('buildNewTiccmds', 1), ('buildDone', 0))),
}


def short_move_tap(symbols, memory='s'):
    if 'MoveObjShort' not in symbols:
        return ''
    pc = symbols['MoveObjShort']
    return f'''
shortMoveObserver={memory}:install_read_tap({pc},{pc},"short-move",function(a,d,m)
  local cpu=manager.machine.devices[":maincpu"]
  if manager.machine:side_effects_disabled() or cpu.state.PB.value~={pc>>16} then return end
  assert({memory}:read_u16(cpu.state.D.value+0x2e)==0,"MoveObj exceeds one tile")
end)
'''


def actor_pointer_taps(symbols, memory='s'):
    if 'actorBatchReturned' not in symbols:
        return ''
    entries=('actorBatchReturned','actorPublishReturned','actorLoopReturned',
             'actorCellReturned','moveFits','snapToTile')
    entries += tuple(name for name in ('sightActorCurrent','sightDelayCurrent') if name in symbols)
    lines=['actorPointerObservers={}']
    for index,name in enumerate(entries,1):
        pc=symbols[name]
        lines.append(f'''
actorPointerObservers[{index}]={memory}:install_read_tap({pc},{pc},"actor-pointer-{index}",function(a,d,m)
  local cpu=manager.machine.devices[":maincpu"]
  if manager.machine:side_effects_disabled() or cpu.state.PB.value~={pc>>16} then return end
  assert(cpu.state.X.value=={memory}:read_u16(cpu.state.D.value),"actor pointer changed at {name}")
end)
''')
    if 'actorOneTic' in symbols:
        pc=symbols['actorOneTic']
        lines.append(f'''
actorOneTicObserver={memory}:install_read_tap({pc},{pc},"actor-one-tic",function(a,d,m)
  local cpu=manager.machine.devices[":maincpu"]
  if manager.machine:side_effects_disabled() or cpu.state.PB.value~={pc>>16} then return end
  local ob=cpu.state.X.value
  assert(ob=={memory}:read_u16(cpu.state.D.value),"one-tic actor pointer changed")
  assert({memory}:read_u16({world(symbols)+symbols['V_tics']})==1,"actor batch tics changed")
  assert({memory}:read_u16({world(symbols)}+ob+{symbols['O_TICS']})<32768,"negative actor entry countdown")
end)
''')
    if 'connectedSight' in symbols:
        pc=symbols['connectedSight']
        lines.append(f'''
connectedSightObserver={memory}:install_read_tap({pc},{pc},"connected-sight",function(a,d,m)
  local cpu=manager.machine.devices[":maincpu"]
  if manager.machine:side_effects_disabled() or cpu.state.PB.value~={pc>>16} then return end
  local area={memory}:read_u16({world(symbols)}+cpu.state.X.value+{symbols['O_AREA']})
  assert({memory}:read_u8({world(symbols)+symbols['AREABYPLAYER']}+area)~=0,"sight entered a disconnected area")
end)
''')
    if 'playerThinkReady' in symbols:
        pc=symbols['playerThinkReady'];base=world(symbols)+symbols['OBJLIST']
        lines.append(f'''
playerThinkObserver={memory}:install_read_tap({pc},{pc},"player-think",function(a,d,m)
  local cpu=manager.machine.devices[":maincpu"]
  if manager.machine:side_effects_disabled() or cpu.state.PB.value~={pc>>16} then return end
  local state={memory}:read_u16({base+symbols['O_STATE']})
  assert(state=={symbols['s_player']} or state=={symbols['s_attack']},"player thinker state changed")
  assert({memory}:read_u16({base+symbols['O_TICS']})==0,"player acquired a state timer")
  assert(({memory}:read_u16({base+symbols['O_FLAGS']})&4)~=0,"player marks the actor map")
  assert(cpu.state.X.value=={symbols['OBJLIST']} and {memory}:read_u16(cpu.state.D.value)=={symbols['OBJLIST']},"player thinker pointer changed")
  local area={memory}:read_u16({base+symbols['O_AREA']})
  assert({memory}:read_u16({base+symbols['O_ACTIVE']})~=0 or {memory}:read_u8({world(symbols)+symbols['AREABYPLAYER']}+area)~=0,"player was inactive")
end)
''')
    return ''.join(lines)


def taps(symbols, kind, callback, memory='s', handle='logicTap'):
    address, entries = EVENTS[kind]
    if kind=='logic' and 'playerTicEnd' in symbols:
        entries += (('playerTicEnd',6),)
    if kind=='world' and 'worldDoorsIdle' in symbols:
        entries += (('worldDoorsIdle',2),)
    if 'playerTicBegin' not in symbols:
        return (f'{handle}={memory}:install_write_tap({address},{address},"{handle}",'
                f'function(a,d,m) {callback}(d) end)\n')
    # Ignore debugger reads and loader back-references into unpacked code.
    lines = [f'local {handle}Cpu=manager.machine.devices[":maincpu"]', f'{handle}={{}}']
    for index, (name, event) in enumerate(entries, 1):
        pc = symbols[name]
        lines.append(f'{handle}[{index}]={memory}:install_read_tap({pc},{pc},"{handle}-{index}",'
                     f'function(a,d,m) if not manager.machine:side_effects_disabled() and '
                     f'{handle}Cpu.state.PB.value=={pc>>16} then {callback}({event}) end end)')
    return '\n'.join(lines)+'\n'
