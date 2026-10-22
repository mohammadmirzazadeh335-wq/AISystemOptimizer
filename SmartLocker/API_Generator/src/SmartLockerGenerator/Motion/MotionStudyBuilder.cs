using SmartLockerGenerator.Config;
using SmartLockerGenerator.Utils;

namespace SmartLockerGenerator.Motion;

/// <summary>
/// ساخت Motion Studyها با SolidWorks API
/// SolidWorks Motion API: IMotionStudyManager, IMotionStudy
/// </summary>
public class MotionStudyBuilder
{
    private readonly SolidWorksHelper _helper;
    private readonly List<MotionStudyDef> _studies = new();

    public record MotionStudyDef(
        string Name,
        string Type, // Animation یا Motion Analysis
        double DurationSec,
        List<MotorDef> Motors,
        string Description);

    public record MotorDef(
        string Name,
        string MotorType, // Linear یا Rotary
        string Entity,     // قطعه/وجه محرک
        string Target,     // هدف نسبی
        double StartValue,
        double EndValue,
        string Profile,    // Trapezoidal, Constant Speed, etc.
        double MaxSpeed,
        double Acceleration);

    public MotionStudyBuilder(SolidWorksHelper helper)
    {
        _helper = helper;
    }

    public void BuildAll()
    {
        _helper.Log("\n=== Building Motion Studies ===");

        // پیش‌تعریف تمام مطالعات
        DefineStudies();

        foreach (var study in _studies)
        {
            CreateStudy(study);
        }

        // KeyFrame های Mate Controller
        BuildMateControllerPositions();

        _helper.Log($"Motion Studies created: {_studies.Count}");
    }

    private void DefineStudies()
    {
        // 1. جاروی X
        _studies.Add(new MotionStudyDef(
            "Study_X_Sweep",
            "Animation",
            4.0,
            new List<MotorDef>
            {
                new("Motor_X_Sweep", "Linear", "X_Carriage <-> Frame Left", "X_Carriage Left vs Frame",
                    0, LockerParameters.XTravel, "Trapezoidal", 300, 500)
            },
            "جاروی کامل محور X: 0->480->0 در 4 ثانیه"));

        // 2. جاروی Z
        _studies.Add(new MotionStudyDef(
            "Study_Z_Sweep",
            "Animation",
            10.0,
            new List<MotorDef>
            {
                new("Motor_Z_Sweep", "Linear", "Z_Carriage <-> Bottom_Plate", "Z_Carriage Bottom vs Bottom_Plate",
                    0, LockerParameters.ZTravel, "Trapezoidal", 200, 500)
            },
            "جاروی کامل Z: 0->2120->0 در 10 ثانیه"));

        // 3. توری XY - بازدید تمام خانه‌ها
        _studies.Add(new MotionStudyDef(
            "Study_XZ_Grid",
            "Animation",
            20.0,
            new List<MotorDef>
            {
                new("Motor_X_Grid", "Linear", "X_Carriage", "Frame", 0, LockerParameters.XTravel, "Stepped", 300, 500),
                new("Motor_Z_Grid", "Linear", "Z_Carriage", "Bottom_Plate", 0, LockerParameters.ZTravel, "Stepped", 200, 500),
            },
            "توری X/Z: پله‌ای از Row1/Col1 تا Row5/Col2 - بازدید 10 خانه"));

        // 4. چرخه دریافت به خانه 06
        var pos06 = LockerParameters.GetCompartmentPosition(6);
        _studies.Add(new MotionStudyDef(
            "Study_Deposit_06",
            "Motion Analysis",
            12.0,
            new List<MotorDef>
            {
                new("Motor_X_To_06", "Linear", "X_Carriage", "Frame", 0, pos06.X, "Trapezoidal (0.5->3.0s)", 300, 500),
                new("Motor_Z_To_06", "Linear", "Z_Carriage", "Bottom_Plate", 0, pos06.Z, "Trapezoidal (0.5->6.0s)", 200, 500),
                new("Motor_Y_Insert_06", "Linear", "Transfer_Tray", "Z_Carriage", 0, 450, "Trapezoidal (6.0->8.0s)", 150, 500),
                new("Motor_Y_Retract_06", "Linear", "Transfer_Tray", "Z_Carriage", 450, 0, "Trapezoidal (8.5->10.5s)", 150, 500),
                new("Motor_X_Home", "Linear", "X_Carriage", "Frame", pos06.X, 0, "Trapezoidal (10.5->12.0s)", 300, 500),
                new("Motor_Z_Home", "Linear", "Z_Carriage", "Bottom_Plate", pos06.Z, 0, "Trapezoidal (10.5->12.0s)", 200, 500),
            },
            $"چرخه دریافت به خانه 06 (Col2/Row3, X={pos06.X}, Z={pos06.Z}): X,Z->Y Insert->Y Retract->Home"));

        // 5. چرخه تحویل از خانه 06
        _studies.Add(new MotionStudyDef(
            "Study_Retrieval_06",
            "Motion Analysis",
            12.0,
            new List<MotorDef>
            {
                new("Motor_X_To_06_Ret", "Linear", "X_Carriage", "Frame", 0, pos06.X, "Trapezoidal (0->2.5s)", 300, 500),
                new("Motor_Z_To_06_Ret", "Linear", "Z_Carriage", "Bottom_Plate", 0, pos06.Z, "Trapezoidal (0->5.0s)", 200, 500),
                new("Motor_Y_Capture", "Linear", "Transfer_Tray", "Z_Carriage", 0, 450, "Trapezoidal (5.0->7.0s)", 150, 500),
                new("Motor_Y_Return", "Linear", "Transfer_Tray", "Z_Carriage", 450, 0, "Trapezoidal (7.0->9.0s)", 150, 500),
                new("Motor_X_To_I_O", "Linear", "X_Carriage", "Frame", pos06.X, 0, "Trapezoidal (9.0->11.0s)", 300, 500),
                new("Motor_Conveyor_Out", "Rotary", "Roller_Drive", "Conveyor_Frame", 0, 360 * 2, "Constant 60RPM (9.0->12.0s)", 360, 0),
            },
            "چرخه تحویل از خانه 06: Gantry->Tray Capture->Return->Conveyor Out"));

        // 6. چرخه کامل تمام 10 خانه (60 ثانیه)
        _studies.Add(new MotionStudyDef(
            "Study_Full_Cycle_All",
            "Animation",
            60.0,
            new List<MotorDef>
            {
                new("Motor_X_Seq", "Linear", "X_Carriage", "Frame", 0, LockerParameters.XTravel, "Sequential via Key Frames", 300, 500),
                new("Motor_Z_Seq", "Linear", "Z_Carriage", "Bottom_Plate", 0, LockerParameters.ZTravel, "Sequential via Key Frames", 200, 500),
                new("Motor_Y_Seq", "Linear", "Transfer_Tray", "Z_Carriage", 0, LockerParameters.YTravel, "Per-compartment Y injection", 150, 500),
            },
            "چرخه کامل: Deposit و Retrieval برای تمام 10 خانه متوالی (6 ثانیه هر خانه x 10 = 60 ثانیه)"));
    }

