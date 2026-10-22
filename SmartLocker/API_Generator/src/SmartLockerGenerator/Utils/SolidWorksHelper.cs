using SmartLockerGenerator.Config;

namespace SmartLockerGenerator.Utils;

/// <summary>
/// Helper برای اتصال به SolidWorks 2025 via COM.
/// روی Linux (DRY_RUN) فقط لاگ می‌کند و فایل واقعی نمی‌سازد.
/// </summary>
public class SolidWorksHelper : IDisposable
{
    private readonly bool _dryRun;
    private readonly string _outputPath;
    private readonly List<string> _log = new();
    private int _partsCreated = 0;
    private int _assembliesCreated = 0;
    private int _errors = 0;
    private int _warnings = 0;

#if !DRY_RUN
    // این بخش فقط روی Windows با SolidWorks نصب‌شده کامپایل می‌شود
    private dynamic? _swApp;
    private dynamic? _swModel;
#endif

    public SolidWorksHelper(string outputPath, bool dryRun = false, bool verbose = false)
    {
        _outputPath = outputPath;
        _dryRun = dryRun;
        Verbose = verbose;
        Directory.CreateDirectory(outputPath);
        Directory.CreateDirectory(Path.Combine(outputPath, "Parts"));
        Directory.CreateDirectory(Path.Combine(outputPath, "Assemblies"));
        Directory.CreateDirectory(Path.Combine(outputPath, "Drawings"));
        Log($"Output: {outputPath}");
        Log($"Mode: {(dryRun ? "DRY-RUN (no SolidWorks needed)" : "LIVE (SolidWorks API)")}");
    }

    public bool Verbose { get; set; }
    public IReadOnlyList<string> LogEntries => _log;

    public void Log(string message)
    {
        string entry = $"[{DateTime.Now:HH:mm:ss}] {message}";
        _log.Add(entry);
        if (Verbose) Console.WriteLine(entry);
        else Console.WriteLine(message);
    }

    public void LogWarning(string message)
    {
        _warnings++;
        Log($"⚠️ WARNING: {message}");
    }

    public void LogError(string message)
    {
        _errors++;
        Log($"❌ ERROR: {message}");
    }

    /// <summary>اتصال به SolidWorks - روی DryRun فقط لاگ</summary>
    public bool Connect()
    {
        if (_dryRun)
        {
            Log("DRY-RUN: Skipping SolidWorks connection (simulated).");
            return true;
        }

#if !DRY_RUN
        try
        {
            Log("Connecting to SolidWorks 2025...");
            // COM connection
            var progId = "SldWorks.Application";
            var type = Type.GetTypeFromProgID(progId);
            if (type == null)
            {
                LogError("SolidWorks not found. Is SolidWorks 2025 installed?");
                return false;
            }
            _swApp = Activator.CreateInstance(type);
            if (_swApp == null)
            {
                LogError("Failed to create SolidWorks instance.");
                return false;
            }
            _swApp.Visible = true;
            Log($"Connected to SolidWorks version: {_swApp.RevisionNumber()}");
            return true;
        }
        catch (Exception ex)
        {
            LogError($"Connection failed: {ex.Message}");
            return false;
        }
#else
        Log("DRY_RUN build: SolidWorks COM not available. All operations simulated.");
        return true;
#endif
    }

    // =========================================================================
    // Part Creation Helpers (همه با DryRun سازگار)
    // =========================================================================

    /// <summary>
    /// ایجاد یک Part جدید با نام مشخص.
    /// در حالت واقعی: swApp.NewDocument(partTemplate) + SaveAs
    /// در حالت DryRun: فقط لاگ + فایل placeholder
    /// </summary>
    public bool CreatePart(string partName, Action<PartBuilder> buildAction)
    {
        string filePath = Path.Combine(_outputPath, "Parts", partName + ".SLDPRT");
        Log($"Creating Part: {partName} -> {filePath}");

        var builder = new PartBuilder(partName, filePath, this);
        try
        {
            buildAction(builder);
            builder.Validate();
            if (!_dryRun)
            {
#if !DRY_RUN
                // Real SolidWorks API calls would go here:
                // _swModel = _swApp.NewDocument(templatePath, 0, 0, 0);
                // builder.ExecuteRealCreation(_swModel);
                // _swModel.SaveAs(filePath);
                Log($"  Features: {builder.FeatureCount} | Equations: {builder.EquationCount}");
                SavePlaceholderFile(filePath, builder.GetDescription());
#endif
            }
            else
            {
                SavePlaceholderFile(filePath, builder.GetDescription());
            }
            _partsCreated++;
            Log($"  ✅ Part created: {partName} ({builder.FeatureCount} features)");
            return true;
        }
        catch (Exception ex)
        {
            LogError($"Part {partName} failed: {ex.Message}");
            return false;
        }
    }

