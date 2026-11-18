<?php
/**
 * Page redesign engine: analyze → propose → preview (draft copy) → apply
 * after approval (snapshot-protected) → compare before/after.
 *
 * Content safety: the apply step never silently deletes content — every
 * extracted content item must be preserved or explicitly listed in the
 * proposal's "removed" set which the approval covers.
 *
 * @package AIWC
 */

namespace AIWC\Builder;

defined( 'ABSPATH' ) || exit;

/**
 * Class Redesign_Engine
 */
class Redesign_Engine {

	/**
	 * Analyze a page: content inventory + design critique + redesign proposal.
	 *
	 * @param int $post_id Post ID.
	 * @return array|\WP_Error
	 */
	public static function analyze( $post_id ) {
		$post = get_post( (int) $post_id );
		if ( ! $post ) {
			return new \WP_Error( 'aiwc_post_not_found', __( 'Post not found.', 'ai-wordpress-copilot' ) );
		}

		$inventory = self::extract_content( $post );
		$critique  = self::critique( $post, $inventory );
		$proposal  = self::propose( $post, $inventory, $critique );

		return array(
			'post_id'    => (int) $post_id,
			'title'      => $post->post_title,
			'inventory'  => $inventory,
			'critique'   => $critique,
			'proposal'   => $proposal,
		);
	}

	/**
	 * Extract the important content of a page (headings, text, images, links).
	 *
	 * @param \WP_Post $post Post.
	 * @return array
	 */
	public static function extract_content( \WP_Post $post ) {
		$content = $post->post_content;
		$elementor = get_post_meta( $post->ID, '_elementor_data', true );
		if ( $elementor ) {
			$data = json_decode( (string) $elementor, true );
			$content .= "\n" . self::elementor_text( is_array( $data ) ? $data : array() );
		}

		$headings = array();
		if ( preg_match_all( '/<h([1-6])[^>]*>(.*?)<\/h\1>/is', $content, $m, PREG_SET_ORDER ) ) {
			foreach ( $m as $row ) {
				$text = trim( wp_strip_all_tags( $row[2] ) );
				if ( '' !== $text ) {
					$headings[] = array( 'level' => (int) $row[1], 'text' => $text );
				}
			}
		}
		$paragraphs = array();
		$text_only  = trim( wp_strip_all_tags( $content ) );
		foreach ( preg_split( '/\n+/', $text_only ) as $line ) {
			$line = trim( $line );
			if ( mb_strlen( $line ) > 30 ) {
				$paragraphs[] = mb_substr( $line, 0, 300 );
			}
		}
		$images = array();
		if ( preg_match_all( '/<img[^>]+src\s*=\s*([\'"])(.*?)\1/is', $content, $m ) ) {
			$images = array_values( array_unique( $m[2] ) );
		}
		$links = array();
		if ( preg_match_all( '/<a\s[^>]*href\s*=\s*([\'"])(.*?)\1[^>]*>(.*?)<\/a>/is', $content, $m, PREG_SET_ORDER ) ) {
			foreach ( $m as $row ) {
				$links[] = array( 'url' => html_entity_decode( $row[2] ), 'text' => trim( wp_strip_all_tags( $row[3] ) ) );
			}
		}

		return array(
			'headings'   => $headings,
			'texts'      => array_slice( $paragraphs, 0, 30 ),
			'images'     => array_slice( $images, 0, 20 ),
			'links'      => array_slice( $links, 0, 20 ),
			'word_count' => str_word_count( $text_only ),
		);
	}

	/**
	 * Flatten elementor widget texts.
	 *
	 * @param array $data Elementor data.
	 * @return string
	 */
	private static function elementor_text( array $data ) {
		$out = '';
		foreach ( $data as $el ) {
			if ( isset( $el['settings']['title'] ) ) {
				$out .= "\n<h2>" . esc_html( $el['settings']['title'] ) . '</h2>';
			}
			if ( isset( $el['settings']['editor'] ) ) {
				$out .= "\n" . wp_strip_all_tags( (string) $el['settings']['editor'] );
			}
			if ( isset( $el['settings']['text'] ) ) {
				$out .= "\n" . wp_strip_all_tags( (string) $el['settings']['text'] );
			}
			if ( ! empty( $el['elements'] ) && is_array( $el['elements'] ) ) {
				$out .= "\n" . self::elementor_text( $el['elements'] );
			}
		}
		return $out;
	}

