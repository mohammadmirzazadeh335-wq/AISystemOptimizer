<?php
/**
 * External link checker: extraction, dedupe, queue, cached checks, reports.
 *
 * Scans post content for external links (with anchor text and source page),
 * stores them in the aiwc_links table, checks HTTP status in limited batches
 * with caching, resume, cancellation and SSRF-safe fetching (Url_Guard), and
 * produces a grouped report with fix suggestions.
 *
 * @package AIWC
 */

namespace AIWC\Seo;

use AIWC\Security\Url_Guard;

defined( 'ABSPATH' ) || exit;

/**
 * Class Link_Checker
 */
class Link_Checker {

	const STATUS_PENDING    = 'pending';
	const STATUS_OK         = 'ok';
	const STATUS_BROKEN     = 'broken';
	const STATUS_REDIRECTED = 'redirected';
	const STATUS_TIMEOUT    = 'timeout';
	const STATUS_SSL        = 'ssl_error';
	const STATUS_UNREACHABLE = 'unreachable';
	const STATUS_BLOCKED    = 'blocked';

	/**
	 * Plugin instance.
	 *
	 * @var object
	 */
	private $plugin;

	/**
	 * Constructor.
	 *
	 * @param object $plugin Plugin.
	 */
	public function __construct( $plugin ) {
		$this->plugin = $plugin;
	}

	/**
	 * Table name.
	 *
	 * @return string
	 */
	public static function table() {
		global $wpdb;
		return $wpdb->prefix . 'aiwc_links';
	}

	/**
	 * Extract external links (http/https) with anchors from a post.
	 *
	 * @param int $post_id Post ID.
	 * @return array[] Each: url, anchor, source_post_id.
	 */
	public function extract_from_post( $post_id ) {
		$post = get_post( (int) $post_id );
		if ( ! $post || 'publish' !== $post->post_status ) {
			return array();
		}
		$home = wp_parse_url( home_url(), PHP_URL_HOST );
		$out  = array();

		$content = $post->post_content;
		// Elementor pages store markup in meta.
		$elementor = get_post_meta( $post->ID, '_elementor_data', true );
		if ( $elementor ) {
			$content .= "\n" . (string) $elementor;
		}

		preg_match_all( '/<a\s[^>]*href\s*=\s*([\'"])(.*?)\1[^>]*>(.*?)<\/a>/is', $content, $matches, PREG_SET_ORDER );
		foreach ( $matches as $m ) {
			$href = html_entity_decode( trim( $m[2] ), ENT_QUOTES );
			if ( '' === $href || 0 === strpos( $href, '#' ) || 0 === strpos( $href, 'mailto:' ) || 0 === strpos( $href, 'tel:' ) ) {
				continue;
			}
			$scheme = (string) wp_parse_url( $href, PHP_URL_SCHEME );
			$host   = (string) wp_parse_url( $href, PHP_URL_HOST );
			if ( '' === $host ) {
				continue; // Relative = internal, not our business here.
			}
			if ( ! in_array( $scheme, array( 'http', 'https' ), true ) ) {
				continue;
			}
			$port = (int) wp_parse_url( $href, PHP_URL_PORT );
			if ( strtolower( $host ) === strtolower( (string) $home ) && $port === (int) wp_parse_url( home_url(), PHP_URL_PORT ) ) {
				continue; // Same-site (same host and port).
			}
			$anchor = trim( wp_strip_all_tags( $m[3] ) );
			$out[]  = array(
				'url'            => $href,
				'anchor'         => mb_substr( $anchor, 0, 500 ),
				'source_post_id' => (int) $post->ID,
			);
		}
		return $out;
	}

