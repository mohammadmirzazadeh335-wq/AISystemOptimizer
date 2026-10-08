using System;
using System.ComponentModel;
using System.Text.Json.Serialization;

namespace AISystemOptimizer.Core.GameApp.Models
{
    /// <summary>
    /// How much a profile is allowed to change.
    ///
    /// There is deliberately no "Unsafe" member and no "Maximum": a mode is a *ceiling* on what the
    /// profile may propose, and the safety layer is the floor underneath all four of them. A mode can
    /// never make an action that the safety layer refuses become acceptable.
    /// </summary>
    public enum GameAppProfileMode
    {
        /// <summary>Minimal, reversible changes only: priority, power mode, nothing else.</summary>
        [Description("Safe")]
        Safe,

        /// <summary>The recommended default: safe changes plus background-process optimisation.</summary>
        [Description("Balanced")]
        Balanced,

        /// <summary>Everything Balanced allows, with the conservative limits raised - still inside the safety model.</summary>
        [Description("Performance")]
        Performance,

        /// <summary>The user selected the individual switches. Nothing is enabled implicitly.</summary>
        [Description("Custom")]
        Custom
    }

    /// <summary>
    /// What the user says the application is.
    ///
    /// This is presentation and grouping only - it never changes a safety decision. It defaults to
    /// <see cref="Unknown"/> because the specification is explicit that the application must not assume
    /// that every executable is a game, and guessing "Game" from a filename is exactly that assumption.
    /// </summary>
    public enum ApplicationKind
    {
        [Description("Not specified")]
        Unknown,

        [Description("Game")]
        Game,

        [Description("Game launcher")]
        Launcher,

        [Description("Creative application")]
        Creative,

        [Description("Development tool")]
        Development,

        [Description("Heavy application")]
        Heavy,

        [Description("Other application")]
        Other
    }

    /// <summary>
    /// How much the optimiser is allowed to do with one background process.
    ///
    /// The order is deliberate: it runs from "no permission at all" to "allowed, still checked".
    /// Nothing here grants permission on its own - a process in <see cref="SafeToClose"/> or
    /// <see cref="UsuallySafe"/> is still passed through the existing safety layer, and the user still
    /// confirms where the policy says so.
    /// </summary>
    public enum BackgroundProcessCategory
    {
        /// <summary>Never closed, whatever any profile or list says.</summary>
        [Description("Never close")]
        NeverClose,

        /// <summary>The user must decide, every time. This is the default for anything uncertain.</summary>
        [Description("Ask before closing")]
        UserConfirmationRequired,

        /// <summary>Background work with no window and no user session; closing it loses no work.</summary>
        [Description("Usually safe")]
        UsuallySafe,

        /// <summary>Nothing to lose at all, and a real effect on memory.</summary>
        [Description("Safe to close")]
        SafeToClose
    }

    /// <summary>
    /// Whether a profile still describes the executable it was created for.
    /// </summary>
    public enum ApplicationHealthState
    {
        /// <summary>The executable is present and matches the identity recorded in the profile.</summary>
        [Description("Healthy")]
        Healthy,

        /// <summary>The file is not where the profile says it is.</summary>
        [Description("Executable missing")]
        ExecutableMissing,

        /// <summary>The file is there but its contents changed - an update, or a different program.</summary>
        [Description("Executable changed")]
        ExecutableChanged,

        /// <summary>The file is unchanged but its publisher no longer matches.</summary>
        [Description("Publisher changed")]
        PublisherChanged,

        /// <summary>The profile was written by a newer version of the application than this one.</summary>
        [Description("Profile outdated")]
        ProfileOutdated,

        /// <summary>The file exists but could not be read - usually a permission problem.</summary>
        [Description("Insufficient permissions")]
        InsufficientPermissions,

        /// <summary>The health check itself could not complete, so nothing is claimed either way.</summary>
        [Description("Not checked")]
        NotChecked
    }

    /// <summary>
    /// What kind of thing a "Never optimize" entry matches on.
    /// </summary>
    public enum NeverOptimizeKind
    {
        [Description("Process name")]
        ProcessName,

        [Description("Executable path")]
        ExecutablePath,

        [Description("Publisher")]
        Publisher,

        [Description("File hash")]
        FileHash
    }

    /// <summary>
    /// The result of verifying an executable's Authenticode signature.
    ///
    /// This is deliberately separate from <see cref="AISystemOptimizer.Core.Models.SignatureStatus"/>,
    /// which only *reads the certificate*. "A certificate is attached" and "Windows verified the file
    /// against that certificate" are different statements, and conflating them would be the kind of
    /// unverified claim this project does not make.
    /// </summary>
    public enum SignatureVerdict
    {
        /// <summary>WinVerifyTrust returned success: the file is signed and the signature verifies.</summary>
        [Description("Valid")]
        Valid,

        /// <summary>The file carries a signature but it does not verify (tampered, expired, untrusted chain).</summary>
        [Description("Invalid")]
        Invalid,

        /// <summary>There is no signature on the file. This is not evidence of malware.</summary>
        [Description("Unsigned")]
        Unsigned,

        /// <summary>The check could not be performed here, so nothing is claimed.</summary>
        [Description("Unknown")]
        Unknown
    }

    /// <summary>
    /// How an application's running state is reported.
    /// </summary>
    public enum ApplicationRunState
    {
        [Description("Not running")]
        NotRunning,

        /// <summary>At least one process was matched to this executable by both name and path.</summary>
        [Description("Running")]
        Running,

        /// <summary>
        /// A process with the same file name is running, but its executable path could not be read, so it
        /// cannot be confirmed to be this program. Reported honestly as unconfirmed rather than assumed.
        /// </summary>
        [Description("Unconfirmed")]
        Unconfirmed
    }
}
