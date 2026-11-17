<?php
/**
 * Core WordPress inspection and light management tools.
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;

defined( 'ABSPATH' ) || exit;

/**
 * Read-mostly tools for understanding and lightly managing the site.
 */
class Core_Tools extends Abstract_Tool_Group {

	/**
	 * Allowed options for update_option_whitelisted.
	 *
	 * @var string[]
	 */
	private static $allowed_options = array(
		'blogname',
		'blogdescription',
		'date_format',
		'time_format',
		'start_of_week',
		'timezone_string',
		'default_comment_status',
		'default_ping_status',
		'posts_per_page',
	);

	/**
	 * Declare tools.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'site_overview',
				'description' => 'Get a structured overview of the site: title, description, counts of pages/posts/users, active theme, active plugins, menus, permalinks and integrations (WooCommerce, Elementor, SEO plugins).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_site_overview',
			),
			array(
				'name'        => 'list_content',
				'description' => 'List pages or posts with pagination. Use this to discover IDs before editing.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'content_type' => array(
							'type'        => 'string',
							'description' => 'Content type: page, post or product.',
							'enum'        => array( 'page', 'post', 'product' ),
						),
						'page'         => array( 'type' => 'integer', 'description' => 'Page number, default 1.' ),
						'per_page'     => array( 'type' => 'integer', 'description' => 'Items per page (max 50), default 10.' ),
						'search'       => array( 'type' => 'string', 'description' => 'Optional search term.' ),
					),
					'required'   => array( 'content_type' ),
				),
				'risk'        => 'read',
				'handler'     => 'handle_list_content',
			),
			array(
				'name'        => 'get_content',
				'description' => 'Get full details of a page/post/product by ID: title, content, excerpt, status, slug, URL, SEO meta.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id' => array( 'type' => 'integer', 'description' => 'The post/page ID.' ),
					),
					'required'   => array( 'post_id' ),
				),
				'risk'        => 'read',
				'handler'     => 'handle_get_content',
			),
			array(
				'name'        => 'search_content',
				'description' => 'Full-text search across pages and posts. Returns matching items with IDs.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'query' => array( 'type' => 'string', 'description' => 'Search query.' ),
						'limit' => array( 'type' => 'integer', 'description' => 'Max results, default 10.' ),
					),
					'required'   => array( 'query' ),
				),
				'risk'        => 'read',
				'handler'     => 'handle_search_content',
			),
			array(
				'name'        => 'users_list',
				'description' => 'List WordPress users (ID, login, name, email, roles). Requires list_users capability.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'limit' => array( 'type' => 'integer', 'description' => 'Max users, default 20.' ),
					),
				),
				'risk'        => 'read',
				'handler'     => 'handle_users_list',
			),
			array(
				'name'        => 'plugins_info',
				'description' => 'List installed plugins with active status, version and author.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_plugins_info',
			),
			array(
				'name'        => 'theme_info',
				'description' => 'Get active theme details: name, version, parent/child, block theme support and available theme supports.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_theme_info',
			),
			array(
				'name'        => 'settings_inspect',
				'description' => 'Inspect general WordPress settings: site title, tagline, timezone, date format, permalink structure, front page, discussion settings.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_settings_inspect',
			),
			array(
				'name'        => 'update_site_option',
				'description' => 'Update a safe general setting: blogname (site title), blogdescription (tagline), date_format, time_format, start_of_week, timezone_string, posts_per_page, default_comment_status, default_ping_status.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'option_name' => array(
							'type'        => 'string',
							'description' => 'Option name.',
							'enum'        => array_values( self::$allowed_options ),
						),
						'option_value' => array( 'type' => 'string', 'description' => 'New value.' ),
					),
					'required'   => array( 'option_name', 'option_value' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_update_site_option',
			),
			array(
				'name'        => 'get_menus',
				'description' => 'List navigation menus with their items (title, URL, type).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_get_menus',
			),
		);
	}

	/**
	 * site_overview
	 *
	 * @return array
	 */
	public function handle_site_overview() {
		$overview = $this->plugin->get( 'context' )->get_overview();
		return $this->success( $overview, 'Site overview collected.' );
	}

