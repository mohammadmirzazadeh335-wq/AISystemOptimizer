using SmartLockerGenerator.Config;
using SmartLockerGenerator.Utils;

namespace SmartLockerGenerator.Parts;

public static class HousingParts
{
    public static void CreateAll(SolidWorksHelper sw)
    {
        CreateSidePanelLeft(sw);
        CreateSidePanelRight(sw);
        CreateRearPanel(sw);
        CreateTopCover(sw);
        CreateCompartmentDividerVertical(sw);
        CreateCompartmentDividerHorizontal(sw);
        CreateCompartmentFloor(sw);
        CreateCompartmentDoor(sw);
        CreateHingeConcealed(sw);
        CreateServiceAccessPanel(sw);
    }

    public static void CreateSidePanelLeft(SolidWorksHelper sw)
    {
        sw.CreatePart("Side_Panel_Left", b =>
        {
            b.AddEquation("External_Depth", LockerParameters.ExternalDepth, "mm");
            b.AddEquation("External_Height", LockerParameters.ExternalHeight, "mm");
            b.AddEquation("Panel_Thickness", LockerParameters.PanelThickness, "mm - 1.5mm steel sheet");

            // Sheet Metal Base Flange
            b.CreateSketch("Sketch_Side_Base", "Front Plane", $"{LockerParameters.ExternalDepth}x{LockerParameters.ExternalHeight} rectangle");
            b.AddFeature("Base_Flange", "Base Flange (Sheet Metal)", $"Thickness={LockerParameters.PanelThickness}mm, Bend Radius=2mm, K-Factor=0.5");

            // Edge Flanges for joining to frame
            b.CreateSketch("Sketch_Edge_Flange_Front", "Front Plane", "Edge along front - width 15mm, 90deg");
            b.AddFeature("Edge_Flange_Front", "Edge Flange", "Length 15mm, Angle 90deg, Radius 2mm");

            b.CreateSketch("Sketch_Edge_Flange_Rear", "Front Plane", "Edge along rear");
            b.AddFeature("Edge_Flange_Rear", "Edge Flange", "Length 15mm, Angle 90deg");

            // Mounting holes
            b.CreateSketch("Sketch_Mounting_Holes_Side", "Front Plane", "M5 holes, pitch 200mm along edges");
            b.HoleWizard("Holes_Side_M5", "ISO", "M5", 20, "Through All - frame mounting");

            // Ventilation slots
            b.CreateSketch("Sketch_Vent_Slots", "Front Plane", "Slots 20x5mm, 10 rows, Linear Pattern");
            b.ExtrudedCut("Cut_Vent_Slots", "Sketch_Vent_Slots", "Through All");
            b.LinearPattern("Pattern_Vent", "Cut_Vent_Slots", 10, 40, "Y");

            // Cable entry cutout (bottom)
            b.CreateSketch("Sketch_Cable_Entry_Side", "Front Plane", "Opening 30x20mm at bottom");
            b.ExtrudedCut("Cut_Cable_Entry_Side", "Sketch_Cable_Entry_Side", "Through All");
        });
    }

    public static void CreateSidePanelRight(SolidWorksHelper sw)
    {
        sw.CreatePart("Side_Panel_Right", b =>
        {
            b.AddEquation("External_Depth", LockerParameters.ExternalDepth, "mm");
            b.AddEquation("External_Height", LockerParameters.ExternalHeight, "mm");
            b.AddEquation("Panel_Thickness", LockerParameters.PanelThickness, "mm");

            b.CreateSketch("Sketch_Side_Base_R", "Front Plane", $"{LockerParameters.ExternalDepth}x{LockerParameters.ExternalHeight}");
            b.AddFeature("Base_Flange_R", "Base Flange (Sheet Metal)", $"Thickness={LockerParameters.PanelThickness}mm");

            b.CreateSketch("Sketch_Mounting_R", "Front Plane", "M5 holes");
            b.HoleWizard("Holes_Side_M5_R", "ISO", "M5", 20, "Through All");

            // Service access cutout 400x600
            b.CreateSketch("Sketch_Service_Cutout", "Front Plane", "400x600mm service access opening");
            b.ExtrudedCut("Cut_Service_Access", "Sketch_Service_Cutout", "Through All");

            b.CreateSketch("Sketch_Service_Hinge", "Front Plane", "2x hinge cutouts 30x5mm");
            b.ExtrudedCut("Cut_Hinge_Service", "Sketch_Service_Hinge", "Through All");

            b.CreateSketch("Sketch_Vent_R", "Front Plane", "Vent slots");
            b.ExtrudedCut("Cut_Vent_R", "Sketch_Vent_R", "Through All");
        });
    }

