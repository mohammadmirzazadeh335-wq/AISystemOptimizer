<?php
/**
 * System tools: rollback, memory, jobs.
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;

defined( 'ABSPATH' ) || exit;

/**
 * Meta tools for recovery, memory and background jobs.
 */
class System_Tools extends Abstract_Tool_Group {

	/**
	 * Declare tools.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'rollback_change',
				'description' => 'Restore a previous state of a page/post/option using a snapshot id (from activity log entries). Reverts the last change made by the AI.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'snapshot_id' => array( 'type' => 'integer', 'description' => 'Snapshot ID to restore.' ),
					),
					'required'   => array( 'snapshot_id' ),
				),
				'risk'        => 'destructive',
				'needs_confirmation' => true,
				'handler'     => 'handle_rollback',
			),
			array(
				'name'        => 'list_snapshots',
				'description' => 'List recent change snapshots (before/after states) that can be rolled back.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'limit' => array( 'type' => 'integer', 'description' => 'Max rows, default 15.' ),
					),
				),
				'risk'        => 'read',
				'handler'     => 'handle_list_snapshots',
			),
			array(
				'name'        => 'memory_save',
				'description' => 'Save a fact to long-term memory so it is respected in future conversations: brand info (e.g. brand colors), design preferences, admin instructions or structural knowledge.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'category' => array(
							'type'        => 'string',
							'description' => 'Category.',
							'enum'        => array( 'brand', 'design', 'instruction', 'structure', 'general' ),
						),
						'key'      => array( 'type' => 'string', 'description' => 'Short key, e.g. primary_color.' ),
						'value'    => array( 'type' => 'string', 'description' => 'Value to remember.' ),
					),
					'required'   => array( 'category', 'key', 'value' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_memory_save',
			),
			array(
				'name'        => 'memory_list',
				'description' => 'List everything stored in long-term memory (brand facts, preferences, instructions).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_memory_list',
			),
			array(
				'name'        => 'memory_forget',
				'description' => 'Remove a memory entry by id.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'memory_id' => array( 'type' => 'integer', 'description' => 'Memory row ID.' ),
					),
					'required'   => array( 'memory_id' ),
				),
				'risk'        => 'destructive',
				'handler'     => 'handle_memory_forget',
			),
			array(
				'name'        => 'jobs_list',
				'description' => 'List background jobs (site SEO analysis, batch operations) with status and results.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_jobs_list',
			),
		);
	}

	/**
	 * rollback_change
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_rollback( array $args, array $context = array() ) {
		$result = $this->plugin->get( 'snapshots' )->restore( absint( $args['snapshot_id'] ) );
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_message() );
		}

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'rollback_change',
				'summary'         => sprintf( 'Rolled back snapshot #%d', absint( $args['snapshot_id'] ) ),
				'args'            => $args,
				'status'          => 'success',
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);
		$result['log_id'] = $log_id;
		return $this->success( $result, $result['message'], array( 'log_id' => $log_id ) );
	}

	/**
	 * list_snapshots
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_list_snapshots( array $args ) {
		$limit = isset( $args['limit'] ) ? absint( $args['limit'] ) : 15;
		$items = $this->plugin->get( 'snapshots' )->list_snapshots( $limit );
		return $this->success( array( 'items' => $items ), sprintf( 'Listed %d snapshots.', count( $items ) ) );
	}

	/**
	 * memory_save
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_memory_save( array $args ) {
		$id = $this->plugin->get( 'memory' )->remember(
			$args['category'],
			$args['key'],
			$args['value'],
			'ai'
		);
		if ( ! $id ) {
			return $this->error( 'Failed to save memory.' );
		}
		return $this->success(
			array( 'memory_id' => $id ),
			sprintf( 'Remembered: %s = %s', $args['key'], $args['value'] )
		);
	}

	/**
	 * memory_list
	 *
	 * @return array
	 */
	public function handle_memory_list() {
		$items = $this->plugin->get( 'memory' )->all();
		return $this->success( array( 'items' => $items ), sprintf( '%d memories stored.', count( $items ) ) );
	}

	/**
	 * memory_forget
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_memory_forget( array $args ) {
		$ok = $this->plugin->get( 'memory' )->forget( absint( $args['memory_id'] ) );
		if ( ! $ok ) {
			return $this->error( 'Memory not found.' );
		}
		return $this->success( array( 'memory_id' => absint( $args['memory_id'] ) ), 'Memory removed.' );
	}

	/**
	 * jobs_list
	 *
	 * @return array
	 */
	public function handle_jobs_list() {
		$items = $this->plugin->get( 'queue' )->list_jobs( 15 );
		return $this->success( array( 'items' => $items ), sprintf( '%d jobs.', count( $items ) ) );
	}
}
