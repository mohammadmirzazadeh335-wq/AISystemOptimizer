<?php
/**
 * HTTP client for OpenAI-compatible chat completion APIs.
 *
 * @package AIWC
 */

namespace AIWC\Ai;

use AIWC\Settings;

defined( 'ABSPATH' ) || exit;

/**
 * Talks to any OpenAI-compatible endpoint (configurable base URL).
 */
class OpenAI_Client {

	/**
	 * Last HTTP error message.
	 *
	 * @var string
	 */
	private $last_error = '';

	/**
	 * Last HTTP status code.
	 *
	 * @var int
	 */
	private $last_status = 0;

	/**
	 * Get last error message.
	 *
	 * @return string
	 */
	public function get_last_error() {
		return $this->last_error;
	}

	/**
	 * Build request URL for an endpoint path.
	 *
	 * @param string $path Endpoint path, e.g. 'chat/completions'.
	 * @return string
	 */
	private function url( $path ) {
		$base = rtrim( (string) Settings::get( 'base_url' ), '/' );
		return $base . '/' . ltrim( $path, '/' );
	}

	/**
	 * Core request with retry / timeout handling.
	 *
	 * @param string $path Endpoint path.
	 * @param array  $body Request body.
	 * @param string $method HTTP method.
	 * @return array|\WP_Error Decoded JSON body or error.
	 */
	private function request( $path, array $body, $method = 'POST' ) {
		$settings   = Settings::all();
		$timeout    = (int) $settings['timeout'];
		$max_retry  = (int) $settings['max_retries'];
		$attempt    = 0;
		$last_error = null;

		while ( $attempt <= $max_retry ) {
			$args = array(
				'method'  => $method,
				'timeout' => $timeout,
				'headers' => array(
					'Content-Type'  => 'application/json',
					'Authorization' => 'Bearer ' . (string) $settings['api_key'],
				),
			);
			if ( ! in_array( strtoupper( $method ), array( 'GET', 'HEAD' ), true ) ) {
				$args['body'] = wp_json_encode( $body );
			}

			$start  = microtime( true );
			$resp   = wp_remote_request( $this->url( $path ), $args );
			$elapsed = (int) ( ( microtime( true ) - $start ) * 1000 );

			if ( is_wp_error( $resp ) ) {
				$last_error = $resp->get_error_message();
				++$attempt;
				if ( $attempt <= $max_retry ) {
					usleep( min( 2000000, 250000 * ( 2 ** $attempt ) ) );
					continue;
				}
				$this->last_error  = $last_error;
				$this->last_status = 0;
				return new \WP_Error( 'aiwc_api_network', sprintf( 'Network error: %s', $last_error ), array( 'status' => 502 ) );
			}

			$status = (int) wp_remote_retrieve_response_code( $resp );
			$this->last_status = $status;
			$raw     = wp_remote_retrieve_body( $resp );
			$decoded = json_decode( $raw, true );

			if ( $status >= 200 && $status < 300 ) {
				if ( ! is_array( $decoded ) ) {
					return new \WP_Error( 'aiwc_api_bad_json', 'The API returned an invalid JSON response.', array( 'status' => 502 ) );
				}
				$decoded['_aiwc_duration_ms'] = $elapsed;
				return $decoded;
			}

			// Extract provider error message.
			$msg = sprintf( 'HTTP %d', $status );
			if ( is_array( $decoded ) ) {
				if ( isset( $decoded['error']['message'] ) ) {
					$msg .= ': ' . $decoded['error']['message'];
				} elseif ( isset( $decoded['message'] ) ) {
					$msg .= ': ' . $decoded['message'];
				}
			}
			$last_error = $msg;

			// Retry only on rate limits and server errors.
			if ( in_array( $status, array( 408, 429, 500, 502, 503, 504 ), true ) && $attempt < $max_retry ) {
				++$attempt;
				usleep( min( 3000000, 500000 * ( 2 ** $attempt ) ) );
				continue;
			}
			break;
		}

		$this->last_error = $last_error;
		return new \WP_Error(
			'aiwc_api_http',
			$last_error ? $last_error : 'Unknown API error',
			array( 'status' => $this->last_status ? $this->last_status : 502 )
		);
	}

	/**
	 * Chat completion call with optional tool definitions.
	 *
	 * @param array $messages OpenAI messages array.
	 * @param array $tools    OpenAI tools array (function calling).
	 * @param array $extra    Extra body params.
	 * @return array|\WP_Error Decoded response.
	 */
	public function chat( array $messages, array $tools = array(), array $extra = array() ) {
		$settings = Settings::all();

		$body = array(
			'model'       => (string) $settings['model'],
			'messages'    => $messages,
			'max_tokens'  => (int) $settings['max_output_tokens'],
			'temperature' => (float) $settings['temperature'],
			'top_p'       => (float) $settings['top_p'],
		);

		if ( $tools ) {
			$body['tools']      = $tools;
			$body['tool_choice'] = isset( $extra['tool_choice'] ) ? $extra['tool_choice'] : 'auto';
		}

		// Note: analysis strictness / creativity are managed by the prompt layer,
		// deliberately separate from temperature & top_p.
		if ( ! empty( $extra['response_format'] ) ) {
			$body['response_format'] = $extra['response_format'];
		}

		return $this->request( 'chat/completions', $body );
	}

	/**
	 * Test the connection against the configured endpoint.
	 *
	 * @return array{ok: bool, message: string, model: string, latency_ms: int}
	 */
	public function test_connection() {
		$settings = Settings::all();
		if ( '' === (string) $settings['api_key'] ) {
			return array(
				'ok'        => false,
				'message'   => __( 'API key is not set.', 'ai-wordpress-copilot' ),
				'model'     => (string) $settings['model'],
				'latency_ms' => 0,
			);
		}

		$resp = $this->chat(
			array(
				array(
					'role'    => 'user',
					'content' => 'Reply with the single word: pong',
				),
			),
			array(),
			array()
		);

		if ( is_wp_error( $resp ) ) {
			return array(
				'ok'        => false,
				'message'   => $resp->get_error_message(),
				'model'     => (string) $settings['model'],
				'latency_ms' => 0,
			);
		}

		$content = '';
		if ( isset( $resp['choices'][0]['message']['content'] ) ) {
			$content = (string) $resp['choices'][0]['message']['content'];
		}

		return array(
			'ok'         => true,
			'message'    => sprintf( 'OK: %s', mb_substr( $content, 0, 60 ) ),
			'model'      => isset( $resp['model'] ) ? (string) $resp['model'] : (string) $settings['model'],
			'latency_ms' => isset( $resp['_aiwc_duration_ms'] ) ? (int) $resp['_aiwc_duration_ms'] : 0,
		);
	}

	/**
	 * List models from the provider (GET /models).
	 *
	 * @return array{models: array}|\WP_Error
	 */
	public function list_models() {
		$settings = Settings::all();
		if ( '' === (string) $settings['api_key'] ) {
			return new \WP_Error( 'aiwc_no_key', __( 'API key is not set.', 'ai-wordpress-copilot' ), array( 'status' => 400 ) );
		}
		$resp = $this->request( 'models', array(), 'GET' );
		if ( is_wp_error( $resp ) ) {
			return $resp;
		}
		$models = array();
		if ( isset( $resp['data'] ) && is_array( $resp['data'] ) ) {
			foreach ( $resp['data'] as $model ) {
				if ( isset( $model['id'] ) ) {
					$models[] = $model['id'];
				}
			}
		}
		return array( 'models' => $models );
	}
}
