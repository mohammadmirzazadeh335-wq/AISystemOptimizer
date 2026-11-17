<?php
/**
 * Conversation and message persistence.
 *
 * @package AIWC
 */

namespace AIWC\Chat;

defined( 'ABSPATH' ) || exit;

/**
 * Stores chat conversations and messages.
 */
class Conversation_Store {

	/**
	 * Conversations table.
	 *
	 * @return string
	 */
	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'aiwc_conversations';
	}

	/**
	 * Messages table.
	 *
	 * @return string
	 */
	public static function messages_table() {
		global $wpdb;
		return $wpdb->prefix . 'aiwc_messages';
	}

	/**
	 * Create a conversation.
	 *
	 * @param int    $user_id Owner.
	 * @param string $title   Initial title.
	 * @param string $model   Model name.
	 * @return int Conversation id.
	 */
	public function create( $user_id, $title = '', $model = '' ) {
		global $wpdb;
		$now = current_time( 'mysql' );
		$wpdb->insert(
			self::table(),
			array(
				'user_id'    => absint( $user_id ),
				'title'      => mb_substr( sanitize_text_field( $title ), 0, 255 ),
				'model'      => sanitize_text_field( $model ),
				'created_at' => $now,
				'updated_at' => $now,
			)
		);
		return (int) $wpdb->insert_id;
	}

	/**
	 * List conversations for a user.
	 *
	 * @param int $user_id User id.
	 * @param int $limit   Max rows.
	 * @return array
	 */
	public function list_for_user( $user_id, $limit = 50 ) {
		global $wpdb;
		$table = self::table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$rows = $wpdb->get_results(
			$wpdb->prepare( "SELECT * FROM {$table} WHERE user_id = %d ORDER BY updated_at DESC LIMIT %d", absint( $user_id ), absint( $limit ) ),
			ARRAY_A
		);
		foreach ( $rows as &$row ) {
			$row['id']          = (int) $row['id'];
			$row['tokens_used'] = (int) $row['tokens_used'];
		}
		return $rows;
	}

	/**
	 * Get one conversation.
	 *
	 * @param int $id Conversation id.
	 * @return array|null
	 */
	public function get( $id ) {
		global $wpdb;
		$table = self::table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", absint( $id ) ), ARRAY_A );
		if ( $row ) {
			$row['id']          = (int) $row['id'];
			$row['tokens_used'] = (int) $row['tokens_used'];
		}
		return $row;
	}

	/**
	 * Delete a conversation and its messages.
	 *
	 * @param int $id Conversation id.
	 * @return bool
	 */
	public function delete( $id ) {
		global $wpdb;
		$id = absint( $id );
		$wpdb->delete( self::messages_table(), array( 'conversation_id' => $id ) );
		return (bool) $wpdb->delete( self::table(), array( 'id' => $id ) );
	}

	/**
	 * Touch conversation (title, model, token usage).
	 *
	 * @param int   $id    Conversation id.
	 * @param array $data  Fields: title, model, add_tokens.
	 */
	public function update( $id, array $data ) {
		global $wpdb;
		$row = array( 'updated_at' => current_time( 'mysql' ) );
		if ( isset( $data['title'] ) ) {
			$row['title'] = mb_substr( sanitize_text_field( $data['title'] ), 0, 255 );
		}
		if ( isset( $data['model'] ) ) {
			$row['model'] = sanitize_text_field( $data['model'] );
		}
		$wpdb->update( self::table(), $row, array( 'id' => absint( $id ) ) );
		if ( ! empty( $data['add_tokens'] ) ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
			$wpdb->query( $wpdb->prepare( 'UPDATE ' . self::table() . ' SET tokens_used = tokens_used + %d WHERE id = %d', absint( $data['add_tokens'] ), absint( $id ) ) );
		}
	}

	/**
	 * Append a message row.
	 *
	 * @param int   $conversation_id Conversation id.
	 * @param array $message {
	 *     @type string $role          user|assistant|tool|system.
	 *     @type string $content       Text content.
	 *     @type array  $tool_calls    Tool calls (assistant).
	 *     @type string $tool_call_id  Tool call id (tool).
	 *     @type string $tool_name     Tool name (tool).
	 *     @type string $status        ok|error|pending.
	 *     @type int    $tokens        Tokens used.
	 * }
	 * @return int Message id.
	 */
	public function add_message( $conversation_id, array $message ) {
		global $wpdb;
		$wpdb->insert(
			self::messages_table(),
			array(
				'conversation_id' => absint( $conversation_id ),
				'role'            => isset( $message['role'] ) ? sanitize_text_field( $message['role'] ) : 'user',
				'content'         => isset( $message['content'] ) ? (string) $message['content'] : '',
				'tool_calls_json' => isset( $message['tool_calls'] ) ? wp_json_encode( $message['tool_calls'] ) : null,
				'tool_call_id'    => isset( $message['tool_call_id'] ) ? sanitize_text_field( $message['tool_call_id'] ) : null,
				'tool_name'       => isset( $message['tool_name'] ) ? sanitize_text_field( $message['tool_name'] ) : null,
				'status'          => isset( $message['status'] ) ? sanitize_text_field( $message['status'] ) : 'ok',
				'tokens'          => isset( $message['tokens'] ) ? absint( $message['tokens'] ) : 0,
				'created_at'      => current_time( 'mysql' ),
			)
		);
		return (int) $wpdb->insert_id;
	}

	/**
	 * Get messages for a conversation.
	 *
	 * @param int $conversation_id Conversation id.
	 * @param int $limit           Max rows.
	 * @param int $offset          Offset.
	 * @return array
	 */
	public function get_messages( $conversation_id, $limit = 200, $offset = 0 ) {
		global $wpdb;
		$table = self::messages_table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$rows = $wpdb->get_results(
			$wpdb->prepare(
				"SELECT * FROM {$table} WHERE conversation_id = %d ORDER BY id ASC LIMIT %d OFFSET %d",
				absint( $conversation_id ),
				absint( $limit ),
				absint( $offset )
			),
			ARRAY_A
		);
		return array_map( array( $this, 'format_message' ), $rows );
	}

	/**
	 * Format a raw message row for API output.
	 *
	 * @param array $row Raw row.
	 * @return array
	 */
	public function format_message( $row ) {
		$row['id']      = (int) $row['id'];
		$row['tokens']  = (int) $row['tokens'];
		$row['tool_calls'] = $row['tool_calls_json'] ? json_decode( $row['tool_calls_json'], true ) : null;
		unset( $row['tool_calls_json'] );
		return $row;
	}

	/**
	 * Rebuild the OpenAI messages array from stored history.
	 *
	 * @param int $conversation_id Conversation id.
	 * @param int $max_chars       Approximate character budget for context.
	 * @return array OpenAI-style messages (without system).
	 */
	public function build_context_messages( $conversation_id, $max_chars = 24000 ) {
		$rows    = $this->get_messages( $conversation_id, 200 );
		$messages = array();
		$used     = 0;

		// Walk backwards to keep the most recent messages within budget.
		$reversed = array_reverse( $rows );
		$tail     = array();
		foreach ( $reversed as $row ) {
			$size = strlen( (string) $row['content'] ) + 200;
			if ( $used + $size > $max_chars && $tail ) {
				break;
			}
			$used += $size;
			array_unshift( $tail, $row );
		}

		foreach ( $tail as $row ) {
			if ( 'user' === $row['role'] ) {
				$messages[] = array(
					'role'    => 'user',
					'content' => (string) $row['content'],
				);
			} elseif ( 'assistant' === $row['role'] ) {
				$entry = array(
					'role'    => 'assistant',
					'content' => null === $row['content'] ? '' : (string) $row['content'],
				);
				if ( ! empty( $row['tool_calls'] ) ) {
					$entry['content']    = $entry['content'] ? $entry['content'] : null;
					$entry['tool_calls'] = $row['tool_calls'];
				}
				$messages[] = $entry;
			} elseif ( 'tool' === $row['role'] ) {
				$messages[] = array(
					'role'         => 'tool',
					'tool_call_id' => (string) $row['tool_call_id'],
					'content'      => (string) $row['content'],
				);
			}
		}

		return $messages;
	}
}
