<?php
/**
 * Test-only mu-plugin for the AIWC smoke-test environment.
 *
 * 1. Enables application passwords over plain HTTP (local test site).
 * 2. Provides a fallback HTTP mock for the OpenAI-compatible API when the
 *    PHP runtime cannot reach the host mock server (127.0.0.1:8899).
 *
 * This file is mounted into the test site only; it is NOT part of the plugin.
 */

add_filter( 'wp_is_application_passwords_available', '__return_true' );

// Surface PHP errors during smoke testing.
if ( ! defined( 'WP_DEBUG' ) ) {
	define( 'WP_DEBUG', true );
}
if ( ! defined( 'WP_DEBUG_DISPLAY' ) ) {
	define( 'WP_DEBUG_DISPLAY', true );
}
ini_set( 'display_errors', '1' );
error_reporting( E_ALL );

/**
 * On-demand application-password provisioning for the smoke tests.
 * Endpoint: /wp-json/aiwc-test/v1/creds?key=smoke
 */
add_action(
	'rest_api_init',
	function () {
		register_rest_route(
			'aiwc-test/v1',
			'/creds',
			array(
				'methods'             => 'GET',
				'callback'            => function ( $request ) {
					if ( 'smoke' !== (string) $request->get_param( 'key' ) ) {
						return new \WP_Error( 'denied', 'bad key', array( 'status' => 403 ) );
					}
					$users = get_users( array( 'role' => 'administrator', 'number' => 1, 'orderby' => 'ID', 'order' => 'ASC' ) );
					if ( ! $users ) {
						return new \WP_Error( 'no_admin', 'no administrator found', array( 'status' => 500 ) );
					}
					$u           = $users[0];
					$created     = \WP_Application_Passwords::create_new_application_password( $u->ID, array( 'name' => 'smoke-' . time() ) );
					if ( is_wp_error( $created ) ) {
						return $created;
					}
					// Core returns array( $item, $password ); be defensive about order.
					$pass = is_string( $created[1] ?? null ) ? $created[1] : ( is_string( $created[0] ?? null ) ? $created[0] : '' );
					return array(
						'user' => $u->user_login,
						'pass' => $pass,
					);
				},
				'permission_callback' => '__return_true',
			)
		);
	}
);

/**
 * The fallback mock activates only when the sentinel file exists, so the
 * smoke tests can exercise the real HTTP transport first.
 *
 * @return bool
 */
function aiwc_test_use_fallback() {
	return file_exists( __DIR__ . '/.use-fallback' );
}

/**
 * Intercept requests to the mock API host only.
 */