    private void CreateStudy(MotionStudyDef study)
    {
        _helper.Log($"  Study: {study.Name} ({study.Type}, {study.DurationSec}s)");
        _helper.Log($"    Description: {study.Description}");
        foreach (var motor in study.Motors)
        {
            _helper.Log($"    Motor: {motor.Name} [{motor.MotorType}] {motor.Entity} : {motor.StartValue} -> {motor.EndValue}mm Profile={motor.Profile} Vmax={motor.MaxSpeed}mm/s");
        }

        // در حالت واقعی، اینجا IMotionStudyManager API فراخوانی می‌شود:
        // var motionMgr = swModel.Extension.GetMotionStudyManager();
        // var study = motionMgr.CreateMotionStudy(study.Name);
        // foreach (var motor in study.Motors)
        //     study.AddMotor(motor.Name, (int)swMotorType_e.swMotorLinear, entity, ...);
        // study.SetTime(study.DurationSec);
        // study.AddKeyFrame(time, distance_mate_name, value);
        // study.SaveToFile(outputPath);

        // حالت DryRun: فقط لاگ
        if (_helper.Verbose)
        {
            _helper.Log($"    [DRY-RUN] Would create: IMotionStudyManager.CreateMotionStudy({study.Name})");
            _helper.Log($"    [DRY-RUN] Would add {study.Motors.Count} motors with Trapezoidal profile");
            _helper.Log($"    [DRY-RUN] Key Frames: 0s, {study.DurationSec / 2:F1}s, {study.DurationSec:F1}s");
        }
    }

    private void BuildMateControllerPositions()
    {
        _helper.Log("\n  Mate Controller Positions (10 compartments + Home):");

        // موقعیت Home
        _helper.Log($"    Position_Home: X=0, Z=0, Y=0 (Gantry at input/conveyor)");

        // موقعیت هر خانه
        for (int n = 1; n <= LockerParameters.NumberOfCompartments; n++)
        {
            var (x, z) = LockerParameters.GetCompartmentPosition(n);
            // Z شامل offset کف است، X از مرکز ستون
            // برای Y، همیشه 0->450 Injection
            _helper.Log($"    Position_{n:D2} (House {n:D2}): X={x:F1}mm, Z={z:F1}mm, Y=450mm (Insert into compartment {n})");
            // در واقعیت: MateController.AddPosition($"Position_{n:D2}", new Dictionary<string, double>
            //   { ["X_LimitDistance_0_480"] = x, ["Z_LimitDistance_0_2120"] = z, ["Y_LimitDistance_0_450"] = 450 });
        }

        _helper.Log($"    Total positions: {LockerParameters.NumberOfCompartments + 1} (10 houses + Home)");

        // توضیح API Mate Controller
        if (_helper.Verbose)
        {
            _helper.Log("    [DRY-RUN] Mate Controller via: AssemblyDoc.MateController.AddPosition / Assembly.FeatureManager.InsertMateController");
        }
    }

    public IReadOnlyList<MotionStudyDef> Studies => _studies;
}
