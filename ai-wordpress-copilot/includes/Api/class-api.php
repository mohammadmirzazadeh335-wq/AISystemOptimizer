<?php
/**
 * REST API registrar.
 *
 * @package AIWC
 */

namespace AIWC\Api;

use AIWC\Plugin;

defined( 'ABSPATH' ) || exit;

/**
 * Registers all REST controllers.
 */
class Api {

	/**
	 * REST namespace.
	 */
	const NS = 'ai-copilot/v1';

	/**
	 * Plugin instance.
	 *
	 * @var Plugin
	 */
	private $plugin;

	/**
	 * Controllers.
	 *
	 * @var array
	 */
	private $controllers = array();

	/**
	 * Constructor.
	 *
	 * @param Plugin $plugin Plugin instance.
	 */
	public function __construct( Plugin $plugin ) {
		$this->plugin = $plugin;
		$this->controllers = array(
			new Chat_Controller( $plugin ),
			new Settings_Controller( $plugin ),
			new Tools_Controller( $plugin ),
			new Content_Controller( $plugin ),
			new Log_Controller( $plugin ),
			new Memory_Controller( $plugin ),
			new Jobs_Controller( $plugin ),
		);
	}

	/**
	 * Register routes on rest_api_init.
	 */
	public function register_routes() {
		foreach ( $this->controllers as $controller ) {
			$controller->register_routes();
		}
	}
}
