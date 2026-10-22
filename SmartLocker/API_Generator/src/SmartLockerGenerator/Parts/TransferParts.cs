using SmartLockerGenerator.Config;
using SmartLockerGenerator.Utils;

namespace SmartLockerGenerator.Parts;

public static class TransferParts
{
    public static void CreateAll(SolidWorksHelper sw)
    {
        CreateXCarriage(sw);
        CreateZCarriage(sw);
        CreateTransferTray(sw);
        CreateRackPinion(sw);
        CreateTrayGuide(sw);
        CreateConveyorParts(sw);
    }

    public static void CreateXCarriage(SolidWorksHelper sw)
    {
        sw.CreatePart("X_Carriage", b =>
        {
            b.AddEquation("X_Carriage_Width", 500, "mm");
            b.AddEquation("X_Carriage_Depth", 200, "mm");
            b.AddEquation("X_Carriage_Thickness", 5, "mm - Aluminum 6061");

            b.CreateSketch("Sketch_X_Carriage_Base", "Top Plane", "500x200mm rectangle");
            b.ExtrudedBoss("Boss_X_Carriage", "Sketch_X_Carriage_Base", 5, "Carriage plate 5mm Aluminum");

            // Holes for guide blocks (4x MGN15 blocks - 2 top, 2 bottom rail)
            b.CreateSketch("Sketch_X_Block_Holes", "Top Plane", "8x M5 holes for 4x guide blocks (2 per rail, 400mm apart)");
            b.HoleWizard("Holes_X_Blocks_M5", "ISO", "M5", 8, "Through All - guide block mounting, 4 holes per block x 2 blocks per rail");

            // Holes for Z rails mounting on front face
            b.CreateSketch("Sketch_Z_Rail_Mounts", "Front Plane", "16x M5 holes for 2x Z rails (8 per rail, pitch 200mm)");
            b.HoleWizard("Holes_Z_Rails_M5", "ISO", "M5", 16, "Through All - Z rail mounting");

            // Bearing block seats
            b.CreateSketch("Sketch_Bearing_Seats_X", "Top Plane", "2x bearing block seats 42x32mm");
            b.ExtrudedCut("Cut_Bearing_Seats_X", "Sketch_Bearing_Seats_X", "Depth 1mm - bearing block recess");

            // Belt clamp area
            b.CreateSketch("Sketch_Belt_Clamp_Area", "Top Plane", "Belt clamp: 40x10x5mm boss with 2x M3 holes");
            b.ExtrudedBoss("Boss_Belt_Clamp", "Sketch_Belt_Clamp_Area", 5, "Belt clamp boss - fixes carriage to GT2 belt");
            b.HoleWizard("Holes_Belt_Clamp_M3", "ISO", "M3", 2, "Belt clamp screws");

            // Cable chain mount
            b.CreateSketch("Sketch_Cable_Chain_Mount", "Top Plane", "Cable chain bracket mount 30x20mm");
            b.ExtrudedBoss("Boss_Cable_Chain_Mount", "Sketch_Cable_Chain_Mount", 3, "Cable chain top mount");

            b.Fillet("Fillet_X_Carriage", 5, "All outer edges R5");
            b.ReferencePlane("Plane_X_Carriage_Front", "Front face for Z rail mounting");
            b.ReferencePlane("Plane_X_Carriage_Top", "Top face for block mounting");
        });
    }

