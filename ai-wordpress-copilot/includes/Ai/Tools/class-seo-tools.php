<?php
/**
 * SEO tools for the AI agent.
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;

defined( 'ABSPATH' ) || exit;

/**
 * SEO analysis and optimization tools.
 */
class Seo_Tools extends Abstract_Tool_Group {

	/**
	 * Declare tools.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'seo_analyze',
				'description' => 'Run a full SEO analysis of one page or post: SEO title, meta description, headings, images alt, internal/external links, broken links, keyword usage, slug, schema and duplicate content. Returns a 0-100 score with issues and fixes.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id' => array( 'type' => 'integer', 'description' => 'Page/post ID.' ),
						'keyword' => array( 'type' => 'string', 'description' => 'Optional focus keyword override.' ),
					),
					'required'   => array( 'post_id' ),
				),
				'risk'        => 'read',
				'handler'     => 'handle_seo_analyze',
			),
			array(
				'name'        => 'seo_update_meta',
				'description' => 'Update SEO title, meta description and focus keyword of a page/post. Integrates with Yoast SEO and Rank Math when active (writes their meta fields) and always keeps AIWC meta as fallback.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id' => array( 'type' => 'integer', 'description' => 'Page/post ID.' ),
						'title'   => array( 'type' => 'string', 'description' => 'SEO title (30-60 chars recommended).' ),
						'description' => array( 'type' => 'string', 'description' => 'Meta description (70-160 chars recommended).' ),
						'keyword' => array( 'type' => 'string', 'description' => 'Focus keyword.' ),
					),
					'required'   => array( 'post_id' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_seo_update_meta',
			),
			array(
				'name'        => 'seo_analyze_site',
				'description' => 'Start a staged site-wide SEO analysis (queued, processes in batches). Returns a job id; results accumulate in the site SEO report.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'batch_size' => array( 'type' => 'integer', 'description' => 'Posts per batch, default 10.' ),
					),
				),
				'risk'        => 'write',
				'handler'     => 'handle_seo_analyze_site',
			),
			array(
				'name'        => 'seo_get_site_report',
				'description' => 'Get the accumulated site-wide SEO report: average score, per-page scores and top issues.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_seo_get_site_report',
			),
			array(
				'name'        => 'seo_suggest_improvements',
				'description' => 'Analyze a page and return concrete rewrite suggestions: optimized SEO title, meta description, heading structure and internal link ideas, based on the current content and focus keyword.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id' => array( 'type' => 'integer', 'description' => 'Page/post ID.' ),
						'keyword' => array( 'type' => 'string', 'description' => 'Target keyword.' ),
					),
					'required'   => array( 'post_id' ),
				),
				'risk'        => 'read',
				'handler'     => 'handle_seo_suggest',
			),
		);
	}

	/**
	 * seo_analyze
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_seo_analyze( array $args ) {
		$extra = array();
		if ( ! empty( $args['keyword'] ) ) {
			$extra['keyword'] = sanitize_text_field( $args['keyword'] );
		}
		$result = $this->plugin->get( 'seo' )->analyze_post( absint( $args['post_id'] ), $extra );
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_message() );
		}
		return $this->success( $result, sprintf( 'SEO score %d/100 with %d issue(s).', $result['score'], $result['issue_count'] ) );
	}

	/**
	 * seo_update_meta
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_seo_update_meta( array $args, array $context = array() ) {
		$post_id = absint( $args['post_id'] );
		if ( ! get_post( $post_id ) ) {
			return $this->error( sprintf( 'Post %d not found.', $post_id ) );
		}

		$state = $this->begin_mutation( $post_id, 'seo_update_meta', $args, $context );

		$saved = $this->plugin->get( 'seo' )->save_seo_meta(
			$post_id,
			isset( $args['title'] ) ? $args['title'] : null,
			isset( $args['description'] ) ? $args['description'] : null,
			isset( $args['keyword'] ) ? $args['keyword'] : null
		);

		return $this->end_mutation(
			$state,
			'post',
			$post_id,
			$this->success( $saved, sprintf( 'SEO meta of #%d updated (source: %s).', $post_id, $saved['source'] ) )
		);
	}

	/**
	 * seo_analyze_site
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_seo_analyze_site( array $args ) {
		$batch = isset( $args['batch_size'] ) ? max( 1, min( 25, absint( $args['batch_size'] ) ) ) : 10;
		$job_id = $this->plugin->get( 'queue' )->push(
			'seo_site_analysis',
			array(
				'batch_size' => $batch,
				'offset'     => 0,
			)
		);
		return $this->success(
			array( 'job_id' => $job_id, 'batch_size' => $batch ),
			sprintf( 'Site-wide SEO analysis queued as job #%d.', $job_id )
		);
	}

	/**
	 * seo_get_site_report
	 *
	 * @return array
	 */
	public function handle_seo_get_site_report() {
		$report = $this->plugin->get( 'seo' )->get_site_report();
		return $this->success( $report, ! empty( $report['available'] ) ? 'Site SEO report loaded.' : 'No site report yet.' );
	}

