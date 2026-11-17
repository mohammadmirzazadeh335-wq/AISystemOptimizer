<?php
/**
 * Admin menu pages and asset loading.
 *
 * @package AIWC
 */

namespace AIWC\Admin;

use AIWC\Plugin;
use AIWC\Security\Permissions;
use AIWC\Settings;
use AIWC\I18n;

defined( 'ABSPATH' ) || exit;

/**
 * Registers the copilot admin panel (single-page app with hash routes).
 */
class Admin {

	/**
	 * Plugin instance.
	 *
	 * @var Plugin
	 */
	private $plugin;

	/**
	 * Constructor.
	 *
	 * @param Plugin $plugin Plugin instance.
	 */
	public function __construct( Plugin $plugin ) {
		$this->plugin = $plugin;
	}

	/**
	 * Register admin menus.
	 */
	public function register_menus() {
		add_menu_page(
			__( 'AI WordPress Copilot', 'ai-wordpress-copilot' ),
			__( 'AI Copilot', 'ai-wordpress-copilot' ),
			'manage_options',
			'aiwc-dashboard',
			array( $this, 'render_app' ),
			'dashicons-editor-code',
			3
		);

		// Hash-routed sub-pages so every spec page has its own menu entry.
		$pages = array(
			'aiwc-chat'      => __( 'AI Chat', 'ai-wordpress-copilot' ),
			'aiwc-tools'     => __( 'AI Tools', 'ai-wordpress-copilot' ),
			'aiwc-design'    => __( 'Site Design', 'ai-wordpress-copilot' ),
			'aiwc-seo'       => __( 'SEO', 'ai-wordpress-copilot' ),
			'aiwc-content'   => __( 'Content', 'ai-wordpress-copilot' ),
			'aiwc-logs'      => __( 'Activity Log', 'ai-wordpress-copilot' ),
			'aiwc-memory'    => __( 'AI Memory', 'ai-wordpress-copilot' ),
			'aiwc-api'       => __( 'API Connection', 'ai-wordpress-copilot' ),
			'aiwc-settings'  => __( 'Settings', 'ai-wordpress-copilot' ),
		);
		foreach ( $pages as $slug => $title ) {
			add_submenu_page(
				'aiwc-dashboard',
				$title,
				$title,
				'manage_options',
				$slug,
				array( $this, 'render_app' )
			);
		}
	}

	/**
	 * Render the SPA container; the JS app reads the current page slug.
	 */
	public function render_app() {
		if ( ! Permissions::current_user_can_manage() ) {
			wp_die( esc_html__( 'You do not have permission to access this page.', 'ai-wordpress-copilot' ) );
		}
		$screen = function_exists( 'get_current_screen' ) ? get_current_screen() : null;
		$slug   = $screen ? $screen->id : '';
		// Convert admin page hook to route: toplevel_page_aiwc-chat -> chat.
		$route = 'dashboard';
		if ( preg_match( '/aiwc-([a-z\-]+)$/', (string) $slug, $m ) ) {
			$route = str_replace( '-', '_', $m[1] );
		}
		echo '<div id="aiwc-app" class="aiwc-app" data-route="' . esc_attr( $route ) . '"><div class="aiwc-loading">' . esc_html__( 'Loading…', 'ai-wordpress-copilot' ) . '</div></div>';
	}

	/**
	 * Enqueue CSS/JS on our pages only.
	 *
	 * @param string $hook Current admin page hook.
	 */
	public function enqueue_assets( $hook ) {
		if ( false === strpos( $hook, 'aiwc-' ) && false === strpos( $hook, 'aiwc_dashboard' ) ) {
			return;
		}

		$version = AIWC_VERSION;

		wp_enqueue_style( 'aiwc-admin', AIWC_URL . 'assets/css/admin.css', array(), $version );

		wp_enqueue_script( 'aiwc-markdown', AIWC_URL . 'assets/js/markdown.js', array(), $version, true );
		wp_enqueue_script( 'aiwc-api', AIWC_URL . 'assets/js/api.js', array( 'aiwc-markdown' ), $version, true );
		wp_enqueue_script( 'aiwc-chat', AIWC_URL . 'assets/js/chat.js', array( 'aiwc-api' ), $version, true );
		wp_enqueue_script( 'aiwc-app', AIWC_URL . 'assets/js/app.js', array( 'aiwc-chat' ), $version, true );

		$settings = Settings::masked();
		wp_localize_script(
			'aiwc-api',
			'AIWC',
			array(
				'root'       => esc_url_raw( rest_url( \AIWC\Api\Api::NS ) ),
				'nonce'      => wp_create_nonce( 'wp_rest' ),
				'adminUrl'   => admin_url(),
				'siteUrl'    => home_url(),
				'version'    => AIWC_VERSION,
				'language'   => I18n::current_language(),
				'theme'      => (string) Settings::get( 'ui_theme', 'dark' ),
				'i18n'       => I18n::for_language( I18n::current_language() ),
				'i18nAll'    => I18n::strings(),
				'model'      => (string) Settings::get( 'model' ),
				'configured' => Settings::is_configured(),
				'settings'   => $settings,
				'route'      => isset( $_GET['page'] ) ? sanitize_key( wp_unslash( $_GET['page'] ) ) : 'aiwc-dashboard',
			)
		);
	}

	/**
	 * Admin notice when the API is not configured yet.
	 */
	public function maybe_config_notice() {
		if ( ! Permissions::current_user_can_manage() || Settings::is_configured() ) {
			return;
		}
		$screen = function_exists( 'get_current_screen' ) ? get_current_screen() : null;
		if ( $screen && false !== strpos( $screen->id, 'aiwc' ) ) {
			return;
		}
		$settings_url = admin_url( 'admin.php?page=aiwc-settings' );
		echo '<div class="notice notice-info"><p>';
		echo esc_html__( 'AI WordPress Copilot: configure your AI API connection to start using the assistant.', 'ai-wordpress-copilot' );
		printf( ' <a href="%s">%s</a>', esc_url( $settings_url ), esc_html__( 'Open settings', 'ai-wordpress-copilot' ) );
		echo '</p></div>';
	}
}
