using SmartLockerGenerator.Config;
using SmartLockerGenerator.Parts;
using SmartLockerGenerator.Assemblies;
using SmartLockerGenerator.Motion;
using SmartLockerGenerator.Mates;
using SmartLockerGenerator.Utils;

Console.OutputEncoding = System.Text.Encoding.UTF8;

// ============================================================================
// Smart Locker SolidWorks 2025 Generator
// Main entry point - CLI: --output <path> [--dry-run] [--verbose] [--help]
// ============================================================================

string outputPath = Path.Combine(Directory.GetCurrentDirectory(), "CAD_Output");
bool dryRun = false;
bool verbose = false;
bool onlyParts = false;
bool onlyAssemblies = false;
bool showHelp = false;

// Parse args
for (int i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--output": if (i + 1 < args.Length) outputPath = args[++i]; break;
        case "--dry-run": dryRun = true; break;
        case "--verbose": verbose = true; break;
        case "--only-parts": onlyParts = true; break;
        case "--only-assemblies": onlyAssemblies = true; break;
        case "--help": case "-h": case "-?": showHelp = true; break;
    }
}

if (showHelp)
{
    Console.WriteLine(@"
SmartLocker SolidWorks 2025 Generator v1.0.0
===========================================
Generates all Parts, Assemblies, Mates, and Motion Studies for the 10-Compartment Smart Locker.

Usage:
  SmartLockerGenerator [options]

Options:
  --output <path>       Output directory (default: ./CAD_Output)
  --dry-run             Simulate without SolidWorks (for Linux/CI, validates logic)
  --verbose             Detailed log of every feature/mate
  --only-parts          Generate only parts
  --only-assemblies     Generate only assemblies
  --help, -h            This help

Examples:
  SmartLockerGenerator --output ""D:\SmartLocker_CAD"" --verbose
  SmartLockerGenerator --dry-run --output ""./TestOutput""
  SmartLockerGenerator --only-parts --dry-run

Requirements:
  - Windows 10/11 + SolidWorks 2025 (for live mode)
  - .NET 8 SDK
  - Without SolidWorks: use --dry-run (validates logic, creates placeholder structure)

Output:
  CAD_Output/
    Equations.txt
    Parts/*.SLDPRT (+ .desc.txt sidecars)
    Assemblies/*.SLDASM (+ .desc.txt sidecars)
    Drawings/ (templates)
    GenerationReport.txt
");
    return 0;
}

// On Linux, default to dry-run (no SolidWorks)
if (OperatingSystem.IsLinux() || OperatingSystem.IsMacOS())
{
    if (!dryRun)
    {
        Console.WriteLine("⚠️ Linux/macOS detected - SolidWorks not available. Enabling --dry-run automatically.");
        Console.WriteLine("   To generate real .SLDPRT files, run on Windows + SolidWorks 2025.");
    }
    dryRun = true;
}

Console.WriteLine(@"
╔════════════════════════════════════════════════════════╗
║  Smart Locker 10-Compartment - SolidWorks 2025     ║
║  Generator v1.0.0                                  ║
║  MMGS | Parametric | Real FeatureManager            ║
╚════════════════════════════════════════════════════════╝
");
Console.WriteLine($"Output:    {outputPath}");
Console.WriteLine($"Mode:      {(dryRun ? "DRY-RUN (simulated)" : "LIVE (SolidWorks API)")}");
Console.WriteLine($"Verbose:   {verbose}");
Console.WriteLine();

// Validate parameters before any generation
Console.WriteLine("Validating parameters...");
if (!LockerParameters.Validate(out var validationErrors))
{
    Console.ForegroundColor = ConsoleColor.Red;
    Console.WriteLine("❌ Parameter validation failed:");
    foreach (var e in validationErrors) Console.WriteLine($"  - {e}");
    Console.ResetColor();
    Console.WriteLine("Aborting. Fix parameters in LockerParameters.cs");
    return 1;
}
Console.WriteLine($"✅ Parameters valid: {LockerParameters.NumberOfCompartments} compartments, "
    + $"External {LockerParameters.ExternalWidth}x{LockerParameters.ExternalDepth}x{LockerParameters.ExternalHeight}mm, "
    + $"Travel X={LockerParameters.XTravel} Z={LockerParameters.ZTravel} Y={LockerParameters.YTravel}");
Console.WriteLine();

// Create helper (connects to SolidWorks or simulates)
using var sw = new SolidWorksHelper(outputPath, dryRun, verbose);

if (!sw.Connect())
{
    Console.ForegroundColor = ConsoleColor.Red;
    Console.WriteLine("Failed to connect to SolidWorks. Use --dry-run for simulation.");
    Console.ResetColor();
    return 1;
}

var swTimer = System.Diagnostics.Stopwatch.StartNew();

// Save Equations
sw.SaveEquationsFile();

// =============================================================================
// Generate Parts
// =============================================================================
if (!onlyAssemblies)
{
    Console.WriteLine("\n═══════════════════════════════════════");
    Console.WriteLine("  PHASE 1: Creating Parts");
    Console.WriteLine("═══════════════════════════════════════\n");

    FrameParts.CreateAll(sw);
    Console.WriteLine();
    HousingParts.CreateAll(sw);
    Console.WriteLine();
    MechanismParts.CreateAll(sw);
    Console.WriteLine();
    TransferParts.CreateAll(sw);
    Console.WriteLine();
    UiParts.CreateAll(sw);
    Console.WriteLine();
    ElectronicsParts.CreateAll(sw);
    Console.WriteLine();
}

// =============================================================================
// Generate Assemblies
// =============================================================================
if (!onlyParts)
{
    Console.WriteLine("\n═══════════════════════════════════════");
    Console.WriteLine("  PHASE 2: Creating Assemblies");
    Console.WriteLine("═══════════════════════════════════════\n");

    AllAssemblies.CreateAll(sw);
    Console.WriteLine();
}

// =============================================================================
// Motion Studies
// =============================================================================
if (!onlyParts)
{
    Console.WriteLine("\n═══════════════════════════════════════");
    Console.WriteLine("  PHASE 3: Motion Studies");
    Console.WriteLine("═══════════════════════════════════════\n");

    var motionBuilder = new MotionStudyBuilder(sw);
    motionBuilder.BuildAll();
    Console.WriteLine();
}

// =============================================================================
// Validation
// =============================================================================
Console.WriteLine("\n═══════════════════════════════════════");
Console.WriteLine("  PHASE 4: Validation");
Console.WriteLine("═══════════════════════════════════════\n");

MateDefinitions.PrintReport();
Console.WriteLine();

// =============================================================================
// Drawings (templates)
// =============================================================================
Console.WriteLine("Creating Drawing templates...");
CreateDrawingTemplates(sw, outputPath);

// =============================================================================
// Final Report
// =============================================================================
swTimer.Stop();
sw.GenerateReport();

Console.ForegroundColor = ConsoleColor.Green;
Console.WriteLine($"\n✅ Generation completed in {swTimer.Elapsed.TotalSeconds:F1}s");
Console.WriteLine($"   Output: {outputPath}");
if (dryRun)
{
    Console.WriteLine("   Mode: DRY-RUN - Logic validated, placeholder structure created.");
    Console.WriteLine("   To generate real SolidWorks files, run on Windows + SolidWorks 2025:");
    Console.WriteLine($"     SmartLockerGenerator.exe --output \"D:\\SmartLocker_CAD\" --verbose");
}
else
{
    Console.WriteLine("   Mode: LIVE - Real SolidWorks files created.");
    Console.WriteLine($"   Open: {Path.Combine(outputPath, "Assemblies", "Main_Assembly.SLDASM")}");
    Console.WriteLine("   Then: Ctrl+Q (Rebuild) -> Interference Detection -> Motion Study Play");
}
Console.ResetColor();

return 0;

// ---------------------------------------------------------------------------
static void CreateDrawingTemplates(SolidWorksHelper sw, string outputPath)
{
    string dwgDir = Path.Combine(outputPath, "Drawings");
    Directory.CreateDirectory(dwgDir);

    var drawings = new[]
    {
        ("Main_Assembly.SLDDRW", "Main Assembly - Front/Top/Side/Isometric + BOM + Dimensions"),
        ("Frame_Assembly.SLDDRW", "Frame Assembly - Profile details + Mounting holes"),
        ("Compartment.SLDDRW", "Compartment Detail - 400x500x400 internal, tolerances"),
        ("X_Axis_Assembly.SLDDRW", "X-Axis - Rails + Carriage + Belt, X travel 480mm"),
        ("Z_Axis_Assembly.SLDDRW", "Z-Axis - Lead screws + Rails, Z travel 2120mm"),
        ("Transfer_Tray.SLDDRW", "Transfer Tray - 380x400x30 with Rack, Y travel 450mm"),
        ("Conveyor_Assembly.SLDDRW", "Conveyor - Rollers + Belt, 350x600"),
        ("Front_Panel_UI.SLDDRW", "Front Panel - Display/Button/Keypad cutouts (parametric)"),
        ("Electronics_Assembly.SLDDRW", "Electronics - Mounting plate + Placeholders + Cable tray"),
    };

    foreach (var (name, desc) in drawings)
    {
        string path = Path.Combine(dwgDir, name);
        string content = $@"SolidWorks Drawing: {name}
Reference: {(name.StartsWith("Main") ? "Main_Assembly.SLDASM" : name.Replace(".SLDDRW", ".SLDPRT/.SLDASM"))}
Description: {desc}
Scale: 1:10 (or as applicable)
Standard: ISO (MMGS), Third Angle
Sheets: 1 (Main_Assembly has 2 sheets)
Views: Front, Top, Side, Isometric (for Main_Assembly)
Dimensions: Critical dimensions + Tolerances (see docs/11_Naghsheh.md)
BOM: Balloon table (Main_Assembly only)

This is a template - real SLDDRW requires SolidWorks Drawing API:
  var draw = swApp.NewDrawing(templateDot);
  draw.CreateView(...);
  draw.AddDimensions(...);
  draw.SaveAs(path);

Generated by SmartLockerGenerator - see API_Generator/src/SmartLockerGenerator/Program.cs
";
        File.WriteAllText(path + ".desc.txt", content);
        // Placeholder file for structure visibility
        if (OperatingSystem.IsLinux() || OperatingSystem.IsMacOS())
        {
            File.WriteAllText(path, $"# SolidWorks 2025 Drawing Placeholder - {desc}\n# Real SLDDRW generated via DrawingsBuilder on Windows\n");
        }
        sw.Log($"  Drawing template: {name}");
    }
}
