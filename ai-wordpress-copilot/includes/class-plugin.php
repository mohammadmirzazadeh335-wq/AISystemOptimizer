<?php
/**
 * Main plugin orchestrator.
 *
 * @package AIWC
 */

namespace AIWC;

defined( 'ABSPATH' ) || exit;

/**
 * Wires all services and hooks.
 */
class Plugin {

	/**
	 * Singleton.
	 *
	 * @var Plugin|null
	 */
	private static $instance = null;

	/**
	 * Service container.
	 *
	 * @var array
	 */
	private $services = array();

	/**
	 * Get singleton instance.
	 *
	 * @return Plugin
	 */
	public static function instance() {
		if ( null === self::$instance ) {
			self::$instance = new self();
			self::$instance->boot();
		}
		return self::$instance;
	}

	/**
	 * Get a service by id.
	 *
	 * @param string $id Service id.
	 * @return object|null
	 */
	public function get( $id ) {
		return isset( $this->services[ $id ] ) ? $this->services[ $id ] : null;
	}

	/**
	 * Register a service.
	 *
	 * @param string $id      Service id.
	 * @param object $service Service instance.
	 */
	public function set( $id, $service ) {
		$this->services[ $id ] = $service;
	}

	/**
	 * Boot services and hooks.
	 */
	private function boot() {
		load_plugin_textdomain( 'ai-wordpress-copilot', false, dirname( plugin_basename( AIWC_FILE ) ) . '/languages' );

		// Core services.
		$this->set( 'log', new Log\Activity_Log() );
		$this->set( 'snapshots', new Backup\Snapshot_Manager( $this->get( 'log' ) ) );
		$this->set( 'conversations', new Chat\Conversation_Store() );
		$this->set( 'memory', new Memory\Memory_Store() );
		$this->set( 'context', new Context\Site_Context_Engine() );
		$this->set( 'queue', new Queue\Job_Queue() );
		$this->set( 'seo', new Seo\Seo_Analyzer( $this->get( 'context' ) ) );
		$this->set( 'link_checker', new Seo\Link_Checker( $this ) );

		// AI layer.
		$client  = new Ai\OpenAI_Client();
		$registry = new Ai\Tool_Registry();
		$this->set( 'client', $client );
		$this->set( 'registry', $registry );
		$this->set( 'agent', new Ai\Agent( $client, $registry, $this->get( 'conversations' ), $this->get( 'memory' ), $this->get( 'context' ), $this->get( 'log' ), $this->get( 'snapshots' ) ) );

		// Tool groups.
		Activator::maybe_upgrade();
		$registry->register_group( new Ai\Tools\Core_Tools( $this ) );
		$registry->register_group( new Ai\Tools\Content_Tools( $this ) );
		$registry->register_group( new Ai\Tools\Design_Tools( $this ) );
		$registry->register_group( new Ai\Tools\Seo_Tools( $this ) );
		$registry->register_group( new Ai\Tools\Woo_Tools( $this ) );
		$registry->register_group( new Ai\Tools\System_Tools( $this ) );
		$registry->register_group( new Ai\Tools\Performance_Tools( $this ) );

		// Admin + REST.
		if ( is_admin() ) {
			$admin = new Admin\Admin( $this );
			$this->set( 'admin', $admin );
			add_action( 'admin_menu', array( $admin, 'register_menus' ) );
			add_action( 'admin_enqueue_scripts', array( $admin, 'enqueue_assets' ) );
			add_action( 'admin_notices', array( $admin, 'maybe_config_notice' ) );
		}

		$api = new Api\Api( $this );
		$this->set( 'api', $api );
		add_action( 'rest_api_init', array( $api, 'register_routes' ) );

		// Cron + housekeeping.
		add_filter( 'cron_schedules', array( $this, 'cron_schedules' ) );
		add_action( 'aiwc_process_jobs', array( $this, 'process_jobs' ) );

		// Context cache invalidation.
		add_action( 'save_post', array( $this->get( 'context' ), 'invalidate' ), 20 );
		add_action( 'switch_theme', array( $this->get( 'context' ), 'invalidate' ) );
		add_action( 'activated_plugin', array( $this->get( 'context' ), 'invalidate' ) );
		add_action( 'deactivated_plugin', array( $this->get( 'context' ), 'invalidate' ) );
		add_action( 'wp_update_nav_menu', array( $this->get( 'context' ), 'invalidate' ) );
		add_action( 'aiwc_memory_updated', array( $this->get( 'context' ), 'invalidate' ) );
	}

	/**
	 * Add custom cron interval.
	 *
	 * @param array $schedules Cron schedules.
	 * @return array
	 */
	public function cron_schedules( $schedules ) {
		$schedules['aiwc_five_minutes'] = array(
			'interval' => 300,
			'display'  => 'AIWC Every Five Minutes',
		);
		return $schedules;
	}

	/**
	 * Process pending queue jobs (WP-Cron callback).
	 */
	public function process_jobs() {
		$queue = $this->get( 'queue' );
		$queue->process_until_empty( 5 );
	}
}
