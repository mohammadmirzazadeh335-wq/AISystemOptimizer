using SmartLockerGenerator.Config;
using SmartLockerGenerator.Utils;

namespace SmartLockerGenerator.Parts;

public static class UiParts
{
    public static void CreateAll(SolidWorksHelper sw)
    {
        CreateFrontPanel(sw);
        CreateDisplay(sw);
        CreateButton(sw);
        CreateKeypad(sw);
    }

    public static void CreateFrontPanel(SolidWorksHelper sw)
    {
        sw.CreatePart("Front_Panel_Frame", b =>
        {
            b.AddEquation("External_Width", LockerParameters.ExternalWidth, "mm");
            b.AddEquation("Front_Panel_Height", 500, "mm - upper front panel (500mm tall, lower is I/O slot area)");
            b.AddEquation("Panel_Thickness", LockerParameters.PanelThickness, "mm");
            b.AddEquation("Display_Cutout_Width", LockerParameters.DisplayCutoutWidth, "mm - 28");
            b.AddEquation("Display_Cutout_Height", LockerParameters.DisplayCutoutHeight, "mm");
            b.AddEquation("Keypad_Cutout_Width", LockerParameters.KeypadCutoutWidth, "mm - 102");
            b.AddEquation("Keypad_Cutout_Height", LockerParameters.KeypadCutoutHeight, "mm - 82");
            b.AddEquation("IO_Slot_Width", LockerParameters.IOSlotWidth, "mm - 400");
            b.AddEquation("IO_Slot_Height", LockerParameters.IOSlotHeight, "mm - 50");

            // Sheet metal base
            b.CreateSketch("Sketch_Front_Base", "Front Plane", $"{LockerParameters.ExternalWidth}x500mm");
            b.AddFeature("Base_Flange_Front", "Base Flange (Sheet Metal)", $"Thickness={LockerParameters.PanelThickness}mm, Bend Radius=2mm");

            // Edge flanges for frame attachment
            b.CreateSketch("Sketch_Front_Edge_Flanges", "Front Plane", "15mm flanges on all sides, 90deg");
            b.AddFeature("Edge_Flanges_Front", "Edge Flange", "15mm x 90deg x 2mm radius on all 4 edges");

            // Display cutout - parametric
            b.CreateSketch("Sketch_Display_Cutout", "Front Plane", $"Display cutout {LockerParameters.DisplayCutoutWidth}x{LockerParameters.DisplayCutoutHeight}mm, centered, Y=400mm from bottom");
            b.ExtrudedCut("Cut_Display_Cutout", "Sketch_Display_Cutout", "Through All - display opening");

            // Button cutouts - 2x Ø16.5mm under display
            b.CreateSketch("Sketch_Button_Cutouts", "Front Plane", $"2x button holes D={LockerParameters.ButtonHoleDiameter}mm, spacing {LockerParameters.ButtonSpacing}mm, Y=350mm");
            b.ExtrudedCut("Cut_Button_Holes", "Sketch_Button_Cutouts", "Through All - 2x Ø16.5mm");

            // Button anti-rotation slots
            b.CreateSketch("Sketch_Button_Slots", "Front Plane", "2x slots 2x1mm for button key");
            b.ExtrudedCut("Cut_Button_Slots", "Sketch_Button_Slots", "Through All");

            // Keypad cutout - parametric
            b.CreateSketch("Sketch_Keypad_Cutout", "Front Plane", $"Keypad {LockerParameters.KeypadCutoutWidth}x{LockerParameters.KeypadCutoutHeight}mm, Y=200mm");
            b.ExtrudedCut("Cut_Keypad_Cutout", "Sketch_Keypad_Cutout", "Through All");

            // I/O slot - parcel entry/exit
            b.CreateSketch("Sketch_IO_Slot", "Front Plane", $"I/O Slot {LockerParameters.IOSlotWidth}x{LockerParameters.IOSlotHeight}mm, Y=20mm, with rounded ends R25mm");
            b.ExtrudedCut("Cut_IO_Slot", "Sketch_IO_Slot", "Through All - parcel slot with 25mm corner radii");

            // Frame mounting holes
            b.CreateSketch("Sketch_Front_Mounting_Holes", "Front Plane", "8x M5 holes around perimeter for frame screws");
            b.HoleWizard("Holes_Front_M5", "ISO", "M5", 8, "Through All - frame attachment");

            b.Fillet("Fillet_Front_Panel", 2, "All cutout edges R2");
        });
    }