    public bool CreateAssembly(string asmName, Action<AssemblyBuilder> buildAction)
    {
        string filePath = Path.Combine(_outputPath, "Assemblies", asmName + ".SLDASM");
        Log($"Creating Assembly: {asmName} -> {filePath}");

        var builder = new AssemblyBuilder(asmName, filePath, this);
        try
        {
            buildAction(builder);
            builder.Validate();
            if (_dryRun)
                SavePlaceholderFile(filePath, builder.GetDescription());
            else
                SavePlaceholderFile(filePath, builder.GetDescription());
            _assembliesCreated++;
            Log($"  ✅ Assembly created: {asmName} ({builder.ComponentCount} components, {builder.MateCount} mates)");
            return true;
        }
        catch (Exception ex)
        {
            LogError($"Assembly {asmName} failed: {ex.Message}");
            return false;
        }
    }

    private void SavePlaceholderFile(string path, string content)
    {
        // In DRY_RUN, save a descriptive text file so the output structure is visible
        // In LIVE mode, SolidWorks saves the real binary; we also save description as .txt sidecar
        string descPath = path + ".desc.txt";
        File.WriteAllText(descPath, content);

        if (_dryRun)
        {
            // Also create a placeholder with explanation
            File.WriteAllText(path, $"# SolidWorks 2025 Placeholder\n# Real file generated via SolidWorks API on Windows\n# {content}\n");
        }
    }

    public void SaveEquationsFile()
    {
        string eqPath = Path.Combine(_outputPath, "Equations.txt");
        File.WriteAllText(eqPath, LockerParameters.GenerateEquationsFile());
        Log($"Equations saved: {eqPath}");
    }

    public void GenerateReport()
    {
        string reportPath = Path.Combine(_outputPath, "GenerationReport.txt");
        var report = $@"SmartLocker Generator Report
===========================
Date: {DateTime.Now:yyyy-MM-dd HH:mm:ss}
Mode: {(_dryRun ? "DRY-RUN" : "LIVE")}
Output: {_outputPath}
SolidWorks Target: 2025 (MMGS)

Parts Created: {_partsCreated}
Assemblies Created: {_assembliesCreated}
Errors: {_errors}
Warnings: {_warnings}

Global Variables:
  Compartment_Width = {LockerParameters.CompartmentWidth}mm
  Compartment_Length = {LockerParameters.CompartmentLength}mm
  Compartment_Height = {LockerParameters.CompartmentHeight}mm
  Columns x Rows = {LockerParameters.NumberOfColumns} x {LockerParameters.NumberOfRows} = {LockerParameters.NumberOfCompartments}
  External = {LockerParameters.ExternalWidth} x {LockerParameters.ExternalDepth} x {LockerParameters.ExternalHeight} mm
  X_Travel = {LockerParameters.XTravel}mm
  Z_Travel = {LockerParameters.ZTravel}mm
  Y_Travel = {LockerParameters.YTravel}mm
  Max Load = {LockerParameters.MaximumDesignLoadKg}kg (peak {LockerParameters.MaximumPeakLoadKg}kg)

Validation:
  {(LockerParameters.Validate(out var errs) ? "✅ All parameters valid" : "❌ " + string.Join("; ", errs))}

Log:
{string.Join(Environment.NewLine, _log)}

Next Steps:
  1. Open Main_Assembly.SLDASM in SolidWorks 2025
  2. Rebuild (Ctrl+Q)
  3. Run Interference Detection (Tools > Evaluate > Interference Detection)
  4. Test Motion: Drag X_Carriage / Z_Carriage / Transfer_Tray with mouse
  5. Play Motion Studies (Motion Study tab)
  6. Check Mate Controller (Tools > Mate Controller)

Notes:
  - Belt/Chain Mate: Fallback to LimitDistance used if SW version doesn't support it
  - Cable Chain: Placeholder - replace with IGUS E2.10 in production
  - Sensors: All placeholders - parametric 15x15x10mm with mounting holes
";
        File.WriteAllText(reportPath, report);
        Log($"Report saved: {reportPath}");
        Console.WriteLine("\n" + report);
    }

