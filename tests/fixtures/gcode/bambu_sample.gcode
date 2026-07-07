; HEADER_BLOCK_START
; BambuStudio 02.07.01.62
; model printing time: 1m 10s; total estimated time: 1m 10s
; total layer number: 2
; HEADER_BLOCK_END
M83 ; use relative distances for extrusion
; CHANGE_LAYER
; Z_HEIGHT: 0.2
; LAYER_HEIGHT: 0.2
G1 X10 Y10 F7800
G1 X20 Y10 E1.0 F1800
G1 X20 Y20 E1.0
G1 E-0.8 F1800
G1 X30 Y30 F7800
G1 E0.8 F1800
G1 X40 Y30 E0.6
; CHANGE_LAYER
; Z_HEIGHT: 0.4
; LAYER_HEIGHT: 0.2
G1 X10 Y10 E1.0
