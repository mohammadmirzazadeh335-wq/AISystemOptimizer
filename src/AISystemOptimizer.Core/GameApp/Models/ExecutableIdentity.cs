using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;
using AISystemOptimizer.Core.Models;

namespace AISystemOptimizer.Core.GameApp.Models
{
    /// <summary>
    /// Who an executable is, in the sense the specification demands: a combination that a file name
    /// alone cannot satisfy.
    ///
    /// The file name is recorded for display and is never used to decide identity. Identity is the
    /// canonical path plus the SHA-256 of the contents plus the publisher; the file name is a label.
    /// </summary>
    public sealed class ExecutableIdentity
    {
        /// <summary>Canonical, absolute path of the executable at the time this identity was captured.</summary>
        public string ExecutablePath { get; set; } = string.Empty;

        /// <summary>File name only. Display and matching hints; never a decision input on its own.</summary>
        public string FileName { get; set; } = string.Empty;

        /// <summary>SHA-256 of the file contents, lower-case hexadecimal.</summary>
        public string Sha256 { get; set; } = string.Empty;

        /// <summary>Company name from the version resource, when present.</summary>
        public string Publisher { get; set; } = string.Empty;

        /// <summary>
        /// The signature state as it was when this identity was captured. Recorded so the interface can
        /// report it without re-reading the file, and so a later change - a file that used to be signed
        /// and is no longer - becomes visible.
        /// </summary>
        public SignatureVerdict Signature { get; set; } = SignatureVerdict.Unknown;

        /// <summary>The executable's architecture as read from its header, or "Unknown".</summary>
        public string Architecture { get; set; } = "Unknown";

        /// <summary>Product name from the version resource, when present.</summary>
        public string ProductName { get; set; } = string.Empty;

        /// <summary>File version from the version resource, when present.</summary>
        public string FileVersion { get; set; } = string.Empty;

        /// <summary>Size of the file in bytes at capture time.</summary>
        public long FileSizeBytes { get; set; }

        /// <summary>When this identity was captured (UTC).</summary>
        public DateTime CapturedAtUtc { get; set; } = DateTime.UtcNow;

        /// <summary>
        /// True when this identity carries enough to identify a file: a path and a content hash.
        /// An identity without a hash is not an identity - it is a path that can be replaced.
        /// </summary>
        [JsonIgnore]
        public bool IsUsable =>
            !string.IsNullOrWhiteSpace(ExecutablePath) &&
            !string.IsNullOrWhiteSpace(Sha256);

        /// <summary>
        /// Build an identity from an inspection result.
        /// </summary>
        public static ExecutableIdentity FromInspection(ExecutableInspectionResult inspection)
        {
            if (inspection == null) throw new ArgumentNullException(nameof(inspection));

            return new ExecutableIdentity
            {
                ExecutablePath = inspection.CanonicalPath,
                FileName = inspection.FileName,
                Sha256 = inspection.Sha256,
                Publisher = inspection.Publisher,
                ProductName = inspection.ProductName,
                FileVersion = inspection.FileVersion,
                FileSizeBytes = inspection.FileSizeBytes,
                Signature = inspection.SignatureVerdict,
                Architecture = inspection.Architecture,
                CapturedAtUtc = DateTime.UtcNow
            };
        }
    }

    /// <summary>
    /// Everything that can be learned about an executable without running it.
    /// </summary>
    public sealed class ExecutableInspectionResult
    {
        /// <summary>Canonical absolute path, as validated.</summary>
        public string CanonicalPath { get; set; } = string.Empty;

        /// <summary>The path exactly as the user supplied it, kept so the difference can be shown.</summary>
        public string SuppliedPath { get; set; } = string.Empty;

        public string FileName { get; set; } = string.Empty;

        /// <summary>Directory the executable lives in (the installation directory, for most installers).</summary>
        public string DirectoryPath { get; set; } = string.Empty;

        /// <summary>Parent of <see cref="DirectoryPath"/>, shown as "install location".</summary>
        public string ParentDirectoryPath { get; set; } = string.Empty;

        public string ProductName { get; set; } = string.Empty;
        public string FileDescription { get; set; } = string.Empty;
        public string Publisher { get; set; } = string.Empty;
        public string FileVersion { get; set; } = string.Empty;
        public string ProductVersion { get; set; } = string.Empty;
        public string Copyright { get; set; } = string.Empty;

        public long FileSizeBytes { get; set; }
        public DateTime LastModifiedUtc { get; set; }

        /// <summary>True when the file still exists at the inspected path.</summary>
        public bool Exists { get; set; }

        /// <summary>"x64", "x86", "ARM64", "Unknown" - read from the PE header, never executed.</summary>
        public string Architecture { get; set; } = "Unknown";

