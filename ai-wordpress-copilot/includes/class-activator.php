<?php
/**
 * Activation / deactivation lifecycle.
 *
 * @package AIWC
 */

namespace AIWC;

defined( 'ABSPATH' ) || exit;

/**
 * Handles plugin activation: tables, roles, defaults, cron.
 */
class Activator {

	/**
	 * Run on plugin activation.
	 */
	public static function activate() {
		self::create_tables();
		self::seed_defaults();
		self::register_capabilities();
		update_option( 'aiwc_db_version', AIWC_DB_VERSION );
		update_option( 'aiwc_activated_at', current_time( 'mysql' ) );
		if ( ! wp_next_scheduled( 'aiwc_process_jobs' ) ) {
			wp_schedule_event( time() + 60, 'aiwc_five_minutes', 'aiwc_process_jobs' );
		}
		flush_rewrite_rules();
	}

	/**
	 * Create custom database tables.
	 */
	public static function create_tables() {
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';

		$charset = $wpdb->get_charset_collate();
		$p       = $wpdb->prefix;

		$sql = array();

		$sql[] = "CREATE TABLE {$p}aiwc_conversations (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			user_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
			title VARCHAR(255) NOT NULL DEFAULT '',
			model VARCHAR(191) NOT NULL DEFAULT '',
			tokens_used BIGINT UNSIGNED NOT NULL DEFAULT 0,
			created_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			updated_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			PRIMARY KEY  (id),
			KEY user_id (user_id),
			KEY updated_at (updated_at)
		) $charset;";

		$sql[] = "CREATE TABLE {$p}aiwc_messages (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			conversation_id BIGINT UNSIGNED NOT NULL,
			role VARCHAR(20) NOT NULL DEFAULT 'user',
			content LONGTEXT NULL,
			tool_calls_json LONGTEXT NULL,
			tool_call_id VARCHAR(64) NULL DEFAULT NULL,
			tool_name VARCHAR(191) NULL DEFAULT NULL,
			status VARCHAR(20) NOT NULL DEFAULT 'ok',
			tokens INT UNSIGNED NOT NULL DEFAULT 0,
			created_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			PRIMARY KEY  (id),
			KEY conversation_id (conversation_id),
			KEY role (role)
		) $charset;";

		$sql[] = "CREATE TABLE {$p}aiwc_activity_log (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			user_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
			conversation_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
			command TEXT NULL,
			tool_name VARCHAR(191) NOT NULL DEFAULT '',
			object_type VARCHAR(50) NOT NULL DEFAULT '',
			object_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
			summary TEXT NULL,
			args_json LONGTEXT NULL,
			status VARCHAR(20) NOT NULL DEFAULT 'success',
			before_state LONGTEXT NULL,
			after_state LONGTEXT NULL,
			error TEXT NULL,
			tokens INT UNSIGNED NOT NULL DEFAULT 0,
			duration_ms INT UNSIGNED NOT NULL DEFAULT 0,
			approval VARCHAR(20) NOT NULL DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			PRIMARY KEY  (id),
			KEY status (status),
			KEY tool_name (tool_name),
			KEY created_at (created_at),
			KEY conversation_id (conversation_id)
		) $charset;";

		$sql[] = "CREATE TABLE {$p}aiwc_snapshots (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			log_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
			object_type VARCHAR(50) NOT NULL DEFAULT '',
			object_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
			before_state LONGTEXT NULL,
			after_state LONGTEXT NULL,
			restored_at DATETIME NULL DEFAULT NULL,
			created_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			PRIMARY KEY  (id),
			KEY object_type (object_type,object_id),
			KEY log_id (log_id)
		) $charset;";

		$sql[] = "CREATE TABLE {$p}aiwc_jobs (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			type VARCHAR(50) NOT NULL DEFAULT '',
			payload LONGTEXT NULL,
			status VARCHAR(20) NOT NULL DEFAULT 'pending',
			attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
			max_attempts TINYINT UNSIGNED NOT NULL DEFAULT 3,
			result LONGTEXT NULL,
			error TEXT NULL,
			scheduled_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			started_at DATETIME NULL DEFAULT NULL,
			finished_at DATETIME NULL DEFAULT NULL,
			created_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			PRIMARY KEY  (id),
			KEY status (status),
			KEY type (type)
		) $charset;";

		$sql[] = "CREATE TABLE {$p}aiwc_memory (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			category VARCHAR(50) NOT NULL DEFAULT 'general',
			memory_key VARCHAR(191) NOT NULL DEFAULT '',
			memory_value LONGTEXT NULL,
			source VARCHAR(20) NOT NULL DEFAULT 'manual',
			updated_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			created_at DATETIME NOT NULL DEFAULT '0000-00-00 00:00:00',
			PRIMARY KEY  (id),
			KEY category (category),
			UNIQUE KEY memory_key (memory_key)
		) $charset;";

		foreach ( $sql as $statement ) {
			dbDelta( $statement );
		}
	}

	/**
	 * Seed default options if missing.
	 */
	public static function seed_defaults() {
		$settings = get_option( 'aiwc_settings', null );
		if ( null === $settings ) {
			add_option( 'aiwc_settings', Settings::defaults() );
		}
		if ( false === get_option( 'aiwc_tool_toggles', false ) ) {
			add_option( 'aiwc_tool_toggles', array() );
		}
		if ( false === get_option( 'aiwc_memory_flag', false ) ) {
			add_option( 'aiwc_memory_flag', array() );
		}
	}

	/**
	 * Register the manage capability for administrators.
	 */
	public static function register_capabilities() {
		$role = get_role( 'administrator' );
		if ( $role && ! $role->has_cap( 'manage_aiwc' ) ) {
			$role->add_cap( 'manage_aiwc' );
		}
	}
}

