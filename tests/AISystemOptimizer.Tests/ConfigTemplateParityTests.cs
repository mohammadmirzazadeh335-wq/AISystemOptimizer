using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using AISystemOptimizer.Core.Models;
using Xunit;

namespace AISystemOptimizer.Tests
{
    /// <summary>
    /// The code and the shipped configuration file must describe the same set of settings.
    ///
    /// This test exists because they did not. `allowRemoteAiServer` was added to <see cref="AppConfig"/>
    /// and enforced in both AI clients, but never added to the template, so a user editing the template
    /// had no way to discover the setting and a reader of the template had no way to know it existed.
    /// Nothing failed, because nothing was checking. This is the check.
    ///
    /// The rule is one-directional on purpose: every setting the code exposes must be present in the
    /// template, so that the file documents the whole surface. The template may contain a key the code
    /// has not heard of - it is ignored on load, which is also worth knowing - but that is reported by
    /// the sibling test rather than by this one.
    /// </summary>
    public class ConfigTemplateParityTests
    {
        /// <summary>
        /// Settings that are deliberately absent from the template, each with the reason.
        /// </summary>
        private static readonly IReadOnlyDictionary<string, string> IntentionallyAbsent =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                // The template version is metadata that the loader writes, not a setting a user edits.
                { "Version", "written by the loader to record the file's schema version" }
            };

        private static string TemplatePath(string fileName) =>
            Path.Combine(AppContext.BaseDirectory, fileName);

        /// <summary>
        /// The keys of a configuration file, tolerant of the JSONC comments the template uses.
        /// </summary>
        private static List<string> ReadKeys(string path)
        {
            var text = StripComments(File.ReadAllText(path));

            using var document = JsonDocument.Parse(text);

            return document.RootElement.EnumerateObject()
                .Select(property => property.Name)
                .ToList();
        }

        /// <summary>
        /// Remove // comments without touching the inside of a string value. A naive removal would
        /// truncate "http://localhost:11434" and this helper exists so that no test has to guess.
        /// </summary>
        private static string StripComments(string text)
        {
            var builder = new StringBuilder(text.Length);
            var inString = false;

            for (var i = 0; i < text.Length; i++)
            {
                var character = text[i];

                if (inString)
                {
                    builder.Append(character);

                    if (character == '\\' && i + 1 < text.Length)
                    {
                        builder.Append(text[i + 1]);
                        i++;
                        continue;
                    }

                    if (character == '"')
                        inString = false;

                    continue;
                }

                if (character == '"')
                {
                    inString = true;
                    builder.Append(character);
                    continue;
                }

                if (character == '/' && i + 1 < text.Length && text[i + 1] == '/')
                {
                    while (i < text.Length && text[i] != '\n')
                        i++;

                    continue;
                }

                builder.Append(character);
            }

            return builder.ToString();
        }