    public static void CreateZCarriage(SolidWorksHelper sw)
    {
        sw.CreatePart("Z_Carriage", b =>
        {
            b.AddEquation("Z_Carriage_Width", 900, "mm - spans X carriage + mechanism");
            b.AddEquation("Z_Carriage_Height", 200, "mm");
            b.AddEquation("Z_Carriage_Thickness", 5, "mm");

            b.CreateSketch("Sketch_Z_Carriage_Base", "Front Plane", "900x200mm");
            b.ExtrudedBoss("Boss_Z_Carriage", "Sketch_Z_Carriage_Base", 5, "Z carriage plate 5mm Al");

            // Mounting to Z guide blocks (4x)
            b.CreateSketch("Sketch_Z_Block_Holes", "Front Plane", "8x M5 for 4x guide blocks Z");
            b.HoleWizard("Holes_Z_Blocks_M5", "ISO", "M5", 8, "Through All");

            // Lead screw nut mounting (2x - left and right)
            b.CreateSketch("Sketch_Lead_Nut_Holes", "Front Plane", "8x M5 for 2x lead screw nuts (4 per nut)");
            b.HoleWizard("Holes_Lead_Nut_M5", "ISO", "M5", 8, "Through All - nut mounting at X=100 and X=800");

            // Y rail mounting on top
            b.CreateSketch("Sketch_Y_Rail_Mount", "Front Plane", "M4 holes for MGN12 Y rail, pitch 60mm, L=500mm");
            b.HoleWizard("Holes_Y_Rail_M4", "ISO", "M4", 8, "Through All - Y rail");

            // Y motor mount
            b.CreateSketch("Sketch_Y_Motor_Holes", "Front Plane", "4x M3 for NEMA17 Y motor bracket");
            b.HoleWizard("Holes_Y_Motor_M3", "ISO", "M3", 4, "Through All");

            // Ejector stopper - passive eject mechanism
            b.CreateSketch("Sketch_Ejector_Stopper", "Front Plane", "L-shaped stopper 380x10x30mm - holds parcel when tray retracts");
            b.ExtrudedBoss("Boss_Ejector_Stopper", "Sketch_Ejector_Stopper", 3, "Passive ejector: fixes parcel while tray retracts");

            // Position sensor mounts on Z carriage
            b.CreateSketch("Sketch_Z_Sensor_Mounts", "Front Plane", "2x sensor mounts for Y endstops");
            b.ExtrudedBoss("Boss_Z_Sensor_Mounts", "Sketch_Z_Sensor_Mounts", 2, "Sensor brackets");

            b.Fillet("Fillet_Z_Carriage", 5, "Outer edges");
            b.ReferencePlane("Plane_Z_Carriage_Top", "Top face for Y rail");
        });
    }

    public static void CreateTransferTray(SolidWorksHelper sw)
    {
        sw.CreatePart("Transfer_Tray", b =>
        {
            b.AddEquation("Transfer_Tray_Width", LockerParameters.TransferTrayWidth, "mm - 380 (400-2*10 clearance)");
            b.AddEquation("Transfer_Tray_Length", LockerParameters.TransferTrayLength, "mm - 400");
            b.AddEquation("Transfer_Tray_Height", LockerParameters.TransferTrayHeight, "mm - 30 front lip");
            b.AddEquation("Transfer_Tray_Thickness", LockerParameters.TransferTrayThickness, "mm - 3mm Al floor");

            // Tray floor - aluminum 3mm
            b.CreateSketch("Sketch_Tray_Base", "Top Plane", $"{LockerParameters.TransferTrayWidth}x{LockerParameters.TransferTrayLength}mm");
            b.ExtrudedBoss("Boss_Tray_Base", "Sketch_Tray_Base", LockerParameters.TransferTrayThickness, "Tray floor 3mm Al");

            // Front edge - L-shaped lip 30mm high, catches parcel on retrieval
            b.CreateSketch("Sketch_Tray_Front_Lip", "Front Plane", $"L-profile: width {LockerParameters.TransferTrayWidth}mm, height 30mm, thickness 3mm");
            b.ExtrudedBoss("Boss_Tray_Front_Lip", "Sketch_Tray_Front_Lip", LockerParameters.TransferTrayThickness, "Front lip 30mm high - parcel catch");

            // Side edges - 10mm high guides to keep parcel centered
            b.CreateSketch("Sketch_Tray_Side_Edges", "Front Plane", $"2x side walls: 400mm long, 10mm high, 2mm thick");
            b.ExtrudedBoss("Boss_Tray_Side_Edges", "Sketch_Tray_Side_Edges", 2, "Side guides 10mm high each side");

            // Reinforcement ribs underneath
            b.CreateSketch("Sketch_Tray_Ribs", "Top Plane", "2x ribs 380x10mm along length");
            b.ExtrudedBoss("Boss_Tray_Ribs", "Sketch_Tray_Ribs", 8, "Stiffening ribs 8mm deep");

            // Silicone anti-slip grooves on floor top surface
            b.CreateSketch("Sketch_Silicone_Grooves", "Top Plane", "5x grooves 380x3mm, pitch 60mm, for silicone strips");
            b.ExtrudedCut("Cut_Silicone_Grooves", "Sketch_Silicone_Grooves", "Depth 1mm - silicone strip seats");

            // Mounting to Y guide blocks (2x MGN12)
            b.CreateSketch("Sketch_Tray_Block_Holes", "Top Plane", "4x M4 holes for 2x Y guide blocks");
            b.HoleWizard("Holes_Tray_Blocks_M4", "ISO", "M4", 4, "Through All - guide block mounting");

            // Rack mounting underneath
            b.CreateSketch("Sketch_Tray_Rack_Mount", "Bottom Plane", "4x M3 holes for rack Y (450mm rack)");
            b.HoleWizard("Holes_Tray_Rack_M3", "ISO", "M3", 4, "Through All - rack mounting along tray length");

            // Parcel presence sensor on tray (reflective)
            b.CreateSketch("Sketch_Tray_Sensor", "Top Plane", "Sensor window Ø8mm at tray center");
            b.ExtrudedCut("Cut_Tray_Sensor_Window", "Sketch_Tray_Sensor", "Through All - parcel detection sensor");

            b.Fillet("Fillet_Tray", 3, "All tray edges R3 - safe for parcel");
            b.Chamfer("Chamfer_Tray_Entry", 1, 45, "Front lip entry edge - smooth parcel entry");

            b.ReferencePlane("Plane_Tray_Floor_Top", "Top surface of floor for Distance mate");
            b.ReferencePlane("Plane_Tray_Rear", "Rear face for Y Limit mate");
        });
    }

