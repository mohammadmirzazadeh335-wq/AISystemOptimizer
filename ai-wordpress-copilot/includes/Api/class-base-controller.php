<?php
/**
 * Base REST controller.
 *
 * @package AIWC
 */

namespace AIWC\Api;

use AIWC\Plugin;
use AIWC\Security\Permissions;

defined( 'ABSPATH' ) || exit;

/**
 * Shared helpers for REST controllers.
 */
abstract class Base_Controller {

	/**
	 * Plugin instance.
	 *
	 * @var Plugin
	 */
	protected $plugin;

	/**
	 * Constructor.
	 *
	 * @param Plugin $plugin Plugin instance.
	 */
	public function __construct( Plugin $plugin ) {
		$this->plugin = $plugin;
	}

	/**
	 * Register routes (implemented by children).
	 */
	abstract public function register_routes();

	/**
	 * Admin permission callback.
	 *
	 * @return bool
	 */
	public function can_manage() {
		return Permissions::rest_admin();
	}

	/**
	 * Wrap a value in a consistent response envelope.
	 *
	 * @param mixed  $data    Data.
	 * @param int    $status  HTTP status.
	 * @param array  $headers Extra headers.
	 * @return \WP_REST_Response
	 */
	protected function respond( $data, $status = 200, array $headers = array() ) {
		return new \WP_REST_Response( $data, $status, $headers );
	}

	/**
	 * Standard error response.
	 *
	 * @param string $code    Error code.
	 * @param string $message Message.
	 * @param int    $status  HTTP status.
	 * @return \WP_Error
	 */
	protected function error( $code, $message, $status = 400 ) {
		return new \WP_Error( $code, $message, array( 'status' => $status ) );
	}
}
