# v2: event log inside the LC34G55T firmware (installed 1006.0), exposed over DDC/CI.
# Assembled against the full RAM image (prefix + AP at 0x200000).
#
# RAM block EV = 0x4fe6b0 .. 0x4feab0 (1 KB). Obtained by moving the heap start (sbrk base word at 0x4c1390)
# and the BSS-clear end bound (prefix 0x2001a7) up by 0x400, so the block is zeroed on every boot.
#   +0x00 u32 magic 'EVT1' (0x45565431)      +0x04 u16 seq (events logged, wraps)
#   +0x06 u16 cursor (set via VCP 0xEB)      +0x08 u8 ms within the current 10 ms (timer ISR)
#   +0x0c u8[8] snapshot of watched values   +0x14 u8 pending switch target port (0x0f = none)
#   +0x18 u32 time of pending request        +0x1c u32 now (10 ms units, incremented by the 1 ms timer ISR hook)
#   +0x20 ring: 64 records x 8 bytes: u16 seq, u8 id, u8 old, u8 new, u8[3] time (10 ms, LE)
#   +0x230 u16 scan offset  +0x232 u8 scan budget  +0x234 u16 addr high  +0x236 u16 addr low  +0x238 u8 shadow ready
#   +0x400 shadow of 0x204000..0x2041ff (512 B)   +0x600 ignore mask (64 B, bit n = settings offset n)
# Block is 2 KB (0x4fe6b0..0x4feeb0).
#
# Event ids: 0x00 boot | 0x01 input port | 0x02 source select cfg[0xde] | 0x03 power/flags cfg[0xd7]
#   0x04 power-save flags (low byte 0x4ca78c) | 0x05 active-port sync flags (+0x1c) | 0x06 signal present
#   0x07 system state (low byte 0x4cebe4) | 0x08 window/port var 0x4ec92d
#   0x10 DDC input-switch request (old = port, new = VCP value)
#   0x11 switch done: target port active and picture locked (old = target, new = port)
#   0x12 switch failed: no locked picture on the target within 8 s (old = target, new = port) | 0x13 DDC power-mode request (new = value)
#
# VCP (manufacturer range, all free in the stock Get table):
#   Get 0xEA: MH=0x40 ring size, ML=0x02 version, CH:CL = seq
#   Set/Get 0xEB: cursor (seq number of the record to read)
#   Get 0xEC: record at cursor: MH=id, ML=old, CH=new, CL=record seq low byte (match against cursor)
#   Get 0xED: record time: MH=record seq low byte, ML:CH:CL = 24-bit time in 10 ms units
#   Get 0xEE: live: MH=input port, ML=cfg[0xde], CH=cfg[0xd7], CL=signal present
#   Get 0xEF: now: 32-bit time in 10 ms units

# ---------------------------------------------------------------- v1: Get 0x60 reports the real input
@0x26fc9b
b.movi r7,0xe
b.movhi r5,0x4c
b.sb 0x1b1e(r5),r7
b.movhi r6,0x3c
b.lwz r6,0x41b0(r6)
b.lbz r7,0xe4(r6)
b.add r6,r6,r7
b.lbz r5,0xe5(r6)
b.movi r7,0x9
b.beqi r5,0x0,@g60_store
b.movi r7,0x6
b.beqi r5,0x1,@g60_store
b.movi r7,0xa
g60_store:
b.movhi r6,0x4c
b.sb 0x1b15(r6),r7
b.j 0x26fcd3

# ---------------------------------------------------------------- memory reservation
@0x2001a7
b.ori r4,r4,0xeeb0              # BSS clear now ends at 0x4feeb0 (2 KB block)
@0x4c1390
.le32 0x004feeb0                # heap (sbrk) starts after our block

# ---------------------------------------------------------------- hooks
@0x24d885
b.j @tickhook                   # end of the 1 ms timer ISR: was tail call j 0x28ba15
@0x26b6d3
b.jal @poll                     # main loop: was jal 0x212fc6 (DDC service)
@0x27123d
b.jal @sethook                  # Set VCP dispatch: was jal 0x270b45
@0x3777b8                       # Get table entries 0xEA..0xEF (0x377410 + 0xEA*4)
.le32 @get_ea
.le32 @get_eb
.le32 @get_ec
.le32 @get_ed
.le32 @get_ee
.le32 @get_ef
@0x3777d0                       # Get table entries 0xF0, 0xF1, 0xF2
.le32 @get_f0
.le32 @get_f1
.le32 @get_f2

