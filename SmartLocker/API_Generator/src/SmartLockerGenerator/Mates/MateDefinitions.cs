namespace SmartLockerGenerator.Mates;

/// <summary>
/// تعریف تمام Mateها به‌صورت متمرکز - با نوع واقعی SolidWorks 2025
/// این کلاس مرجعی برای مستندسازی و اعتبارسنجی Mateهاست.
/// کد واقعی Mateها در AllAssemblies.cs اعمال می‌شود.
/// </summary>
public static class MateDefinitions
{
    public record MateDef(string Name, string Type, string Entity1, string Entity2, string Limits, string Notes);

    public static readonly List<MateDef> AllMates = new()
    {
        // ===== ثابت‌سازی شاسی =====
        new("Frame_Fix", "Fix", "Main_Frame", "Origin", "-", "شاسی مرجع ثابت - فقط یکی Fix"),
        new("Bottom_Plate_Coincident", "Coincident", "Bottom_Plate Top", "Frame Bottom", "-", "کف روی فریم"),
        new("Side_Panel_Left_Coincident", "Coincident", "Side_Panel_Left Inner", "Frame Left Inner", "-", "پنل جانبی چپ"),
        new("Side_Panel_Right_Coincident", "Coincident", "Side_Panel_Right Inner", "Frame Right Inner", "-", "پنل جانبی راست با دریچه سرویس"),
        new("Rear_Panel_Coincident", "Coincident", "Rear_Panel Inner", "Frame Rear Inner", "-", "پنل عقب 2 تکه"),
        new("Divider_Vertical_Coincident", "Coincident", "Divider_Vertical Mid Plane", "Housing Mid Plane", "-", "جداکننده عمودی وسط"),

        // ===== محور X - حرکت افقی (0-480mm) =====
        new("X_Rail_Top_Coincident", "Coincident", "Linear_Rail_X Top", "Frame Front Top Beam", "-", "ریل X بالا روی فریم جلو"),
        new("X_Rail_Bottom_Coincident", "Coincident", "Linear_Rail_X Bottom", "Frame Front Bottom Beam", "-", "ریل X پایین روی فریم جلو"),
        new("X_Block_Top_Coincident", "Coincident", "Guide_Block_X Top x2 Groove", "Linear_Rail_X Top Groove", "-", "2 واگن روی ریل بالا"),
        new("X_Block_Bottom_Coincident", "Coincident", "Guide_Block_X Bottom x2 Groove", "Linear_Rail_X Bottom Groove", "-", "2 واگن روی ریل پایین"),
        new("X_Carriage_To_Blocks", "Coincident", "X_Carriage Bottom", "Guide_Block_X Top x4", "-", "کالسکه روی 4 واگن"),
        new("X_LimitDistance_0_480", "LimitDistance", "X_Carriage Left Face", "Frame Left Inner", "Min 0mm, Max 480mm", "⭐ محور X - انتخاب ستون"),
        new("X_Shaft_To_Bearings", "Concentric", "Shaft_Drive_X Ø8", "Bearing_Block_X Bore Ø8", "-", "شفت در بلبرینگ‌ها"),
        new("X_Pulley_Drive_Concentric", "Concentric", "Pulley_GT2_20T Drive Bore Ø8", "Shaft_Drive_X / Motor Shaft", "-", "پولی محرک روی شفت/موتور"),
        new("X_Pulley_Idler_Concentric", "Concentric", "Pulley_Idler Bore Ø5", "Tensioner Shaft Ø5", "-", "پولی هرزگرد"),
        new("X_Belt_To_Pulleys", "Coincident", "Belt_GT2_X Inner", "Pulley Groove", "-", "تسمه دور پولی‌ها - مسیر بسته"),
        new("X_Belt_Clamp", "Coincident", "X_Carriage Belt Clamp", "Belt_GT2_X Outer", "-", "کالسکه به تسمه قفل - حرکت با تسمه"),
        new("X_BeltChain", "Belt/Chain", "Pulley Drive", "Pulley Idler", "1:1 via Belt_GT2_X", "Fallback: Distance mate اگر پشتیبانی نشود"),

        // ===== محور Z - حرکت عمودی (0-2120mm) =====
        new("Z_Rail_Left_To_XCarriage", "Coincident", "Linear_Rail_Z Left Back", "X_Carriage Front Left", "-", "ریل Z چپ روی X_Carriage"),
        new("Z_Rail_Right_To_XCarriage", "Coincident", "Linear_Rail_Z Right Back", "X_Carriage Front Right", "-", "ریل Z راست روی X_Carriage"),
        new("Z_Blocks_On_Rails", "Coincident", "Guide_Block_Z x4 Groove", "Linear_Rail_Z Groove", "-", "4 واگن روی 2 ریل Z"),
        new("Z_Carriage_To_Blocks", "Coincident", "Z_Carriage Back", "Guide_Block_Z Front x4", "-", "کالسکه Z روی 4 واگن"),
        new("Z_LimitDistance_0_2120", "LimitDistance", "Z_Carriage Bottom", "Bottom_Plate Top", "Min 0mm, Max 2120mm", "⭐ محور Z - انتخاب ردیف (5 ردیف)"),
        new("Z_Lead_Screw_Left_Bearings", "Concentric", "Lead_Screw_T8x8 Left Ø8", "Bearing_Block_Z Left Top+Bottom Bores", "-", "لید اسکرو چپ در بلبرینگ‌ها"),
        new("Z_Lead_Screw_Right_Bearings", "Concentric", "Lead_Screw_T8x8 Right Ø8", "Bearing_Block_Z Right Top+Bottom Bores", "-", "لید اسکرو راست"),
        new("Z_Nut_Left_To_Carriage", "Coincident", "Lead_Screw_Nut Left Flange", "Z_Carriage Nut Hole Left", "-", "مهره چپ به Z_Carriage"),
        new("Z_Nut_Right_To_Carriage", "Coincident", "Lead_Screw_Nut Right Flange", "Z_Carriage Nut Hole Right", "-", "مهره راست به Z_Carriage"),
        new("Z_Sync_Belt", "Belt/Chain", "Lead_Screw Left Pulley", "Lead_Screw Right Pulley", "1:1 via Belt_GT2_Z_Sync", "همگام‌سازی 2 لید اسکرو - جلوگیری از Racking"),
        new("Z_Motor_Shaft_To_Lead", "Concentric", "Motor_NEMA23_Z Shaft", "Lead_Screw_T8x8 Left Bottom", "-", "موتور Z به لید اسکرو چپ"),

        // ===== محور Y - سینی کشویی (0-450mm) =====
        new("Y_Rail_To_ZCarriage", "Coincident", "Linear_Rail_Y Bottom", "Z_Carriage Top Center", "-", "ریل Y روی Z_Carriage"),
        new("Y_Blocks_On_Rail", "Coincident", "Guide_Block_Y x2 Groove", "Linear_Rail_Y Groove", "-", "2 واگن Y روی ریل Y"),
        new("Y_Tray_To_Blocks", "Coincident", "Transfer_Tray Bottom", "Guide_Block_Y Top x2", "-", "سینی روی 2 واگن Y"),
        new("Y_LimitDistance_0_450", "LimitDistance", "Transfer_Tray Rear", "Z_Carriage Rear", "Min 0mm, Max 450mm", "⭐ محور Y - ورود به عمق خانه"),
        new("Y_Rack_To_Tray", "Coincident", "Rack_Y Top", "Transfer_Tray Bottom Center", "-", "دندانه شانه زیر سینی"),
        new("Y_Pinion_To_Motor", "Concentric", "Pinion_Y Bore Ø5", "Motor_NEMA17_Y Shaft Ø5", "-", "پینیون روی شفت موتور Y"),
        new("Y_Pinion_Engaged_Rack", "Distance", "Pinion_Y Pitch Circle", "Rack_Y Teeth Top", "0mm (Tangent)", "درگیری پینیون و شانه - Module 1"),

        // ===== نوار نقاله =====
        new("Conveyor_Frame_To_Plate", "Coincident", "Conveyor_Frame Bottom", "Bottom_Plate Top Front", "-", "قاب نوار روی کف"),
        new("Roller_Drive_Concentric", "Concentric", "Roller_Drive Shaft Ø12", "Conveyor_Frame Drive Hole Ø12", "-", "غلتک محرک در قاب"),
        new("Roller_Idler_Concentric", "Concentric", "Roller_Idler Shaft Ø12", "Conveyor_Frame Idler Slot", "-", "غلتک هرزگرد با اسلات تنظیم"),

        // ===== UI =====
        new("Front_Panel_To_Frame", "Coincident", "Front_Panel_Frame Back", "Frame Front Upper", "-", "پنل جلویی روی فریم"),
        new("Display_Mount_To_Panel", "Coincident", "Display_Mount Back", "Front_Panel Inner at Display Cutout", "-", "قاب نمایشگر"),
        new("Display_To_Mount", "Coincident", "Display Bottom", "Display_Mount Inside", "-", "نمایشگر در قاب"),
        new("Button_To_Panel", "Concentric", "Button Body Ø16", "Front_Panel Button Hole Ø16.5", "-", "2 دکمه در سوراخ‌های پنل"),
        new("Keypad_Mount_To_Panel", "Coincident", "Keypad_Mount Back", "Front_Panel Inner at Keypad Cutout", "-", "قاب کیپد"),
        new("Keypad_To_Mount", "Coincident", "Keypad Bottom", "Keypad_Mount Inside", "-", "کیپد در قاب"),

        // ===== الکترونیک =====
        new("Plate_To_Standoffs", "Coincident", "Electronics_Plate Bottom", "Standoff Top x4", "-", "صفحه الکترونیک روی 4 پایه 20mm"),
        new("Arduino_To_Plate", "Coincident", "Arduino Bottom", "Electronics_Plate Top", "-", "آردوینو روی صفحه"),

        // ===== کابل =====
        new("Cable_Tray_To_Frame", "Coincident", "Cable_Tray Back", "Frame Side Inner", "25mm from Z Rail", "سینی کابل عمودی"),
        new("Cable_Chain_Top_Fixed", "Coincident", "Cable_Chain Top Mount", "Frame / X_Carriage Rear Top", "-", "سر ثابت زنجیر کابل"),
        new("Cable_Chain_Bottom_Moving", "Coincident", "Cable_Chain Bottom Mount", "Z_Carriage Rear Top", "30mm from Z Belt", "سر متحرک زنجیر با Z_Carriage"),
    };