    public static void CreateDisplay(SolidWorksHelper sw)
    {
        sw.CreatePart("Display_Placeholder", b =>
        {
            b.AddEquation("Display_Width", LockerParameters.DisplayWidth, "mm - 26 (1 inch)");
            b.AddEquation("Display_Height", LockerParameters.DisplayHeight, "mm");
            b.AddEquation("Display_Depth", 8, "mm - PCB thickness");

            b.CreateSketch("Sketch_Display_Body", "Front Plane", $"{LockerParameters.DisplayWidth}x{LockerParameters.DisplayHeight}mm");
            b.ExtrudedBoss("Boss_Display_Body", "Sketch_Display_Body", 8, "Display PCB 26x26x8mm");

            // Screen area
            b.CreateSketch("Sketch_Display_Screen", "Front Plane", "Screen 22x22mm on front face, 0.5mm recess");
            b.ExtrudedBoss("Boss_Display_Screen", "Sketch_Display_Screen", 1, "Screen area - different appearance (glass)");

            // Connector on back
            b.CreateSketch("Sketch_Display_Connector", "Front Plane", "FPC connector 10x3mm on back");
            b.ExtrudedBoss("Boss_Display_Connector", "Sketch_Display_Connector", 3, "FPC connector");

            b.Fillet("Fillet_Display", 0.5, "Body edges");
            b.ReferencePlane("Plane_Display_Front", "Front face for mounting mate");
        });

        sw.CreatePart("Display_Mount", b =>
        {
            b.CreateSketch("Sketch_Display_Mount_Base", "Front Plane", "40x40mm frame, 10mm deep, wall 3mm");
            b.ExtrudedBoss("Boss_Display_Mount_Frame", "Sketch_Display_Mount_Base", 10, "Display mount frame 40x40x10mm");
            b.CreateSketch("Sketch_Display_Mount_Cutout", "Front Plane", $"Inner {LockerParameters.DisplayWidth}x{LockerParameters.DisplayHeight}mm cutout");
            b.ExtrudedCut("Cut_Display_Mount_Cutout", "Sketch_Display_Mount_Cutout", "Through All - display seat");
            b.CreateSketch("Sketch_Display_Mount_Holes", "Front Plane", "4x Ø3.2mm holes, PCD 36mm");
            b.HoleWizard("Holes_Display_Mount_M3", "ISO", "M3", 4, "Through All - display screws");
            b.CreateSketch("Sketch_Display_Mount_Frame_Holes", "Front Plane", "4x M3 holes for panel mounting");
            b.HoleWizard("Holes_Display_Mount_Frame", "ISO", "M3", 4, "Through All - panel screws");
            b.CreateSketch("Sketch_Display_Cable_Opening", "Front Plane", "Opening 10x8mm at back for cable");
            b.ExtrudedCut("Cut_Display_Cable_Opening", "Sketch_Display_Cable_Opening", "Through All");
            b.Fillet("Fillet_Display_Mount", 1, "Edges");
        });
    }

    public static void CreateButton(SolidWorksHelper sw)
    {
        sw.CreatePart("Button_Placeholder", b =>
        {
            b.AddEquation("Button_Diameter", LockerParameters.ButtonDiameter, "mm - Ø16");
            b.CreateSketch("Sketch_Button_Body", "Front Plane", $"Button: Ø{LockerParameters.ButtonDiameter}mm, H=12mm");
            b.RevolvedBoss("Revolve_Button_Body", "Sketch_Button_Body", 360, "Button body Ø16x12mm");
            b.CreateSketch("Sketch_Button_Cap", "Top Plane", "Cap Ø14mm, H=3mm above body");
            b.RevolvedBoss("Revolve_Button_Cap", "Sketch_Button_Cap", 360, "Button cap - concave top");
            b.CreateSketch("Sketch_Button_Key", "Front Plane", "Anti-rotation key 2x1mm on side");
            b.ExtrudedBoss("Boss_Button_Key", "Sketch_Button_Key", 1, "Key for anti-rotation slot");
            b.Fillet("Fillet_Button", 0.5, "Cap edge");
            b.ReferenceAxis("Axis_Button", "Central axis for mounting");
        });

        sw.CreatePart("Button_Mount", b =>
        {
            b.CreateSketch("Sketch_Button_Mount_Hole", "Front Plane", $"Hole D={LockerParameters.ButtonHoleDiameter}mm (16.5mm) for button");
            b.ExtrudedCut("Cut_Button_Mount_Hole", "Sketch_Button_Mount_Hole", "Through All - button passage");
            b.CreateSketch("Sketch_Button_Mount_Flange", "Front Plane", "Flange Ø20mm, 2mm thick, panel clamping");
            b.ExtrudedBoss("Boss_Button_Mount_Flange", "Sketch_Button_Mount_Flange", 2, "Clamping flange");
            b.CreateSketch("Sketch_Button_Nut", "Front Plane", "Retaining nut M16x1 thread area, 4mm");
            b.ExtrudedBoss("Boss_Button_Nut_Area", "Sketch_Button_Nut", 4, "Nut area - thread placeholder");
            b.ReferenceAxis("Axis_Button_Mount", "Mount axis");
        });
    }