# ---------------------------------------------------------------- code cave (end-of-.text padding)
@0x399820
poll:
b.addi r1,r1,-0x8
b.sw 0x4(r1),r9
b.jal 0x212fc6                  # original DDC service
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0              # r8 = EV
b.lwz r7,0x0(r8)
b.movhi r6,0x4556
b.ori r6,r6,0x5431
b.beq r7,r6,@tick
# first run after boot: magic, sentinel snapshot (so the first pass logs the initial state), no pending switch
b.sw 0x0(r8),r6
b.movhi r6,0xeeee
b.ori r6,r6,0xeeee
b.sw 0xc(r8),r6
b.sw 0x10(r8),r6
b.movi r7,0xf
b.sb 0x14(r8),r7
b.movi r3,0x0
b.movi r4,0x0
b.movi r5,0x0
b.jal @log                      # boot event
tick:
# watch 1: input port
b.jal @getport
b.lbz r4,0xc(r8)
b.beq r4,r5,@w2
b.sb 0xc(r8),r5
b.movi r3,0x1
b.jal @log
w2:
b.movhi r6,0x3c
b.lwz r6,0x41b0(r6)
b.lbz r5,0xde(r6)
b.lbz r4,0xd(r8)
b.beq r4,r5,@w3
b.sb 0xd(r8),r5
b.movi r3,0x2
b.jal @log
w3:
b.movhi r6,0x3c
b.lwz r6,0x41b0(r6)
b.lbz r5,0xd7(r6)
b.lbz r4,0xe(r8)
b.beq r4,r5,@w4
b.sb 0xe(r8),r5
b.movi r3,0x3
b.jal @log
w4:
b.movhi r6,0x4d
b.lbz r5,-0x5874(r6)            # 0x4ca78c low byte
b.lbz r4,0xf(r8)
b.beq r4,r5,@w5
b.sb 0xf(r8),r5
b.movi r3,0x4
b.jal @log
w5:
b.jal @portstruct               # r6 = port struct of the active port
b.lbz r5,0x1c(r6)
b.lbz r4,0x10(r8)
b.beq r4,r5,@w6
b.sb 0x10(r8),r5
b.movi r3,0x5
b.jal @log
w6:
b.jal @portstruct
b.lhz r7,0x22(r6)               # horizontal frequency, 0 = no signal
b.movi r5,0x0
b.beqi r7,0x0,@w6_cmp
b.movi r5,0x1
w6_cmp:
b.lbz r4,0x11(r8)
b.beq r4,r5,@w7
b.sb 0x11(r8),r5
b.movi r3,0x6
b.jal @log
w7:
b.movhi r6,0x4d
b.lbz r5,-0x141c(r6)            # 0x4cebe4 low byte
b.lbz r4,0x12(r8)
b.beq r4,r5,@w8
b.sb 0x12(r8),r5
b.movi r3,0x7
b.jal @log
w8:
b.movhi r6,0x4f
b.lbz r5,-0x36d3(r6)            # 0x4ec92d
b.lbz r4,0x13(r8)
b.beq r4,r5,@scan
b.sb 0x13(r8),r5
b.movi r3,0x8
b.jal @log
scan:
# settings scanner: compares 8 bytes per pass of cfg/settings RAM 0x204000..0x2041ff against a shadow copy
# (EV+0x400). First full sweep only fills the shadow (EV+0x238 = 0 until it wraps). Offsets whose bit is set in the
# mask at EV+0x600 are ignored. Event id 0x20 | (offset >> 8), old = offset low byte, new = new value.
b.movi r7,0x8
b.sb 0x232(r8),r7               # bytes left in this pass
scan_loop:
b.lhz r4,0x230(r8)              # offset
b.movhi r6,0x20
b.ori r6,r6,0x4000
b.add r6,r6,r4
b.lbz r5,0x0(r6)                # current value
b.add r7,r8,r4
b.lbz r6,0x400(r7)              # shadow value
b.beq r5,r6,@scan_next
b.sb 0x400(r7),r5
b.lbz r6,0x238(r8)
b.beqi r6,0x0,@scan_next        # still filling the shadow
b.srli r6,r4,0x3
b.add r6,r6,r8
b.lbz r6,0x600(r6)              # mask byte
b.andi r7,r4,0x7
b.srl r6,r6,r7
b.andi r6,r6,0x1
b.bnei r6,0x0,@scan_next        # ignored offset
b.srli r3,r4,0x8
b.ori r3,r3,0x20
b.andi r4,r4,0xff
b.jal @log
scan_next:
b.lhz r4,0x230(r8)
b.addi r4,r4,0x1
b.andi r4,r4,0x1ff
b.sh 0x230(r8),r4
b.bnei r4,0x0,@scan_cnt
b.movi r7,0x1
b.sb 0x238(r8),r7               # first sweep done: start reporting
scan_cnt:
b.lbz r7,0x232(r8)
b.addi r7,r7,-0x1
b.sb 0x232(r8),r7
b.bnei r7,0x0,@scan_loop
pend:
b.lbz r4,0x14(r8)               # pending target port
b.beqi r4,0xf,@done
b.jal @getport
b.lbz r4,0x14(r8)
b.bne r4,r5,@pend_time          # not on the target port yet
b.jal @portstruct
b.lbz r7,0x1c(r6)
b.sfeqi r7,0xa                  # sync flags 0x0a = picture locked (seen on both DP and HDMI)
b.bnf @pend_time
b.jal @getport
b.lbz r4,0x14(r8)
b.ori r3,r0,0x11                  # switch done: on target port with a locked picture
b.jal @log
b.movi r7,0xf
b.sb 0x14(r8),r7
b.j @done
pend_time:
b.lwz r6,0x1c(r8)
b.lwz r7,0x18(r8)
b.sub r6,r6,r7
b.sfgtui r6,0x320               # 800 x 10 ms = 8 s without a locked picture on the target port
b.bnf @done
b.ori r3,r0,0x12                  # switch failed
b.jal @log
b.movi r7,0xf
b.sb 0x14(r8),r7
done:
b.lwz r9,0x4(r1)
b.addi r1,r1,0x8
b.jr r9

