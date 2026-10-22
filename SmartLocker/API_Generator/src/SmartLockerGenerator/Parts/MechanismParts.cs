using SmartLockerGenerator.Config;
using SmartLockerGenerator.Utils;

namespace SmartLockerGenerator.Parts;

public static class MechanismParts
{
    public static void CreateAll(SolidWorksHelper sw)
    {
        CreateLinearRailX(sw);
        CreateLinearRailZ(sw);
        CreateLinearRailY(sw);
        CreateGuideBlockX(sw);
        CreateGuideBlockZ(sw);
        CreateGuideBlockY(sw);
        CreateShaftX(sw);
        CreateLeadScrew(sw);
        CreatePulleyGT2(sw);
        CreateBeltGT2(sw);
        CreateBearingBlock(sw);
        CreateBeltTensioner(sw);
        CreateMotorMounts(sw);
        CreateSensors(sw);
    }

    public static void CreateLinearRailX(SolidWorksHelper sw)
    {
        sw.CreatePart("Linear_Rail_X", b =>
        {
            b.AddEquation("Linear_Rail_Length_X", LockerParameters.LinearRailLengthX, "mm - 900mm MGN15");
            b.AddEquation("Rail_Width", LockerParameters.LinearRailSizeX, "mm - MGN15");
            b.AddEquation("Rail_Height", 10, "mm - MGN15 rail height");

            // Rail profile - simplified MGN15 cross section
            b.CreateSketch("Sketch_Rail_Profile_X", "Front Plane", "MGN15 profile: 15mm wide, 10mm high, with ball grooves (simplified)");
            b.AddFeature("Sketch_Rail_Profile_X", "Sketch", "Outer 15x10, grooves 2x semicircular R1.5mm");
            b.ExtrudedBoss("Boss_Rail_X", "Sketch_Rail_Profile_X", LockerParameters.LinearRailLengthX, "Rail body 900mm long");

            // Mounting holes - M4, pitch 60mm
            int holeCount = (int)(LockerParameters.LinearRailLengthX / 60) + 1;
            b.CreateSketch("Sketch_Rail_Holes_X", "Top Plane", $"M4 holes, pitch 60mm, count {holeCount}");
            b.HoleWizard("Holes_Rail_M4_X", "ISO", "M4", holeCount, "Depth 8mm - mounting to frame/bracket");
            b.LinearPattern("Pattern_Rail_Holes_X", "Holes_Rail_M4_X", holeCount, 60, "Z");

            // Reference geometry for mating
            b.ReferenceAxis("Axis_Rail_X", "Along rail length through center");
            b.ReferencePlane("Plane_Rail_X_Top", "Top face of rail for block mating");

            b.Fillet("Fillet_Rail_X", 0.5, "Rail outer edges R0.5");
        });
    }

    public static void CreateLinearRailZ(SolidWorksHelper sw)
    {
        sw.CreatePart("Linear_Rail_Z", b =>
        {
            b.AddEquation("Linear_Rail_Length_Z", LockerParameters.LinearRailLengthZ, "mm - 2400mm MGN15");
            b.CreateSketch("Sketch_Rail_Profile_Z", "Front Plane", "MGN15 profile 15x10mm");
            b.ExtrudedBoss("Boss_Rail_Z", "Sketch_Rail_Profile_Z", LockerParameters.LinearRailLengthZ, "Rail Z 2400mm");
            int holes = (int)(LockerParameters.LinearRailLengthZ / 60) + 1;
            b.CreateSketch("Sketch_Rail_Holes_Z", "Top Plane", $"M4 holes x{holes}, pitch 60mm");
            b.HoleWizard("Holes_Rail_M4_Z", "ISO", "M4", holes, "Depth 8mm");
            b.LinearPattern("Pattern_Rail_Holes_Z", "Holes_Rail_M4_Z", holes, 60, "Z");
            b.ReferenceAxis("Axis_Rail_Z", "Along rail length");
            b.Fillet("Fillet_Rail_Z", 0.5, "Edges");
        });
    }

