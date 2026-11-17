<?php
/**
 * Plugin settings container.
 *
 * @package AIWC
 */

namespace AIWC;

defined( 'ABSPATH' ) || exit;

/**
 * Reads and writes the aiwc_settings option with validation.
 */
class Settings {

	const OPTION = 'aiwc_settings';

	/**
	 * Default settings.
	 *
	 * @return array
	 */
	public static function defaults() {
		return array(
			// API connection.
			'api_key'         => '',
			'base_url'        => 'https://api.openai.com/v1',
			'model'           => 'gpt-4o-mini',
			'max_output_tokens' => 2048,
			'timeout'         => 60,
			'temperature'     => 0.7,
			'top_p'           => 1.0,
			'max_retries'     => 2,
			// Intelligence / accuracy (kept separate from sampling parameters).
			'analysis_strictness' => 3,   // 1..5.
			'creativity'          => 3,   // 1..5 (maps to extra sampling hints only when explicitly enabled).
			'autonomy_level'      => 2,   // 1..5.
			'context_detail'      => 3,   // 1..5.
			'max_steps'           => 8,
			'max_tools_per_request' => 8,
			'context_token_budget'  => 8000,
			'execution_mode'        => 2, // 1 analyze, 2 confirm, 3 auto low-risk, 4 step-confirm.
			'ui_language'           => 'fa',
			'ui_theme'              => 'dark',
		);
	}

	/**
	 * Get all settings merged with defaults.
	 *
	 * @return array
	 */
	public static function all() {
		$stored = get_option( self::OPTION, array() );
		if ( ! is_array( $stored ) ) {
			$stored = array();
		}
		return wp_parse_args( $stored, self::defaults() );
	}

	/**
	 * Get one setting.
	 *
	 * @param string $key Setting key.
	 * @param mixed  $fallback Fallback value.
	 * @return mixed
	 */
	public static function get( $key, $fallback = null ) {
		$all = self::all();
		return array_key_exists( $key, $all ) ? $all[ $key ] : $fallback;
	}

	/**
	 * Save settings (partial merge) with sanitization.
	 *
	 * @param array $input Raw input.
	 * @return array Sanitized settings.
	 */
	public static function save( array $input ) {
		$current = self::all();
		$clean   = $current;

		$string_keys = array( 'base_url', 'model', 'ui_language', 'ui_theme' );
		foreach ( $string_keys as $key ) {
			if ( isset( $input[ $key ] ) ) {
				$clean[ $key ] = sanitize_text_field( (string) $input[ $key ] );
			}
		}

		if ( isset( $input['api_key'] ) ) {
			$raw = trim( (string) $input['api_key'] );
			// Empty string keeps the existing key; explicit "[CLEAR]" removes it.
			if ( '[CLEAR]' === $raw ) {
				$clean['api_key'] = '';
			} elseif ( '' !== $raw ) {
				$clean['api_key'] = self::sanitize_key_value( $raw );
			}
		}

		if ( isset( $input['base_url'] ) && '' !== $input['base_url'] ) {
			$clean['base_url'] = self::sanitize_base_url( $clean['base_url'] );
		} else {
			$clean['base_url'] = self::sanitize_base_url( $clean['base_url'] );
		}

		$int_ranges = array(
			'max_output_tokens'      => array( 64, 128000 ),
			'timeout'                => array( 5, 600 ),
			'max_retries'            => array( 0, 5 ),
			'analysis_strictness'    => array( 1, 5 ),
			'creativity'             => array( 1, 5 ),
			'autonomy_level'         => array( 1, 5 ),
			'context_detail'         => array( 1, 5 ),
			'max_steps'              => array( 1, 25 ),
			'max_tools_per_request'  => array( 1, 25 ),
			'context_token_budget'   => array( 1000, 100000 ),
			'execution_mode'         => array( 1, 4 ),
		);
		foreach ( $int_ranges as $key => $range ) {
			if ( isset( $input[ $key ] ) ) {
				$clean[ $key ] = max( $range[0], min( $range[1], (int) $input[ $key ] ) );
			}
		}

		$float_ranges = array(
			'temperature' => array( 0.0, 2.0 ),
			'top_p'       => array( 0.0, 1.0 ),
		);
		foreach ( $float_ranges as $key => $range ) {
			if ( isset( $input[ $key ] ) ) {
				$clean[ $key ] = max( $range[0], min( $range[1], (float) $input[ $key ] ) );
			}
		}

		if ( isset( $input['ui_language'] ) && ! in_array( $clean['ui_language'], array( 'fa', 'en' ), true ) ) {
			$clean['ui_language'] = 'fa';
		}
		if ( isset( $input['ui_theme'] ) && ! in_array( $clean['ui_theme'], array( 'dark', 'light' ), true ) ) {
			$clean['ui_theme'] = 'dark';
		}

		update_option( self::OPTION, $clean );
		return $clean;
	}

	/**
	 * Sanitize an API key value (no spaces/newlines; keep it secret).
	 *
	 * @param string $value Raw key.
	 * @return string
	 */
	private static function sanitize_key_value( $value ) {
		$value = preg_replace( '/[\r\n\t\s]+/', '', $value );
		return substr( sanitize_text_field( $value ), 0, 512 );
	}

	/**
	 * Sanitize and normalize the base URL.
	 *
	 * @param string $url Raw URL.
	 * @return string
	 */
	private static function sanitize_base_url( $url ) {
		$url = esc_url_raw( trim( (string) $url ) );
		$url = rtrim( $url, '/' );
		if ( '' === $url ) {
			$url = self::defaults()['base_url'];
		}
		return $url;
	}

	/**
	 * Masked copy of settings safe to expose over REST (no full API key).
	 *
	 * @return array
	 */
	public static function masked() {
		$all = self::all();
		$key = (string) $all['api_key'];
		if ( '' === $key ) {
			$all['api_key']       = '';
			$all['api_key_set']   = false;
		} else {
			$all['api_key']       = self::mask_key( $key );
			$all['api_key_set']   = true;
		}
		return $all;
	}

	/**
	 * Mask an API key, keeping a short suffix.
	 *
	 * @param string $key Full key.
	 * @return string
	 */
	public static function mask_key( $key ) {
		$len = strlen( $key );
		if ( $len <= 8 ) {
			return str_repeat( '*', $len );
		}
		return str_repeat( '*', min( 24, $len - 4 ) ) . substr( $key, -4 );
	}

	/**
	 * Whether the plugin is ready to call an AI API.
	 *
	 * @return bool
	 */
	public static function is_configured() {
		$all = self::all();
		return '' !== (string) $all['api_key'] && '' !== (string) $all['base_url'] && '' !== (string) $all['model'];
	}
}
