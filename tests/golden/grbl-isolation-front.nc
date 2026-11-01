(KiCad to CNC - GRBL v1.1 command subset; review and simulate before use.)
(Operation: isolation-front; source: front.ngc.)
(Tool: 0.2 mm; converter tool T1.)
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
G4 P2
G0 Z3
G1 X1 Y2 Z-0.05 F120
G0 Z10.000
M5
M9
G4 P3
M30