        /// <summary>True when the PE header marks the file as a DLL rather than an executable.</summary>
        public bool IsDll { get; set; }

        /// <summary>SHA-256 of the contents, lower-case hexadecimal, or empty when it could not be read.</summary>
        public string Sha256 { get; set; } = string.Empty;

        /// <summary>
        /// What Windows says about the signature, verified with WinVerifyTrust where that is possible.
        /// Never <see cref="SignatureVerdict.Valid"/> unless verification actually succeeded.
        /// </summary>
        public SignatureVerdict SignatureVerdict { get; set; } = SignatureVerdict.Unknown;

        /// <summary>The HRESULT behind <see cref="SignatureVerdict"/>, so a verdict is never bare.</summary>
        public int SignatureResultCode { get; set; }

        /// <summary>Subject of the signing certificate, when one could be read.</summary>
        public string SignatureSubject { get; set; } = string.Empty;

        /// <summary>
        /// The same classification the rest of the application uses, for continuity with the existing
        /// screens. It means "a certificate is present and looks like this", not "Windows verified it".
        /// </summary>
        public SignatureStatus SignatureStatus { get; set; } = SignatureStatus.Unsigned;

        /// <summary>True when the file is reachable over SMB rather than a local volume.</summary>
        public bool IsNetworkPath { get; set; }

        /// <summary>Anything the inspector could not determine, in plain words, for the UI to show.</summary>
        public List<string> Notes { get; set; } = new List<string>();
    }

    /// <summary>
    /// One running process that appears to belong to an executable.
    /// </summary>
    public sealed class ApplicationRunInfo
    {
        public int ProcessId { get; set; }

        /// <summary>Creation time, the discriminator against pid reuse. Never <see cref="DateTime.MinValue"/>.</summary>
        public DateTime CreationTimeUtc { get; set; }

        /// <summary>The executable path the process reports, when readable.</summary>
        public string Path { get; set; } = string.Empty;

        /// <summary>Working set in bytes at the moment of the check.</summary>
        public long WorkingSet { get; set; }

        /// <summary>True when the path was read and matches the executable being profiled.</summary>
        public bool IsConfirmedMatch { get; set; }

        /// <summary>
        /// True when the process is the current foreground process. Carried so a caller does not have to
        /// ask again - and so that "in use" is never judged from a stale scan.
        /// </summary>
        public bool IsForeground { get; set; }

        /// <summary>True when the process owns a visible window.</summary>
        public bool HasVisibleWindow { get; set; }

        /// <summary>
        /// One line describing this run for the interface and the log. It always carries the creation time
        /// as well as the pid, because the pid on its own does not identify a process.
        /// </summary>
        public string Describe()
        {
            var started = CreationTimeUtc == default
                ? "start time unknown"
                : CreationTimeUtc.ToLocalTime().ToString("HH:mm:ss");

            var memory = WorkingSet > 0 ? $", {WorkingSet / (1024.0 * 1024.0):F0} MB" : string.Empty;

            var state = IsConfirmedMatch ? string.Empty : ", unconfirmed";

            return $"PID {ProcessId} (started {started}{memory}{state})";
        }
    }

    /// <summary>
    /// The result of asking "is this profile still about the executable it was created for?"
    /// </summary>
    public sealed class ApplicationHealth
    {
        public ApplicationHealthState State { get; set; } = ApplicationHealthState.NotChecked;

        /// <summary>Every difference that was found, in words a user can act on.</summary>
        public List<string> Findings { get; set; } = new List<string>();

        /// <summary>The identity as it is now, when it could be read.</summary>
        public ExecutableIdentity? CurrentIdentity { get; set; }

        /// <summary>
        /// True when the profile may be used. A changed or unreachable executable suspends the profile
        /// rather than letting it be applied to whatever is at that path now.
        /// </summary>
        public bool IsUsable => State == ApplicationHealthState.Healthy;

        /// <summary>The sentence the interface shows.</summary>
        public string Summary => State switch
        {
            ApplicationHealthState.Healthy => "Executable verified.",
            ApplicationHealthState.ExecutableMissing => "Executable missing. Profile cannot be used until the file is back.",
            ApplicationHealthState.ExecutableChanged => "Executable changed. Profile requires verification.",
            ApplicationHealthState.PublisherChanged => "Publisher changed. Profile requires verification.",
            ApplicationHealthState.ProfileOutdated => "Profile was written by a newer version of this application.",
            ApplicationHealthState.InsufficientPermissions => "Insufficient permissions to verify the executable.",
            _ => "Profile has not been checked against the executable yet."
        };
    }
}
