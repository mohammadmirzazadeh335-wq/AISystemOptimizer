<?php
/**
 * Tool registry: flattens tool groups, exposes OpenAI schemas, executes safely.
 *
 * @package AIWC
 */

namespace AIWC\Ai;

defined( 'ABSPATH' ) || exit;

/**
 * Holds all available tools and their metadata.
 */
class Tool_Registry {

	/**
	 * Registered groups.
	 *
	 * @var Tool_Group_Interface[]
	 */
	private $groups = array();

	/**
	 * Flattened tool definitions indexed by name.
	 *
	 * @var array[]
	 */
	private $tools = array();

	/**
	 * Register a tool group.
	 *
	 * @param Tool_Group_Interface $group Group instance.
	 */
	public function register_group( Tool_Group_Interface $group ) {
		$this->groups[] = $group;
		foreach ( $group->tools() as $tool ) {
			if ( empty( $tool['name'] ) || empty( $tool['handler'] ) ) {
				continue;
			}
			$tool['group']             = $group;
			$tool['risk']              = isset( $tool['risk'] ) ? $tool['risk'] : 'write';
			$tool['capability']        = isset( $tool['capability'] ) ? $tool['capability'] : 'manage_aiwc';
			$tool['needs_confirmation'] = ! empty( $tool['needs_confirmation'] );
			$this->tools[ $tool['name'] ] = $tool;
		}
	}

	/**
	 * All tool definitions (metadata only, no closures).
	 *
	 * @return array[]
	 */
	public function all() {
		$out = array();
		foreach ( $this->tools as $name => $tool ) {
			$out[] = array(
				'name'              => $name,
				'description'       => $tool['description'],
				'parameters'        => $tool['parameters'],
				'risk'              => $tool['risk'],
				'capability'        => $tool['capability'],
				'needs_confirmation' => $tool['needs_confirmation'],
				'read_only'         => 'read' === $tool['risk'],
			);
		}
		return $out;
	}

	/**
	 * Get one tool definition.
	 *
	 * @param string $name Tool name.
	 * @return array|null
	 */
	public function get( $name ) {
		return isset( $this->tools[ $name ] ) ? $this->tools[ $name ] : null;
	}

	/**
	 * Tool enabled state (admin toggle; default enabled).
	 *
	 * @param string $name Tool name.
	 * @return bool
	 */
	public function is_enabled( $name ) {
		$toggles = get_option( 'aiwc_tool_toggles', array() );
		if ( ! is_array( $toggles ) ) {
			return true;
		}
		return ! isset( $toggles[ $name ] ) || false !== $toggles[ $name ];
	}

	/**
	 * Enable / disable a tool.
	 *
	 * @param string $name    Tool name.
	 * @param bool   $enabled Enabled state.
	 * @return bool
	 */
	public function set_enabled( $name, $enabled ) {
		$toggles = get_option( 'aiwc_tool_toggles', array() );
		if ( ! is_array( $toggles ) ) {
			$toggles = array();
		}
		$toggles[ $name ] = (bool) $enabled;
		update_option( 'aiwc_tool_toggles', $toggles );
		return true;
	}

	/**
	 * OpenAI function-calling schemas, filtered by execution mode and toggles.
	 *
	 * @param int  $execution_mode Current execution mode.
	 * @param bool $include_mutable Whether to include mutating tools.
	 * @return array OpenAI tools array.
	 */
	public function openai_tools( $execution_mode, $include_mutable = true ) {
		$schemas = array();
		foreach ( $this->tools as $name => $tool ) {
			if ( ! $this->is_enabled( $name ) ) {
				continue;
			}
			$is_read = 'read' === $tool['risk'];
			if ( ! $include_mutable && ! $is_read ) {
				continue;
			}
			$schemas[] = array(
				'type'        => 'function',
				'function'    => array(
					'name'        => $name,
					'description' => $tool['description'],
					'parameters'  => $tool['parameters'],
				),
			);
		}
		// Respect max tools per request (keep read-only first).
		$max = (int) \AIWC\Settings::get( 'max_tools_per_request', 8 );
		if ( count( $schemas ) > $max ) {
			$schemas = array_slice( $schemas, 0, $max );
		}
		return $schemas;
	}

	/**
	 * Execute a tool with permission checks, logging and snapshots.
	 *
	 * @param string $name    Tool name.
	 * @param array  $args    Raw arguments from the model.
	 * @param array  $context Context (command, conversation_id, source).
	 * @return array Result array.
	 */
	public function execute( $name, array $args, array $context = array() ) {
		$tool = $this->get( $name );
		if ( ! $tool ) {
			return array(
				'success' => false,
				'error'   => sprintf( 'Unknown tool: %s', $name ),
				'summary' => sprintf( 'Unknown tool: %s', $name ),
				'data'    => null,
			);
		}

		if ( ! $this->is_enabled( $name ) ) {
			return array(
				'success' => false,
				'error'   => sprintf( 'Tool %s is disabled.', $name ),
				'summary' => sprintf( 'Tool %s is disabled.', $name ),
				'data'    => null,
			);
		}

		if ( ! current_user_can( $tool['capability'] ) && ! \AIWC\Security\Permissions::current_user_can_manage() ) {
			return array(
				'success' => false,
				'error'   => sprintf( 'Missing capability for tool %s.', $name ),
				'summary' => sprintf( 'Missing capability for tool %s.', $name ),
				'data'    => null,
			);
		}

		// Validate arguments against the declared schema.
		$validated = $tool['group']->validate_args( $args, $tool['parameters'] );
		if ( is_wp_error( $validated ) ) {
			return array(
				'success' => false,
				'error'   => $validated->get_error_message(),
				'summary' => $validated->get_error_message(),
				'data'    => null,
			);
		}

		$context['tool_name'] = $name;
		$context['risk']      = $tool['risk'];
		$start                = microtime( true );

		$result = $tool['group']->execute( $name, $validated, $context );

		$duration = (int) ( ( microtime( true ) - $start ) * 1000 );
		$result['duration_ms'] = $duration;
		$result['tool']        = $name;
		$result['risk']        = $tool['risk'];
		return $result;
	}

	/**
	 * Create an approval entry (pending operation) in the activity log.
	 *
	 * @param string $name    Tool name.
	 * @param array  $args    Tool arguments.
	 * @param array  $context Context.
	 * @return int Log id of the pending entry.
	 */
	public function create_approval( $name, array $args, array $context = array() ) {
		$log = aiwc()->get( 'log' );
		return $log->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => $name,
				'args'            => $args,
				'status'          => 'pending',
				'summary'         => sprintf( 'Awaiting approval: %s', $name ),
				'approval'        => 'pending',
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);
	}
}