    public static void CreateLinearRailY(SolidWorksHelper sw)
    {
        sw.CreatePart("Linear_Rail_Y", b =>
        {
            b.AddEquation("Linear_Rail_Length_Y", LockerParameters.LinearRailLengthY, "mm - 500mm MGN12");
            b.CreateSketch("Sketch_Rail_Profile_Y", "Front Plane", "MGN12 profile: 12mm wide, 8mm high");
            b.ExtrudedBoss("Boss_Rail_Y", "Sketch_Rail_Profile_Y", LockerParameters.LinearRailLengthY, "Rail Y 500mm (on Z_Carriage)");
            int holes = (int)(LockerParameters.LinearRailLengthY / 60) + 1;
            b.CreateSketch("Sketch_Rail_Holes_Y", "Top Plane", $"M3 holes x{holes}");
            b.HoleWizard("Holes_Rail_M3_Y", "ISO", "M3", holes, "Depth 6mm");
            b.Fillet("Fillet_Rail_Y", 0.5, "Edges");
        });
    }

    public static void CreateGuideBlockX(SolidWorksHelper sw)
    {
        sw.CreatePart("Linear_Guide_Block_X", b =>
        {
            b.CreateSketch("Sketch_Block_X", "Top Plane", "MGN15H block: 60x45x25mm (LxWxH)");
            b.ExtrudedBoss("Boss_Block_X", "Sketch_Block_X", 25, "Block body 25mm high");
            b.CreateSketch("Sketch_Block_Groove", "Front Plane", "Ball groove matching rail - semicircular R1.5mm");
            b.ExtrudedCut("Cut_Block_Groove", "Sketch_Block_Groove", "Through All - rail contact groove");
            b.CreateSketch("Sketch_Block_Holes", "Top Plane", "4x M5 mounting holes, PCD 38x30mm");
            b.HoleWizard("Holes_Block_M5_X", "ISO", "M5", 4, "Depth 8mm - carriage mounting");
            b.CreateSketch("Sketch_Block_Balls", "Front Plane", "Ball circulation placeholder - 2x channels Ø3mm");
            b.ExtrudedCut("Cut_Ball_Channels", "Sketch_Block_Balls", "Conceptual - not functional");
            b.Fillet("Fillet_Block_X", 1, "Block edges R1");
            b.ReferencePlane("Plane_Block_X_Top", "Top face for carriage mating");
        });
    }

    public static void CreateGuideBlockZ(SolidWorksHelper sw)
    {
        sw.CreatePart("Linear_Guide_Block_Z", b =>
        {
            b.CreateSketch("Sketch_Block_Z", "Top Plane", "MGN15H block 60x45x25mm");
            b.ExtrudedBoss("Boss_Block_Z", "Sketch_Block_Z", 25, "Block Z");
            b.CreateSketch("Sketch_Block_Z_Groove", "Front Plane", "Rail groove R1.5mm");
            b.ExtrudedCut("Cut_Block_Z_Groove", "Sketch_Block_Z_Groove", "Through All");
            b.HoleWizard("Holes_Block_M5_Z", "ISO", "M5", 4, "Mounting holes");
            b.Fillet("Fillet_Block_Z", 1, "Edges");
        });
    }

    public static void CreateGuideBlockY(SolidWorksHelper sw)
    {
        sw.CreatePart("Linear_Guide_Block_Y", b =>
        {
            b.CreateSketch("Sketch_Block_Y", "Top Plane", "MGN12 block: 45x35x20mm");
            b.ExtrudedBoss("Boss_Block_Y", "Sketch_Block_Y", 20, "Block Y - smaller MGN12");
            b.CreateSketch("Sketch_Block_Y_Groove", "Front Plane", "Groove R1.2mm for MGN12 rail");
            b.ExtrudedCut("Cut_Block_Y_Groove", "Sketch_Block_Y_Groove", "Through All");
            b.HoleWizard("Holes_Block_M4_Y", "ISO", "M4", 4, "Mounting");
            b.Fillet("Fillet_Block_Y", 1, "Edges");
        });
    }