add_filter(
	'pre_http_request',
	function ( $preempt, $args, $url ) {
		if ( false === strpos( $url, '127.0.0.1:8899' ) && false === strpos( $url, 'localhost:8899' ) ) {
			return $preempt;
		}
		if ( ! aiwc_test_use_fallback() ) {
			return $preempt;
		}

		$path = wp_parse_url( $url, PHP_URL_PATH );

		if ( 'GET' === strtoupper( (string) $args['method'] ) && $path && false !== strpos( $path, 'models' ) ) {
			return aiwc_test_http_response(
				array(
					'object' => 'list',
					'data'   => array(
						array( 'id' => 'mock-gpt' ),
						array( 'id' => 'mock-gpt-mini' ),
						array( 'id' => 'mock-gpt-pro' ),
					),
				)
			);
		}

		$body = json_decode( (string) ( isset( $args['body'] ) ? $args['body'] : '' ), true );
		if ( ! is_array( $body ) ) {
			$body = array();
		}
		$messages = isset( $body['messages'] ) && is_array( $body['messages'] ) ? $body['messages'] : array();

		$has_tool_result = false;
		$last_user       = '';
		foreach ( array_reverse( $messages ) as $message ) {
			if ( 'tool' === ( $message['role'] ?? '' ) ) {
				$has_tool_result = true;
			}
			if ( 'user' === ( $message['role'] ?? '' ) && '' === $last_user ) {
				$last_user = (string) ( $message['content'] ?? '' );
			}
		}

		if ( $has_tool_result ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'    => 'assistant',
						'content' => "## گزارش تغییرات\n\nعملیات با موفقیت انجام شد و در تاریخچه ثبت شد.\n\nAll done — the operation has been executed and logged.",
					)
				)
			);
		}

		if ( preg_match( '/(create page|ایجاد صفحه|بساز|create a page)/iu', $last_user ) ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'         => 'call_create_1',
								'type'       => 'function',
								'function'   => array(
									'name'      => 'create_page',
									'arguments' => wp_json_encode(
										array(
											'title'   => 'AIWC Test Page ' . time(),
											'content' => '<h2>درباره ما</h2><p>این صفحه توسط دستیار هوشمند وردپرس ساخته شده است.</p>',
											'status'  => 'publish',
										)
									),
								),
							),
						),
					)
				)
			);
		}

		if ( preg_match( '/(analyze seo|تحلیل سئو)/iu', $last_user ) ) {
			preg_match( '/\b(\d+)\b/', $last_user, $m );
			$post_id = isset( $m[1] ) ? absint( $m[1] ) : 1;
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_seo_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'seo_analyze',
									'arguments' => wp_json_encode( array( 'post_id' => $post_id ) ),
								),
							),
						),
					)
				)
			);
		}

		if ( preg_match( '/(update page|ویرایش صفحه)/iu', $last_user ) ) {
			preg_match( '/\b(\d+)\b/', $last_user, $m );
			$post_id = isset( $m[1] ) ? absint( $m[1] ) : 1;
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_upd_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'update_page',
									'arguments' => wp_json_encode(
										array(
											'post_id'      => $post_id,
											'title'        => 'Updated Title ' . time(),
											'content'      => '<p>Updated content by AI agent.</p>',
											'content_mode' => 'replace',
										)
									),
								),
							),
						),
					)
				)
			);
		}

		if ( preg_match( '/(delete|حذف)/iu', $last_user ) ) {
			preg_match( '/\b(\d+)\b/', $last_user, $m );
			$post_id = isset( $m[1] ) ? absint( $m[1] ) : 1;
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_del_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'delete_page',
									'arguments' => wp_json_encode( array( 'post_id' => $post_id, 'permanent' => false ) ),
								),
							),
						),
					)
				)
			);
		}

		if ( preg_match( '/(remember|یاد بگیر|به خاطر بسپار)/iu', $last_user ) ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_mem_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'memory_save',
									'arguments' => wp_json_encode(
										array(
											'category' => 'brand',
											'key'      => 'primary_color',
											'value'    => 'سرمه‌ای',
										)
									),
								),
							),
						),
					)
				)
			);
		}

		if ( preg_match( '/(site overview|نمای کلی)/iu', $last_user ) ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_ov_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'site_overview',
									'arguments' => '{}',
								),
							),
						),
					)
				)
			);
		}

		return aiwc_test_http_response(
			aiwc_test_completion(
				array(
					'role'    => 'assistant',
					'content' => "سلام! من دستیار هوشمند وردپرس هستم.\n\nHello! I am your WordPress copilot.",
				)
			)
		);
	},
	10,
	3
);

/**
 * Build a WP HTTP mock response array.
 *
 * @param array $body Response body.
 * @return array
 */
function aiwc_test_http_response( $body ) {
	return array(
		'headers'  => array(),
		'body'     => wp_json_encode( $body ),
		'response' => array(
			'code'    => 200,
			'message' => 'OK',
		),
		'cookies'  => array(),
		'filename' => null,
	);
}

/**
 * Build a chat completion payload.
 *
 * @param array $message Assistant message.
 * @return array
 */
function aiwc_test_completion( $message ) {
	return array(
		'id'      => 'chatcmpl-test-' . time(),
		'object'  => 'chat.completion',
		'created' => time(),
		'model'   => 'mock-gpt',
		'choices' => array(
			array(
				'index'         => 0,
				'message'       => $message,
				'finish_reason' => empty( $message['tool_calls'] ) ? 'stop' : 'tool_calls',
			),
		),
		'usage'   => array(
			'prompt_tokens'     => 120,
			'completion_tokens' => 60,
			'total_tokens'      => 180,
		),
	);
}
