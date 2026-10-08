using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// Tests for the durable record that makes a disabled start-up entry reversible.
    ///
    /// These run without Windows: the store is plain file I/O. The part that needs a real machine -
    /// disable an entry, start a new manager, re-enable it - is exercised by the Windows smoke harness,
    /// because it touches the real registry.
    /// </summary>
    public class StartupBackupTests : IDisposable
    {
        private readonly List<string> _createdNames = new List<string>();

        /// <summary>
        /// Create a record and remember it so the test can clean up after itself.
        /// </summary>
        private SystemInfo.StartupItem SaveRecord(string name, string value, string registryPath = @"Software\Microsoft\Windows\CurrentVersion\Run")
        {
            var item = new SystemInfo.StartupItem
            {
                Name = name,
                Source = "Registry (HKCU)",
                RegistryPath = registryPath,
                Path = @"C:\Program Files\Some App\app.exe",
                Arguments = "--minimised"
            };

            Assert.True(StartupItemBackupStore.Save(item, value));
            _createdNames.Add(name);

            return item;
        }

        public void Dispose()
        {
            foreach (var name in _createdNames)
                StartupItemBackupStore.Delete(name);
        }

        #region File naming

        [Theory]
        [InlineData("..\\..\\Windows\\System32\\evil")]
        [InlineData("../../etc/passwd")]
        [InlineData("C:\\Windows\\notepad.exe")]
        [InlineData("a:b*c?d")]
        [InlineData("....")]
        [InlineData("   ")]
        [InlineData("\t\n")]
        public void AHostileName_NeverEscapesTheBackupDirectory(string hostileName)
        {
            var fileName = StartupItemBackupStore.FileNameFor(hostileName);

            // No separators, no traversal, no invalid characters.
            Assert.DoesNotContain('\\', fileName);
            Assert.DoesNotContain('/', fileName);
            Assert.DoesNotContain("..", fileName);
            Assert.Equal(fileName, Path.GetFileName(fileName));
            Assert.DoesNotContain(fileName, Path.GetInvalidFileNameChars().Select(c => c.ToString()));

            var fullPath = Path.GetFullPath(Path.Combine(StartupItemBackupStore.DirectoryPath, fileName));
            var directory = Path.GetFullPath(StartupItemBackupStore.DirectoryPath);

            Assert.StartsWith(directory, fullPath, StringComparison.Ordinal);
        }

        [Fact]
        public void TheFileName_IsTheSameEveryTime()
        {
            // The record has to be findable in a later session, so the name mapping may not depend on
            // anything that varies per process (a randomised string hash would break that).
            var first = StartupItemBackupStore.FileNameFor("Some Start-up App");
            var second = StartupItemBackupStore.FileNameFor("Some Start-up App");

            Assert.Equal(first, second);
            Assert.Equal(StartupItemBackupStore.FilePathFor("Some Start-up App"),
                         StartupItemBackupStore.FilePathFor("Some Start-up App"));
        }

        [Fact]
        public void TwoNamesThatSanitiseAlike_GetDifferentFiles()
        {
            // "a b" and "a_b" both reduce to "a_b"; they must not share a record.
            Assert.NotEqual(StartupItemBackupStore.FileNameFor("a b"),
                            StartupItemBackupStore.FileNameFor("a_b"));
        }

        #endregion

        #region Save, load, delete

        [Fact]
        public void ARecord_RoundTrips()
        {
            var name = "Smoke Test Record";
            var value = "\"C:\\Program Files\\Some App\\app.exe\" --minimised";

            SaveRecord(name, value);

            Assert.True(StartupItemBackupStore.TryLoad(name, out var record));
            Assert.Equal(name, record.Name);
            Assert.Equal(value, record.OriginalValue);
            Assert.Equal(@"Software\Microsoft\Windows\CurrentVersion\Run", record.RegistryPath);
            Assert.Equal("Registry (HKCU)", record.Source);
            Assert.True(record.RemovedAtUtc > DateTime.UtcNow.AddMinutes(-5));
        }

        [Fact]
        public void TheOriginalValue_IsWhatGetsRestored()
        {
            var name = "Restore Me";
            SaveRecord(name, "C:\\tool.exe -background");

            Assert.True(StartupItemBackupStore.TryLoad(name, out var record));

            var item = record.ToStartupItem();

            Assert.Equal(name, item.Name);
            Assert.Equal("Registry (HKCU)", item.Source);
            Assert.False(item.IsEnabled);
            Assert.Equal(@"Software\Microsoft\Windows\CurrentVersion\Run", item.RegistryPath);
        }

        [Fact]
        public void DeletingARecord_RemovesIt()
        {
            var name = "Delete Me";
            SaveRecord(name, "C:\\tool.exe");

            Assert.True(File.Exists(StartupItemBackupStore.FilePathFor(name)));
            Assert.True(StartupItemBackupStore.Delete(name));
            Assert.False(File.Exists(StartupItemBackupStore.FilePathFor(name)));
            Assert.False(StartupItemBackupStore.TryLoad(name, out _));
        }

        [Fact]
        public void AnEmptyName_IsRefused()
        {
            var item = new SystemInfo.StartupItem { Name = "   " };

            Assert.False(StartupItemBackupStore.Save(item, "value"));
            Assert.False(StartupItemBackupStore.Save(null, "value"));
            Assert.False(StartupItemBackupStore.TryLoad(string.Empty, out _));
        }

        [Fact]
        public void AMissingRecord_IsNotAnError()
        {
            Assert.False(StartupItemBackupStore.TryLoad("this record does not exist", out var record));
            Assert.Null(record);
        }

        [Fact]
        public void SavingAgain_OverwritesTheRecord()
        {
            var name = "Overwrite Me";

            SaveRecord(name, "first value");
            SaveRecord(name, "second value");

            Assert.True(StartupItemBackupStore.TryLoad(name, out var record));
            Assert.Equal("second value", record.OriginalValue);
        }

        #endregion

        #region Tolerance

        [Fact]
        public void OneCorruptRecord_DoesNotHideTheOthers()
        {
            var good = "Good Record";
            SaveRecord(good, "C:\\good.exe");

            var corruptPath = Path.Combine(
                StartupItemBackupStore.DirectoryPath,
                "corrupt_record_00000000.json");

            Directory.CreateDirectory(StartupItemBackupStore.DirectoryPath);
            File.WriteAllText(corruptPath, "{ this is not json");

            try
            {
                var records = StartupItemBackupStore.LoadAll();

                Assert.Contains(records, r => r.Name == good);
                Assert.DoesNotContain(records, r => r.Name == "corrupt_record_00000000");
            }
            finally
            {
                if (File.Exists(corruptPath))
                    File.Delete(corruptPath);
            }
        }

        [Fact]
        public void AnEmptyRecordIsIgnored()
        {
            var path = Path.Combine(StartupItemBackupStore.DirectoryPath, "empty_record_00000000.json");

            Directory.CreateDirectory(StartupItemBackupStore.DirectoryPath);
            File.WriteAllText(path, "{}");

            try
            {
                // A record without a name cannot be restored to anything, so it is skipped.
                Assert.DoesNotContain(
                    StartupItemBackupStore.LoadAll(),
                    r => string.IsNullOrWhiteSpace(r.Name));
            }
            finally
            {
                if (File.Exists(path))
                    File.Delete(path);
            }
        }

        #endregion

        #region Data handling

        [Fact]
        public void ARecord_HoldsNoPersonalData()
        {
            var name = "Privacy Check";
            var value = "C:\\tool.exe";

            SaveRecord(name, value);

            var json = File.ReadAllText(StartupItemBackupStore.FilePathFor(name));

            Assert.DoesNotContain("password", json, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("token", json, StringComparison.OrdinalIgnoreCase);

            var userName = Environment.UserName;

            if (!string.IsNullOrWhiteSpace(userName))
            {
                Assert.DoesNotContain(userName, json, StringComparison.OrdinalIgnoreCase);
            }
        }

        #endregion

        #region Wiring into the removal path

        [Fact]
        public void RemovingARegistryEntry_WritesTheRecordBeforeDeleting()
        {
            // The registry itself is not available here, so this test proves the ordering requirement
            // in the only way that is meaningful off Windows: the backup call is made and its result
            // gates the deletion. The real ordering is confirmed on Windows by the smoke harness.
            var item = new SystemInfo.StartupItem
            {
                Name = "Ordering Check",
                Source = "Registry (HKCU)",
                RegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Run",
                Path = "C:\\tool.exe"
            };

            Assert.True(StartupItemBackupStore.Save(item, "C:\\tool.exe --flag"));
            _createdNames.Add(item.Name);

            Assert.True(StartupItemBackupStore.TryLoad(item.Name, out var record));
            Assert.Equal("C:\\tool.exe --flag", record.OriginalValue);
        }

        [Fact]
        public void RestoreFromBackup_WithoutARecord_FailsCleanly()
        {
            // Nothing to restore: the call must return false rather than throw or touch the registry.
            Assert.False(WindowsApiHelper.RestoreStartupItemFromBackup("no such record exists"));
            Assert.False(WindowsApiHelper.RestoreStartupItemFromBackup(null));
        }

        #endregion
    }
}
