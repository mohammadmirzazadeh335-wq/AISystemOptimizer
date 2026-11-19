<?php
/**
 * REST controller for the Reports section: operations, token usage,
 * success/fail rates, SEO issues, jobs, recent changes.
 *
 * @package AIWC
 */

namespace AIWC\Api;

use AIWC\Backup\Snapshot_Manager;
use AIWC\Chat\Conversation_Store;
use AIWC\Log\Activity_Log;
use AIWC\Queue\Job_Queue;

defined( 'ABSPATH' ) || exit;

/**
 * Reports_Controller
 */
class Reports_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			\AIWC\Api\Api::NS,
			'/reports/summary',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_summary' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);
	}

	/**
	 * GET /reports/summary
	 *
	 * @return \WP_REST_Response
	 */
	public function get_summary() {
		global $wpdb;

		$log_table = Activity_Log::table();

		// Operations: totals and success/fail/pending split.
		$op_counts = $wpdb->get_results(
			"SELECT status, COUNT(*) AS c FROM {$log_table} GROUP BY status", // phpcs:ignore WordPress.DB.PreparedSQL
			ARRAY_A
		);
		$operations = array(
			'total'   => 0,
			'success' => 0,
			'failed'  => 0,
			'other'   => 0,
		);
		foreach ( (array) $op_counts as $row ) {
			$count                = (int) $row['c'];
			$operations['total'] += $count;
			if ( 'success' === $row['status'] ) {
				$operations['success'] += $count;
			} elseif ( in_array( $row['status'], array( 'error', 'failed' ), true ) ) {
				$operations['failed'] += $count;
			} else {
				$operations['other'] += $count;
			}
		}

		// By tool (top 10).
		$by_tool = $wpdb->get_results(
			"SELECT tool_name, COUNT(*) AS c FROM {$log_table} WHERE tool_name <> '' GROUP BY tool_name ORDER BY c DESC LIMIT 10", // phpcs:ignore WordPress.DB.PreparedSQL
			ARRAY_A
		);

		// Token usage: per-conversation totals + message-level completions.
		$conv_table      = Conversation_Store::table();
		$total_tokens    = (int) $wpdb->get_var( "SELECT COALESCE(SUM(tokens_used),0) FROM {$conv_table}" ); // phpcs:ignore WordPress.DB.PreparedSQL
		$msg_table       = Conversation_Store::messages_table();
		$completion_tok  = (int) $wpdb->get_var( "SELECT COALESCE(SUM(tokens),0) FROM {$msg_table} WHERE role = 'assistant'" ); // phpcs:ignore WordPress.DB.PreparedSQL
		$conversation_count = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$conv_table}" ); // phpcs:ignore WordPress.DB.PreparedSQL

		// SEO issues from the stored site report.
		$seo_report = $this->plugin->get( 'seo' )->get_site_report();
		$seo        = array(
			'available'    => ! empty( $seo_report['available'] ),
			'average_score' => isset( $seo_report['average_score'] ) ? (int) $seo_report['average_score'] : null,
			'total_items'  => isset( $seo_report['total'] ) ? (int) $seo_report['total'] : 0,
			'issues'       => array(),
		);
		if ( $seo['available'] && ! empty( $seo_report['items'] ) && is_array( $seo_report['items'] ) ) {
			$issue_counts = array();
			foreach ( $seo_report['items'] as $item ) {
				foreach ( (array) ( $item['top_issues'] ?? array() ) as $code ) {
					$issue_counts[ $code ] = ( $issue_counts[ $code ] ?? 0 ) + 1;
				}
			}
			arsort( $issue_counts );
			$seo['issues'] = array_slice( $issue_counts, 0, 10, true );
		}

		// Jobs (recent background queue entries).
		$queue      = new Job_Queue();
		$jobs       = $queue->list_jobs( 10 );
		$job_items  = array();
		foreach ( (array) $jobs as $job ) {
			$job_items[] = array(
				'id'         => (int) ( $job['id'] ?? 0 ),
				'type'       => (string) ( $job['type'] ?? '' ),
				'status'     => (string) ( $job['status'] ?? '' ),
				'created_at' => (string) ( $job['created_at'] ?? '' ),
			);
		}

		// Recent changes: snapshots + latest successful operations.
		$snapshots    = new Snapshot_Manager( new Activity_Log() );
		$recent_snaps = array();
		foreach ( (array) $snapshots->list_snapshots( 10 ) as $snap ) {
			$recent_snaps[] = array(
				'id'          => (int) ( $snap['id'] ?? 0 ),
				'object_type' => (string) ( $snap['object_type'] ?? '' ),
				'object_id'   => (int) ( $snap['object_id'] ?? 0 ),
				'created_at'  => (string) ( $snap['created_at'] ?? '' ),
			);
		}
		$log            = new Activity_Log();
		$recent_changes = array();
		foreach ( (array) $log->get_logs( array( 'per_page' => 10 ) )['items'] as $row ) {
			$recent_changes[] = array(
				'id'         => (int) ( $row['id'] ?? 0 ),
				'tool'       => (string) ( $row['tool_name'] ?? '' ),
				'summary'    => (string) ( $row['summary'] ?? '' ),
				'status'     => (string) ( $row['status'] ?? '' ),
				'created_at' => (string) ( $row['created_at'] ?? '' ),
			);
		}

		return $this->respond(
			array(
				'operations' => $operations,
				'by_tool'    => (array) $by_tool,
				'tokens'     => array(
					'total'              => $total_tokens,
					'completion_tokens'  => $completion_tok,
					'conversation_count' => $conversation_count,
				),
				'seo'            => $seo,
				'jobs'           => $job_items,
				'recent_changes' => $recent_changes,
				'recent_snapshots' => $recent_snaps,
			)
		);
	}
}
