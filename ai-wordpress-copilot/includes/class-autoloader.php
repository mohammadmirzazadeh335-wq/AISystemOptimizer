<?php
/**
 * PSR-4 style autoloader for the AIWC namespace.
 *
 * @package AIWC
 */

namespace AIWC;

defined( 'ABSPATH' ) || exit;

/**
 * Maps AIWC\Foo\Bar_Baz to includes/Foo/class-bar-baz.php.
 */
class Autoloader {

	/**
	 * Register the autoloader.
	 */
	public static function register() {
		spl_autoload_register( array( __CLASS__, 'load' ) );
	}

	/**
	 * Load a class file if it belongs to our namespace.
	 *
	 * @param string $class Fully qualified class name.
	 */
	public static function load( $class ) {
		if ( 0 !== strpos( $class, 'AIWC\\' ) ) {
			return;
		}

		$relative = substr( $class, strlen( 'AIWC\\' ) );
		$parts    = explode( '\\', $relative );
		$class_name = array_pop( $parts );

		$dir = AIWC_PATH . 'includes';
		foreach ( $parts as $part ) {
			$dir .= DIRECTORY_SEPARATOR . $part;
		}

		$file = $dir . DIRECTORY_SEPARATOR . 'class-' . str_replace( '_', '-', strtolower( $class_name ) ) . '.php';

		if ( is_readable( $file ) ) {
			require_once $file;
		}
	}
}
