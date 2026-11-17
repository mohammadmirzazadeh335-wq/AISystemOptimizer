<?php
/**
 * Site context, content, design and SEO REST endpoints.
 *
 * @package AIWC
 */

namespace AIWC\Api;

defined( 'ABSPATH' ) || exit;

/**
 * Content & site controller.
 */
class Content_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			Api::NS,
			'/site/context',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'site_context' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/content',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'list_content' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/design/css',
			array(
				array(
					'methods'             => \WP_REST_Server::READABLE,
					'callback'            => array( $this, 'get_css' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
				array(
					'methods'             => \WP_REST_Server::CREATABLE,
					'callback'            => array( $this, 'save_css' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
			)
		);

		register_rest_route(
			Api::NS,
			'/seo/report',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'seo_report' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/seo/analyze',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'seo_analyze' ),
				'permission_callback' => array( $this, 'can_manage' ),
				'args'                => array(
					'post_id' => array(
						'type'     => 'integer',
						'required' => true,
					),
				),
			)
		);

		register_rest_route(
			Api::NS,
			'/seo/analyze-site',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'seo_analyze_site' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/stats',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'stats' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);
	}

	/**
	 * GET /site/context
	 *
	 * @return \WP_REST_Response
	 */
	public function site_context() {
		return $this->respond( $this->plugin->get( 'context' )->get_full_context() );
	}

	/**
	 * GET /content?type=page&search=&page=1
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function list_content( \WP_REST_Request $request ) {
		$result = $this->plugin->get( 'context' )->list_content(
			sanitize_text_field( (string) $request->get_param( 'type' ) ),
			(int) $request->get_param( 'page' ),
			(int) $request->get_param( 'per_page' ),
			sanitize_text_field( (string) $request->get_param( 'search' ) )
		);
		return $this->respond( $result );
	}

	/**
	 * GET /design/css
	 *
	 * @return \WP_REST_Response
	 */
	public function get_css() {
		$css = wp_get_custom_css( wp_get_theme()->get_stylesheet() );
		return $this->respond( array( 'css' => $css ) );
	}

	/**
	 * POST /design/css
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function save_css( \WP_REST_Request $request ) {
		$body = $request->get_json_params();
		if ( ! is_array( $body ) ) {
			$body = $request->get_params();
		}
		$css  = isset( $body['css'] ) ? (string) $body['css'] : '';
		$mode = isset( $body['mode'] ) ? sanitize_text_field( $body['mode'] ) : 'replace';

		if ( preg_match( '/(expression\s*\(|@import|javascript:|behavior\s*:|<\s*\/?\s*script)/i', $css ) ) {
			return $this->error( 'aiwc_bad_css', __( 'CSS contains disallowed constructs.', 'ai-wordpress-copilot' ), 400 );
		}

		$result = $this->plugin->get( 'registry' )->execute(
			'update_custom_css',
			array(
				'css'  => $css,
				'mode' => $mode,
			),
			array(
				'command' => 'Manual CSS update from design panel',
				'source'  => 'ui',
			)
		);
		return $this->respond( $result, $result['success'] ? 200 : 400 );
	}

	/**
	 * GET /seo/report
	 *
	 * @return \WP_REST_Response
	 */
	public function seo_report() {
		return $this->respond( $this->plugin->get( 'seo' )->get_site_report() );
	}

	/**
	 * POST /seo/analyze
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response
	 */
	public function seo_analyze( \WP_REST_Request $request ) {
		$result = $this->plugin->get( 'seo' )->analyze_post( (int) $request['post_id'] );
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_code(), $result->get_error_message(), 404 );
		}
		return $this->respond( $result );
	}

	/**
	 * POST /seo/analyze-site
	 *
	 * @return \WP_REST_Response
	 */
	public function seo_analyze_site() {
		$job_id = $this->plugin->get( 'queue' )->push( 'seo_site_analysis', array( 'batch_size' => 10, 'offset' => 0 ) );
		return $this->respond( array( 'job_id' => $job_id ), 201 );
	}

	/**
	 * GET /stats — dashboard numbers.
	 *
	 * @return \WP_REST_Response
	 */
	public function stats() {
		$overview = $this->plugin->get( 'context' )->get_overview();
		$logs     = $this->plugin->get( 'log' )->get_logs( array( 'per_page' => 8 ) );
		$approvals = $this->plugin->get( 'log' )->get_logs( array( 'status' => 'pending', 'per_page' => 20 ) );
		$pending  = array();
		foreach ( $approvals['items'] as $row ) {
			if ( 'pending' === $row['approval'] ) {
				$pending[] = $row;
			}
		}

		return $this->respond(
			array(
				'overview'   => $overview,
				'configured' => \AIWC\Settings::is_configured(),
				'model'      => (string) \AIWC\Settings::get( 'model' ),
				'execution_mode' => (int) \AIWC\Settings::get( 'execution_mode' ),
				'recent_logs' => $logs['items'],
				'pending_approvals' => count( $pending ),
				'total_logs' => $logs['total'],
			)
		);
	}
}
