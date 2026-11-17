<?php
/**
 * Background jobs REST endpoints.
 *
 * @package AIWC
 */

namespace AIWC\Api;

defined( 'ABSPATH' ) || exit;

/**
 * Jobs controller.
 */
class Jobs_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			Api::NS,
			'/jobs',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'list_jobs' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/jobs/(?P<id>\d+)/run',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'run_job' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/jobs/(?P<id>\d+)',
			array(
				'methods'             => \WP_REST_Server::DELETABLE,
				'callback'            => array( $this, 'delete_job' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);
	}

	/**
	 * GET /jobs
	 *
	 * @return \WP_REST_Response
	 */
	public function list_jobs() {
		return $this->respond(
			array(
				'items' => $this->plugin->get( 'queue' )->list_jobs( 25 ),
			)
		);
	}

	/**
	 * POST /jobs/{id}/run — process immediately (also used in tests).
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function run_job( \WP_REST_Request $request ) {
		$queue = $this->plugin->get( 'queue' );
		$job   = $queue->get( (int) $request['id'] );
		if ( ! $job ) {
			return $this->error( 'aiwc_job_missing', __( 'Job not found.', 'ai-wordpress-copilot' ), 404 );
		}
		$queue->process_until_empty( 8 );
		return $this->respond( $queue->get( (int) $request['id'] ) );
	}

	/**
	 * DELETE /jobs/{id}
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function delete_job( \WP_REST_Request $request ) {
		$this->plugin->get( 'queue' )->delete( (int) $request['id'] );
		return $this->respond( array( 'deleted' => true ) );
	}
}
