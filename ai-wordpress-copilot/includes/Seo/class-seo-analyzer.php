<?php
/**
 * SEO analysis engine with real checks and scoring.
 *
 * @package AIWC
 */

namespace AIWC\Seo;

use AIWC\Context\Site_Context_Engine;

defined( 'ABSPATH' ) || exit;

/**
 * Analyzes posts/pages for on-page SEO quality.
 */
class Seo_Analyzer {

	/**
	 * Site context engine.
	 *
	 * @var Site_Context_Engine
	 */
	private $context;

	/**
	 * Constructor.
	 *
	 * @param Site_Context_Engine $context Context engine.
	 */
	public function __construct( Site_Context_Engine $context ) {
		$this->context = $context;
	}

	/**
	 * Get the effective SEO meta of a post (our meta > Rank Math > Yoast > defaults).
	 *
	 * @param int $post_id Post id.
	 * @return array{title: string, desc: string, keyword: string, source: string}
	 */
	public function get_seo_meta( $post_id ) {
		$post = get_post( $post_id );
		if ( ! $post ) {
			return array( 'title' => '', 'desc' => '', 'keyword' => '', 'source' => 'none' );
		}

		$title   = (string) get_post_meta( $post_id, '_aiwc_seo_title', true );
		$desc    = (string) get_post_meta( $post_id, '_aiwc_seo_desc', true );
		$keyword = (string) get_post_meta( $post_id, '_aiwc_seo_keyword', true );
		$source  = 'aiwc';

		if ( '' === $title && defined( 'RANK_MATH_VERSION' ) ) {
			$title = (string) get_post_meta( $post_id, 'rank_math_title', true );
			$desc  = $desc ? $desc : (string) get_post_meta( $post_id, 'rank_math_description', true );
			$keyword = $keyword ? $keyword : (string) get_post_meta( $post_id, 'rank_math_focus_keyword', true );
			$source  = $title ? 'rank_math' : $source;
		}
		if ( '' === $title && defined( 'WPSEO_VERSION' ) ) {
			$title = (string) get_post_meta( $post_id, '_yoast_wpseo_title', true );
			$desc  = $desc ? $desc : (string) get_post_meta( $post_id, '_yoast_wpseo_metadesc', true );
			$keyword = $keyword ? $keyword : (string) get_post_meta( $post_id, '_yoast_wpseo_focuskw', true );
			$source  = $title ? 'yoast' : $source;
		}

		if ( '' === $title ) {
			$title = $post->post_title;
			$source = 'default';
		}
		if ( '' === $desc ) {
			$plain  = wp_strip_all_tags( $post->post_content );
			$desc   = mb_substr( $plain, 0, 155 );
			$source = 'default' === $source ? 'default' : $source;
		}

		return array(
			'title'   => $title,
			'desc'    => $desc,
			'keyword' => $keyword,
			'source'  => $source,
		);
	}

	/**
	 * Save SEO meta for a post (writes to our meta AND detected SEO plugin meta).
	 *
	 * @param int    $post_id Post id.
	 * @param string $title   SEO title.
	 * @param string $desc    Meta description.
	 * @param string $keyword Focus keyword.
	 * @return array Saved values.
	 */
	public function save_seo_meta( $post_id, $title = null, $desc = null, $keyword = null ) {
		if ( null !== $title ) {
			update_post_meta( $post_id, '_aiwc_seo_title', sanitize_text_field( $title ) );
			if ( defined( 'WPSEO_VERSION' ) ) {
				update_post_meta( $post_id, '_yoast_wpseo_title', sanitize_text_field( $title ) );
			}
			if ( defined( 'RANK_MATH_VERSION' ) ) {
				update_post_meta( $post_id, 'rank_math_title', sanitize_text_field( $title ) );
			}
		}
		if ( null !== $desc ) {
			update_post_meta( $post_id, '_aiwc_seo_desc', sanitize_textarea_field( $desc ) );
			if ( defined( 'WPSEO_VERSION' ) ) {
				update_post_meta( $post_id, '_yoast_wpseo_metadesc', sanitize_textarea_field( $desc ) );
			}
			if ( defined( 'RANK_MATH_VERSION' ) ) {
				update_post_meta( $post_id, 'rank_math_description', sanitize_textarea_field( $desc ) );
			}
		}
		if ( null !== $keyword ) {
			update_post_meta( $post_id, '_aiwc_seo_keyword', sanitize_text_field( $keyword ) );
			if ( defined( 'WPSEO_VERSION' ) ) {
				update_post_meta( $post_id, '_yoast_wpseo_focuskw', sanitize_text_field( $keyword ) );
			}
			if ( defined( 'RANK_MATH_VERSION' ) ) {
				update_post_meta( $post_id, 'rank_math_focus_keyword', sanitize_text_field( $keyword ) );
			}
		}
		return $this->get_seo_meta( $post_id );
	}

