# اسمبلی‌ها (Assemblies) — سلسله‌مراتب

## ساختار درختی Main_Assembly

```
Main_Assembly.SLDASM (950×700×2400)
│
├── Frame_Assembly.SLDASM
│   ├── Main_Frame.SLDPRT (Fix)
│   ├── Vertical_Support.SLDPRT ×4
│   ├── Horizontal_Beam.SLDPRT ×8 (Top/Bottom/Middle)
│   ├── Bottom_Plate.SLDPRT
│   ├── Mounting_Bracket_Corner.SLDPRT ×24
│   ├── Foot_Adjustable.SLDPRT ×4
│   └── Fasteners_Assembly.SLDASM (M8×20 ×48)
│
├── Housing_Assembly.SLDASM
│   ├── Side_Panel_Left/Right
│   ├── Rear_Panel (2-Piece)
│   ├── Top_Cover (Hinged)
│   ├── Compartment_Divider_Vertical
│   ├── Compartment_Divider_Horizontal ×4
│   ├── Compartment_Floor ×10 (Pattern)
│   ├── Compartment_Door ×10
│   ├── Hinge_Concealed ×20
│   ├── Service_Access_Panel ×2
│   └── Compartments via Instances (01-10)
│
├── X_Axis_Assembly.SLDASM ⭐ متحرک
│   ├── Linear_Rail_X.SLDPRT ×2 (L=900)
│   ├── Linear_Guide_Block_X.SLDPRT ×4
│   ├── X_Carriage.SLDPRT
│   ├── Shaft_Drive_X.SLDPRT
│   ├── Bearing_Block_X.SLDPRT ×2
│   ├── Pulley_GT2_20T.SLDPRT ×2 (Drive + Idler)
│   ├── Belt_GT2_X.SLDPRT
│   ├── Belt_Tensioner_X.SLDPRT
│   ├── Motor_Mount_X.SLDPRT
│   ├── Motor_NEMA23_X (Placeholder)
│   ├── Sensor_Endstop_X ×2
│   └── Mechanical_Stop_X ×2
│   └── Mates: LimitDistance X 0-480mm
│
├── Z_Axis_Assembly.SLDASM ⭐ متحرک
│   ├── Linear_Rail_Z.SLDPRT ×2 (L=2400)
│   ├── Linear_Guide_Block_Z.SLDPRT ×4
│   ├── Z_Carriage.SLDPRT
│   ├── Lead_Screw_T8x8.SLDPRT ×2
│   ├── Lead_Screw_Nut_T8.SLDPRT ×2
│   ├── Bearing_Block_Z ×4 (Top/Bottom)
│   ├── Belt_GT2_Z_Sync.SLDPRT
│   ├── Pulley_GT2_20T_Z ×4
│   ├── Motor_Mount_Z.SLDPRT
│   ├── Motor_NEMA23_Z (Placeholder)
│   └── Sensor_Endstop_Z ×2
│   └── Mates: LimitDistance Z 0-2120mm
│
├── Transfer_Tray_Assembly.SLDASM ⭐ متحرک
│   ├── Transfer_Tray.SLDPRT (380×400×30)
│   ├── Linear_Rail_Y.SLDPRT (MGN12, L=500)
│   ├── Linear_Guide_Block_Y.SLDPRT ×2
│   ├── Rack_Y.SLDPRT (450mm)
│   ├── Pinion_Y.SLDPRT (20T)
│   ├── Motor_Mount_Y.SLDPRT
│   ├── Motor_NEMA17_Y (Placeholder)
│   ├── Tray_Guide.SLDPRT ×2
│   └── Sensor_Endstop_Y ×2
│   └── Mates: LimitDistance Y 0-450mm
│
├── Conveyor_Assembly.SLDASM
│   ├── Conveyor_Frame.SLDPRT ×2
│   ├── Roller_Drive.SLDPRT (Ø40)
│   ├── Roller_Idler.SLDPRT
│   ├── Conveyor_Belt.SLDPRT (350×600)
│   ├── Bearing_Block_Conveyor ×4
│   ├── Motor_Conveyor (JGB37-520)
│   └── Sensor_Conveyor.SLDPRT
│
├── User_Interface_Assembly.SLDASM
│   ├── Front_Panel_Frame.SLDPRT
│   ├── Display_Placeholder + Display_Mount
│   ├── Button_Placeholder ×2 + Button_Mount ×2
│   ├── Keypad_Placeholder + Keypad_Mount
│   └── IO_Slot (400×50 cutout)
│
├── Electronics_Assembly.SLDASM
│   ├── Electronics_Mounting_Plate.SLDPRT (800×500×3)
│   ├── Arduino_Placeholder.SLDPRT
│   ├── Motor_Driver_Placeholder ×3
│   ├── Power_Supply_Placeholder.SLDPRT
│   ├── Terminal_Block_Placeholder.SLDPRT
│   ├── Standoff_M3x20 ×4
│   └── Sensor_Hub.SLDPRT
│
├── Cable_Management_Assembly.SLDASM
│   ├── Cable_Tray.SLDPRT (40×30×2000)
│   ├── Cable_Tray_Horizontal.SLDPRT
│   ├── Cable_Chain_Z.SLDPRT (Energy Chain Placeholder)
│   ├── Cable_Chain_Mount_Top/Bottom
│   ├── Cable_Clip.SLDPRT ×10
│   └── Cable_Entry/Exit_Openings
│
└── Fasteners_Assembly.SLDASM
    ├── Fastener_M5x12 ×120
    ├── Fastener_M8x20 ×48
    └── Fastener_M3x8 ×32
```

## Mateهای کلیدی هر اسمبلی

| اسمبلی | Mate اصلی | نوع | مقدار |
|--------|-----------|-----|-------|
| X_Axis | `X_LimitDistance` | LimitDistance | 0–480mm |
| Z_Axis | `Z_LimitDistance` | LimitDistance | 0–2120mm |
| Transfer_Tray | `Y_LimitDistance` | LimitDistance | 0–450mm |
| X_Axis | `X_Rail_Coincident` | Coincident | ثابت |
| Z_Axis | `Z_Rail_Coincident` | Coincident | روی X_Carriage |
| Transfer | `Y_Rail_Coincident` | Coincident | روی Z_Carriage |

## ترتیب وابستگی (Build Order)

1. Frame_Assembly (مستقل)
2. Housing_Assembly (وابسته به Frame)
3. X_Axis_Assembly (مستقل، سپس روی Frame)
4. Z_Axis_Assembly (روی X_Carriage)
5. Transfer_Tray_Assembly (روی Z_Carriage)
6. Conveyor_Assembly (روی Bottom_Plate)
7. User_Interface_Assembly (روی Front_Panel)
8. Electronics_Assembly (روی Top)
9. Cable_Management_Assembly (بین همه)
10. Main_Assembly (مونتاژ نهایی همه)