    public static void CreateRearPanel(SolidWorksHelper sw)
    {
        sw.CreatePart("Rear_Panel", b =>
        {
            b.AddEquation("External_Width", LockerParameters.ExternalWidth, "mm");
            b.AddEquation("External_Height", LockerParameters.ExternalHeight, "mm");

            b.CreateSketch("Sketch_Rear", "Front Plane", $"{LockerParameters.ExternalWidth}x{LockerParameters.ExternalHeight}");
            b.AddFeature("Base_Flange_Rear", "Base Flange (Sheet Metal)", $"Thickness={LockerParameters.PanelThickness}mm");

            // Split into 2 pieces for access (horizontal split at mid-height)
            b.CreateSketch("Sketch_Split_Line", "Front Plane", $"Horizontal line at Z={LockerParameters.ExternalHeight / 2}mm");
            b.AddFeature("Split_Rear_Panel", "Split Line (for 2-piece)", "Splits panel into upper/lower for service");

            b.CreateSketch("Sketch_Rear_Holes", "Front Plane", "M5 mounting holes, pitch 200mm");
            b.HoleWizard("Holes_Rear_M5", "ISO", "M5", 24, "Through All");

            b.CreateSketch("Sketch_Rear_Vent", "Front Plane", "Vent slots 20x5mm");
            b.ExtrudedCut("Cut_Rear_Vent", "Sketch_Rear_Vent", "Through All");
        });
    }

    public static void CreateTopCover(SolidWorksHelper sw)
    {
        sw.CreatePart("Top_Cover", b =>
        {
            b.AddEquation("External_Width", LockerParameters.ExternalWidth, "mm");
            b.AddEquation("External_Depth", LockerParameters.ExternalDepth, "mm");

            b.CreateSketch("Sketch_Top", "Top Plane", $"{LockerParameters.ExternalWidth}x{LockerParameters.ExternalDepth}");
            b.ExtrudedBoss("Boss_Top", "Sketch_Top", LockerParameters.TopCoverThickness, "Top plate 1.5mm");

            // Edge flanges down
            b.CreateSketch("Sketch_Top_Edge_Front", "Front Plane", "15mm flange down");
            b.AddFeature("Edge_Flange_Top_Front", "Edge Flange", "15mm x 90deg");

            // Hinge mounting (top cover hinges to rear frame)
            b.CreateSketch("Sketch_Top_Hinge", "Top Plane", "2x hinge bosses Ø6mm at rear");
            b.ExtrudedBoss("Boss_Top_Hinge", "Sketch_Top_Hinge", 5, "Hinge mounting bosses");

            // Electronics access opening
            b.CreateSketch("Sketch_Electronics_Access", "Top Plane", "600x400mm opening for electronics bay");
            b.ExtrudedCut("Cut_Electronics_Access", "Sketch_Electronics_Access", "Through All - electronics bay access");

            // Ventilation
            b.CreateSketch("Sketch_Top_Vent", "Top Plane", "Slots 30x5mm near PSU location");
            b.ExtrudedCut("Cut_Top_Vent", "Sketch_Top_Vent", "Through All");

            b.CreateSketch("Sketch_Top_Holes", "Top Plane", "M5 holes for frame mounting, 8 holes");
            b.HoleWizard("Holes_Top_M5", "ISO", "M5", 8, "Through All");

            b.Fillet("Fillet_Top", 3, "All outer edges");
        });
    }