    public static void CreateShaftX(SolidWorksHelper sw)
    {
        sw.CreatePart("Shaft_Drive_X", b =>
        {
            b.AddEquation("Shaft_Diameter_X", LockerParameters.ShaftDiameterX, "mm - Ø8mm");
            b.AddEquation("Shaft_Length_X", 920, "mm - spans frame width with bearings");
            b.CreateSketch("Sketch_Shaft_X", "Front Plane", "Shaft profile: Ø8mm x 920mm, with keyway");
            b.RevolvedBoss("Revolve_Shaft_X", "Sketch_Shaft_X", 360, "Shaft body Ø8x920");
            b.CreateSketch("Sketch_Shaft_Shoulder", "Front Plane", "Shoulder Ø12mm x 5mm at each end");
            b.ExtrudedBoss("Boss_Shaft_Shoulder", "Sketch_Shaft_Shoulder", 5, "Bearing shoulder each end");
            b.CreateSketch("Sketch_Keyway", "Top Plane", "Keyway 3x3mm, L=20mm for pulley");
            b.ExtrudedCut("Cut_Keyway_Shaft", "Sketch_Keyway", "Depth 1.5mm - pulley key");
            b.Chamfer("Chamfer_Shaft_X", 0.5, 45, "Both ends");
            b.ReferenceAxis("Axis_Shaft_X", "Central axis for Concentric mate");
        });
    }

    public static void CreateLeadScrew(SolidWorksHelper sw)
    {
        sw.CreatePart("Lead_Screw_T8x8", b =>
        {
            b.AddEquation("Lead_Screw_Diameter", LockerParameters.LeadScrewDiameter, "mm - T8");
            b.AddEquation("Lead_Screw_Pitch", LockerParameters.LeadScrewPitch, "mm - 8mm pitch, 4-start");
            b.AddEquation("Lead_Screw_Length", LockerParameters.LeadScrewLength, "mm - 2150mm");

            // Lead screw body
            b.CreateSketch("Sketch_LeadScrew_Profile", "Front Plane", "Screw profile: Ø8mm core");
            b.RevolvedBoss("Revolve_LeadScrew", "Sketch_LeadScrew_Profile", 360, "Lead screw core Ø8x2150");

            // Helix for thread
            b.CreateSketch("Sketch_Helix_Circle", "Top Plane", "Circle Ø8mm for helix path");
            b.AddFeature("Helix_Thread", "Helix/Spiral", $"Pitch={LockerParameters.LeadScrewPitch}mm, Revolutions={LockerParameters.LeadScrewLength / LockerParameters.LeadScrewPitch:F0}, Height={LockerParameters.LeadScrewLength}mm, Clockwise");

            // Thread sweep - trapezoidal profile
            b.CreateSketch("Sketch_Thread_Profile", "Front Plane", "Trapezoid: width 2mm, depth 1mm, angle 30deg");
            b.AddFeature("Sweep_Thread", "Sweep", "Profile=Sketch_Thread_Profile, Path=Helix_Thread - creates thread");

            b.CreateSketch("Sketch_LeadScrew_Bearing_Ends", "Front Plane", "Bearing journals Ø8mm, L=20mm each end, Ø12mm shoulder");
            b.ExtrudedBoss("Boss_LeadScrew_Journal", "Sketch_LeadScrew_Bearing_Ends", 20, "Bearing journals");
            b.Chamfer("Chamfer_LeadScrew", 0.5, 45, "Both ends");
            b.ReferenceAxis("Axis_LeadScrew", "Central axis");
        });

        sw.CreatePart("Lead_Screw_Nut_T8", b =>
        {
            b.CreateSketch("Sketch_Nut_Body", "Front Plane", "Flange nut: Ø22mm, Flange 38x8mm");
            b.RevolvedBoss("Revolve_Nut", "Sketch_Nut_Body", 360, "Nut body with flange");
            // Internal thread (simplified - hole)
            b.CreateSketch("Sketch_Nut_Hole", "Front Plane", "Internal Ø8mm with thread clearance");
            b.ExtrudedCut("Cut_Nut_Hole", "Sketch_Nut_Hole", "Through All - screw passage");
            b.CreateSketch("Sketch_Nut_Holes", "Top Plane", "4x M5 flange mounting holes, PCD 30mm");
            b.HoleWizard("Holes_Nut_M5", "ISO", "M5", 4, "Through All - mounting to Z_Carriage");
            b.Fillet("Fillet_Nut", 1, "Flange edges");
        });
    }

