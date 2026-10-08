using System;
using System.ComponentModel;

namespace AISystemOptimizer.Core.Models
{
    /// <summary>
    /// Process categories for classification
    /// </summary>
    public enum ProcessCategory
    {
        [Description("Unknown")]
        Unknown = 0,
        
        [Description("Critical System")]
        Critical,
        
        [Description("Windows System")]
        System,
        
        [Description("Hardware Driver")]
        Driver,
        
        [Description("Security")]
        Security,
        
        [Description("User Application")]
        UserApplication,
        
        [Description("Background Application")]
        BackgroundApplication,
        
        [Description("Game")]
        Game,
        
        [Description("Launcher")]
        Launcher,
        
        [Description("Updater")]
        Updater,
        
        [Description("Cloud Sync")]
        CloudSync,
        
        [Description("Telemetry")]
        Telemetry,
        
        [Description("Malware Suspected")]
        Suspicious
    }

    /// <summary>
    /// Risk levels for optimization actions
    /// </summary>
    public enum RiskLevel
    {
        [Description("Safe")]
        Low = 0,
        
        [Description("Caution Advised")]
        Medium,
        
        [Description("High Risk")]
        High,
        
        [Description("Critical - Do Not Touch")]
        Critical
    }

    /// <summary>
    /// Optimization action types
    /// </summary>
    public enum OptimizationActionType
    {
        [Description("Close Process")]
        CloseProcess,
        
        [Description("Disable Startup")]
        DisableStartup,
        
        [Description("Stop Service")]
        StopService,
        
        [Description("Disable Service")]
        DisableService,
        
        [Description("Clear Cache")]
        ClearCache,
        
        [Description("Change Priority")]
        ChangePriority,
        
        [Description("Change Affinity")]
        ChangeAffinity,
        
        [Description("Uninstall Application")]
        UninstallApplication,
        
        [Description("Adjust Power Settings")]
        AdjustPowerSettings
    }

    /// <summary>
    /// System resource types
    /// </summary>
    public enum ResourceType
    {
        [Description("RAM")]
        RAM,
        
        [Description("CPU")]
        CPU,
        
        [Description("GPU")]
        GPU,
        
        [Description("Disk")]
        Disk,
        
        [Description("Network")]
        Network
    }

    /// <summary>
    /// Power modes for Windows
    /// </summary>
    public enum PowerMode
    {
        [Description("Balanced")]
        Balanced,
        
        [Description("High Performance")]
        HighPerformance,
        
        [Description("Power Saver")]
        PowerSaver,
        
        [Description("Ultimate Performance")]
        UltimatePerformance
    }

    /// <summary>
    /// Process state
    /// </summary>
    public enum ProcessState
    {
        [Description("Running")]
        Running,
        
        [Description("Suspended")]
        Suspended,
        
        [Description("Stopped")]
        Stopped,
        
        [Description("Not Responding")]
        NotResponding
    }

    /// <summary>
    /// Digital signature status
    /// </summary>
    public enum SignatureStatus
    {
        [Description("Microsoft Signed")]
        MicrosoftSigned,
        
        [Description("Known Vendor")]
        KnownVendor,
        
        [Description("Unsigned")]
        Unsigned,
        
        [Description("Suspicious")]
        Suspicious,
        
        [Description("Invalid Signature")]
        InvalidSignature
    }

    /// <summary>
    /// Optimization mode
    /// </summary>
    public enum OptimizationMode
    {
        [Description("Manual")]
        Manual,
        
        [Description("Automatic")]
        Automatic,
        
        [Description("Game Mode")]
        GameMode,
        
        [Description("Aggressive")]
        Aggressive,
        
        [Description("Conservative")]
        Conservative
    }

    /// <summary>
    /// Action status
    /// </summary>
    public enum ActionStatus
    {
        [Description("Pending")]
        Pending,
        
        [Description("Success")]
        Success,
        
        [Description("Failed")]
        Failed,
        
        [Description("Skipped")]
        Skipped,
        
        [Description("Rejected")]
        Rejected
    }
}