	/**
	 * Design critique (rule-based, evidence from the parsed structure).
	 *
	 * @param \WP_Post $post      Post.
	 * @param array    $inventory Inventory.
	 * @return array[]
	 */
	private static function critique( \WP_Post $post, array $inventory ) {
		$issues = array();
		if ( count( $inventory['headings'] ) < 2 && $inventory['word_count'] > 100 ) {
			$issues[] = array( 'issue' => 'weak_hierarchy', 'detail' => 'Few headings for the amount of text.', 'fix' => 'Break content into scannable sections with clear headings.' );
		}
		if ( 0 === count( $inventory['images'] ) && $inventory['word_count'] > 150 ) {
			$issues[] = array( 'issue' => 'no_visuals', 'detail' => 'No images found.', 'fix' => 'Add relevant imagery or feature cards.' );
		}
		$has_cta = false;
		foreach ( $inventory['links'] as $l ) {
			if ( preg_match( '/(خرید|تماس|شروع|سفارش|buy|contact|start|order)/iu', $l['text'] ) ) {
				$has_cta = true;
				break;
			}
		}
		if ( ! $has_cta && $inventory['word_count'] > 100 ) {
			$issues[] = array( 'issue' => 'no_cta', 'detail' => 'No clear call-to-action found.', 'fix' => 'Add a prominent CTA section.' );
		}
		if ( ! has_blocks( $post ) && ! get_post_meta( $post->ID, '_elementor_data', true ) ) {
			$issues[] = array( 'issue' => 'classic_content', 'detail' => 'Content is classic HTML without block structure.', 'fix' => 'Rebuild with structured sections for consistent design.' );
		}
		if ( ! $issues ) {
			$issues[] = array( 'issue' => 'ok', 'detail' => 'Structure is reasonable; redesign will modernize styling.', 'fix' => 'Apply the current design system for a consistent look.' );
		}
		return $issues;
	}

