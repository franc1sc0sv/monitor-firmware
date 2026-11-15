# v1: Get VCP 0x60 reports the input actually shown (main-window port), not the port the query came in on.
# Replaces the case block at 0x26fc9b..0x26fcd3 (0x38 bytes); ends with a jump into the common reply tail at 0x26fcd3.
# port index (cfg[0xe5 + cfg[0xe4]]): 0 = DisplayPort -> 0x09, 1 = HDMI -> 0x06, other -> 0x0a (stock mapping)
@0x26fc9b
b.movi r7,0xe               # max value low byte = 0x0e (stock)
b.movhi r5,0x4c
b.sb 0x1b1e(r5),r7
b.movhi r6,0x3c
b.lwz r6,0x41b0(r6)         # r6 = cfg (pointer stored at 0x3c41b0)
b.lbz r7,0xe4(r6)           # current window index
b.add r6,r6,r7
b.lbz r5,0xe5(r6)           # r5 = port index of that window
b.movi r7,0x9
b.beqi r5,0x0,0x26fcc3
b.movi r7,0x6
b.beqi r5,0x1,0x26fcc3
b.movi r7,0xa
b.movhi r6,0x4c             # 0x26fcc3
b.sb 0x1b15(r6),r7          # current value low byte
b.j 0x26fcd3
