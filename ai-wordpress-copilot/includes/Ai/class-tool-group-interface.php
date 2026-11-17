<?php
/**
 * Tool group contract.
 *
 * @package AIWC
 */

namespace AIWC\Ai;

defined( 'ABSPATH' ) || exit;

/**
 * A tool group declares one or more callable tools and dispatches them.
 */
interface Tool_Group_Interface {

	/**
	 * Declare tools.
	 *
	 * Each tool definition:
	 *  - name (string, snake_case, unique)
	 *  - description (string)
	 *  - parameters (array JSON schema object: type/properties/required)
	 *  - risk (string) read|write|destructive|critical
	 *  - capability (string) WP capability required (default manage_aiwc)
	 *  - handler (string) method name on this class receiving ($args, $context)
	 *  - needs_confirmation (bool) force approval even in auto mode
	 *
	 * @return array[]
	 */
	public function tools();

	/**
	 * Execute a tool of this group.
	 *
	 * @param string $name    Tool name.
	 * @param array  $args    Validated arguments.
	 * @param array  $context Execution context (conversation_id, command, source).
	 * @return array Standard result: {success: bool, data: mixed, summary: string, snapshot_id?: int, log_id?: int}
	 */
	public function execute( $name, array $args, array $context = array() );
}
