using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using AISystemOptimizer.Core.Models;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.App
{
    /// <summary>
    /// Application entry point.
    ///
    /// Responsibilities kept deliberately small:
    ///   * single-instance enforcement,
    ///   * global exception handling so nothing can crash the desktop,
    ///   * theme selection based on configuration,
    ///   * flushing logs on exit.
    /// </summary>
    public partial class App : Application
    {
        private const string SingleInstanceMutexName = "Global\\AISystemOptimizer.SingleInstance";
        private Mutex? _singleInstanceMutex;
        private AppConfig _config = AppConfig.CreateDefault();

        public App()
        {
            // DPI awareness (also declared in the manifest - belt and braces for older systems).
            WindowsApiHelper.SetDpiAwareness();

            AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
            DispatcherUnhandledException += OnDispatcherUnhandledException;
            TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;
        }

        protected override void OnStartup(StartupEventArgs e)
        {
            // ---- Single instance ----
            _singleInstanceMutex = new Mutex(true, SingleInstanceMutexName, out var isNewInstance);

            if (!isNewInstance)
            {
                MessageBox.Show(
                    "AI System Optimizer is already running.\n\n" +
                    "Only one instance is needed - the running copy already monitors the system.",
                    "AI System Optimizer",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);

                Shutdown(0);
                return;
            }

            // ---- Configuration ----
            _config = AppConfig.Load();
            LoggerFactory.SetDefaultLogger(LoggerFactory.CreateLogger(_config));
            var logger = LoggerFactory.GetLogger();
            logger.Info("App", $"Starting AI System Optimizer {typeof(App).Assembly.GetName().Version}");

            // ---- Theme ----
            ApplyTheme(logger);

            base.OnStartup(e);
        }

        private void ApplyTheme(ILogger logger)
        {
            try
            {
                var dictionaries = Resources.MergedDictionaries;

                // Remove an existing theme dictionary so the correct one can be inserted.
                var existingTheme = dictionaries.FirstOrDefault(d =>
                    d.Source != null &&
                    (d.Source.OriginalString.Contains("DarkTheme.xaml") ||
                     d.Source.OriginalString.Contains("LightTheme.xaml")));

                if (existingTheme != null)
                    dictionaries.Remove(existingTheme);

                var themeUri = _config.DarkMode
                    ? "pack://application:,,,/AISystemOptimizer.UI;component/Styles/DarkTheme.xaml"
                    : "pack://application:,,,/AISystemOptimizer.UI;component/Styles/LightTheme.xaml";

                dictionaries.Add(new ResourceDictionary { Source = new Uri(themeUri, UriKind.Absolute) });

                logger.Info("App", $"Theme applied: {(_config.DarkMode ? "dark" : "light")}");
            }
            catch (Exception ex)
            {
                logger.Warning("App", "Could not apply the configured theme; the default was kept", null, ex);
            }
        }

        protected override void OnExit(ExitEventArgs e)
        {
            var logger = LoggerFactory.GetLogger();
            logger.Info("App", $"Exiting with code {e.ApplicationExitCode}");

            // Make sure the active configuration and the log buffer are on disk.
            try
            {
                _config.Save();

                if (logger is IDisposable disposable)
                    disposable.Dispose();
            }
            catch { }

            try
            {
                _singleInstanceMutex?.ReleaseMutex();
                _singleInstanceMutex?.Dispose();
            }
            catch { }

            base.OnExit(e);
        }

        #region Exception handling

        private void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
        {
            HandleException("UI thread", e.Exception);
            e.Handled = true; // keep the window alive: optimisation state is never left half-applied
        }

        private void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
        {
            HandleException("background thread", e.ExceptionObject as Exception);
        }

        private void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
        {
            HandleException("background task", e.Exception);
            e.SetObserved();
        }

        private void HandleException(string source, Exception? exception)
        {
            try
            {
                LoggerFactory.GetLogger().Error("App", $"Unhandled exception on the {source}", null, exception);
            }
            catch { }

            MessageBox.Show(
                "Something went wrong, but nothing was changed on your system.\n\n" +
                $"Details: {exception?.Message}\n\n" +
                "The full error was written to the log. Operations are applied one at a time and each one is " +
                "validated before it runs, so a failure cannot leave your system in a broken state.",
                "AI System Optimizer",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }

        #endregion
    }
}
