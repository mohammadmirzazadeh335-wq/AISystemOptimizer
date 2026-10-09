using System;
using System.Threading;
using System.Threading.Tasks;

namespace AISystemOptimizer.Core.Utilities
{
    /// <summary>
    /// Runs an external read (WMI query, performance-counter access, anything that talks to a
    /// Windows subsystem) with a hard time limit.
    ///
    /// Why this class exists (bug found on a real machine, v1.0.0):
    /// <c>ManagementObjectSearcher.Get()</c> and performance-counter creation have NO timeout.
    /// On a machine whose WMI repository or counter store is busy or corrupt, a single call can
    /// block for minutes or forever. Version 1.0.0 called them directly - including from the
    /// dashboard's two-second timer, on the UI thread - so the whole window could freeze while
    /// "gathering system information", exactly as a user reported.
    ///
    /// The contract here: the read runs on a worker thread; when the limit expires the caller
    /// gets the fallback value immediately and the machine carries on with that reading shown
    /// as unavailable. The abandoned worker is left behind on purpose - one leaked background
    /// thread waiting inside a broken Windows subsystem is the price of keeping the UI alive,
    /// and it is recorded so the log (and the tests) can tell it happened.
    /// </summary>
    public static class BoundedReader
    {
        private static int _abandonedReads;
        private static string _lastAbandonedSource = string.Empty;
        private static readonly object SourceLock = new object();

        /// <summary>How many reads have been abandoned since the process started.</summary>
        public static int AbandonedReads => Volatile.Read(ref _abandonedReads);

        /// <summary>The source name of the most recent abandoned read (empty when none).</summary>
        public static string LastAbandonedSource
        {
            get { lock (SourceLock) return _lastAbandonedSource; }
        }

        /// <summary>
        /// Run <paramref name="read"/> with a time limit and return its value.
        /// Returns <paramref name="fallback"/> when the read times out or throws.
        /// </summary>
        public static T Read<T>(Func<T> read, T fallback, int timeoutMs, string source)
        {
            if (read == null) return fallback;
            if (timeoutMs <= 0) timeoutMs = 1;

            try
            {
                var task = Task.Run(read);

                if (task.Wait(timeoutMs))
                    return task.Result;

                RecordAbandonment(source);
            }
            catch (AggregateException)
            {
                // The read threw; the fallback below is the honest answer.
            }
            catch (Exception)
            {
                // Task.Wait itself failing for another reason is also "no reading".
            }

            return fallback;
        }

        /// <summary>
        /// Run an action (a read with side effects into a caller-owned collection) with a time limit.
        /// Returns true when it finished inside the limit.
        /// </summary>
        public static bool TryRun(Action work, int timeoutMs, string source)
        {
            if (work == null) return false;
            if (timeoutMs <= 0) timeoutMs = 1;

            try
            {
                var task = Task.Run(work);

                if (task.Wait(timeoutMs))
                    return true;

                RecordAbandonment(source);
            }
            catch (AggregateException)
            {
            }
            catch (Exception)
            {
            }

            return false;
        }

        private static void RecordAbandonment(string source)
        {
            Interlocked.Increment(ref _abandonedReads);

            lock (SourceLock)
            {
                _lastAbandonedSource = source ?? string.Empty;
            }
        }
    }
}