    public static void CreatePulleyGT2(SolidWorksHelper sw)
    {
        sw.CreatePart("Pulley_GT2_20T", b =>
        {
            b.AddEquation("Pulley_Teeth", LockerParameters.PulleyTeeth, "GT2 20T");
            b.AddEquation("Pulley_Pitch", LockerParameters.PulleyPitch, "mm");
            b.AddEquation("Pulley_Diameter", LockerParameters.PulleyDiameter, "mm - ~12.73mm pitch diameter");

            // Pulley body
            b.CreateSketch("Sketch_Pulley_Body", "Front Plane", $"Pulley profile: OD={LockerParameters.PulleyDiameter + 1.5:F1}mm, ID bore Ø8mm, width 10mm");
            b.RevolvedBoss("Revolve_Pulley_Body", "Sketch_Pulley_Body", 360, "Pulley body with flanges");

            // Teeth - simplified as groove
            b.CreateSketch("Sketch_Pulley_Teeth", "Front Plane", "GT2 tooth profile: 20 teeth, pitch 2mm - simplified semicircular groove");
            b.AddFeature("Cut_Pulley_Teeth", "Extruded Cut (or Sweep)", "Teeth grooves - simplified representation, 20x around circumference");
            b.LinearPattern("Pattern_Pulley_Teeth", "Cut_Pulley_Teeth", 20, 18, "Circular - 360/20=18deg each");

            // Flanges
            b.CreateSketch("Sketch_Pulley_Flange", "Front Plane", "Flange Ø16mm, thickness 1mm, each side");
            b.ExtrudedBoss("Boss_Pulley_Flange_Top", "Sketch_Pulley_Flange", 1, "Top flange to retain belt");
            b.ExtrudedBoss("Boss_Pulley_Flange_Bot", "Sketch_Pulley_Flange", 1, "Bottom flange");

            // Bore
            b.CreateSketch("Sketch_Pulley_Bore", "Front Plane", "Bore Ø8mm with keyway/M3 grub screw");
            b.ExtrudedCut("Cut_Pulley_Bore", "Sketch_Pulley_Bore", "Through All - shaft bore");
            b.CreateSketch("Sketch_Grub_Screw", "Front Plane", "M3 grub screw hole");
            b.HoleWizard("Hole_Grub_M3", "ISO", "M3", 2, "Radial - shaft fixing, 90deg apart");

            b.Fillet("Fillet_Pulley", 0.3, "Flange edges");
            b.ReferenceAxis("Axis_Pulley", "Central bore axis for Concentric mate");
        });

        sw.CreatePart("Pulley_Idler_X", b =>
        {
            b.CreateSketch("Sketch_Idler_Body", "Front Plane", "Idler: OD=16mm, ID bearing seat Ø22mm (for 625ZZ)");
            b.RevolvedBoss("Revolve_Idler", "Sketch_Idler_Body", 360, "Idler body with bearing pocket");
            b.CreateSketch("Sketch_Idler_Bearing", "Front Plane", "Bearing 625ZZ: Ø5x16x5mm pocket");
            b.ExtrudedCut("Cut_Idler_Bearing", "Sketch_Idler_Bearing", "Depth 5mm - bearing seat each side");
            b.Fillet("Fillet_Idler", 0.3, "Edges");
        });
    }