	/**
	 * Analyze one post/page.
	 *
	 * @param int   $post_id Post id.
	 * @param array $extra   Extra options: keyword override, check_broken_links.
	 * @return array|WP_Error Analysis result with score and issues.
	 */
	public function analyze_post( $post_id, array $extra = array() ) {
		$post = get_post( absint( $post_id ) );
		if ( ! $post ) {
			return new \WP_Error( 'aiwc_seo_not_found', sprintf( 'Post %d not found.', $post_id ), array( 'status' => 404 ) );
		}

		$content   = $post->post_content;
		$plain     = wp_strip_all_tags( $content );
		$word_count = str_word_count( $plain );
		$meta      = $this->get_seo_meta( $post->ID );
		$keyword   = ! empty( $extra['keyword'] ) ? sanitize_text_field( $extra['keyword'] ) : $meta['keyword'];

		$issues = array();
		$checks = array();

		// 1. SEO title.
		$title_len = mb_strlen( $meta['title'] );
		$checks['seo_title'] = array( 'value' => $meta['title'], 'length' => $title_len );
		if ( $title_len < 30 ) {
			$issues[] = $this->issue( 'title_short', 'medium', sprintf( 'SEO title is too short (%d chars). Aim for 30-60 characters.', $title_len ), 'Extend the SEO title with the focus keyword and brand name.' );
		} elseif ( $title_len > 60 ) {
			$issues[] = $this->issue( 'title_long', 'low', sprintf( 'SEO title is too long (%d chars). It may be truncated in search results.', $title_len ), 'Shorten the title to under 60 characters.' );
		}

		// 2. Meta description.
		$desc_len = mb_strlen( $meta['desc'] );
		$checks['meta_description'] = array( 'value' => $meta['desc'], 'length' => $desc_len );
		if ( $desc_len < 70 ) {
			$issues[] = $this->issue( 'desc_short', 'medium', sprintf( 'Meta description is too short (%d chars). Aim for 70-160 characters.', $desc_len ), 'Write a compelling meta description of 70-160 characters.' );
		} elseif ( $desc_len > 160 ) {
			$issues[] = $this->issue( 'desc_long', 'low', sprintf( 'Meta description is too long (%d chars).', $desc_len ), 'Trim the description to under 160 characters.' );
		}

		// 3. Headings structure.
		preg_match_all( '/<h([1-6])[^>]*>(.*?)<\/h\1>/is', $content, $heading_matches, PREG_SET_ORDER );
		$levels = array();
		$heading_texts = array();
		foreach ( $heading_matches as $match ) {
			$levels[] = (int) $match[1];
			$heading_texts[] = wp_strip_all_tags( $match[2] );
		}
		$checks['headings'] = array( 'levels' => $levels, 'count' => count( $levels ) );
		$h1_count = count( array_keys( $levels, 1 ) );
		if ( 'page' === $post->post_type || 'post' === $post->post_type ) {
			if ( 0 === $h1_count && count( $levels ) > 0 ) {
				$issues[] = $this->issue( 'no_h1', 'high', 'Content has headings but no H1.', 'Add exactly one H1 containing the focus keyword.' );
			}
			if ( $h1_count > 1 ) {
				$issues[] = $this->issue( 'multiple_h1', 'medium', sprintf( 'Content contains %d H1 headings.', $h1_count ), 'Keep a single H1 and demote extras to H2.' );
			}
		}

		// 4. Images alt attributes.
		preg_match_all( '/<img[^>]+>/i', $content, $img_matches );
		$missing_alt = 0;
		foreach ( $img_matches[0] as $img_tag ) {
			if ( ! preg_match( '/alt\s*=\s*([\'"]).+?\1/i', $img_tag ) ) {
				++$missing_alt;
			}
		}
		$checks['images'] = array( 'total' => count( $img_matches[0] ), 'missing_alt' => $missing_alt );
		if ( $missing_alt > 0 ) {
			$issues[] = $this->issue( 'img_alt', 'medium', sprintf( '%d image(s) missing alt text.', $missing_alt ), 'Add descriptive alt text to every image (use the update_media_alt tool).' );
		}

		// 5. Links.
		preg_match_all( '/<a\s[^>]*href\s*=\s*([\'"])(.*?)\1/i', $content, $link_matches );
		$internal       = 0;
		$external       = 0;
		$broken         = array();
		$external_links = array();
		$site_host = wp_parse_url( home_url(), PHP_URL_HOST );
		foreach ( $link_matches[2] as $href ) {
			$href = html_entity_decode( $href );
			if ( 0 === strpos( $href, '#' ) || 0 === strpos( $href, 'mailto:' ) ) {
				continue;
			}
			$host = wp_parse_url( $href, PHP_URL_HOST );
			$port = (int) wp_parse_url( $href, PHP_URL_PORT );
			if ( ! $host || ( $host === $site_host && $port === (int) wp_parse_url( home_url(), PHP_URL_PORT ) ) ) {
				++$internal;
				// Verify internal link resolves (post name or path).
				$path = wp_parse_url( $href, PHP_URL_PATH );
				if ( $path && '/' !== $path ) {
					$linked = url_to_postid( $href );
					if ( ! $linked && ! get_page_by_path( trim( $path, '/' ) ) ) {
						$broken[] = $href;
					}
				}
			} else {
				++$external;
				$external_links[] = $href;
			}
		}
		$checks['links'] = array( 'internal' => $internal, 'external' => $external, 'broken' => $broken );
		if ( $internal < 2 && $word_count > 200 ) {
			$issues[] = $this->issue( 'few_internal_links', 'medium', sprintf( 'Only %d internal link(s) found.', $internal ), 'Add at least 2-3 contextual internal links to related content.' );
		}
		if ( $broken ) {
			$issues[] = $this->issue( 'broken_links', 'high', sprintf( 'Broken internal link(s): %s', implode( ', ', array_slice( $broken, 0, 5 ) ) ), 'Fix or remove the broken links.' );
		}

		// External link statuses from the link checker cache (run /links/scan +
		// /links/check to populate; the analyzer stays fast by never fetching).
		$ext_broken = array();
		$ext_status = array();
		foreach ( array_unique( $external_links ) as $ext_url ) {
			$row = Link_Checker::cached_status( $ext_url );
			$ext_status[ $ext_url ] = $row && 'pending' !== $row['status'] ? $row['status'] : 'unchecked';
			if ( $row && in_array( $row['status'], array( 'broken', 'timeout', 'unreachable', 'ssl_error' ), true ) ) {
				$ext_broken[] = $ext_url;
			}
		}
		if ( $ext_status ) {
			$checks['links']['external_status'] = $ext_status;
		}
		if ( $ext_broken ) {
			$issues[] = $this->issue(
				'broken_external_links',
				'high',
				sprintf( 'Broken external link(s): %s', implode( ', ', array_slice( $ext_broken, 0, 5 ) ) ),
				'Open the link report (Website Builder → Links) for fix suggestions; update or remove the failing links.'
			);
		}

		// 6. Content length.
		$checks['word_count'] = $word_count;
		if ( 'post' === $post->post_type && $word_count < 300 ) {
			$issues[] = $this->issue( 'thin_content', 'high', sprintf( 'Content is thin (%d words).', $word_count ), 'Expand the content to at least 300 words of useful text.' );
		}

		// 7. Focus keyword usage.
		if ( $keyword ) {
			$kw_lower = mb_strtolower( $keyword );
			$checks['focus_keyword'] = array(
				'keyword'        => $keyword,
				'in_title'       => false !== mb_strpos( mb_strtolower( $meta['title'] ), $kw_lower ),
				'in_first_para'  => false !== mb_strpos( mb_strtolower( mb_substr( $plain, 0, 300 ) ), $kw_lower ),
				'in_headings'    => false,
				'in_slug'        => false !== mb_strpos( $post->post_name, sanitize_title( $keyword ) ),
				'density'        => 0.0,
			);
			foreach ( $heading_texts as $ht ) {
				if ( false !== mb_strpos( mb_strtolower( $ht ), $kw_lower ) ) {
					$checks['focus_keyword']['in_headings'] = true;
					break;
				}
			}
			$occurrences = mb_substr_count( mb_strtolower( $plain ), $kw_lower );
			$checks['focus_keyword']['density'] = $word_count > 0 ? round( 100 * $occurrences / $word_count, 2 ) : 0;

			if ( ! $checks['focus_keyword']['in_title'] ) {
				$issues[] = $this->issue( 'kw_title', 'high', sprintf( 'Focus keyword "%s" is not in the SEO title.', $keyword ), 'Include the focus keyword in the SEO title.' );
			}
			if ( ! $checks['focus_keyword']['in_first_para'] ) {
				$issues[] = $this->issue( 'kw_intro', 'medium', 'Focus keyword is not in the first paragraph.', 'Mention the focus keyword in the opening paragraph.' );
			}
		} else {
			$checks['focus_keyword'] = array( 'keyword' => '' );
			$issues[] = $this->issue( 'no_keyword', 'medium', 'No focus keyword defined.', 'Set a focus keyword for this content.' );
		}

		// 8. Slug quality.
		$slug = $post->post_name;
		$checks['slug'] = $slug;
		if ( strlen( $slug ) > 60 ) {
			$issues[] = $this->issue( 'slug_long', 'low', 'URL slug is long (>60 chars).', 'Use a shorter, keyword-rich slug.' );
		}
		if ( preg_match( '/\d{4,}/', $slug ) ) {
			$issues[] = $this->issue( 'slug_numbers', 'low', 'Slug contains long numeric fragments.', 'Use human-readable words in the slug.' );
		}

		// 9. Schema / structured data presence.
		$has_schema = false !== strpos( $content, 'application/ld+json' ) || '' !== (string) get_post_meta( $post->ID, '_aiwc_schema', true );
		$checks['schema'] = $has_schema;
		if ( ! $has_schema && 'post' === $post->post_type ) {
			$issues[] = $this->issue( 'no_schema', 'low', 'No structured data (Schema.org) detected.', 'Add Article schema (JSON-LD) to improve rich results.' );
		}

		// 10. Duplicate content (content hash vs other posts).
		$hash         = md5( $plain );
		$has_duplicate = false;
		$others = get_posts(
			array(
				'post_type'      => array( 'post', 'page' ),
				'post_status'    => 'publish',
				'posts_per_page' => 50,
				'exclude'        => array( $post->ID ),
				'fields'         => 'ids',
			)
		);
		foreach ( $others as $other_id ) {
			$other_plain = wp_strip_all_tags( (string) get_post_field( 'post_content', $other_id ) );
			if ( md5( $other_plain ) === $hash && '' !== $other_plain ) {
				$has_duplicate = true;
				$issues[] = $this->issue( 'duplicate_content', 'high', sprintf( 'Content is identical to post #%d.', $other_id ), 'Differentiate or consolidate duplicate content.' );
				break;
			}
		}
		$checks['duplicate'] = $has_duplicate;

		// Score.
		$score = 100;
		$weights = array( 'high' => 12, 'medium' => 7, 'low' => 3 );
		foreach ( $issues as $issue ) {
			$score -= $weights[ $issue['severity'] ];
		}
		$score = max( 0, min( 100, $score ) );

		return array(
			'post_id'    => (int) $post->ID,
			'title'      => $post->post_title,
			'url'        => get_permalink( $post->ID ),
			'score'      => $score,
			'seo_meta'   => $meta,
			'checks'     => $checks,
			'issues'     => $issues,
			'issue_count' => count( $issues ),
		);
	}

