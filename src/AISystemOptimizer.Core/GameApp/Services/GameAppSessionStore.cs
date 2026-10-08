using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using AISystemOptimizer.Core.Constants;
using AISystemOptimizer.Core.GameApp.Models;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.Core.GameApp.Services
{
    /// <summary>
    /// Durable storage for optimisation sessions.
    ///
    /// Two separate things are stored, because they have different lifetimes:
    ///   * Open sessions - one small file per session, written before the first change and deleted only
    ///     after the session has been closed and its restore verified. Their existence *is* the crash
    ///     detection: a file for a session that this process is not running means the optimiser stopped
    ///     while that session was live.
    ///   * History - the completed sessions, appended to one file that is trimmed, so the History view
    ///     has something to show.
    ///
    /// The same discipline as the profile store: write to a temporary file, keep a backup of the previous
    /// good file, and quarantine anything unreadable with a written reason rather than deleting it.
    /// </summary>
    public sealed class GameAppSessionStore
    {
        private const int MaxOpenSessionBytes = 512 * 1024;

        private readonly ILogger _logger;
        private readonly string _openDirectory;
        private readonly string _historyPath;

        public GameAppSessionStore(ILogger? logger = null, string? directory = null)
        {
            _logger = logger ?? LoggerFactory.GetLogger();

            var root = string.IsNullOrWhiteSpace(directory)
                ? Path.Combine(AppConstants.AppDataPath, AppConstants.GameAppDirectoryName)
                : directory!;

            _openDirectory = Path.Combine(root, "sessions", "open");
            _historyPath = Path.Combine(root, "sessions", "history.json");
        }

        public string OpenSessionDirectory => _openDirectory;

        public string HistoryPath => _historyPath;

        public IReadOnlyList<string> LoadProblems { get; private set; } = Array.Empty<string>();

        #region Open sessions

        /// <summary>
        /// Record a session as started, before the first change is made. This is what makes an interrupted
        /// session visible on the next start.
        /// </summary>
        public bool SaveOpen(GameAppSession session)
        {
            if (session == null || session.SessionId == Guid.Empty)
                return false;

            try
            {
                Directory.CreateDirectory(_openDirectory);

                var target = PathForOpen(session.SessionId);
                var temporary = target + ".tmp";

                File.WriteAllText(temporary, JsonSerializer.Serialize(session, GameAppSession.JsonOptions));

                if (File.Exists(target))
                    File.Delete(target);

                File.Move(temporary, target);

                return File.Exists(target);
            }
            catch (Exception exception)
            {
                _logger.Error("GameAppSessionStore",
                    $"The session record for '{session.ApplicationName}' could not be written", null, exception);

                // Without the record, a crash would leave no trace of the changes. The caller refuses to
                // start a session when this fails.
                return false;
            }
        }

        /// <summary>
        /// Close a session: remove its open record and append it to the history.
        /// </summary>
        public bool CloseSession(GameAppSession session)
        {
            if (session == null)
                return false;

            try
            {
                session.IsOpen = false;
                session.EndTimeUtc ??= DateTime.UtcNow;

                var open = PathForOpen(session.SessionId);

                if (File.Exists(open))
                    File.Delete(open);

                return AppendToHistory(session);
            }
            catch (Exception exception)
            {
                _logger.Error("GameAppSessionStore",
                    $"The session record for '{session.ApplicationName}' could not be closed", null, exception);

                return false;
            }
        }

        /// <summary>
        /// Every session that was left open. On a normal start this is empty; anything in it was
        /// interrupted.
        /// </summary>
        public List<GameAppSession> LoadOpenSessions()
        {
            var problems = new List<string>();
            var sessions = new List<GameAppSession>();

            try
            {
                if (!Directory.Exists(_openDirectory))
                {
                    LoadProblems = problems;
                    return sessions;
                }

                foreach (var file in Directory.GetFiles(_openDirectory, "*.json"))
                {
                    try
                    {
                        var info = new FileInfo(file);

                        if (info.Length == 0 || info.Length > MaxOpenSessionBytes)
                        {
                            problems.Add($"{Path.GetFileName(file)} has an unexpected size " +
                                         $"({info.Length} bytes) and was not read.");
                            continue;
                        }

                        var session = JsonSerializer.Deserialize<GameAppSession>(
                            File.ReadAllText(file), GameAppSession.JsonOptions);

                        if (session == null || session.SessionId == Guid.Empty)
                        {
                            problems.Add($"{Path.GetFileName(file)} did not contain a usable session.");
                            continue;
                        }

                        session.WasInterrupted = true;
                        sessions.Add(session);
                    }
                    catch (JsonException exception)
                    {
                        problems.Add($"{Path.GetFileName(file)} is not valid JSON: {exception.Message}");
                    }
                    catch (IOException exception)
                    {
                        problems.Add($"{Path.GetFileName(file)} could not be read: {exception.Message}");
                    }
                }
            }
            catch (Exception exception)
            {
                problems.Add($"The open-session directory could not be read: {exception.Message}");
            }

            LoadProblems = problems;

            foreach (var problem in problems)
                _logger.Warning("GameAppSessionStore", problem);

            return sessions;
        }

        private string PathForOpen(Guid sessionId) =>
            Path.Combine(_openDirectory, $"{sessionId:D}.json");

        #endregion

        #region History

        public List<GameAppSession> LoadHistory(int maximum = 200)
        {
            var history = new List<GameAppSession>();

            try
            {
                if (!File.Exists(_historyPath))
                    return history;

                var info = new FileInfo(_historyPath);

                if (info.Length == 0 || info.Length > 8 * 1024 * 1024)
                {
                    _logger.Warning("GameAppSessionStore",
                        $"The session history file has an unexpected size ({info.Length} bytes) and was not read.");
                    return history;
                }

                var sessions = JsonSerializer.Deserialize<List<GameAppSession>>(
                    File.ReadAllText(_historyPath), GameAppSession.JsonOptions);

                if (sessions != null)
                    history.AddRange(sessions.Where(s => s != null));

                if (history.Count > maximum)
                    history = history.OrderByDescending(s => s.StartTimeUtc).Take(maximum).ToList();
            }
            catch (Exception exception)
            {
                _logger.Warning("GameAppSessionStore",
                    $"The session history could not be read: {exception.Message}");

                // A damaged history must not stop the feature; the open sessions - the ones that matter for
                // safety - are stored separately for exactly this reason.
                QuarantineHistory(exception.Message);
            }

            return history;
        }

        private bool AppendToHistory(GameAppSession session)
        {
            var history = LoadHistory(maximum: 500);

            history.RemoveAll(s => s.SessionId == session.SessionId);
            history.Insert(0, session);

            history = history.OrderByDescending(s => s.StartTimeUtc).Take(200).ToList();

            try
            {
                var directory = Path.GetDirectoryName(_historyPath);

                if (!string.IsNullOrEmpty(directory))
                    Directory.CreateDirectory(directory);

                var temporary = _historyPath + ".tmp";

                File.WriteAllText(temporary, JsonSerializer.Serialize(history, GameAppSession.JsonOptions));

                if (File.Exists(_historyPath))
                {
                    try
                    {
                        File.Copy(_historyPath, AppConfig.BackupPathFor(_historyPath), overwrite: true);
                    }
                    catch
                    {
                        // The previous history is still readable until the move below replaces it.
                    }

                    File.Delete(_historyPath);
                }

                File.Move(temporary, _historyPath);

                return true;
            }
            catch (Exception exception)
            {
                _logger.Error("GameAppSessionStore", "The session history could not be written", null, exception);
                return false;
            }
        }

        private void QuarantineHistory(string reason)
        {
            try
            {
                var target = _historyPath + ".invalid";

                if (File.Exists(target))
                    File.Delete(target);

                File.Move(_historyPath, target);

                File.WriteAllText(target + ".reason.txt", $"Reason: {reason}{Environment.NewLine}");
            }
            catch
            {
                // Nothing further can be done with an unreadable file.
            }
        }

        #endregion
    }
}
