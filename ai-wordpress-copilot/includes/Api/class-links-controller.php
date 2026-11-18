<?php
/**
 * REST endpoints for the external link checker.
 *
 * @package AIWC
 */

namespace AIWC\Api;

use AIWC\Settings;

defined( 'ABSPATH' ) || exit;

/**
 * Class Links_Controller
 */
class Links_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			Api::NS,
			'/links/scan',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'scan' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/links/check',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'check' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/links/report',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'report' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/links/cancel',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'cancel' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);
	}

	/**
	 * POST /links/scan — extract and enqueue links.
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function scan( \WP_REST_Request $request ) {
		$post_id = isset( $request['post_id'] ) ? (int) $request['post_id'] : 0;
		$result  = $this->plugin->get( 'link_checker' )->scan( $post_id );
		return $this->respond( $result );
	}

	/**
	 * POST /links/check — run one batch of pending checks.
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function check( \WP_REST_Request $request ) {
		$limit  = isset( $request['limit'] ) ? (int) $request['limit'] : 10;
		$force  = ! empty( $request['force'] );
		$result = $this->plugin->get( 'link_checker' )->check_pending( $limit, $force );
		return $this->respond( $result );
	}

	/**
	 * GET /links/report — grouped report with suggestions.
	 *
	 * @return \WP_REST_Response
	 */
	public function report() {
		return $this->respond( $this->plugin->get( 'link_checker' )->report() );
	}

	/**
	 * POST /links/cancel — cooperative cancellation.
	 *
	 * @return \WP_REST_Response
	 */
	public function cancel() {
		$this->plugin->get( 'link_checker' )->cancel();
		return $this->respond( array( 'cancelling' => true ) );
	}
}
