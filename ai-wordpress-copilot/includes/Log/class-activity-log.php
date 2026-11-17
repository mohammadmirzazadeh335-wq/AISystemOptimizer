<?php
/**
 * Activity log storage.
 *
 * @package AIWC
 */

namespace AIWC\Log;

defined( 'ABSPATH' ) || exit;

/**
 * Writes and reads the aiwc_activity_log table.
 */
class Activity_Log {

	/**
	 * Table name with prefix.
	 *
	 * @return string
	 */
	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'aiwc_activity_log';
	}

	/**
	 * Insert a log entry.
	 *
	 * @param array $data Entry data.
	 *      - command (string)      User command.
	 *      - tool_name (string)    Tool used.
	 *      - object_type (string)  'post', 'page', 'option', ...
	 *      - object_id (int)       Affected object id.
	 *      - summary (string)      Human readable summary.
	 *      - args (array)          Tool arguments.
	 *      - status (string)       success|failed|pending|rejected.
	 *      - before_state (mixed)  State before change.
	 *      - after_state (mixed)   State after change.
	 *      - error (string)        Error text.
	 *      - tokens (int)          Tokens consumed.
	 *      - duration_ms (int)     Duration.
	 *      - approval (string)     '', 'approved', 'rejected'.
	 *      - conversation_id (int) Conversation id.
	 * @return int Log id.
	 */
	public function log( array $data ) {
		global $wpdb;

		$row = array(
			'user_id'         => isset( $data['user_id'] ) ? absint( $data['user_id'] ) : get_current_user_id(),
			'conversation_id' => isset( $data['conversation_id'] ) ? absint( $data['conversation_id'] ) : 0,
			'command'         => isset( $data['command'] ) ? wp_kses_post( (string) $data['command'] ) : '',
			'tool_name'       => isset( $data['tool_name'] ) ? sanitize_text_field( (string) $data['tool_name'] ) : '',
			'object_type'     => isset( $data['object_type'] ) ? sanitize_text_field( (string) $data['object_type'] ) : '',
			'object_id'       => isset( $data['object_id'] ) ? absint( $data['object_id'] ) : 0,
			'summary'         => isset( $data['summary'] ) ? wp_kses_post( (string) $data['summary'] ) : '',
			'args_json'       => isset( $data['args'] ) ? wp_json_encode( $data['args'] ) : null,
			'status'          => isset( $data['status'] ) ? sanitize_text_field( (string) $data['status'] ) : 'success',
			'before_state'    => isset( $data['before_state'] ) ? wp_json_encode( $data['before_state'] ) : null,
			'after_state'     => isset( $data['after_state'] ) ? wp_json_encode( $data['after_state'] ) : null,
			'error'           => isset( $data['error'] ) ? sanitize_text_field( (string) $data['error'] ) : null,
			'tokens'          => isset( $data['tokens'] ) ? absint( $data['tokens'] ) : 0,
			'duration_ms'     => isset( $data['duration_ms'] ) ? absint( $data['duration_ms'] ) : 0,
			'approval'        => isset( $data['approval'] ) ? sanitize_text_field( (string) $data['approval'] ) : '',
			'created_at'      => current_time( 'mysql' ),
		);

		$wpdb->insert( self::table(), $row );
		return (int) $wpdb->insert_id;
	}

	/**
	 * Update an existing log entry (status transitions).
	 *
	 * @param int   $id   Log id.
	 * @param array $data Fields to update.
	 * @return bool
	 */
	public function update( $id, array $data ) {
		global $wpdb;
		$allowed = array( 'status', 'approval', 'error', 'summary', 'after_state', 'before_state', 'object_id', 'object_type', 'tokens', 'duration_ms' );
		$row     = array();
		foreach ( $allowed as $key ) {
			if ( isset( $data[ $key ] ) ) {
				if ( in_array( $key, array( 'after_state', 'before_state' ), true ) && ! is_string( $data[ $key ] ) ) {
					$row[ $key ] = wp_json_encode( $data[ $key ] );
				} elseif ( 'object_id' === $key || 'tokens' === $key || 'duration_ms' === $key ) {
					$row[ $key ] = absint( $data[ $key ] );
				} else {
					$row[ $key ] = sanitize_text_field( (string) $data[ $key ] );
				}
			}
		}
		if ( empty( $row ) ) {
			return false;
		}
		return false !== $wpdb->update( self::table(), $row, array( 'id' => absint( $id ) ) );
	}

	/**
	 * Fetch logs with filters and pagination.
	 *
	 * @param array $args {
	 *     @type int    $page           Page number.
	 *     @type int    $per_page       Items per page.
	 *     @type string $status         Filter by status.
	 *     @type string $tool_name      Filter by tool.
	 *     @type int    $conversation_id Filter by conversation.
	 *     @type string $search         Free text search in command/summary.
	 *     @type string $date_from      Y-m-d.
	 *     @type string $date_to        Y-m-d.
	 * }
	 * @return array{items: array, total: int}
	 */
	public function get_logs( array $args = array() ) {
		global $wpdb;
		$table = self::table();

		$defaults = array(
			'page'            => 1,
			'per_page'        => 20,
			'status'          => '',
			'tool_name'       => '',
			'conversation_id' => 0,
			'search'          => '',
			'date_from'       => '',
			'date_to'         => '',
		);
		$args = wp_parse_args( $args, $defaults );

		$where  = array( '1=1' );
		$params = array();

		if ( $args['status'] ) {
			$where[]  = 'status = %s';
			$params[] = sanitize_text_field( $args['status'] );
		}
		if ( $args['tool_name'] ) {
			$where[]  = 'tool_name = %s';
			$params[] = sanitize_text_field( $args['tool_name'] );
		}
		if ( $args['conversation_id'] ) {
			$where[]  = 'conversation_id = %d';
			$params[] = absint( $args['conversation_id'] );
		}
		if ( $args['search'] ) {
			$where[]  = '(command LIKE %s OR summary LIKE %s)';
			$like     = '%' . $wpdb->esc_like( sanitize_text_field( $args['search'] ) ) . '%';
			$params[] = $like;
			$params[] = $like;
		}
		if ( $args['date_from'] ) {
			$where[]  = 'created_at >= %s';
			$params[] = sanitize_text_field( $args['date_from'] ) . ' 00:00:00';
		}
		if ( $args['date_to'] ) {
			$where[]  = 'created_at <= %s';
			$params[] = sanitize_text_field( $args['date_to'] ) . ' 23:59:59';
		}

		$where_sql = implode( ' AND ', $where );
		$page      = max( 1, absint( $args['page'] ) );
		$per_page  = max( 1, min( 100, absint( $args['per_page'] ) ) );
		$offset    = ( $page - 1 ) * $per_page;

		$count_sql = "SELECT COUNT(*) FROM {$table} WHERE {$where_sql}";
		if ( $params ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- prepared below.
			$total = (int) $wpdb->get_var( $wpdb->prepare( $count_sql, $params ) );
		} else {
			$total = (int) $wpdb->get_var( $count_sql );
		}

		$list_sql = "SELECT * FROM {$table} WHERE {$where_sql} ORDER BY id DESC LIMIT %d OFFSET %d";
		$params[] = $per_page;
		$params[] = $offset;
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
		$items = $wpdb->get_results( $wpdb->prepare( $list_sql, $params ), ARRAY_A );

		foreach ( $items as &$item ) {
			$item['id']            = (int) $item['id'];
			$item['object_id']     = (int) $item['object_id'];
			$item['args']          = $item['args_json'] ? json_decode( $item['args_json'], true ) : null;
			$item['before_state']  = $item['before_state'] ? json_decode( $item['before_state'], true ) : null;
			$item['after_state']   = $item['after_state'] ? json_decode( $item['after_state'], true ) : null;
			unset( $item['args_json'] );
		}

		return array(
			'items' => $items,
			'total' => $total,
		);
	}

	/**
	 * Get one log entry.
	 *
	 * @param int $id Log id.
	 * @return array|null
	 */
	public function get( $id ) {
		global $wpdb;
		$table = self::table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$item = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", absint( $id ) ), ARRAY_A );
		if ( ! $item ) {
			return null;
		}
		$item['id']           = (int) $item['id'];
		$item['args']         = $item['args_json'] ? json_decode( $item['args_json'], true ) : null;
		$item['before_state'] = $item['before_state'] ? json_decode( $item['before_state'], true ) : null;
		$item['after_state']  = $item['after_state'] ? json_decode( $item['after_state'], true ) : null;
		unset( $item['args_json'] );
		return $item;
	}

	/**
	 * Distinct tool names (for filters).
	 *
	 * @return array
	 */
	public function tool_names() {
		global $wpdb;
		$table = self::table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		return $wpdb->get_col( "SELECT DISTINCT tool_name FROM {$table} WHERE tool_name != '' ORDER BY tool_name" );
	}
}