	/**
	 * seo_suggest_improvements
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_seo_suggest( array $args ) {
		$post_id = absint( $args['post_id'] );
		$analysis = $this->plugin->get( 'seo' )->analyze_post(
			$post_id,
			! empty( $args['keyword'] ) ? array( 'keyword' => sanitize_text_field( $args['keyword'] ) ) : array()
		);
		if ( is_wp_error( $analysis ) ) {
			return $this->error( $analysis->get_error_message() );
		}

		$post    = get_post( $post_id );
		$keyword = $analysis['seo_meta']['keyword'];
		$suggestions = array();

		// Suggest an optimized title.
		$suggested_title = $keyword
			? sprintf( '%s | %s', ucwords( $keyword ), get_bloginfo( 'name' ) )
			: $post->post_title . ' | ' . get_bloginfo( 'name' );
		$suggestions['suggested_seo_title'] = mb_substr( $suggested_title, 0, 60 );

		// Suggest meta description from the opening paragraph.
		$plain = wp_strip_all_tags( $post->post_content );
		$desc  = trim( mb_substr( $plain, 0, 150 ) );
		if ( $keyword && false === mb_strpos( mb_strtolower( $desc ), mb_strtolower( $keyword ) ) ) {
			$desc = $keyword . ': ' . $desc;
		}
		$suggestions['suggested_meta_description'] = mb_substr( $desc, 0, 158 );

		// Heading suggestions.
		$heading_suggestions = array();
		if ( $keyword ) {
			$heading_suggestions[] = sprintf( 'Add an H2 containing "%s" (e.g. "Why %s matters").', $keyword, $keyword );
		}
		$heading_suggestions[] = 'Break long text into H2/H3 sections of 150-300 words.';
		$suggestions['heading_ideas'] = $heading_suggestions;

		// Internal link ideas: top related posts by title keyword overlap.
		$ideas = array();
		$related = get_posts(
			array(
				'post_type'      => array( 'post', 'page' ),
				'post_status'    => 'publish',
				'posts_per_page' => 5,
				'exclude'        => array( $post_id ),
				's'              => $keyword ? $keyword : $post->post_title,
			)
		);
		foreach ( $related as $rel ) {
			$ideas[] = array(
				'post_id' => (int) $rel->ID,
				'title'   => $rel->post_title,
				'url'     => get_permalink( $rel->ID ),
			);
		}
		$suggestions['internal_link_ideas'] = $ideas;

		return $this->success(
			array(
				'post_id'     => $post_id,
				'analysis'    => array(
					'score'  => $analysis['score'],
					'issues' => $analysis['issues'],
				),
				'suggestions' => $suggestions,
			),
			sprintf( 'Prepared SEO improvement suggestions for #%d (score %d).', $post_id, $analysis['score'] )
		);
	}
}
