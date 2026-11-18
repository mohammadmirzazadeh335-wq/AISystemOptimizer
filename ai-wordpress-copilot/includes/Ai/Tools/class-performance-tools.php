<?php
/**
 * Performance analysis tool (real, measurable checks).
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;

defined( 'ABSPATH' ) || exit;

/**
 * Site speed / performance diagnostics.
 */
class Performance_Tools extends Abstract_Tool_Group {

	/**
	 * Declare tools.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'performance_analyze',
				'description' => 'Analyze site speed and performance: homepage weight, number of scripts/styles, image lazy-load usage, caching headers, autoloaded options size, transients, active plugins count and optimization hints. Returns a 0-100 performance score with issues and fixes.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'page_url' => array( 'type' => 'string', 'description' => 'Optional page URL to analyze (default: homepage).' ),
					),
				),
				'risk'        => 'read',
				'handler'     => 'handle_performance_analyze',
			),
		);
	}

	/**
	 * performance_analyze
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_performance_analyze( array $args ) {
		$url = ! empty( $args['page_url'] ) ? esc_url_raw( $args['page_url'] ) : home_url( '/' );
		$issues = array();
		$checks = array();

		// 1. Fetch the page and measure size + asset counts.
		$start    = microtime( true );
		$response = wp_remote_get( $url, array( 'timeout' => 10, 'redirection' => 3 ) );
		$elapsed  = (int) ( ( microtime( true ) - $start ) * 1000 );

		if ( is_wp_error( $response ) ) {
			// Loopback fetch can fail on hosts that block self-requests (also common
			// behind strict firewalls). Degrade gracefully: keep the local checks.
			$checks['page'] = array(
				'url'     => $url,
				'skipped' => 'unreachable: ' . $response->get_error_message(),
			);
			$issues[] = $this->issue( 'page_unreachable', 'low', 'Could not fetch the page over HTTP for front-end analysis.', 'Check that the site can reach itself (loopback request); server-side checks below are unaffected.' );
			$body     = '';
		} else {
			$body      = (string) wp_remote_retrieve_body( $response );
			$size_kb   = (int) round( strlen( $body ) / 1024 );
			$checks['page'] = array(
				'url'           => $url,
				'size_kb'       => $size_kb,
				'load_time_ms'  => $elapsed,
				'status_code'   => (int) wp_remote_retrieve_response_code( $response ),
			);

			if ( $size_kb > 300 ) {
				$issues[] = $this->issue( 'page_heavy', 'high', sprintf( 'Homepage HTML is heavy (%d KB).', $size_kb ), 'Reduce inline content, move large data to assets, enable gzip on the server.' );
			} elseif ( $size_kb > 150 ) {
				$issues[] = $this->issue( 'page_medium', 'medium', sprintf( 'Homepage HTML is %d KB.', $size_kb ), 'Consider trimming large inline blocks.' );
			}
		}

		// 2. Script / style counts.
		preg_match_all( '/<script[^>]+src=/i', $body, $scripts );
		preg_match_all( '/<link[^>]+rel=["\']?stylesheet/i', $body, $styles );
		preg_match_all( '/<img[^>]+>/i', $body, $images );
		$checks['assets'] = array(
			'scripts' => count( $scripts[0] ),
			'styles'  => count( $styles[0] ),
			'images'  => count( $images[0] ),
		);

		if ( count( $scripts[0] ) > 25 ) {
			$issues[] = $this->issue( 'many_scripts', 'medium', sprintf( '%d script files loaded on the page.', count( $scripts[0] ) ), 'Dequeue unused scripts, defer/async non-critical JS, combine where possible.' );
		}
		if ( count( $styles[0] ) > 15 ) {
			$issues[] = $this->issue( 'many_styles', 'low', sprintf( '%d stylesheet files loaded.', count( $styles[0] ) ), 'Remove unused CSS and merge stylesheets.' );
		}

		// 3. Image best practices (lazy load, dimensions).
		$no_lazy = 0;
		$no_dims = 0;
		foreach ( $images[0] as $img ) {
			if ( ! preg_match( '/loading\s*=\s*["\']?lazy/i', $img ) ) {
				++$no_lazy;
			}
			if ( ! preg_match( '/(width|height)\s*=/i', $img ) ) {
				++$no_dims;
			}
		}
		$checks['images_best_practice'] = array( 'without_lazy_load' => $no_lazy, 'without_dimensions' => $no_dims );
		if ( $no_lazy > 3 ) {
			$issues[] = $this->issue( 'img_no_lazy', 'medium', sprintf( '%d image(s) without lazy loading.', $no_lazy ), 'Add loading="lazy" to below-the-fold images.' );
		}
		if ( $no_dims > 3 ) {
			$issues[] = $this->issue( 'img_no_dims', 'medium', sprintf( '%d image(s) without width/height (layout shift risk).', $no_dims ), 'Set explicit width/height attributes on images.' );
		}

		// 4. Cache headers.
		$headers = wp_remote_retrieve_headers( $response );
		$cache_control = isset( $headers['cache-control'] ) ? (string) $headers['cache-control'] : '';
		$checks['cache_control'] = $cache_control ? $cache_control : '(none)';
		if ( ! $cache_control ) {
			$issues[] = $this->issue( 'no_cache_headers', 'medium', 'No Cache-Control header on the page.', 'Enable page/object caching (host cache, WP Super Cache, W3TC or similar).' );
		}

		// 5. Database / options health.
		global $wpdb;
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$autoload_kb = (int) round( (int) $wpdb->get_var( "SELECT SUM(LENGTH(option_value)) FROM {$wpdb->options} WHERE autoload IN ('yes','on','auto','auto-on')" ) / 1024 );
		// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		$transients = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$wpdb->options} WHERE option_name LIKE '_transient_timeout_%'" );
		$checks['database'] = array(
			'autoloaded_options_kb' => $autoload_kb,
			'transients'            => $transients,
		);
		if ( $autoload_kb > 800 ) {
			$issues[] = $this->issue( 'autoload_heavy', 'high', sprintf( 'Autoloaded options are large (%d KB) — slows every page load.', $autoload_kb ), 'Disable autoload on large options (e.g. old plugin data), clean up with a database optimizer.' );
		} elseif ( $autoload_kb > 400 ) {
			$issues[] = $this->issue( 'autoload_medium', 'medium', sprintf( 'Autoloaded options: %d KB.', $autoload_kb ), 'Review large autoloaded options.' );
		}
		if ( $transients > 500 ) {
			$issues[] = $this->issue( 'many_transients', 'low', sprintf( '%d transients stored.', $transients ), 'Expired transients accumulate; schedule periodic cleanup.' );
		}

		// 6. Environment hints.
		$active_plugins = (array) get_option( 'active_plugins', array() );
		$checks['environment'] = array(
			'active_plugins' => count( $active_plugins ),
			'wp_debug'       => ( defined( 'WP_DEBUG' ) && WP_DEBUG ) ? 'on (disable on production!)' : 'off',
			'gzip_header'    => isset( $headers['content-encoding'] ) ? (string) $headers['content-encoding'] : '(none)',
		);
		if ( count( $active_plugins ) > 25 ) {
			$issues[] = $this->issue( 'many_plugins', 'medium', sprintf( '%d active plugins.', count( $active_plugins ) ), 'Deactivate unused plugins; each adds load time.' );
		}
		if ( defined( 'WP_DEBUG' ) && WP_DEBUG ) {
			$issues[] = $this->issue( 'debug_on', 'high', 'WP_DEBUG is enabled on the site.', 'Turn off WP_DEBUG on production (error logging slows pages and leaks paths).' );
		}
		if ( ! isset( $headers['content-encoding'] ) ) {
			$issues[] = $this->issue( 'no_gzip', 'medium', 'Response is not compressed (no gzip/br).', 'Enable gzip/brotli compression on the web server or CDN.' );
		}

		// Score.
		$score = 100;
		$weights = array( 'high' => 12, 'medium' => 7, 'low' => 3 );
		foreach ( $issues as $issue ) {
			$score -= $weights[ $issue['severity'] ];
		}
		$score = max( 0, min( 100, $score ) );

		return $this->success(
			array(
				'score'  => $score,
				'checks' => $checks,
				'issues' => $issues,
			),
			sprintf( 'Performance score %d/100 with %d issue(s).', $score, count( $issues ) )
		);
	}

	/**
	 * Issue factory.
	 *
	 * @param string $code     Code.
	 * @param string $severity Severity.
	 * @param string $message  Message.
	 * @param string $fix      Fix suggestion.
	 * @return array
	 */
	private function issue( $code, $severity, $message, $fix ) {
		return array(
			'code'     => $code,
			'severity' => $severity,
			'message'  => $message,
			'fix'      => $fix,
		);
	}
}
