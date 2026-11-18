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

// php-wasm prints PHP notices to output even when error_reporting/display_errors
// are relaxed, and that early output breaks REST status headers ("headers already
// sent" -> 200 instead of 401/201) and pollutes JSON. Buffer everything and strip
// benign notice/warning HTML chunks at flush time.
if ( ! ob_get_level() ) {
	ob_start(
		function ( $html ) {
			return preg_replace(
				'#<br\s*/?>\s*<b>(?:Notice|Warning|Deprecated|Strict Standards)</b>:[\s\S]*?on line <b>\d+</b><br\s*/?>#i',
				'',
				$html
			);
		}
	);
}

// Keep REST/JSON responses clean in tests: hide benign early-translation notices.
ini_set( 'display_errors', '0' );
error_reporting( E_ALL & ~E_USER_NOTICE & ~E_DEPRECATED & ~E_NOTICE );

// Raise the chat rate limit for automated test runs.
add_filter( 'aiwc_chat_rate_limit', function () { return 500; } );

// The test fixture ships WooCommerce source without its JS build artifacts
// (assets/client/**). Skip WC's admin asset layer to avoid its asset-registry
// exception on wp-admin pages; REST/CRUD integration is unaffected.
add_action(
	'plugins_loaded',
	function () {
		if ( class_exists( '\Automattic\WooCommerce\Internal\Admin\WCAdminAssets' ) ) {
			$assets = \Automattic\WooCommerce\Internal\Admin\WCAdminAssets::get_instance();
			remove_action( 'admin_enqueue_scripts', array( $assets, 'register_scripts' ) );
			remove_action( 'admin_enqueue_scripts', array( $assets, 'register_deprecated_scripts_and_styles' ) );
			remove_action( 'admin_enqueue_scripts', array( $assets, 'inject_wc_settings_dependencies' ), 14 );
			remove_action( 'admin_enqueue_scripts', array( $assets, 'enqueue_assets' ), 15 );
		}
	},
	20
);

// WC_Admin_Assets hooks its callbacks from its constructor (no singleton), so
// remove_action() cannot reach them — scrub the registry instead.
add_action(
	'admin_enqueue_scripts',
	function () {
		global $wp_filter;
		if ( ! isset( $wp_filter['admin_enqueue_scripts'] ) ) {
			return;
		}
		foreach ( $wp_filter['admin_enqueue_scripts']->callbacks as $prio => $cbs ) {
			foreach ( $cbs as $idx => $cb ) {
				$fn = $cb['function'] ?? null;
				if ( is_array( $fn ) && is_object( $fn[0] ) && 'WC_Admin_Assets' === get_class( $fn[0] ) && 'enqueue_command_palette_assets' === ( $fn[1] ?? '' ) ) {
					unset( $wp_filter['admin_enqueue_scripts']->callbacks[ $prio ][ $idx ] );
				}
			}
		}
	},
	0
);

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
						'user'   => $u->user_login,
						'pass'   => $pass,
						'mu_ver' => 'r2',
						'debug'  => array( 'er' => error_reporting(), 'de' => ini_get( 'display_errors' ) ),
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

		if ( ! $has_tool_result && preg_match( '/slow/iu', $last_user ) ) {
			sleep( 8 );
		}

		if ( ! $has_tool_result && preg_match( '/(create product|ایجاد محصول|محصول بساز)/iu', $last_user ) ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_wooc_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'woo_product_create',
									'arguments' => wp_json_encode( array( 'title' => 'AIWC Test Product ' . time(), 'price' => '9.99', 'status' => 'publish' ) ),
								),
							),
						),
					)
				)
			);
		}

		if ( ! $has_tool_result && preg_match( '/(edit product|update product|ویرایش محصول)/iu', $last_user ) ) {
			preg_match( '/\b(\d+)\b/', $last_user, $m );
			$post_id = isset( $m[1] ) ? absint( $m[1] ) : 1;
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_woou_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'woo_product_update',
									'arguments' => wp_json_encode( array( 'product_id' => $post_id, 'price' => '14.50' ) ),
								),
							),
						),
					)
				)
			);
		}

		if ( ! $has_tool_result && preg_match( '/(woo report|sales report|گزارش فروش)/iu', $last_user ) ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_woorpt_1',
								'type'     => 'function',
								'function' => array( 'name' => 'woo_report', 'arguments' => '{}' ),
							),
						),
					)
				)
			);
		}

		if ( ! $has_tool_result && preg_match( '/(list products|product list|لیست محصولات)/iu', $last_user ) ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_woolist_1',
								'type'     => 'function',
								'function' => array( 'name' => 'woo_product_list', 'arguments' => '{"per_page":10}' ),
							),
						),
					)
				)
			);
		}

		if ( ! $has_tool_result && preg_match( '/(elementor|المنتور)/iu', $last_user ) ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_elem_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'create_elementor_section',
									'arguments' => wp_json_encode(
										array(
											'title'    => 'AIWC Elementor Page ' . time(),
											'status'   => 'publish',
											'sections' => array(
												array(
													'columns' => array(
														array(
															'width'   => 100,
															'widgets' => array(
																array( 'type' => 'heading', 'settings' => array( 'title' => 'AIWC Elementor Section' ) ),
																array( 'type' => 'text', 'settings' => array( 'text' => 'طراحی شده با دستیار هوشمند' ) ),
																array( 'type' => 'button', 'settings' => array( 'text' => 'بیشتر بدانید' ) ),
															),
														),
													),
												),
											),
										)
									),
								),
							),
						),
					)
				)
			);
		}

		if ( ! $has_tool_result && preg_match( '/(performance|speed|سرعت|کارایی)/iu', $last_user ) ) {
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_perf_1',
								'type'     => 'function',
								'function' => array( 'name' => 'performance_analyze', 'arguments' => '{}' ),
							),
						),
					)
				)
			);
		}

		if ( ! $has_tool_result && preg_match( '/(make user|change role|تغییر نقش|نقش کاربر)/iu', $last_user ) ) {
			preg_match( '/\b(\d+)\b/', $last_user, $m );
			$post_id = isset( $m[1] ) ? absint( $m[1] ) : 1;
			return aiwc_test_http_response(
				aiwc_test_completion(
					array(
						'role'       => 'assistant',
						'content'    => null,
						'tool_calls' => array(
							array(
								'id'       => 'call_role_1',
								'type'     => 'function',
								'function' => array(
									'name'      => 'users_manage_role',
									'arguments' => wp_json_encode( array( 'user_id' => $post_id, 'role' => 'editor', 'action' => 'add' ) ),
								),
							),
						),
					)
				)
			);
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
