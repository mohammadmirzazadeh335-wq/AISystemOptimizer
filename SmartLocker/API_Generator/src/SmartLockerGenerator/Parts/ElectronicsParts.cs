using SmartLockerGenerator.Config;
using SmartLockerGenerator.Utils;

namespace SmartLockerGenerator.Parts;

public static class ElectronicsParts
{
    public static void CreateAll(SolidWorksHelper sw)
    {
        CreateElectronicsPlate(sw);
        CreateArduino(sw);
        CreateMotorDrivers(sw);
        CreatePowerSupply(sw);
        CreateTerminalBlock(sw);
        CreateCableTray(sw);
        CreateCableChain(sw);
    }

    public static void CreateElectronicsPlate(SolidWorksHelper sw)
    {
        sw.CreatePart("Electronics_Mounting_Plate", b =>
        {
            b.AddEquation("Plate_Width", 800, "mm - fits 800x500 electronics bay");
            b.AddEquation("Plate_Depth", 500, "mm");
            b.AddEquation("Plate_Thickness", 3, "mm - Aluminum 5052");

            b.CreateSketch("Sketch_Plate_Base", "Top Plane", "800x500mm");
            b.ExtrudedBoss("Boss_Plate", "Sketch_Plate_Base", 3, "Electronics plate 800x500x3mm Al");

            // Stand-off mounting holes (4x corners)
            b.CreateSketch("Sketch_Plate_Standoffs", "Top Plane", "4x Ø3.5mm at corners, inset 15mm");
            b.HoleWizard("Holes_Standoffs_M3", "ISO", "M3", 4, "Through All - stand-off to top frame");

            // Arduino mounting (Uno pattern: 4x M3 holes)
            b.CreateSketch("Sketch_Arduino_Holes", "Top Plane", "4x Ø3.2mm at (50,50), (50,100), (110,50), (110,100) from corner");
            b.ExtrudedCut("Cut_Arduino_Holes", "Sketch_Arduino_Holes", "Through All - Arduino Uno mounting");

            // Motor driver slots
            b.CreateSketch("Sketch_Driver_Holes", "Top Plane", "12x M4 holes for 3x motor drivers, 80x50 zones each");
            b.HoleWizard("Holes_Drivers_M4", "ISO", "M4", 12, "Through All - driver mounting (4 per driver x 3)");

            // PSU mounting
            b.CreateSketch("Sketch_PSU_Holes", "Top Plane", "4x M5 holes for PSU (200x110mm zone, centered)");
            b.HoleWizard("Holes_PSU_M5", "ISO", "M5", 4, "Through All - PSU mounting");

            // Ventilation slots
            b.CreateSketch("Sketch_Vent_Slots_Plate", "Top Plane", "Slots 20x5mm, 6 rows under PSU area");
            b.ExtrudedCut("Cut_Vent_Slots_Plate", "Sketch_Vent_Slots_Plate", "Through All");
            b.LinearPattern("Pattern_Vent_Plate", "Cut_Vent_Slots_Plate", 6, 20, "Y");

            // Cable entry openings
            b.CreateSketch("Sketch_Cable_Entry_Plate", "Top Plane", "2x openings 30x20mm at edges for cable trays");
            b.ExtrudedCut("Cut_Cable_Entry_Plate", "Sketch_Cable_Entry_Plate", "Through All - cable pass-through");

            // Terminal block holes
            b.CreateSketch("Sketch_Terminal_Holes", "Top Plane", "4x M3 for terminal block");
            b.HoleWizard("Holes_Terminal_M3", "ISO", "M3", 4, "Through All");

            b.Fillet("Fillet_Plate", 3, "Outer edges R3");
            b.ReferencePlane("Plane_Plate_Top", "Top surface for component placement");
        });

        sw.CreatePart("Standoff_M3x20", b =>
        {
            b.CreateSketch("Sketch_Standoff_Body", "Front Plane", "Hex 5.5mm across flats, M3x20mm");
            b.ExtrudedBoss("Boss_Standoff", "Sketch_Standoff_Body", 20, "Standoff 20mm high");
            b.CreateSketch("Sketch_Standoff_Holes", "Front Plane", "M3 threaded both ends, 8mm deep");
            b.HoleWizard("Holes_Standoff_M3", "ISO", "M3", 2, "Depth 8mm - screw holes both ends");
            b.Fillet("Fillet_Standoff", 0.5, "Hex edges");
        });
    }

