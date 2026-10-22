# قطعات (Parts) — لیست کامل

تمام قطعات با SolidWorks API Generator تولید می‌شوند. هر قطعه دارای FeatureManager واقعی و پارامتریک است.

## لیست 28 قطعه

| # | فایل SLDPRT | ابعاد کلیدی | Features | Generator |
|---|-------------|------------|----------|-----------|
| 1 | `Main_Frame.SLDPRT` | 950×700×2400 | Sweep, HoleWizard | FrameParts.cs |
| 2 | `Vertical_Support.SLDPRT` | 40×40×2400 | Extrude, Pattern | FrameParts.cs |
| 3 | `Horizontal_Beam.SLDPRT` | 40×40×870 | Extrude | FrameParts.cs |
| 4 | `Side_Panel_Left.SLDPRT` | 700×2400×1.5 | Sheet Metal, Vent Cut | HousingParts.cs |
| 5 | `Side_Panel_Right.SLDPRT` | 700×2400×1.5 | Sheet Metal, Service Cut | HousingParts.cs |
| 6 | `Rear_Panel.SLDPRT` | 950×2400×1.5 | Sheet Metal | HousingParts.cs |
| 7 | `Front_Panel_Frame.SLDPRT` | 950×500×1.5 | Sheet Metal, UI Cutouts | UiParts.cs |
| 8 | `Top_Cover.SLDPRT` | 950×700×1.5 | Extrude, Hinge Cut | HousingParts.cs |
| 9 | `Bottom_Plate.SLDPRT` | 950×700×2 | Extrude, HoleWizard | FrameParts.cs |
| 10 | `Compartment_Divider_Vertical.SLDPRT` | 500×2000×1.5 | Extrude | HousingParts.cs |
| 11 | `Compartment_Divider_Horizontal.SLDPRT` | 400×500×1.5 | Extrude | HousingParts.cs |
| 12 | `Compartment_Floor.SLDPRT` | 400×500×1.5 | Extrude, Mounting Holes | HousingParts.cs |
| 13 | `Compartment_Door.SLDPRT` | 398×398×2 | Extrude, Hinge Boss | HousingParts.cs |
| 14 | `Hinge_Concealed.SLDPRT` | 30×20×15 | Revolve, Extrude | HousingParts.cs |
| 15 | `Linear_Rail_X.SLDPRT` | 15×15×900 | Extrude (Profile MGN15) | MechanismParts.cs |
| 16 | `Linear_Guide_Block_X.SLDPRT` | 60×45×25 | Extrude, Ball Groove | MechanismParts.cs |
| 17 | `Linear_Rail_Z.SLDPRT` | 15×15×2400 | Extrude, Hole Pattern | MechanismParts.cs |
| 18 | `Linear_Rail_Y.SLDPRT` | 12×12×500 | Extrude, MGN12 Profile | MechanismParts.cs |
| 19 | `X_Carriage.SLDPRT` | 500×200×5 | Extrude, HoleWizard M5 | TransferParts.cs |
| 20 | `Z_Carriage.SLDPRT` | 900×200×5 | Extrude, HoleWizard | TransferParts.cs |
| 21 | `Transfer_Tray.SLDPRT` | 380×400×30 | Extrude, Edge Flange, Silicone Groove | TransferParts.cs |
| 22 | `Roller_Drive.SLDPRT` | Ø40×380 | Revolve, Shaft Bore | ConveyorParts.cs |
| 23 | `Shaft_Drive_X.SLDPRT` | Ø8×920 | Revolve, Chamfer | MechanismParts.cs |
| 24 | `Pulley_GT2_20T.SLDPRT` | Ø12.73×10 | Revolve, Teeth Cut (GT2) | MechanismParts.cs |
| 25 | `Belt_GT2_X.SLDPRT` | 10×2200 (loop) | Extrude (Thin), Path Sweep | MechanismParts.cs |
| 26 | `Lead_Screw_T8x8.SLDPRT` | Ø8×2150 | Helix + Sweep (Thread) | MechanismParts.cs |
| 27 | `Display_Placeholder.SLDPRT` | 26×26×8 | Extrude | UiParts.cs |
| 28 | `Electronics_Mounting_Plate.SLDPRT` | 800×500×3 | Extrude, HoleWizard | ElectronicsParts.cs |

> قطعات تکراری (10× Door, 4× Divider_Horizontal, 10× Floor) از یک فایل با Instance/Pattern استفاده می‌کنند.

## نمونه Feature Tree (هر قطعه)

```
Example: Transfer_Tray.SLDPRT
├── Equations (Transfer_Tray_Width=380, Length=400, Height=30)
├── Reference Geometry (Origin, Planes)
├── Sketch_Base (380×400 مستطیل)
├── Boss_Extrude_Base (3mm کف)
├── Sketch_Edge_Front (L-Profile 30mm)
├── Boss_Extrude_Edge_Front
├── Sketch_Edge_Sides (2× 400mm)
├── Boss_Extrude_Edge_Sides
├── Sketch_Mounting_Holes (4× M5)
├── HoleWizard_M5 (Through)
├── Sketch_Silicone_Groove
├── Cut_Silicone_Groove (1mm deep)
├── Fillet_Edges (R2mm)
└── Appearance (Aluminum Anodized)
```
