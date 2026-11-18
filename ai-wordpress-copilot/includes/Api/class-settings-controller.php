<?php
/**
 * Settings and API-connection REST endpoints.
 *
 * @package AIWC
 */

namespace AIWC\Api;

use AIWC\Settings;

defined( 'ABSPATH' ) || exit;

/**
 * Settings controller.
 */
class Settings_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			Api::NS,
			'/settings',
			array(
				array(
					'methods'             => \WP_REST_Server::READABLE,
					'callback'            => array( $this, 'get_settings' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
				array(
					'methods'             => \WP_REST_Server::CREATABLE,
					'callback'            => array( $this, 'update_settings' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
			)
		);

		register_rest_route(
			Api::NS,
			'/settings/test',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'test_connection' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/settings/detect-capabilities',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'detect_capabilities' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/models',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'list_models' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);
	}

	/**
	 * GET /settings (masked).
	 *
	 * @return \WP_REST_Response
	 */
	public function get_settings() {
		return $this->respond( Settings::masked() );
	}

	/**
	 * POST /settings
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function update_settings( \WP_REST_Request $request ) {
		$params = $request->get_json_params();
		if ( ! is_array( $params ) ) {
			$params = $request->get_params();
		}
		$saved = Settings::save( is_array( $params ) ? $params : array() );
		return $this->respond( Settings::masked() );
	}

	/**
	 * POST /settings/test
	 *
	 * @return \WP_REST_Response
	 */
	public function test_connection() {
		$result = $this->plugin->get( 'client' )->test_connection();
		return $this->respond( $result, $result['ok'] ? 200 : 502 );
	}

	/**
	 * POST /settings/detect-capabilities — probe the model for tool calling /
	 * streaming / JSON mode / context window and cache the result.
	 *
	 * @param \WP_REST_Request $request Request (optional "force"=false).
	 * @return \WP_REST_Response
	 */
	public function detect_capabilities( \WP_REST_Request $request ) {
		$force = ! empty( $request['force'] );
		$caps  = $this->plugin->get( 'client' )->detect_capabilities( $force );
		return $this->respond( $caps );
	}

	/**
	 * GET /models
	 *
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function list_models() {
		$result = $this->plugin->get( 'client' )->list_models();
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_code(), $result->get_error_message(), 502 );
		}
		return $this->respond( $result );
	}
}
