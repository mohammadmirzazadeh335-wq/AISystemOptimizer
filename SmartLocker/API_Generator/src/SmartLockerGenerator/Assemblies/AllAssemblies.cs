using SmartLockerGenerator.Config;
using SmartLockerGenerator.Utils;

namespace SmartLockerGenerator.Assemblies;

public static class AllAssemblies
{
    public static void CreateAll(SolidWorksHelper sw)
    {
        CreateFrameAssembly(sw);
        CreateHousingAssembly(sw);
        CreateXAxisAssembly(sw);
        CreateZAxisAssembly(sw);
        CreateTransferTrayAssembly(sw);
        CreateConveyorAssembly(sw);
        CreateUiAssembly(sw);
        CreateElectronicsAssembly(sw);
        CreateCableManagementAssembly(sw);
        CreateMainAssembly(sw);
    }

    // ========================================================================
    // Frame_Assembly
    // ========================================================================
    public static void CreateFrameAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("Frame_Assembly", b =>
        {
            b.AddComponent("Main_Frame.SLDPRT", 1, "", "Fix - Main frame structure");
            b.FixComponent("Fix_Main_Frame", "Main_Frame grounded to Origin");

            b.AddComponent("Vertical_Support.SLDPRT", 4, "", "4 vertical columns");
            b.AddComponent("Horizontal_Beam.SLDPRT", 8, "", "Top/Bottom + Middle beams (4 top + 4 bottom)");
            b.AddComponent("Bottom_Plate.SLDPRT", 1, "", "Bottom plate on frame");
            b.AddComponent("Mounting_Bracket_Corner.SLDPRT", 24, "", "Corner brackets - every frame joint");
            b.AddComponent("Foot_Adjustable.SLDPRT", 4, "", "Adjustable feet at bottom corners");

            // Mates
            b.CoincidentMate("Bottom_Plate_To_Frame", "Bottom_Plate Top Face", "Main_Frame Bottom Face");
            b.CoincidentMate("Vertical_Supports_To_Frame", "Vertical_Support End Face", "Main_Frame Corner");
            b.CoincidentMate("Horizontal_Beams_To_Frame", "Horizontal_Beam End", "Vertical_Support Side");
            b.CoincidentMate("Feet_To_Bottom", "Foot Top", "Bottom_Plate Bottom, concentric M10 holes", "4x Concentric M10");
            b.CoincidentMate("Corner_Brackets", "Bracket Face", "Frame Joint", "24 brackets, coincident + M8 fasteners");
        });
    }

    // ========================================================================
    // Housing_Assembly - 10 compartments
    // ========================================================================
    public static void CreateHousingAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("Housing_Assembly", b =>
        {
            b.AddComponent("Side_Panel_Left.SLDPRT", 1, "", "Left side panel");
            b.AddComponent("Side_Panel_Right.SLDPRT", 1, "", "Right side with service door");
            b.AddComponent("Rear_Panel.SLDPRT", 1, "", "Rear panel (2-piece)");
            b.AddComponent("Top_Cover.SLDPRT", 1, "", "Top cover, hinged to rear");
            b.AddComponent("Compartment_Divider_Vertical.SLDPRT", 1, "", "Middle vertical divider");
            b.AddComponent("Compartment_Divider_Horizontal.SLDPRT", 4, "", "4 horizontal dividers between 5 rows");
            b.AddComponent("Compartment_Floor.SLDPRT", 10, "", "Floors - 10 instances, one per compartment");
            b.AddComponent("Compartment_Door.SLDPRT", 10, "", "Doors - 10x, each 398x398, hinged");
            b.AddComponent("Hinge_Concealed.SLDPRT", 20, "", "2x per door, 10 doors");
            b.AddComponent("Service_Access_Panel.SLDPRT", 2, "", "Side + Rear service doors");

            // Mates - panels to frame
            b.CoincidentMate("Side_Left_To_Frame", "Side_Panel_Left Inner Face", "Frame Left Inner Face");
            b.CoincidentMate("Side_Right_To_Frame", "Side_Panel_Right Inner Face", "Frame Right Inner Face");
            b.CoincidentMate("Rear_To_Frame", "Rear_Panel Inner Face", "Frame Rear Inner Face");
            b.CoincidentMate("Top_To_Frame", "Top_Cover Bottom Face", "Frame Top Face");

            // Dividers
            b.CoincidentMate("Divider_V_To_Panels", "Divider_V Mid Plane", "Housing Mid Plane (External_Width/2)");
            b.DistanceMate("Divider_H_01", "Divider_H 01 Bottom Face", "Bottom_Plate Top", LockerParameters.CompartmentHeight + LockerParameters.PanelThickness, "Row 1 ceiling");
            b.DistanceMate("Divider_H_02", "Divider_H 02 Bottom", "Bottom_Plate Top", 2 * (LockerParameters.CompartmentHeight + LockerParameters.DividerThickness) + LockerParameters.PanelThickness, "Row 2");
            b.DistanceMate("Divider_H_03", "Divider_H 03", "Bottom_Plate Top", 3 * (LockerParameters.CompartmentHeight + LockerParameters.DividerThickness) + LockerParameters.PanelThickness, "Row 3");
            b.DistanceMate("Divider_H_04", "Divider_H 04", "Bottom_Plate Top", 4 * (LockerParameters.CompartmentHeight + LockerParameters.DividerThickness) + LockerParameters.PanelThickness, "Row 4");

            // Floors - linear patterns to fill 10 compartments
            b.CoincidentMate("Floors_To_Dividers", "Compartment_Floor Bottom Face", "Compartment_Divider_H Top or Bottom_Plate Top");
            b.DistanceMate("Floor_Positions", "Floor Front Face", "Rear_Panel Inner", 0, "Floors aligned to dividers via pattern");

            // Doors - hinged to frame/dividers
            b.CoincidentMate("Doors_Hinge_Axis", "Door Hinge Edge", "Frame/Divider Door Opening Edge", "Each door hinged at one vertical edge");
            b.DistanceMate("Door_Clearance", "Door Face", "Frame", LockerParameters.DoorClearance, "All doors inset by Door_Clearance");

            b.CoincidentMate("Top_Cover_Hinge", "Top_Cover Rear Edge", "Rear_Panel Top Edge", "Hinged - coincident, free to rotate 90deg");
        });
    }

    // ========================================================================
    // X_Axis_Assembly - MOVING (LimitDistance X 0-480mm)
    // ========================================================================
    public static void CreateXAxisAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("X_Axis_Assembly", b =>
        {
            b.AddComponent("Linear_Rail_X.SLDPRT", 2, "", "Top + Bottom rails, L=900mm, on front frame");
            b.AddComponent("Linear_Guide_Block_X.SLDPRT", 4, "", "2 per rail = 4 total");
            b.AddComponent("X_Carriage.SLDPRT", 1, "", "⭐ MOVING - X carriage plate 500x200x5mm");
            b.AddComponent("Shaft_Drive_X.SLDPRT", 1, "", "Drive shaft Ø8x920mm across frame");
            b.AddComponent("Bearing_Block_X.SLDPRT", 2, "", "Shaft bearings SK8 each end");
            b.AddComponent("Pulley_GT2_20T.SLDPRT", 2, "", "Drive pulley (on motor shaft) + Idler pulley");
            b.AddComponent("Belt_GT2_X.SLDPRT", 1, "", "GT2 belt loop ~2200mm, 10mm wide");
            b.AddComponent("Belt_Tensioner_X.SLDPRT", 1, "", "Idler tensioner with M5 slot");
            b.AddComponent("Motor_Mount_X.SLDPRT", 1, "", "L-bracket for NEMA23");
            b.AddComponent("Motor_NEMA23_X.SLDPRT", 1, "", "Placeholder NEMA23 on mount");
            b.AddComponent("Sensor_Placeholder.SLDPRT", 2, "", "Endstops X min/max");
            b.AddComponent("Mechanical_Stop.SLDPRT", 2, "", "Mechanical stops with rubber bumper");

            // Fixed: rails to frame
            b.CoincidentMate("X_Rail_Top_To_Frame", "Linear_Rail_X Top Bottom Face", "Frame_Assembly Front Top Beam Top Face");
            b.CoincidentMate("X_Rail_Bottom_To_Frame", "Linear_Rail_X Bottom Bottom Face", "Frame_Assembly Front Bottom Beam Top Face");
            b.ParallelMate("X_Rails_Parallel", "Linear_Rail_X Top Axis", "Linear_Rail_X Bottom Axis");
            b.DistanceMate("X_Rails_Alignment", "Linear_Rail_X Top Front Face", "Linear_Rail_X Bottom Front Face", 0, "Rails co-planar front");

            // Moving: blocks on rails
            b.CoincidentMate("X_Blocks_Top_On_Rails", "Linear_Guide_Block_X (Top Pair) Bottom Groove", "Linear_Rail_X Top Groove Face");
            b.CoincidentMate("X_Blocks_Bottom_On_Rails", "Linear_Guide_Block_X (Bottom Pair) Bottom Groove", "Linear_Rail_X Bottom Groove Face");

            // Moving: carriage on blocks
            b.CoincidentMate("X_Carriage_To_Blocks", "X_Carriage Bottom Face", "Linear_Guide_Block_X Top Face x4");
            b.ConcentricMate("X_Carriage_Mount_Holes", "X_Carriage M5 Holes", "Linear_Guide_Block_X M5 Holes", "8x M5 - blocks to carriage");

            // MAIN MOTION MATE - X axis movement
            b.LimitDistanceMate("X_LimitDistance_0_480", "X_Carriage Left Face", "Frame_Assembly Left Inner Face", 0, LockerParameters.XTravel, "⭐ CORE: X motion 0-480mm, drag with mouse!");

            // Shaft and pulleys
            b.ConcentricMate("X_Shaft_To_Bearings", "Shaft_Drive_X", "Bearing_Block_X Bore", "Shaft through bearings");
            b.CoincidentMate("X_Shaft_Shoulder", "Shaft Shoulder Face", "Bearing_Block Face");
            b.CoincidentMate("X_Bearings_To_Frame", "Bearing_Block_X Bottom", "Frame Top/Bottom Beams");
            b.ConcentricMate("X_Pulley_Drive_To_Shaft", "Pulley_GT2_20T (Drive) Bore", "Shaft_Drive_X End (or Motor Shaft)");
            b.ConcentricMate("X_Pulley_Idler_To_Shaft", "Pulley_GT2_20T (Idler) Bore", "Belt_Tensioner Shaft");

            // Belt
            b.CoincidentMate("X_Belt_To_Pulleys", "Belt_GT2_X Inner Surface", "Pulley_GT2_20T Groove", "Belt wrapped around both pulleys");
            b.CoincidentMate("X_Belt_Clamp", "X_Carriage Belt Clamp", "Belt_GT2_X Outer", "Carriage clamped to belt - moves with belt");
            b.BeltChainMate("X_BeltChain", "Pulley_GT2_20T Drive", "Pulley_GT2_20T Idler", "Belt_GT2_X", "1:1 ratio - pulleys rotate together");

            // Motor
            b.CoincidentMate("X_Motor_To_Mount", "Motor_NEMA23_X Flange", "Motor_Mount_X Vertical Face");
            b.ConcentricMate("X_Motor_Shaft_To_Pulley", "Motor_NEMA23_X Shaft", "Pulley_GT2_20T Drive Bore");
            b.CoincidentMate("X_Motor_Mount_To_Frame", "Motor_Mount_X Horizontal Base", "Frame Left Frame");

            // Sensors and stops - fixed
            b.CoincidentMate("X_Endstop_Min", "Sensor X Min", "Frame Left Inner", "X=0 endstop position");
            b.CoincidentMate("X_Endstop_Max", "Sensor X Max", "Frame Right Inner", "X=480 endstop position");
            b.CoincidentMate("X_Stop_Min", "Mechanical_Stop Min Base", "Frame Left Inner", "With rubber bumper");
            b.CoincidentMate("X_Stop_Max", "Mechanical_Stop Max Base", "Frame Right Inner", "With rubber bumper");
        });
    }

    // ========================================================================
    // Z_Axis_Assembly - MOVING (LimitDistance Z 0-2120mm)
    // ========================================================================
    public static void CreateZAxisAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("Z_Axis_Assembly", b =>
        {
            b.AddComponent("Linear_Rail_Z.SLDPRT", 2, "", "Left + Right vertical, L=2400mm, on X_Carriage");
            b.AddComponent("Linear_Guide_Block_Z.SLDPRT", 4, "", "2 per rail");
            b.AddComponent("Z_Carriage.SLDPRT", 1, "", "⭐ MOVING - Z carriage 900x200x5mm");
            b.AddComponent("Lead_Screw_T8x8.SLDPRT", 2, "", "Left + Right, T8x8, L=2150mm");
            b.AddComponent("Lead_Screw_Nut_T8.SLDPRT", 2, "", "Brass nuts, on Z_Carriage");
            b.AddComponent("Bearing_Block_Z.SLDPRT", 4, "", "KP08, top+bottom each screw, on X_Carriage");
            b.AddComponent("Belt_GT2_Z_Sync.SLDPRT", 1, "", "Sync belt between 2 lead screws");
            b.AddComponent("Pulley_GT2_20T.SLDPRT", 4, "", "2 per screw (top+bottom), sync");
            b.AddComponent("Motor_Mount_Z.SLDPRT", 1, "", "Bottom center for NEMA23 Z");
            b.AddComponent("Motor_NEMA23_X.SLDPRT", 1, "", "NEMA23 Z motor (reuse NEMA23 part)");
            b.AddComponent("Sensor_Placeholder.SLDPRT", 2, "", "Z endstops top/bottom");
            b.AddComponent("Mechanical_Stop.SLDPRT", 2, "", "Z stops top/bottom");

            // Fixed: rails on X_Carriage
            b.CoincidentMate("Z_Rail_Left_To_XCarriage", "Linear_Rail_Z Left Back Face", "X_Carriage Front Face Left Area");
            b.CoincidentMate("Z_Rail_Right_To_XCarriage", "Linear_Rail_Z Right Back Face", "X_Carriage Front Face Right Area");
            b.ParallelMate("Z_Rails_Vertical", "Linear_Rail_Z Left Axis", "Linear_Rail_Z Right Axis");

            // Moving: blocks on rails
            b.CoincidentMate("Z_Blocks_On_Rails", "Linear_Guide_Block_Z Groove", "Linear_Rail_Z Groove Face x4");

            // Moving: Z carriage on blocks
            b.CoincidentMate("Z_Carriage_To_Blocks", "Z_Carriage Back Face", "Linear_Guide_Block_Z Front Face x4");
            b.ConcentricMate("Z_Carriage_Block_Holes", "Z_Carriage M5 Holes", "Linear_Guide_Block_Z M5 Holes");

            // MAIN MOTION MATE - Z axis
            b.LimitDistanceMate("Z_LimitDistance_0_2120", "Z_Carriage Bottom Face", "Bottom_Plate Top Face", 0, LockerParameters.ZTravel,
                "⭐ CORE: Z motion 0-2120mm covers Row1 to Row5! Drag with mouse.");

            // Lead screws - vertical, through bearings
            b.ConcentricMate("Z_Lead_Screw_Left_To_Bearings", "Lead_Screw_T8x8 Left", "Bearing_Block_Z Top+Bottom Left Bores");
            b.ConcentricMate("Z_Lead_Screw_Right_To_Bearings", "Lead_Screw_T8x8 Right", "Bearing_Block_Z Top+Bottom Right Bores");
            b.CoincidentMate("Z_Lead_Screw_Shoulder", "Lead_Screw Shoulder", "Bearing_Block_Z Bottom Face");
            b.CoincidentMate("Z_Bearings_To_XCarriage", "Bearing_Block_Z Bottom", "X_Carriage Front Face");

            // Lead nuts on Z_Carriage
            b.CoincidentMate("Z_Nut_Left_To_Carriage", "Lead_Screw_Nut_T8 Left Flange Bottom", "Z_Carriage Lead Nut Hole Area Left");
            b.CoincidentMate("Z_Nut_Right_To_Carriage", "Lead_Screw_Nut_T8 Right Flange Bottom", "Z_Carriage Lead Nut Hole Area Right");
            b.ConcentricMate("Z_Nuts_On_Screws", "Lead_Screw_Nut_T8 Bore", "Lead_Screw_T8x8 Shaft");

            // Sync belt between screws
            b.BeltChainMate("Z_Sync_Belt", "Lead_Screw_T8x8 Left Pulley", "Lead_Screw_T8x8 Right Pulley", "Belt_GT2_Z_Sync", "Syncs 2 screws 1:1");

            // Motor
            b.CoincidentMate("Z_Motor_To_Mount", "Motor_NEMA23_X Flange", "Motor_Mount_Z Top Face");
            b.ConcentricMate("Z_Motor_Shaft_To_Lead", "Motor Shaft", "Lead_Screw_T8x8 Left Bottom End", "Motor drives left screw, sync belt drives right");
            b.CoincidentMate("Z_Motor_Mount_To_XCarriage", "Motor_Mount_Z Base", "X_Carriage Bottom Center");

            // Sensors and stops on X_Carriage (fixed relative to X)
            b.CoincidentMate("Z_Endstop_Bottom", "Sensor Z Bottom", "X_Carriage Bottom Face", "Z=0");
            b.CoincidentMate("Z_Endstop_Top", "Sensor Z Top", "X_Carriage Top Face (2400mm up)", "Z=2120");
            b.CoincidentMate("Z_Stop_Bottom", "Mechanical_Stop Bottom", "X_Carriage Bottom");
            b.CoincidentMate("Z_Stop_Top", "Mechanical_Stop Top", "X_Carriage Top");
        });
    }

    // ========================================================================
    // Transfer_Tray_Assembly - MOVING (LimitDistance Y 0-450mm)
    // ========================================================================
    public static void CreateTransferTrayAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("Transfer_Tray_Assembly", b =>
        {
            b.AddComponent("Transfer_Tray.SLDPRT", 1, "", "⭐ MOVING - Main tray 380x400x30mm");
            b.AddComponent("Linear_Rail_Y.SLDPRT", 1, "", "MGN12 L=500mm, on Z_Carriage top");
            b.AddComponent("Linear_Guide_Block_Y.SLDPRT", 2, "", "2x blocks for tray, MGN12");
            b.AddComponent("Rack_Y.SLDPRT", 1, "", "Rack Module 1, L=450mm, under tray");
            b.AddComponent("Pinion_Y.SLDPRT", 1, "", "20T Module 1, on Y motor shaft");
            b.AddComponent("Motor_Mount_Y.SLDPRT", 1, "", "NEMA17 mount on Z_Carriage");
            b.AddComponent("Motor_NEMA17_Y.SLDPRT", 1, "", "NEMA17 for Y, placeholder");
            b.AddComponent("Tray_Guide.SLDPRT", 2, "", "Side guides on tray edges");
            b.AddComponent("Sensor_Placeholder.SLDPRT", 2, "", "Y endstops min/max on Z_Carriage");

            // Fixed: Y rail on Z_Carriage
            b.CoincidentMate("Y_Rail_To_ZCarriage", "Linear_Rail_Y Bottom Face", "Z_Carriage Top Face (centered)");
            b.ParallelMate("Y_Rail_Along_Depth", "Linear_Rail_Y Axis", "Compartment Depth Axis (Y direction)");

            // Moving: blocks on rail
            b.CoincidentMate("Y_Blocks_On_Rail", "Linear_Guide_Block_Y Groove", "Linear_Rail_Y Groove Face");

            // Moving: tray on blocks
            b.CoincidentMate("Tray_To_Blocks", "Transfer_Tray Bottom Face", "Linear_Guide_Block_Y Top Face x2");
            b.ConcentricMate("Tray_Block_Holes", "Transfer_Tray M4 Holes", "Linear_Guide_Block_Y M4 Holes");

            // MAIN MOTION MATE - Y axis (pick/place into compartment)
            b.LimitDistanceMate("Y_LimitDistance_0_450", "Transfer_Tray Rear Face", "Z_Carriage Rear Face", 0, LockerParameters.YTravel,
                "⭐ CORE: Y motion 0-450mm - into compartment! Drag to test pick/place.");

            // Rack and pinion
            b.CoincidentMate("Rack_To_Tray", "Rack_Y Top Face", "Transfer_Tray Bottom Face (center line)");
            b.ConcentricMate("Rack_To_Tray_Holes", "Rack_Y M3 Holes", "Transfer_Tray Rack M3 Holes");
            b.ConcentricMate("Pinion_To_Motor", "Pinion_Y Bore", "Motor_NEMA17_Y Shaft Ø5mm");
            b.DistanceMate("Pinion_To_Rack", "Pinion_Y Pitch Circle", "Rack_Y Teeth", 0, "Tangent - pinion engages rack (10mm pitch dia)");
            b.CoincidentMate("Y_Motor_To_Mount", "Motor_NEMA17_Y Flange", "Motor_Mount_Y Vertical Face");
            b.CoincidentMate("Y_Mount_To_ZCarriage", "Motor_Mount_Y Base", "Z_Carriage Side Face near Y rail");

            // Tray guides (side walls)
            b.CoincidentMate("Tray_Guides_To_Tray", "Tray_Guide Bottom", "Transfer_Tray Side Edges Bottom");

            // Sensors on Z_Carriage fixed - detect tray limits
            b.CoincidentMate("Y_Endstop_Rear", "Sensor Y Rear (Y=0)", "Z_Carriage Rear Face", "Y=0 - tray retracted");
            b.CoincidentMate("Y_Endstop_Front", "Sensor Y Front (Y=450)", "Z_Carriage Front with offset 450mm", "Y=450 - tray inside compartment");
        });
    }

    // ========================================================================
    // Conveyor_Assembly
    // ========================================================================
    public static void CreateConveyorAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("Conveyor_Assembly", b =>
        {
            b.AddComponent("Conveyor_Frame.SLDPRT", 2, "", "Left + Right side plates");
            b.AddComponent("Roller_Drive.SLDPRT", 1, "", "Drive roller Ø40x380");
            b.AddComponent("Roller_Idler.SLDPRT", 1, "", "Idler roller Ø40x380");
            b.AddComponent("Conveyor_Belt.SLDPRT", 1, "", "PVC belt 350x600");
            b.AddComponent("Bearing_Block_X.SLDPRT", 4, "", "SK8 bearings - 2 per roller");
            b.AddComponent("Belt_Tensioner_Conveyor.SLDPRT", 1, "", "Idler tensioner slot");
            b.AddComponent("Sensor_Placeholder.SLDPRT", 1, "", "Parcel detection on conveyor");

            b.CoincidentMate("Conveyor_Frames_To_Plate", "Conveyor_Frame Bottom", "Bottom_Plate Top (Front area, Y=50mm)");
            b.DistanceMate("Conveyor_Pos_X", "Conveyor Center X", "Frame Center X", 0, "Centered");
            b.DistanceMate("Conveyor_Pos_Z", "Conveyor Roller Axis Z", "Bottom_Plate Top", 400, "Height 400mm - level with tray at Z lowest");
            b.ConcentricMate("Conveyor_Drive_Roller", "Roller_Drive Shaft Ø12", "Conveyor_Frame Drive Hole Ø12");
            b.ConcentricMate("Conveyor_Idler_Roller", "Roller_Idler Shaft Ø12", "Conveyor_Frame Idler Hole (slot for tension)");
            b.CoincidentMate("Conveyor_Belt_On_Rollers", "Conveyor_Belt Inner", "Roller_Drive Outer Surface", "Belt wrapped around both rollers");
            b.CoincidentMate("Conveyor_Sensor", "Sensor Conveyor", "Conveyor_Frame Front Edge Center", "Detects parcel on belt");
        });
    }

    // ========================================================================
    // User_Interface_Assembly
    // ========================================================================
    public static void CreateUiAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("User_Interface_Assembly", b =>
        {
            b.AddComponent("Front_Panel_Frame.SLDPRT", 1, "", "Fix - Front panel 950x500x1.5mm");
            b.AddComponent("Display_Placeholder.SLDPRT", 1, "", "26x26x8mm display");
            b.AddComponent("Display_Mount.SLDPRT", 1, "", "40x40x10mm mount frame");
            b.AddComponent("Button_Placeholder.SLDPRT", 2, "", "Ø16mm tactile buttons x2");
            b.AddComponent("Button_Mount.SLDPRT", 2, "", "Mounts for each button");
            b.AddComponent("Keypad_Placeholder.SLDPRT", 1, "", "100x80x10mm 12-key keypad");
            b.AddComponent("Keypad_Mount.SLDPRT", 1, "", "110x90x12mm mount frame");

            b.CoincidentMate("Front_Panel_To_Frame", "Front_Panel_Frame Back Face", "Frame_Assembly Front Face (Upper section)");
            b.CoincidentMate("Display_Mount_To_Panel", "Display_Mount Back Face", "Front_Panel_Frame Inner Face around Display Cutout");
            b.CoincidentMate("Display_To_Mount", "Display_Placeholder Back Face", "Display_Mount Inside Cutout");
            b.ConcentricMate("Display_Screws", "Display M3 Holes", "Display_Mount M3 Holes");
            b.ConcentricMate("Buttons_To_Panel", "Button_Placeholder Body", "Button_Mount Bore Ø16.5mm each", "2x buttons through panel holes");
            b.ConcentricMate("Button_Mounts_To_Panel", "Button_Mount Axis", "Front_Panel_Frame Button Holes (Ø16.5mm)", "Mounts behind panel");
            b.CoincidentMate("Keypad_Mount_To_Panel", "Keypad_Mount Back", "Front_Panel_Frame Inner around Keypad Cutout");
            b.CoincidentMate("Keypad_To_Mount", "Keypad_Placeholder Back", "Keypad_Mount Inside");

            b.AddSubAssembly("Note: UI cutouts are parametric - change Display_Cutout_Width/Height in Equations");
        });
    }

    // ========================================================================
    // Electronics_Assembly
    // ========================================================================
    public static void CreateElectronicsAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("Electronics_Assembly", b =>
        {
            b.AddComponent("Electronics_Mounting_Plate.SLDPRT", 1, "", "800x500x3mm Al plate, top bay");
            b.AddComponent("Standoff_M3x20.SLDPRT", 4, "", "4x standoffs plate -> top frame");
            b.AddComponent("Arduino_Placeholder.SLDPRT", 1, "", "Uno 75x55x15");
            b.AddComponent("Motor_Driver_Placeholder.SLDPRT", 3, "", "3x DM542 - X, Z, Y drivers");
            b.AddComponent("Power_Supply_Placeholder.SLDPRT", 1, "", "Meanwell 24V 15A, 200x110x50");
            b.AddComponent("Terminal_Block_Placeholder.SLDPRT", 1, "", "DIN rail, front of plate");
            b.AddComponent("Sensor_Placeholder.SLDPRT", 1, "", "Sensor hub near Arduino");

            b.CoincidentMate("Standoffs_To_TopFrame", "Standoff Bottom", "Top_Cover.Bottom / Frame Top Face");
            b.CoincidentMate("Plate_To_Standoffs", "Electronics_Mounting_Plate Bottom", "Standoff Top x4");
            b.ConcentricMate("Plate_Standoff_Holes", "Plate M3 Holes", "Standoff M3 Holes");
            b.CoincidentMate("Arduino_To_Plate", "Arduino_Placeholder Bottom", "Electronics_Mounting_Plate Top (corner)");
            b.ConcentricMate("Arduino_Screws", "Arduino M3 Holes", "Plate Arduino M3 Holes");
            b.CoincidentMate("Drivers_To_Plate", "Motor_Driver Bottom", "Plate Top (3 zones along plate)");
            b.CoincidentMate("PSU_To_Plate", "Power_Supply Bottom", "Plate Top Center");
            b.CoincidentMate("Terminal_To_Plate", "Terminal_Block Bottom", "Plate Top Front Edge");
            b.DistanceMate("Electronics_Clearance", "Plate Top (highest component 50mm)", "Top_Cover Bottom", 30, "30mm clearance to Top_Cover");

            b.AddSubAssembly("Note: 80mm gap from Z_Carriage max (2120) to Plate (2200) - no collision");
        });
    }

    // ========================================================================
    // Cable_Management_Assembly
    // ========================================================================
    public static void CreateCableManagementAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("Cable_Management_Assembly", b =>
        {
            b.AddComponent("Cable_Tray.SLDPRT", 1, "", "Main vertical tray 40x30x2000mm");
            b.AddComponent("Cable_Tray_Horizontal.SLDPRT", 1, "", "Top horizontal 40x30x800mm");
            b.AddComponent("Cable_Chain_Z.SLDPRT", 1, "", "Energy chain 30x20x2200mm (placeholder IGUS E2.10)");
            b.AddComponent("Cable_Clip.SLDPRT", 10, "", "Cable clips every 200mm");
            b.AddComponent("Sensor_Placeholder.SLDPRT", 10, "", "Compartment presence sensors - one per house, on ceiling");

            b.CoincidentMate("Cable_Tray_To_Frame", "Cable_Tray Back", "Frame Left Inner (or Right) Vertical Frame Rear Face");
            b.DistanceMate("Cable_Tray_Offset", "Cable_Tray Inner", "Linear_Rail_Z Nearest", 25, "25mm from Z rail - no interference with moving gantry");
            b.CoincidentMate("Cable_Tray_H_To_Plate", "Cable_Tray_Horizontal Bottom", "Electronics_Mounting_Plate Top Edge");
            b.CoincidentMate("Cable_Chain_Top_To_Frame", "Cable_Chain_Z Top Mount", "Frame Top / X_Carriage Rear Top");
            b.CoincidentMate("Cable_Chain_Bottom_To_ZCarriage", "Cable_Chain_Z Bottom Mount", "Z_Carriage Rear Top", "Chain moves with Z_Carriage, bend radius 50mm");
            b.DistanceMate("Cable_Chain_To_Belt", "Cable_Chain_Z Outer", "Belt_GT2_Z_Sync Outer", 30, "30mm clearance from Z sync belt");

            // Compartment sensors - on ceiling of each compartment
            b.CoincidentMate("Presence_Sensors", "Sensor_Presence Bottom", "Compartment Ceiling (Top of each house)", "10x, one per compartment at ceiling center");
            b.DistanceMate("Presence_Sensor_Offset", "Sensor_Presence Center", "Compartment Center X", 0, "Centered in each compartment");

            b.AddSubAssembly("Note: Cable path from PSU (top) -> vertical tray -> energy chain -> Z_Carriage (motors/sensors) -> front panel (UI)");
            b.AddSubAssembly("Note: No cable crosses any moving belt or rail - verified by 30mm clearance mates above");
        });
    }

    // ========================================================================
    // Main_Assembly - Final Assembly of Everything
    // ========================================================================
    public static void CreateMainAssembly(SolidWorksHelper sw)
    {
        sw.CreateAssembly("Main_Assembly", b =>
        {
            // All sub-assemblies
            b.AddSubAssembly("Frame_Assembly.SLDASM", "Grounded - Fixed to Origin");
            b.AddSubAssembly("Housing_Assembly.SLDASM", "Fixed - 10 compartments inside frame");
            b.AddSubAssembly("X_Axis_Assembly.SLDASM", "⭐ MOTION - X axis 0-480mm LimitDistance");
            b.AddSubAssembly("Z_Axis_Assembly.SLDASM", "⭐ MOTION - Z axis 0-2120mm LimitDistance on X_Carriage");
            b.AddSubAssembly("Transfer_Tray_Assembly.SLDASM", "⭐ MOTION - Y axis 0-450mm LimitDistance on Z_Carriage");
            b.AddSubAssembly("Conveyor_Assembly.SLDASM", "Fixed - Input/output conveyor at bottom front");
            b.AddSubAssembly("User_Interface_Assembly.SLDASM", "Fixed - Front panel UI");
            b.AddSubAssembly("Electronics_Assembly.SLDASM", "Fixed - Top bay electronics");
            b.AddSubAssembly("Cable_Management_Assembly.SLDASM", "Fixed + Moving - Cable trays and energy chain");

            // Main assembly mates (sub-assemblies to each other)
            b.FixComponent("Fix_Frame_Assembly", "Frame_Assembly grounded - entire structure reference");

            b.CoincidentMate("Housing_To_Frame", "Housing_Assembly Back/Bottom", "Frame_Assembly Inner", "Housing fits inside frame");
            b.CoincidentMate("X_Axis_To_Frame", "X_Axis_Assembly Rails Back", "Frame_Assembly Front Beams Front Face", "X rails on front of frame");
            b.CoincidentMate("Z_Axis_To_X", "Z_Axis_Assembly Rails Back", "X_Axis_Assembly X_Carriage Front Face", "Z rails on X carriage - nested motion");
            b.CoincidentMate("Tray_To_Z", "Transfer_Tray_Assembly Rail Bottom", "Z_Axis_Assembly Z_Carriage Top Face", "Y rail on Z carriage - triple-nested!");
            b.CoincidentMate("Conveyor_To_Bottom", "Conveyor_Assembly Frame Bottom", "Frame_Assembly Bottom_Plate Top Front");
            b.CoincidentMate("UI_To_Front", "User_Interface_Assembly Panel Back", "Frame_Assembly Front Face Upper");
            b.CoincidentMate("Electronics_To_Top", "Electronics_Assembly Standoffs Bottom", "Housing_Assembly Top_Cover / Frame Top");
            b.CoincidentMate("Cable_Management_To_Frame", "Cable_Management Cable_Tray Back", "Frame_Assembly Frame Inner Side");

            // Motion Study mates summary (for documentation)
            b.AddSubAssembly("MOTION SUMMARY:");
            b.AddSubAssembly("  X: LimitDistance 0-480mm (Columns: Col1 X=200 -> Col2 X=601.5) - Motor NEMA23 + GT2 Belt");
            b.AddSubAssembly("  Z: LimitDistance 0-2120mm (Rows: Row1 Z=200 -> Row5 Z=1806) - Motor NEMA23 + Lead Screw T8x8 + Sync Belt");
            b.AddSubAssembly("  Y: LimitDistance 0-450mm (Retracted -> Inside Compartment) - Motor NEMA17 + Rack/Pinion");
            b.AddSubAssembly("  All 10 compartments reachable: Position = (Col, Row) -> (X, Z) + Y=450 injection");
            b.AddSubAssembly("  Mate Controller: 3 Sliders (X_Position, Z_Position, Y_Position) + 10 Saved Positions");
            b.AddSubAssembly("  Motion Studies: X_Sweep, Z_Sweep, Deposit_06, Retrieval_06, Full_Cycle_All");
        });
    }
}