    public static void CreateCompartmentDividerVertical(SolidWorksHelper sw)
    {
        sw.CreatePart("Compartment_Divider_Vertical", b =>
        {
            b.AddEquation("Compartment_Length", LockerParameters.CompartmentLength, "mm - 500 depth");
            b.AddEquation("External_Height", LockerParameters.ExternalHeight, "mm");
            b.AddEquation("Divider_Thickness", LockerParameters.DividerThickness, "mm");

            // Vertical divider: full height between columns
            double height = LockerParameters.NumberOfRows * LockerParameters.CompartmentHeight + (LockerParameters.NumberOfRows - 1) * LockerParameters.DividerThickness;
            b.CreateSketch("Sketch_Divider_V", "Front Plane", $"{LockerParameters.CompartmentLength}x{height}mm");
            b.ExtrudedBoss("Boss_Divider_V", "Sketch_Divider_V", LockerParameters.DividerThickness, "Vertical divider between columns");

            b.CreateSketch("Sketch_Divider_V_Holes", "Front Plane", "M5 mounting holes top/bottom");
            b.HoleWizard("Holes_Divider_V_M5", "ISO", "M5", 8, "Through All - frame mounting");

            // Slots for horizontal dividers insertion
            b.CreateSketch("Sketch_H_Slots", "Front Plane", $"4x horizontal slots {LockerParameters.DividerThickness}x{LockerParameters.CompartmentLength}mm");
            b.ExtrudedCut("Cut_H_Slots", "Sketch_H_Slots", "Through All - slots for horizontal dividers");

            b.Fillet("Fillet_Divider_V", 1, "All vertical edges");
        });
    }

    public static void CreateCompartmentDividerHorizontal(SolidWorksHelper sw)
    {
        sw.CreatePart("Compartment_Divider_Horizontal", b =>
        {
            b.AddEquation("Compartment_Width", LockerParameters.CompartmentWidth, "mm");
            b.AddEquation("Compartment_Length", LockerParameters.CompartmentLength, "mm");
            b.AddEquation("Divider_Thickness", LockerParameters.DividerThickness, "mm");

            b.CreateSketch("Sketch_Divider_H", "Top Plane", $"{LockerParameters.CompartmentWidth}x{LockerParameters.CompartmentLength}mm");
            b.ExtrudedBoss("Boss_Divider_H", "Sketch_Divider_H", LockerParameters.DividerThickness, "Horizontal divider between rows");

            b.CreateSketch("Sketch_Divider_H_Holes", "Top Plane", "M5 holes at frame contact");
            b.HoleWizard("Holes_Divider_H_M5", "ISO", "M5", 6, "Through All");

            // Cable/sensor pass-through hole
            b.CreateSketch("Sketch_Cable_Pass", "Top Plane", "Opening 20x15mm for sensor cables");
            b.ExtrudedCut("Cut_Cable_Pass_H", "Sketch_Cable_Pass", "Through All");

            b.Fillet("Fillet_Divider_H", 1, "All horizontal edges");
        });
    }

    public static void CreateCompartmentFloor(SolidWorksHelper sw)
    {
        sw.CreatePart("Compartment_Floor", b =>
        {
            b.AddEquation("Compartment_Width", LockerParameters.CompartmentWidth, "mm");
            b.AddEquation("Compartment_Length", LockerParameters.CompartmentLength, "mm");
            b.AddEquation("Panel_Thickness", LockerParameters.PanelThickness, "mm");

            b.CreateSketch("Sketch_Floor", "Top Plane", $"{LockerParameters.CompartmentWidth}x{LockerParameters.CompartmentLength}mm");
            b.ExtrudedBoss("Boss_Floor", "Sketch_Floor", LockerParameters.PanelThickness, "Compartment floor 1.5mm");

            b.CreateSketch("Sketch_Floor_Holes", "Top Plane", "4x M5 mounting holes at corners");
            b.HoleWizard("Holes_Floor_M5", "ISO", "M5", 4, "Through All - mounting to shelf/divider");

            // Drainage/ventilation micro-holes
            b.CreateSketch("Sketch_Floor_Vent", "Top Plane", "4x Ø5mm vent holes at corners");
            b.ExtrudedCut("Cut_Floor_Vent", "Sketch_Floor_Vent", "Through All");

            b.Fillet("Fillet_Floor", 2, "All floor edges R2");
        });
    }