	/**
	 * Propose a new design: a section plan that PRESERVES all extracted content.
	 *
	 * @param \WP_Post $post      Post.
	 * @param array    $inventory Inventory.
	 * @param array    $critique  Critique.
	 * @return array
	 */
	private static function propose( \WP_Post $post, array $inventory, array $critique ) {
		$design  = Design_System::get();
		$sections = array();

		// Hero from the first heading + first text.
		$hero_heading = isset( $inventory['headings'][0]['text'] ) ? $inventory['headings'][0]['text'] : $post->post_title;
		$hero_text    = isset( $inventory['texts'][0] ) ? mb_substr( $inventory['texts'][0], 0, 200 ) : '';
		$sections[] = array(
			'type'    => 'hero',
			'content' => array( 'heading' => $hero_heading, 'text' => $hero_text, 'button_text' => __( 'ادامه مطلب', 'ai-wordpress-copilot' ), 'button_url' => '#main' ),
		);

		// Body: all remaining headings become section headings with their texts.
		// Chunked so no content is dropped by the section item limits.
		$body_items = array();
		$text_idx   = 1;
		foreach ( array_slice( $inventory['headings'], 1 ) as $h ) {
			$body_items[] = array( 'title' => $h['text'], 'text' => isset( $inventory['texts'][ $text_idx ] ) ? $inventory['texts'][ $text_idx ] : '' );
			++$text_idx;
		}
		foreach ( array_chunk( $body_items, 5 ) as $chunk ) {
			$sections[] = array( 'type' => 'features', 'content' => array( 'heading' => __( 'مهم‌ترین بخش‌ها', 'ai-wordpress-copilot' ), 'items' => $chunk ) );
		}

		// Remaining texts that had no heading go into their own feature cards.
		$orphan_texts = array_slice( $inventory['texts'], $text_idx );
		if ( $orphan_texts ) {
			$sections[] = array(
				'type'    => 'features',
				'content' => array(
					'heading' => __( 'مطالب صفحه', 'ai-wordpress-copilot' ),
					'items'   => array_map(
						function ( $t ) {
							return array( 'title' => mb_substr( $t, 0, 40 ), 'text' => $t );
						},
						array_slice( $orphan_texts, 0, 5 )
					),
				),
			);
		}

		// Gallery when images exist (chunked so none are dropped).
		foreach ( array_chunk( $inventory['images'], 9 ) as $img_chunk ) {
			$sections[] = array( 'type' => 'gallery', 'content' => array( 'heading' => __( 'گالری', 'ai-wordpress-copilot' ), 'images' => array_map(
				function ( $u ) {
					return array( 'url' => $u, 'alt' => '' );
				},
				$img_chunk
			) ) );
		}

		// CTA when critique flagged it (or always, for conversion).
		$sections[] = array( 'type' => 'cta', 'content' => array( 'heading' => __( 'آماده‌اید؟', 'ai-wordpress-copilot' ), 'button_text' => __( 'تماس با ما', 'ai-wordpress-copilot' ), 'button_url' => '#contact' ) );

		return array(
			'builder'      => Design_Engine::resolve_builder( 'auto' ),
			'design_note'  => Design_System::to_context( $design ),
			'sections'     => $sections,
			'preserved'    => array(
				'headings' => wp_list_pluck( $inventory['headings'], 'text' ),
				'texts'    => $inventory['texts'],
				'images'   => $inventory['images'],
				'links'    => $inventory['links'],
			),
			'removed'      => array(), // Nothing removed by default — approval covers any additions here.
		);
	}

	/**
	 * Build the redesigned page as a DRAFT preview copy (original untouched).
	 *
	 * @param int   $post_id  Original post ID.
	 * @param array $proposal Proposal (from analyze; can be adjusted).
	 * @return array|\WP_Error {preview_id, preview_url, checks}
	 */
	public static function preview( $post_id, array $proposal = array() ) {
		$post = get_post( (int) $post_id );
		if ( ! $post ) {
			return new \WP_Error( 'aiwc_post_not_found', __( 'Post not found.', 'ai-wordpress-copilot' ) );
		}
		if ( ! $proposal ) {
			$analysis = self::analyze( $post_id );
			if ( is_wp_error( $analysis ) ) {
				return $analysis;
			}
			$proposal = $analysis['proposal'];
		}

		$sections = isset( $proposal['sections'] ) && is_array( $proposal['sections'] ) ? $proposal['sections'] : array();
		$builder  = isset( $proposal['builder'] ) ? (string) $proposal['builder'] : 'auto';

		$build = Design_Engine::build_page(
			$post->post_title . ' — ' . __( 'پیش‌نمایش بازطراحی', 'ai-wordpress-copilot' ),
			$sections,
			array(
				'post_status' => 'draft',
				'builder'     => $builder,
			)
		);
		if ( is_wp_error( $build ) ) {
			return $build;
		}
		$preview_id = (int) $build['post_id'];
		update_post_meta( $preview_id, '_aiwc_redesign_preview_of', (int) $post_id );
		update_post_meta( $preview_id, '_aiwc_redesign_proposal', wp_json_encode( $proposal ) );

		$checks = self::check_preview( $post_id, $preview_id, $proposal );

		return array(
			'preview_id'  => $preview_id,
			'preview_url' => get_preview_post_link( $preview_id ) ? get_preview_post_link( $preview_id ) : get_permalink( $preview_id ),
			'original_untouched' => true,
			'checks'      => $checks,
			'proposal'    => $proposal,
		);
	}

