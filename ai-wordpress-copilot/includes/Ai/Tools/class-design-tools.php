<?php
/**
 * Site design tools: sections, header/footer, CSS, templates, menus, Elementor.
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;

defined( 'ABSPATH' ) || exit;

/**
 * Design-related tools working with block themes, widgets, custom CSS and menus.
 */
class Design_Tools extends Abstract_Tool_Group {

	/**
	 * Declare tools.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'create_design_section',
				'description' => 'Create a reusable design section (Gutenberg block pattern / reusable block) with HTML content, e.g. hero, features, CTA, contact. Store it as a reusable block and optionally append it to a page.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'title'        => array( 'type' => 'string', 'description' => 'Section title (used as pattern/reusable block name).' ),
						'content'      => array( 'type' => 'string', 'description' => 'Section HTML or Gutenberg block markup.' ),
						'append_to_id' => array( 'type' => 'integer', 'description' => 'Optional page/post ID to append this section to.' ),
					),
					'required'   => array( 'title', 'content' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_create_design_section',
			),
			array(
				'name'        => 'update_header_footer',
				'description' => 'Update the site header or footer. On block themes this edits the corresponding template part. On classic themes it updates the Custom HTML widget in the first sidebar. Provide full replacement HTML with navigation.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'area'    => array( 'type' => 'string', 'description' => 'header or footer.', 'enum' => array( 'header', 'footer' ) ),
						'content' => array( 'type' => 'string', 'description' => 'Replacement HTML/blocks.' ),
					),
					'required'   => array( 'area', 'content' ),
				),
				'risk'        => 'write',
				'needs_confirmation' => true,
				'handler'     => 'handle_update_header_footer',
			),
			array(
				'name'        => 'update_custom_css',
				'description' => 'Update the site-wide custom CSS (Customizer additional CSS). Use for colors, fonts and spacing changes, e.g. button colors.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'css'   => array( 'type' => 'string', 'description' => 'Full replacement CSS, or rules to add when mode=append.' ),
						'mode'  => array( 'type' => 'string', 'description' => 'replace (default) or append.', 'enum' => array( 'replace', 'append' ) ),
					),
					'required'   => array( 'css' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_update_custom_css',
			),
			array(
				'name'        => 'get_custom_css',
				'description' => 'Get the current site-wide custom CSS.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_get_custom_css',
			),
			array(
				'name'        => 'create_menu',
				'description' => 'Create a navigation menu with items (title + URL) and optionally assign it to a theme location.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'menu_name' => array( 'type' => 'string', 'description' => 'Menu name.' ),
						'items'     => array(
							'type'        => 'array',
							'description' => 'Menu items: array of {title, url}. URL can be a site-relative path like /contact/.',
						),
						'location'  => array( 'type' => 'string', 'description' => 'Optional theme location slug to assign.' ),
					),
					'required'   => array( 'menu_name', 'items' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_create_menu',
			),
			array(
				'name'        => 'add_menu_item',
				'description' => 'Add an item to an existing navigation menu.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'menu_id'   => array( 'type' => 'integer', 'description' => 'Menu term ID (use get_menus to find it).' ),
						'title'     => array( 'type' => 'string', 'description' => 'Item title.' ),
						'url'       => array( 'type' => 'string', 'description' => 'Item URL.' ),
					),
					'required'   => array( 'menu_id', 'title', 'url' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_add_menu_item',
			),
			array(
				'name'        => 'create_elementor_section',
				'description' => 'Create a page with Elementor structure (when Elementor is active): sections, columns and widgets from a structured JSON description.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'title'   => array( 'type' => 'string', 'description' => 'Page title.' ),
						'status'  => array( 'type' => 'string', 'description' => 'publish or draft. Default draft.', 'enum' => array( 'publish', 'draft' ) ),
						'sections' => array(
							'type'        => 'array',
							'description' => 'Array of sections: {columns: [{width, widgets: [{type: heading|text|button|image|divider|spacer, settings: {...}}]}]}.',
						),
					),
					'required'   => array( 'title', 'sections' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_create_elementor_section',
			),
			array(
				'name'        => 'get_design_settings',
				'description' => 'Read current design-related settings: custom CSS, global styles presence, theme supports, custom logo, colors from theme.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_get_design_settings',
			),
		);
	}

	/**
	 * create_design_section
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_create_design_section( array $args, array $context = array() ) {
		$title   = sanitize_text_field( $args['title'] );
		$content = wp_kses_post( $args['content'] );

		// Store as a reusable block (wp_block) — usable in the block editor.
		$block_id = wp_insert_post(
			array(
				'post_title'   => $title,
				'post_content' => $content,
				'post_status'  => 'publish',
				'post_type'    => 'wp_block',
				'post_author'  => get_current_user_id(),
			),
			true
		);
		if ( is_wp_error( $block_id ) ) {
			return $this->error( $block_id->get_error_message() );
		}

		$appended_to = 0;
		if ( ! empty( $args['append_to_id'] ) ) {
			$target = get_post( absint( $args['append_to_id'] ) );
			if ( $target ) {
				$state   = $this->begin_mutation( $target->ID, 'create_design_section.append', $args, $context );
				$updated = wp_update_post(
					array(
						'ID'           => $target->ID,
						'post_content' => $target->post_content . "\n\n" . $content,
					),
					true
				);
				if ( ! is_wp_error( $updated ) ) {
					$this->end_mutation(
						$state,
						'post',
						$target->ID,
						$this->success( array( 'post_id' => $target->ID ), 'Section appended to page.' )
					);
					$appended_to = (int) $target->ID;
				}
			}
		}

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'create_design_section',
				'object_type'     => 'post',
				'object_id'       => $block_id,
				'summary'         => sprintf( 'Created design section "%s" (#%d)', $title, $block_id ),
				'args'            => $args,
				'after_state'     => $this->plugin->get( 'snapshots' )->capture( 'post', $block_id ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array(
				'block_id'   => (int) $block_id,
				'appended_to' => $appended_to,
			),
			sprintf( 'Design section "%s" created (#%d)%s.', $title, $block_id, $appended_to ? " and appended to #$appended_to" : '' ),
			array( 'log_id' => $log_id, 'object_type' => 'post', 'object_id' => $block_id )
		);
	}

	/**
	 * update_header_footer
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_update_header_footer( array $args, array $context = array() ) {
		$area    = in_array( $args['area'], array( 'header', 'footer' ), true ) ? $args['area'] : 'header';
		$content = wp_kses_post( $args['content'] );
		$theme   = wp_get_theme();

		if ( $theme->is_block_theme() ) {
			return $this->update_template_part( $area, $content, $args, $context );
		}

		// Classic theme: use a Custom HTML widget in the first sidebar.
		$sidebars = wp_get_sidebars_widgets();
		$sidebar_id = '';
		foreach ( $sidebars as $id => $widgets ) {
			if ( in_array( $id, array( 'wp_inactive_widgets', 'array' ), true ) || ! is_array( $widgets ) ) {
				continue;
			}
			$sidebar_id = $id;
			break;
		}
		if ( '' === $sidebar_id ) {
			return $this->error( 'Classic theme has no widget area; header/footer update is not supported for this theme.' );
		}

		$widget_id = 'aiwc-' . $area . '-' . substr( md5( $sidebar_id ), 0, 6 );
		$state     = array( 'before' => array( 'option_name' => 'widget_custom_html', 'value' => get_option( 'widget_custom_html' ) ) );

		$widgets = get_option( 'widget_custom_html', array() );
		if ( ! is_array( $widgets ) ) {
			$widgets = array();
		}
		$number = 2;
		foreach ( array_keys( $widgets ) as $key ) {
			if ( is_int( $key ) && $key >= $number ) {
				$number = $key + 1;
			}
		}
		$widgets[ $number ] = array(
			'title'   => 'AIWC ' . $area,
			'content' => $content,
		);
		update_option( 'widget_custom_html', $widgets );

		$sidebars[ $sidebar_id ][] = 'custom_html-' . $number;
		wp_set_sidebars_widgets( $sidebars );

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'update_header_footer',
				'object_type'     => 'option',
				'object_id'       => 0,
				'summary'         => sprintf( 'Updated %s widget (classic theme)', $area ),
				'args'            => $args,
				'before_state'    => $state['before'],
				'after_state'     => array( 'option_name' => 'widget_custom_html', 'value' => get_option( 'widget_custom_html' ) ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array( 'mode' => 'widget', 'sidebar' => $sidebar_id, 'widget' => 'custom_html-' . $number ),
			sprintf( 'A %s HTML widget was added to sidebar "%s". Note: classic themes render header/footer from theme files; the widget provides custom content.', $area, $sidebar_id ),
			array( 'log_id' => $log_id )
		);
	}

	/**
	 * Update a block-theme template part.
	 *
	 * @param string $area    header|footer.
	 * @param string $content Replacement content.
	 * @param array  $args    Tool args.
	 * @param array  $context Context.
	 * @return array
	 */
	private function update_template_part( $area, $content, array $args, array $context ) {
		$slug = 'aiwc-' . $area;

		$existing = get_page_by_path( $slug, OBJECT, 'wp_template_part' );
		if ( $existing ) {
			$state = $this->begin_mutation( $existing->ID, 'update_header_footer', $args, $context );
			$res   = wp_update_post(
				array(
					'ID'           => $existing->ID,
					'post_content' => $content,
				),
				true
			);
			if ( is_wp_error( $res ) ) {
				return $this->end_mutation( $state, 'post', $existing->ID, $this->error( $res->get_error_message() ) );
			}
			$part_id = $existing->ID;
		} else {
			$part_id = wp_insert_post(
				array(
					'post_title'   => 'AIWC ' . $area,
					'post_name'    => $slug,
					'post_content' => $content,
					'post_status'  => 'publish',
					'post_type'    => 'wp_template_part',
				),
				true
			);
			if ( is_wp_error( $part_id ) ) {
				return $this->error( $part_id->get_error_message() );
			}
			$state = array( 'before' => null, 'log_id' => 0 );
			update_post_meta( $part_id, 'wp_template_part_area', $area );
		}

		$result = $this->success(
			array( 'mode' => 'template_part', 'part_id' => (int) $part_id, 'area' => $area ),
			sprintf( 'Template part "%s" updated (#%d).', $area, $part_id )
		);

		if ( ! empty( $state['log_id'] ) ) {
			return $this->end_mutation( $state, 'post', $part_id, $result );
		}

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'update_header_footer',
				'object_type'     => 'post',
				'object_id'       => $part_id,
				'summary'         => sprintf( 'Created %s template part (#%d)', $area, $part_id ),
				'args'            => $args,
				'after_state'     => $this->plugin->get( 'snapshots' )->capture( 'post', $part_id ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);
		$result['log_id'] = $log_id;
		return $result;
	}

