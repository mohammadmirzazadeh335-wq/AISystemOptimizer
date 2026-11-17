<?php
/**
 * Snapshot manager: before/after state capture and rollback.
 *
 * @package AIWC
 */

namespace AIWC\Backup;

use AIWC\Log\Activity_Log;

defined( 'ABSPATH' ) || exit;

/**
 * Stores object state before mutating tools run, and restores it later.
 */
class Snapshot_Manager {

	/**
	 * Log service.
	 *
	 * @var Activity_Log
	 */
	private $log;

	/**
	 * Constructor.
	 *
	 * @param Activity_Log $log Log service.
	 */
	public function __construct( Activity_Log $log ) {
		$this->log = $log;
	}

	/**
	 * Table name.
	 *
	 * @return string
	 */
	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'aiwc_snapshots';
	}

	/**
	 * Capture the current state of an object.
	 *
	 * @param string $object_type 'post', 'option' or 'custom_css'.
	 * @param int    $object_id   Post id or 0 for options.
	 * @param string $meta_key    For options: option name.
	 * @return array|null State array or null when nothing to capture.
	 */
	public function capture( $object_type, $object_id = 0, $meta_key = '' ) {
		if ( 'custom_css' === $object_type ) {
			return array(
				'css' => wp_get_custom_css( wp_get_theme()->get_stylesheet() ),
			);
		}

		if ( 'post' === $object_type ) {
			$post = get_post( absint( $object_id ) );
			if ( ! $post ) {
				return null;
			}
			$meta = array();
			foreach ( get_post_meta( $post->ID ) as $key => $values ) {
				if ( 0 === strpos( $key, '_wp_old_slug' ) ) {
					continue;
				}
				$meta[ $key ] = array_map( 'maybe_unserialize', $values );
			}
			return array(
				'post' => array(
					'ID'           => $post->ID,
					'post_title'   => $post->post_title,
					'post_content' => $post->post_content,
					'post_excerpt' => $post->post_excerpt,
					'post_status'  => $post->post_status,
					'post_type'    => $post->post_type,
					'post_name'    => $post->post_name,
					'menu_order'   => $post->menu_order,
					'post_parent'  => $post->post_parent,
				),
				'meta' => $meta,
			);
		}

		if ( 'option' === $object_type && $meta_key ) {
			return array(
				'option_name' => sanitize_key( $meta_key ),
				'value'       => get_option( $meta_key ),
			);
		}

		return null;
	}

	/**
	 * Persist a snapshot row.
	 *
	 * @param string   $object_type Object type.
	 * @param int      $object_id   Object id.
	 * @param mixed    $before      Before state.
	 * @param mixed    $after       After state (nullable).
	 * @param int      $log_id      Related log id.
	 * @return int Snapshot id.
	 */
	public function save( $object_type, $object_id, $before, $after = null, $log_id = 0 ) {
		global $wpdb;
		$wpdb->insert(
			self::table(),
			array(
				'log_id'       => absint( $log_id ),
				'object_type'  => sanitize_text_field( $object_type ),
				'object_id'    => absint( $object_id ),
				'before_state' => wp_json_encode( $before ),
				'after_state'  => null === $after ? null : wp_json_encode( $after ),
				'created_at'   => current_time( 'mysql' ),
			)
		);
		return (int) $wpdb->insert_id;
	}

	/**
	 * List snapshots, newest first.
	 *
	 * @param int $limit Max rows.
	 * @return array
	 */
	public function list_snapshots( $limit = 20 ) {
		global $wpdb;
		$table = self::table();
		$limit = max( 1, min( 100, absint( $limit ) ) );
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} ORDER BY id DESC LIMIT %d", $limit ), ARRAY_A );
		foreach ( $rows as &$row ) {
			$row['id']           = (int) $row['id'];
			$row['before_state'] = $row['before_state'] ? json_decode( $row['before_state'], true ) : null;
			$row['after_state']  = $row['after_state'] ? json_decode( $row['after_state'], true ) : null;
		}
		return $rows;
	}

	/**
	 * Restore an object to a snapshot's before state.
	 *
	 * @param int $snapshot_id Snapshot id.
	 * @return array|\WP_Error Result message or error.
	 */
	public function restore( $snapshot_id ) {
		global $wpdb;
		$table = self::table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", absint( $snapshot_id ) ), ARRAY_A );
		if ( ! $row ) {
			return new \WP_Error( 'aiwc_snapshot_missing', __( 'Snapshot not found.', 'ai-wordpress-copilot' ), array( 'status' => 404 ) );
		}

		$before = json_decode( (string) $row['before_state'], true );
		if ( ! is_array( $before ) ) {
			return new \WP_Error( 'aiwc_snapshot_corrupt', __( 'Snapshot data is corrupted.', 'ai-wordpress-copilot' ), array( 'status' => 500 ) );
		}

		if ( 'custom_css' === $row['object_type'] && isset( $before['css'] ) ) {
			$result = wp_update_custom_css_post( (string) $before['css'] );
			if ( is_wp_error( $result ) ) {
				return $result;
			}
		} elseif ( 'post' === $row['object_type'] && isset( $before['post'] ) ) {
			$post_data = $before['post'];
			$existing  = get_post( absint( $post_data['ID'] ) );
			if ( ! $existing ) {
				return new \WP_Error( 'aiwc_snapshot_gone', __( 'The original post no longer exists.', 'ai-wordpress-copilot' ), array( 'status' => 404 ) );
			}
			$result = wp_update_post(
				array(
					'ID'           => absint( $post_data['ID'] ),
					'post_title'   => $post_data['post_title'],
					'post_content' => $post_data['post_content'],
					'post_excerpt' => isset( $post_data['post_excerpt'] ) ? $post_data['post_excerpt'] : '',
					'post_status'  => $post_data['post_status'],
					'post_name'    => isset( $post_data['post_name'] ) ? $post_data['post_name'] : '',
					'menu_order'   => isset( $post_data['menu_order'] ) ? absint( $post_data['menu_order'] ) : 0,
				),
				true
			);
			if ( is_wp_error( $result ) ) {
				return $result;
			}
			if ( isset( $before['meta'] ) && is_array( $before['meta'] ) ) {
				foreach ( $before['meta'] as $meta_key => $values ) {
					delete_post_meta( absint( $post_data['ID'] ), $meta_key );
					foreach ( (array) $values as $value ) {
						add_post_meta( absint( $post_data['ID'] ), $meta_key, $value );
					}
				}
			}
		} elseif ( 'option' === $row['object_type'] && isset( $before['option_name'] ) ) {
			update_option( sanitize_key( $before['option_name'] ), $before['value'] );
		} else {
			return new \WP_Error( 'aiwc_snapshot_type', __( 'Unsupported snapshot type.', 'ai-wordpress-copilot' ), array( 'status' => 400 ) );
		}

		$wpdb->update( self::table(), array( 'restored_at' => current_time( 'mysql' ) ), array( 'id' => absint( $snapshot_id ) ) );

		$this->log->log(
			array(
				'tool_name'   => 'rollback',
				'object_type' => sanitize_text_field( $row['object_type'] ),
				'object_id'   => absint( $row['object_id'] ),
				'summary'     => sprintf( 'Restored snapshot #%d', absint( $snapshot_id ) ),
				'status'      => 'success',
				'approval'    => 'approved',
			)
		);

		clean_post_cache( absint( $row['object_id'] ) );

		return array(
			'success'     => true,
			'snapshot_id' => absint( $snapshot_id ),
			'message'     => __( 'Object restored to its previous state.', 'ai-wordpress-copilot' ),
		);
	}
}