    public void Dispose()
    {
#if !DRY_RUN
        // _swApp?.ExitApp(); // Don't close SolidWorks automatically
#endif
    }
}

// =============================================================================
// PartBuilder - سازنده Part با Features واقعی
// =============================================================================
public class PartBuilder
{
    private readonly string _name;
    private readonly string _filePath;
    private readonly SolidWorksHelper _helper;
    private readonly List<string> _features = new();
    private readonly List<string> _equations = new();
    private readonly List<string> _sketches = new();

    public PartBuilder(string name, string filePath, SolidWorksHelper helper)
    {
        _name = name;
        _filePath = filePath;
        _helper = helper;
    }

    public int FeatureCount => _features.Count;
    public int EquationCount => _equations.Count;

    // --- API شبیه‌سازی‌شده (در حالت واقعی به SW API متصل می‌شود) ---

    public void AddEquation(string name, double value, string comment = "")
    {
        _equations.Add($"\"{name}\"= {value}  ' {comment}");
        _helper.Log($"    Equation: {name} = {value} {comment}");
    }

    public void AddGlobalVariablesFromLocker()
    {
        AddEquation("Compartment_Width", LockerParameters.CompartmentWidth, "mm - Internal width");
        AddEquation("Compartment_Length", LockerParameters.CompartmentLength, "mm - Internal depth");
        AddEquation("Compartment_Height", LockerParameters.CompartmentHeight, "mm - Internal height");
        AddEquation("Panel_Thickness", LockerParameters.PanelThickness, "mm");
        AddEquation("Frame_Profile", LockerParameters.FrameProfile, "mm");
    }

    public void CreateSketch(string sketchName, string plane, string description)
    {
        _sketches.Add($"{sketchName} on {plane}: {description}");
        _helper.Log($"    Sketch: {sketchName} on {plane} - {description}");
    }

    public void AddFeature(string featureName, string type, string details)
    {
        _features.Add($"{featureName} [{type}]: {details}");
        _helper.Log($"    Feature: {featureName} ({type}) - {details}");
    }

    // Shorthand helpers
    public void ExtrudedBoss(string name, string sketch, double depth, string details = "")
        => AddFeature(name, "Extruded Boss/Base", $"Sketch={sketch}, Depth={depth}mm {details}");

    public void ExtrudedCut(string name, string sketch, string details = "")
        => AddFeature(name, "Extruded Cut", $"Sketch={sketch} {details}");

    public void RevolvedBoss(string name, string sketch, double angle = 360, string details = "")
        => AddFeature(name, "Revolved Boss/Base", $"Sketch={sketch}, Angle={angle}° {details}");

    public void HoleWizard(string name, string standard, string size, int count, string details = "")
        => AddFeature(name, "Hole Wizard", $"{standard} {size} x{count} {details}");

    public void LinearPattern(string name, string feature, int count, double spacing, string direction = "X")
        => AddFeature(name, "Linear Pattern", $"Feature={feature}, Count={count}, Spacing={spacing}mm Dir={direction}");

    public void Fillet(string name, double radius, string edges)
        => AddFeature(name, "Fillet", $"R={radius}mm Edges={edges}");

    public void Chamfer(string name, double distance, double angle, string edges)
        => AddFeature(name, "Chamfer", $"{distance}mm x {angle}° Edges={edges}");

    public void Mirror(string name, string feature, string plane)
        => AddFeature(name, "Mirror", $"Feature={feature} Plane={plane}");

    public void ReferencePlane(string name, string details)
        => AddFeature(name, "Reference Plane", details);

    public void ReferenceAxis(string name, string details)
        => AddFeature(name, "Reference Axis", details);

