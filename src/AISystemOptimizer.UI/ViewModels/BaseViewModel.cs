using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows.Input;
using AISystemOptimizer.Core.Utilities;

namespace AISystemOptimizer.UI.ViewModels
{
    /// <summary>
    /// Base class for every view model: property change notification, a busy flag and
    /// command helpers. Deliberately dependency free (no MVVM framework required).
    /// </summary>
    public abstract class BaseViewModel : INotifyPropertyChanged, IDisposable
    {
        private bool _isBusy;
        private string _busyMessage = string.Empty;
        private string _errorMessage = string.Empty;
        private bool _isDisposed;

        protected BaseViewModel(ILogger? logger = null)
        {
            Logger = logger ?? LoggerFactory.GetLogger();
        }

        /// <summary>Shared logger.</summary>
        protected ILogger Logger { get; }

        /// <summary>Raised when a bound property changes.</summary>
        public event PropertyChangedEventHandler? PropertyChanged;

        /// <summary>True while a long running operation is in progress (drives progress UI).</summary>
        public bool IsBusy
        {
            get => _isBusy;
            protected set => SetProperty(ref _isBusy, value);
        }

        /// <summary>Text shown next to the busy indicator.</summary>
        public string BusyMessage
        {
            get => _busyMessage;
            protected set => SetProperty(ref _busyMessage, value);
        }

        /// <summary>Last error, shown in the status bar. Empty when there is none.</summary>
        public string ErrorMessage
        {
            get => _errorMessage;
            set
            {
                if (SetProperty(ref _errorMessage, value))
                    OnPropertyChanged(nameof(HasError));
            }
        }

        /// <summary>True when <see cref="ErrorMessage"/> is not empty.</summary>
        public bool HasError => !string.IsNullOrEmpty(ErrorMessage);

        /// <summary>Raised when a child view model wants to navigate.</summary>
        public event EventHandler<string>? NavigationRequested;

        /// <summary>Request navigation to another page.</summary>
        protected void RequestNavigation(string pageKey)
        {
            NavigationRequested?.Invoke(this, pageKey);
        }

        #region Property helpers

        /// <summary>Set a field and raise <see cref="PropertyChanged"/> when it changed.</summary>
        protected bool SetProperty<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
        {
            if (EqualityComparer<T>.Default.Equals(field, value))
                return false;

            field = value;
            OnPropertyChanged(propertyName);
            return true;
        }

        /// <summary>Raise <see cref="PropertyChanged"/>.</summary>
        protected void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }

        #endregion

        #region Busy / error helpers

        /// <summary>
        /// Run an operation with the busy flag set, capturing errors into
        /// <see cref="ErrorMessage"/> instead of letting them crash the app.
        /// </summary>
        protected async Task RunGuardedAsync(string busyMessage, Func<Task> operation)
        {
            if (IsBusy) return;

            try
            {
                IsBusy = true;
                BusyMessage = busyMessage;
                ErrorMessage = string.Empty;

                await operation();
            }
            catch (OperationCanceledException)
            {
                ErrorMessage = "Operation cancelled.";
            }
            catch (Exception ex)
            {
                Logger.Error(GetType().Name, $"Operation failed: {busyMessage}", null, ex);
                ErrorMessage = $"Operation failed safely: {ex.Message}";
            }
            finally
            {
                IsBusy = false;
                BusyMessage = string.Empty;
            }
        }

        #endregion

        #region IDisposable

        /// <summary>Dispose managed resources (override in derived classes).</summary>
        public void Dispose()
        {
            if (_isDisposed) return;
            _isDisposed = true;

            Dispose(true);
            GC.SuppressFinalize(this);
        }

        protected virtual void Dispose(bool disposing)
        {
        }

        #endregion

        #region Commands

        /// <summary>Synchronous command.</summary>
        public sealed class RelayCommand : ICommand
        {
            private readonly Action _execute;
            private readonly Func<bool>? _canExecute;