    public static void CreateCompartmentDoor(SolidWorksHelper sw)
    {
        sw.CreatePart("Compartment_Door", b =>
        {
            double w = LockerParameters.CompartmentWidth - 2 * LockerParameters.DoorClearance; // 398mm
            double h = LockerParameters.CompartmentHeight - 2 * LockerParameters.DoorClearance; // 398mm
            b.AddEquation("Door_Width", w, "mm - 398 (400-2*1 clearance)");
            b.AddEquation("Door_Height", h, "mm - 398");
            b.AddEquation("Door_Thickness", LockerParameters.DoorThickness, "mm - 2mm steel");

            b.CreateSketch("Sketch_Door", "Front Plane", $"{w}x{h}mm");
            b.ExtrudedBoss("Boss_Door", "Sketch_Door", LockerParameters.DoorThickness, "Door plate 2mm");

            // Hinge bosses (2x)
            b.CreateSketch("Sketch_Hinge_Bosses", "Front Plane", "2x hinge mounting bosses Ø10mm at right edge, Y=80 and Y=320");
            b.ExtrudedBoss("Boss_Hinge_Mounts", "Sketch_Hinge_Bosses", 5, "Hinge bosses 5mm thick");
            b.HoleWizard("Holes_Door_Hinge", "ISO", "M4", 4, "Hinge mounting holes 2x2");

            // Lock strike plate area
            b.CreateSketch("Sketch_Lock_Area", "Front Plane", "Lock bracket mounting at left edge center");
            b.ExtrudedBoss("Boss_Lock_Mount", "Sketch_Lock_Area", 3, "Lock mounting reinforcement 3mm");
            b.HoleWizard("Holes_Door_Lock", "ISO", "M4", 2, "Lock mounting");

            // Window/handle opening (optional)
            b.CreateSketch("Sketch_Handle", "Front Plane", "Label area 60x20mm centered");
            b.ExtrudedCut("Cut_Handle_Label", "Sketch_Handle", "Depth 0.5mm - label recess");

            b.Fillet("Fillet_Door", 2, "All door outer edges R2");
            b.Chamfer("Chamfer_Door_Inner", 0.5, 45, "Inner face edges");

            // Hinge clearance cut - allows 100deg open
            b.CreateSketch("Sketch_Hinge_Clearance", "Front Plane", "Chamfer at hinge edge for clearance");
            b.ExtrudedCut("Cut_Hinge_Clearance", "Sketch_Hinge_Clearance", "Through All - hinge clearance");
        });
    }

    public static void CreateHingeConcealed(SolidWorksHelper sw)
    {
        sw.CreatePart("Hinge_Concealed", b =>
        {
            b.CreateSketch("Sketch_Hinge_Base", "Front Plane", "30x15mm hinge base plate, 3mm thick");
            b.ExtrudedBoss("Boss_Hinge_Base", "Sketch_Hinge_Base", 3, "Hinge base 3mm");
            b.CreateSketch("Sketch_Hinge_Pin", "Front Plane", "Hinge knuckle Ø6mm, L=20mm");
            b.RevolvedBoss("Revolve_Hinge_Pin", "Sketch_Hinge_Pin", 360, "Hinge pin knuckle");
            b.CreateSketch("Sketch_Hinge_Holes", "Front Plane", "2x M4 holes on base");
            b.HoleWizard("Holes_Hinge_M4", "ISO", "M4", 2, "Through All");
            b.Fillet("Fillet_Hinge", 1, "Knuckle edges");
        });
    }

    public static void CreateServiceAccessPanel(SolidWorksHelper sw)
    {
        sw.CreatePart("Service_Access_Panel", b =>
        {
            b.CreateSketch("Sketch_Service", "Front Plane", "400x600mm access door");
            b.ExtrudedBoss("Boss_Service", "Sketch_Service", LockerParameters.PanelThickness, "Service panel 1.5mm");
            b.CreateSketch("Sketch_Service_Hinge2", "Front Plane", "2x hinge cutouts");
            b.ExtrudedCut("Cut_Service_Hinge", "Sketch_Service_Hinge2", "Through All");
            b.CreateSketch("Sketch_Service_Lock", "Front Plane", "Cam lock hole Ø19mm");
            b.ExtrudedCut("Cut_Service_Lock", "Sketch_Service_Lock", "Through All - cam lock");
            b.CreateSketch("Sketch_Service_Holes", "Front Plane", "M5 mounting holes");
            b.HoleWizard("Holes_Service_M5", "ISO", "M5", 6, "Through All");
            b.Fillet("Fillet_Service", 2, "Outer edges");
        });
    }
}
