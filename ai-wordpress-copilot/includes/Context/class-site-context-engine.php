<?php
/**
 * Site Context Engine: bounded, cached knowledge about the site.
 *
 * @package AIWC
 */

namespace AIWC\Context;

defined( 'ABSPATH' ) || exit;

/**
 * Collects site information in a controlled, paginated way.
 */
class Site_Context_Engine {

	const CACHE_KEY  = 'aiwc_site_context';
	const CACHE_TTL  = 300; // 5 minutes.

	/**
	 * Invalidate the cached context.
	 */
	public function invalidate() {
		delete_transient( self::CACHE_KEY );
		delete_transient( self::CACHE_KEY . '_structure' );
	}

	/**
	 * Overview counts and basics (cached).
	 *
	 * @return array
	 */
	public function get_overview() {
		$cached = get_transient( self::CACHE_KEY );
		if ( is_array( $cached ) ) {
			return $cached;
		}

		$theme      = wp_get_theme();
		$active     = get_option( 'active_plugins', array() );
		$menus      = wp_get_nav_menus();
		$menu_names = array();
		foreach ( $menus as $menu ) {
			$menu_names[] = $menu->name;
		}

		$overview = array(
			'site'            => array(
				'title'       => get_bloginfo( 'name' ),
				'description' => get_bloginfo( 'description' ),
				'url'         => home_url(),
				'wp_version'  => get_bloginfo( 'version' ),
				'language'    => get_bloginfo( 'language' ),
				'charset'     => get_bloginfo( 'charset' ),
			),
			'counts'          => array(
				'pages'    => (int) wp_count_posts( 'page' )->publish,
				'posts'    => (int) wp_count_posts( 'post' )->publish,
				'comments' => (int) wp_count_comments()->approved,
				'users'    => (int) count_users()['total_users'],
				'menus'    => count( $menus ),
				'categories' => (int) wp_count_terms( array( 'taxonomy' => 'category', 'hide_empty' => false ) ),
				'tags'       => (int) wp_count_terms( array( 'taxonomy' => 'post_tag', 'hide_empty' => false ) ),
				'images'   => (int) wp_count_posts( 'attachment' )->inherit,
			),
			'theme'           => array(
				'name'    => $theme->get( 'Name' ),
				'version' => $theme->get( 'Version' ),
				'author'  => $theme->get( 'Author' ),
				'block_theme' => $theme->is_block_theme(),
			),
			'plugins_active'  => array_values( array_map( 'basename', (array) $active ) ),
			'menus'           => $menu_names,
			'permalink'       => get_option( 'permalink_structure' ),
			'homepage'        => get_option( 'show_on_front' ),
			'page_on_front'   => absint( get_option( 'page_on_front' ) ),
			'page_for_posts'  => absint( get_option( 'page_for_posts' ) ),
			'woocommerce'     => class_exists( 'WooCommerce' ),
			'elementor'       => defined( 'ELEMENTOR_VERSION' ),
			'yoast'           => defined( 'WPSEO_VERSION' ),
			'rank_math'       => defined( 'RANK_MATH_VERSION' ),
			'generated_at'    => current_time( 'mysql' ),
		);

		set_transient( self::CACHE_KEY, $overview, self::CACHE_TTL );
		return $overview;
	}

	/**
	 * Paginated content listing.
	 *
	 * @param string $type   post_type.
	 * @param int    $page   Page number.
	 * @param int    $per    Per page.
	 * @param string $search Search term.
	 * @return array{items: array, total: int, pages: int}
	 */
	public function list_content( $type = 'page', $page = 1, $per = 10, $search = '' ) {
		$type = in_array( $type, array( 'page', 'post', 'product', 'attachment' ), true ) ? $type : 'page';
		$args = array(
			'post_type'      => $type,
			'post_status'    => 'publish',
			'posts_per_page' => max( 1, min( 50, absint( $per ) ) ),
			'paged'          => max( 1, absint( $page ) ),
			'orderby'        => 'modified',
			'order'          => 'DESC',
			'fields'         => 'ids',
		);
		if ( $search ) {
			$args['s'] = sanitize_text_field( $search );
		}

		$query = new \WP_Query( $args );
		$items = array();
		foreach ( $query->posts as $post_id ) {
			$items[] = $this->summarize_post( $post_id );
		}

		return array(
			'items' => $items,
			'total' => (int) $query->found_posts,
			'pages' => (int) $query->max_num_pages,
		);
	}

	/**
	 * Compact summary of a post.
	 *
	 * @param int $post_id Post id.
	 * @return array|null
	 */
	public function summarize_post( $post_id ) {
		$post = get_post( absint( $post_id ) );
		if ( ! $post ) {
			return null;
		}
		$content = wp_strip_all_tags( $post->post_content );
		return array(
			'id'          => (int) $post->ID,
			'type'        => $post->post_type,
			'title'       => $post->post_title,
			'status'      => $post->post_status,
			'slug'        => $post->post_name,
			'url'         => get_permalink( $post->ID ),
			'excerpt'     => mb_substr( $content, 0, 180 ),
			'word_count'  => str_word_count( $content ),
			'modified'    => $post->post_modified,
		);
	}