    public static void CreateArduino(SolidWorksHelper sw)
    {
        sw.CreatePart("Arduino_Placeholder", b =>
        {
            b.CreateSketch("Sketch_Arduino_Body", "Top Plane", "75x55x15mm (Arduino Uno footprint)");
            b.ExtrudedBoss("Boss_Arduino_Body", "Sketch_Arduino_Body", 15, "Arduino PCB 75x55x1.6mm + components 13.4mm");
            b.CreateSketch("Sketch_Arduino_USB", "Front Plane", "USB-B connector 12x8mm on edge");
            b.ExtrudedBoss("Boss_Arduino_USB", "Sketch_Arduino_USB", 8, "USB connector");
            b.CreateSketch("Sketch_Arduino_Pins", "Top Plane", "Headers - 2x rows of pins");
            b.ExtrudedBoss("Boss_Arduino_Pins", "Sketch_Arduino_Pins", 8, "Pin headers");
            b.CreateSketch("Sketch_Arduino_Holes", "Top Plane", "4x Ø3.2mm mounting holes, Uno standard");
            b.ExtrudedCut("Cut_Arduino_Holes", "Sketch_Arduino_Holes", "Through All");
            b.Fillet("Fillet_Arduino", 1, "PCB edges");
        });
    }

    public static void CreateMotorDrivers(SolidWorksHelper sw)
    {
        sw.CreatePart("Motor_Driver_Placeholder", b =>
        {
            b.CreateSketch("Sketch_Driver_Body", "Top Plane", "80x50x25mm (DM542 style)");
            b.ExtrudedBoss("Boss_Driver_Body", "Sketch_Driver_Body", 25, "Driver 80x50x25mm");
            b.CreateSketch("Sketch_Driver_Terminals", "Front Plane", "Screw terminals 40x8mm on one side");
            b.ExtrudedBoss("Boss_Driver_Terminals", "Sketch_Driver_Terminals", 8, "Terminal block area");
            b.CreateSketch("Sketch_Driver_Heatsink", "Top Plane", "Heatsink fins 10x2mm x 6 fins on top");
            b.ExtrudedBoss("Boss_Driver_Heatsink", "Sketch_Driver_Heatsink", 8, "Heatsink fins");
            b.LinearPattern("Pattern_Heatsink", "Boss_Driver_Heatsink", 6, 4, "X");
            b.HoleWizard("Holes_Driver_M4", "ISO", "M4", 4, "Mounting holes at corners");
            b.Fillet("Fillet_Driver", 1, "Body edges");
        });
    }

    public static void CreatePowerSupply(SolidWorksHelper sw)
    {
        sw.CreatePart("Power_Supply_Placeholder", b =>
        {
            b.CreateSketch("Sketch_PSU_Body", "Top Plane", "200x110x50mm (Meanwell 24V 15A style)");
            b.ExtrudedBoss("Boss_PSU_Body", "Sketch_PSU_Body", 50, "PSU body 200x110x50mm metal case");
            b.CreateSketch("Sketch_PSU_Fan", "Front Plane", "Fan Ø80mm on one end");
            b.ExtrudedBoss("Boss_PSU_Fan", "Sketch_PSU_Fan", 5, "Fan placeholder");
            // Fix: Use AddFeature for circular pattern (no direct method in PartBuilder with count+spacing)
            b.AddFeature("Pattern_Fan_Slots", "Circular Vent", "Fan holes pattern");
            b.CreateSketch("Sketch_PSU_Terminals", "Front Plane", "AC/DC terminals 40x20mm on other end");
            b.ExtrudedBoss("Boss_PSU_Terminals", "Sketch_PSU_Terminals", 10, "Terminal cover");
            b.CreateSketch("Sketch_PSU_Holes", "Top Plane", "4x M5 mounting holes, 180x90 PCD");
            b.HoleWizard("Holes_PSU_M5", "ISO", "M5", 4, "Mounting to plate");
            b.Fillet("Fillet_PSU", 2, "Case edges");
        });
    }

    public static void CreateTerminalBlock(SolidWorksHelper sw)
    {
        sw.CreatePart("Terminal_Block_Placeholder", b =>
        {
            b.CreateSketch("Sketch_TB_Body", "Top Plane", "100x40x30mm");
            b.ExtrudedBoss("Boss_TB_Body", "Sketch_TB_Body", 30, "DIN rail terminal block 100x40x30mm");
            b.CreateSketch("Sketch_TB_Rail", "Front Plane", "DIN rail 35mm cut - 2x notches");
            b.ExtrudedCut("Cut_TB_Rail", "Sketch_TB_Rail", "Depth 5mm - DIN rail clips");
            b.CreateSketch("Sketch_TB_Holes", "Top Plane", "M3 mounting holes 2x");
            b.HoleWizard("Holes_TB_M3", "ISO", "M3", 2, "Mounting");
            b.Fillet("Fillet_TB", 1, "Edges");
        });
    }