            public RelayCommand(Action execute, Func<bool>? canExecute = null)
            {
                _execute = execute ?? throw new ArgumentNullException(nameof(execute));
                _canExecute = canExecute;
            }

            public bool CanExecute(object? parameter) => _canExecute?.Invoke() ?? true;

            public void Execute(object? parameter) => _execute();

            public event EventHandler? CanExecuteChanged
            {
                add => CommandManager.RequerySuggested += value;
                remove => CommandManager.RequerySuggested -= value;
            }

            /// <summary>
            /// Ask WPF to re-evaluate every command. Synchronous commands are wired to
            /// CommandManager.RequerySuggested, so this is the way to force an immediate refresh
            /// when application state changed outside of user input.
            /// </summary>
            public void RaiseCanExecuteChanged() => CommandManager.InvalidateRequerySuggested();
        }

        /// <summary>Synchronous command taking a parameter.</summary>
        public sealed class RelayCommand<T> : ICommand
        {
            private readonly Action<T?> _execute;
            private readonly Func<T?, bool>? _canExecute;

            public RelayCommand(Action<T?> execute, Func<T?, bool>? canExecute = null)
            {
                _execute = execute ?? throw new ArgumentNullException(nameof(execute));
                _canExecute = canExecute;
            }

            public bool CanExecute(object? parameter)
            {
                if (_canExecute == null) return true;
                return _canExecute(ConvertParameter(parameter));
            }

            public void Execute(object? parameter) => _execute(ConvertParameter(parameter));

            private static T? ConvertParameter(object? parameter)
            {
                if (parameter is T typed) return typed;
                return default;
            }

            public event EventHandler? CanExecuteChanged
            {
                add => CommandManager.RequerySuggested += value;
                remove => CommandManager.RequerySuggested -= value;
            }
        }

        /// <summary>Asynchronous command that disables itself while running.</summary>
        public sealed class AsyncRelayCommand : ICommand
        {
            private readonly Func<Task> _execute;
            private readonly Func<bool>? _canExecute;
            private readonly ILogger? _logger;
            private bool _isRunning;

            public AsyncRelayCommand(
                Func<Task> execute,
                Func<bool>? canExecute = null,
                ILogger? logger = null)
            {
                _execute = execute ?? throw new ArgumentNullException(nameof(execute));
                _canExecute = canExecute;
                _logger = logger;
            }

            /// <summary>Last exception raised by the command, for diagnostics in the UI.</summary>
            public Exception? LastError { get; private set; }

            public bool CanExecute(object? parameter)
            {
                return !_isRunning && (_canExecute?.Invoke() ?? true);
            }

            /// <summary>
            /// Run the command.
            ///
            /// <see cref="ICommand.Execute"/> is a void contract, so this method is necessarily
            /// `async void` - which means an exception escaping it would be raised on the UI
            /// synchronisation context with no caller to catch it, tearing down the process. Every
            /// path is therefore wrapped: the command can fail, but it cannot take the application
            /// down with it, and the failure is logged with full context.
            /// </summary>
            public async void Execute(object? parameter)
            {
                if (!CanExecute(parameter))
                    return;

                try
                {
                    _isRunning = true;
                    RaiseCanExecuteChanged();
                    await _execute().ConfigureAwait(true);
                }
                catch (OperationCanceledException)
                {
                    // A cancelled operation is a normal outcome, not an error.
                    _logger?.Info("AsyncRelayCommand", "Command cancelled by the user.");
                }
                catch (Exception ex)
                {
                    LastError = ex;
                    _logger?.Error("AsyncRelayCommand",
                        $"Unhandled error in command '{_execute.Method.Name}'.", null, ex);
                }
                finally
                {
                    _isRunning = false;
                    RaiseCanExecuteChanged();
                }
            }

            public event EventHandler? CanExecuteChanged;

            public void RaiseCanExecuteChanged() =>
                CanExecuteChanged?.Invoke(this, EventArgs.Empty);
        }

        #endregion
    }
}