    public static void CreateBeltGT2(SolidWorksHelper sw)
    {
        sw.CreatePart("Belt_GT2_X", b =>
        {
            b.AddEquation("Belt_Width", LockerParameters.BeltWidth, "mm - 10mm GT2");
            b.AddEquation("Belt_Length_X", LockerParameters.BeltLengthX, "mm - loop length 2200mm");
            b.AddEquation("Pulley_Center_Distance", 850, "mm - between drive and idler");

            // Belt as closed-loop thin extrusion along path
            b.CreateSketch("Sketch_Belt_Path", "Top Plane", "Closed rectangular loop: 850mm centers + semicircles at each end (around pulleys)");
            b.AddFeature("Sketch_Belt_Path", "Sketch", "Loop: 2x straight 850mm + 2x semicircle D=12.73mm => total ~1750mm");

            // Belt cross section
            b.CreateSketch("Sketch_Belt_Section", "Front Plane", "Belt cross section: 10mm wide x 1.5mm thick with teeth (simplified flat)");
            b.AddFeature("Sweep_Belt", "Sweep (Thin)", $"Path=Sketch_Belt_Path, Profile=Sketch_Belt_Section, Thickness={LockerParameters.BeltWidth}mm");

            // Teeth representation (visual only)
            b.CreateSketch("Sketch_Belt_Teeth", "Front Plane", "GT2 teeth on inner surface - pitch 2mm, height 0.75mm");
            b.ExtrudedBoss("Boss_Belt_Teeth", "Sketch_Belt_Teeth", 0.75, "Teeth - visual only, Linear Pattern pitch 2mm around loop (simplified)");

            b.ReferenceAxis("Axis_Belt", "Belt loop center - for Belt/Chain mate");
        });

        sw.CreatePart("Belt_GT2_Z_Sync", b =>
        {
            b.CreateSketch("Sketch_Belt_Z_Path", "Front Plane", "Sync belt loop: 2x Lead Screws, center distance ~870mm");
            b.AddFeature("Sweep_Belt_Z", "Sweep (Thin)", "Sync belt connecting 2 Lead Screws, width 10mm");
            b.ReferenceAxis("Axis_Belt_Z", "Center");
        });
    }

    public static void CreateBearingBlock(SolidWorksHelper sw)
    {
        sw.CreatePart("Bearing_Block_X", b =>
        {
            b.CreateSketch("Sketch_Bearing_Block", "Front Plane", "SK8 bearing block: 42x32x14mm, bore Ø8mm");
            b.ExtrudedBoss("Boss_Bearing_Block", "Sketch_Bearing_Block", 14, "SK8 vertical bearing block");
            b.CreateSketch("Sketch_Bearing_Bore", "Front Plane", "Bore Ø8mm for shaft");
            b.ExtrudedCut("Cut_Bearing_Bore", "Sketch_Bearing_Bore", "Through All - shaft passage");
            b.CreateSketch("Sketch_Bearing_Holes", "Top Plane", "2x M5 mounting holes, 32mm apart");
            b.HoleWizard("Holes_Bearing_M5", "ISO", "M5", 2, "Through All - frame mounting");
            b.Fillet("Fillet_Bearing", 1, "Edges");
        });

        sw.CreatePart("Bearing_Block_Z", b =>
        {
            b.CreateSketch("Sketch_Bearing_Z", "Front Plane", "KP08 bearing block: 40x40x20mm");
            b.ExtrudedBoss("Boss_Bearing_Z", "Sketch_Bearing_Z", 20, "KP08 for Lead Screw");
            b.CreateSketch("Sketch_Bearing_Z_Bore", "Front Plane", "Bore Ø8mm");
            b.ExtrudedCut("Cut_Bearing_Z_Bore", "Sketch_Bearing_Z_Bore", "Through All");
            b.HoleWizard("Holes_Bearing_Z_M5", "ISO", "M5", 2, "Mounting");
            b.Fillet("Fillet_Bearing_Z", 1, "Edges");
        });
    }