    public static void CreateRackPinion(SolidWorksHelper sw)
    {
        sw.CreatePart("Rack_Y", b =>
        {
            b.AddEquation("Rack_Length", LockerParameters.YTravel, "mm - 450mm stroke");
            b.AddEquation("Rack_Module", 1, "Module 1, tooth pitch π*1=3.14mm");
            b.CreateSketch("Sketch_Rack_Profile", "Front Plane", "Rack: 450x10mm body, 8mm thick, teeth Module 1 on top");
            b.ExtrudedBoss("Boss_Rack_Body", "Sketch_Rack_Profile", 8, "Rack body 8mm thick");
            b.CreateSketch("Sketch_Rack_Teeth", "Front Plane", "Teeth Module 1: height 2.25mm, pitch 3.14mm, ~143 teeth over 450mm");
            b.ExtrudedBoss("Boss_Rack_Teeth", "Sketch_Rack_Teeth", 8, "Rack teeth - visual, 143 teeth Module 1");
            b.LinearPattern("Pattern_Rack_Teeth", "Boss_Rack_Teeth", 143, 3.14, "X - tooth pitch");
            b.CreateSketch("Sketch_Rack_Holes", "Top Plane", "4x M3 mounting holes, pitch 100mm");
            b.HoleWizard("Holes_Rack_M3", "ISO", "M3", 4, "Through All - tray mounting");
            b.Fillet("Fillet_Rack", 0.5, "Tooth tips");
        });

        sw.CreatePart("Pinion_Y", b =>
        {
            b.AddEquation("Pinion_Teeth_Y", 20, "20T Module 1");
            b.AddEquation("Pinion_Pitch_Dia", 20, "mm - Module 1 x 20T = 20mm pitch diameter");
            b.CreateSketch("Sketch_Pinion_Y_Plan", "Front Plane", "Pinion: pitch D=20mm, OD=22mm, bore Ø5mm, face width 8mm");
            b.RevolvedBoss("Revolve_Pinion_Y", "Sketch_Pinion_Y_Plan", 360, "Pinion body Ø22x8mm");
            b.CreateSketch("Sketch_Pinion_Y_Teeth", "Front Plane", "20 teeth Module 1, involute profile (simplified)");
            b.ExtrudedCut("Cut_Pinion_Y_Teeth", "Sketch_Pinion_Y_Teeth", "Teeth - simplified trapezoidal cut");
            b.LinearPattern("Pattern_Pinion_Teeth_Y", "Cut_Pinion_Y_Teeth", 20, 18, "Circular");
            b.CreateSketch("Sketch_Pinion_Y_Bore", "Front Plane", "Bore Ø5mm + M4 set screw hole");
            b.ExtrudedCut("Cut_Pinion_Y_Bore", "Sketch_Pinion_Y_Bore", "Through All");
            b.HoleWizard("Hole_Pinion_Y_Set", "ISO", "M3", 1, "Set screw radial hole");
            b.ReferenceAxis("Axis_Pinion_Y", "Bore axis for Concentric to motor shaft");
        });

        sw.CreatePart("Tray_Guide", b =>
        {
            b.CreateSketch("Sketch_Guide", "Front Plane", "L-guide rail 400x10x10mm");
            b.ExtrudedBoss("Boss_Guide", "Sketch_Guide", 2, "Parcel side guide - UHMW plastic placeholder");
            b.CreateSketch("Sketch_Guide_Holes", "Top Plane", "3x M3 mounting holes");
            b.HoleWizard("Holes_Guide_M3", "ISO", "M3", 3, "Through All");
            b.Fillet("Fillet_Guide", 1, "Edges");
        });
    }

