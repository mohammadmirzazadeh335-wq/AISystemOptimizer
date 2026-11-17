<?php
/**
 * Tools registry REST endpoints.
 *
 * @package AIWC
 */

namespace AIWC\Api;

defined( 'ABSPATH' ) || exit;

/**
 * Tools controller.
 */
class Tools_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			Api::NS,
			'/tools',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'list_tools' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/tools/(?P<name>[a-z0-9_\-]+)',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'toggle_tool' ),
				'permission_callback' => array( $this, 'can_manage' ),
				'args'                => array(
					'enabled' => array(
						'type'     => 'boolean',
						'required' => true,
					),
				),
			)
		);
	}

	/**
	 * GET /tools
	 *
	 * @return \WP_REST_Response
	 */
	public function list_tools() {
		$registry = $this->plugin->get( 'registry' );
		$tools    = $registry->all();
		foreach ( $tools as &$tool ) {
			$tool['enabled'] = $registry->is_enabled( $tool['name'] );
		}
		return $this->respond( array( 'items' => $tools ) );
	}

	/**
	 * POST /tools/{name}
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function toggle_tool( \WP_REST_Request $request ) {
		$name = sanitize_text_field( $request['name'] );
		$registry = $this->plugin->get( 'registry' );
		if ( ! $registry->get( $name ) ) {
			return $this->error( 'aiwc_tool_unknown', __( 'Tool not found.', 'ai-wordpress-copilot' ), 404 );
		}
		$registry->set_enabled( $name, (bool) $request['enabled'] );
		return $this->respond(
			array(
				'name'    => $name,
				'enabled' => $registry->is_enabled( $name ),
			)
		);
	}
}
