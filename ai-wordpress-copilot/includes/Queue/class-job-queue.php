<?php
/**
 * Background job queue processed by WP-Cron.
 *
 * @package AIWC
 */

namespace AIWC\Queue;

defined( 'ABSPATH' ) || exit;

/**
 * Simple persistent job queue for long-running operations.
 */
class Job_Queue {

	/**
	 * Table name.
	 *
	 * @return string
	 */
	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'aiwc_jobs';
	}

	/**
	 * Push a job.
	 *
	 * @param string $type    Job type: seo_site_analysis|bulk_content|custom.
	 * @param array  $payload Job payload.
	 * @return int Job id.
	 */
	public function push( $type, array $payload = array() ) {
		global $wpdb;
		$wpdb->insert(
			self::table(),
			array(
				'type'         => sanitize_text_field( $type ),
				'payload'      => wp_json_encode( $payload ),
				'status'       => 'pending',
				'scheduled_at' => current_time( 'mysql' ),
				'created_at'   => current_time( 'mysql' ),
			)
		);
		$id = (int) $wpdb->insert_id;
		// Nudge cron so jobs run soon even on low-traffic sites.
		if ( ! wp_next_scheduled( 'aiwc_process_jobs' ) ) {
			wp_schedule_event( time() + 30, 'aiwc_five_minutes', 'aiwc_process_jobs' );
		}
		wp_schedule_single_event( time() + 5, 'aiwc_process_jobs' );
		return $id;
	}

	/**
	 * List jobs.
	 *
	 * @param int    $limit  Max rows.
	 * @param string $status Status filter.
	 * @return array
	 */
	public function list_jobs( $limit = 20, $status = '' ) {
		global $wpdb;
		$table = self::table();
		$limit = max( 1, min( 100, absint( $limit ) ) );
		if ( $status ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
			$rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} WHERE status = %s ORDER BY id DESC LIMIT %d", sanitize_text_field( $status ), $limit ), ARRAY_A );
		} else {
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
			$rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} ORDER BY id DESC LIMIT %d", $limit ), ARRAY_A );
		}
		foreach ( $rows as &$row ) {
			$row['id']      = (int) $row['id'];
			$row['payload'] = $row['payload'] ? json_decode( $row['payload'], true ) : null;
			$row['result']  = $row['result'] ? json_decode( $row['result'], true ) : null;
		}
		return $rows;
	}

	/**
	 * Get one job.
	 *
	 * @param int $id Job id.
	 * @return array|null
	 */
	public function get( $id ) {
		global $wpdb;
		$table = self::table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", absint( $id ) ), ARRAY_A );
		if ( ! $row ) {
			return null;
		}
		$row['id']      = (int) $row['id'];
		$row['payload'] = $row['payload'] ? json_decode( $row['payload'], true ) : null;
		$row['result']  = $row['result'] ? json_decode( $row['result'], true ) : null;
		return $row;
	}

	/**
	 * Delete a job.
	 *
	 * @param int $id Job id.
	 * @return bool
	 */
	public function delete( $id ) {
		global $wpdb;
		return (bool) $wpdb->delete( self::table(), array( 'id' => absint( $id ) ) );
	}

	/**
	 * Process a batch of pending jobs.
	 *
	 * @param int $batch Max jobs to process.
	 * @return int Processed count.
	 */
	public function process_batch( $batch = 3 ) {
		global $wpdb;
		$table = self::table();
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$ids = $wpdb->get_col(
			$wpdb->prepare(
				"SELECT id FROM {$table} WHERE status = 'pending' AND scheduled_at <= %s ORDER BY id ASC LIMIT %d",
				current_time( 'mysql' ),
				absint( $batch )
			)
		);

		$count = 0;
		foreach ( $ids as $id ) {
			if ( $this->run_job( absint( $id ) ) ) {
				++$count;
			}
		}
		return $count;
	}

	/**
	 * Process jobs in rounds until the queue drains (handles chained jobs).
	 *
	 * @param int $max_rounds Safety cap on rounds.
	 * @return int Total processed jobs.
	 */
	public function process_until_empty( $max_rounds = 8 ) {
		$total = 0;
		for ( $round = 0; $round < $max_rounds; ++$round ) {
			$processed = $this->process_batch( 5 );
			$total    += $processed;
			if ( 0 === $processed ) {
				break;
			}
		}
		return $total;
	}

	/**
	 * Run a single job by id.
	 *
	 * @param int $id Job id.
	 * @return bool Success.
	 */
	public function run_job( $id ) {
		global $wpdb;
		$job = $this->get( $id );
		if ( ! $job || 'pending' !== $job['status'] ) {
			return false;
		}

		$wpdb->update( self::table(), array( 'status' => 'running', 'started_at' => current_time( 'mysql' ) ), array( 'id' => $id ) );

		try {
			$result = $this->dispatch( $job['type'], is_array( $job['payload'] ) ? $job['payload'] : array() );
			$wpdb->update(
				self::table(),
				array(
					'status'      => 'complete',
					'result'      => wp_json_encode( $result ),
					'finished_at' => current_time( 'mysql' ),
					'attempts'    => absint( $job['attempts'] ) + 1,
				),
				array( 'id' => $id )
			);
			return true;
		} catch ( \Exception $e ) {
			$attempts = absint( $job['attempts'] ) + 1;
			$status   = $attempts >= absint( $job['max_attempts'] ) ? 'failed' : 'pending';
			$wpdb->update(
				self::table(),
				array(
					'status'      => $status,
					'error'       => $e->getMessage(),
					'attempts'    => $attempts,
					'finished_at' => current_time( 'mysql' ),
				),
				array( 'id' => $id )
			);
			return false;
		}
	}

	/**
	 * Dispatch a job to its handler.
	 *
	 * @param string $type    Job type.
	 * @param array  $payload Payload.
	 * @return array Result.
	 * @throws \Exception When the type is unknown or a handler fails.
	 */
	private function dispatch( $type, array $payload ) {
		$plugin = aiwc();

		switch ( $type ) {
			case 'seo_site_analysis':
				$seo   = $plugin->get( 'seo' );
				$batch = isset( $payload['batch_size'] ) ? absint( $payload['batch_size'] ) : 10;
				$since = isset( $payload['offset'] ) ? absint( $payload['offset'] ) : 0;
				$result = $seo->analyze_site_batch( $batch, $since );
				// Chain the next batch until the whole site is processed.
				if ( empty( $result['finished'] ) ) {
					$result['chained_job'] = $this->push(
						'seo_site_analysis',
						array(
							'batch_size' => $batch,
							'offset'     => $result['processed'],
						)
					);
				}
				return $result;

			case 'tool_batch':
				// Execute a list of approved tool calls sequentially.
				$registry = $plugin->get( 'registry' );
				$results  = array();
				foreach ( (array) ( isset( $payload['calls'] ) ? $payload['calls'] : array() ) as $call ) {
					$name = isset( $call['tool'] ) ? sanitize_text_field( $call['tool'] ) : '';
					$args = isset( $call['args'] ) && is_array( $call['args'] ) ? $call['args'] : array();
					$res  = $registry->execute( $name, $args, array( 'source' => 'queue' ) );
					$results[] = array(
						'tool'   => $name,
						'result' => $res,
					);
				}
				return array( 'results' => $results );

			default:
				throw new \Exception( sprintf( 'Unknown job type: %s', $type ) );
		}
	}
}
