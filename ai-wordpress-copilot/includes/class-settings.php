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
			// Provider flexibility.
			'custom_headers'        => '',   // JSON object of extra HTTP headers.
			'custom_params'         => '',   // JSON object of extra body params.
			'streaming'             => 1,    // Use SSE streaming when the model supports it.
			'stream_timeout'        => 120,  // Seconds for streaming requests.
			'context_window'        => 128000, // Model context window in tokens (0 = auto-detect).
			'json_mode'             => 0,    // Request JSON response_format when supported.
			'model_capabilities'    => '',   // Cached JSON: {tool_calling, streaming, streaming_tools, json_mode, context_window, source, detected_at}.
			'system_prompt'         => '',   // Extra system prompt appended to the built-in one.
			'preferred_builder'     => 'auto', // auto|elementor|gutenberg|classic.
			'link_check_concurrency' => 3,
			'link_check_timeout'    => 8,
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

		$string_keys = array( 'base_url', 'model', 'ui_language', 'ui_theme', 'system_prompt', 'preferred_builder' );
		foreach ( $string_keys as $key ) {
			if ( isset( $input[ $key ] ) ) {
				$clean[ $key ] = sanitize_text_field( (string) $input[ $key ] );
			}
		}

		if ( isset( $clean['preferred_builder'] ) && ! in_array( $clean['preferred_builder'], array( 'auto', 'elementor', 'gutenberg', 'classic' ), true ) ) {
			$clean['preferred_builder'] = 'auto';
		}

		// JSON blobs: custom headers / custom params / cached capabilities.
		foreach ( array( 'custom_headers', 'custom_params', 'model_capabilities' ) as $json_key ) {
			if ( isset( $input[ $json_key ] ) ) {
				$clean[ $json_key ] = self::sanitize_json_object( (string) $input[ $json_key ] );
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
			'streaming'              => array( 0, 1 ),
			'stream_timeout'         => array( 10, 600 ),
			'context_window'         => array( 0, 2000000 ),
			'json_mode'              => array( 0, 1 ),
			'link_check_concurrency' => array( 1, 10 ),
			'link_check_timeout'     => array( 2, 30 ),
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
	 * Sanitize a JSON object string (headers/params). Only flat string→string
	 * maps survive; anything else is dropped. Returns '' for empty/invalid input.
	 *
	 * @param string $raw Raw JSON.
	 * @return string Clean JSON or ''.
	 */
	private static function sanitize_json_object( $raw ) {
		$raw = trim( (string) $raw );
		if ( '' === $raw ) {
			return '';
		}
		$decoded = json_decode( $raw, true );
		if ( ! is_array( $decoded ) ) {
			return '';
		}
		$clean = array();
		foreach ( $decoded as $k => $v ) {
			$key = sanitize_text_field( (string) $k );
			if ( '' === $key || ! is_scalar( $v ) ) {
				continue;
			}
			// Never allow overriding auth headers through custom headers.
			if ( in_array( strtolower( $key ), array( 'authorization', 'host', 'content-length', 'cookie' ), true ) ) {
				continue;
			}
			$clean[ $key ] = sanitize_text_field( (string) $v );
		}
		return $clean ? (string) wp_json_encode( $clean ) : '';
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
