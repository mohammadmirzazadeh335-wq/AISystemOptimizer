<?php
/**
 * Memory REST endpoints.
 *
 * @package AIWC
 */

namespace AIWC\Api;

defined( 'ABSPATH' ) || exit;

/**
 * Memory controller.
 */
class Memory_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			Api::NS,
			'/memory',
			array(
				array(
					'methods'             => \WP_REST_Server::READABLE,
					'callback'            => array( $this, 'list_memory' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
				array(
					'methods'             => \WP_REST_Server::CREATABLE,
					'callback'            => array( $this, 'save_memory' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
			)
		);

		register_rest_route(
			Api::NS,
			'/memory/(?P<id>\d+)',
			array(
				array(
					'methods'             => \WP_REST_Server::DELETABLE,
					'callback'            => array( $this, 'delete_memory' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
				array(
					'methods'             => \WP_REST_Server::CREATABLE,
					'callback'            => array( $this, 'update_memory' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
			)
		);
	}

	/**
	 * GET /memory
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function list_memory( \WP_REST_Request $request ) {
		$category = sanitize_text_field( (string) $request->get_param( 'category' ) );
		return $this->respond(
			array(
				'items' => $this->plugin->get( 'memory' )->all( $category ),
			)
		);
	}

	/**
	 * POST /memory
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function save_memory( \WP_REST_Request $request ) {
		$body = $request->get_json_params();
		if ( ! is_array( $body ) ) {
			$body = $request->get_params();
		}
		$category = isset( $body['category'] ) ? sanitize_text_field( $body['category'] ) : 'general';
		$key      = isset( $body['memory_key'] ) ? (string) $body['memory_key'] : ( isset( $body['key'] ) ? (string) $body['key'] : '' );
		$value    = isset( $body['memory_value'] ) ? (string) $body['memory_value'] : ( isset( $body['value'] ) ? (string) $body['value'] : '' );

		if ( '' === trim( $key ) || '' === trim( $value ) ) {
			return $this->error( 'aiwc_memory_invalid', __( 'Key and value are required.', 'ai-wordpress-copilot' ), 400 );
		}

		$id = $this->plugin->get( 'memory' )->remember( $category, $key, $value, 'manual' );
		if ( ! $id ) {
			return $this->error( 'aiwc_memory_failed', __( 'Failed to save memory.', 'ai-wordpress-copilot' ), 500 );
		}
		return $this->respond( array( 'id' => $id ), 201 );
	}

	/**
	 * POST /memory/{id}
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function update_memory( \WP_REST_Request $request ) {
		$body = $request->get_json_params();
		if ( ! is_array( $body ) ) {
			$body = $request->get_params();
		}
		$ok = $this->plugin->get( 'memory' )->update( (int) $request['id'], is_array( $body ) ? $body : array() );
		if ( ! $ok ) {
			return $this->error( 'aiwc_memory_failed', __( 'Update failed.', 'ai-wordpress-copilot' ), 500 );
		}
		return $this->respond( array( 'id' => (int) $request['id'], 'updated' => true ) );
	}

	/**
	 * DELETE /memory/{id}
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function delete_memory( \WP_REST_Request $request ) {
		$ok = $this->plugin->get( 'memory' )->forget( (int) $request['id'] );
		if ( ! $ok ) {
			return $this->error( 'aiwc_memory_missing', __( 'Memory not found.', 'ai-wordpress-copilot' ), 404 );
		}
		return $this->respond( array( 'deleted' => true ) );
	}
}
