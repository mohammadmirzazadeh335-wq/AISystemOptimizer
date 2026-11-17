<?php
/**
 * Activity log REST endpoints.
 *
 * @package AIWC
 */

namespace AIWC\Api;

defined( 'ABSPATH' ) || exit;

/**
 * Log controller.
 */
class Log_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			Api::NS,
			'/logs',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'list_logs' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/logs/(?P<id>\d+)',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'get_log' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/logs/(?P<id>\d+)/restore',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'restore_log' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/logs/filters',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'filters' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);
	}

	/**
	 * GET /logs
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function list_logs( \WP_REST_Request $request ) {
		$result = $this->plugin->get( 'log' )->get_logs(
			array(
				'page'            => (int) $request->get_param( 'page' ),
				'per_page'        => (int) $request->get_param( 'per_page' ),
				'status'          => sanitize_text_field( (string) $request->get_param( 'status' ) ),
				'tool_name'       => sanitize_text_field( (string) $request->get_param( 'tool_name' ) ),
				'conversation_id' => (int) $request->get_param( 'conversation_id' ),
				'search'          => sanitize_text_field( (string) $request->get_param( 'search' ) ),
				'date_from'       => sanitize_text_field( (string) $request->get_param( 'date_from' ) ),
				'date_to'         => sanitize_text_field( (string) $request->get_param( 'date_to' ) ),
			)
		);
		$result['pages'] = (int) ceil( $result['total'] / max( 1, (int) ( $request->get_param( 'per_page' ) ?: 20 ) ) );
		return $this->respond( $result );
	}

	/**
	 * GET /logs/{id}
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function get_log( \WP_REST_Request $request ) {
		$row = $this->plugin->get( 'log' )->get( (int) $request['id'] );
		if ( ! $row ) {
			return $this->error( 'aiwc_not_found', __( 'Log entry not found.', 'ai-wordpress-copilot' ), 404 );
		}
		return $this->respond( $row );
	}

	/**
	 * POST /logs/{id}/restore — rollback the change recorded in this entry.
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function restore_log( \WP_REST_Request $request ) {
		global $wpdb;
		$log_id = (int) $request['id'];
		$row    = $this->plugin->get( 'log' )->get( $log_id );
		if ( ! $row ) {
			return $this->error( 'aiwc_not_found', __( 'Log entry not found.', 'ai-wordpress-copilot' ), 404 );
		}

		// Find the snapshot linked to this log entry.
		$table = \AIWC\Backup\Snapshot_Manager::table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$snapshot_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT id FROM {$table} WHERE log_id = %d ORDER BY id DESC LIMIT 1", $log_id ) );
		if ( ! $snapshot_id ) {
			return $this->error( 'aiwc_no_snapshot', __( 'No rollback snapshot exists for this operation.', 'ai-wordpress-copilot' ), 404 );
		}

		$result = $this->plugin->get( 'snapshots' )->restore( $snapshot_id );
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_code(), $result->get_error_message(), 500 );
		}
		return $this->respond( $result );
	}

	/**
	 * GET /logs/filters
	 *
	 * @return \WP_REST_Response
	 */
	public function filters() {
		return $this->respond(
			array(
				'tools' => $this->plugin->get( 'log' )->tool_names(),
			)
		);
	}
}