        /// <summary>
        /// Names of every setting the code exposes as a readable, writable instance property, under the
        /// name it carries in the file - which is not always the property name (a property may declare
        /// <c>JsonPropertyName</c>), and which is not a file setting at all when the property is marked
        /// <c>JsonIgnore</c>.
        /// </summary>
        private static List<string> PublicSettingNames()
        {
            var names = new List<string>();

            foreach (var property in typeof(AppConfig)
                .GetProperties(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
                .Where(p => p.CanRead && p.CanWrite))
            {
                if (property.GetCustomAttributes(typeof(System.Text.Json.Serialization.JsonIgnoreAttribute), true).Length > 0)
                    continue;

                var declaredName = property
                    .GetCustomAttributes(typeof(System.Text.Json.Serialization.JsonPropertyNameAttribute), true)
                    .OfType<System.Text.Json.Serialization.JsonPropertyNameAttribute>()
                    .Select(a => a.Name)
                    .FirstOrDefault();

                names.Add(declaredName ?? property.Name);
            }

            return names;
        }

        /// <summary>
        /// True when the file mentions the setting, whether as a key or in a comment.
        ///
        /// A setting whose built-in default is a long curated list (the list of known game executables,
        /// the list of applications Game Mode closes) is documented by naming it in a comment instead of
        /// writing 70 lines of default content twice. The file's own header already states the rule that
        /// makes this safe: a key that is not present keeps its built-in default, so naming the setting
        /// without writing it changes nothing - while writing it as an empty array would silently
        /// replace the default with nothing. Being mentioned is what makes it discoverable; adding the
        /// key is what makes it configurable.
        /// </summary>
        private static bool MentionsSetting(string fileText, string settingName)
        {
            return System.Text.RegularExpressions.Regex.IsMatch(
                fileText,
                $"(?<![A-Za-z0-9_]){System.Text.RegularExpressions.Regex.Escape(settingName)}(?![A-Za-z0-9_])",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        }

        [Theory]
        [InlineData("config.defaults.json")]
        [InlineData("config.template.json")]
        public void EverySettingInTheCode_AppearsInTheShippedFile(string fileName)
        {
            var path = TemplatePath(fileName);

            Assert.True(File.Exists(path), $"{fileName} was not copied next to the tests ({path}).");

            var fileText = File.ReadAllText(path);

            var missing = PublicSettingNames()
                .Where(name => !IntentionallyAbsent.ContainsKey(name))
                .Where(name => !MentionsSetting(fileText, name))
                .ToList();

            Assert.True(
                missing.Count == 0,
                $"{fileName} does not mention {missing.Count} setting(s) that the code exposes: " +
                $"{string.Join(", ", missing)}. A setting that exists in code but is nowhere in the " +
                "shipped file cannot be discovered by a user.");
        }

        [Theory]
        [InlineData("config.defaults.json")]
        [InlineData("config.template.json")]
        public void EveryKeyInTheShippedFile_IsUnderstoodByTheCode(string fileName)
        {
            var path = TemplatePath(fileName);

            var keys = ReadKeys(path);

            var known = PublicSettingNames().ToHashSet(StringComparer.OrdinalIgnoreCase);

            // Static state and nested types are not settings; only instance properties are compared.
            var unknown = keys
                .Where(key => !known.Contains(key))
                .ToList();

            Assert.True(
                unknown.Count == 0,
                $"{fileName} contains {unknown.Count} key(s) the configuration class does not define: " +
                $"{string.Join(", ", unknown)}. An unknown key is ignored when the file is loaded, which " +
                "means a typo silently does nothing.");
        }

        [Theory]
        [InlineData("config.defaults.json")]
        [InlineData("config.template.json")]
        public void TheShippedFiles_AreValidJson(string fileName)
        {
            var path = TemplatePath(fileName);

            // Both files must be parseable as JSON once comments are removed; the loader tolerates
            // comments, but a file that is not even valid JSON after stripping them is a mistake.
            var keys = ReadKeys(path);

            Assert.NotEmpty(keys);
        }

        [Theory]
        [InlineData("config.defaults.json")]
        [InlineData("config.template.json")]
        public void TheShippedFiles_KeepTheSafetyDefaults(string fileName)
        {
            var path = TemplatePath(fileName);
            var text = StripComments(File.ReadAllText(path));

            using var document = JsonDocument.Parse(text);

            var root = document.RootElement;

            Assert.True(root.GetProperty("safetyLayerEnabled").GetBoolean(),
                $"{fileName} switches the safety layer off.");

            Assert.False(root.GetProperty("allowHighRiskActions").GetBoolean(),
                $"{fileName} allows high-risk actions by default.");

            Assert.False(root.GetProperty("allowCriticalRiskActions").GetBoolean(),
                $"{fileName} allows critical-risk actions by default.");

            Assert.False(root.GetProperty("allowRemoteAiServer").GetBoolean(),
                $"{fileName} allows a remote AI server by default.");

            // The risk ceiling is written as a name, not a number: a file that a human reads must not
            // depend on enum ordinals.
            var ceiling = root.GetProperty("maxAutoRiskLevel").GetString();

            Assert.False(string.IsNullOrWhiteSpace(ceiling),
                $"{fileName} writes maxAutoRiskLevel as a number. It must be a readable name.");

            Assert.Contains(ceiling, new[] { "Low", "Medium", "High", "Critical" }, StringComparer.OrdinalIgnoreCase);
        }

        [Theory]
        [InlineData("config.defaults.json")]
        [InlineData("config.template.json")]
        public void ACuratedListInTheShippedFile_MatchesTheCodeDefault(string fileName)
        {
            // These two lists are the only settings whose shipped value is a long curated list rather
            // than a scalar. They are written out in full in both files, which means they can drift from
            // the code - and a drifting list changes behaviour, because a present key replaces the
            // built-in default while an absent one keeps it. So the values are compared, not just the
            // keys.
            var path = TemplatePath(fileName);
            var text = StripComments(File.ReadAllText(path));

            using var document = JsonDocument.Parse(text);

            var defaults = AppConfig.CreateDefault();

            foreach (var (key, expected) in new[]
            {
                ("knownGameExecutables", defaults.KnownGameExecutables),
                ("gameModeCloseList", defaults.GameModeCloseList)
            })
            {
                var shipped = document.RootElement.GetProperty(key)
                    .EnumerateArray()
                    .Select(item => item.GetString())
                    .ToList();

                Assert.Equal(expected.Count, shipped.Count);

                var differences = expected
                    .Where((value, index) => !string.Equals(value, shipped[index], StringComparison.Ordinal))
                    .ToList();

                Assert.True(differences.Count == 0,
                    $"{fileName}: '{key}' differs from the built-in default at {differences.Count} position(s): " +
                    $"{string.Join(", ", differences)}");
            }
        }

        [Fact]
        public void TheTwoShippedFiles_DescribeTheSameSettings()
        {
            var defaults = ReadKeys(TemplatePath("config.defaults.json"))
                .ToHashSet(StringComparer.OrdinalIgnoreCase);

            var template = ReadKeys(TemplatePath("config.template.json"))
                .ToHashSet(StringComparer.OrdinalIgnoreCase);

            var onlyInDefaults = defaults.Except(template).ToList();
            var onlyInTemplate = template.Except(defaults).ToList();

            Assert.True(onlyInDefaults.Count == 0 && onlyInTemplate.Count == 0,
                "The two shipped files have drifted apart. " +
                $"Only in config.defaults.json: {string.Join(", ", onlyInDefaults)}. " +
                $"Only in the commented template: {string.Join(", ", onlyInTemplate)}.");
        }
    }
}
