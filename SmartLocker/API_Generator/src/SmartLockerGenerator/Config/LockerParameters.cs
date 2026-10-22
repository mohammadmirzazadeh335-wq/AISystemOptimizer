namespace SmartLockerGenerator.Config;

/// <summary>
/// تمام پارامترهای پارامتریک دستگاه - MMGS
/// این مقادیر به Global Variables و Equations در SolidWorks متصل می‌شوند.
/// </summary>
public static class LockerParameters
{
    // --- ابعاد داخلی هر خانه (الزام پروژه) ---
    public const double CompartmentWidth = 400;    // mm - عرض داخلی
    public const double CompartmentLength = 500;   // mm - عمق داخلی
    public const double CompartmentHeight = 400;   // mm - ارتفاع داخلی

    // --- چیدمان ---
    public const int NumberOfColumns = 2;
    public const int NumberOfRows = 5;
    public const int NumberOfCompartments = 10; // = Columns * Rows

    // --- سازه ---
    public const double FrameProfile = 40;         // mm - مقطع پروفیل 40x40
    public const double FrameWallThickness = 2;    // mm
    public const double PanelThickness = 1.5;      // mm - ورق پنل
    public const double DividerThickness = 1.5;     // mm
    public const double DoorThickness = 2;         // mm
    public const double DoorClearance = 1;         // mm - لقی هر طرف
    public const double BottomPlateThickness = 2;  // mm
    public const double TopCoverThickness = 1.5;   // mm

    // --- ابعاد خارجی (محاسبه‌شده) ---
    public const double ExternalWidth = 950;       // mm
    public const double ExternalDepth = 700;       // mm
    public const double ExternalHeight = 2400;     // mm
    public const double FootHeight = 50;           // mm

    // --- کورس‌های حرکتی ---
    public const double XTravel = 480;             // mm
    public const double ZTravel = 2120;            // mm
    public const double YTravel = 450;             // mm

    // --- بار طراحی ---
    public const double MaximumDesignLoadKg = 15;  // kg nominal
    public const double MaximumPeakLoadKg = 25;    // kg max
    public const double SafetyFactor = 1.5;
    public const double DynamicFactor = 1.2;

    // --- مکانیزم ---
    public const double RollerDiameter = 40;       // mm
    public const double BeltWidth = 10;            // mm - GT2
    public const double BeltLengthX = 2200;        // mm - loop
    public const double LinearRailSizeX = 15;      // mm - MGN15
    public const double LinearRailSizeZ = 15;
    public const double LinearRailSizeY = 12;      // MGN12
    public const double LinearRailLengthX = 900;   // mm
    public const double LinearRailLengthZ = 2400;  // mm
    public const double LinearRailLengthY = 500;   // mm
    public const double PulleyTeeth = 20;
    public const double PulleyPitch = 2;           // GT2 Pitch 2mm
    public static double PulleyDiameter => PulleyTeeth * PulleyPitch / Math.PI; // ~12.73mm
    public const double LeadScrewPitch = 8;        // mm - T8x8
    public const double LeadScrewDiameter = 8;     // mm
    public const double LeadScrewLength = 2150;    // mm
    public const double ShaftDiameterX = 8;        // mm
    public const double ShaftDiameterZ = 8;

    // --- UI ---
    public const double DisplayWidth = 26;         // mm (1 inch)
    public const double DisplayHeight = 26;
    public const double DisplayCutoutWidth = 28;
    public const double DisplayCutoutHeight = 28;
    public const double ButtonDiameter = 16;
    public const double ButtonHoleDiameter = 16.5;
    public const double ButtonSpacing = 40;
    public const double KeypadWidth = 100;
    public const double KeypadHeight = 80;
    public const double KeypadCutoutWidth = 102;
    public const double KeypadCutoutHeight = 82;
    public const double IOSlotWidth = 400;
    public const double IOSlotHeight = 50;

    // --- سینی ---
    public const double TransferTrayWidth = 380;   // mm (400 - 10*2 clearance)
    public const double TransferTrayLength = 400;  // mm
    public const double TransferTrayHeight = 30;   // mm
    public const double TransferTrayThickness = 3; // mm - کف آلومینیوم

    // --- نوار نقاله ---
    public const double ConveyorWidth = 350;
    public const double ConveyorLength = 600;

    // --- الکترونیک ---
    public const double ElectronicsBayHeight = 100;
    public const double CableTrayWidth = 40;
    public const double CableTrayHeight = 30;