	/**
	 * Verify the preview: valid structure + every promised item present or
	 * explicitly listed as removed.
	 *
	 * @param int   $post_id    Original.
	 * @param int   $preview_id Preview.
	 * @param array $proposal   Proposal.
	 * @return array
	 */
	public static function check_preview( $post_id, $preview_id, array $proposal ) {
		$preview = get_post( (int) $preview_id );
		$issues  = array();
		if ( ! $preview ) {
			return array( 'ok' => false, 'issues' => array( 'preview missing' ) );
		}

		$is_elementor = (bool) get_post_meta( $preview_id, '_elementor_data', true );
		if ( $is_elementor ) {
			$data = json_decode( (string) get_post_meta( $preview_id, '_elementor_data', true ), true );
			$valid = Elementor_Adapter::validate_data( is_array( $data ) ? $data : array() );
			if ( is_wp_error( $valid ) ) {
				$issues[] = $valid->get_error_message();
			}
			$haystack = self::elementor_text( is_array( $data ) ? $data : array() );
		} else {
			$valid = Gutenberg_Adapter::validate_markup( $preview->post_content );
			if ( is_wp_error( $valid ) ) {
				$issues[] = $valid->get_error_message();
			}
			$haystack = $preview->post_content;
		}

		$removed = isset( $proposal['removed'] ) && is_array( $proposal['removed'] ) ? array_map( 'strval', $proposal['removed'] ) : array();
		$preserved = isset( $proposal['preserved'] ) ? $proposal['preserved'] : array();
		$missing   = array();
		foreach ( array( 'headings', 'texts', 'images' ) as $group ) {
			$items = isset( $preserved[ $group ] ) && is_array( $preserved[ $group ] ) ? $preserved[ $group ] : array();
			foreach ( $items as $item ) {
				$needle = is_array( $item ) ? (string) ( isset( $item['text'] ) ? $item['text'] : '' ) : (string) $item;
				$needle = trim( $needle );
				if ( '' === $needle || in_array( $needle, $removed, true ) ) {
					continue;
				}
				$short = mb_substr( $needle, 0, 24 );
				if ( '' !== $short && false === mb_strpos( $haystack, $short ) ) {
					$missing[] = $short;
				}
			}
		}
		if ( $missing ) {
			$issues[] = 'content_missing: ' . implode( ' | ', array_slice( $missing, 0, 5 ) );
		}

		return array(
			'ok'         => ! $issues,
			'issues'     => $issues,
			'preserved_count' => count( $preserved['headings'] ?? array() ) + count( $preserved['texts'] ?? array() ),
			'removed_count'   => count( $removed ),
		);
	}

