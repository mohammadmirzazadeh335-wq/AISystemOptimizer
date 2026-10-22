using SmartLockerGenerator.Config;
using SmartLockerGenerator.Utils;

namespace SmartLockerGenerator.Parts;

/// <summary>
/// تولید قطعات فریم و سازه
/// </summary>
public static class FrameParts
{
    public static void CreateAll(SolidWorksHelper sw)
    {
        CreateMainFrame(sw);
        CreateVerticalSupport(sw);
        CreateHorizontalBeam(sw);
        CreateBottomPlate(sw);
        CreateMountingBracketCorner(sw);
        CreateMountingBracketRail(sw);
        CreateFootAdjustable(sw);
    }

    public static void CreateMainFrame(SolidWorksHelper sw)
    {
        sw.CreatePart("Main_Frame", b =>
        {
            b.AddGlobalVariablesFromLocker();
            b.AddEquation("Frame_Profile", LockerParameters.FrameProfile, "mm - Profile 40x40");
            b.AddEquation("External_Width", LockerParameters.ExternalWidth, "mm");
            b.AddEquation("External_Depth", LockerParameters.ExternalDepth, "mm");
            b.AddEquation("External_Height", LockerParameters.ExternalHeight, "mm");

            b.ReferencePlane("Plane_Front", "Origin, Offset 0");
            b.ReferencePlane("Plane_Top", "Origin, Offset 0");
            b.ReferenceAxis("Axis_Vertical", "Along Z through Origin");

            // مقطع پروفیل 40x40 با دیواره 2mm
            b.CreateSketch("Sketch_Frame_Profile", "Plane_Front", "40x40 square, wall 2mm, hollow");
            b.AddFeature("Sketch_Frame_Profile", "Sketch", "Closed profile: outer 40x40, inner 36x36");

            // ستون‌های عمودی - Sweep
            b.CreateSketch("Sketch_Vertical_Paths", "Plane_Top", "4 vertical lines at corners, H=External_Height");
            b.AddFeature("Sweep_Vertical_Supports", "Sweep", "Profile=Sketch_Frame_Profile, Paths=Sketch_Vertical_Paths, x4 instances");

            // تیرهای افقی بالا
            b.CreateSketch("Sketch_Horizontal_Top", "Plane_Front", "4 horizontal lines at top (Z=External_Height)");
            b.AddFeature("Sweep_Horizontal_Top", "Sweep", "Profile=Sketch_Frame_Profile, Paths=Sketch_Horizontal_Top x4");

            // تیرهای افقی پایین
            b.CreateSketch("Sketch_Horizontal_Bottom", "Plane_Front", "4 horizontal lines at bottom (Z=0)");
            b.AddFeature("Sweep_Horizontal_Bottom", "Sweep", "Profile=Sketch_Frame_Profile, Paths=Sketch_Horizontal_Bottom x4");

            // تیرهای میانی برای تقسیم ارتفاع
            b.CreateSketch("Sketch_Horizontal_Mid", "Plane_Front", "4 lines at Z=600 and Z=1200");
            b.AddFeature("Sweep_Horizontal_Middle", "Sweep", "Profile=Sketch_Frame_Profile, Paths=Sketch_Horizontal_Mid");

            // سوراخ‌های نصب پنل
            b.CreateSketch("Sketch_Mounting_Holes", "Plane_Front", "M8 holes on all profiles, Pitch 100mm");
            b.HoleWizard("Mounting_Holes_M8", "ISO", "M8 Clearance", 48, "Through All - panel mounting");

            // سوراخ‌های ریل
            b.CreateSketch("Sketch_Rail_Mounting", "Plane_Front", "M5 holes for MGN15 rails, pitch 60mm");
            b.HoleWizard("Rail_Mounting_Holes_M5", "ISO", "M5", 64, "Depth 8mm - rail mounting");

            b.Fillet("Fillet_Frame_Edges", 2, "All outer edges of frame");
            b.Chamfer("Chamfer_Bottom", 1, 45, "Bottom edges of vertical supports");
        });
    }

    public static void CreateVerticalSupport(SolidWorksHelper sw)
    {
        sw.CreatePart("Vertical_Support", b =>
        {
            b.AddEquation("Frame_Profile", LockerParameters.FrameProfile, "mm");
            b.AddEquation("External_Height", LockerParameters.ExternalHeight, "mm");

            b.CreateSketch("Sketch_Profile", "Front Plane", "40x40 square, wall 2mm");
            b.ExtrudedBoss("Boss_Vertical", "Sketch_Profile", LockerParameters.ExternalHeight, "Vertical extrusion");
            b.CreateSketch("Sketch_Hollow", "Front Plane", "36x36 inner square");
            b.ExtrudedCut("Cut_Hollow", "Sketch_Hollow", "Through All - hollow profile");
            b.HoleWizard("Holes_M8", "ISO", "M8", 12, "For cross beams - pitch 400mm");
            b.Fillet("Fillet_Vertical", 2, "All vertical edges");
        });
    }