	/**
	 * Scan posts and enqueue discovered links (deduped per URL+source).
	 *
	 * @param int $post_id Optional single post; 0 = all published posts/pages.
	 * @return array{new: int, total: int, posts: int}
	 */
	public function scan( $post_id = 0 ) {
		global $wpdb;
		if ( $post_id > 0 ) {
			$posts = array( get_post( (int) $post_id ) );
		} else {
			$posts = get_posts(
				array(
					'post_type'      => array( 'post', 'page' ),
					'post_status'    => 'publish',
					'posts_per_page' => 200,
					'fields'         => 'ids',
				)
			);
		}
		$new = 0;
		$now = current_time( 'mysql' );
		foreach ( $posts as $p ) {
			$pid = is_object( $p ) ? (int) $p->ID : (int) $p;
			if ( ! $pid ) {
				continue;
			}
			foreach ( $this->extract_from_post( $pid ) as $link ) {
				$hash = md5( $link['url'] );
				$exists = $wpdb->get_var(
					$wpdb->prepare(
						'SELECT id FROM ' . self::table() . ' WHERE url_hash = %s AND source_post_id = %d',
						$hash,
						$link['source_post_id']
					)
				);
				if ( $exists ) {
					$wpdb->update(
						self::table(),
						array( 'anchor_text' => $link['anchor'] ),
						array( 'id' => (int) $exists )
					);
					continue;
				}
				$wpdb->insert(
					self::table(),
					array(
						'url_hash'       => $hash,
						'url'            => $link['url'],
						'source_post_id' => $link['source_post_id'],
						'anchor_text'    => $link['anchor'],
						'status'         => self::STATUS_PENDING,
						'created_at'     => $now,
					)
				);
				++$new;
			}
		}
		$total = (int) $wpdb->get_var( 'SELECT COUNT(*) FROM ' . self::table() );
		return array(
			'new'   => $new,
			'total' => $total,
			'posts' => count( array_filter( $posts ) ),
		);
	}

	/**
	 * Cancel a running link check (cooperative, between batches).
	 */
	public function cancel() {
		set_transient( 'aiwc_link_cancel', time(), 5 * MINUTE_IN_SECONDS );
	}

	/**
	 * Is cancellation requested? Consumes the flag so one cancel aborts one
	 * run and never leaks into later batches.
	 *
	 * @return bool
	 */
	private function is_cancelled() {
		if ( get_transient( 'aiwc_link_cancel' ) ) {
			delete_transient( 'aiwc_link_cancel' );
			return true;
		}
		return false;
	}

