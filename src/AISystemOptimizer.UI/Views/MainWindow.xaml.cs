using System;
using System.ComponentModel;
using System.Windows;
using System.Windows.Input;
using AISystemOptimizer.UI.ViewModels;

namespace AISystemOptimizer.UI.Views
{
    /// <summary>
    /// Code-behind for the shell window. Kept intentionally thin: everything of substance lives in
    /// <see cref="MainViewModel"/> so the window chrome behaviour is the only concern here.
    /// </summary>
    public partial class MainWindow : Window
    {
        public MainWindow()
        {
            InitializeComponent();

            StateChanged += MainWindow_StateChanged;
            Closing += MainWindow_Closing;
        }

        #region Window chrome

        private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            if (e.ClickCount == 2)
            {
                ToggleMaximize();
                return;
            }

            if (e.ButtonState == MouseButtonState.Pressed)
            {
                try
                {
                    DragMove();
                }
                catch
                {
                    // DragMove throws when the mouse button is already released - harmless.
                }
            }
        }

        private void MinimizeButton_Click(object sender, RoutedEventArgs e)
        {
            WindowState = WindowState.Minimized;
        }

        private void MaximizeButton_Click(object sender, RoutedEventArgs e)
        {
            ToggleMaximize();
        }

        private void CloseButton_Click(object sender, RoutedEventArgs e)
        {
            Close();
        }

        private void ToggleMaximize()
        {
            WindowState = WindowState == WindowState.Maximized
                ? WindowState.Normal
                : WindowState.Maximized;
        }

        private void MainWindow_StateChanged(object? sender, EventArgs e)
        {
            // The template trigger removes the rounded corners when maximised (see MainWindow.xaml),
            // so there is nothing extra to do here - kept for future custom chrome work.
        }

        #endregion

        #region Closing

        private void MainWindow_Closing(object? sender, CancelEventArgs e)
        {
            if (DataContext is not MainViewModel viewModel)
                return;

            if (viewModel.HasUnsavedChanges)
            {
                var result = MessageBox.Show(
                    "There are unsaved changes. Close anyway?",
                    "AI System Optimizer",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Warning);

                if (result == MessageBoxResult.No)
                {
                    e.Cancel = true;
                    return;
                }
            }

            // Persist configuration and stop the timers before shutting down.
            try
            {
                viewModel.Dispose();
            }
            catch { }
        }

        #endregion
    }
}