    public static void CreateHorizontalBeam(SolidWorksHelper sw)
    {
        sw.CreatePart("Horizontal_Beam", b =>
        {
            b.AddEquation("Frame_Profile", LockerParameters.FrameProfile, "mm");
            b.AddEquation("External_Width", LockerParameters.ExternalWidth, "mm");

            b.CreateSketch("Sketch_Profile", "Front Plane", "40x40 square");
            double length = LockerParameters.ExternalWidth - 2 * LockerParameters.FrameProfile;
            b.ExtrudedBoss("Boss_Horizontal", "Sketch_Profile", length, $"L={length}mm");
            b.CreateSketch("Sketch_Hollow_H", "Front Plane", "36x36 inner");
            b.ExtrudedCut("Cut_Hollow_H", "Sketch_Hollow_H", "Through All");
            b.HoleWizard("Holes_M8_H", "ISO", "M8", 4, "End holes for corner brackets");
            b.Fillet("Fillet_H", 2, "All edges");
        });
    }

    public static void CreateBottomPlate(SolidWorksHelper sw)
    {
        sw.CreatePart("Bottom_Plate", b =>
        {
            b.AddEquation("External_Width", LockerParameters.ExternalWidth, "mm");
            b.AddEquation("External_Depth", LockerParameters.ExternalDepth, "mm");
            b.AddEquation("Bottom_Plate_Thickness", LockerParameters.BottomPlateThickness, "mm - 2mm steel");

            b.CreateSketch("Sketch_Base", "Top Plane", $"{LockerParameters.ExternalWidth}x{LockerParameters.ExternalDepth} rectangle");
            b.ExtrudedBoss("Boss_Base", "Sketch_Base", LockerParameters.BottomPlateThickness, "Bottom plate 2mm");

            b.CreateSketch("Sketch_Frame_Mounting", "Top Plane", "M8 holes for frame - 8 holes at corners");
            b.HoleWizard("Holes_Frame_M8", "ISO", "M8", 8, "Through All - frame mounting");

            b.CreateSketch("Sketch_Foot_Holes", "Top Plane", "4x M10 holes for feet at corners");
            b.HoleWizard("Holes_Foot_M10", "ISO", "M10", 4, "Through All - feet");

            b.CreateSketch("Sketch_Cable_Entry", "Top Plane", "2x 30x20mm cable entry openings");
            b.ExtrudedCut("Cut_Cable_Entry", "Sketch_Cable_Entry", "Through All");

            b.CreateSketch("Sketch_Conveyor_Holes", "Top Plane", "4x M8 for conveyor frame");
            b.HoleWizard("Holes_Conveyor", "ISO", "M8", 4, "Conveyor mounting");

            b.Fillet("Fillet_Bottom", 3, "All outer edges R3");
            b.Chamfer("Chamfer_Bottom_Edge", 1, 45, "Bottom face edges");
        });
    }

    public static void CreateMountingBracketCorner(SolidWorksHelper sw)
    {
        sw.CreatePart("Mounting_Bracket_Corner", b =>
        {
            b.CreateSketch("Sketch_L_Profile", "Front Plane", "L-shape 60x60x3mm, legs 40mm");
            b.ExtrudedBoss("Boss_L", "Sketch_L_Profile", 40, "L-bracket depth 40mm");
            b.CreateSketch("Sketch_Holes_Corner", "Front Plane", "2x M8 holes per leg");
            b.HoleWizard("Holes_Corner_M8", "ISO", "M8", 4, "Through All");
            b.Fillet("Fillet_Corner", 3, "L-bend outer");
        });
    }

    public static void CreateMountingBracketRail(SolidWorksHelper sw)
    {
        sw.CreatePart("Mounting_Bracket_Rail", b =>
        {
            b.CreateSketch("Sketch_Rail_Bracket", "Front Plane", "50x30x3mm flat with 90deg bend");
            b.ExtrudedBoss("Boss_Rail_Bracket", "Sketch_Rail_Bracket", 15, "Bracket for MGN rail");
            b.CreateSketch("Sketch_Rail_Holes", "Top Plane", "2x M5 slot holes (5.5x12mm)");
            b.ExtrudedCut("Cut_Rail_Slots", "Sketch_Rail_Holes", "Through All - adjustment slots");
            b.Fillet("Fillet_Rail_Bracket", 2, "Bend");
        });
    }

    public static void CreateFootAdjustable(SolidWorksHelper sw)
    {
        sw.CreatePart("Foot_Adjustable", b =>
        {
            b.CreateSketch("Sketch_Foot_Base", "Front Plane", "Circle D=50mm");
            b.ExtrudedBoss("Boss_Foot_Base", "Sketch_Foot_Base", 8, "Rubber base + steel plate");
            b.CreateSketch("Sketch_Thread", "Front Plane", "M10 threaded rod, L=50mm");
            b.RevolvedBoss("Revolve_Foot_Thread", "Sketch_Thread", 360, "M10x50 threaded stem");
            b.CreateSketch("Sketch_Hex", "Top Plane", "Hex 17mm for wrench");
            b.ExtrudedBoss("Boss_Hex", "Sketch_Hex", 6, "Hex nut area");
            b.Fillet("Fillet_Foot", 1, "Base edge");
        });
    }
}
