<?php
/**
 * Long-term memory of site facts and user preferences.
 *
 * @package AIWC
 */

namespace AIWC\Memory;

defined( 'ABSPATH' ) || exit;

/**
 * Stores and retrieves structured memories.
 */
class Memory_Store {

	/**
	 * Table name.
	 *
	 * @return string
	 */
	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'aiwc_memory';
	}

	/**
	 * Remember a fact (insert or update by key).
	 *
	 * @param string $category Category: brand|design|instruction|structure|general.
	 * @param string $key      Machine key.
	 * @param string $value    Human-readable value.
	 * @param string $source   manual|ai.
	 * @return int Row id.
	 */
	public function remember( $category, $key, $value, $source = 'manual' ) {
		global $wpdb;
		$category = in_array( $category, array( 'brand', 'design', 'instruction', 'structure', 'general' ), true ) ? $category : 'general';
		$key      = sanitize_key( str_replace( array( ' ', '-' ), '_', $key ) );
		$value    = trim( (string) $value );
		if ( '' === $key || '' === $value ) {
			return 0;
		}

		$table = self::table();
		$now   = current_time( 'mysql' );
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$existing = $wpdb->get_var( $wpdb->prepare( "SELECT id FROM {$table} WHERE memory_key = %s", $key ) );
		if ( $existing ) {
			$wpdb->update(
				$table,
				array(
					'category'     => $category,
					'memory_value' => $value,
					'source'       => sanitize_text_field( $source ),
					'updated_at'   => $now,
				),
				array( 'id' => absint( $existing ) )
			);
			$id = absint( $existing );
		} else {
			$wpdb->insert(
				$table,
				array(
					'category'     => $category,
					'memory_key'   => $key,
					'memory_value' => $value,
					'source'       => sanitize_text_field( $source ),
					'created_at'   => $now,
					'updated_at'   => $now,
				)
			);
			$id = (int) $wpdb->insert_id;
		}

		do_action( 'aiwc_memory_updated', $id );
		return $id;
	}

	/**
	 * Forget a memory.
	 *
	 * @param int $id Memory id.
	 * @return bool
	 */
	public function forget( $id ) {
		global $wpdb;
		$result = (bool) $wpdb->delete( self::table(), array( 'id' => absint( $id ) ) );
		if ( $result ) {
			do_action( 'aiwc_memory_updated', absint( $id ) );
		}
		return $result;
	}

	/**
	 * Update a memory row.
	 *
	 * @param int   $id   Memory id.
	 * @param array $data Fields: category, memory_key, memory_value.
	 * @return bool
	 */
	public function update( $id, array $data ) {
		global $wpdb;
		$row = array( 'updated_at' => current_time( 'mysql' ) );
		if ( isset( $data['category'] ) ) {
			$row['category'] = in_array( $data['category'], array( 'brand', 'design', 'instruction', 'structure', 'general' ), true ) ? $data['category'] : 'general';
		}
		if ( isset( $data['memory_key'] ) ) {
			$row['memory_key'] = sanitize_key( str_replace( array( ' ', '-' ), '_', (string) $data['memory_key'] ) );
		}
		if ( isset( $data['memory_value'] ) ) {
			$row['memory_value'] = trim( (string) $data['memory_value'] );
		}
		$ok = (bool) $wpdb->update( self::table(), $row, array( 'id' => absint( $id ) ) );
		if ( $ok ) {
			do_action( 'aiwc_memory_updated', absint( $id ) );
		}
		return $ok;
	}

	/**
	 * List memories.
	 *
	 * @param string $category Optional category filter.
	 * @return array
	 */
	public function all( $category = '' ) {
		global $wpdb;
		$table = self::table();
		if ( $category ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
			$rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} WHERE category = %s ORDER BY updated_at DESC", sanitize_text_field( $category ) ), ARRAY_A );
		} else {
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
			$rows = $wpdb->get_results( "SELECT * FROM {$table} ORDER BY updated_at DESC", ARRAY_A );
		}
		foreach ( $rows as &$row ) {
			$row['id'] = (int) $row['id'];
		}
		return $rows;
	}

	/**
	 * Compact prompt block with all memories.
	 *
	 * @param int $max_chars Character budget.
	 * @return string
	 */
	public function prompt_block( $max_chars = 3000 ) {
		$rows = $this->all();
		if ( ! $rows ) {
			return '';
		}
		$lines  = array( 'Known site facts and user preferences (respect these):' );
		$length = 0;
		foreach ( $rows as $row ) {
			$line = '- [' . $row['category'] . '] ' . $row['memory_key'] . ': ' . $row['memory_value'];
			$length += strlen( $line );
			if ( $length > $max_chars ) {
				$lines[] = '- … (more memories omitted)';
				break;
			}
			$lines[] = $line;
		}
		return implode( "\n", $lines );
	}
}