	/**
	 * list_content
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_list_content( array $args ) {
		$type = isset( $args['content_type'] ) ? $args['content_type'] : 'page';
		if ( ! in_array( $type, array( 'page', 'post', 'product' ), true ) ) {
			$type = 'page';
		}
		$result = $this->plugin->get( 'context' )->list_content(
			$type,
			isset( $args['page'] ) ? absint( $args['page'] ) : 1,
			isset( $args['per_page'] ) ? absint( $args['per_page'] ) : 10,
			isset( $args['search'] ) ? sanitize_text_field( $args['search'] ) : ''
		);
		return $this->success( $result, sprintf( 'Found %d %s items.', $result['total'], $type ) );
	}

	/**
	 * get_content
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_get_content( array $args ) {
		$post_id = absint( $args['post_id'] );
		$post    = get_post( $post_id );
		if ( ! $post ) {
			return $this->error( sprintf( 'Post %d not found.', $post_id ) );
		}
		$data = array(
			'id'           => (int) $post->ID,
			'type'         => $post->post_type,
			'title'        => $post->post_title,
			'content'      => $post->post_content,
			'excerpt'      => $post->post_excerpt,
			'status'       => $post->post_status,
			'slug'         => $post->post_name,
			'url'          => get_permalink( $post->ID ),
			'modified'     => $post->post_modified,
			'author'       => get_the_author_meta( 'display_name', $post->post_author ),
			'seo_title'    => (string) get_post_meta( $post->ID, '_aiwc_seo_title', true ),
			'seo_desc'     => (string) get_post_meta( $post->ID, '_aiwc_seo_desc', true ),
			'yoast_title'  => (string) get_post_meta( $post->ID, '_yoast_wpseo_title', true ),
			'yoast_desc'   => (string) get_post_meta( $post->ID, '_yoast_wpseo_metadesc', true ),
			'rank_title'   => (string) get_post_meta( $post->ID, 'rank_math_title', true ),
			'rank_desc'    => (string) get_post_meta( $post->ID, 'rank_math_description', true ),
		);
		return $this->success( $data, sprintf( 'Fetched "%s" (#%d).', $post->post_title, $post->ID ) );
	}

	/**
	 * search_content
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_search_content( array $args ) {
		$query = sanitize_text_field( $args['query'] );
		$limit = isset( $args['limit'] ) ? max( 1, min( 50, absint( $args['limit'] ) ) ) : 10;

		$q = new \WP_Query(
			array(
				's'              => $query,
				'post_type'      => array( 'page', 'post' ),
				'post_status'    => 'publish',
				'posts_per_page' => $limit,
			)
		);

		$items = array();
		foreach ( $q->posts as $post ) {
			$items[] = array(
				'id'     => (int) $post->ID,
				'type'   => $post->post_type,
				'title'  => $post->post_title,
				'status' => $post->post_status,
				'url'    => get_permalink( $post->ID ),
			);
		}
		return $this->success(
			array( 'items' => $items, 'total' => (int) $q->found_posts ),
			sprintf( 'Search "%s" matched %d items.', $query, $q->found_posts )
		);
	}

	/**
	 * users_list
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_users_list( array $args ) {
		if ( ! current_user_can( 'list_users' ) ) {
			return $this->error( 'Missing capability: list_users' );
		}
		$limit = isset( $args['limit'] ) ? max( 1, min( 100, absint( $args['limit'] ) ) ) : 20;
		$users = get_users( array( 'number' => $limit, 'fields' => array( 'ID', 'user_login', 'display_name', 'user_email', 'roles' ) ) );
		$items = array();
		foreach ( $users as $user ) {
			$items[] = array(
				'id'    => (int) $user->ID,
				'login' => $user->user_login,
				'name'  => $user->display_name,
				'email' => $user->user_email,
				'roles' => $user->roles,
			);
		}
		return $this->success( array( 'items' => $items ), sprintf( 'Listed %d users.', count( $items ) ) );
	}

	/**
	 * plugins_info
	 *
	 * @return array
	 */
	public function handle_plugins_info() {
		if ( ! function_exists( 'get_plugins' ) ) {
			require_once ABSPATH . 'wp-admin/includes/plugin.php';
		}
		$all    = get_plugins();
		$active = (array) get_option( 'active_plugins', array() );
		$items  = array();
		foreach ( $all as $file => $data ) {
			$items[] = array(
				'file'    => $file,
				'name'    => $data['Name'],
				'version' => $data['Version'],
				'author'  => $data['Author'],
				'active'  => in_array( $file, $active, true ),
			);
		}
		return $this->success( array( 'items' => $items ), sprintf( 'Listed %d plugins.', count( $items ) ) );
	}

