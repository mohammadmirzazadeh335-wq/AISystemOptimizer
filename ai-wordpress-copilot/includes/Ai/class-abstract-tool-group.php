<?php
/**
 * Base class for tool groups with shared helpers.
 *
 * @package AIWC
 */

namespace AIWC\Ai;

use AIWC\Plugin;

defined( 'ABSPATH' ) || exit;

/**
 * Shared execution helpers for tool groups.
 */
abstract class Abstract_Tool_Group implements Tool_Group_Interface {

	/**
	 * Plugin instance.
	 *
	 * @var Plugin
	 */
	protected $plugin;

	/**
	 * Constructor.
	 *
	 * @param Plugin $plugin Plugin instance.
	 */
	public function __construct( Plugin $plugin ) {
		$this->plugin = $plugin;
	}

	/**
	 * Dispatch by tool name to the registered handler method.
	 *
	 * @param string $name    Tool name.
	 * @param array  $args    Arguments.
	 * @param array  $context Context.
	 * @return array
	 */
	public function execute( $name, array $args, array $context = array() ) {
		foreach ( $this->tools() as $tool ) {
			if ( $tool['name'] === $name ) {
				$handler = $tool['handler'];
				if ( ! method_exists( $this, $handler ) ) {
					return $this->error( sprintf( 'Handler %s missing for tool %s.', $handler, $name ) );
				}
				try {
					$result = $this->{$handler}( $args, $context );
					return is_array( $result ) ? $result : $this->error( 'Tool returned an invalid result.' );
				} catch ( \Exception $e ) {
					return $this->error( $e->getMessage() );
				}
			}
		}
		return $this->error( sprintf( 'Unknown tool: %s', $name ) );
	}

	/**
	 * Standard success result.
	 *
	 * @param mixed  $data     Result data.
	 * @param string $summary  Human summary.
	 * @param array  $extra    Extra fields (snapshot_id, log_id, object_type, object_id).
	 * @return array
	 */
	protected function success( $data, $summary, array $extra = array() ) {
		return array_merge(
			array(
				'success' => true,
				'data'    => $data,
				'summary' => $summary,
			),
			$extra
		);
	}

	/**
	 * Standard error result.
	 *
	 * @param string $message Error message.
	 * @return array
	 */
	protected function error( $message ) {
		return array(
			'success' => false,
			'data'    => null,
			'summary' => (string) $message,
			'error'   => (string) $message,
		);
	}

	/**
	 * Capture before-state for a post and return (log_id, snapshot data).
	 *
	 * @param int    $post_id  Post id.
	 * @param string $command  User command.
	 * @param string $tool     Tool name.
	 * @param array  $args     Tool args.
	 * @param int    $conversation_id Conversation id.
	 * @return array{before: array|null, log_id: int}
	 */
	protected function begin_mutation( $post_id, $tool, array $args, array $context ) {
		$snapshots = $this->plugin->get( 'snapshots' );
		$log       = $this->plugin->get( 'log' );
		$before    = $snapshots->capture( 'post', absint( $post_id ) );
		$log_id    = $log->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => $tool,
				'object_type'     => 'post',
				'object_id'       => absint( $post_id ),
				'args'            => $args,
				'status'          => 'pending',
				'before_state'    => $before,
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);
		return array(
			'before' => $before,
			'log_id' => $log_id,
		);
	}

	/**
	 * Finish a mutation: save snapshot, update log.
	 *
	 * @param array  $state   Result of begin_mutation.
	 * @param string $object_type Object type.
	 * @param int    $object_id   Object id.
	 * @param array  $result      Tool result.
	 * @param array  $after       After state (captured when null).
	 * @return array Result with snapshot_id/log_id injected.
	 */
	protected function end_mutation( array $state, $object_type, $object_id, array $result, $after = null ) {
		$snapshots = $this->plugin->get( 'snapshots' );
		$log       = $this->plugin->get( 'log' );

		if ( null === $after ) {
			$after = $snapshots->capture( $object_type, absint( $object_id ) );
		}

		$snapshot_id = 0;
		if ( ! empty( $state['before'] ) ) {
			$snapshot_id = $snapshots->save( $object_type, absint( $object_id ), $state['before'], $after, $state['log_id'] );
		}

		$log->update(
			$state['log_id'],
			array(
				'status'       => ! empty( $result['success'] ) ? 'success' : 'failed',
				'summary'      => isset( $result['summary'] ) ? $result['summary'] : '',
				'after_state'  => $after,
				'error'        => ! empty( $result['error'] ) ? $result['error'] : '',
				'object_type'  => $object_type,
				'object_id'    => absint( $object_id ),
			)
		);

		$result['snapshot_id'] = $snapshot_id;
		$result['log_id']      = $state['log_id'];
		return $result;
	}

	/**
	 * Validate args against a minimal schema (type + required).
	 *
	 * @param array $args   Input args.
	 * @param array $schema JSON schema (properties/required).
	 * @return array|\WP_Error Validated args.
	 */
	public function validate_args( array $args, array $schema ) {
		$clean = array();
		$props = isset( $schema['properties'] ) && is_array( $schema['properties'] ) ? $schema['properties'] : array();
		$req   = isset( $schema['required'] ) && is_array( $schema['required'] ) ? $schema['required'] : array();

		foreach ( $req as $key ) {
			if ( ! isset( $args[ $key ] ) || '' === $args[ $key ] ) {
				return new \WP_Error( 'aiwc_missing_arg', sprintf( 'Missing required argument: %s', $key ), array( 'status' => 400 ) );
			}
		}

		foreach ( $props as $key => $def ) {
			if ( ! isset( $args[ $key ] ) ) {
				continue;
			}
			$value = $args[ $key ];
			$type  = isset( $def['type'] ) ? $def['type'] : 'string';
			switch ( $type ) {
				case 'integer':
					$clean[ $key ] = absint( $value );
					break;
				case 'number':
					$clean[ $key ] = (float) $value;
					break;
				case 'boolean':
					$clean[ $key ] = (bool) $value;
					break;
				case 'array':
					$clean[ $key ] = is_array( $value ) ? $value : json_decode( (string) $value, true );
					if ( ! is_array( $clean[ $key ] ) ) {
						$clean[ $key ] = array();
					}
					break;
				case 'object':
					$clean[ $key ] = is_array( $value ) ? $value : (array) json_decode( (string) $value, true );
					break;
				default:
					$clean[ $key ] = is_scalar( $value ) ? sanitize_textarea_field( (string) $value ) : '';
			}
		}

		return $clean;
	}
}