    public static void CreateBeltTensioner(SolidWorksHelper sw)
    {
        sw.CreatePart("Belt_Tensioner_X", b =>
        {
            b.CreateSketch("Sketch_Tensioner_Base", "Front Plane", "Base 50x30x5mm, with 20mm slot");
            b.ExtrudedBoss("Boss_Tensioner_Base", "Sketch_Tensioner_Base", 5, "Tensioner base plate");
            b.CreateSketch("Sketch_Tensioner_Slot", "Top Plane", "Slot 5.5x20mm for M5 adjustment screw");
            b.ExtrudedCut("Cut_Tensioner_Slot", "Sketch_Tensioner_Slot", "Through All - adjustment slot");
            b.CreateSketch("Sketch_Tensioner_Screw", "Front Plane", "M5x30 screw with spring");
            b.ExtrudedBoss("Boss_Tensioner_Screw", "Sketch_Tensioner_Screw", 30, "Adjustment screw + spring (placeholder)");
            b.CreateSketch("Sketch_Idler_Mount", "Front Plane", "Idler pulley mount Ø5mm bore");
            b.ExtrudedCut("Cut_Idler_Bore", "Sketch_Idler_Mount", "Through All");
            b.Fillet("Fillet_Tensioner", 1, "Edges");
        });
    }

    public static void CreateMotorMounts(SolidWorksHelper sw)
    {
        sw.CreatePart("Motor_Mount_X", b =>
        {
            b.CreateSketch("Sketch_Motor_Mount_X", "Front Plane", "L-bracket 80x60x5mm, for NEMA23 (56x56mm)");
            b.ExtrudedBoss("Boss_Motor_Mount_X", "Sketch_Motor_Mount_X", 5, "L-bracket vertical + horizontal");
            b.CreateSketch("Sketch_Motor_Holes_X", "Front Plane", "4x M5 holes PCD 47.14mm for NEMA23");
            b.HoleWizard("Holes_Motor_M5_X", "ISO", "M5", 4, "Through All - motor mounting");
            b.CreateSketch("Sketch_Motor_Shaft_Hole_X", "Front Plane", "Shaft clearance Ø10mm");
            b.ExtrudedCut("Cut_Shaft_Hole_X", "Sketch_Motor_Shaft_Hole_X", "Through All");
            b.CreateSketch("Sketch_Frame_Holes_X", "Front Plane", "2x M6 frame mounting holes");
            b.HoleWizard("Holes_Frame_M6_X", "ISO", "M6", 2, "Through All");
            b.Fillet("Fillet_Motor_Mount_X", 3, "L-bend R3");
        });

        sw.CreatePart("Motor_Mount_Z", b =>
        {
            b.CreateSketch("Sketch_Motor_Mount_Z", "Front Plane", "L-bracket 100x80x8mm for NEMA23 Z motor");
            b.ExtrudedBoss("Boss_Motor_Mount_Z", "Sketch_Motor_Mount_Z", 8, "Heavy duty for Z");
            b.HoleWizard("Holes_Motor_M5_Z", "ISO", "M5", 4, "NEMA23 mounting");
            b.HoleWizard("Holes_Frame_M6_Z", "ISO", "M6", 4, "Frame mounting");
            b.Fillet("Fillet_Motor_Mount_Z", 3, "Bend");
        });

        sw.CreatePart("Motor_Mount_Y", b =>
        {
            b.CreateSketch("Sketch_Motor_Mount_Y", "Front Plane", "L-bracket 40x40x3mm for NEMA17");
            b.ExtrudedBoss("Boss_Motor_Mount_Y", "Sketch_Motor_Mount_Y", 3, "NEMA17 mount on Z_Carriage");
            b.HoleWizard("Holes_Motor_M3_Y", "ISO", "M3", 4, "NEMA17 31mm PCD");
            b.Fillet("Fillet_Motor_Mount_Y", 2, "Bend");
        });

        // Placeholder motors
        sw.CreatePart("Motor_NEMA23_X", b =>
        {
            b.CreateSketch("Sketch_NEMA23_Body", "Front Plane", "56x56x56mm body + 38mm shaft Ø6.35mm");
            b.ExtrudedBoss("Boss_NEMA23_Body", "Sketch_NEMA23_Body", 56, "Motor body - placeholder 56x56mm square");
            b.CreateSketch("Sketch_NEMA23_Shaft", "Front Plane", "Shaft Ø6.35mm, L=21mm");
            b.RevolvedBoss("Revolve_NEMA23_Shaft", "Sketch_NEMA23_Shaft", 360, "Motor shaft");
            b.CreateSketch("Sketch_NEMA23_Holes", "Front Plane", "4x M5 on PCD 47.14mm");
            b.HoleWizard("Holes_NEMA23_M5", "ISO", "M5", 4, "Motor mounting");
            b.ReferenceAxis("Axis_Motor_Shaft", "Shaft axis for pulley mating");
        });

        sw.CreatePart("Motor_NEMA17_Y", b =>
        {
            b.CreateSketch("Sketch_NEMA17", "Front Plane", "42x42x34mm body, shaft Ø5mm");
            b.ExtrudedBoss("Boss_NEMA17", "Sketch_NEMA17", 34, "NEMA17 placeholder");
            b.RevolvedBoss("Revolve_NEMA17_Shaft", "Sketch_NEMA17", 360, "Shaft Ø5x24mm");
            b.ReferenceAxis("Axis_NEMA17", "Shaft axis");
        });
    }