	/**
	 * theme_info
	 *
	 * @return array
	 */
	public function handle_theme_info() {
		$theme = wp_get_theme();
		$data  = array(
			'name'        => $theme->get( 'Name' ),
			'version'     => $theme->get( 'Version' ),
			'author'      => $theme->get( 'Author' ),
			'description' => $theme->get( 'Description' ),
			'parent'      => is_child_theme() ? $theme->get( 'Template' ) : '',
			'block_theme' => $theme->is_block_theme(),
			'supports'    => array(
				'title-tag'       => current_theme_supports( 'title-tag' ),
				'post-thumbnails' => current_theme_supports( 'post-thumbnails' ),
				'html5'           => current_theme_supports( 'html5' ),
				'custom-logo'     => current_theme_supports( 'custom-logo' ),
				'editor-styles'   => current_theme_supports( 'editor-styles' ),
			),
		);
		return $this->success( $data, sprintf( 'Active theme: %s', $data['name'] ) );
	}

	/**
	 * settings_inspect
	 *
	 * @return array
	 */
	public function handle_settings_inspect() {
		$data = array(
			'blogname'                 => get_option( 'blogname' ),
			'blogdescription'          => get_option( 'blogdescription' ),
			'timezone_string'          => get_option( 'timezone_string' ),
			'date_format'              => get_option( 'date_format' ),
			'time_format'              => get_option( 'time_format' ),
			'start_of_week'            => get_option( 'start_of_week' ),
			'permalink_structure'      => get_option( 'permalink_structure' ),
			'show_on_front'            => get_option( 'show_on_front' ),
			'page_on_front'            => absint( get_option( 'page_on_front' ) ),
			'page_for_posts'           => absint( get_option( 'page_for_posts' ) ),
			'default_comment_status'   => get_option( 'default_comment_status' ),
			'default_ping_status'      => get_option( 'default_ping_status' ),
			'posts_per_page'           => absint( get_option( 'posts_per_page' ) ),
			'users_can_register'       => get_option( 'users_can_register' ),
			'default_role'             => get_option( 'default_role' ),
			'WPLANG'                   => get_option( 'WPLANG' ),
		);
		return $this->success( $data, 'General settings inspected.' );
	}

	/**
	 * update_site_option
	 *
	 * @param array $args       Args.
	 * @param array $context    Context.
	 * @return array
	 */
	public function handle_update_site_option( array $args, array $context = array() ) {
		$name  = sanitize_key( $args['option_name'] );
		$value = $args['option_value'];

		if ( ! in_array( $name, self::$allowed_options, true ) ) {
			return $this->error( sprintf( 'Option "%s" is not in the safe whitelist.', $name ) );
		}

		$before = array( 'option_name' => $name, 'value' => get_option( $name ) );

		// Type-safe updates.
		if ( in_array( $name, array( 'posts_per_page', 'start_of_week' ), true ) ) {
			$value = absint( $value );
		}
		update_option( $name, $value );

		$after = array( 'option_name' => $name, 'value' => get_option( $name ) );

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'update_site_option',
				'object_type'     => 'option',
				'object_id'       => 0,
				'summary'         => sprintf( 'Updated option %s', $name ),
				'args'            => $args,
				'before_state'    => $before,
				'after_state'     => $after,
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		$this->plugin->get( 'snapshots' )->save( 'option', 0, $before, $after, $log_id );

		return $this->success(
			$after,
			sprintf( 'Option "%s" updated.', $name ),
			array( 'log_id' => $log_id )
		);
	}

	/**
	 * get_menus
	 *
	 * @return array
	 */
	public function handle_get_menus() {
		$structure = $this->plugin->get( 'context' )->get_structure();
		return $this->success( array( 'menus' => $structure['menus'] ), sprintf( 'Found %d menus.', count( $structure['menus'] ) ) );
	}
}