	/**
	 * update_custom_css
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_update_custom_css( array $args, array $context = array() ) {
		$css  = (string) $args['css'];
		$mode = isset( $args['mode'] ) ? $args['mode'] : 'replace';

		$current_theme = wp_get_theme();
		$previous      = wp_get_custom_css( $current_theme->get_stylesheet() );
		$new           = 'append' === $mode ? trim( $previous . "\n\n" . $css ) : $css;

		// Basic CSS sanitation: no expression/import/behavior tricks.
		if ( preg_match( '/(expression\s*\(|@import|javascript:|behavior\s*:|<\s*\/?\s*script)/i', $new ) ) {
			return $this->error( 'CSS contains disallowed constructs (expression, @import, javascript:, behavior or script tags).' );
		}

		$result = wp_update_custom_css_post( $new );
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_message() );
		}

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'update_custom_css',
				'object_type'     => 'custom_css',
				'object_id'       => 0,
				'summary'         => sprintf( 'Custom CSS updated (%s, %d chars)', $mode, strlen( $new ) ),
				'args'            => array( 'mode' => $mode, 'length' => strlen( $new ) ),
				'before_state'    => array( 'css' => $previous ),
				'after_state'     => array( 'css' => $new ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		// Snapshot so CSS can be rolled back.
		$this->plugin->get( 'snapshots' )->save(
			'custom_css',
			0,
			array( 'css' => $previous ),
			array( 'css' => $new ),
			$log_id
		);

		return $this->success(
			array( 'css_length' => strlen( $new ) ),
			sprintf( 'Custom CSS updated (%s).', $mode ),
			array( 'log_id' => $log_id )
		);
	}

	/**
	 * get_custom_css
	 *
	 * @return array
	 */
	public function handle_get_custom_css() {
		$css = wp_get_custom_css( wp_get_theme()->get_stylesheet() );
		return $this->success( array( 'css' => $css ), sprintf( 'Custom CSS: %d chars.', strlen( $css ) ) );
	}

