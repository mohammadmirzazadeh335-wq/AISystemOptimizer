<?php
/**
 * Uninstall handler: removes plugin data when deleted from the admin.
 *
 * @package AIWC
 */

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

global $wpdb;

$tables = array(
	'aiwc_conversations',
	'aiwc_messages',
	'aiwc_activity_log',
	'aiwc_snapshots',
	'aiwc_jobs',
	'aiwc_memory',
);

foreach ( $tables as $table ) {
	// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	$wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}{$table}" );
}

delete_option( 'aiwc_settings' );
delete_option( 'aiwc_tool_toggles' );
delete_option( 'aiwc_db_version' );
delete_option( 'aiwc_activated_at' );
delete_option( 'aiwc_seo_report' );
delete_option( 'aiwc_custom_css_backup' );

wp_clear_scheduled_hook( 'aiwc_process_jobs' );

$role = get_role( 'administrator' );
if ( $role ) {
	$role->remove_cap( 'manage_aiwc' );
}