	/**
	 * Analyze a batch of posts for the site-wide report (queue handler).
	 *
	 * @param int $batch_size Posts per batch.
	 * @param int $offset     Offset into the post list.
	 * @return array Progress info.
	 */
	public function analyze_site_batch( $batch_size = 10, $offset = 0 ) {
		$query = new \WP_Query(
			array(
				'post_type'      => array( 'post', 'page' ),
				'post_status'    => 'publish',
				'posts_per_page' => max( 1, min( 25, absint( $batch_size ) ) ),
				'offset'         => absint( $offset ),
				'fields'         => 'ids',
				'orderby'        => 'ID',
				'order'          => 'ASC',
			)
		);

		$report = get_option( 'aiwc_seo_report', array() );
		if ( ! is_array( $report ) || absint( $offset ) === 0 ) {
			$report = array(
				'started_at' => current_time( 'mysql' ),
				'total'      => (int) $query->found_posts,
				'items'      => array(),
			);
		}

		foreach ( $query->posts as $post_id ) {
			$analysis = $this->analyze_post( $post_id );
			if ( ! is_wp_error( $analysis ) ) {
				$report['items'][] = array(
					'post_id'    => $analysis['post_id'],
					'title'      => $analysis['title'],
					'url'        => $analysis['url'],
					'score'      => $analysis['score'],
					'issue_count' => $analysis['issue_count'],
					'top_issues' => array_slice(
						array_map(
							function ( $issue ) {
								return $issue['code'];
							},
							$analysis['issues']
						),
						0,
						5
					),
				);
			}
		}

		$report['processed'] = absint( $offset ) + count( $query->posts );
		$report['finished']  = $report['processed'] >= $report['total'];
		if ( $report['finished'] ) {
			$report['finished_at'] = current_time( 'mysql' );
			$scores = wp_list_pluck( $report['items'], 'score' );
			$report['average_score'] = $scores ? (int) round( array_sum( $scores ) / count( $scores ) ) : 0;
		}
		update_option( 'aiwc_seo_report', $report );

		return array(
			'processed' => $report['processed'],
			'total'     => $report['total'],
			'finished'  => $report['finished'],
		);
	}

	/**
	 * Site-wide SEO summary from the stored report.
	 *
	 * @return array
	 */
	public function get_site_report() {
		$report = get_option( 'aiwc_seo_report', array() );
		if ( ! is_array( $report ) || empty( $report ) ) {
			return array(
				'available' => false,
				'message'   => 'No site analysis has been run yet. Trigger seo_analyze_site to build the report.',
			);
		}
		$report['available'] = true;
		if ( ! isset( $report['average_score'] ) && ! empty( $report['items'] ) && is_array( $report['items'] ) ) {
			$scores                 = wp_list_pluck( $report['items'], 'score' );
			$report['average_score'] = $scores ? (int) round( array_sum( $scores ) / count( $scores ) ) : 0;
		}
		return $report;
	}

	/**
	 * Issue factory.
	 *
	 * @param string $code     Issue code.
	 * @param string $severity high|medium|low.
	 * @param string $message  Message.
	 * @param string $fix      Suggested fix.
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
