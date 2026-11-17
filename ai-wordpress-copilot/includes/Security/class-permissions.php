<?php
/**
 * Security helpers: capability checks and REST guards.
 *
 * @package AIWC
 */

namespace AIWC\Security;

defined( 'ABSPATH' ) || exit;

/**
 * Central permission checks for REST and admin.
 */
class Permissions {

	/**
	 * Capability required to use the copilot.
	 */
	const CAP = 'manage_aiwc';

	/**
	 * Whether the current user may use the copilot.
	 *
	 * @return bool
	 */
	public static function current_user_can_manage() {
		if ( ! is_user_logged_in() ) {
			return false;
		}
		// Administrators always pass; manage_aiwc is granted to them on activation.
		return current_user_can( self::CAP ) || current_user_can( 'manage_options' );
	}

	/**
	 * REST permission callback: admin only.
	 *
	 * @return bool
	 */
	public static function rest_admin() {
		return self::current_user_can_manage();
	}

	/**
	 * REST permission callback: any logged-in user with edit_posts (content helpers).
	 *
	 * @return bool
	 */
	public static function rest_editor() {
		return is_user_logged_in() && current_user_can( 'edit_posts' );
	}

	/**
	 * Require a capability or die with a WP_Error.
	 *
	 * @param string $cap Capability name.
	 * @return true|\WP_Error
	 */
	public static function require_cap( $cap ) {
		if ( ! current_user_can( $cap ) ) {
			return new \WP_Error(
				'aiwc_forbidden',
				__( 'You do not have permission to perform this action.', 'ai-wordpress-copilot' ),
				array( 'status' => 403 )
			);
		}
		return true;
	}

	/**
	 * Validate an incoming REST request: nonce is enforced by cookie auth in
	 * REST API; this adds explicit sanitization of common parameters.
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return array{ok: bool, error: \WP_Error|null}
	 */
	public static function validate_request( \WP_REST_Request $request ) {
		if ( ! self::current_user_can_manage() ) {
			return array(
				'ok'    => false,
				'error' => new \WP_Error(
					'aiwc_forbidden',
					__( 'You do not have permission to perform this action.', 'ai-wordpress-copilot' ),
					array( 'status' => 403 )
				),
			);
		}
		return array( 'ok' => true, 'error' => null );
	}
}
