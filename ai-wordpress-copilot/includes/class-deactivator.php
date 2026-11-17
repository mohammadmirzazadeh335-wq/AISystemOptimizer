<?php
/**
 * Plugin deactivation.
 *
 * @package AIWC
 */

namespace AIWC;

defined( 'ABSPATH' ) || exit;

/**
 * Handles plugin deactivation: cron cleanup only (data is preserved).
 */
class Deactivator {

	/**
	 * Run on plugin deactivation.
	 */
	public static function deactivate() {
		$timestamp = wp_next_scheduled( 'aiwc_process_jobs' );
		if ( $timestamp ) {
			wp_unschedule_event( $timestamp, 'aiwc_process_jobs' );
		}
		wp_clear_scheduled_hook( 'aiwc_process_jobs' );
	}
}