# 1 ms timer ISR tail: EV+0x08 counts ms 0..9, EV+0x1c counts 10 ms units; then the stock tail callee.
tickhook:
b.movhi r6,0x4f
b.ori r6,r6,0xe6b0
b.lbz r7,0x8(r6)
b.addi r7,r7,0x1
b.sb 0x8(r6),r7
b.sfgtui r7,0x9
b.bnf @th_out
b.sb 0x8(r6),r0
b.lwz r7,0x1c(r6)
b.addi r7,r7,0x1
b.sw 0x1c(r6),r7
th_out:
b.j 0x28ba15

# r5 = port index of the main window (cfg[0xe5 + cfg[0xe4]]); clobbers r6, r7
getport:
b.movhi r6,0x3c
b.lwz r6,0x41b0(r6)
b.lbz r7,0xe4(r6)
b.add r6,r6,r7
b.lbz r5,0xe5(r6)
b.jr r9

# r6 = 0x3c3440 + port*0x8c (port struct of the main-window port); clobbers r5, r7
portstruct:
b.movhi r6,0x3c
b.lwz r6,0x41b0(r6)
b.lbz r7,0xe4(r6)
b.add r6,r6,r7
b.lbz r5,0xe5(r6)
b.andi r5,r5,0x3
b.ori r7,r0,0x8c
b.mul r7,r7,r5
b.movhi r6,0x3c
b.addi r6,r6,0x3440
b.add r6,r6,r7
b.jr r9

# log(r3 = id, r4 = old, r5 = new); r8 = EV; clobbers r6, r7
log:
b.lhz r6,0x4(r8)
b.addi r6,r6,0x1
b.sh 0x4(r8),r6
b.andi r7,r6,0x3f
b.slli r7,r7,0x3
b.add r7,r7,r8
b.sh 0x20(r7),r6
b.sb 0x22(r7),r3
b.sb 0x23(r7),r4
b.sb 0x24(r7),r5
b.lwz r6,0x1c(r8)
b.sb 0x25(r7),r6
b.srli r6,r6,0x8
b.sb 0x26(r7),r6
b.srli r6,r6,0x8
b.sb 0x27(r7),r6
b.jr r9

