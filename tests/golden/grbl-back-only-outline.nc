(KiCad to CNC - GRBL v1.1 command subset; review and simulate before use.)
(Operation: outline; source: outline.ngc.)
(Tool: 1 mm; converter tool T1.)
(Back-only setup: X-mirrored to match B.Cu; place board with B.Cu upward.)
(With spindle stopped, install this tool and set/probe Z0 against the PCB surface.)
(Verify G54 origin, homing, travel, workholding, spindle direction, and clearance.)
G21
G90
G94
G17
G91.1
G54
G40
G49
M5
M9
G0 Z10.000
M3 S10000
G4 P1
G0 X-1 Y2
G3 X-3 Y4 I-1 J0 F100
G0 Z10.000
M5
M9
G4 P1
M30
