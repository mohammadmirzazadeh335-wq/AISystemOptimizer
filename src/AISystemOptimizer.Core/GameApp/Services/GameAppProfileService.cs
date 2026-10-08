using System;
using System.Collections.Generic;
using System.Linq;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// The outcome of trying to add an application.
    /// </summary>
    public sealed class AddApplicationResult
    {
        public bool Success { get; init; }

        public GameAppProfile? Profile { get; init; }

        /// <summary>Why the application was not added, in words the user can act on.</summary>
        public string ErrorMessage { get; init; } = string.Empty;

        /// <summary>Things that are not errors but should be shown: unsigned publisher, network share, existing profile.</summary>
        public List<string> Notes { get; init; } = new List<string>();

        /// <summary>Set when the executable is already profiled, so the interface can offer to open it instead.</summary>
        public GameAppProfile? ExistingProfile { get; init; }

        public static AddApplicationResult Failure(string reason) =>
            new AddApplicationResult { Success = false, ErrorMessage = reason };
    }

    /// <summary>
    /// The operations behind the Game &amp; App Optimizer page, other than the ones that change the system.
    ///
    /// Adding an application does exactly three things: validate the path, read the file's metadata and
    /// write one profile file. It does not run the executable, start a process, touch the registry, change
    /// a power setting or alter any file the application owns. That is the requirement in the specification
    /// ("adding an application only creates a profile") and it is asserted by a test.
    ///
    /// Every system-changing operation lives in <c>GameAppActionPlanner</c>, <c>GameAppSessionManager</c>
    /// and, ultimately, the existing <c>SafeExecutor</c>.
    /// </summary>
    public sealed class GameAppProfileService : IDisposable
    {
        private readonly ILogger _logger;
        private readonly GameAppProfileStore _store;
        private readonly ExecutableInspector _inspector;

        private readonly List<GameAppProfile> _profiles = new List<GameAppProfile>();

        private bool _disposed;

        public GameAppProfileService(
            ILogger? logger = null,
            GameAppProfileStore? store = null,
            ExecutableInspector? inspector = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();
            _store = store ?? new GameAppProfileStore(_logger);
            _inspector = inspector ?? new ExecutableInspector(_logger);
        }

        #region State

        /// <summary>The profiles currently held in memory, in the order the interface shows them.</summary>
        public IReadOnlyList<GameAppProfile> Profiles => _profiles;

        /// <summary>Problems from the last load, for the interface to surface instead of hiding.</summary>
        public IReadOnlyList<string> LoadProblems => _store.LoadProblems;

        public ProfileLoadOutcome LastOutcome => _store.LastOutcome;

        public string StoreDirectory => _store.DirectoryPath;

        #endregion

        #region Load

        /// <summary>
        /// Read every profile from disk. Called on start-up and whenever the page is opened.
        /// </summary>
        public void Reload()
        {
            _profiles.Clear();
            _profiles.AddRange(_store.LoadAll());

            foreach (var profile in _profiles)
                profile.LastKnownHealth = ApplicationHealthState.NotChecked;

            _logger.Info("GameAppProfileService",
                $"{_profiles.Count} application profile(s) loaded from {_store.DirectoryPath}");

            if (_store.LoadProblems.Count > 0)
            {
                foreach (var problem in _store.LoadProblems)
                    _logger.Warning("GameAppProfileService", problem);
            }
        }

        #endregion

        #region Add

        /// <summary>
        /// Add an application by its executable path.
        ///
        /// The path is treated as untrusted input from the first line. Nothing happens to the system: the
        /// method reads the file, writes one profile and returns.
        /// </summary>
        public AddApplicationResult AddApplication(string? path, ApplicationKind kind = ApplicationKind.Unknown)
        {
            var validation = ExecutablePathValidator.Validate(path);

            if (!validation.IsValid)
            {
                _logger.Warning("GameAppProfileService", $"Application not added: {validation.ErrorMessage}");
                return AddApplicationResult.Failure(validation.ErrorMessage);
            }

            var inspection = _inspector.Inspect(validation);

            if (!inspection.Exists)
            {
                return AddApplicationResult.Failure("The file is not present at the selected path.");
            }

            if (string.IsNullOrWhiteSpace(inspection.Sha256))
            {
                return AddApplicationResult.Failure(
                    "This file could not be read for hashing, so it cannot be identified reliably. It will not " +
                    "be profiled. Details: " + string.Join(" ", inspection.Notes));
            }

            // Refuse a duplicate before the user invests time in a second profile for one program.
            var existing = _store.FindByExecutable(_profiles, inspection.CanonicalPath, inspection.Sha256);

            if (existing != null)
            {
                return new AddApplicationResult
                {
                    Success = false,
                    ExistingProfile = existing,
                    ErrorMessage =
                        $"'{existing.ResolveDisplayName()}' already has a profile for this executable.",
                    Notes = { "Open the existing profile instead of creating a second one." }
                };
            }

            var profile = new GameAppProfile
            {
                ApplicationId = Guid.NewGuid(),
                Kind = kind,
                ProfileMode = GameAppProfileMode.Balanced,
                Identity = ExecutableIdentity.FromInspection(inspection)
            };

            profile.DisplayName = !string.IsNullOrWhiteSpace(inspection.ProductName)
                ? inspection.ProductName
                : inspection.FileName;

            var notes = new List<string>(inspection.Notes);

            switch (inspection.SignatureVerdict)
            {
                case SignatureVerdict.Unsigned:
                    notes.Add(
                        "This executable is unsigned. That is common for legitimate software - it means the " +
                        "publisher cannot be verified, not that anything is wrong.");
                    break;

                case SignatureVerdict.Invalid:
                    notes.Add(
                        "Windows reports that this file's signature does not verify. The file may have been " +
                        "modified after it was signed.");
                    break;

                case SignatureVerdict.Unknown:
                    notes.Add("The signature could not be checked on this machine.");
                    break;
            }

            if (inspection.IsDll)
                notes.Add("The file is marked as a library rather than an application.");

            if (inspection.Architecture.StartsWith("Unknown", StringComparison.OrdinalIgnoreCase))
                notes.Add("The executable's architecture could not be read.");

            profile.NormalizeToSupportedRanges();

            if (!_store.Save(profile))
            {
                return AddApplicationResult.Failure(
                    $"The profile could not be written to {_store.DirectoryPath}. Check that the folder is writable.");
            }

            var duplicateInMemory = _profiles.Any(p => p.ApplicationId == profile.ApplicationId);

            if (!duplicateInMemory)
                _profiles.Add(profile);

            _logger.Info("GameAppProfileService",
                $"Added '{profile.ResolveDisplayName()}' ({inspection.Architecture}, " +
                $"signature {inspection.SignatureVerdict}) from '{inspection.CanonicalPath}'. " +
                "No system setting was changed by adding it.");

            return new AddApplicationResult
            {
                Success = true,
                Profile = profile,
                Notes = notes
            };
        }

        #endregion

        #region Remove / update

        /// <summary>
        /// Remove a profile. Only this application's own files are removed; the executable itself is
        /// never touched.
        /// </summary>
        public bool RemoveApplication(Guid applicationId)
        {
            var profile = _profiles.FirstOrDefault(p => p.ApplicationId == applicationId);

            if (profile == null)
                return false;

            if (!_store.Delete(profile))
                return false;

            _profiles.Remove(profile);

            _logger.Info("GameAppProfileService",
                $"Removed the profile for '{profile.ResolveDisplayName()}'. The application itself was not touched.");

            return true;
        }

        /// <summary>
        /// Persist a change to a profile that already exists.
        /// </summary>
        public bool Update(GameAppProfile profile)
        {
            if (profile == null)
                return false;

            profile.NormalizeToSupportedRanges();

            if (!_store.Save(profile))
                return false;

            if (!_profiles.Any(p => p.ApplicationId == profile.ApplicationId))
                _profiles.Add(profile);

            return true;
        }

        #endregion

        #region Health

        /// <summary>
        /// Compare a profile against the executable on disk.
        ///
        /// This is the guard that stops a profile being applied to a different program that happens to sit
        /// at the same path: if the contents changed, the profile is suspended and the user is told, rather
        /// than the optimisation silently running against whatever is there now.
        /// </summary>
        public ApplicationHealth CheckHealth(GameAppProfile profile, bool computeHash = true)
        {
            var health = new ApplicationHealth();

            if (profile == null)
            {
                health.State = ApplicationHealthState.NotChecked;
                health.Findings.Add("No profile was supplied.");
                return health;
            }

            if (profile.SchemaVersion > GameAppProfile.CurrentSchemaVersion)
            {
                health.State = ApplicationHealthState.ProfileOutdated;
                health.Findings.Add(
                    $"The profile was written by schema version {profile.SchemaVersion}; this build understands " +
                    $"version {GameAppProfile.CurrentSchemaVersion}.");
                return health;
            }

            var path = profile.ExecutablePath;

            if (string.IsNullOrWhiteSpace(path))
            {
                health.State = ApplicationHealthState.ExecutableMissing;
                health.Findings.Add("The profile does not record an executable path.");
                return health;
            }

            // Re-validate the stored path: a profile file is user-editable, so its contents are input too.
            var validation = ExecutablePathValidator.Validate(path, requireExists: false, rejectReparsePoints: true);

            if (!validation.IsValid)
            {
                health.State = ApplicationHealthState.ExecutableChanged;
                health.Findings.Add($"The recorded path is no longer acceptable: {validation.ErrorMessage}");
                return health;
            }

            var inspection = _inspector.Inspect(validation);

            if (!inspection.Exists)
            {
                health.State = ApplicationHealthState.ExecutableMissing;
                health.Findings.Add($"No file exists at '{path}'.");
                return health;
            }

            if (string.IsNullOrWhiteSpace(inspection.Sha256))
            {
                health.State = ApplicationHealthState.InsufficientPermissions;
                health.Findings.Add("The file exists but could not be read, so its identity cannot be verified.");
                return health;
            }

            return EvaluateHealth(profile, inspection, computeHash);
        }

        /// <summary>
        /// The comparison itself, as a pure function of a profile and an inspection result.
        ///
        /// It is separated from the reading of the file so that every rule here - changed contents,
        /// changed publisher, a missing hash, an outdated schema - can be tested directly, without a
        /// particular file having to exist on the machine running the tests.
        /// </summary>
        public static ApplicationHealth EvaluateHealth(
            GameAppProfile profile,
            ExecutableInspectionResult inspection,
            bool computeHash = true)
        {
            var health = new ApplicationHealth();

            if (profile == null || inspection == null)
            {
                health.Findings.Add("Nothing to compare.");
                return health;
            }

            health.CurrentIdentity = ExecutableIdentity.FromInspection(inspection);

            if (string.IsNullOrWhiteSpace(profile.Identity?.Sha256))
            {
                health.State = ApplicationHealthState.ExecutableChanged;
                health.Findings.Add(
                    "The profile does not record a file hash, so the executable's identity cannot be verified. " +
                    "Re-verify the profile to continue using it.");
                return health;
            }

            if (computeHash &&
                !string.Equals(profile.Identity!.Sha256, inspection.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                health.State = ApplicationHealthState.ExecutableChanged;
                health.Findings.Add(
                    $"The file's contents changed. The profile recorded {Short(profile.Identity.Sha256)} and the " +
                    $"file is now {Short(inspection.Sha256)}. This is what an application update looks like - and " +
                    "it is also what a different program placed at the same path looks like.");

                if (profile.Identity.FileSizeBytes != inspection.FileSizeBytes)
                {
                    health.Findings.Add(
                        $"The size changed from {profile.Identity.FileSizeBytes:N0} to {inspection.FileSizeBytes:N0} bytes.");
                }

                if (!string.Equals(profile.Identity.FileVersion, inspection.FileVersion, StringComparison.OrdinalIgnoreCase))
                {
                    health.Findings.Add(
                        $"The file version changed from '{Describe(profile.Identity.FileVersion)}' to " +
                        $"'{Describe(inspection.FileVersion)}'.");
                }

                return health;
            }

            if (!string.IsNullOrWhiteSpace(profile.Identity.Publisher) &&
                !string.IsNullOrWhiteSpace(inspection.Publisher) &&
                !profile.Identity.Publisher.Equals(inspection.Publisher, StringComparison.OrdinalIgnoreCase))
            {
                health.State = ApplicationHealthState.PublisherChanged;
                health.Findings.Add(
                    $"The publisher changed from '{profile.Identity.Publisher}' to '{inspection.Publisher}'.");
                return health;
            }

            if (!string.IsNullOrWhiteSpace(profile.Identity.Sha256) &&
                !string.IsNullOrWhiteSpace(inspection.Sha256) &&
                profile.Identity.Sha256.Equals(inspection.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                health.State = ApplicationHealthState.Healthy;

                if (inspection.SignatureVerdict is SignatureVerdict.Unsigned or SignatureVerdict.Invalid)
                    health.Findings.Add($"Signature: {inspection.SignatureVerdict}.");

                foreach (var note in inspection.Notes)
                    health.Findings.Add(note);

                return health;
            }

            health.State = ApplicationHealthState.ExecutableChanged;
            health.Findings.Add("The executable does not match the profile.");

            return health;
        }

        /// <summary>
        /// Re-bind a profile to the executable as it is now, after the user has confirmed that the change
        /// was theirs (an update). The new identity replaces the old one; the profile's settings and
        /// history stay.
        /// </summary>
        public bool RebindToCurrentExecutable(GameAppProfile profile, ApplicationHealth health)
        {
            if (profile == null || health?.CurrentIdentity == null)
                return false;

            profile.Identity = health.CurrentIdentity;
            profile.LastVerifiedAtUtc = DateTime.UtcNow;
            profile.LastKnownHealth = ApplicationHealthState.Healthy;

            var saved = _store.Save(profile);

            if (saved)
            {
                _logger.Info("GameAppProfileService",
                    $"Profile '{profile.ResolveDisplayName()}' was re-verified against the executable at " +
                    $"'{profile.ExecutablePath}' by the user's confirmation.");
            }

            return saved;
        }

        #endregion

        #region Never-optimize interaction

        /// <summary>
        /// True when the application itself is on the user's never-optimise list. A profile whose
        /// executable is protected is listed but never applied.
        /// </summary>
        public bool IsApplicationProtected(GameAppProfile profile, IEnumerable<NeverOptimizeEntry> entries)
        {
            if (profile == null || entries == null)
                return false;

            var identity = profile.Identity;

            return entries.Any(entry => entry != null && entry.Matches(
                profile.FileName,
                profile.ExecutablePath,
                identity?.Publisher,
                identity?.Sha256));
        }

        #endregion

        private static string Short(string? hash) =>
            string.IsNullOrWhiteSpace(hash) ? "(none)" : hash!.Substring(0, Math.Min(12, hash.Length)) + "…";

        private static string Describe(string? value) =>
            string.IsNullOrWhiteSpace(value) ? "(not recorded)" : value!;

        public void Dispose()
        {
            if (_disposed)
                return;

            _disposed = true;
            _profiles.Clear();
        }
    }
}