	/**
	 * Check up to $limit pending/stale links. Resumable: unprocessed rows
	 * stay pending. Cached results (fresh) are skipped.
	 *
	 * @param int  $limit        Max links to check in this batch.
	 * @param bool $force        Re-check even cached results.
	 * @param int  $max_age_days Cache freshness window.
	 * @return array{checked: int, remaining: int, cancelled: bool, results: array[]}
	 */
	public function check_pending( $limit = 10, $force = false, $max_age_days = 7 ) {
		global $wpdb;
		$limit = max( 1, min( 50, (int) $limit ) );
		$stale = gmdate( 'Y-m-d H:i:s', time() - max( 1, $max_age_days ) * DAY_IN_SECONDS );

		// One row per unique URL (dedupe): others share the result afterwards.
		$rows = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT * FROM ' . self::table() . " WHERE ( status = %s OR ( checked_at IS NOT NULL AND checked_at < %s ) ) ORDER BY id ASC LIMIT %d",
				self::STATUS_PENDING,
				$stale,
				$limit
			),
			ARRAY_A
		);
		if ( ! is_array( $rows ) ) {
			$rows = array();
		}

		$results  = array();
		$checked  = 0;
		$cancel   = false;
		$deferred = array();

		foreach ( $rows as $row ) {
			if ( $this->is_cancelled() ) {
				$cancel = true;
				break;
			}
			// Skip duplicate URLs within the batch — copy the fresh result.
			$hash = $row['url_hash'];
			if ( isset( $deferred[ $hash ] ) ) {
				$this->store_result( $row, $deferred[ $hash ] );
				continue;
			}
			$one    = $this->check_url( $row['url'] );
			$checked++;
			$deferred[ $hash ] = $one;
			$results[]         = array_merge( array( 'url' => $row['url'] ), $one );
			$this->store_result( $row, $one );
		}

		if ( $cancel ) {
			delete_transient( 'aiwc_link_cancel' );
		}

		$remaining = (int) $wpdb->get_var(
			$wpdb->prepare( 'SELECT COUNT(*) FROM ' . self::table() . ' WHERE status = %s', self::STATUS_PENDING )
		);
		return array(
			'checked'   => $checked,
			'remaining' => $remaining,
			'cancelled' => $cancel,
			'results'   => $results,
		);
	}

	/**
	 * Check a single URL (SSRF-safe, manual redirect following).
	 *
	 * @param string $url URL.
	 * @return array{status: string, http_code: int, final_url: string, redirect_count: int, error: string}
	 */
	public function check_url( $url ) {
		$start = microtime( true );

		$guard = Url_Guard::validate_url( $url );
		if ( is_wp_error( $guard ) ) {
			return array(
				'status'         => self::STATUS_BLOCKED,
				'http_code'      => 0,
				'final_url'      => '',
				'redirect_count' => 0,
				'error'          => $guard->get_error_message(),
			);
		}

		$timeout = max( 2, (int) apply_filters( 'aiwc_link_check_timeout', defined( 'AIWC_TEST_MODE' ) ? 8 : 8 ) );
		$out     = Url_Guard::request_with_validated_redirects(
			$url,
			array(
				'timeout'     => $timeout,
				'user-agent'  => 'Mozilla/5.0 (compatible; AILinkChecker/1.0; +' . home_url( '/' ) . ')',
			),
			5
		);

		$response = $out['response'];
		$redirects = count( $out['redirects'] );

		if ( is_wp_error( $response ) ) {
			$code = $response->get_error_code();
			$msg  = $response->get_error_message();
			if ( false !== strpos( $code, 'private_ip' ) || false !== strpos( $code, 'url_' ) ) {
				$status = self::STATUS_BLOCKED;
			} elseif ( false !== stripos( $msg, 'timed out' ) || 'http_request_failed' === $code && false !== stripos( $msg, 'timed out' ) ) {
				$status = self::STATUS_TIMEOUT;
			} elseif ( false !== stripos( $msg, 'ssl' ) || false !== stripos( $msg, 'certificate' ) ) {
				$status = self::STATUS_SSL;
			} elseif ( 'aiwc_too_many_redirects' === $code ) {
				$status = self::STATUS_BROKEN;
			} else {
				$status = self::STATUS_UNREACHABLE;
			}
			return array(
				'status'         => $status,
				'http_code'      => 0,
				'final_url'      => $out['final_url'],
				'redirect_count' => $redirects,
				'error'          => self::short_error( $msg ),
			);
		}

		$http_code = (int) wp_remote_retrieve_response_code( $response );
		$elapsed   = microtime( true ) - $start;

		if ( $http_code >= 200 && $http_code < 300 ) {
			$status = $redirects > 0 ? self::STATUS_REDIRECTED : self::STATUS_OK;
		} elseif ( $http_code >= 300 && $http_code < 400 ) {
			$status = self::STATUS_REDIRECTED; // Unfollowed 3xx (no location).
		} else {
			$status = self::STATUS_BROKEN;
		}

		return array(
			'status'         => $status,
			'http_code'      => $http_code,
			'final_url'      => $out['final_url'],
			'redirect_count' => $redirects,
			'error'          => $http_code >= 400 ? sprintf( 'HTTP %d', $http_code ) : ( $elapsed > $timeout ? 'slow' : '' ),
		);
	}

	/**
	 * Persist a check result for a queue row (+ mirror to same-URL rows).
	 *
	 * @param array $row  Queue row.
	 * @param array $info check_url() result.
	 * @return void
	 */
	private function store_result( array $row, array $info ) {
		global $wpdb;
		$data = array(
			'status'         => $info['status'],
			'http_code'      => (int) $info['http_code'],
			'final_url'      => $info['final_url'] ? $info['final_url'] : null,
			'redirect_count' => (int) $info['redirect_count'],
			'error_message'  => mb_substr( (string) $info['error'], 0, 500 ),
			'attempts'       => (int) $row['attempts'] + 1,
			'checked_at'     => current_time( 'mysql' ),
		);
		$wpdb->update( self::table(), $data, array( 'id' => (int) $row['id'] ) );
		// Propagate to other source pages carrying the identical URL.
		$wpdb->update(
			self::table(),
			$data + array( 'attempts' => (int) $row['attempts'] + 1 ),
			array( 'url_hash' => $row['url_hash'], 'status' => self::STATUS_PENDING )
		);
	}

	/**
	 * Grouped report with fix suggestions.
	 *
	 * @param int $per_group Max rows per group.
	 * @return array
	 */
	public function report( $per_group = 50 ) {
		global $wpdb;
		$per_group = max( 1, min( 200, (int) $per_group ) );
		$rows      = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT * FROM ' . self::table() . ' ORDER BY status ASC, url ASC LIMIT %d',
				$per_group * 6
			),
			ARRAY_A
		);
		$groups = array(
			'broken'      => array(),
			'redirected'  => array(),
			'timeout'     => array(),
			'ssl_error'   => array(),
			'unreachable' => array(),
			'blocked'     => array(),
			'ok'          => array(),
			'pending'     => array(),
		);
		foreach ( (array) $rows as $row ) {
			$g = isset( $groups[ $row['status'] ] ) ? $row['status'] : 'pending';
			if ( count( $groups[ $g ] ) >= $per_group ) {
				continue;
			}
			$groups[ $g ][] = array(
				'id'             => (int) $row['id'],
				'url'            => $row['url'],
				'anchor'         => $row['anchor_text'],
				'source_post_id' => (int) $row['source_post_id'],
				'source_title'   => get_the_title( (int) $row['source_post_id'] ),
				'source_url'     => get_permalink( (int) $row['source_post_id'] ),
				'http_code'      => (int) $row['http_code'],
				'final_url'      => $row['final_url'],
				'redirect_count' => (int) $row['redirect_count'],
				'error'          => $row['error_message'],
				'checked_at'     => $row['checked_at'],
				'suggestion'     => $this->suggestion( $row ),
			);
		}
		$counts = array();
		foreach ( $groups as $g => $items ) {
			$counts[ $g ] = (int) $wpdb->get_var( $wpdb->prepare( 'SELECT COUNT(*) FROM ' . self::table() . ' WHERE status = %s', $g ) );
		}
		return array(
			'counts' => $counts,
			'groups' => $groups,
		);
	}

	/**
	 * Fix suggestion for one row.
	 *
	 * @param array $row Row.
	 * @return string
	 */
	private function suggestion( array $row ) {
		switch ( $row['status'] ) {
			case self::STATUS_BROKEN:
				if ( (int) $row['http_code'] === 404 || (int) $row['http_code'] === 410 ) {
					return __( 'Link returns 404/410 — remove it or replace it with a working target (web.archive.org may hold a copy).', 'ai-wordpress-copilot' );
				}
				return __( 'Link is failing — verify the address manually, update or remove it.', 'ai-wordpress-copilot' );
			case self::STATUS_REDIRECTED:
				/* translators: %s: final URL */
				return sprintf( __( 'Link redirects — update it to the final URL: %s', 'ai-wordpress-copilot' ), (string) $row['final_url'] );
			case self::STATUS_TIMEOUT:
				return __( 'Target timed out — retry later or link to an alternative resource.', 'ai-wordpress-copilot' );
			case self::STATUS_SSL:
				return __( 'TLS/SSL problem on the target — use a correct HTTPS URL or link to an alternative.', 'ai-wordpress-copilot' );
			case self::STATUS_UNREACHABLE:
				return __( 'Host unreachable — verify the domain still exists; remove if it is gone.', 'ai-wordpress-copilot' );
			case self::STATUS_BLOCKED:
				return __( 'URL blocked by SSRF protection (internal/private target) — remove it from public content.', 'ai-wordpress-copilot' );
			default:
				return '';
		}
	}

	/**
	 * Shorten transport error strings.
	 *
	 * @param string $msg Message.
	 * @return string
	 */
	private function short_error( $msg ) {
		$msg = trim( (string) $msg );
		if ( strlen( $msg ) > 300 ) {
			$msg = substr( $msg, 0, 300 ) . '…';
		}
		return $msg;
	}

	/**
	 * Cached status lookup for one URL (used by the SEO analyzer).
	 *
	 * @param string $url URL.
	 * @return array|null
	 */
	public static function cached_status( $url ) {
		global $wpdb;
		$row = $wpdb->get_row(
			$wpdb->prepare(
				'SELECT * FROM ' . self::table() . ' WHERE url_hash = %s ORDER BY checked_at DESC LIMIT 1',
				md5( $url )
			),
			ARRAY_A
		);
		return $row ? $row : null;
	}
}