    // --- موقعیت خانه‌ها (محاسبه پارامتریک) ---
    public static (double X, double Z) GetCompartmentPosition(int compartmentNumber)
    {
        // compartmentNumber: 1-10
        // Col = (n-1) % Columns + 1, Row = (n-1) / Columns + 1
        int col = (compartmentNumber - 1) % NumberOfColumns + 1;
        int row = (compartmentNumber - 1) / NumberOfColumns + 1;
        double x = (col - 1) * (CompartmentWidth + DividerThickness) + CompartmentWidth / 2.0;
        double z = (row - 1) * (CompartmentHeight + DividerThickness) + CompartmentHeight / 2.0 + BottomPlateThickness + FrameProfile;
        return (x, z);
    }

    /// <summary>
    /// تمام Global Variables به فرمت SolidWorks Equations.txt
    /// </summary>
    public static string GenerateEquationsFile()
    {
        var lines = new List<string>
        {
            "' SmartLocker - Global Variables & Equations (MMGS)",
            "' SolidWorks 2025 Compatible",
            $"' Generated: {DateTime.Now:yyyy-MM-dd HH:mm:ss}",
            "",
            $"\"Compartment_Width\"= {CompartmentWidth}",
            $"\"Compartment_Length\"= {CompartmentLength}",
            $"\"Compartment_Height\"= {CompartmentHeight}",
            $"\"Number_Of_Columns\"= {NumberOfColumns}",
            $"\"Number_Of_Rows\"= {NumberOfRows}",
            $"\"Number_Of_Compartments\"= {NumberOfCompartments}",
            $"\"Frame_Profile\"= {FrameProfile}",
            $"\"Panel_Thickness\"= {PanelThickness}",
            $"\"Divider_Thickness\"= {DividerThickness}",
            $"\"Door_Thickness\"= {DoorThickness}",
            $"\"Door_Clearance\"= {DoorClearance}",
            $"\"External_Width\"= {ExternalWidth}",
            $"\"External_Depth\"= {ExternalDepth}",
            $"\"External_Height\"= {ExternalHeight}",
            $"\"X_Travel\"= {XTravel}",
            $"\"Z_Travel\"= {ZTravel}",
            $"\"Y_Travel\"= {YTravel}",
            $"\"Maximum_Design_Load\"= {MaximumDesignLoadKg}",
            $"\"Roller_Diameter\"= {RollerDiameter}",
            $"\"Belt_Width\"= {BeltWidth}",
            $"\"Belt_Length_X\"= {BeltLengthX}",
            $"\"Linear_Rail_X_Length\"= {LinearRailLengthX}",
            $"\"Linear_Rail_Z_Length\"= {LinearRailLengthZ}",
            $"\"Linear_Rail_Y_Length\"= {LinearRailLengthY}",
            $"\"Display_Width\"= {DisplayWidth}",
            $"\"Display_Height\"= {DisplayHeight}",
            $"\"Display_Cutout_Width\"= {DisplayCutoutWidth}",
            $"\"Display_Cutout_Height\"= {DisplayCutoutHeight}",
            $"\"Button_Diameter\"= {ButtonDiameter}",
            $"\"Keypad_Width\"= {KeypadWidth}",
            $"\"Keypad_Height\"= {KeypadHeight}",
            $"\"Conveyor_Width\"= {ConveyorWidth}",
            $"\"Conveyor_Length\"= {ConveyorLength}",
            $"\"Transfer_Tray_Width\"= {TransferTrayWidth}",
            $"\"Transfer_Tray_Length\"= {TransferTrayLength}",
            $"\"Pulley_Teeth\"= {PulleyTeeth}",
            $"\"Pulley_Pitch\"= {PulleyPitch}",
            $"\"Lead_Screw_Pitch\"= {LeadScrewPitch}",
        };
        return string.Join(Environment.NewLine, lines);
    }

    /// <summary>اعتبارسنجی پارامترها - جلوگیری از تداخل</summary>
    public static bool Validate(out List<string> errors)
    {
        errors = new List<string>();
        if (XTravel > LinearRailLengthX - 60) // 60mm = block length
            errors.Add($"X_Travel ({XTravel}) too large for rail length {LinearRailLengthX} - block will exit rail!");
        if (ZTravel > LinearRailLengthZ - 210) // 210mm = 2 blocks footprint
            errors.Add($"Z_Travel ({ZTravel}) too large for rail length {LinearRailLengthZ}");
        if (YTravel > LinearRailLengthY - 40)
            errors.Add($"Y_Travel ({YTravel}) too large for rail length {LinearRailLengthY}");
        if (TransferTrayWidth > CompartmentWidth - 5)
            errors.Add($"Tray width {TransferTrayWidth} too close to compartment {CompartmentWidth} - collision risk!");
        if (NumberOfCompartments != NumberOfColumns * NumberOfRows)
            errors.Add($"Compartment count mismatch: {NumberOfCompartments} != {NumberOfColumns}*{NumberOfRows}");
        return errors.Count == 0;
    }
}