    public static void CreateConveyorParts(SolidWorksHelper sw)
    {
        sw.CreatePart("Conveyor_Belt", b =>
        {
            b.AddEquation("Conveyor_Width", LockerParameters.ConveyorWidth, "mm");
            b.AddEquation("Conveyor_Length", LockerParameters.ConveyorLength, "mm");
            b.CreateSketch("Sketch_Conveyor_Belt_Path", "Top Plane", "Belt loop: 2x rollers Ø40mm, center distance 500mm, width 350mm");
            b.AddFeature("Sweep_Conveyor_Belt", "Sweep (Thin)", "Path=Sketch_Conveyor_Belt_Path, Profile=belt cross section 2mm thick PVC");
            b.CreateSketch("Sketch_Belt_Pattern", "Top Plane", "Belt surface texture - optional");
            b.ExtrudedBoss("Boss_Belt_Texture", "Sketch_Belt_Pattern", 0.5, "Surface grip pattern - optional");
        });

        sw.CreatePart("Roller_Drive", b =>
        {
            b.AddEquation("Roller_Diameter", LockerParameters.RollerDiameter, "mm - Ø40mm");
            b.AddEquation("Roller_Length", 380, "mm");
            b.CreateSketch("Sketch_Roller_Profile", "Front Plane", "Roller: Ø40mm x 380mm, shaft stubs Ø12x20mm each end");
            b.RevolvedBoss("Revolve_Roller_Drive", "Sketch_Roller_Profile", 360, "Roller body Ø40x380 + shafts");
            b.CreateSketch("Sketch_Roller_Shaft_Bearing", "Front Plane", "Bearing journal Ø12mm, circlip groove");
            b.RevolvedBoss("Revolve_Roller_Shaft", "Sketch_Roller_Shaft_Bearing", 360, "Shaft stubs with bearing seats");
            b.CreateSketch("Sketch_Roller_Motor_Shaft", "Front Plane", "D-flat on drive end for motor coupling, M5 set screw");
            b.ExtrudedCut("Cut_Roller_D_Flat", "Sketch_Roller_Motor_Shaft", "Depth 2mm - D-flat");
            b.Fillet("Fillet_Roller", 1, "Roller edges R1");
            b.Chamfer("Chamfer_Roller_Shaft", 0.5, 45, "Shaft ends");
            b.ReferenceAxis("Axis_Roller", "Central axis for Concentric mate");
        });

        sw.CreatePart("Roller_Idler", b =>
        {
            b.CreateSketch("Sketch_Idler_Profile", "Front Plane", "Idler: Ø40mm x 380mm, shafts Ø12x20mm");
            b.RevolvedBoss("Revolve_Roller_Idler", "Sketch_Idler_Profile", 360, "Idler roller");
            b.ReferenceAxis("Axis_Idler", "Central axis");
            b.Fillet("Fillet_Idler", 1, "Edges");
        });

        sw.CreatePart("Conveyor_Frame", b =>
        {
            b.CreateSketch("Sketch_Conveyor_Frame", "Front Plane", "Side plate: 600x50x3mm with roller bearing holes Ø12mm");
            b.ExtrudedBoss("Boss_Conveyor_Frame", "Sketch_Conveyor_Frame", 3, "Conveyor side frame 3mm steel");
            b.CreateSketch("Sketch_Conveyor_Holes", "Front Plane", "2x Ø12mm bearing holes, center distance 500mm");
            b.ExtrudedCut("Cut_Conveyor_Bearing_Holes", "Sketch_Conveyor_Holes", "Through All - roller bearing seats");
            b.CreateSketch("Sketch_Conveyor_Tension", "Front Plane", "Idler slot 12x20mm for belt tension");
            b.ExtrudedCut("Cut_Conveyor_Tension_Slot", "Sketch_Conveyor_Tension", "Through All - belt tension adjustment");
            b.HoleWizard("Holes_Conveyor_Frame_M6", "ISO", "M6", 4, "Frame-to-plate mounting");
            b.Fillet("Fillet_Conveyor_Frame", 2, "Outer edges");
        });

        sw.CreatePart("Belt_Tensioner_Conveyor", b =>
        {
            b.CreateSketch("Sketch_Tensioner_Conv", "Front Plane", "Tensioner block 40x30x15mm with M5 screw");
            b.ExtrudedBoss("Boss_Tensioner_Conv", "Sketch_Tensioner_Conv", 15, "Belt tensioner for conveyor");
            b.HoleWizard("Hole_Tensioner_Conv_M5", "ISO", "M5", 1, "Adjustment screw hole");
            b.Fillet("Fillet_Tensioner_Conv", 1, "Edges");
        });
    }
}