# Set VCP hook: called with r9 = return into the dispatcher. VCP code at 0x4c1b14, value hi/lo at 0x4c1b1f/0x4c1b1e.
sethook:
b.movhi r7,0x4c
b.lbz r6,0x1b14(r7)
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.lbz r5,0x1b1f(r7)
b.slli r5,r5,0x8
b.lbz r4,0x1b1e(r7)
b.or r5,r5,r4                   # r5 = 16-bit value, r4 = low byte
b.sfeqi r6,0xf0
b.bnf @sh_f1
b.sh 0x234(r8),r5               # address high half (EV+0x234); low half lives at EV+0x236
b.j @sh_ok
sh_f1:
b.sfeqi r6,0xf1
b.bnf @sh_f4
b.sh 0x236(r8),r5
b.j @sh_ok
sh_f4:
b.sfeqi r6,0xf4
b.bnf @sh_f6
b.addi r1,r1,-0x8
b.sw 0x4(r1),r9                 # helpers below are called with jal
b.jal @peekaddr                 # r7 = address (r6 clobbered)
b.movhi r6,0x20
b.ori r6,r6,0x4000
b.sfgtu r6,r7                   # below 0x204000 -> refuse
b.bf @f4_out
b.movhi r6,0x20
b.ori r6,r6,0x4400
b.sfleu r6,r7                   # at or above 0x204400 -> refuse
b.bf @f4_out
b.sb 0x0(r7),r4                 # poke one settings byte
b.addi r7,r7,0x1
b.jal @setaddr
f4_out:
b.lwz r9,0x4(r1)
b.addi r1,r1,0x8
b.j @sh_ok
sh_f6:
b.sfeqi r6,0xf6
b.bnf @sh_eb
b.sfgtui r4,0x6e
b.bf @sh_ok                     # unknown menu item -> ignore
b.addi r1,r1,-0x8
b.sw 0x4(r1),r9
b.mov r3,r4
b.movi r4,0x1
b.jal 0x284884                  # apply menu item and save, exactly as the OSD/DDC path does
b.lwz r9,0x4(r1)
b.addi r1,r1,0x8
sh_ok:
b.movi r3,0x0
b.jr r9
sh_eb:
b.movhi r7,0x4c
b.sfeqi r6,0xeb
b.bnf @sh_60
# Set 0xEB: cursor = value
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.lbz r6,0x1b1f(r7)
b.slli r6,r6,0x8
b.lbz r5,0x1b1e(r7)
b.or r6,r6,r5
b.sh 0x6(r8),r6
b.movi r3,0x0
b.jr r9
sh_60:
b.sfeqi r6,0x60
b.bf @sh_log
b.sfeqi r6,0xd6
b.bf @sh_log
b.j 0x270b45                    # anything else: stock Set handler (tail call)
sh_log:
b.addi r1,r1,-0x8
b.sw 0x4(r1),r9
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.lwz r7,0x0(r8)
b.movhi r5,0x4556
b.ori r5,r5,0x5431
b.bne r7,r5,@sh_out             # log not initialised yet
b.jal @getport
b.mov r4,r5
b.movhi r7,0x4c
b.lbz r5,0x1b1e(r7)
b.lbz r6,0x1b14(r7)
b.ori r3,r0,0x13
b.sfeqi r6,0x60
b.bnf @sh_dolog
b.ori r3,r0,0x10
sh_dolog:
b.jal @log
b.movhi r7,0x4c
b.lbz r6,0x1b14(r7)
b.sfeqi r6,0x60
b.bnf @sh_out
b.lbz r5,0x1b1e(r7)             # value -> target port: 9 -> 0 (DP), 6 -> 1 (HDMI), else none
b.movi r4,0x0
b.beqi r5,0x9,@sh_req
b.movi r4,0x1
b.beqi r5,0x6,@sh_req
b.movi r4,0xf
sh_req:
b.sb 0x14(r8),r4
b.lwz r6,0x1c(r8)
b.sw 0x18(r8),r6
sh_out:
b.lwz r9,0x4(r1)
b.addi r1,r1,0x8
b.j 0x270b45                    # stock Set handler with the original return address

