<?php
/**
 * Plugin Name:       AI WordPress Copilot
 * Plugin URI:        https://example.com/ai-wordpress-copilot
 * Description:       AI WordPress Copilot — یک دستیار هوش مصنوعی واقعی برای مدیریت، طراحی، سئو و محتوای سایت وردپرسی. (AI agent with real tools, site context, memory, SEO and safe execution.)
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            AIWC Studio
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       ai-wordpress-copilot
 * Domain Path:       /languages
 *
 * @package AIWC
 */

defined( 'ABSPATH' ) || exit;

define( 'AIWC_VERSION', '1.0.0' );
define( 'AIWC_FILE', __FILE__ );
define( 'AIWC_PATH', plugin_dir_path( __FILE__ ) );
define( 'AIWC_URL', plugin_dir_url( __FILE__ ) );
define( 'AIWC_DB_VERSION', '1.1.0' );

require_once AIWC_PATH . 'includes/class-autoloader.php';
AIWC\Autoloader::register();

register_activation_hook( __FILE__, array( 'AIWC\\Activator', 'activate' ) );
register_deactivation_hook( __FILE__, array( 'AIWC\\Deactivator', 'deactivate' ) );

/**
 * Main instance accessor.
 *
 * @return AIWC\Plugin
 */
function aiwc(): AIWC\Plugin {
	return AIWC\Plugin::instance();
}

add_action( 'plugins_loaded', 'aiwc', 5 );