    public static void CreateKeypad(SolidWorksHelper sw)
    {
        sw.CreatePart("Keypad_Placeholder", b =>
        {
            b.AddEquation("Keypad_Width", LockerParameters.KeypadWidth, "mm - 100");
            b.AddEquation("Keypad_Height", LockerParameters.KeypadHeight, "mm - 80");
            b.CreateSketch("Sketch_Keypad_Body", "Front Plane", $"{LockerParameters.KeypadWidth}x{LockerParameters.KeypadHeight}x10mm");
            b.ExtrudedBoss("Boss_Keypad_Body", "Sketch_Keypad_Body", 10, "Keypad PCB 100x80x10mm");

            // 12 buttons (4x3 grid)
            b.CreateSketch("Sketch_Keypad_Buttons", "Front Plane", "12 buttons: 3 cols x 4 rows, each 18x18mm, spacing 4mm");
            b.ExtrudedBoss("Boss_Keypad_Buttons", "Sketch_Keypad_Buttons", 3, "Individual keys 18x18x3mm above body");
            b.LinearPattern("Pattern_Keypad_X", "Boss_Keypad_Buttons", 3, 22, "X - 3 columns");
            b.LinearPattern("Pattern_Keypad_Y", "Boss_Keypad_Buttons", 4, 19, "Y - 4 rows");

            // Connector
            b.CreateSketch("Sketch_Keypad_Connector", "Front Plane", "Pin header 12x3mm at back");
            b.ExtrudedBoss("Boss_Keypad_Connector", "Sketch_Keypad_Connector", 5, "Connector");
            b.Fillet("Fillet_Keypad", 1, "Body edges");
            b.ReferencePlane("Plane_Keypad_Front", "Front face");
        });

        sw.CreatePart("Keypad_Mount", b =>
        {
            b.CreateSketch("Sketch_Keypad_Mount_Frame", "Front Plane", $"Frame: {LockerParameters.KeypadCutoutWidth + 8}x{LockerParameters.KeypadCutoutHeight + 8}x12mm (110x90x12)");
            b.ExtrudedBoss("Boss_Keypad_Mount_Frame", "Sketch_Keypad_Mount_Frame", 12, "Keypad mount frame 110x90x12mm");
            b.CreateSketch("Sketch_Keypad_Mount_Cutout", "Front Plane", $"Inner {LockerParameters.KeypadCutoutWidth}x{LockerParameters.KeypadCutoutHeight}mm");
            b.ExtrudedCut("Cut_Keypad_Mount_Cutout", "Sketch_Keypad_Mount_Cutout", "Through All - keypad seat");
            b.CreateSketch("Sketch_Keypad_Mount_Holes", "Front Plane", "4x M3 holes, PCD 102x82mm");
            b.HoleWizard("Holes_Keypad_Mount_M3", "ISO", "M3", 4, "Through All - keypad screws");
            b.CreateSketch("Sketch_Keypad_Mount_Panel_Holes", "Front Plane", "4x M3 panel mounting holes");
            b.HoleWizard("Holes_Keypad_Panel_M3", "ISO", "M3", 4, "Through All - panel attachment");
            b.CreateSketch("Sketch_Keypad_Cable", "Front Plane", "Opening 15x10mm at back for ribbon cable");
            b.ExtrudedCut("Cut_Keypad_Cable", "Sketch_Keypad_Cable", "Through All");
            b.Fillet("Fillet_Keypad_Mount", 1, "Edges");
        });
    }
}
