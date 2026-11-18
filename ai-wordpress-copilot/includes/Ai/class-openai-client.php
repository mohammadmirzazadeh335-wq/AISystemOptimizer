<?php
/**
 * HTTP client for OpenAI-compatible chat completion APIs.
 *
 * Supports: configurable base URL, custom headers/params, JSON mode, real SSE
 * streaming (tool-call fragment assembly), typed error taxonomy and model
 * capability detection. No model name is hardcoded anywhere.
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
	 * Last HTTP error message (sanitized for display).
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
	 * Last typed error code.
	 *
	 * @var string
	 */
	private $last_error_code = '';

	/**
	 * Get last error message.
	 *
	 * @return string
	 */
	public function get_last_error() {
		return $this->last_error;
	}

	/**
	 * Get last typed error code.
	 *
	 * @return string
	 */
	public function get_last_error_code() {
		return $this->last_error_code;
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
	 * Sanitize an error message: strip API keys and URL query strings so raw
	 * provider errors never leak secrets to the UI.
	 *
	 * @param string $msg Raw message.
	 * @return string
	 */
	public static function sanitize_error_message( $msg ) {
		$msg = (string) $msg;
		// Redact bearer keys / sk- tokens.
		$msg = preg_replace( '/(?:sk|rk|key)[-_][A-Za-z0-9_\-]{8,}/', '[redacted]', $msg );
		$msg = preg_replace( '/Bearer\s+\S+/', 'Bearer [redacted]', $msg );
		// Redact URL query strings.
		$msg = preg_replace( '/\?[\w%&=\.\-\/\+]+/', '?[redacted]', $msg );
		return substr( $msg, 0, 400 );
	}

	/**
	 * Map an HTTP status / body to a typed error code.
	 *
	 * @param int    $status HTTP status.
	 * @param string $body   Raw body text.
	 * @return string
	 */
	public static function classify_error( $status, $body = '' ) {
		$lower = strtolower( (string) $body );
		if ( 401 === $status || 403 === $status ) {
			return 'aiwc_auth_invalid';
		}
		if ( 404 === $status ) {
			return 'aiwc_model_not_found';
		}
		if ( 429 === $status ) {
			return 'aiwc_rate_limited';
		}
		if ( 400 === $status && ( false !== strpos( $lower, 'context_length' ) || false !== strpos( $lower, 'maximum context' ) || false !== strpos( $lower, 'too many tokens' ) ) ) {
			return 'aiwc_context_length_exceeded';
		}
		if ( 400 === $status && ( false !== strpos( $lower, 'tool' ) || false !== strpos( $lower, 'function calling' ) ) ) {
			return 'aiwc_unsupported_tool_calling';
		}
		if ( in_array( $status, array( 408, 504 ), true ) ) {
			return 'aiwc_timeout';
		}
		if ( $status >= 500 ) {
			return 'aiwc_provider_error';
		}
		return 'aiwc_api_http';
	}

	/**
	 * Human-friendly, safe message for a typed error code.
	 *
	 * @param string $code   Error code.
	 * @param string $detail Optional sanitized detail.
	 * @return string
	 */
	public static function error_message( $code, $detail = '' ) {
		$map = array(
			'aiwc_auth_invalid'              => __( 'API key is invalid or has no access to this model.', 'ai-wordpress-copilot' ),
			'aiwc_model_not_found'           => __( 'Model not found on this provider. Check the model name.', 'ai-wordpress-copilot' ),
			'aiwc_rate_limited'              => __( 'Rate limit reached. Please wait a moment and try again.', 'ai-wordpress-copilot' ),
			'aiwc_context_length_exceeded'   => __( 'The request exceeds the model context window. Reduce context detail or split the command.', 'ai-wordpress-copilot' ),
			'aiwc_timeout'                   => __( 'The AI provider timed out.', 'ai-wordpress-copilot' ),
			'aiwc_connection'                => __( 'Could not connect to the AI provider. Check the Base URL and your network.', 'ai-wordpress-copilot' ),
			'aiwc_invalid_response'          => __( 'The AI provider returned an invalid response.', 'ai-wordpress-copilot' ),
			'aiwc_unsupported_tool_calling'   => __( 'This model does not support tool calling.', 'ai-wordpress-copilot' ),
			'aiwc_invalid_tool_arguments'    => __( 'The model produced invalid tool arguments.', 'ai-wordpress-copilot' ),
			'aiwc_stream_unsupported'        => __( 'This endpoint does not support streaming; falling back to standard mode.', 'ai-wordpress-copilot' ),
			'aiwc_provider_error'            => __( 'The AI provider reported a server error.', 'ai-wordpress-copilot' ),
		);
		$base = isset( $map[ $code ] ) ? $map[ $code ] : __( 'Unknown API error.', 'ai-wordpress-copilot' );
		return $detail ? $base . ' (' . self::sanitize_error_message( $detail ) . ')' : $base;
	}

	/**
	 * Decode custom headers setting into an array.
	 *
	 * @return array
	 */
	private function custom_headers() {
		$raw = (string) Settings::get( 'custom_headers' );
		if ( '' === $raw ) {
			return array();
		}
		$decoded = json_decode( $raw, true );
		return is_array( $decoded ) ? $decoded : array();
	}

	/**
	 * Decode custom body params setting into an array.
	 *
	 * @return array
	 */
	private function custom_params() {
		$raw = (string) Settings::get( 'custom_params' );
		if ( '' === $raw ) {
			return array();
		}
		$decoded = json_decode( $raw, true );
		return is_array( $decoded ) ? $decoded : array();
	}

	/**
	 * Core request with retry / timeout handling and typed errors.
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
			$headers = array_merge(
				array(
					'Content-Type'  => 'application/json',
					'Authorization' => 'Bearer ' . (string) $settings['api_key'],
				),
				$this->custom_headers()
			);
			$args = array(
				'method'   => $method,
				'timeout'  => $timeout,
				'headers'  => $headers,
				'redirection' => 0, // API endpoints must not silently redirect (SSRF hygiene).
			);
			if ( ! in_array( strtoupper( $method ), array( 'GET', 'HEAD' ), true ) ) {
				$args['body'] = wp_json_encode( $body );
			}

			$start   = microtime( true );
			$resp    = wp_remote_request( $this->url( $path ), $args );
			$elapsed = (int) ( ( microtime( true ) - $start ) * 1000 );

			if ( is_wp_error( $resp ) ) {
				$code = 'aiwc_connection';
				if ( false !== stripos( $resp->get_error_code(), 'http_request_failed' ) ) {
					$code = 'aiwc_connection';
				}
				$last_error = $resp->get_error_message();
				++$attempt;
				if ( $attempt <= $max_retry ) {
					usleep( min( 2000000, 250000 * ( 2 ** $attempt ) ) );
					continue;
				}
				$this->last_error      = self::error_message( $code, $last_error );
				$this->last_error_code = $code;
				$this->last_status     = 0;
				return new \WP_Error( $code, $this->last_error, array( 'status' => 502 ) );
			}

			$status = (int) wp_remote_retrieve_response_code( $resp );
			$this->last_status = $status;
			$raw     = (string) wp_remote_retrieve_body( $resp );
			$decoded = json_decode( $raw, true );

			if ( $status >= 200 && $status < 300 ) {
				if ( ! is_array( $decoded ) ) {
					$this->last_error_code = 'aiwc_invalid_response';
					return new \WP_Error( 'aiwc_invalid_response', self::error_message( 'aiwc_invalid_response' ), array( 'status' => 502 ) );
				}
				$decoded['_aiwc_duration_ms'] = $elapsed;
				return $decoded;
			}

			// Build sanitized error.
			$detail = sprintf( 'HTTP %d', $status );
			if ( is_array( $decoded ) ) {
				if ( isset( $decoded['error']['message'] ) ) {
					$detail .= ': ' . (string) $decoded['error']['message'];
				} elseif ( isset( $decoded['message'] ) ) {
					$detail .= ': ' . (string) $decoded['message'];
				}
			}
			$code = self::classify_error( $status, $raw );
			$last_error = self::error_message( $code, $detail );

			// Retry only on rate limits and server errors.
			if ( in_array( $status, array( 408, 429, 500, 502, 503, 504 ), true ) && $attempt < $max_retry ) {
				++$attempt;
				usleep( min( 3000000, 500000 * ( 2 ** $attempt ) ) );
				continue;
			}
			$this->last_error      = $last_error;
			$this->last_error_code = $code;
			return new \WP_Error( $code, $last_error, array( 'status' => $status ? $status : 502 ) );
		}

		$this->last_error      = $last_error ? $last_error : self::error_message( 'aiwc_connection' );
		$this->last_error_code = 'aiwc_connection';
		return new \WP_Error( 'aiwc_connection', $this->last_error, array( 'status' => 502 ) );
	}

	/**
	 * Build the shared chat body.
	 *
	 * @param array $messages Messages.
	 * @param array $tools    Tools.
	 * @param array $extra    Extra params.
	 * @param bool  $stream   Streaming request.
	 * @return array
	 */
	private function chat_body( array $messages, array $tools, array $extra, $stream = false ) {
		$settings = Settings::all();

		$body = array(
			'model'       => (string) $settings['model'],
			'messages'    => $messages,
			'max_tokens'  => (int) $settings['max_output_tokens'],
			'temperature' => (float) $settings['temperature'],
			'top_p'       => (float) $settings['top_p'],
		);

		if ( $stream ) {
			$body['stream'] = true;
		}

		if ( $tools ) {
			$body['tools']       = $tools;
			$body['tool_choice'] = isset( $extra['tool_choice'] ) ? $extra['tool_choice'] : 'auto';
		}

		// JSON mode when enabled and supported.
		if ( ! empty( $extra['response_format'] ) ) {
			$body['response_format'] = $extra['response_format'];
		} elseif ( (int) Settings::get( 'json_mode' ) === 1 ) {
			$body['response_format'] = array( 'type' => 'json_object' );
		}

		// User-defined extra params (never override the core keys above).
		foreach ( $this->custom_params() as $k => $v ) {
			if ( ! array_key_exists( $k, $body ) && is_scalar( $v ) ) {
				$body[ $k ] = $v;
			}
		}

		// Note: analysis strictness / creativity live in the prompt layer,
		// deliberately separate from temperature & top_p.
		return $body;
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
		return $this->request( 'chat/completions', $this->chat_body( $messages, $tools, $extra, false ) );
	}

	/**
	 * Streaming chat completion (Server-Sent Events).
	 *
	 * Uses the WordPress HTTP API; when the cURL transport is available the
	 * response body is consumed incrementally through CURLOPT_WRITEFUNCTION so
	 * events are forwarded live via $on_event. Tool-call argument fragments are
	 * accumulated and assembled into complete tool calls before returning, so
	 * the return shape matches chat() and the agent loop is unchanged.
	 *
	 * @param array    $messages OpenAI messages array.
	 * @param array    $tools    Tools.
	 * @param array    $extra    Extra params.
	 * @param callable $on_event function( string $type, mixed $data ): void.
	 *                           Types: 'delta', 'tool_call', 'tool_args', 'usage', 'raw'.
	 * @return array|\WP_Error Assembled response (same shape as chat()).
	 */
	public function chat_stream( array $messages, array $tools = array(), array $extra = array(), callable $on_event = null ) {
		$settings = Settings::all();
		$timeout  = max( 10, (int) Settings::get( 'stream_timeout', 120 ) );
		$body     = $this->chat_body( $messages, $tools, $extra, true );

		$state = array(
			'buffer'      => '',
			'content'     => '',
			'tool_calls'  => array(), // index => ['id','name','arguments'].
			'usage'       => null,
			'model'       => (string) $settings['model'],
			'saw_data'    => false,
			'curl_used'   => false,
		);

		$emit = function ( $type, $data ) use ( &$on_event ) {
			if ( is_callable( $on_event ) ) {
				call_user_func( $on_event, $type, $data );
			}
		};

		$chunk_handler = function ( $handle, $chunk ) use ( &$state, $emit ) {
			$state['curl_used'] = true;
			$state['buffer']   .= (string) $chunk;
			// Process complete SSE lines; keep the remainder buffered.
			while ( ( $pos = strpos( $state['buffer'], "\n" ) ) !== false ) {
				$line   = rtrim( substr( $state['buffer'], 0, $pos ), "\r" );
				$state['buffer'] = substr( $state['buffer'], $pos + 1 );
				if ( '' === $line || 0 === strpos( $line, ':' ) ) {
					continue; // comment / keep-alive.
				}
				if ( 0 !== strpos( $line, 'data:' ) ) {
					continue;
				}
				$payload = trim( substr( $line, 5 ) );
				if ( '[DONE]' === $payload ) {
					return strlen( $chunk ); // Must report consumed bytes or cURL fails with error 23.
				}
				$state['saw_data'] = true;
				$decoded = json_decode( $payload, true );
				if ( ! is_array( $decoded ) ) {
					continue;
				}
				$this->absorb_stream_chunk( $decoded, $state, $emit );
			}
			return strlen( $chunk );
		};

		$headers = array_merge(
			array(
				'Content-Type'  => 'application/json',
				'Authorization' => 'Bearer ' . (string) $settings['api_key'],
				'Accept'        => 'text/event-stream',
			),
			$this->custom_headers()
		);

		$args = array(
			'method'      => 'POST',
			'timeout'     => $timeout,
			'headers'     => $headers,
			'body'        => wp_json_encode( $body ),
			'redirection' => 0,
		);

		// Intercept the cURL transport to consume the body incrementally.
		$interceptor = function ( $handle ) use ( &$chunk_handler, &$state ) {
			if ( is_resource( $handle ) || ( is_object( $handle ) && 'CurlHandle' === get_class( $handle ) ) ) {
				// phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions -- streaming the SSE body.
				curl_setopt( $handle, CURLOPT_WRITEFUNCTION, $chunk_handler );
			}
		};
		add_action( 'http_api_curl', $interceptor, 10, 1 );

		$resp = wp_remote_request( $this->url( 'chat/completions' ), $args );

		remove_action( 'http_api_curl', $interceptor, 10 );

		if ( is_wp_error( $resp ) ) {
			$code = 'aiwc_connection';
			$this->last_error_code = $code;
			$this->last_error      = self::error_message( $code, $resp->get_error_message() );
			return new \WP_Error( $code, $this->last_error, array( 'status' => 502 ) );
		}

		$status = (int) wp_remote_retrieve_response_code( $resp );
		$this->last_status = $status;

		if ( $status < 200 || $status >= 300 ) {
			$raw  = (string) wp_remote_retrieve_body( $resp );
			$code = self::classify_error( $status, $raw );
			$this->last_error_code = $code;
			$this->last_error      = self::error_message( $code, sprintf( 'HTTP %d', $status ) );
			return new \WP_Error( $code, $this->last_error, array( 'status' => $status ) );
		}

		// Transport could not deliver incremental data (no cURL interception):
		// treat as unsupported so callers fall back to a normal request.
		if ( ! $state['curl_used'] && ! $state['saw_data'] ) {
			// The body may still contain a complete SSE stream (non-incremental).
			$raw_body = (string) wp_remote_retrieve_body( $resp );
			if ( $raw_body ) {
				foreach ( explode( "\n", $raw_body ) as $line ) {
					$line = rtrim( $line, "\r" );
					if ( 0 === strpos( $line, 'data:' ) ) {
						$payload = trim( substr( $line, 5 ) );
						if ( '[DONE]' === $payload ) {
							continue;
						}
						$decoded = json_decode( $payload, true );
						if ( is_array( $decoded ) ) {
							$state['saw_data'] = true;
							$this->absorb_stream_chunk( $decoded, $state, $emit );
						}
					}
				}
			}
			if ( ! $state['saw_data'] ) {
				$this->last_error_code = 'aiwc_stream_unsupported';
				$this->last_error      = self::error_message( 'aiwc_stream_unsupported' );
				return new \WP_Error( 'aiwc_stream_unsupported', $this->last_error, array( 'status' => 501 ) );
			}
		}

		// Assemble the final response in the same shape as chat().
		$tool_calls = array();
		foreach ( $state['tool_calls'] as $tc ) {
			$args_json = (string) $tc['arguments'];
			$parsed    = json_decode( $args_json, true );
			if ( ! is_array( $parsed ) ) {
				// Attempt to repair truncated JSON fragments; if hopeless, report.
				$parsed = self::repair_json_arguments( $args_json );
				if ( null === $parsed ) {
					$this->last_error_code = 'aiwc_invalid_tool_arguments';
					return new \WP_Error(
						'aiwc_invalid_tool_arguments',
						self::error_message( 'aiwc_invalid_tool_arguments' ),
						array( 'status' => 502 )
					);
				}
			}
			$tool_calls[] = array(
				'id'       => (string) $tc['id'],
				'type'     => 'function',
				'function' => array(
					'name'      => (string) $tc['name'],
					'arguments' => wp_json_encode( $parsed ),
				),
			);
		}

		$response = array(
			'id'      => 'aiwc-stream-' . time(),
			'object'  => 'chat.completion',
			'model'   => $state['model'],
			'choices' => array(
				array(
					'index'         => 0,
					'finish_reason' => $tool_calls ? 'tool_calls' : 'stop',
					'message'       => array(
						'role'       => 'assistant',
						'content'    => '' === $state['content'] ? null : $state['content'],
						'tool_calls' => $tool_calls ? $tool_calls : null,
					),
				),
			),
			'usage'   => $state['usage'] ? $state['usage'] : array(
				'prompt_tokens'     => 0,
				'completion_tokens' => 0,
				'total_tokens'      => 0,
			),
		);
		$response['_aiwc_duration_ms'] = 0;
		return $response;
	}

	/**
	 * Absorb one decoded SSE chunk into the assembly state.
	 *
	 * @param array    $chunk Decoded chunk.
	 * @param array    $state State (by ref).
	 * @param callable $emit  Event emitter.
	 * @return void
	 */
	private function absorb_stream_chunk( array $chunk, array &$state, callable $emit ) {
		if ( isset( $chunk['model'] ) && is_string( $chunk['model'] ) ) {
			$state['model'] = $chunk['model'];
		}
		if ( isset( $chunk['usage'] ) && is_array( $chunk['usage'] ) ) {
			$state['usage'] = $chunk['usage'];
			$emit( 'usage', $chunk['usage'] );
		}
		$choice = isset( $chunk['choices'][0] ) ? $chunk['choices'][0] : array();
		$delta  = isset( $choice['delta'] ) && is_array( $choice['delta'] ) ? $choice['delta'] : array();

		if ( isset( $delta['content'] ) && is_string( $delta['content'] ) && '' !== $delta['content'] ) {
			$state['content'] .= $delta['content'];
			$emit( 'delta', $delta['content'] );
		}

		if ( isset( $delta['tool_calls'] ) && is_array( $delta['tool_calls'] ) ) {
			foreach ( $delta['tool_calls'] as $tc ) {
				$idx = isset( $tc['index'] ) ? (int) $tc['index'] : 0;
			if ( ! isset( $state['tool_calls'][ $idx ] ) ) {
				$state['tool_calls'][ $idx ] = array(
					'id'        => '',
					'name'      => '',
					'arguments' => '',
				);
			}
			if ( isset( $tc['id'] ) && '' !== $tc['id'] ) {
				$state['tool_calls'][ $idx ]['id'] = $tc['id'];
			}
			$fn = isset( $tc['function'] ) && is_array( $tc['function'] ) ? $tc['function'] : array();
			if ( isset( $fn['name'] ) && '' !== $fn['name'] ) {
				$state['tool_calls'][ $idx ]['name'] = $fn['name'];
				$emit(
					'tool_call',
					array(
						'index' => $idx,
						'id'    => $state['tool_calls'][ $idx ]['id'],
						'tool'  => $fn['name'],
					)
				);
			}
				if ( isset( $fn['arguments'] ) && is_string( $fn['arguments'] ) && '' !== $fn['arguments'] ) {
					$state['tool_calls'][ $idx ]['arguments'] .= $fn['arguments'];
					$emit( 'tool_args', array( 'index' => $idx, 'fragment' => $fn['arguments'] ) );
				}
			}
		}
	}

	/**
	 * Best-effort repair of truncated JSON tool arguments (missing braces).
	 *
	 * @param string $raw Raw argument string.
	 * @return array|null
	 */
	public static function repair_json_arguments( $raw ) {
		$raw = trim( (string) $raw );
		if ( '' === $raw ) {
			return array();
		}
		$decoded = json_decode( $raw, true );
		if ( is_array( $decoded ) ) {
			return $decoded;
		}
		// Close open strings/brackets.
		$candidate = $raw;
		$opens     = substr_count( $candidate, '{' ) - substr_count( $candidate, '}' );
		$opens_sq  = substr_count( $candidate, '[' ) - substr_count( $candidate, ']' );
		if ( substr( $candidate, -1 ) === ',' ) {
			$candidate = substr( $candidate, 0, -1 );
		}
		if ( substr_count( $candidate, '"' ) % 2 === 1 ) {
			$candidate .= '"';
		}
		$candidate .= str_repeat( ']', max( 0, $opens_sq ) );
		$candidate .= str_repeat( '}', max( 0, $opens ) );
		$decoded = json_decode( $candidate, true );
		return is_array( $decoded ) ? $decoded : null;
	}

	/**
	 * Get model capabilities (cached heuristics + optional live probe).
	 *
	 * @param bool $force Re-probe even when a cache exists.
	 * @return array{tool_calling: bool, streaming: bool, streaming_tools: bool, json_mode: bool, context_window: int, source: string}
	 */
	public function detect_capabilities( $force = false ) {
		$cached = json_decode( (string) Settings::get( 'model_capabilities' ), true );
		if ( ! $force && is_array( $cached ) && ! empty( $cached['detected_at'] ) && ( time() - (int) $cached['detected_at'] ) < DAY_IN_SECONDS ) {
			return $cached;
		}

		$model = strtolower( (string) Settings::get( 'model' ) );
		$caps  = array(
			'tool_calling'     => true,
			'streaming'        => true,
			'streaming_tools'  => true,
			'json_mode'        => true,
			'context_window'   => (int) Settings::get( 'context_window' ),
			'source'           => 'heuristic',
			'detected_at'      => time(),
		);

		// Name-based heuristics. Model names are never hardcoded as defaults,
		// but known families give safe capability hints.
		$no_tools = array( 'gpt-3.5-turbo-instruct', 'davinci', 'babbage', 'ada', 'completion' );
		foreach ( $no_tools as $needle ) {
			if ( false !== strpos( $model, $needle ) ) {
				$caps['tool_calling']    = false;
				$caps['streaming_tools'] = false;
				$caps['json_mode']       = false;
				$caps['source']          = 'heuristic-name';
			}
		}
		if ( preg_match( '/(instruct|complete|embedding)/', $model ) && ! preg_match( '/(gpt-4o|o1|o3|o4)/', $model ) ) {
			$caps['tool_calling']    = false;
			$caps['streaming_tools'] = false;
		}
		if ( 0 === $caps['context_window'] ) {
			// Common context windows by family, otherwise a safe default.
			if ( preg_match( '/(gpt-4o|o1|o3|claude-3|gemini-1\.5|gemini-2)/', $model ) ) {
				$caps['context_window'] = 128000;
			} elseif ( preg_match( '/gpt-4(?!o)/', $model ) ) {
				$caps['context_window'] = 8192;
			} elseif ( preg_match( '/gpt-3\.5/', $model ) ) {
				$caps['context_window'] = 16385;
			} else {
				$caps['context_window'] = 8192;
			}
		}

		// Optional live probe (cheap) when explicitly forced and configured.
		if ( $force && Settings::is_configured() ) {
			$probe = $this->probe_tool_calling();
			if ( null !== $probe ) {
				$caps['tool_calling']    = $probe;
				$caps['streaming_tools'] = $probe;
				$caps['source']          = 'probe';
			}
			$stream_probe = $this->probe_streaming();
			if ( null !== $stream_probe ) {
				$caps['streaming']       = $stream_probe;
				$caps['streaming_tools'] = $stream_probe ? $caps['streaming_tools'] : false;
				$caps['source']          = 'probe';
			}
			// Context window hint from /models when the provider exposes it.
			$models = $this->list_models_raw();
			if ( is_array( $models ) && isset( $models['_aiwc_context_window'] ) ) {
				$caps['context_window'] = (int) $models['_aiwc_context_window'];
			}
		}

		Settings::save( array( 'model_capabilities' => (string) wp_json_encode( $caps ) ) );
		return $caps;
	}

	/**
	 * Probe tool-calling support with a minimal request.
	 *
	 * @return bool|null Null when the probe could not run.
	 */
	private function probe_tool_calling() {
		$resp = $this->chat(
			array(
				array( 'role' => 'user', 'content' => 'Call the ping tool.' ),
			),
			array(
				array(
					'type'     => 'function',
					'function' => array(
						'name'        => 'ping',
						'description' => 'Ping.',
						'parameters'  => array( 'type' => 'object', 'properties' => array() ),
					),
				),
			),
			array( 'tool_choice' => 'auto' )
		);
		if ( is_wp_error( $resp ) ) {
			if ( 'aiwc_unsupported_tool_calling' === $resp->get_error_code() ) {
				return false;
			}
			return null;
		}
		$msg = isset( $resp['choices'][0]['message'] ) ? $resp['choices'][0]['message'] : array();
		return ! empty( $msg['tool_calls'] );
	}

	/**
	 * Probe streaming support with a minimal stream request.
	 *
	 * @return bool|null
	 */
	private function probe_streaming() {
		$out = null;
		$resp = $this->chat_stream(
			array(
				array( 'role' => 'user', 'content' => 'Say hi.' ),
			),
			array(),
			array(),
			function ( $type, $data ) use ( &$out ) {
				if ( 'delta' === $type ) {
					$out = true;
				}
			}
		);
		if ( is_wp_error( $resp ) ) {
			return 'aiwc_stream_unsupported' === $resp->get_error_code() ? false : null;
		}
		return null === $out ? false : true;
	}

	/**
	 * Internal: GET /models raw (also extracts a context window hint).
	 *
	 * @return array|\WP_Error
	 */
	private function list_models_raw() {
		$resp = $this->request( 'models', array(), 'GET' );
		if ( is_wp_error( $resp ) ) {
			return $resp;
		}
		// Some providers expose context_length on model objects.
		if ( isset( $resp['data'][0]['context_length'] ) ) {
			$resp['_aiwc_context_window'] = (int) $resp['data'][0]['context_length'];
		}
		return $resp;
	}

	/**
	 * Test the connection against the configured endpoint.
	 *
	 * @return array{ok: bool, message: string, model: string, latency_ms: int, error_code: string}
	 */
	public function test_connection() {
		$settings = Settings::all();
		if ( '' === (string) $settings['api_key'] ) {
			return array(
				'ok'         => false,
				'message'    => __( 'API key is not set.', 'ai-wordpress-copilot' ),
				'model'      => (string) $settings['model'],
				'latency_ms' => 0,
				'error_code' => 'aiwc_auth_invalid',
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
				'ok'         => false,
				'message'    => $resp->get_error_message(),
				'model'      => (string) $settings['model'],
				'latency_ms' => 0,
				'error_code' => (string) $resp->get_error_code(),
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
			'error_code' => '',
		);
	}

	/**
	 * List models from the provider (GET /models).
	 *
	 * @return array{models: array, context_window: int}|WP_Error
	 */
	public function list_models() {
		$settings = Settings::all();
		if ( '' === (string) $settings['api_key'] ) {
			return new \WP_Error( 'aiwc_no_key', __( 'API key is not set.', 'ai-wordpress-copilot' ), array( 'status' => 400 ) );
		}
		$resp = $this->list_models_raw();
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
		return array(
			'models'        => $models,
			'context_window' => isset( $resp['_aiwc_context_window'] ) ? (int) $resp['_aiwc_context_window'] : 0,
		);
	}
}