	/**
	 * Site structure: menus with items, categories, front pages.
	 *
	 * @return array
	 */
	public function get_structure() {
		$cached = get_transient( self::CACHE_KEY . '_structure' );
		if ( is_array( $cached ) ) {
			return $cached;
		}

		$menus_out = array();
		foreach ( wp_get_nav_menus() as $menu ) {
			$items = wp_get_nav_menu_items( $menu->term_id );
			$flat  = array();
			if ( $items ) {
				foreach ( $items as $item ) {
					$flat[] = array(
						'title' => $item->title,
						'url'   => $item->url,
						'type'  => $item->object,
					);
				}
			}
			$menus_out[] = array(
				'id'    => (int) $menu->term_id,
				'name'  => $menu->name,
				'items' => $flat,
			);
		}

		$categories = array();
		foreach ( get_categories( array( 'hide_empty' => false, 'number' => 30 ) ) as $cat ) {
			$categories[] = array(
				'name'  => $cat->name,
				'slug'  => $cat->slug,
				'count' => (int) $cat->count,
			);
		}

		$structure = array(
			'menus'       => $menus_out,
			'categories'  => $categories,
			'templates'   => $this->list_templates(),
			'front_page'  => $this->summarize_post( absint( get_option( 'page_on_front' ) ) ),
			'posts_page'  => $this->summarize_post( absint( get_option( 'page_for_posts' ) ) ),
		);

		set_transient( self::CACHE_KEY . '_structure', $structure, self::CACHE_TTL );
		return $structure;
	}

	/**
	 * List block templates / template parts when available.
	 *
	 * @return array
	 */
	private function list_templates() {
		$templates = array();
		if ( ! current_theme_supports( 'block-templates' ) && ! wp_is_block_theme() ) {
			return $templates;
		}
		$query = new \WP_Query(
			array(
				'post_type'      => array( 'wp_template', 'wp_template_part' ),
				'post_status'    => 'publish',
				'posts_per_page' => 30,
				'fields'         => 'ids',
			)
		);
		foreach ( $query->posts as $post_id ) {
			$post        = get_post( $post_id );
			$templates[] = array(
				'id'    => (int) $post_id,
				'type'  => $post->post_type,
				'title' => $post->post_title,
				'slug'  => $post->post_name,
			);
		}
		return $templates;
	}

	/**
	 * Compact prompt block describing the site for the AI system prompt.
	 *
	 * @param int $detail 1..5 detail level.
	 * @return string
	 */
	public function prompt_block( $detail = 3 ) {
		$overview = $this->get_overview();
		$lines    = array();
		$lines[]  = 'SITE CONTEXT:';
		$lines[]  = sprintf( '- Site: %s (%s) — %s', $overview['site']['title'], $overview['site']['url'], $overview['site']['description'] );
		$lines[]  = sprintf( '- WordPress %s, theme "%s"%s', $overview['site']['wp_version'], $overview['theme']['name'], $overview['theme']['block_theme'] ? ' (block theme)' : ' (classic theme)' );
		$lines[]  = sprintf( '- Content: %d pages, %d posts, %d categories, %d menus, %d users', $overview['counts']['pages'], $overview['counts']['posts'], $overview['counts']['categories'], $overview['counts']['menus'], $overview['counts']['users'] );
		$lines[]  = '- Active integrations: ' . ( $overview['woocommerce'] ? 'WooCommerce, ' : '' ) . ( $overview['elementor'] ? 'Elementor, ' : '' ) . ( $overview['yoast'] ? 'Yoast SEO, ' : '' ) . ( $overview['rank_math'] ? 'Rank Math, ' : '' ) . 'none';

		if ( $detail >= 3 ) {
			$structure = $this->get_structure();
			if ( ! empty( $structure['menus'] ) ) {
				$names = array();
				foreach ( $structure['menus'] as $menu ) {
					$names[] = $menu['name'] . '(' . count( $menu['items'] ) . ' items)';
				}
				$lines[] = '- Menus: ' . implode( ', ', $names );
			}
			if ( $overview['page_on_front'] ) {
				$front = $this->summarize_post( $overview['page_on_front'] );
				if ( $front ) {
					$lines[] = sprintf( '- Front page: #%d "%s"', $front['id'], $front['title'] );
				}
			}
		}

		if ( $detail >= 4 ) {
			$pages = $this->list_content( 'page', 1, 10 );
			foreach ( $pages['items'] as $item ) {
				$lines[] = sprintf( '  - Page #%d "%s" (%s)', $item['id'], $item['title'], $item['status'] );
			}
			$posts = $this->list_content( 'post', 1, 5 );
			foreach ( $posts['items'] as $item ) {
				$lines[] = sprintf( '  - Post #%d "%s"', $item['id'], $item['title'] );
			}
		}

		return implode( "\n", $lines );
	}

	/**
	 * Full context payload for REST responses.
	 *
	 * @return array
	 */
	public function get_full_context() {
		return array(
			'overview'  => $this->get_overview(),
			'structure' => $this->get_structure(),
		);
	}
}