    /// <summary>اعتبارسنجی عدم تداخل Mateها</summary>
    public static List<string> Validate()
    {
        var issues = new List<string>();

        // چک Over-defined: هر محور فقط یک LimitDistance
        var limitMates = AllMates.Where(m => m.Type == "LimitDistance").ToList();
        if (limitMates.Count(m => m.Name.StartsWith("X_")) > 1)
            issues.Add("Multiple LimitDistance on X axis - over-defined risk");
        if (limitMates.Count(m => m.Name.StartsWith("Z_")) > 1)
            issues.Add("Multiple LimitDistance on Z axis - over-defined risk");
        if (limitMates.Count(m => m.Name.StartsWith("Y_")) > 1)
            issues.Add("Multiple LimitDistance on Y axis - over-defined risk");

        // چک Fix: فقط یکی
        var fixMates = AllMates.Where(m => m.Type == "Fix").ToList();
        if (fixMates.Count != 1)
            issues.Add($"Should have exactly 1 Fix mate, found {fixMates.Count}");

        // چک Belt/Chain fallback مستند شده
        var beltMates = AllMates.Where(m => m.Type == "Belt/Chain").ToList();
        foreach (var bm in beltMates)
        {
            if (!bm.Notes.Contains("Fallback"))
                issues.Add($"Belt/Chain mate {bm.Name} should mention Fallback");
        }

        return issues;
    }

    public static void PrintReport()
    {
        Console.WriteLine($"\n=== Mate Definitions: {AllMates.Count} mates ===");
        foreach (var m in AllMates)
        {
            Console.WriteLine($"  {m.Name} [{m.Type}] : {m.Entity1} <-> {m.Entity2} | {m.Limits} | {m.Notes}");
        }
        var issues = Validate();
        if (issues.Count == 0) Console.WriteLine("✅ All mates valid - no over-defined, no conflict");
        else foreach (var i in issues) Console.WriteLine($"⚠️ {i}");
    }
}