    public static void CreateSensors(SolidWorksHelper sw)
    {
        sw.CreatePart("Sensor_Placeholder", b =>
        {
            b.CreateSketch("Sketch_Sensor", "Front Plane", "Sensor placeholder: 15x15x10mm");
            b.ExtrudedBoss("Boss_Sensor", "Sketch_Sensor", 10, "Sensor body - optical/inductive");
            b.CreateSketch("Sketch_Sensor_Holes", "Top Plane", "2x M3 mounting holes");
            b.HoleWizard("Holes_Sensor_M3", "ISO", "M3", 2, "Through All");
            b.CreateSketch("Sketch_Sensor_Cable", "Front Plane", "Cable exit Ø4mm");
            b.ExtrudedCut("Cut_Sensor_Cable", "Sketch_Sensor_Cable", "Through All");
            b.ReferencePlane("Plane_Sensor_Face", "Sensing face for distance mate");
        });

        sw.CreatePart("Sensor_Presence", b =>
        {
            b.CreateSketch("Sketch_Presence", "Front Plane", "Presence sensor: 15x15x10mm, ceiling mount");
            b.ExtrudedBoss("Boss_Presence", "Sketch_Presence", 10, "Compartment presence sensor");
            b.HoleWizard("Holes_Presence_M3", "ISO", "M3", 2, "Mounting");
        });

        sw.CreatePart("Mechanical_Stop", b =>
        {
            b.CreateSketch("Sketch_Stop", "Front Plane", "Stop block: 20x20x15mm with rubber bumper Ø12x5mm");
            b.ExtrudedBoss("Boss_Stop", "Sketch_Stop", 15, "Aluminum stop block 20x20x15");
            b.CreateSketch("Sketch_Bumper", "Front Plane", "Rubber bumper Ø12x5mm on face");
            b.ExtrudedBoss("Boss_Bumper", "Sketch_Bumper", 5, "Rubber bumper - absorbs impact");
            b.CreateSketch("Sketch_Stop_Holes", "Top Plane", "2x M5 mounting holes");
            b.HoleWizard("Holes_Stop_M5", "ISO", "M5", 2, "Through All");
            b.Fillet("Fillet_Stop", 2, "Block edges");
        });
    }
}
