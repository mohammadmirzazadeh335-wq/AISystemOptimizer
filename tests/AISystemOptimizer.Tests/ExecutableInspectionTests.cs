using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.GameApp.Services;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the two places where input the user chose enters the application: the executable path
    /// validator and the metadata inspector.
    ///
    /// A path from a file dialog is still untrusted input. These tests are written on the assumption that
    /// every hostile shape a path can take will eventually be tried: device paths, traversal, characters
    /// that mean something to a shell, links that are re-pointed later, and files that are not what their
    /// extension claims.
    /// </summary>
    public class ExecutableInspectionTests : IDisposable
    {
        private readonly string _directory;

        public ExecutableInspectionTests()
        {
            _directory = Path.Combine(Path.GetTempPath(), "aio-inspect-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_directory);
        }

        public void Dispose()
        {
            try
            {
                if (Directory.Exists(_directory))
                    Directory.Delete(_directory, recursive: true);
            }
            catch
            {
                // Never fail a run on cleanup.
            }
        }

        /// <summary>
        /// Create a file that starts with a real PE header, so the inspector has something concrete to
        /// read. The header is written by hand: this repository must not need a Windows toolchain to test
        /// its own inspection code.
        /// </summary>
        private string CreateFakeExecutable(string name, ushort machine = 0x8664, bool dll = false)
        {
            var path = Path.Combine(_directory, name);

            var bytes = new List<byte>();

            // DOS header: 'MZ' plus a stub, with the PE offset stored at 0x3C.
            bytes.AddRange(new byte[] { 0x4D, 0x5A });          // "MZ"
            bytes.AddRange(new byte[0x3A]);                     // padding up to 0x3C
            bytes.AddRange(BitConverter.GetBytes(0x80));        // e_lfanew = 0x80
            bytes.AddRange(new byte[0x80 - bytes.Count]);

            // PE signature "PE\0\0"
            bytes.AddRange(new byte[] { 0x50, 0x45, 0x00, 0x00 });

            // IMAGE_FILE_HEADER: Machine, NumberOfSections, TimeDateStamp, PointerToSymbolTable,
            // NumberOfSymbols, SizeOfOptionalHeader, Characteristics
            bytes.AddRange(BitConverter.GetBytes(machine));
            bytes.AddRange(BitConverter.GetBytes((ushort)1));
            bytes.AddRange(BitConverter.GetBytes(0));
            bytes.AddRange(BitConverter.GetBytes(0));
            bytes.AddRange(BitConverter.GetBytes(0));
            bytes.AddRange(BitConverter.GetBytes((ushort)0xE0));
            bytes.AddRange(BitConverter.GetBytes((ushort)(dll ? 0x2000 : 0x0022)));

            // Enough body that the file is not obviously a stub.
            bytes.AddRange(Encoding.ASCII.GetBytes(new string('A', 4096)));

            File.WriteAllBytes(path, bytes.ToArray());

            return path;
        }

        #region Path validation

        [Fact]
        public void APlainExecutablePath_IsAccepted()
        {
            var path = CreateFakeExecutable("App.exe");

            var result = ExecutablePathValidator.Validate(path);

            Assert.True(result.IsValid, result.ErrorMessage);
            Assert.Equal(Path.GetFullPath(path), result.CanonicalPath);
            Assert.Equal("App.exe", result.FileName);
            Assert.False(result.IsNetworkPath);
        }

        [Fact]
        public void AnEmptyOrMissingPath_IsRejected()
        {
            Assert.False(ExecutablePathValidator.Validate(null).IsValid);
            Assert.False(ExecutablePathValidator.Validate("").IsValid);
            Assert.False(ExecutablePathValidator.Validate("   ").IsValid);
            Assert.False(ExecutablePathValidator.Validate(@"C:\does\not\exist\nothing.exe").IsValid);
        }

        [Fact]
        public void ANonExecutableExtension_IsRejected()
        {
            var path = Path.Combine(_directory, "script.bat");
            File.WriteAllText(path, "rem");

            var result = ExecutablePathValidator.Validate(path);

            Assert.False(result.IsValid);
            Assert.Contains(".exe", result.ErrorMessage, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void ARelativePath_IsRejected()
        {
            Assert.False(ExecutablePathValidator.Validate(@"Games\Game.exe").IsValid);
            Assert.False(ExecutablePathValidator.Validate("Game.exe").IsValid);
        }

        [Theory]
        [InlineData(@"\\?\C:\Windows\System32\cmd.exe")]
        [InlineData(@"\\.\PhysicalDrive0")]
        [InlineData(@"\??\C:\Windows\notepad.exe")]
        public void DevicePaths_AreRejected(string path)
        {
            // Device paths bypass normal path parsing. Nothing a user browses to in a file dialog is a
            // device path, so refusing them costs nothing and closes a whole class of surprises.
            var result = ExecutablePathValidator.Validate(path);

            Assert.False(result.IsValid);
            Assert.Contains("Device paths", result.ErrorMessage, StringComparison.Ordinal);
        }

        [Fact]
        public void APathWithControlCharacters_IsRejected()
        {
            var result = ExecutablePathValidator.Validate("C:\\Games\\Evi\u0007l\\Game.exe");

            Assert.False(result.IsValid);
        }

        [Fact]
        public void AnOverlongPath_IsRejected()
        {
            var longPath = @"C:\" + new string('a', 600) + ".exe";

            var result = ExecutablePathValidator.Validate(longPath);

            Assert.False(result.IsValid);
            Assert.Contains("limit", result.ErrorMessage, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void ADirectoryPath_IsRejected()
        {
            var result = ExecutablePathValidator.Validate(_directory);

            Assert.False(result.IsValid);
        }

        [Fact]
        public void SurroundingQuotesAndMixedSeparators_AreAccepted()
        {
            // The Windows "Copy as path" command puts quotes around the path; a user pasting it should not
            // have to remove them.
            var path = CreateFakeExecutable("Quoted.exe");

            var result = ExecutablePathValidator.Validate("\"" + path + "\"");

            Assert.True(result.IsValid, result.ErrorMessage);
        }

        [Fact]
        public void RefersToSameFile_IgnoresCaseAndSeparators()
        {
            Assert.True(ExecutablePathValidator.RefersToSameFile(@"C:\Games\A\Game.exe", @"c:/games/a/GAME.EXE"));
            Assert.True(ExecutablePathValidator.RefersToSameFile(@"C:\Games\A\Game.exe", @"C:\Games\A\Game.exe\"));
            Assert.False(ExecutablePathValidator.RefersToSameFile(@"C:\Games\A\Game.exe", @"C:\Games\B\Game.exe"));
            Assert.False(ExecutablePathValidator.RefersToSameFile(null, @"C:\Games\A\Game.exe"));
        }

        [Fact]
        public void NormaliseExecutableName_StripsThePathAndTheExtension()
        {
            Assert.Equal("Game", ExecutablePathValidator.NormaliseExecutableName(@"C:\Games\Game.exe"));

            // The case is preserved - callers compare case-insensitively - but the path and the extension
            // are gone, and both separators are understood.
            Assert.Equal("game", ExecutablePathValidator.NormaliseExecutableName("game.EXE"));
            Assert.Equal("game", ExecutablePathValidator.NormaliseExecutableName("C:/Games/game.exe"));
            Assert.Equal("Game", ExecutablePathValidator.NormaliseExecutableName("  \"Game.exe\"  "));
            Assert.Equal(string.Empty, ExecutablePathValidator.NormaliseExecutableName(null));
        }

        [Fact]
        public void VolumeRootOf_ReturnsTheDrive()
        {
            // The exact form differs between platforms, so only the invariant is asserted.
            var root = ExecutablePathValidator.VolumeRootOf(@"C:\Games\Game.exe");

            Assert.False(string.IsNullOrEmpty(root));
            Assert.Equal(Path.GetPathRoot(Path.GetFullPath(@"C:\Games\Game.exe")), root);
        }

        #endregion

        #region Inspection

        [Fact]
        public void Inspection_ReadsTheHeaderAndHashesTheFile()
        {
            var path = CreateFakeExecutable("App.exe", machine: 0x8664);

            var inspector = new ExecutableInspector();
            var inspection = inspector.ValidateAndInspect(path, out var validation);

            Assert.True(validation.IsValid);
            Assert.True(inspection.Exists);
            Assert.Equal("x64", inspection.Architecture);
            Assert.False(inspection.IsDll);
            Assert.Equal(new FileInfo(path).Length, inspection.FileSizeBytes);
            Assert.Equal(64, inspection.Sha256.Length);
            Assert.Equal(inspection.Sha256.ToLowerInvariant(), inspection.Sha256);
            Assert.False(string.IsNullOrWhiteSpace(inspection.DirectoryPath));
        }

        [Theory]
        [InlineData(0x014C, "x86")]
        [InlineData(0x8664, "x64")]
        [InlineData(0xAA64, "ARM64")]
        public void TheArchitecture_IsReadFromTheHeader(ushort machine, string expected)
        {
            var inspector = new ExecutableInspector();

            var path = CreateFakeExecutable($"arch-{expected}.exe", machine);
            var inspection = inspector.Inspect(ExecutablePathValidator.Validate(path));

            Assert.Equal(expected, inspection.Architecture);
        }

        [Fact]
        public void ADll_IsMarkedAsOneRatherThanAssumedToBeAnApplication()
        {
            var path = CreateFakeExecutable("Library.dll.exe", dll: true);

            var inspection = new ExecutableInspector().Inspect(ExecutablePathValidator.Validate(path));

            Assert.True(inspection.IsDll);
            Assert.Contains(inspection.Notes, n => n.Contains("library", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void AFileThatIsNotAnExecutable_IsReportedAsSuchAndNotThrown()
        {
            var path = Path.Combine(_directory, "Notreally.exe");

            // Large enough to hold a header, but plainly not one: this is the shape that must be reported
            // as "not an executable" rather than merely "too small to tell".
            File.WriteAllText(path, new string('p', 512));

            var inspection = new ExecutableInspector().Inspect(ExecutablePathValidator.Validate(path));

            Assert.True(inspection.Exists);
            Assert.Equal("Unknown", inspection.Architecture);

            // It is still hashed - the file exists and can be read - but the notes say why it is odd.
            Assert.False(string.IsNullOrWhiteSpace(inspection.Sha256));
            Assert.Contains(inspection.Notes, n => n.Contains("DOS header", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void InspectionNeverThrows_ForAnyOfTheseInputs()
        {
            var inspector = new ExecutableInspector();

            // A directory, a device path, a control-character path, an empty name: none of these may throw.
            var inputs = new List<string?>
            {
                null,
                string.Empty,
                _directory,
                @"\\?\C:\x.exe",
                "C:\\a\u0001b\\x.exe",
                Path.Combine(_directory, "missing.exe"),
                new string('x', 900)
            };

            foreach (var input in inputs)
            {
                var inspection = inspector.ValidateAndInspect(input, out var validation);

                Assert.NotNull(inspection);
                Assert.NotNull(validation);
                Assert.NotNull(inspection.Notes);
            }
        }

        [Fact]
        public void TheHash_ChangesWhenTheFileChanges()
        {
            var path = CreateFakeExecutable("Versioned.exe");

            var inspector = new ExecutableInspector();

            var first = inspector.Inspect(ExecutablePathValidator.Validate(path)).Sha256;

            // Append a byte: this is what an update looks like to the health check.
            File.AppendAllText(path, "x");

            var second = inspector.Inspect(ExecutablePathValidator.Validate(path)).Sha256;

            Assert.NotEqual(first, second);
        }

        [Fact]
        public void TheSignatureVerdict_IsNeverValidWithoutARealCheck()
        {
            // Off Windows the check cannot run, so the verdict must be Unknown. On Windows this test file
            // is unsigned, so the verdict is Unsigned. Either is honest; "Valid" would not be.
            var path = CreateFakeExecutable("Unsigned.exe");

            var inspection = new ExecutableInspector().Inspect(ExecutablePathValidator.Validate(path));

            Assert.NotEqual(SignatureVerdict.Valid, inspection.SignatureVerdict);

            if (!OperatingSystem.IsWindows())
            {
                Assert.Equal(SignatureVerdict.Unknown, inspection.SignatureVerdict);
            }
        }

        [Fact]
        public void TheSignatureVerdict_ExplainsItself()
        {
            var path = CreateFakeExecutable("Explained.exe");

            var inspection = new ExecutableInspector().Inspect(ExecutablePathValidator.Validate(path));

            Assert.Contains(
                inspection.Notes,
                n => n.Contains("signature", StringComparison.OrdinalIgnoreCase));
        }

        #endregion

        #region Signature classification

        [Theory]
        [InlineData(0, SignatureVerdict.Valid)]
        [InlineData(unchecked((int)0x800B0100), SignatureVerdict.Unsigned)]   // TRUST_E_NOSIGNATURE
        [InlineData(unchecked((int)0x800B0003), SignatureVerdict.Unsigned)]   // TRUST_E_SUBJECT_FORM_UNKNOWN
        [InlineData(unchecked((int)0x800B0001), SignatureVerdict.Unsigned)]   // TRUST_E_PROVIDER_UNKNOWN
        [InlineData(unchecked((int)0x80096010), SignatureVerdict.Invalid)]    // TRUST_E_BAD_DIGEST
        [InlineData(unchecked((int)0x800B0109), SignatureVerdict.Invalid)]    // CERT_E_UNTRUSTEDROOT
        [InlineData(unchecked((int)0x800B0101), SignatureVerdict.Invalid)]    // CERT_E_EXPIRED
        [InlineData(unchecked((int)0x800B010A), SignatureVerdict.Invalid)]    // CERT_E_CHAINING
        [InlineData(unchecked((int)0x800B0111), SignatureVerdict.Invalid)]    // TRUST_E_EXPLICIT_DISTRUST
        [InlineData(unchecked((int)0x800B010C), SignatureVerdict.Unknown)]    // CERT_E_REVOKED, unclassified here
        public void WinVerifyTrustCodes_MapToTheRightVerdict(int code, SignatureVerdict expected)
        {
            Assert.Equal(expected, AuthenticodeVerifier.ClassifyResult(code));
        }

        [Fact]
        public void AnUnsignedFile_IsExplainedAsNotBeingEvidenceOfHarm()
        {
            var explanation = AuthenticodeVerifier.ExplainResult(SignatureVerdict.Unsigned, unchecked((int)0x800B0100));

            Assert.Contains("no digital signature", explanation, StringComparison.OrdinalIgnoreCase);
            Assert.Contains("not", explanation, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void AModifiedSignedFile_IsExplainedAsModified()
        {
            var explanation = AuthenticodeVerifier.ExplainResult(
                SignatureVerdict.Invalid, unchecked((int)0x80096010));

            Assert.Contains("modified", explanation, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void VerificationOfAMissingPath_IsUnknownRatherThanAFailure()
        {
            // An unreadable input is not evidence about the file.
            var result = AuthenticodeVerifier.Verify(null);

            Assert.Equal(SignatureVerdict.Unknown, result.Verdict);
            Assert.False(string.IsNullOrWhiteSpace(result.Explanation));
        }

        [Fact]
        public void ASignatureVerdictAlwaysCarriesAReason()
        {
            var path = CreateFakeExecutable("Reasoned.exe");

            var verification = AuthenticodeVerifier.Verify(path);

            Assert.False(string.IsNullOrWhiteSpace(verification.Explanation));
        }

        #endregion

        #region Profile creation from an inspection

        [Fact]
        public void AnInspection_BecomesAnIdentityWithAPathAndAHash()
        {
            var path = CreateFakeExecutable("Identified.exe");

            var inspection = new ExecutableInspector().Inspect(ExecutablePathValidator.Validate(path));
            var identity = ExecutableIdentity.FromInspection(inspection);

            Assert.True(identity.IsUsable);
            Assert.Equal(inspection.CanonicalPath, identity.ExecutablePath);
            Assert.Equal(inspection.Sha256, identity.Sha256);
            Assert.Equal("Identified.exe", identity.FileName);
        }

        #endregion
    }
}