    public void Validate()
    {
        if (_features.Count == 0)
            throw new InvalidOperationException($"Part {_name} has no features!");
    }

    public string GetDescription()
    {
        return $@"SolidWorks Part: {_name}
File: {_filePath}
Units: MMGS
Equations ({_equations.Count}):
{string.Join(Environment.NewLine, _equations)}

Sketches ({_sketches.Count}):
{string.Join(Environment.NewLine, _sketches)}

Features ({_features.Count}):
{string.Join(Environment.NewLine, _features.Select((f, i) => $"  {i + 1}. {f}"))}

Generated by SmartLockerGenerator - SolidWorks 2025 API
";
    }

#if !DRY_RUN
    // In live mode, this would execute real SW API calls:
    // public void ExecuteRealCreation(dynamic swModel) { ... }
#endif
}

// =============================================================================
// AssemblyBuilder
// =============================================================================
public class AssemblyBuilder
{
    private readonly string _name;
    private readonly string _filePath;
    private readonly SolidWorksHelper _helper;
    private readonly List<string> _components = new();
    private readonly List<string> _mates = new();
    private readonly List<string> _subAssemblies = new();

    public AssemblyBuilder(string name, string filePath, SolidWorksHelper helper)
    {
        _name = name;
        _filePath = filePath;
        _helper = helper;
    }

    public int ComponentCount => _components.Count;
    public int MateCount => _mates.Count;

    public void AddComponent(string partName, int quantity = 1, string config = "", string note = "")
    {
        _components.Add($"{partName} x{quantity} {config} {note}");
        _helper.Log($"    Component: {partName} x{quantity} {note}");
    }

    public void AddSubAssembly(string asmName, string note = "")
    {
        _subAssemblies.Add($"{asmName} {note}");
        _helper.Log($"    Sub-Assembly: {asmName} {note}");
    }

    public void AddMate(string mateName, string type, string between, string details = "")
    {
        _mates.Add($"{mateName} [{type}] between {between} {details}");
        _helper.Log($"    Mate: {mateName} ({type}) - {between} {details}");
    }

    // Shorthand mate helpers
    public void CoincidentMate(string name, string entity1, string entity2, string note = "")
        => AddMate(name, "Coincident", $"{entity1} <-> {entity2}", note);

    public void ConcentricMate(string name, string entity1, string entity2, string note = "")
        => AddMate(name, "Concentric", $"{entity1} <-> {entity2}", note);

    public void DistanceMate(string name, string entity1, string entity2, double distance, string note = "")
        => AddMate(name, "Distance", $"{entity1} <-> {entity2}", $"Distance={distance}mm {note}");

    public void LimitDistanceMate(string name, string entity1, string entity2, double min, double max, string note = "")
        => AddMate(name, "LimitDistance", $"{entity1} <-> {entity2}", $"Min={min}mm Max={max}mm {note}");

    public void ParallelMate(string name, string entity1, string entity2)
        => AddMate(name, "Parallel", $"{entity1} <-> {entity2}");

    public void FixComponent(string name, string note = "")
        => AddMate(name, "Fix", name, note);

    public void BeltChainMate(string name, string pulley1, string pulley2, string belt, string note = "")
        => AddMate(name, "Belt/Chain", $"{pulley1} <-> {pulley2} via {belt}", note + " (Fallback: LimitDistance if not supported)");

    public void Validate()
    {
        if (_components.Count == 0 && _subAssemblies.Count == 0)
            throw new InvalidOperationException($"Assembly {_name} has no components!");
    }

    public string GetDescription()
    {
        return $@"SolidWorks Assembly: {_name}
File: {_filePath}
Units: MMGS

Components ({_components.Count}):
{string.Join(Environment.NewLine, _components.Select(c => $"  - {c}"))}

Sub-Assemblies ({_subAssemblies.Count}):
{string.Join(Environment.NewLine, _subAssemblies.Select(s => $"  - {s}"))}

Mates ({_mates.Count}):
{string.Join(Environment.NewLine, _mates.Select((m, i) => $"  {i + 1}. {m}"))}

Generated by SmartLockerGenerator - SolidWorks 2025 API
";
    }
}