	/**
	 * create_menu
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_create_menu( array $args, array $context = array() ) {
		$name = sanitize_text_field( $args['menu_name'] );
		$menu_id = wp_create_nav_menu( $name );
		if ( is_wp_error( $menu_id ) ) {
			return $this->error( $menu_id->get_error_message() );
		}

		$added = 0;
		foreach ( (array) $args['items'] as $item ) {
			if ( empty( $item['title'] ) || empty( $item['url'] ) ) {
				continue;
			}
			$item_id = wp_update_nav_menu_item(
				$menu_id,
				0,
				array(
					'menu-item-title'  => sanitize_text_field( $item['title'] ),
					'menu-item-url'    => esc_url_raw( $item['url'] ),
					'menu-item-status' => 'publish',
				)
			);
			if ( ! is_wp_error( $item_id ) ) {
				++$added;
			}
		}

		$locations = get_theme_mod( 'nav_menu_locations', array() );
		if ( ! is_array( $locations ) ) {
			$locations = array();
		}
		if ( ! empty( $args['location'] ) ) {
			$locations[ sanitize_key( $args['location'] ) ] = (int) $menu_id;
			set_theme_mod( 'nav_menu_locations', $locations );
		}

		do_action( 'wp_update_nav_menu', $menu_id );

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'create_menu',
				'object_type'     => 'menu',
				'object_id'       => absint( $menu_id ),
				'summary'         => sprintf( 'Created menu "%s" with %d items', $name, $added ),
				'args'            => $args,
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array( 'menu_id' => (int) $menu_id, 'items_added' => $added ),
			sprintf( 'Menu "%s" created with %d items.', $name, $added ),
			array( 'log_id' => $log_id )
		);
	}

	/**
	 * add_menu_item
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_add_menu_item( array $args, array $context = array() ) {
		$menu_id = absint( $args['menu_id'] );
		$menu    = wp_get_nav_menu_object( $menu_id );
		if ( ! $menu ) {
			return $this->error( sprintf( 'Menu %d not found.', $menu_id ) );
		}

		$item_id = wp_update_nav_menu_item(
			$menu_id,
			0,
			array(
				'menu-item-title'  => sanitize_text_field( $args['title'] ),
				'menu-item-url'    => esc_url_raw( $args['url'] ),
				'menu-item-status' => 'publish',
			)
		);
		if ( is_wp_error( $item_id ) ) {
			return $this->error( $item_id->get_error_message() );
		}

		do_action( 'wp_update_nav_menu', $menu_id );

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'add_menu_item',
				'object_type'     => 'menu',
				'object_id'       => $menu_id,
				'summary'         => sprintf( 'Added menu item "%s"', $args['title'] ),
				'args'            => $args,
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array( 'item_id' => (int) $item_id ),
			sprintf( 'Menu item "%s" added to menu #%d.', $args['title'], $menu_id ),
			array( 'log_id' => $log_id )
		);
	}

	/**
	 * create_elementor_section
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_create_elementor_section( array $args, array $context = array() ) {
		if ( ! defined( 'ELEMENTOR_VERSION' ) ) {
			return $this->error( 'Elementor is not active on this site.' );
		}

		$title   = sanitize_text_field( $args['title'] );
		$status  = in_array( $args['status'] ?? 'draft', array( 'publish', 'draft' ), true ) ? $args['status'] : 'draft';
		$sections = is_array( $args['sections'] ) ? $args['sections'] : array();

		$post_id = wp_insert_post(
			array(
				'post_title'   => $title,
				'post_content' => '',
				'post_status'  => $status,
				'post_type'    => 'page',
				'post_author'  => get_current_user_id(),
			),
			true
		);
		if ( is_wp_error( $post_id ) ) {
			return $this->error( $post_id->get_error_message() );
		}

		$elementor_data = $this->build_elementor_data( $sections );
		update_post_meta( $post_id, '_elementor_edit_mode', 'builder' );
		update_post_meta( $post_id, '_elementor_template_type', 'wp-page' );
		update_post_meta( $post_id, '_elementor_data', wp_slash( wp_json_encode( $elementor_data ) ) );

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'create_elementor_section',
				'object_type'     => 'post',
				'object_id'       => $post_id,
				'summary'         => sprintf( 'Created Elementor page "%s" (#%d)', $title, $post_id ),
				'args'            => array( 'sections' => count( $sections ) ),
				'after_state'     => $this->plugin->get( 'snapshots' )->capture( 'post', $post_id ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array(
				'post_id' => (int) $post_id,
				'url'     => get_permalink( $post_id ),
			),
			sprintf( 'Elementor page "%s" created (#%d).', $title, $post_id ),
			array( 'log_id' => $log_id, 'object_type' => 'post', 'object_id' => $post_id )
		);
	}

	/**
	 * Convert structured sections to Elementor _elementor_data format.
	 *
	 * @param array $sections Sections definition.
	 * @return array
	 */
	private function build_elementor_data( array $sections ) {
		$data = array();
		foreach ( $sections as $section ) {
			$columns = array();
			foreach ( (array) ( isset( $section['columns'] ) ? $section['columns'] : array() ) as $col ) {
				$widgets = array();
				foreach ( (array) ( isset( $col['widgets'] ) ? $col['widgets'] : array() ) as $widget ) {
					$type     = isset( $widget['type'] ) ? sanitize_key( $widget['type'] ) : 'text';
					$settings = isset( $widget['settings'] ) && is_array( $widget['settings'] ) ? $widget['settings'] : array();
					// Map friendly widget types to Elementor widget names.
					$map = array(
						'heading'  => 'heading',
						'text'     => 'text-editor',
						'button'   => 'button',
						'image'    => 'image',
						'divider'  => 'divider',
						'spacer'   => 'spacer',
					);
					$widgets[] = array(
						'id'       => substr( md5( wp_json_encode( $widget ) . microtime() ), 0, 7 ),
						'elType'   => 'widget',
						'settings' => $settings,
						'widgetType' => isset( $map[ $type ] ) ? $map[ $type ] : 'text-editor',
						'elements' => array(),
					);
				}
				$columns[] = array(
					'id'       => substr( md5( wp_json_encode( $col ) . microtime() ), 0, 7 ),
					'elType'   => 'column',
					'settings' => array( '_column_size' => isset( $col['width'] ) ? absint( $col['width'] ) : 100 ),
					'elements' => $widgets,
				);
			}
			$data[] = array(
				'id'       => substr( md5( wp_json_encode( $section ) . microtime() ), 0, 7 ),
				'elType'   => 'section',
				'settings' => isset( $section['settings'] ) && is_array( $section['settings'] ) ? $section['settings'] : array(),
				'elements' => $columns,
			);
		}
		return $data;
	}

	/**
	 * get_design_settings
	 *
	 * @return array
	 */
	public function handle_get_design_settings() {
		$theme = wp_get_theme();
		$data  = array(
			'custom_css'   => wp_get_custom_css( $theme->get_stylesheet() ),
			'block_theme'  => $theme->is_block_theme(),
			'custom_logo'  => absint( get_theme_mod( 'custom_logo' ) ),
			'header_textcolor' => get_theme_mod( 'header_textcolor' ),
			'background_color' => get_theme_mod( 'background_color' ),
			'supports'     => array(
				'custom-logo'   => current_theme_supports( 'custom-logo' ),
				'html5'         => current_theme_supports( 'html5' ),
				'align-wide'    => current_theme_supports( 'align-wide' ),
				'editor-styles' => current_theme_supports( 'editor-styles' ),
			),
			'global_styles' => wp_is_block_theme() ? 'available' : 'n/a',
		);
		return $this->success( $data, 'Design settings collected.' );
	}
}