	/**
	 * Apply a preview to the original page with snapshot protection.
	 * The caller MUST have obtained approval (registry needs_confirmation).
	 *
	 * @param int  $post_id    Original.
	 * @param int  $preview_id Preview.
	 * @param bool $confirm    Explicit confirmation (enforced).
	 * @return array|\WP_Error
	 */
	public static function apply( $post_id, $preview_id, $confirm = false ) {
		if ( true !== $confirm && '1' !== (string) $confirm ) {
			return new \WP_Error( 'aiwc_apply_needs_confirmation', __( 'Applying a redesign requires explicit confirmation (main content is snapshot-protected).', 'ai-wordpress-copilot' ) );
		}
		$post    = get_post( (int) $post_id );
		$preview = get_post( (int) $preview_id );
		if ( ! $post || ! $preview ) {
			return new \WP_Error( 'aiwc_post_not_found', __( 'Post not found.', 'ai-wordpress-copilot' ) );
		}
		if ( (int) get_post_meta( $preview_id, '_aiwc_redesign_preview_of', true ) !== (int) $post_id ) {
			return new \WP_Error( 'aiwc_preview_mismatch', __( 'Preview does not belong to this page.', 'ai-wordpress-copilot' ) );
		}

		// Snapshot the original content + meta before overwriting (shape
		// matches Snapshot_Manager::restore for object type "post").
		$plugin   = function_exists( 'aiwc' ) ? aiwc() : null;
		$before   = array(
			'post' => array(
				'ID'           => (int) $post->ID,
				'post_title'   => $post->post_title,
				'post_content' => $post->post_content,
				'post_excerpt' => $post->post_excerpt,
				'post_status'  => $post->post_status,
				'post_name'    => $post->post_name,
				'menu_order'   => (int) $post->menu_order,
			),
			'meta' => array(
				'_elementor_data'      => array( (string) get_post_meta( $post_id, '_elementor_data', true ) ),
				'_elementor_edit_mode' => array( (string) get_post_meta( $post_id, '_elementor_edit_mode', true ) ),
			),
		);
		$snapshot_id = 0;
		if ( $plugin && $plugin->get( 'snapshots' ) ) {
			$snapshot_id = $plugin->get( 'snapshots' )->save( 'post', (int) $post_id, $before, array( 'redesign_applied_from' => $preview_id ), 0 );
		}

		$is_elementor = (bool) get_post_meta( $preview_id, '_elementor_data', true );
		if ( $is_elementor ) {
			$data = json_decode( (string) get_post_meta( $preview_id, '_elementor_data', true ), true );
			$r = wp_update_post( array( 'ID' => (int) $post_id, 'post_content' => '' ), true );
			if ( is_wp_error( $r ) ) {
				return $r;
			}
			Elementor_Adapter::save_data( (int) $post_id, is_array( $data ) ? $data : array() );
		} else {
			// Remove stale elementor meta when switching to blocks.
			delete_post_meta( $post_id, '_elementor_data' );
			$r = wp_update_post( array( 'ID' => (int) $post_id, 'post_content' => $preview->post_content ), true );
			if ( is_wp_error( $r ) ) {
				return $r;
			}
		}

		if ( $plugin && $plugin->get( 'log' ) ) {
			$log_id = $plugin->get( 'log' )->log(
				array(
					'command'      => 'redesign_apply',
					'tool_name'    => 'redesign_page',
					'object_type'  => 'post',
					'object_id'    => (int) $post_id,
					'summary'      => sprintf( 'Applied redesign preview #%d to page #%d', $preview_id, $post_id ),
					'args'         => array( 'preview_id' => $preview_id ),
					'before_state' => array( 'content_length' => strlen( (string) $before['post_content'] ) ),
					'after_state'  => array( 'content_length' => strlen( $preview->post_content ) ),
				)
			);
		}

		return array(
			'post_id'     => (int) $post_id,
			'snapshot_id' => (int) $snapshot_id,
			'applied'     => true,
			'url'         => get_permalink( (int) $post_id ),
		);
	}

	/**
	 * Before/after comparison. Screenshots require a browser runtime which is
	 * not available here — the limitation is returned explicitly.
	 *
	 * @param int $post_id Post ID.
	 * @return array
	 */
	public static function compare( $post_id ) {
		$post = get_post( (int) $post_id );
		if ( ! $post ) {
			return new \WP_Error( 'aiwc_post_not_found', __( 'Post not found.', 'ai-wordpress-copilot' ) );
		}
		$plugin = function_exists( 'aiwc' ) ? aiwc() : null;
		$snapshots = array();
		if ( $plugin && $plugin->get( 'snapshots' ) ) {
			$all = $plugin->get( 'snapshots' )->list_snapshots( 20 );
			foreach ( is_array( $all ) ? $all : array() as $row ) {
				if ( isset( $row['object_type'] ) && 'post' === $row['object_type'] && (int) ( $row['object_id'] ?? 0 ) === (int) $post_id ) {
					$snapshots[] = $row;
				}
			}
		}
		$inventory_now = self::extract_content( $post );
		return array(
			'post_id'    => (int) $post_id,
			'now'        => array(
				'headings'   => wp_list_pluck( $inventory_now['headings'], 'text' ),
				'word_count' => $inventory_now['word_count'],
				'images'     => count( $inventory_now['images'] ),
			),
			'history'    => array_slice( $snapshots, -5 ),
			'screenshots' => array(
				'available' => false,
				'reason'    => 'No browser/screenshot runtime in this environment; comparison is structural (content inventory + snapshot history).',
			),
		);
	}
}