    public static void CreateCableTray(SolidWorksHelper sw)
    {
        sw.CreatePart("Cable_Tray", b =>
        {
            b.AddEquation("Cable_Tray_Width", LockerParameters.CableTrayWidth, "mm - 40");
            b.AddEquation("Cable_Tray_Height", LockerParameters.CableTrayHeight, "mm - 30");
            b.CreateSketch("Sketch_Tray_Profile", "Front Plane", "U-channel: 40mm wide x 30mm high x 2mm wall, open top");
            b.ExtrudedBoss("Boss_Cable_Tray", "Sketch_Tray_Profile", 2000, "Cable tray main vertical 2000mm, U-profile");
            b.CreateSketch("Sketch_Tray_Holes", "Front Plane", "M5 mounting holes every 300mm, 6x, plus cable clip holes every 200mm");
            b.HoleWizard("Holes_Tray_M5", "ISO", "M5", 6, "Through All - frame mounting");
            b.CreateSketch("Sketch_Tray_Slots", "Top Plane", "Slots 10x5mm every 200mm for cable ties");
            b.ExtrudedCut("Cut_Tray_Slots", "Sketch_Tray_Slots", "Through All - cable tie slots");
            b.LinearPattern("Pattern_Tray_Slots", "Cut_Tray_Slots", 10, 200, "Z");
            b.Fillet("Fillet_Tray", 1, "Channel edges");
        });

        sw.CreatePart("Cable_Tray_Horizontal", b =>
        {
            b.CreateSketch("Sketch_Tray_H_Profile", "Front Plane", "U-channel 40x30x2mm");
            b.ExtrudedBoss("Boss_Cable_Tray_H", "Sketch_Tray_H_Profile", 800, "Horizontal tray 800mm, above compartments");
            b.HoleWizard("Holes_Tray_H_M5", "ISO", "M5", 3, "Frame mounting");
            b.Fillet("Fillet_Tray_H", 1, "Edges");
        });

        sw.CreatePart("Cable_Clip", b =>
        {
            b.CreateSketch("Sketch_Clip_Body", "Front Plane", "Clip: Ø10mm capacity, base 15x10x5mm, snap-fit");
            b.ExtrudedBoss("Boss_Clip", "Sketch_Clip_Body", 10, "Cable clip for 10mm bundle");
            b.CreateSketch("Sketch_Clip_Hole", "Top Plane", "M3 mounting hole");
            b.HoleWizard("Hole_Clip_M3", "ISO", "M3", 1, "Through All");
            b.Fillet("Fillet_Clip", 0.5, "Edges");
        });
    }

    public static void CreateCableChain(SolidWorksHelper sw)
    {
        sw.CreatePart("Cable_Chain_Z", b =>
        {
            // Energy chain placeholder - 30x20mm cross section, 2200mm travel
            b.CreateSketch("Sketch_Chain_Link", "Front Plane", "Chain link: 30x20mm outer, 20x10mm inner, hinge pins Ø4mm");
            b.ExtrudedBoss("Boss_Chain_Link", "Sketch_Chain_Link", 15, "Single chain link 15mm wide");
            b.CreateSketch("Sketch_Chain_Hinge", "Front Plane", "Hinge pins Ø4x8mm");
            b.ExtrudedBoss("Boss_Chain_Hinge", "Sketch_Chain_Hinge", 8, "Hinge pins");

            // Pattern to create full chain
            b.AddFeature("Pattern_Chain", "Linear Pattern", "Link + Hinge, 140 links, 15mm pitch => 2100mm chain (bend radius 50mm)");

            // Bending radius section
            b.CreateSketch("Sketch_Chain_Bend", "Front Plane", "180deg bend, radius 50mm at moving end");
            b.AddFeature("Curve_Chain_Bend", "Curve Driven", "Chain bend follows Z carriage movement");

            b.CreateSketch("Sketch_Chain_Mount_Top", "Front Plane", "Top mount bracket 40x30x5mm");
            b.ExtrudedBoss("Boss_Chain_Mount_Top", "Sketch_Chain_Mount_Top", 5, "Top fixed mount to frame");
            b.CreateSketch("Sketch_Chain_Mount_Bottom", "Front Plane", "Bottom mount 40x30x5mm to Z_Carriage");
            b.ExtrudedBoss("Boss_Chain_Mount_Bottom", "Sketch_Chain_Mount_Bottom", 5, "Moving mount to Z_Carriage");

            b.HoleWizard("Holes_Chain_Mount_M4", "ISO", "M4", 4, "Mounting holes 2 per mount");
        });
    }
}
