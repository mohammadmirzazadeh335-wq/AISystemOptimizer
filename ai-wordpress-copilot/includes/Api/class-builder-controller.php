<?php
/**
 * REST controller for the Website Builder section:
 * design system, reusable components, designed pages.
 *
 * @package AIWC
 */

namespace AIWC\Api;

use AIWC\Builder\Design_Engine;
use AIWC\Builder\Design_System;
use AIWC\Builder\Section_Library;

defined( 'ABSPATH' ) || exit;

/**
 * Builder_Controller
 */
class Builder_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			\AIWC\Api\Api::NS,
			'/builder/status',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_status' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			\AIWC\Api\Api::NS,
			'/builder/design-system',
			array(
				array(
					'methods'             => 'GET',
					'callback'            => array( $this, 'get_design_system' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
				array(
					'methods'             => 'POST',
					'callback'            => array( $this, 'update_design_system' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
			)
		);

		register_rest_route(
			\AIWC\Api\Api::NS,
			'/builder/components',
			array(
				array(
					'methods'             => 'GET',
					'callback'            => array( $this, 'list_components' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
				array(
					'methods'             => 'POST',
					'callback'            => array( $this, 'manage_component' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
			)
		);

		register_rest_route(
			\AIWC\Api\Api::NS,
			'/builder/pages',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_pages' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);
	}

	/**
	 * GET /builder/status
	 *
	 * @return \WP_REST_Response
	 */
	public function get_status() {
		return $this->respond( Design_Engine::status() );
	}

	/**
	 * GET /builder/design-system
	 *
	 * @return \WP_REST_Response
	 */
	public function get_design_system() {
		$detected = Design_System::detect();
		return $this->respond(
			array(
				'system'   => Design_System::get(),
				'detected' => array(
					'source' => isset( $detected['source'] ) ? $detected['source'] : 'theme',
					'tokens' => isset( $detected['tokens'] ) ? $detected['tokens'] : array(),
				),
				'css'      => Design_System::to_css_vars(),
			)
		);
	}

	/**
	 * POST /builder/design-system — patch the central design system.
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function update_design_system( $request ) {
		$patch = $request->get_json_params();
		if ( ! is_array( $patch ) || empty( $patch ) ) {
			return $this->error( 'aiwc_builder_empty_patch', 'Provide at least one design token to update.', 400 );
		}
		// Accept either a nested {colors:{primary}} or flat {primary} patch.
		$system = Design_System::update( $patch );
		return $this->respond( array( 'system' => $system, 'updated' => true ) );
	}

	/**
	 * GET /builder/components
	 *
	 * @return \WP_REST_Response
	 */
	public function list_components() {
		return $this->respond(
			array(
				'items' => Section_Library::list_components(),
				'types' => array_keys( Section_Library::types() ),
			)
		);
	}

	/**
	 * POST /builder/components — save/delete a reusable component.
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function manage_component( $request ) {
		$name   = sanitize_text_field( (string) $request->get_param( 'name' ) );
		$action = sanitize_key( (string) $request->get_param( 'action' ) );
		if ( '' === $name ) {
			return $this->error( 'aiwc_builder_name_required', 'Component name is required.', 400 );
		}
		if ( 'delete' === $action ) {
			Section_Library::delete_component( $name );
			return $this->respond( array( 'deleted' => true, 'name' => $name ) );
		}
		$spec = $request->get_param( 'spec' );
		if ( ! is_array( $spec ) ) {
			return $this->error( 'aiwc_builder_spec_required', 'Component spec must be an object.', 400 );
		}
		$saved = Section_Library::save_component( $name, $spec );
		return $this->respond( array( 'saved' => true, 'name' => $name, 'component' => $saved ) );
	}

	/**
	 * GET /builder/pages — pages designed by the builder/redesign engine.
	 *
	 * @return \WP_REST_Response
	 */
	public function list_pages() {
		$query = new \WP_Query(
			array(
				'post_type'      => 'page',
				'post_status'    => array( 'publish', 'draft' ),
				'posts_per_page' => 50,
				'meta_key'       => '_aiwc_built', // phpcs:ignore WordPress.DB.SlowDBQuery
				'orderby'        => 'modified',
				'order'          => 'DESC',
				'no_found_rows'  => false,
			)
		);
		$items = array();
		foreach ( $query->posts as $post ) {
			$built = get_post_meta( $post->ID, '_aiwc_built', true );
			$items[] = array(
				'id'        => (int) $post->ID,
				'title'     => get_the_title( $post ),
				'url'       => get_permalink( $post ),
				'edit_url'  => get_edit_post_link( $post->ID, 'raw' ),
				'status'    => $post->post_status,
				'modified'  => $post->post_modified,
				'builder'   => is_array( $built ) && isset( $built['builder'] ) ? $built['builder'] : 'unknown',
				'built_at'  => is_array( $built ) && isset( $built['built_at'] ) ? $built['built_at'] : '',
			);
		}
		return $this->respond(
			array(
				'items' => $items,
				'total' => (int) $query->found_posts,
			)
		);
	}
}