# Get handlers: fill MH 0x4c1b1f, ML 0x4c1b1e, CH 0x4c1b18, CL 0x4c1b15, then the stock reply tail.
# Only r5-r8 are used; r11/r12/r13 belong to the stock Get handler.
get_ea:
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.movhi r6,0x4c
b.ori r7,r0,0x40
b.sb 0x1b1f(r6),r7
b.movi r7,0x2
b.sb 0x1b1e(r6),r7
b.lhz r5,0x4(r8)
b.j @put_chcl
get_eb:
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.movhi r6,0x4c
b.sb 0x1b1f(r6),r0
b.sb 0x1b1e(r6),r0
b.lhz r5,0x6(r8)
b.j @put_chcl
get_ec:
b.jal @recptr                   # r7 = record, r6 = 0x4c0000
b.lbz r5,0x22(r7)
b.sb 0x1b1f(r6),r5
b.lbz r5,0x23(r7)
b.sb 0x1b1e(r6),r5
b.lbz r5,0x24(r7)
b.sb 0x1b18(r6),r5
b.lbz r5,0x20(r7)
b.sb 0x1b15(r6),r5
b.j 0x26fcd3
get_ed:
b.jal @recptr
b.lbz r5,0x20(r7)
b.sb 0x1b1f(r6),r5
b.lbz r5,0x27(r7)
b.sb 0x1b1e(r6),r5
b.lbz r5,0x26(r7)
b.sb 0x1b18(r6),r5
b.lbz r5,0x25(r7)
b.sb 0x1b15(r6),r5
b.j 0x26fcd3
get_ee:
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.movhi r6,0x4c
b.lbz r5,0xc(r8)
b.sb 0x1b1f(r6),r5
b.lbz r5,0xd(r8)
b.sb 0x1b1e(r6),r5
b.lbz r5,0xe(r8)
b.sb 0x1b18(r6),r5
b.lbz r5,0x11(r8)
b.sb 0x1b15(r6),r5
b.j 0x26fcd3
get_ef:
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.movhi r6,0x4c
b.lwz r5,0x1c(r8)
b.srli r7,r5,0x18
b.sb 0x1b1f(r6),r7
b.srli r7,r5,0x10
b.sb 0x1b1e(r6),r7
put_chcl:                        # CH:CL = r5 (low 16 bits); r6 = 0x4c0000
b.srli r7,r5,0x8
b.sb 0x1b18(r6),r7
b.sb 0x1b15(r6),r5
b.j 0x26fcd3

# r7 = EV + 0x00 + (cursor & 0x3f) * 8 (record base minus 0x20), r6 = 0x4c0000; clobbers r8. Called from Get
# handlers, so it must not touch r9's caller frame: the Get handler entered via jr, r9 is the Get handler's own
# return address and is saved by its prologue, so clobbering r9 here is safe.
recptr:
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.lhz r7,0x6(r8)
b.andi r7,r7,0x3f
b.slli r7,r7,0x3
b.add r7,r7,r8
b.movhi r6,0x4c
b.jr r9

# r7 = peek/poke address (EV+0x234 low half, EV+0x236 high half -> stored as two u16 halves)
peekaddr:
b.lhz r7,0x234(r8)
b.slli r7,r7,0x10
b.lhz r6,0x236(r8)
b.or r7,r7,r6
b.jr r9
# store r7 as the address (high half at +0x234, low half at +0x236); clobbers r6
setaddr:
b.srli r6,r7,0x10
b.sh 0x234(r8),r6
b.sh 0x236(r8),r7
b.jr r9

get_f0:
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.movhi r6,0x4c
b.sb 0x1b1f(r6),r0
b.sb 0x1b1e(r6),r0
b.lhz r5,0x234(r8)
b.j @put_chcl
get_f1:
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.movhi r6,0x4c
b.sb 0x1b1f(r6),r0
b.sb 0x1b1e(r6),r0
b.lhz r5,0x236(r8)
b.j @put_chcl
# Get 0xF2: 4 bytes at the address (RAM 0x200000..0x7fffff only), then address += 4. Outside: FF FF FF FF.
get_f2:
b.movhi r8,0x4f
b.ori r8,r8,0xe6b0
b.jal @peekaddr
b.movhi r6,0x20
b.sfgtu r6,r7
b.bf @f2_bad
b.movhi r6,0x80
b.sfleu r6,r7
b.bf @f2_bad
b.movhi r6,0x4c
b.lbz r5,0x0(r7)
b.sb 0x1b1f(r6),r5
b.lbz r5,0x1(r7)
b.sb 0x1b1e(r6),r5
b.lbz r5,0x2(r7)
b.sb 0x1b18(r6),r5
b.lbz r5,0x3(r7)
b.sb 0x1b15(r6),r5
b.addi r7,r7,0x4
b.jal @setaddr
b.j 0x26fcd3
f2_bad:
b.movhi r6,0x4c
b.movi r5,-0x1
b.sb 0x1b1f(r6),r5
b.sb 0x1b1e(r6),r5
b.sb 0x1b18(r6),r5
b.sb 0x1b15(r6),r5
b.j 0x26fcd3
